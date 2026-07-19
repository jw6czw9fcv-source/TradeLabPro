"""Trade journal (Qt-free, offline-testable).

A JournalEntry is one round-trip idea: a Long or Short position in a symbol
with an entry, an optional protective stop, tags/strategy/notes, and - once
closed - an exit. From those, the journal derives the numbers a trader
actually reviews: P&L, %, R-multiple (vs. the stop), holding period, and
aggregate stats (win rate, average win/loss, expectancy, profit factor,
average R) overall and broken down by strategy / tag / symbol.

It also pairs the paper broker's filled orders into position-level trades
(extract_trades_from_fills) so a session's paper trading can be imported
without retyping.

All Qt / persistence-as-UI lives in the panel; this module is pure data.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from tradelab.core.config import DATA_DIR

JOURNAL_PATH = DATA_DIR / "journal.json"

LONG, SHORT = "Long", "Short"


def _today() -> str:
    return date.today().isoformat()


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


@dataclass
class JournalEntry:
    symbol: str
    side: str = LONG                 # "Long" / "Short"
    qty: float = 0.0
    entry_price: float = 0.0
    entry_date: str = field(default_factory=_today)
    exit_price: Optional[float] = None    # None while the trade is open
    exit_date: Optional[str] = None
    stop: Optional[float] = None          # protective stop -> risk for R-multiple
    strategy: str = ""
    tags: list = field(default_factory=list)
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.symbol = (self.symbol or "").strip().upper()
        self.side = SHORT if str(self.side).lower().startswith("s") else LONG
        if isinstance(self.tags, str):
            self.tags = [t.strip() for t in self.tags.split(",") if t.strip()]

    # --- derived numbers --------------------------------------------------
    @property
    def direction(self) -> int:
        return -1 if self.side == SHORT else 1

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    @property
    def pnl(self) -> Optional[float]:
        """Realized P&L in dollars, or None while open."""
        if self.is_open:
            return None
        return (float(self.exit_price) - self.entry_price) * self.direction * self.qty

    @property
    def pnl_pct(self) -> Optional[float]:
        if self.is_open or not self.entry_price:
            return None
        return (float(self.exit_price) - self.entry_price) * self.direction / self.entry_price * 100.0

    @property
    def risk_per_share(self) -> Optional[float]:
        if self.stop is None:
            return None
        r = abs(self.entry_price - float(self.stop))
        return r if r > 1e-9 else None

    @property
    def r_multiple(self) -> Optional[float]:
        """Result in units of initial risk (needs a stop). +2R = made twice
        what was risked; -1R = a full stop-out."""
        rps = self.risk_per_share
        if self.is_open or rps is None:
            return None
        return (float(self.exit_price) - self.entry_price) * self.direction / rps

    @property
    def holding_days(self) -> Optional[int]:
        a, b = _parse_date(self.entry_date), _parse_date(self.exit_date)
        if a is None or b is None:
            return None
        return (b - a).days

    @property
    def is_win(self) -> Optional[bool]:
        p = self.pnl
        return None if p is None else p > 0

    def close(self, exit_price: float, exit_date: Optional[str] = None):
        self.exit_price = float(exit_price)
        self.exit_date = exit_date or _today()

    # --- serialization ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id, "symbol": self.symbol, "side": self.side, "qty": self.qty,
            "entry_price": self.entry_price, "entry_date": self.entry_date,
            "exit_price": self.exit_price, "exit_date": self.exit_date, "stop": self.stop,
            "strategy": self.strategy, "tags": list(self.tags), "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JournalEntry":
        entry = cls(
            symbol=data.get("symbol", ""), side=data.get("side", LONG),
            qty=float(data.get("qty", 0) or 0),
            entry_price=float(data.get("entry_price", 0) or 0),
            entry_date=data.get("entry_date") or _today(),
            exit_price=(float(data["exit_price"]) if data.get("exit_price") is not None else None),
            exit_date=data.get("exit_date"),
            stop=(float(data["stop"]) if data.get("stop") is not None else None),
            strategy=data.get("strategy", ""), tags=list(data.get("tags", []) or []),
            notes=data.get("notes", ""),
        )
        if data.get("id"):
            entry.id = data["id"]
        if data.get("created_at") is not None:
            entry.created_at = float(data["created_at"])
        return entry


# --- aggregate statistics ---------------------------------------------------

def summarize(entries: list) -> dict:
    """Aggregate stats over the CLOSED trades in `entries`."""
    closed = [e for e in entries if not e.is_open]
    wins = [e for e in closed if (e.pnl or 0) > 0]
    losses = [e for e in closed if (e.pnl or 0) < 0]
    gross_win = sum(e.pnl for e in wins)
    gross_loss = sum(e.pnl for e in losses)          # negative
    total_pnl = sum(e.pnl for e in closed)
    n = len(closed)
    win_rate = (len(wins) / n * 100.0) if n else 0.0
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    # Expectancy per trade (dollars): probability-weighted avg outcome.
    expectancy = (total_pnl / n) if n else 0.0
    profit_factor = (gross_win / abs(gross_loss)) if gross_loss else (float("inf") if gross_win else 0.0)
    r_values = [e.r_multiple for e in closed if e.r_multiple is not None]
    avg_r = (sum(r_values) / len(r_values)) if r_values else None
    return {
        "trades": len(entries),
        "open": len(entries) - n,
        "closed": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "avg_r": avg_r,
    }


def group_stats(entries: list, key: str = "strategy") -> list:
    """[(group_value, summary_dict), ...] ordered by total P&L descending.
    key = 'strategy' | 'symbol' | 'tag' (a trade contributes to each of its
    tags)."""
    buckets: dict[str, list] = {}
    for e in entries:
        if key == "tag":
            labels = e.tags or ["(untagged)"]
        else:
            labels = [getattr(e, key, "") or f"(no {key})"]
        for label in labels:
            buckets.setdefault(label, []).append(e)
    out = [(label, summarize(items)) for label, items in buckets.items()]
    out.sort(key=lambda kv: kv[1]["total_pnl"], reverse=True)
    return out


# --- import from paper broker fills -----------------------------------------

def extract_trades_from_fills(fills: list) -> list:
    """Pair a paper broker's filled orders into position-level trades.

    `fills` are order dicts (symbol, side BUY/SELL, filled_qty, filled_price,
    filled_at). Per symbol, walk fills in time order tracking the running
    signed position; each time the position returns to flat (or flips through
    zero) a closed JournalEntry is emitted with the size-weighted entry/exit.
    Any residual position becomes an open entry.
    """
    from collections import defaultdict
    by_symbol: dict[str, list] = defaultdict(list)
    for f in fills:
        if str(f.get("status", "FILLED")) != "FILLED":
            continue
        qty = float(f.get("filled_qty") or 0)
        price = f.get("filled_price")
        if qty <= 0 or price is None:
            continue
        by_symbol[str(f.get("symbol", "")).upper()].append(f)

    trades: list = []
    for symbol, group in by_symbol.items():
        group.sort(key=lambda f: f.get("filled_at") or 0)
        pos = 0.0            # signed open qty
        entry_px = 0.0       # size-weighted avg entry of the open position
        entry_at = None
        exit_notional = 0.0  # accumulated exit price*qty for the current trade
        exit_qty = 0.0
        for f in group:
            remaining = float(f["filled_qty"])
            fill_sign = 1 if f["side"] == "BUY" else -1
            price = float(f["filled_price"])
            at = f.get("filled_at")
            while remaining > 1e-12:
                if pos == 0 or (pos > 0) == (fill_sign > 0):
                    # Opening or adding to the position (size-weight the entry).
                    new_abs = abs(pos) + remaining
                    entry_px = (entry_px * abs(pos) + price * remaining) / new_abs
                    pos += fill_sign * remaining
                    if entry_at is None:
                        entry_at = at
                    remaining = 0.0
                else:
                    # Reducing / closing the position.
                    was_long = pos > 0
                    closing = min(remaining, abs(pos))
                    exit_notional += price * closing
                    exit_qty += closing
                    pos += (-1 if was_long else 1) * closing   # toward zero
                    remaining -= closing
                    if abs(pos) < 1e-9:
                        # Flat -> emit the completed round-trip trade.
                        trades.append(_make_closed_trade(
                            symbol, entry_px, exit_notional, exit_qty,
                            entry_at, at, was_long=was_long))
                        pos = 0.0; entry_px = 0.0; entry_at = None
                        exit_notional = 0.0; exit_qty = 0.0
                        # any leftover `remaining` opens a new (flipped) position
        if abs(pos) > 1e-9:
            trades.append(JournalEntry(
                symbol=symbol, side=LONG if pos > 0 else SHORT, qty=round(abs(pos), 6),
                entry_price=round(entry_px, 4),
                entry_date=_ts_to_date(entry_at)))
    return trades


def _ts_to_date(ts) -> str:
    try:
        return date.fromtimestamp(float(ts)).isoformat()
    except Exception:
        return _today()


def _make_closed_trade(symbol, entry_px, exit_notional, exit_qty, entry_at, exit_at, was_long) -> JournalEntry:
    e = JournalEntry(
        symbol=symbol, side=LONG if was_long else SHORT, qty=round(exit_qty, 6),
        entry_price=round(entry_px, 4), entry_date=_ts_to_date(entry_at))
    e.close(round(exit_notional / exit_qty, 4), _ts_to_date(exit_at))
    return e


# --- IBKR CSV import ---------------------------------------------------------

_IBKR_DT_FORMATS = (
    "%Y-%m-%d, %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    "%Y%m%d;%H%M%S", "%Y%m%d",
)


def _parse_ibkr_datetime(value) -> Optional[float]:
    """IBKR uses several date/time spellings; return a POSIX timestamp."""
    from datetime import datetime
    s = str(value or "").strip().strip('"')
    if not s:
        return None
    for fmt in _IBKR_DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).timestamp()
        except Exception:
            continue
    return None


def _to_fill(symbol, side, qty, price, at) -> Optional[dict]:
    try:
        qty = abs(float(qty))
        price = float(price)
    except Exception:
        return None
    symbol = str(symbol or "").strip().upper()
    if not symbol or qty <= 0 or price <= 0:
        return None
    return {"symbol": symbol, "side": "BUY" if side == "BUY" else "SELL",
            "filled_qty": qty, "filled_price": price, "filled_at": at, "status": "FILLED"}


def parse_ibkr_trades_csv(text: str) -> list:
    """Parse an IBKR trades CSV into fill dicts (compatible with
    extract_trades_from_fills). Handles both the flat **Flex Query** trades
    export (a header row + rows) and the sectioned **Activity Statement**
    export (rows beginning `Trades,Header,...` / `Trades,Data,...`). Side comes
    from a Buy/Sell column when present, else from the sign of Quantity.
    Only equity/stock rows are kept when an asset-class column is available.
    """
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    fills: list = []
    seq = 0  # fallback ordering when a datetime can't be parsed

    def col(header, *names):
        low = {str(h).strip().lower(): i for i, h in enumerate(header)}
        for n in names:
            if n in low:
                return low[n]
        return None

    # --- Activity Statement (sectioned) ---
    trade_rows = [r for r in rows if r and str(r[0]).strip() == "Trades"]
    if trade_rows:
        header = next((r for r in trade_rows if len(r) > 1 and str(r[1]).strip() == "Header"), None)
        if header:
            sym_i = col(header, "symbol")
            qty_i = col(header, "quantity")
            px_i = col(header, "t. price", "price", "tradeprice")
            dt_i = col(header, "date/time", "datetime", "date")
            ac_i = col(header, "asset category", "assetclass")
            for r in trade_rows:
                if len(r) < 2 or str(r[1]).strip() != "Data":
                    continue
                if ac_i is not None and ac_i < len(r) and "stock" not in str(r[ac_i]).lower():
                    continue
                if None in (sym_i, qty_i, px_i) or max(sym_i, qty_i, px_i) >= len(r):
                    continue
                try:
                    signed = float(str(r[qty_i]).replace(",", ""))
                except Exception:
                    continue
                at = _parse_ibkr_datetime(r[dt_i]) if (dt_i is not None and dt_i < len(r)) else None
                if at is None:
                    seq += 1; at = seq
                f = _to_fill(r[sym_i], "BUY" if signed > 0 else "SELL", signed, r[px_i], at)
                if f:
                    fills.append(f)
        return fills

    # --- flat Flex Query CSV (header row 0) ---
    header = rows[0]
    sym_i = col(header, "symbol", "underlyingsymbol")
    side_i = col(header, "buy/sell", "buysell")
    qty_i = col(header, "quantity")
    px_i = col(header, "tradeprice", "price", "t. price")
    dt_i = col(header, "datetime", "date/time", "tradedate", "date")
    ac_i = col(header, "assetclass", "asset category")
    if None in (sym_i, qty_i, px_i):
        return []
    for r in rows[1:]:
        if not r or max(sym_i, qty_i, px_i) >= len(r):
            continue
        if ac_i is not None and ac_i < len(r) and str(r[ac_i]).strip() and "stk" not in str(r[ac_i]).lower() and "stock" not in str(r[ac_i]).lower():
            continue
        try:
            qty_val = float(str(r[qty_i]).replace(",", ""))
        except Exception:
            continue
        if side_i is not None and side_i < len(r) and str(r[side_i]).strip():
            side = "BUY" if str(r[side_i]).strip().upper().startswith("B") else "SELL"
        else:
            side = "BUY" if qty_val > 0 else "SELL"
        at = _parse_ibkr_datetime(r[dt_i]) if (dt_i is not None and dt_i < len(r)) else None
        if at is None:
            seq += 1; at = seq
        f = _to_fill(r[sym_i], side, qty_val, r[px_i], at)
        if f:
            fills.append(f)
    return fills


# --- IBKR Flex Web Service (direct pull) ------------------------------------
#
# Read-only: fetches the user's own Flex Query report over HTTPS with a
# read-only Flex token. No login, no order routing, no funds - consistent with
# the app's simulated-only safety model. The token is the user's own read-only
# report token (stored locally by the UI, like the AI-Assist API key).

FLEX_SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
FLEX_GET_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"


def _http_get(url: str, timeout: int = 30) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "TradeLabPro/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _flex_text(root, tag):
    import xml.etree.ElementTree as ET  # noqa: F401
    el = root.find(tag)
    return el.text if el is not None else None


def _parse_flex_send(xml_text: str) -> tuple[str, str]:
    """From a SendRequest response, return (reference_code, get_statement_url).
    Raises RuntimeError with IBKR's message on a Fail status."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text)
    status = (_flex_text(root, "Status") or root.get("Status") or "").strip().lower()
    if status and status != "success":
        code = _flex_text(root, "ErrorCode") or "?"
        msg = _flex_text(root, "ErrorMessage") or "request failed"
        raise RuntimeError(f"IBKR Flex error {code}: {msg}")
    ref = _flex_text(root, "ReferenceCode")
    url = _flex_text(root, "Url") or FLEX_GET_URL
    if not ref:
        raise RuntimeError("IBKR Flex: no reference code returned (check token / query id).")
    return ref, url


