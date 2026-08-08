"""Tests for the Home dashboard snapshot (tradelab/core/home.py).

Home assembles what the other engines compute, so these tests focus on the
assembly: the day move, movers ordering, next payment, attention items, and
that the headline figures agree with the tabs they came from.
"""
import numpy as np
import pandas as pd
import pytest

from tradelab.core import home, portfolio_analytics as pa

TODAY = pd.Timestamp("2026-07-01")


def _hist(closes, start="2026-01-01"):
    idx = pd.date_range(start=start, periods=len(closes), freq="B")
    v = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": v, "High": v, "Low": v, "Close": v,
                         "Volume": [0] * len(v)}, index=idx)


def _rate(n, value):
    return pd.Series([value] * n, index=pd.date_range("2026-01-01", periods=n, freq="B"))


# --- movers & day move ------------------------------------------------------

def test_movers_ranked_by_absolute_move():
    pos = [{"symbol": "UP", "shares": 10, "entry_price": 1},
           {"symbol": "FLAT", "shares": 10, "entry_price": 1},
           {"symbol": "DOWN", "shares": 10, "entry_price": 1}]
    hist = {"UP": _hist([100, 102]),      # +2%
            "FLAT": _hist([50, 50.1]),    # +0.2%
            "DOWN": _hist([80, 76])}      # -5%
    rows = home.movers(pos, hist)
    assert [m["symbol"] for m in rows] == ["DOWN", "UP", "FLAT"]
    assert rows[0]["change_pct"] == pytest.approx(-5.0)
    assert rows[0]["change_value"] == pytest.approx(-40.0)   # -4 x 10 shares


def test_day_move_sums_holdings():
    pos = [{"symbol": "A", "shares": 10, "entry_price": 1},
           {"symbol": "B", "shares": 5, "entry_price": 1}]
    hist = {"A": _hist([100, 101]), "B": _hist([200, 198])}
    rows = home.movers(pos, hist)
    assert home.day_move(rows) == pytest.approx(10 * 1 + 5 * -2)   # +10 -10 = 0


def test_movers_percent_is_native_but_value_converts():
    pos = [{"symbol": "VTI", "shares": 10, "entry_price": 1}]      # USD
    hist = {"VTI": _hist([100, 110])}
    fx = {"USD": _rate(2, 1.4)}
    row = home.movers(pos, hist, target="CAD", fx=fx)[0]
    assert row["change_pct"] == pytest.approx(10.0)                # native move
    assert row["change_value"] == pytest.approx(10 * 10 * 1.4)     # CAD value


def test_movers_skips_unpriced_holdings():
    pos = [{"symbol": "A", "shares": 1, "entry_price": 1},
           {"symbol": "ZZZZ", "shares": 1, "entry_price": 1}]
    rows = home.movers(pos, {"A": _hist([10, 11])})
    assert [m["symbol"] for m in rows] == ["A"]


# --- next payment -----------------------------------------------------------

def test_next_payment_picks_the_nearest_month_ahead():
    rows = [{"symbol": "Q", "pays": True, "annual_income": 400.0, "months": [3, 6, 9, 12]},
            {"symbol": "M", "pays": True, "annual_income": 120.0, "months": list(range(1, 13))}]
    nxt = home.next_payment(rows, today=pd.Timestamp("2026-07-01"))
    assert nxt["symbol"] == "M" and nxt["month"] == 7           # pays this month
    # With only the quarterly payer, September is next after July.
    nxt_q = home.next_payment([rows[0]], today=pd.Timestamp("2026-07-01"))
    assert nxt_q["month"] == 9
    assert nxt_q["amount"] == pytest.approx(100.0)


def test_next_payment_wraps_into_next_year():
    rows = [{"symbol": "A", "pays": True, "annual_income": 100.0, "months": [2]}]
    nxt = home.next_payment(rows, today=pd.Timestamp("2026-12-15"))
    assert nxt["month"] == 2 and nxt["name"] == "February"


def test_next_payment_none_when_nothing_pays():
    assert home.next_payment([{"symbol": "K", "pays": False, "months": []}]) is None
    assert home.next_payment([]) is None


# --- attention --------------------------------------------------------------

def test_attention_flags_a_big_drop():
    rows = [{"symbol": "CRASH", "change_pct": -8.0, "change_value": -800, "last": 10}]
    items = home.attention({}, {}, rows)
    assert any("CRASH" in i["text"] and i["kind"] == "warn" for i in items)


def test_attention_flags_missing_data_and_concentration():
    analytics = {"no_data": ["ZZZZ"], "fx_missing": ["GBP"],
                 "concentration": {"largest_pct": 44.0},
                 "holdings": [{"symbol": "XDIV.TO"}]}
    items = home.attention(analytics, {}, [])
    text = " ".join(i["text"] for i in items)
    assert "ZZZZ" in text and "GBP" in text and "XDIV.TO" in text


