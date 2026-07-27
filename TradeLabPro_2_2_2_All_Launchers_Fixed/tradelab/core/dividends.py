"""Dividend income analysis (Qt-free, offline-testable).

What an income-oriented book actually pays you. From each holding's dividend
history plus its share count this derives the numbers a dividend investor
reviews: annual income per holding and for the book, the yield on what you
*paid* versus the yield at today's price, how often each name pays, whether its
payout has been growing, and which months the money lands in.

Two income figures, deliberately kept separate because they answer different
questions:
  * **TTM** — what was actually paid over the last 12 months (a historical fact).
  * **Forward rate** — the most recent payment annualized at its frequency (the
    current run rate, which reflects a recent raise or cut that TTM still averages
    away).

Currency follows the same model as portfolio_analytics: per-share amounts stay in
the holding's native currency, while income totals are reported in the target
currency (e.g. CAD). Yields are ratios of two native numbers, so they are
currency-neutral either way.

Pure and network-free — callers pass in already-fetched dividend histories, the
same pattern as core/market.py, core/coach.py and core/seasonality.py.
"""
from __future__ import annotations

import pandas as pd

from tradelab.core.portfolio_analytics import (currency_of, _latest_rate,
                                               aggregate_positions)

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Median days between payments -> payments per year. Bounds are generous because
# real schedules drift by a few days around holidays.
_FREQUENCY_BANDS = [
    (45, 12, "Monthly"),
    (75, 6, "Bi-monthly"),
    (135, 4, "Quarterly"),
    (250, 2, "Semi-annual"),
    (10_000, 1, "Annual"),
]


def _clean(divs) -> pd.Series:
    """A numeric, date-indexed, tz-naive dividend series (possibly empty)."""
    if divs is None or getattr(divs, "empty", True):
        return pd.Series(dtype=float)
    s = pd.to_numeric(divs, errors="coerce").dropna()
    if s.empty:
        return pd.Series(dtype=float)
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index, errors="coerce")
        s = s[s.index.notna()]
    try:
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return s[s > 0].sort_index()


def _asof(today=None) -> pd.Timestamp:
    return pd.Timestamp(today) if today is not None else pd.Timestamp.today().normalize()


def detect_frequency(divs, today=None) -> dict:
    """How often this name pays: {'per_year': int|None, 'label': str}. Measured
    from the median gap between the last ~3 years of payments, so one irregular
    special dividend doesn't skew it."""
    s = _clean(divs)
    if s.shape[0] < 2:
        return {"per_year": None, "label": "—" if s.empty else "Irregular"}
    recent = s[s.index >= _asof(today) - pd.DateOffset(years=3)]
    if recent.shape[0] < 2:
        recent = s
    gap = float(pd.Series(recent.index).diff().dt.days.dropna().median())
    for max_days, per_year, label in _FREQUENCY_BANDS:
        if gap <= max_days:
            return {"per_year": per_year, "label": label}
    return {"per_year": 1, "label": "Annual"}


def ttm_per_share(divs, today=None):
    """Dividend per share actually paid over the last 12 months, or None when
    there is no dividend history at all."""
    s = _clean(divs)
    if s.empty:
        return None
    end = _asof(today)
    window = s[(s.index > end - pd.DateOffset(years=1)) & (s.index <= end)]
    return float(window.sum())


def forward_per_share(divs, today=None):
    """Annualized run rate per share: the most recent payment x its frequency.
    None when the frequency can't be established (a single payment ever)."""
    s = _clean(divs)
    if s.empty:
        return None
    freq = detect_frequency(s, today)["per_year"]
    if not freq:
        return None
    return float(s.iloc[-1]) * freq


def growth_pct(divs, today=None):
    """Year-over-year growth of the dividend per share, as a %.

    Compares the **average payment size** of the last 12 months against the 12
    months before it — NOT the window totals. A trailing-year window often holds
    a different number of payments than the prior one purely because of where
    the boundary falls (a quarterly payer can show 3 vs 4), which made a raising
    dividend look like a deep cut. Averaging per payment removes that artifact.
    None without payments in both years.
    """
    s = _clean(divs)
    if s.empty:
        return None
    end = _asof(today)
    this_year = s[(s.index > end - pd.DateOffset(years=1)) & (s.index <= end)]
    prior = s[(s.index > end - pd.DateOffset(years=2))
              & (s.index <= end - pd.DateOffset(years=1))]
    if this_year.empty or prior.empty:
        return None
    this_avg, prior_avg = float(this_year.mean()), float(prior.mean())
    if not prior_avg:
        return None
    return float((this_avg / prior_avg - 1.0) * 100.0)


def payment_months(divs, today=None) -> list:
    """Which calendar months this name paid in over the last 12 months (1–12),
    which is the best available guide to when the next year's payments land."""
    s = _clean(divs)
    if s.empty:
        return []
    end = _asof(today)
    window = s[(s.index > end - pd.DateOffset(years=1)) & (s.index <= end)]
    return sorted({int(d.month) for d in window.index})


