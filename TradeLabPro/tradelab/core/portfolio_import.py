"""Import current portfolio *positions* from Interactive Brokers (read-only).

The Journal's IBKR import pulls *trades* (round-trips); this pulls your *open
positions* — the holdings themselves — so they can populate the Portfolio tab and
be analysed. Two sources, mirroring the Journal:

* an IBKR **Flex/Activity report** you export as XML or CSV (`parse_ibkr_positions`);
* a direct **Flex Web Service** pull (`fetch_ibkr_holdings`), reusing the same
  read-only token + query id the Journal uses — a single Flex query that includes
  the *Open Positions* section serves both.

When the report also includes its *Cash Report* section, the cash per currency
comes with the positions (`parse_ibkr_cash`).

Read-only throughout: this reads what you hold, it never logs in to trade, routes
orders, or moves funds — consistent with the app's simulated-only safety model.
Pure/parsing functions are Qt-free and network-free (the fetch is injectable), so
they're unit-testable offline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


# IBKR reports bare local tickers; Yahoo (the app's price source) needs an
# exchange suffix for non-US listings and a dash for class shares. Map the
# IBKR listing exchange -> Yahoo suffix for the common venues.
_EXCHANGE_SUFFIX = {
    "TSE": ".TO", "TSX": ".TO", "TSENMS": ".TO",          # Toronto
    "VENTURE": ".V", "TSXV": ".V",                          # TSX Venture
    "LSE": ".L", "LSEETF": ".L", "LSEIOB1": ".L",           # London
    "IBIS": ".DE", "IBIS2": ".DE", "XETRA": ".DE",          # Xetra
    "FWB": ".F", "SWB": ".SG",                              # Frankfurt / Stuttgart
    "SBF": ".PA", "AEB": ".AS", "BM": ".MC", "BVME": ".MI",  # Paris/Amsterdam/Madrid/Milan
    "EBS": ".SW", "SWX": ".SW", "VSE": ".VI",               # Swiss / Vienna
    "ASX": ".AX", "SEHK": ".HK", "TSEJ": ".T", "SGX": ".SI",  # Sydney/HK/Tokyo/Singapore
}
_US_EXCHANGES = {"NYSE", "NASDAQ", "NASDAQ.NMS", "NMS", "ARCA", "AMEX", "BATS",
                 "ISLAND", "PINK", "IEX", "PSE", "CBOE", "NYSENAT", "DRCTEDGE", "VALUE"}
# Fallback when no exchange is given (e.g. a CSV that only carries currency).
_CURRENCY_SUFFIX = {"CAD": ".TO", "GBP": ".L"}
_YF_SUFFIXES = tuple(sorted(set(_EXCHANGE_SUFFIX.values()) | {".V", ".TO", ".L"}))


def _to_yahoo_symbol(symbol, exchange=None, currency=None) -> str:
    """Translate an IBKR ticker to the Yahoo-Finance form the app prices with.

    - Already-suffixed symbols (``XDIV.TO``) are left alone.
    - Non-US listings get an exchange suffix from the listing exchange, or from
      the currency when the exchange is absent (``XDIV`` on TSE / CAD -> ``XDIV.TO``).
    - US class shares use Yahoo's dash form (``BRK B`` / ``BRK.B`` -> ``BRK-B``).
    """
    raw = str(symbol or "").strip().upper()
    if not raw:
        return raw
    if raw.endswith(_YF_SUFFIXES):          # already Yahoo-formatted
        return raw
    ex = str(exchange or "").strip().upper()
    cur = str(currency or "").strip().upper()
    base = raw.replace(" ", "-").replace(".", "-")   # class-share separator -> dash
    if ex in _EXCHANGE_SUFFIX:
        return base + _EXCHANGE_SUFFIX[ex]
    if ex in _US_EXCHANGES:
        return base
    # Exchange missing or unrecognized: fall back to the currency (a CAD account
    # whose CSV carries no exchange column still maps to .TO).
    if cur in _CURRENCY_SUFFIX:
        return base + _CURRENCY_SUFFIX[cur]
    return base


def _num(value):
    """Best-effort float from an IBKR field (handles thousands commas / blanks)."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _entry_from(price, cost_basis, quantity, multiplier):
    """Per-share entry price from whichever fields IBKR provided: the explicit
    cost-basis price, else total cost basis / (qty x multiplier), else 0."""
    p = _num(price)
    if p is not None:
        return p
    cb = _num(cost_basis)
    denom = (quantity or 0) * (multiplier or 1)
    if cb is not None and denom:
        return cb / denom
    return 0.0