def _flex_not_ready(stmt: str) -> bool:
    low = stmt.lower()
    return "statement generation in progress" in low or ">1019<" in stmt or ">1021<" in stmt


def _flex_raise_if_failed(stmt: str):
    low = stmt.replace(" ", "").lower()
    if "<status>fail" in low:
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(stmt)
            code = _flex_text(root, "ErrorCode") or "?"
            msg = _flex_text(root, "ErrorMessage") or "statement failed"
            raise RuntimeError(f"IBKR Flex error {code}: {msg}")
        except ET.ParseError:
            raise RuntimeError("IBKR Flex: statement request failed.")


def fetch_ibkr_flex(token: str, query_id: str, transport=None,
                    max_wait: float = 20.0, sleep: float = 1.0) -> str:
    """Run the two-step Flex Web Service exchange and return the report text.
    `transport(url) -> str` defaults to a plain HTTPS GET; inject a fake in
    tests. Retries GetStatement while IBKR reports the statement is still
    generating, up to `max_wait` seconds."""
    import time as _time
    transport = transport or _http_get
    token = str(token).strip()
    query_id = str(query_id).strip()
    if not token or not query_id:
        raise RuntimeError("A Flex token and query id are both required.")
    ref, url = _parse_flex_send(transport(f"{FLEX_SEND_URL}?t={token}&q={query_id}&v=3"))
    deadline = _time.time() + max_wait
    while True:
        stmt = transport(f"{url}?t={token}&q={ref}&v=3")
        if not _flex_not_ready(stmt):
            _flex_raise_if_failed(stmt)
            return stmt
        if _time.time() >= deadline:
            return stmt
        _time.sleep(sleep)


