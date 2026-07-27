"""Home dashboard snapshot (Qt-free, offline-testable).

One screen answering the questions you actually open the app to ask: what is my
book worth, how did it move today, what income is coming, what moved most, and
is anything wrong. Nothing here is a new calculation — it assembles what
portfolio_analytics and dividends already compute, so a number on Home always
matches the tab it came from.

Pure and network-free: callers pass in already-fetched histories, the same
pattern as the other core modules.
"""
from __future__ import annotations

import pandas as pd

from tradelab.core import portfolio_analytics as pa
from tradelab.core import dividends as dv

# A holding that drops this much in a day is worth surfacing unprompted.
ATTENTION_DROP_PCT = -5.0

# The share of the book at which a single name is worth pointing out. Used for
# both the position-level and the look-through reading, so the two agree.
CONCENTRATION_PCT = 40.0


def _day_change(close: pd.Series):
    """(absolute, percent) move on the last bar, or (None, None)."""
    if close is None or close.shape[0] < 2:
        return None, None
    last, prev = float(close.iloc[-1]), float(close.iloc[-2])
    if not prev:
        return None, None
    return last - prev, (last - prev) / prev * 100.0


def movers(positions: list, histories: dict, target: str = None, fx: dict = None) -> list:
    """Each holding's move today, biggest absolute percentage move first.

    The percentage is the holding's own price move (native currency, so FX
    doesn't distort it); the dollar figure is that move applied to your share
    count, converted to the display currency.
    """
    out = []
    for pos in pa.aggregate_positions(positions):
        close = pa._close((histories or {}).get(pos["symbol"]))
        change, pct = _day_change(close)
        if pct is None:
            continue
        rate = pa._latest_rate(fx, pa.currency_of(pos["symbol"]), target)
        conv = rate if rate is not None else 1.0
        out.append({
            "symbol": pos["symbol"],
            "change_pct": pct,
            "change_value": change * pos["shares"] * conv,
            "last": float(close.iloc[-1]),
        })
    out.sort(key=lambda m: abs(m["change_pct"]), reverse=True)
    return out


def day_move(movers_rows: list):
    """The book's move today in the display currency: the sum of each holding's
    own move. None when nothing could be priced."""
    values = [m["change_value"] for m in movers_rows if m["change_value"] is not None]
    return sum(values) if values else None


def next_payment(dividend_rows: list, today=None):
    """The next dividend expected, as {symbol, month, name, amount}, based on the
    months each holding paid in over the past year. None when nothing pays."""
    now = pd.Timestamp(today) if today is not None else pd.Timestamp.today()
    best = None
    for h in dividend_rows or []:
        if not h.get("pays") or not h.get("months") or not h.get("annual_income"):
            continue
        per_payment = h["annual_income"] / len(h["months"])
        for month in h["months"]:
            # Months ahead of us in the calendar, wrapping into next year.
            ahead = (month - now.month) % 12
            if best is None or ahead < best["ahead"]:
                best = {"symbol": h["symbol"], "month": month,
                        "name": dv.MONTH_NAMES[month - 1],
                        "amount": per_payment, "ahead": ahead}
    return best


def attention(analytics: dict, dividend_summary: dict, movers_rows: list,
              look_through: dict = None) -> list:
    """Things worth knowing without being asked, most important first. Each item
    is {kind, text} where kind is 'warn' or 'info'."""
    items = []
    for m in movers_rows:
        if m["change_pct"] <= ATTENTION_DROP_PCT:
            items.append({"kind": "warn",
                          "text": f"{m['symbol']} is down {m['change_pct']:.1f}% today."})
    if analytics:
        if analytics.get("no_data"):
            items.append({"kind": "warn",
                          "text": "No price data for " + ", ".join(analytics["no_data"])
                                  + " — excluded from totals."})
        if analytics.get("fx_missing"):
            items.append({"kind": "warn",
                          "text": "No FX rate for " + ", ".join(analytics["fx_missing"])
                                  + " — shown in native currency."})
        conc = analytics.get("concentration") or {}
        largest = conc.get("largest_pct")
        if largest and largest >= CONCENTRATION_PCT:
            rows = analytics.get("holdings") or []
            name = rows[0]["symbol"] if rows else "one holding"
            items.append({"kind": "info",
                          "text": f"{name} is {largest:.0f}% of the book — concentrated."})
    # The same question asked of companies rather than positions. Only worth
    # saying when funds actually contribute to the total: otherwise it would
    # just restate the position-level line above.
    biggest = (look_through or {}).get("largest") or {}
    if (biggest.get("weight_pct") or 0) >= CONCENTRATION_PCT and biggest.get("fund_value"):
        direct_pct = (biggest["direct_value"] / look_through["total"] * 100.0
                      if look_through.get("total") else 0.0)
        via = ", ".join(biggest.get("via") or []) or "your funds"
        items.append({"kind": "info",
                      "text": f"{biggest['symbol']} is {biggest['weight_pct']:.0f}% of the book "
                              f"once funds are opened up — {direct_pct:.0f}% held directly, "
                              f"the rest inside {via}."})
    return items


# --- market context ---------------------------------------------------------
# Both of the following read numbers the Market tab already downloaded. Home
# formats them; it never fetches or recomputes anything of its own.

# The world board, in the order a Canadian book reads it: your own market first,
# then the US session that sets its tone, then the overnight tape. Names match
# tradelab.core.market.GLOBAL_INDICES; the short form is what fits on one line.
STRIP_INDICES = [("TSX Composite", "TSX"), ("S&P 500", "S&P 500"),
                 ("Nasdaq Composite", "Nasdaq"), ("FTSE 100", "FTSE"),
                 ("Nikkei 225", "Nikkei")]