def parse_ibkr_positions_xml(text: str) -> list:
    """Parse `<OpenPosition>` rows from a Flex XML report into position dicts:
    {symbol, shares, entry_price}. Shares carry their sign (short = negative)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except Exception:
        return []
    out = []
    for e in root.iter("OpenPosition"):
        a = e.attrib
        raw = a.get("symbol") or a.get("underlyingSymbol") or ""
        qty = _num(a.get("position"))
        if not raw.strip() or not qty:
            continue
        symbol = _to_yahoo_symbol(raw, a.get("listingExchange") or a.get("exchange"),
                                  a.get("currency"))
        mult = _num(a.get("multiplier")) or 1.0
        entry = _entry_from(a.get("costBasisPrice") or a.get("openPrice"),
                            a.get("costBasisMoney"), qty, mult)
        out.append({"symbol": symbol, "shares": qty, "entry_price": entry})
    return _merge(out)


def _col(header, *names):
    low = {str(h).strip().lower(): i for i, h in enumerate(header)}
    for n in names:
        if n in low:
            return low[n]
    return None


def parse_ibkr_positions_csv(text: str) -> list:
    """Parse open positions from an IBKR CSV export — either the sectioned
    Activity Statement (`Open Positions,Header/Data,...`) or a flat positions
    Flex CSV (a header row + rows)."""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    out = []

    # --- Activity Statement (sectioned) ---
    section = [r for r in rows if r and str(r[0]).strip() == "Open Positions"]
    if section:
        header = next((r for r in section if len(r) > 1 and str(r[1]).strip() == "Header"), None)
        if header:
            disc_i = _col(header, "datadiscriminator")
            sym_i = _col(header, "symbol")
            qty_i = _col(header, "quantity", "position")
            px_i = _col(header, "cost price", "costbasisprice", "costprice")
            cur_i = _col(header, "currency")
            ex_i = _col(header, "listing exchange", "listingexchange", "exchange")
            has_summary = any(len(r) > (disc_i or 0) and disc_i is not None
                              and str(r[disc_i]).strip() == "Summary"
                              for r in section if len(r) > 1 and str(r[1]).strip() == "Data")
            for r in section:
                if len(r) < 2 or str(r[1]).strip() != "Data":
                    continue
                # Prefer per-symbol Summary rows when present (avoids double-counting lots).
                if has_summary and disc_i is not None and disc_i < len(r) \
                        and str(r[disc_i]).strip() != "Summary":
                    continue
                if None in (sym_i, qty_i) or max(sym_i, qty_i) >= len(r):
                    continue
                raw = str(r[sym_i]).strip()
                if not raw or raw.lower().startswith("total"):
                    continue
                qty = _num(r[qty_i])
                if not qty:
                    continue
                cur = r[cur_i] if (cur_i is not None and cur_i < len(r)) else None
                ex = r[ex_i] if (ex_i is not None and ex_i < len(r)) else None
                price = r[px_i] if (px_i is not None and px_i < len(r)) else None
                out.append({"symbol": _to_yahoo_symbol(raw, ex, cur), "shares": qty,
                            "entry_price": _entry_from(price, None, qty, 1)})
        return _merge(out)

    # --- flat Flex CSV (header row 0) ---
    header = rows[0]
    sym_i = _col(header, "symbol", "underlyingsymbol")
    qty_i = _col(header, "position", "quantity")
    px_i = _col(header, "costbasisprice", "cost price", "openprice")
    cb_i = _col(header, "costbasismoney", "cost basis")
    mult_i = _col(header, "multiplier")
    if None in (sym_i, qty_i):
        return []
    cur_i = _col(header, "currency")
    ex_i = _col(header, "listingexchange", "listing exchange", "exchange")
    for r in rows[1:]:
        if not r or max(sym_i, qty_i) >= len(r):
            continue
        raw = str(r[sym_i]).strip()
        qty = _num(r[qty_i])
        if not raw or not qty:
            continue
        mult = _num(r[mult_i]) if (mult_i is not None and mult_i < len(r)) else 1.0
        price = r[px_i] if (px_i is not None and px_i < len(r)) else None
        cb = r[cb_i] if (cb_i is not None and cb_i < len(r)) else None
        cur = r[cur_i] if (cur_i is not None and cur_i < len(r)) else None
        ex = r[ex_i] if (ex_i is not None and ex_i < len(r)) else None
        out.append({"symbol": _to_yahoo_symbol(raw, ex, cur), "shares": qty,
                    "entry_price": _entry_from(price, cb, qty, mult or 1.0)})
    return _merge(out)


def _merge(positions: list) -> list:
    """Combine duplicate symbols (multiple lots) into one holding, summing shares
    and cost-weighting the entry price."""
    agg: dict[str, dict] = {}
    for p in positions:
        sym = p["symbol"]
        a = agg.setdefault(sym, {"symbol": sym, "shares": 0.0, "cost": 0.0})
        a["shares"] += p["shares"]
        a["cost"] += p["shares"] * (p["entry_price"] or 0.0)
    out = []
    for a in agg.values():
        sh = a["shares"]
        out.append({"symbol": a["symbol"], "shares": sh,
                    "entry_price": (a["cost"] / sh) if sh else 0.0})
    return out


def parse_ibkr_positions(text: str) -> list:
    """Parse positions from a report, trying XML first then CSV."""
    return parse_ibkr_positions_xml(text) or parse_ibkr_positions_csv(text)


# --- cash -------------------------------------------------------------------
#
# The same report can carry what the account holds in cash, per currency: the
# Flex XML's Cash Report section (`<CashReportCurrency currency="CAD"
# endingCash="..."/>`) and the Activity Statement's "Cash Report" rows labelled
# "Ending Cash". Each also has a base-currency summary that restates the other
# currencies converted; counting it as well would count the cash twice.

_BASE_SUMMARY = {"BASE_SUMMARY", "BASE CURRENCY SUMMARY", "BASE"}


def _add_cash(out: dict, currency, amount) -> None:
    cur = str(currency or "").strip().upper()
    value = _num(amount)
    if cur and cur not in _BASE_SUMMARY and value is not None:
        out[cur] = out.get(cur, 0.0) + value


def parse_ibkr_cash_xml(text: str) -> dict:
    """Ending cash per currency from a Flex XML report, {currency: amount}.
    Empty when the report has no Cash Report section."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except Exception:
        return {}
    out: dict = {}
    for e in root.iter("CashReportCurrency"):
        _add_cash(out, e.attrib.get("currency"), e.attrib.get("endingCash"))
    return out