def holding_income(position: dict, divs, price=None, target: str = None,
                   fx: dict = None, today=None) -> dict:
    """Income figures for one holding.

    `position` carries symbol / shares / avg_entry (native per-share cost).
    Per-share amounts stay native; `annual_income` and `ttm_income` are converted
    to `target` when an FX rate is available. Yields are native-over-native, so
    they are unaffected by the display currency.
    """
    symbol = str(position.get("symbol", "")).upper()
    shares = float(position.get("shares", 0) or 0)
    avg_entry = float(position.get("avg_entry", 0) or 0)
    cur = currency_of(symbol)
    rate = _latest_rate(fx, cur, target)
    conv = rate if rate is not None else 1.0

    s = _clean(divs)
    freq = detect_frequency(s, today)
    fwd = forward_per_share(s, today)
    ttm = ttm_per_share(s, today)
    # The forward run rate is the projection; fall back to TTM when the
    # frequency is unknown (e.g. a single payment on record).
    per_share = fwd if fwd is not None else ttm

    annual = per_share * shares * conv if per_share is not None else None
    ttm_income = ttm * shares * conv if ttm is not None else None
    return {
        "symbol": symbol,
        "shares": shares,
        "currency": cur,
        "converted": target is None or cur == target or rate is not None,
        "pays": bool(per_share),
        "per_share_annual": per_share,          # native
        "per_share_ttm": ttm,                   # native
        "last_payment": float(s.iloc[-1]) if not s.empty else None,
        "last_date": s.index[-1].date() if not s.empty else None,
        "frequency": freq["per_year"],
        "frequency_label": freq["label"],
        "annual_income": annual,                # target currency
        "ttm_income": ttm_income,               # target currency
        "current_yield_pct": (per_share / price * 100.0)
                             if (per_share and price) else None,
        "yield_on_cost_pct": (per_share / avg_entry * 100.0)
                             if (per_share and avg_entry) else None,
        "growth_pct": growth_pct(s, today),
        "months": payment_months(s, today),
    }


def payment_calendar(rows: list) -> list:
    """Expected income by calendar month, spreading each holding's annual income
    across the months it actually paid in over the past year. Returns 12 dicts
    (month number, short name, amount, contributing symbols)."""
    months = [{"month": m + 1, "name": MONTHS_SHORT[m], "amount": 0.0,
               "symbols": []} for m in range(12)]
    for h in rows:
        income, paid_in = h.get("annual_income"), h.get("months") or []
        if not income or not paid_in:
            continue
        per_month = income / len(paid_in)
        for m in paid_in:
            months[m - 1]["amount"] += per_month
            months[m - 1]["symbols"].append(h["symbol"])
    return months


def summarize(positions: list, dividends: dict, prices: dict = None,
              target_currency: str = None, fx: dict = None, today=None) -> dict:
    """Everything the Dividends tab renders, computed offline.

    `dividends` maps symbol -> dividend Series; `prices` maps symbol -> latest
    native price (for current yield and the portfolio yield).
    """
    prices = prices or {}
    rows = []
    for pos in aggregate_positions(positions):
        rows.append(holding_income(pos, (dividends or {}).get(pos["symbol"]),
                                   price=prices.get(pos["symbol"]),
                                   target=target_currency, fx=fx, today=today))
    rows.sort(key=lambda h: (h["annual_income"] or 0), reverse=True)

    payers = [h for h in rows if h["pays"]]
    total_annual = sum(h["annual_income"] for h in payers if h["annual_income"])
    total_ttm = sum(h["ttm_income"] for h in payers if h["ttm_income"])

    # Portfolio yield needs market value in the same currency as the income.
    market_value = 0.0
    cost_value = 0.0
    for h in rows:
        price = prices.get(h["symbol"])
        rate = _latest_rate(fx, h["currency"], target_currency)
        conv = rate if rate is not None else 1.0
        if price:
            market_value += price * h["shares"] * conv
        pos = next((p for p in aggregate_positions(positions)
                    if p["symbol"] == h["symbol"]), None)
        if pos and pos.get("avg_entry"):
            cost_value += pos["avg_entry"] * h["shares"] * conv

    result = {
        "holdings": rows,
        "total_annual_income": total_annual if payers else None,
        "total_ttm_income": total_ttm if payers else None,
        "monthly_average": (total_annual / 12.0) if payers and total_annual else None,
        "portfolio_yield_pct": (total_annual / market_value * 100.0)
                               if (total_annual and market_value) else None,
        "portfolio_yield_on_cost_pct": (total_annual / cost_value * 100.0)
                                       if (total_annual and cost_value) else None,
        "calendar": payment_calendar(rows),
        "payers": len(payers),
        "non_payers": sorted(h["symbol"] for h in rows if not h["pays"]),
        "currency": target_currency,
        "fx_missing": sorted({h["currency"] for h in rows
                              if target_currency and not h["converted"]}),
    }
    result["text"] = _summary_text(result)
    return result


def _summary_text(r: dict) -> str:
    if not r["holdings"]:
        return "No positions yet — add holdings in the Portfolio tab, then refresh."
    if not r["payers"]:
        return "None of your holdings currently pay a dividend."
    ccy = f" {r['currency']}" if r.get("currency") else ""
    parts = [f"{r['payers']} of {len(r['holdings'])} holdings pay dividends",
             f"about ${r['total_annual_income']:,.0f}{ccy} a year "
             f"(${r['monthly_average']:,.0f}{ccy}/month average)"]
    if r["portfolio_yield_pct"] is not None:
        seg = f"portfolio yield {r['portfolio_yield_pct']:.2f}%"
        if r["portfolio_yield_on_cost_pct"] is not None:
            seg += f" ({r['portfolio_yield_on_cost_pct']:.2f}% on cost)"
        parts.append(seg)
    return " · ".join(parts) + "."
