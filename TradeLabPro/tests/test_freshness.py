"""Tests for tradelab.core.freshness - when data is old enough to fetch again."""
import time

from tradelab.core import freshness as f


def _at(y, mo, d, h, mi):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


NOW = _at(2026, 10, 6, 14, 0)


def test_never_fetched_is_always_stale():
    assert f.is_stale(None, NOW)
    assert f.is_stale(None, NOW, f.DAILY)


def test_intraday_goes_stale_at_the_threshold():
    assert not f.is_stale(NOW - 14 * 60, NOW, f.INTRADAY, 15)
    assert f.is_stale(NOW - 15 * 60, NOW, f.INTRADAY, 15)


def test_the_threshold_is_yours_to_set():
    assert not f.is_stale(NOW - 40 * 60, NOW, f.INTRADAY, 60)
    assert f.is_stale(NOW - 2 * 60, NOW, f.INTRADAY, 1)


def test_daily_ignores_the_threshold_within_the_day():
    """Dividends and sectors do not move in a session; a morning fetch holds
    all afternoon."""
    assert not f.is_stale(_at(2026, 10, 6, 9, 0), NOW, f.DAILY, 15)


def test_daily_goes_stale_when_the_day_turns_even_a_minute_later():
    assert f.is_stale(_at(2026, 10, 5, 23, 59), _at(2026, 10, 6, 0, 0), f.DAILY)


def test_a_recent_reading_says_updated():
    assert f.stamp(_at(2026, 10, 6, 13, 50), NOW) == "updated 13:50"


def test_an_old_reading_says_as_of():
    assert f.stamp(_at(2026, 10, 6, 12, 30), NOW) == "as of 12:30"


def test_a_reading_from_yesterday_carries_its_date():
    """A figure from yesterday must never read like one from this afternoon."""
    assert f.stamp(_at(2026, 10, 5, 16, 0), NOW) == "as of Oct 5 16:00"
