"""Tests for seasonality analysis (tradelab/core/seasonality.py).

All pure and offline: we build price frames with known calendar patterns and
check the month/weekday/annual stats fall out correctly.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradelab.core import seasonality as sz


def _daily_close(values, start="2020-01-01"):
    idx = pd.date_range(start=start, periods=len(values), freq="D")
    return pd.DataFrame({"Close": values,
                         "Open": values, "High": values, "Low": values,
                         "Volume": [0] * len(values)}, index=idx)


def _month_end_frame(month_closes, start_year=2018):
    """Build a daily frame whose month-END closes follow `month_closes` (a list
    of floats, one per consecutive month from Jan `start_year`). Every day in a
    month sits at that month's close, so month-over-month returns are exact."""
    rows = {}
    month = pd.Timestamp(f"{start_year}-01-01")
    for close in month_closes:
        days = pd.date_range(month, month + pd.offsets.MonthEnd(0), freq="D")
        for d in days:
            rows[d] = close
        month = month + pd.offsets.MonthBegin(1)
    s = pd.Series(rows).sort_index()
    return pd.DataFrame({"Close": s, "Open": s, "High": s, "Low": s,
                        "Volume": [0] * len(s)})


def _from_monthly_returns(returns_pct, base=100.0, start_year=2018):
    """Build a frame whose month-over-month returns are EXACTLY `returns_pct`
    (a list of percents; the first month is the base with no return). Avoids the
    spike-then-flat artifact of specifying absolute closes directly."""
    closes = [base]
    for r in returns_pct:
        closes.append(closes[-1] * (1 + r / 100.0))
    return _month_end_frame(closes, start_year)


# --- basic guards -----------------------------------------------------------

def test_empty_and_missing_are_safe():
    assert sz.monthly_return_series(None).empty
    assert sz.years_covered(None) == 0
    assert sz.annual_returns(pd.DataFrame()) == []
    r = sz.summarize(None)
    assert r["best_month"] is None
    assert "Not enough" in r["text"]


def test_monthly_stats_always_twelve_rows():
    stats = sz.monthly_stats(_daily_close([100] * 40))
    assert [s["label"] for s in stats] == sz.MONTHS
    assert len(stats) == 12


# --- month-over-month returns ----------------------------------------------

def test_monthly_returns_are_month_over_month_percent():
    # Jan=100, Feb=110, Mar=99 -> Feb +10%, Mar -10%.
    df = _month_end_frame([100, 110, 99])
    r = sz.monthly_return_series(df)
    vals = [round(v, 4) for v in r.values]
    assert vals == [10.0, -10.0]


def test_january_average_across_years():
    # Two years. Each January return is measured from the prior December.
    # Dec'18=100, Jan'19=110 (+10%); Dec'19=100, Jan'20=90 (-10%). Avg Jan = 0%.
    closes = [50] * 11 + [100, 110] + [100] * 10 + [100, 90]  # ... Nov, Dec'18, Jan'19,... Dec'19, Jan'20
    df = _month_end_frame(closes)
    stats = {s["label"]: s for s in sz.monthly_stats(df)}
    jan = stats["Jan"]
    assert jan["count"] == 2
    assert jan["avg"] == pytest.approx(0.0, abs=1e-6)
    assert jan["best"] == pytest.approx(10.0)
    assert jan["worst"] == pytest.approx(-10.0)
    assert jan["win_rate"] == pytest.approx(50.0)


def test_win_rate_and_extremes_for_a_positive_month():
    # Feb up in both years: +10% and +20% -> win rate 100%, avg 15%.
    closes = [100, 110] + [100] * 10 + [100, 120] + [100] * 10
    df = _month_end_frame(closes)
    feb = {s["label"]: s for s in sz.monthly_stats(df)}["Feb"]
    assert feb["count"] == 2
    assert feb["win_rate"] == pytest.approx(100.0)
    assert feb["avg"] == pytest.approx(15.0)
    assert feb["best"] == pytest.approx(20.0)


# --- weekday, annual, coverage ---------------------------------------------

def test_weekday_stats_five_weekdays_no_weekends():
    stats = sz.weekday_stats(_daily_close(list(range(100, 200))))
    assert [s["label"] for s in stats] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    # A steadily rising series -> every measured weekday averages a positive move.
    for s in stats:
        assert s["count"] > 0 and s["avg"] > 0


def test_annual_returns_are_intra_year():
    # 2020 starts at 100 ends at 120 (+20%); 2021 starts 120 ends 108 (-10%).
    idx = (list(pd.date_range("2020-01-01", "2020-12-31", freq="D"))
           + list(pd.date_range("2021-01-01", "2021-12-31", freq="D")))
    vals = ([100 + (20 * i / 365) for i in range(366)]
            + [120 - (12 * i / 364) for i in range(365)])
    df = pd.DataFrame({"Close": vals, "Open": vals, "High": vals, "Low": vals,
                      "Volume": [0] * len(vals)}, index=pd.DatetimeIndex(idx))
    ann = {a["year"]: a for a in sz.annual_returns(df)}
    assert ann[2020]["return_pct"] == pytest.approx(20.0, abs=0.2)
    assert ann[2021]["return_pct"] == pytest.approx(-10.0, abs=0.2)


def test_years_covered_counts_distinct_years():
    idx = pd.date_range("2019-06-01", periods=800, freq="D")   # spans 2019-2021
    df = pd.DataFrame({"Close": np.arange(1.0, 801.0)}, index=idx)
    assert sz.years_covered(df) == 3


# --- month context + summary -----------------------------------------------

def test_month_context_reads_strong_and_weak():
    # Base month is Jan 2018 (index 0). Returns are month-over-month from Feb 2018.
    # Set Dec strong (+10, +12) and Sep weak (-8, -9); every other month flat.
    rets = [0.0] * 24
    rets[7] = -8.0      # Sep 2018
    rets[10] = 10.0     # Dec 2018
    rets[19] = -9.0     # Sep 2019
    rets[22] = 12.0     # Dec 2019
    df = _from_monthly_returns(rets)
    stats = sz.monthly_stats(df)
    dec = sz.month_context(stats, 12)
    sep = sz.month_context(stats, 9)
    assert dec["read"] == "historically strong"
    assert sep["read"] == "historically weak"
    assert dec["month_name"] == "December"
    assert dec["count"] == 2 and sep["count"] == 2


def test_summarize_reports_current_month_and_extremes():
    # Feb best (+30 both years), Dec worst (-30 both years), else flat.
    rets = [0.0] * 24
    rets[0] = 30.0      # Feb 2018
    rets[12] = 30.0     # Feb 2019
    rets[10] = -30.0    # Dec 2018
    rets[22] = -30.0    # Dec 2019
    df = _from_monthly_returns(rets)
    r = sz.summarize(df, today=date(2020, 2, 15))
    assert r["best_month"]["label"] == "Feb"
    assert r["worst_month"]["label"] == "Dec"
    assert r["current"]["month_name"] == "February"
    assert "February" in r["text"]
    assert r["years"] >= 1