def parse_ibkr_cash_csv(text: str) -> dict:
    """Ending cash per currency from an Activity Statement CSV's Cash Report
    section, its columns found by their headings. Empty without one."""
    import csv
    import io
    rows = [r for r in csv.reader(io.StringIO(text)) if r and str(r[0]).strip() == "Cash Report"]
    header = next((r for r in rows if len(r) > 1 and str(r[1]).strip() == "Header"), None)
    if not header:
        return {}
    label_i = _col(header, "currency summary")
    cur_i = _col(header, "currency")
    total_i = _col(header, "total")
    if None in (label_i, cur_i, total_i):
        return {}
    out: dict = {}
    for r in rows:
        if len(r) <= max(label_i, cur_i, total_i) or str(r[1]).strip() != "Data":
            continue
        if str(r[label_i]).strip().lower() == "ending cash":
            _add_cash(out, r[cur_i], r[total_i])
    return out


def parse_ibkr_cash(text: str) -> dict:
    """Cash per currency from a report, trying XML first then CSV."""
    return parse_ibkr_cash_xml(text) or parse_ibkr_cash_csv(text)


def has_cash_section(text: str) -> bool:
    """Whether a report carries a Cash Report section at all - so an import
    that read no cash can tell "the query has no such section" (a setting in
    IBKR) from "the section is there and TradeLab could not read it" (a bug)."""
    import re
    text = text or ""
    return "<CashReport" in text or bool(re.search(r'^"?Cash Report"?,', text, re.MULTILINE))