def parse_ibkr_flex_xml(text: str) -> list:
    """Parse a Flex Query XML report's <Trade> rows into fill dicts (stocks
    only). Side comes from buySell when present, else the sign of quantity."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except Exception:
        return []
    fills: list = []
    seq = 0
    for tr in root.iter("Trade"):
        a = tr.attrib
        asset = (a.get("assetCategory") or "").upper()
        if asset and asset != "STK":
            continue
        try:
            qty_val = float(str(a.get("quantity", "")).replace(",", ""))
        except Exception:
            continue
        buysell = (a.get("buySell") or "").upper()
        side = "BUY" if (buysell.startswith("B") if buysell else qty_val > 0) else "SELL"
        at = _parse_ibkr_datetime(a.get("dateTime") or a.get("tradeDate"))
        if at is None:
            seq += 1; at = seq
        f = _to_fill(a.get("symbol"), side, qty_val,
                     a.get("tradePrice") or a.get("price"), at)
        if f:
            fills.append(f)
    return fills


class Journal:
    """JSON-backed list of JournalEntry (data/journal.json, gitignored)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else JOURNAL_PATH
        self._entries: list = []
        self.load()

    def all(self) -> list:
        return list(self._entries)

    def get(self, entry_id: str) -> Optional[JournalEntry]:
        return next((e for e in self._entries if e.id == entry_id), None)

    def add(self, entry: JournalEntry) -> JournalEntry:
        self._entries.append(entry)
        self.save()
        return entry

    def remove(self, entry_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        changed = len(self._entries) != before
        if changed:
            self.save()
        return changed

    def close_trade(self, entry_id: str, exit_price: float, exit_date: Optional[str] = None) -> bool:
        e = self.get(entry_id)
        if e is None:
            return False
        e.close(exit_price, exit_date)
        self.save()
        return True

    def import_fills(self, fills: list) -> int:
        """Add trades extracted from paper broker fills; returns how many new
        trades were added (skips ones already imported by fingerprint)."""
        existing = {self._fingerprint(e) for e in self._entries}
        added = 0
        for trade in extract_trades_from_fills(fills):
            if self._fingerprint(trade) not in existing:
                self._entries.append(trade)
                existing.add(self._fingerprint(trade))
                added += 1
        if added:
            self.save()
        return added

    def import_ibkr_csv(self, path: str | Path) -> int:
        """Import trades from an IBKR CSV export (Flex Query or Activity
        Statement). Fills are paired into round-trips and de-duplicated the
        same way as paper-trading imports; returns the number of new trades."""
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        return self.import_fills(parse_ibkr_trades_csv(text))

    def import_ibkr_flex(self, token: str, query_id: str, transport=None) -> int:
        """Pull the user's Flex Query report over the IBKR Flex Web Service and
        import its trades (XML report, falling back to CSV). Read-only."""
        text = fetch_ibkr_flex(token, query_id, transport=transport)
        fills = parse_ibkr_flex_xml(text) or parse_ibkr_trades_csv(text)
        return self.import_fills(fills)

    @staticmethod
    def _fingerprint(e: JournalEntry):
        return (e.symbol, e.side, round(e.qty, 4), round(e.entry_price, 4),
                e.entry_date, e.exit_price, e.exit_date)

    def summary(self) -> dict:
        return summarize(self._entries)

    def load(self) -> list:
        self._entries = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._entries = [JournalEntry.from_dict(d) for d in data.get("entries", [])]
            except Exception:
                self._entries = []
        return self._entries

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"entries": [e.to_dict() for e in self._entries]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
