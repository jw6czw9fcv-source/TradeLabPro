"""Tests for scheduled holding events (tradelab/core/events.py)."""
from datetime import date, timedelta

from tradelab.core import events as ev

TODAY = date(2026, 7, 27)


def _cal(earnings=None, ex_dividend=None):
    return {"earnings": earnings, "ex_dividend": ex_dividend}


def test_events_are_ordered_soonest_first():
    cals = {"RY.TO": _cal(earnings=date(2026, 8, 27)),
            "POW.TO": _cal(earnings=date(2026, 7, 30))}
    out = ev.upcoming(cals, today=TODAY)
    assert [e["symbol"] for e in out] == ["POW.TO", "RY.TO"]
    assert out[0]["days_away"] == 3
    assert out[0]["text"] == "POW.TO reports in 3 days"


def test_past_dates_are_dropped():
    # An ex-dividend that already happened is history, not a heads-up.
    cals = {"RY.TO": _cal(ex_dividend=date(2026, 7, 26))}   # yesterday
    assert ev.upcoming(cals, today=TODAY) == []
    # The same date, today, still counts.
    assert len(ev.upcoming({"RY.TO": _cal(ex_dividend=TODAY)}, today=TODAY)) == 1


def test_events_beyond_the_horizon_are_dropped():
    cals = {"A": _cal(earnings=date(2026, 9, 30))}          # ~65 days out
    assert ev.upcoming(cals, today=TODAY) == []
    assert len(ev.upcoming(cals, today=TODAY, horizon_days=90)) == 1


def test_both_kinds_are_reported_for_one_holding():
    cals = {"RY.TO": _cal(earnings=date(2026, 8, 20), ex_dividend=date(2026, 7, 30))}
    out = ev.upcoming(cals, today=TODAY)
    assert [e["kind"] for e in out] == [ev.EX_DIVIDEND, ev.EARNINGS]
    assert out[0]["text"] == "RY.TO ex-dividend in 3 days"


def test_missing_and_empty_calendars_are_silent():
    # An ETF publishes no calendar; it must contribute nothing, not a guess.
    assert ev.upcoming({"XDIV.TO": _cal()}, today=TODAY) == []
    assert ev.upcoming({}, today=TODAY) == [] and ev.upcoming(None, today=TODAY) == []


def test_describe_when_reads_naturally():
    assert ev.describe_when(0) == "today"
    assert ev.describe_when(1) == "tomorrow"
    assert ev.describe_when(9) == "in 9 days"


def test_summarize_names_holdings_with_no_calendar():
    cals = {"POW.TO": _cal(earnings=date(2026, 7, 30)), "XDIV.TO": _cal()}
    r = ev.summarize(cals, today=TODAY, symbols=["POW.TO", "XDIV.TO", "XIC.TO"])
    assert r["no_data"] == ["XDIV.TO", "XIC.TO"]      # incl. one absent entirely
    assert r["text"] == "POW.TO reports in 3 days"


def test_summary_text_caps_the_list_and_counts_the_rest():
    cals = {f"S{i}": _cal(earnings=TODAY + timedelta(days=i + 1)) for i in range(5)}
    r = ev.summarize(cals, today=TODAY)
    assert r["text"].endswith("+2 more")
    assert r["text"].startswith("S0 reports tomorrow")
    assert ev.text_for([]) == ""


def test_next_for_picks_one_holdings_soonest():
    cals = {"RY.TO": _cal(earnings=date(2026, 8, 20), ex_dividend=date(2026, 7, 30)),
            "POW.TO": _cal(earnings=date(2026, 7, 29))}
    out = ev.upcoming(cals, today=TODAY)
    assert ev.next_for(out, "RY.TO")["kind"] == ev.EX_DIVIDEND
    assert ev.next_for(out, "RY.TO", ev.EARNINGS)["date"] == date(2026, 8, 20)
    assert ev.next_for(out, "ZZZZ") is None


def test_timestamps_are_accepted_as_dates():
    import pandas as pd
    cals = {"A": _cal(earnings=pd.Timestamp("2026-07-30"))}
    out = ev.upcoming(cals, today=pd.Timestamp("2026-07-27"))
    assert out and out[0]["days_away"] == 3
