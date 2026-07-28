"""Scheduled dates for the holdings you own (Qt-free, offline-testable).

The narrow, honest version of a "catalysts" feed: the two dates that are
genuinely published for a stock — when it next **reports earnings**, and when it
next trades **ex-dividend**. Nothing here is predicted, inferred or scored.

Deliberately not included: economic releases (CPI, PPI, central-bank decisions)
and analyst actions. No source wired into this app publishes them reliably, and
a hardcoded table of dates goes stale silently — a wrong date on a real-money
screen is worse than no date at all.

Note what this cannot cover: ETFs have no earnings, and most publish no calendar
at all, so a book held mostly in funds will show few events. That is a real
limit of the data, and the UI says so rather than padding the list.

Pure and network-free: callers pass in already-fetched calendars, the same
pattern as the other core modules.
"""
from __future__ import annotations

from datetime import date, timedelta

EARNINGS = "earnings"
EX_DIVIDEND = "ex-dividend"

# How far ahead is still "coming up". Beyond about six weeks a date is trivia
# rather than something to know today, and estimated earnings dates that far out
# often move anyway.
HORIZON_DAYS = 45

_LABELS = {EARNINGS: "reports", EX_DIVIDEND: "ex-dividend"}


def _as_date(value):
    if isinstance(value, date):
        return value
    try:                                    # a pandas Timestamp, or similar
        return value.date()
    except AttributeError:
        return None


def upcoming(calendars: dict, today=None, horizon_days: int = HORIZON_DAYS,
             symbols: list = None) -> list:
    """Every scheduled date ahead of us, soonest first.

    `calendars` maps a symbol to {"earnings": date|None, "ex_dividend":
    date|None} — see market_data.get_calendar. Dates already past are dropped:
    an ex-dividend that happened last week is history, not a heads-up.

    Each event is {symbol, kind, date, days_away, text}. `symbols` optionally
    restricts and orders which holdings are considered.
    """
    now = _as_date(today) or date.today()
    limit = now + timedelta(days=horizon_days)
    wanted = list(symbols) if symbols is not None else list((calendars or {}).keys())

    events = []
    for symbol in wanted:
        entry = (calendars or {}).get(symbol) or {}
        for kind, key in ((EARNINGS, "earnings"), (EX_DIVIDEND, "ex_dividend")):
            when = _as_date(entry.get(key))
            if when is None or when < now or when > limit:
                continue
            days = (when - now).days
            events.append({
                "symbol": symbol, "kind": kind, "date": when, "days_away": days,
                "text": f"{symbol} {_LABELS[kind]} {describe_when(days)}",
            })
    events.sort(key=lambda e: (e["date"], e["symbol"], e["kind"]))
    return events


def describe_when(days_away: int) -> str:
    """Plain English for how far off something is."""
    if days_away == 0:
        return "today"
    if days_away == 1:
        return "tomorrow"
    return f"in {days_away} days"


def next_for(events: list, symbol: str, kind: str = None):
    """The soonest event for one holding, optionally of one kind."""
    for event in events:
        if event["symbol"] == symbol and (kind is None or event["kind"] == kind):
            return event
    return None


def summarize(calendars: dict, today=None, horizon_days: int = HORIZON_DAYS,
              symbols: list = None) -> dict:
    """What the Home tab renders: the events themselves, plus which holdings had
    no calendar at all so the absence can be explained rather than looking like
    a quiet day."""
    events = upcoming(calendars, today, horizon_days, symbols)
    wanted = list(symbols) if symbols is not None else list((calendars or {}).keys())
    # A holding has "no calendar" when neither date is published for it — the
    # normal case for an ETF.
    no_data = []
    for symbol in wanted:
        entry = (calendars or {}).get(symbol) or {}
        if not entry.get("earnings") and not entry.get("ex_dividend"):
            no_data.append(symbol)
    return {"events": events, "no_data": no_data,
            "horizon_days": horizon_days,
            "text": text_for(events)}


def text_for(events: list, limit: int = 3) -> str:
    """A one-line summary of the next few events, or "" when there are none."""
    if not events:
        return ""
    shown = [e["text"] for e in events[:limit]]
    more = len(events) - len(shown)
    return " · ".join(shown) + (f" · +{more} more" if more > 0 else "")
