"""Seasonality analysis (Qt-free, offline-testable).

"Is this a historically strong month for the stock?" From a symbol's daily price
history this derives its calendar patterns — average return and win rate for each
of the 12 months and each weekday, plus a year-by-year performance table — so a
trader can see whether the current month has tended to be kind or cruel to a name
over its history.

Purely descriptive and backward-looking: seasonality summarizes what price *did*
in past calendars, it does not predict the next one. All functions are pure and
network-free (callers pass in already-fetched history), the same pattern as
core/market.py and core/coach.py, so they're unit-testable offline.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _close(df) -> pd.Series | None:
    """The numeric close series with a DatetimeIndex, or None if there isn't a
    usable one. Mirrors market._close_series (collapse a duplicated 2-D 'Close'
    from yfinance's MultiIndex flattening) and additionally guarantees the index
    is datetime so the calendar grouping below can't blow up."""
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        return None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    if close.empty:
        return None
    if not isinstance(close.index, pd.DatetimeIndex):
        close.index = pd.to_datetime(close.index, errors="coerce")
        close = close[close.index.notna()]
    return close if not close.empty else None


def monthly_return_series(df) -> pd.Series:
    """Month-over-month % returns, indexed by month-end date. Each point is the
    return from the prior month's last close to this month's last close."""
    close = _close(df)
    if close is None:
        return pd.Series(dtype=float)
    monthly = close.resample("ME").last().dropna()
    return (monthly.pct_change().dropna() * 100.0)


def _stat_row(label: str, values: pd.Series) -> dict:
    """Average / median / win-rate / best / worst over a set of period returns.
    Everything is None (not guessed) when there's nothing to measure."""
    n = int(values.shape[0])
    if n == 0:
        return {"label": label, "count": 0, "avg": None, "median": None,
                "win_rate": None, "best": None, "worst": None}
    return {
        "label": label,
        "count": n,
        "avg": float(values.mean()),
        "median": float(values.median()),
        "win_rate": float((values > 0).mean() * 100.0),
        "best": float(values.max()),
        "worst": float(values.min()),
    }


def monthly_stats(df) -> list:
    """One stat row per calendar month (Jan…Dec), each summarizing that month's
    returns across every year in the history."""
    r = monthly_return_series(df)
    out = []
    for m in range(1, 13):
        vals = r[r.index.month == m] if not r.empty else r
        out.append(_stat_row(MONTHS[m - 1], vals))
    return out


def weekday_stats(df) -> list:
    """One stat row per weekday (Mon…Fri) over daily returns — the day-of-week
    seasonality. Weekends are omitted (equity markets are closed)."""
    close = _close(df)
    if close is None:
        return [_stat_row(WEEKDAYS[d][:3], pd.Series(dtype=float)) for d in range(5)]
    r = (close.pct_change().dropna() * 100.0)
    return [_stat_row(WEEKDAYS[d][:3], r[r.index.dayofweek == d]) for d in range(5)]


def annual_returns(df) -> list:
    """Per-calendar-year performance: the return from the first to the last close
    within each year (intra-year, so a partial current year still reports)."""
    close = _close(df)
    if close is None:
        return []
    out = []
    for year, grp in close.groupby(close.index.year):
        if grp.shape[0] >= 2 and grp.iloc[0]:
            out.append({"year": int(year),
                        "return_pct": float((grp.iloc[-1] / grp.iloc[0] - 1.0) * 100.0),
                        "count": int(grp.shape[0])})
    return out


def years_covered(df) -> int:
    """How many distinct calendar years the history spans."""
    close = _close(df)
    if close is None:
        return 0
    return int(pd.Index(close.index.year).nunique())


def month_context(stats: list, month: int) -> dict:
    """The stat row for a given month number (1–12), plus a plain-English
    strength read of how that month has historically treated the stock."""
    row = dict(stats[month - 1]) if 1 <= month <= 12 and stats else _stat_row("", pd.Series(dtype=float))
    avg, wr, n = row.get("avg"), row.get("win_rate"), row.get("count", 0)
    if not n or avg is None:
        read = "no history yet"
    elif avg > 0.5 and (wr or 0) >= 55:
        read = "historically strong"
    elif avg < -0.5 and (wr or 0) <= 45:
        read = "historically weak"
    else:
        read = "historically mixed"
    row["read"] = read
    row["month_name"] = MONTH_NAMES[month - 1] if 1 <= month <= 12 else ""
    return row


def summarize(df, today: date | None = None) -> dict:
    """Everything the Seasonality tab renders, computed offline: the 12-month and
    weekday stat tables, the year-by-year returns, the best/worst months, and the
    current month's historical context."""
    stats = monthly_stats(df)
    measured = [s for s in stats if s["count"]]
    years = years_covered(df)
    result = {
        "months": stats,
        "weekdays": weekday_stats(df),
        "annual": annual_returns(df),
        "years": years,
        "best_month": None,
        "worst_month": None,
        "current": None,
        "text": "",
    }
    if not measured:
        result["text"] = ("Not enough price history to measure seasonality yet — "
                          "try a longer period.")
        return result

    best = max(measured, key=lambda s: s["avg"])
    worst = min(measured, key=lambda s: s["avg"])
    result["best_month"] = best
    result["worst_month"] = worst

    cur_month = (today or date.today()).month
    cur = month_context(stats, cur_month)
    result["current"] = cur

    if cur["count"]:
        result["text"] = (
            f"Over {years} year(s) of history, {cur['month_name']} has been "
            f"{cur['read']}: it averaged {cur['avg']:+.1f}% with a "
            f"{cur['win_rate']:.0f}% win rate ({cur['count']} occurrences). "
            f"Historically the strongest month is {MONTH_NAMES[MONTHS.index(best['label'])]} "
            f"({best['avg']:+.1f}%) and the weakest is "
            f"{MONTH_NAMES[MONTHS.index(worst['label'])]} ({worst['avg']:+.1f}%).")
    else:
        result["text"] = (
            f"Over {years} year(s) of history, the strongest month has been "
            f"{MONTH_NAMES[MONTHS.index(best['label'])]} ({best['avg']:+.1f}%) and the "
            f"weakest {MONTH_NAMES[MONTHS.index(worst['label'])]} ({worst['avg']:+.1f}%).")
    return result
