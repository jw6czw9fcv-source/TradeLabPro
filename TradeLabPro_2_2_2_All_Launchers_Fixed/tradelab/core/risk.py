"""Risk & position-sizing (Qt-free, offline-testable).

Answers the trader's core money-management questions:

* **How many shares?** Given account equity, the % you're willing to risk, and
  your entry + stop, `size_position` returns the share count that puts exactly
  that much at risk - optionally capped by a max position size or buying power.
* **Where are my targets?** `r_targets` turns the stop distance (1R) into target
  prices and dollar gains at 1R / 2R / 3R…
* **How concentrated am I?** `sector_exposure` breaks a set of positions down by
  sector so you can see if you're over-weight one area.

All Qt / data-fetching lives in the panel; this module is pure math with an
injectable sector lookup.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional


def _norm_side(side: str) -> str:
    return "Short" if str(side).lower().startswith("s") else "Long"


@dataclass
class SizeResult:
    valid: bool
    reason: str = ""
    side: str = "Long"
    risk_amount: float = 0.0      # intended $ risk before any cap
    risk_per_share: float = 0.0
    shares: int = 0
    position_value: float = 0.0
    position_pct: float = 0.0     # position value as % of equity
    actual_risk: float = 0.0      # shares * risk_per_share (after caps/rounding)
    actual_risk_pct: float = 0.0  # actual risk as % of equity
    stop_pct: float = 0.0         # stop distance as % of entry
    capped_by: str = ""           # "", "max position %", or "buying power"


def size_position(equity: float, risk_pct: float, entry: float, stop: float,
                  side: str = "Long", risk_amount: Optional[float] = None,
                  max_position_pct: Optional[float] = None,
                  buying_power: Optional[float] = None) -> SizeResult:
    """Shares to trade so that a stop-out loses `risk_pct` of `equity` (or a
    fixed `risk_amount` if given). Optionally capped by a max position size
    (% of equity) and/or available buying power."""
    try:
        equity = float(equity); entry = float(entry); stop = float(stop)
    except Exception:
        return SizeResult(False, "Invalid numeric input.")
    side = _norm_side(side)
    if entry <= 0:
        return SizeResult(False, "Entry price must be positive.", side=side)
    rps = abs(entry - stop)
    if rps <= 0:
        return SizeResult(False, "Stop must be different from the entry.", side=side)

    if risk_amount is None:
        risk_amount = equity * (float(risk_pct) / 100.0)
    risk_amount = float(risk_amount)
    if risk_amount <= 0:
        return SizeResult(False, "Risk amount must be positive.", side=side)

    shares = int(math.floor(risk_amount / rps))
    capped_by = ""
    if max_position_pct:
        max_value = equity * float(max_position_pct) / 100.0
        if shares * entry > max_value:
            shares = int(math.floor(max_value / entry))
            capped_by = "max position %"
    if buying_power is not None:
        if shares * entry > float(buying_power):
            shares = int(math.floor(float(buying_power) / entry))
            capped_by = "buying power"

    position_value = shares * entry
    actual_risk = shares * rps
    return SizeResult(
        valid=shares > 0,
        reason="" if shares > 0 else "Risk is too small for even one share at this stop distance.",
        side=side,
        risk_amount=risk_amount,
        risk_per_share=rps,
        shares=shares,
        position_value=position_value,
        position_pct=(position_value / equity * 100.0) if equity else 0.0,
        actual_risk=actual_risk,
        actual_risk_pct=(actual_risk / equity * 100.0) if equity else 0.0,
        stop_pct=rps / entry * 100.0,
        capped_by=capped_by,
    )


@dataclass
class RTarget:
    r: float
    price: float
    pnl_per_share: float
    pnl: float          # for the sized position (0 if shares unknown)


def r_targets(entry: float, stop: float, side: str = "Long",
              multiples=(1.0, 2.0, 3.0), shares: int = 0) -> list:
    """Target prices at each R multiple. 1R = the stop distance; a long's
    targets are above entry, a short's below. `shares` fills in the dollar P&L
    for the sized position."""
    entry = float(entry); stop = float(stop)
    rps = abs(entry - stop)
    if entry <= 0 or rps <= 0:
        return []
    sign = 1 if _norm_side(side) == "Long" else -1
    out = []
    for r in multiples:
        r = float(r)
        price = entry + sign * r * rps
        pnl_ps = r * rps
        out.append(RTarget(r=r, price=price, pnl_per_share=pnl_ps, pnl=pnl_ps * shares))
    return out


def sector_exposure(positions: list, sector_of: Optional[Callable[[str], str]] = None):
    """Break positions down by sector.

    `positions`: dicts with either `market_value`, or `shares` + `price`.
    `sector_of(symbol) -> sector` defaults to the cached quote metadata.
    Returns ([(sector, value, pct_of_total), ...] sorted by value desc, total).
    """
    if sector_of is None:
        from tradelab.data.market_data import get_quote_meta
        def sector_of(symbol):
            return get_quote_meta(symbol).get("sector", "Unknown") or "Unknown"

    buckets: dict[str, float] = {}
    total = 0.0
    for p in positions:
        symbol = str(p.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        value = p.get("market_value")
        if value is None:
            value = float(p.get("shares", 0) or 0) * float(p.get("price", 0) or 0)
        value = abs(float(value))
        if value <= 0:
            continue
        sector = sector_of(symbol) or "Unknown"
        buckets[sector] = buckets.get(sector, 0.0) + value
        total += value

    rows = [(sector, value, (value / total * 100.0) if total else 0.0)
            for sector, value in buckets.items()]
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows, total