def test_attention_quiet_when_all_is_well():
    analytics = {"no_data": [], "fx_missing": [],
                 "concentration": {"largest_pct": 20.0}, "holdings": []}
    rows = [{"symbol": "A", "change_pct": 0.5, "change_value": 5, "last": 10}]
    assert home.attention(analytics, {}, rows) == []


# --- market context ---------------------------------------------------------

def test_index_strip_orders_and_shortens():
    strip = home.index_strip({
        "S&P 500": {"last": 7100.0, "change_pct": 0.24},
        "TSX Composite": {"last": 35568.14, "change_pct": 0.5626},
        "Nikkei 225": {"last": 48000.0, "change_pct": -1.05},
    })
    assert [i["label"] for i in strip] == ["TSX", "S&P 500", "Nikkei"]  # home market first
    assert strip[0]["text"] == "TSX +0.6%"
    assert strip[2]["text"] == "Nikkei -1.1%"


def test_index_strip_skips_unpriced_indices():
    strip = home.index_strip({"DAX": {"last": None, "change_pct": None},
                              "FTSE 100": {"last": 9000.0, "change_pct": 0.3}})
    assert [i["label"] for i in strip] == ["FTSE"]
    assert home.index_strip({}) == [] and home.index_strip(None) == []


def test_macro_row_formats_each_instrument_its_own_way():
    rows = home.macro_row({
        "CAD=X": {"last": 1.4125, "change_pct": 0.284},   # FX: 4 decimals
        "CL=F": {"last": 81.90, "change_pct": -8.3},      # under $1000: cents
        "GC=F": {"last": 4081.10, "change_pct": 0.33},    # over $1000: no cents
        "^TNX": {"last": 4.641, "change_pct": -0.812},    # a yield, not a price
    })
    text = {r["label"]: r["text"] for r in rows}
    assert text["USD/CAD"] == "USD/CAD 1.4125 +0.3%"
    assert text["Oil"] == "Oil $81.90 -8.3%"
    assert text["Gold"] == "Gold $4,081 +0.3%"


def test_macro_row_quotes_the_ten_year_in_basis_points():
    # 4.641 after a -0.812% move came from 4.679 -> down ~4bp, not "-0.8%".
    rows = home.macro_row({"^TNX": {"last": 4.641, "change_pct": -0.812}})
    assert rows[0]["text"] == "US 10Y 4.64% -4 bp"
    # Rising rates aren't "good news" for a book of dividend payers, so the
    # yield is never coloured green-for-up.
    assert rows[0]["directional"] is False


def test_macro_row_handles_missing_and_partial_data():
    assert home.macro_row({}) == [] and home.macro_row(None) == []
    rows = home.macro_row({"GC=F": {"last": 4081.10, "change_pct": None}})
    assert rows[0]["text"] == "Gold $4,081"          # level only, no invented move
    assert rows[0]["change_pct"] is None


# --- summarize --------------------------------------------------------------

def test_summarize_empty_book():
    r = home.summarize([], {})
    assert r["has_positions"] is False
    assert "No holdings yet" in r["text"]
    assert r["movers"] == [] and r["attention"] == []


def test_summarize_matches_the_source_tabs():
    # Home must not recompute: its value and income have to equal what the
    # Analytics and Dividends tabs would report for the same inputs.
    from tradelab.core import dividends as dv
    pos = [{"symbol": "XDIV.TO", "shares": 300, "entry_price": 43.26}]
    hist = {"XDIV.TO": _hist(list(np.linspace(43.0, 46.42, 120)))}
    divs_idx = pd.DatetimeIndex(
        [TODAY - pd.DateOffset(months=i) for i in range(1, 13)][::-1])
    divs = {"XDIV.TO": pd.Series([0.12] * 12, index=divs_idx)}

    r = home.summarize(pos, hist, divs, target_currency="CAD", today=TODAY)
    analytics = pa.summarize(pos, hist, target_currency="CAD")
    income = dv.summarize(pos, divs, {"XDIV.TO": 46.42},
                          target_currency="CAD", today=TODAY)

    assert r["analytics"]["total_value"] == pytest.approx(analytics["total_value"])
    assert r["income"]["total_annual_income"] == pytest.approx(
        income["total_annual_income"])
    assert "CAD" in r["text"] and "dividends" in r["text"]
    assert r["next_payment"] is not None


# --- the year-so-far curve --------------------------------------------------

def _daily(closes, start):
    """A daily-bar frame of `closes` beginning on `start` (business days)."""
    idx = pd.date_range(start=start, periods=len(closes), freq="B")
    v = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": v, "High": v, "Low": v, "Close": v,
                         "Volume": [0] * len(v)}, index=idx)


