"""When data is old enough to fetch again - one rule, for every tab.

Not everything on screen moves at the same speed, so there are two:

* INTRADAY - prices, book value, the market read. They move all session, so a
  tab showing them is stale once it is older than the threshold you set
  (15 minutes unless you change it in Settings).
* DAILY - dividend histories, sector labels, the index histories the
  retirement plan is measured against. Nothing in them changes during a
  session, so they go stale only when the calendar day turns. Fetching them
  every quarter of an hour would download identical data and change nothing
  on screen.

And one way of saying how old something is, so every tab says it alike:
"updated 14:32" while it is recent, "as of 14:32" once it is more than an hour
old, and the date as well once it is from another day - a figure from
yesterday must never read like one from this afternoon.

Qt-free, no network.
"""
from __future__ import annotations

import time

INTRADAY = "intraday"
DAILY = "daily"

DEFAULT_MAX_AGE_MINUTES = 15
AS_OF_AFTER_MINUTES = 60


def _day(ts: float) -> tuple:
    return tuple(time.localtime(ts)[:3])


def is_stale(last: float | None, now: float, policy: str = INTRADAY,
             max_age_minutes: float = DEFAULT_MAX_AGE_MINUTES) -> bool:
    """Whether data last fetched at `last` should be fetched again at `now`.

    Never fetched is always stale. A DAILY source ignores the threshold and
    asks only whether the day has changed - including across midnight, where
    a minute is enough.
    """
    if last is None:
        return True
    if policy == DAILY:
        return _day(last) != _day(now)
    return (now - last) >= max_age_minutes * 60


def stamp(as_of: float, now: float) -> str:
    """How old a reading is, in the words every tab uses for it."""
    local = time.localtime(as_of)
    clock = time.strftime("%H:%M", local)
    if _day(as_of) != _day(now):
        return f"as of {time.strftime('%b', local)} {local.tm_mday} {clock}"
    if now - as_of > AS_OF_AFTER_MINUTES * 60:
        return f"as of {clock}"
    return f"updated {clock}"