RAW_POSITIONS_REPORT = "ibkr_positions_last.xml"


def keep_raw_report(text: str, folder) -> Optional[Path]:
    """Save the last Flex report as IBKR sent it, in the logs folder (on this PC
    only), so a section the import could not read can be looked at. Returns
    the path, or None if it could not be written."""
    try:
        out = Path(folder) / RAW_POSITIONS_REPORT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text or "", encoding="utf-8")
        return out
    except OSError:
        return None


# --- symbol resolution by cost-basis proximity ------------------------------
#
# IBKR reports bare tickers; when the exchange/currency fields are missing, a
# bare ticker can resolve to the wrong listing (e.g. US 'XDIV' at $30 instead of
# Toronto 'XDIV.TO' at $46), and some US names even have a Canadian CDR at the
# same ticker (US 'NVDA' $206 vs the 'NVDA.TO' CDR at $46). The one signal we
# always have is the cost basis: the *correct* listing trades near what you paid.
# So we probe the candidate listings and pick whichever price is closest (in log
# ratio) to the cost basis.

_RESOLVE_SUFFIXES = ("", ".TO", ".V")

_probe_cache: dict = {}


def _probe_close(symbol: str):
    """Latest real close for a symbol from Yahoo, or None if it has no such
    listing. Deliberately does NOT use the synthetic fallback — an unknown symbol
    must read as None here, not as fabricated data. Cached per process."""
    if symbol in _probe_cache:
        return _probe_cache[symbol]
    value = None
    try:
        import pandas as pd
        import yfinance as yf
        df = yf.download(symbol, period="5d", interval="1d", progress=False,
                         auto_adjust=False, threads=False)
        if df is not None and not getattr(df, "empty", True) and "Close" in df:
            c = df["Close"]
            if hasattr(c, "columns"):
                c = c.iloc[:, 0]
            c = pd.to_numeric(c, errors="coerce").dropna()
            if not c.empty:
                value = float(c.iloc[-1])
    except Exception:
        value = None
    _probe_cache[symbol] = value
    return value


def choose_symbol(base, cost_basis, price_of, candidates=_RESOLVE_SUFFIXES) -> str:
    """Pick the listing whose price best matches the cost basis. `price_of(sym)`
    returns a real last close or None. Returns the bare symbol unchanged when it
    already has a suffix, when there's no cost basis to compare, or when no
    candidate has data."""
    import math
    base = str(base or "").strip().upper()
    if not base or base.endswith(_YF_SUFFIXES):
        return base
    try:
        cb = float(cost_basis)
    except (TypeError, ValueError):
        cb = 0.0
    if cb <= 0:
        return base
    best, best_score = base, None
    for suf in candidates:
        cand = base + suf
        try:
            p = float(price_of(cand))
        except (TypeError, ValueError):
            continue
        if p <= 0:
            continue
        score = abs(math.log(p / cb))
        if best_score is None or score < best_score:
            best, best_score = cand, score
    return best


def resolve_positions(positions: list, probe=None) -> list:
    """Correct each position's symbol to the Yahoo listing closest to its cost
    basis (see choose_symbol). Network-bound (probes Yahoo) — call off the UI
    thread. `probe` is injectable for tests."""
    probe = probe or _probe_close
    resolved = [{**p, "symbol": choose_symbol(p.get("symbol"), p.get("entry_price"), probe)}
                for p in positions]
    return _merge(resolved)


def fetch_ibkr_positions(token: str, query_id: str, transport=None) -> list:
    """Pull the user's Flex report over the IBKR Flex Web Service and return its
    open positions. Reuses the Journal's read-only Flex fetch. `transport` is
    injectable for tests."""
    return fetch_ibkr_holdings(token, query_id, transport=transport)[0]


def fetch_ibkr_holdings(token: str, query_id: str, transport=None):
    """One Flex Web Service pull -> (open positions, cash per currency). The
    cash is empty when the query has no Cash Report section."""
    from tradelab.core.journal import fetch_ibkr_flex
    text = fetch_ibkr_flex(token, query_id, transport=transport)
    return parse_ibkr_positions(text), parse_ibkr_cash(text)