def test_ytd_curve_starts_from_last_years_close():
    # 20 sessions of 2025 at $100, then 2026 rising to $110. The year began
    # where the book closed last year, not at its own first bar.
    closes = [100.0] * 20 + list(np.linspace(100.0, 110.0, 60))
    hist = {"A": _daily(closes, "2025-12-04")}
    pos = [{"symbol": "A", "shares": 10, "entry_price": 90.0}]
    r = home.ytd_curve(pos, hist)
    assert r["from_last_year"] is True
    assert r["start_value"] == pytest.approx(1000.0)      # 10 x $100
    assert r["last_value"] == pytest.approx(1100.0)
    assert r["change"] == pytest.approx(100.0)
    assert r["change_pct"] == pytest.approx(10.0)
    assert r["start_date"].year == 2025                   # the anchor bar
    assert r["limited_by"] is None
    assert "up $100" in r["text"] and "+10.0%" in r["text"]


def test_ytd_curve_without_last_year_measures_from_january():
    hist = {"A": _daily(list(np.linspace(50.0, 55.0, 40)), "2026-01-02")}
    pos = [{"symbol": "A", "shares": 100, "entry_price": 50.0}]
    r = home.ytd_curve(pos, hist)
    assert r["from_last_year"] is False
    assert r["start_value"] == pytest.approx(5000.0)
    assert r["start_date"] == pd.Timestamp("2026-01-02")
    assert r["limited_by"] is None                        # January is not "late"
    assert "since 02 Jan" in r["text"]


def test_ytd_curve_needs_more_than_a_couple_of_sessions():
    # Two dots in the first days of January is a line segment, not a year.
    hist = {"A": _daily([10.0, 10.5], "2026-01-02")}
    pos = [{"symbol": "A", "shares": 1, "entry_price": 10.0}]
    assert home.ytd_curve(pos, hist) is None
    assert home.ytd_curve(pos, {}) is None
    assert home.ytd_curve([], hist) is None


def test_ytd_curve_names_the_holding_that_shortened_the_year():
    # The curve spans only dates every holding shares, so a name listed in
    # March moves the start of "the year" to March. Say which one.
    hist = {"OLD": _daily([100.0] * 200, "2025-10-01"),
            "NEW": _daily([20.0] * 60, "2026-03-02")}
    pos = [{"symbol": "OLD", "shares": 10, "entry_price": 90.0},
           {"symbol": "NEW", "shares": 50, "entry_price": 18.0}]
    r = home.ytd_curve(pos, hist)
    assert r["limited_by"] == "NEW"
    assert r["start_date"] == pd.Timestamp("2026-03-02")
    assert r["from_last_year"] is False


def test_ytd_curve_is_reported_in_the_display_currency():
    hist = {"VTI": _daily([100.0] * 40, "2025-12-15")}
    fx = {"USD": pd.Series([1.4] * 40,
                           index=pd.date_range("2025-12-15", periods=40, freq="B"))}
    r = home.ytd_curve([{"symbol": "VTI", "shares": 10, "entry_price": 90.0}],
                       hist, target="CAD", fx=fx)
    assert r["last_value"] == pytest.approx(10 * 100.0 * 1.4)
    assert r["currency"] == "CAD"
    assert "CAD" in r["text"]


def test_ytd_curve_reports_the_deepest_dip():
    # Eight sessions of 2025 (the last is 31 Dec), then the swing in January.
    closes = [100.0] * 8 + [100.0, 120.0, 90.0, 110.0] + [110.0] * 10
    hist = {"A": _daily(closes, "2025-12-22")}
    r = home.ytd_curve([{"symbol": "A", "shares": 1, "entry_price": 100.0}], hist)
    assert r["max_drawdown_pct"] == pytest.approx(-25.0)   # 120 -> 90
    assert r["high"] == pytest.approx(120.0) and r["low"] == pytest.approx(90.0)
    assert "deepest dip -25.0%" in r["text"]


def test_ytd_curve_matches_the_analytics_equity_curve():
    # The chart and Analytics' risk figures must be the same curve, so a
    # drawdown on Home can never disagree with the one on Analytics.
    pos = [{"symbol": "A", "shares": 10, "entry_price": 90.0}]
    hist = {"A": _daily(list(np.linspace(100.0, 130.0, 80)), "2026-01-02")}
    r = home.ytd_curve(pos, hist)
    equity = pa.portfolio_equity(pos, hist)
    assert r["last_value"] == pytest.approx(float(equity.iloc[-1]))
    assert r["series"].equals(equity[equity.index >= pd.Timestamp("2026-01-01")])


def test_summarize_carries_the_year_curve():
    pos = [{"symbol": "A", "shares": 10, "entry_price": 90.0}]
    hist = {"A": _daily(list(np.linspace(100.0, 110.0, 80)), "2025-12-01")}
    r = home.summarize(pos, hist, target_currency=None, today=TODAY)
    assert r["ytd"]["change_pct"] is not None
    assert home.summarize([], {})["ytd"] is None
