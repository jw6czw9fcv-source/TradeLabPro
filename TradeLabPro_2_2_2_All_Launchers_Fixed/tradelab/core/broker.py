"""Phase 8: broker connectivity layer.

This module defines a broker abstraction plus a fully-local **paper trading**
implementation. It is deliberately Qt-free and price-source-injectable so it
is unit-testable offline.

Scope and safety
----------------
This layer implements **simulated (paper) trading only**: orders fill against a
local ledger, no real money moves, and nothing is routed to an external broker.
It intentionally does **not** place live orders or move real funds. The
abstract `Broker` interface is here so a real broker adapter (e.g. an IBKR
*paper-account* gateway connection) can be added later behind the same API - but
any such adapter must remain paper/simulated; live order routing is out of
scope for this app.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Sides / order types / statuses kept as plain strings for easy JSON round-trip.
BUY, SELL = "BUY", "SELL"
MARKET, LIMIT = "MARKET", "LIMIT"
PENDING, FILLED, CANCELLED, REJECTED = "PENDING", "FILLED", "CANCELLED", "REJECTED"


@dataclass
class Order:
    id: int
    symbol: str
    side: str                # BUY / SELL
    qty: float
    order_type: str          # MARKET / LIMIT
    limit_price: float | None = None
    status: str = PENDING
    filled_price: float | None = None
    filled_qty: float = 0.0
    created_at: float = field(default_factory=time.time)
    filled_at: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    qty: float               # signed: positive = long, negative = short
    avg_price: float         # average cost of the open position

    def market_value(self, price: float) -> float:
        return self.qty * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.qty

    def to_dict(self) -> dict:
        return asdict(self)


class Broker(ABC):
    """Abstract broker interface. A real (paper-account) adapter would
    implement the same surface; only PaperBroker is provided here."""

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def account_summary(self) -> dict: ...

    @abstractmethod
    def positions(self) -> list[Position]: ...

    @abstractmethod
    def orders(self) -> list[Order]: ...

    @abstractmethod
    def place_order(self, symbol: str, side: str, qty: float,
                    order_type: str = MARKET, limit_price: float | None = None) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: int) -> bool: ...


def _default_price_fn(symbol: str) -> float:
    """Last close via the app's market-data layer. Isolated so tests inject a
    deterministic price and never hit the network."""
    from tradelab.data.market_data import get_history
    df = get_history(symbol, "5d", "1d")
    if df is None or df.empty:
        raise BrokerError(f"No price available for {symbol}.")
    return float(df["Close"].iloc[-1])


class BrokerError(RuntimeError):
    """Raised on invalid paper-trading operations so the UI can show a
    friendly message."""


class PaperBroker(Broker):
    """A self-contained simulated broker: a cash balance, positions, an order
    book, and realized P&L, all in a local ledger. Market orders fill
    immediately at the injected price; limit orders rest until `poll()` sees a
    crossing price. Nothing leaves this process."""

    def __init__(self, starting_cash: float = 100_000.0, commission: float = 0.0,
                 price_fn=None, persist_path: str | Path | None = None):
        self.starting_cash = float(starting_cash)
        self.cash = float(starting_cash)
        self.commission = float(commission)
        self.realized_pnl = 0.0
        self._price_fn = price_fn or _default_price_fn
        self._positions: dict[str, Position] = {}
        self._orders: list[Order] = []
        self._next_id = 1
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path and self._persist_path.exists():
            self._load()

    # -- Broker interface --
    def is_connected(self) -> bool:
        return True  # local simulator is always "connected"

    def price(self, symbol: str) -> float:
        return float(self._price_fn(symbol))

    def account_summary(self) -> dict:
        positions = self.positions()
        unrealized = 0.0
        market_value = 0.0
        for p in positions:
            try:
                px = self.price(p.symbol)
            except Exception:
                px = p.avg_price
            unrealized += p.unrealized_pnl(px)
            market_value += p.market_value(px)
        equity = self.cash + market_value
        return {
            "cash": round(self.cash, 2),
            "positions_value": round(market_value, 2),
            "equity": round(equity, 2),
            "starting_cash": round(self.starting_cash, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(equity - self.starting_cash, 2),
            # Simple cash-account buying power (no margin simulated).
            "buying_power": round(max(self.cash, 0.0), 2),
        }

    def positions(self) -> list[Position]:
        return [p for p in self._positions.values() if abs(p.qty) > 1e-9]

    def orders(self) -> list[Order]:
        return list(self._orders)

    def place_order(self, symbol: str, side: str, qty: float,
                    order_type: str = MARKET, limit_price: float | None = None) -> Order:
        symbol = symbol.strip().upper()
        side = side.upper()
        order_type = order_type.upper()
        if side not in (BUY, SELL):
            raise BrokerError(f"Invalid side: {side}")
        if order_type not in (MARKET, LIMIT):
            raise BrokerError(f"Invalid order type: {order_type}")
        if qty is None or float(qty) <= 0:
            raise BrokerError("Quantity must be greater than zero.")
        if order_type == LIMIT and (limit_price is None or float(limit_price) <= 0):
            raise BrokerError("Limit orders require a positive limit price.")

        order = Order(id=self._next_id, symbol=symbol, side=side, qty=float(qty),
                      order_type=order_type,
                      limit_price=float(limit_price) if limit_price else None)
        self._next_id += 1
        self._orders.append(order)

        if order_type == MARKET:
            try:
                self._fill(order, self.price(symbol))
            except BrokerError as e:
                order.status = REJECTED
                order.note = str(e)
        # LIMIT orders stay PENDING until poll() crosses them.
        self._save()
        return order

    def cancel_order(self, order_id: int) -> bool:
        for o in self._orders:
            if o.id == order_id and o.status == PENDING:
                o.status = CANCELLED
                self._save()
                return True
        return False

    def poll(self):
        """Attempt to fill resting limit orders at the current price. BUY fills
        when price <= limit; SELL fills when price >= limit."""
        changed = False
        for o in self._orders:
            if o.status != PENDING or o.order_type != LIMIT:
                continue
            try:
                px = self.price(o.symbol)
            except Exception:
                continue
            if (o.side == BUY and px <= o.limit_price) or (o.side == SELL and px >= o.limit_price):
                self._fill(o, px)
                changed = True
        if changed:
            self._save()
        return changed

    def reset(self):
        """Wipe the paper account back to its starting cash."""
        self.cash = self.starting_cash
        self.realized_pnl = 0.0
        self._positions.clear()
        self._orders.clear()
        self._next_id = 1
        self._save()

    # -- internal fill accounting --
    def _fill(self, order: Order, price: float):
        signed = order.qty if order.side == BUY else -order.qty
        cost = signed * price
        commission = self.commission
        # Realize P&L on the portion of this fill that reduces an existing
        # opposite-side position.
        pos = self._positions.get(order.symbol)
        if pos and (pos.qty > 0) != (signed > 0) and abs(pos.qty) > 1e-9:
            closing = min(abs(signed), abs(pos.qty))
            direction = 1 if pos.qty > 0 else -1
            self.realized_pnl += (price - pos.avg_price) * closing * direction

        self._apply_position(order.symbol, signed, price)
        self.cash -= cost + commission
        order.status = FILLED
        order.filled_price = price
        order.filled_qty = order.qty
        order.filled_at = time.time()

    def _apply_position(self, symbol: str, signed_qty: float, price: float):
        pos = self._positions.get(symbol)
        if pos is None:
            self._positions[symbol] = Position(symbol=symbol, qty=signed_qty, avg_price=price)
            return
        new_qty = pos.qty + signed_qty
        if abs(new_qty) < 1e-9:
            # Fully closed.
            self._positions.pop(symbol, None)
            return
        if (pos.qty > 0) == (signed_qty > 0):
            # Adding to the same side -> weighted-average the cost.
            pos.avg_price = (pos.avg_price * pos.qty + price * signed_qty) / new_qty
        elif (new_qty > 0) != (pos.qty > 0):
            # Flipped through zero -> the remainder opens at the fill price.
            pos.avg_price = price
        # else: partial close on the same side keeps the original avg_price.
        pos.qty = new_qty

    # -- persistence (JSON; per-user runtime data, gitignored) --
    def _save(self):
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "starting_cash": self.starting_cash,
                "cash": self.cash,
                "commission": self.commission,
                "realized_pnl": self.realized_pnl,
                "next_id": self._next_id,
                "positions": [p.to_dict() for p in self._positions.values()],
                "orders": [o.to_dict() for o in self._orders],
            }
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass  # persistence is best-effort; never break trading on a disk error

    def _load(self):
        try:
            data = json.loads(self._persist_path.read_text())
        except Exception:
            return
        self.starting_cash = float(data.get("starting_cash", self.starting_cash))
        self.cash = float(data.get("cash", self.cash))
        self.commission = float(data.get("commission", self.commission))
        self.realized_pnl = float(data.get("realized_pnl", 0.0))
        self._next_id = int(data.get("next_id", 1))
        self._positions = {
            p["symbol"]: Position(symbol=p["symbol"], qty=float(p["qty"]),
                                  avg_price=float(p["avg_price"]))
            for p in data.get("positions", [])
        }
        self._orders = [Order(**o) for o in data.get("orders", [])]