# The macro instruments that actually move a Canadian book: the rate USD
# holdings translate through, the two commodities that dominate the TSX (energy
# and materials), and the yield every dividend payer is priced against.
MACRO_ROW = [("CAD=X", "USD/CAD", "fx"), ("CL=F", "Oil", "usd"),
             ("GC=F", "Gold", "usd"), ("^TNX", "US 10Y", "yield")]


def index_strip(indices: dict) -> list:
    """The world board as [{label, change_pct, text, directional}], skipping any
    index the market pass couldn't price.

    Percentages only: a level like 35,568 says nothing at a glance, the day's
    move does.
    """
    out = []
    for name, short in STRIP_INDICES:
        row = (indices or {}).get(name) or {}
        pct = row.get("change_pct")
        if pct is None:
            continue
        out.append({"label": short, "change_pct": float(pct),
                    "text": f"{short} {float(pct):+.1f}%", "directional": True})
    return out


def _prev_close(last, change_pct):
    """The prior close implied by a last price and its percentage change."""
    if last is None or change_pct is None:
        return None
    denom = 1.0 + change_pct / 100.0
    return (last / denom) if denom else None


def macro_row(macro: dict) -> list:
    """Currency, commodities and the 10-year as [{label, change_pct, text,
    directional}].

    Each is formatted the way its own market quotes it: FX to four decimals,
    commodities in dollars, and the 10-year as a yield whose move is in basis
    points — a 4.64% yield easing to 4.60% is "-4 bp", never "-0.9%".

    `directional` is False for the yield: green-for-up would imply rising rates
    are good news, and for a book of dividend payers they are usually the
    opposite. The number is stated; reading it is left to you.
    """
    out = []
    for symbol, label, kind in MACRO_ROW:
        row = (macro or {}).get(symbol) or {}
        last = row.get("last")
        if last is None:
            continue
        last, pct = float(last), row.get("change_pct")
        if kind == "fx":
            text = f"{label} {last:,.4f}"
        elif kind == "yield":
            text = f"{label} {last:,.2f}%"
        else:
            text = f"{label} ${last:,.0f}" if last >= 1000 else f"{label} ${last:,.2f}"
        if pct is not None:
            if kind == "yield":
                prev = _prev_close(last, pct)
                if prev is not None:
                    text += f" {(last - prev) * 100.0:+.0f} bp"
            else:
                text += f" {float(pct):+.1f}%"
        out.append({"label": label, "text": text, "directional": kind != "yield",
                    "change_pct": None if pct is None else float(pct)})
    return out


def summarize(positions: list, histories: dict, dividends: dict = None,
              benchmark_df=None, benchmark_symbol: str = "SPY",
              target_currency: str = None, fx: dict = None,
              market_read: dict = None, compositions: dict = None,
              today=None) -> dict:
    """Everything the Home tab renders. Reuses portfolio_analytics and dividends
    so every figure agrees with its own tab."""
    if not positions:
        return {"has_positions": False, "currency": target_currency,
                "analytics": None, "income": None, "movers": [], "attention": [],
                "day_change": None, "next_payment": None,
                "market_read": market_read, "look_through": None,
                "text": "No holdings yet — add positions in the Portfolio tab, "
                        "or import them from IBKR."}

    analytics = pa.summarize(positions, histories, benchmark_df=benchmark_df,
                             benchmark_symbol=benchmark_symbol,
                             target_currency=target_currency, fx=fx)
    prices = {}
    for pos in pa.aggregate_positions(positions):
        close = pa._close((histories or {}).get(pos["symbol"]))
        if close is not None and not close.empty:
            prices[pos["symbol"]] = float(close.iloc[-1])
    income = dv.summarize(positions, dividends or {}, prices,
                          target_currency=target_currency, fx=fx, today=today)

    rows = movers(positions, histories, target_currency, fx)
    # Company-level exposure, when fund compositions were fetched. Home only
    # reads the headline from it; the full breakdown lives on Analytics.
    look = pa.look_through(analytics["holdings"], compositions) if compositions else None
    result = {
        "has_positions": True,
        "currency": target_currency,
        "analytics": analytics,
        "income": income,
        "movers": rows,
        "day_change": day_move(rows),
        "next_payment": next_payment(income.get("holdings"), today),
        "attention": attention(analytics, income, rows, look),
        "market_read": market_read,
        "look_through": look,
    }
    result["text"] = _headline(result)
    return result


def _headline(r: dict) -> str:
    a = r["analytics"] or {}
    ccy = f" {r['currency']}" if r.get("currency") else ""
    value = a.get("total_value")
    parts = [f"Your book is worth ${value:,.0f}{ccy}" if value else "Book value unavailable"]
    day = r.get("day_change")
    if day is not None:
        direction = "up" if day >= 0 else "down"
        parts.append(f"{direction} ${abs(day):,.0f} today")
    unreal = a.get("total_unrealized")
    if unreal is not None and a.get("total_unrealized_pct") is not None:
        parts.append(f"unrealized {unreal:+,.0f} ({a['total_unrealized_pct']:+.1f}%)")
    income = (r.get("income") or {}).get("total_annual_income")
    if income:
        parts.append(f"paying ${income:,.0f}{ccy} a year in dividends")
    return " · ".join(parts) + "."
