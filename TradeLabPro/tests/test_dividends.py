"""Tests for dividend income analysis (tradelab/core/dividends.py).

Pure/offline: dividend histories are built by hand with known schedules, so the
frequency, income, yield and calendar maths are checked exactly. `today` is
pinned everywhere so the trailing-12-month windows never drift with the clock.
"""
import pandas as pd
import pytest

from tradelab.core import dividends as dv

TODAY = pd.Timestamp("2026-07-01")


def _series(dates, amounts):
    return pd.Series(amounts, index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]))


def _every(months, amount, n, end):
    """n payments `months` apart, ending on `end` (mid-month so no payment lands
    exactly on the trailing-12-month boundary, which is exclusive)."""
    end_ts = pd.Timestamp(end)
    idx = pd.DatetimeIndex(
        [end_ts - pd.DateOffset(months=months * i) for i in range(n)][::-1])
    return pd.Series([amount] * n, index=idx)


def _monthly(amount=0.12, n=12, end="2026-06-15"):
    return _every(1, amount, n, end)


def _quarterly(amount=0.29, n=8, end="2026-06-15"):
    return _every(3, amount, n, end)


# --- frequency detection ----------------------------------------------------

def test_detect_frequency_monthly_and_quarterly():
    assert dv.detect_frequency(_monthly(), TODAY)["per_year"] == 12
    assert dv.detect_frequency(_monthly(), TODAY)["label"] == "Monthly"
    assert dv.detect_frequency(_quarterly(), TODAY)["per_year"] == 4
    assert dv.detect_frequency(_quarterly(), TODAY)["label"] == "Quarterly"


def test_detect_frequency_semi_annual_and_annual():
    semi = _series(["2024-01-15", "2024-07-15", "2025-01-15", "2025-07-15"], [1.0] * 4)
    annual = _series(["2023-06-01", "2024-06-01", "2025-06-01"], [2.0] * 3)
    assert dv.detect_frequency(semi, TODAY)["per_year"] == 2
    assert dv.detect_frequency(annual, TODAY)["per_year"] == 1


def test_detect_frequency_handles_empty_and_single():
    assert dv.detect_frequency(None, TODAY)["per_year"] is None
    assert dv.detect_frequency(pd.Series(dtype=float), TODAY)["label"] == "—"
    single = _series(["2026-01-15"], [1.0])
    assert dv.detect_frequency(single, TODAY)["per_year"] is None


# --- per-share income -------------------------------------------------------

def test_ttm_sums_only_the_last_twelve_months():
    # 24 monthly payments; only the last 12 count toward TTM.
    s = _monthly(amount=0.10, n=24)
    assert dv.ttm_per_share(s, TODAY) == pytest.approx(1.20)


def test_forward_rate_annualizes_the_latest_payment():
    # A raise in the final month: TTM lags, the forward rate reflects it.
    s = _monthly(amount=0.10, n=12)
    s.iloc[-1] = 0.20
    assert dv.ttm_per_share(s, TODAY) == pytest.approx(1.30)     # 11*0.10 + 0.20
    assert dv.forward_per_share(s, TODAY) == pytest.approx(2.40)  # 0.20 * 12


def test_no_dividends_returns_none():
    assert dv.ttm_per_share(pd.Series(dtype=float), TODAY) is None
    assert dv.forward_per_share(None, TODAY) is None


def test_growth_compares_two_twelve_month_windows():
    # Prior year 0.10/mo (1.20), this year 0.15/mo (1.80) -> +50%.
    old = _monthly(amount=0.10, n=12, end="2025-06-15")     # prior 12 months
    new = _monthly(amount=0.15, n=12, end="2026-06-15")     # last 12 months
    assert dv.growth_pct(pd.concat([old, new]), TODAY) == pytest.approx(50.0, abs=0.01)


def test_growth_needs_two_years():
    assert dv.growth_pct(_monthly(n=6), TODAY) is None


def test_growth_survives_uneven_payment_counts():
    # Regression (real RY.TO shape): a quarterly payer that has RAISED every
    # year, but whose trailing window holds 3 payments while the prior holds 4.
    # Comparing window sums reported a ~-19% "cut"; comparing average payment
    # size must report the real raise.
    s = _series(["2024-07-25", "2024-10-24", "2025-01-27", "2025-04-24",
                 "2025-07-24", "2025-10-27", "2026-01-26", "2026-04-23"],
                [1.42, 1.42, 1.48, 1.48, 1.54, 1.54, 1.64, 1.64])
    asof = pd.Timestamp("2026-07-24")          # boundary excludes 2025-07-24
    ttm = s[(s.index > asof - pd.DateOffset(years=1)) & (s.index <= asof)]
    prior = s[(s.index > asof - pd.DateOffset(years=2))
              & (s.index <= asof - pd.DateOffset(years=1))]
    assert len(ttm) != len(prior)              # the uneven split that broke it
    assert ttm.sum() < prior.sum()             # sums alone imply a "cut"...
    g = dv.growth_pct(s, asof)
    assert g > 0, "a raising dividend must not report negative growth"
    assert g == pytest.approx(9.4, abs=0.5)    # ...but mean 1.607 vs 1.468 is a raise


# --- per-holding ------------------------------------------------------------

def test_holding_income_yields_and_totals():
    # 300 shares, $0.12 monthly -> $1.44/share/yr -> $432/yr.
    pos = {"symbol": "XDIV.TO", "shares": 300, "avg_entry": 43.26}
    h = dv.holding_income(pos, _monthly(0.12), price=46.42, today=TODAY)
    assert h["pays"] and h["frequency"] == 12
    assert h["per_share_annual"] == pytest.approx(1.44)
    assert h["annual_income"] == pytest.approx(432.0)
    assert h["current_yield_pct"] == pytest.approx(1.44 / 46.42 * 100, abs=0.01)
    # Bought lower, so yield on cost is above the current yield.
    assert h["yield_on_cost_pct"] == pytest.approx(1.44 / 43.26 * 100, abs=0.01)
    assert h["yield_on_cost_pct"] > h["current_yield_pct"]


def test_holding_income_non_payer_is_safe():
    pos = {"symbol": "KTOS", "shares": 1, "avg_entry": 48.54}
    h = dv.holding_income(pos, pd.Series(dtype=float), price=47.35, today=TODAY)
    assert h["pays"] is False
    assert h["annual_income"] is None and h["current_yield_pct"] is None
    assert h["frequency_label"] == "—"


def test_holding_income_converts_to_target_currency():
    # Per-share amounts stay native (USD); income converts to CAD at 1.4.
    pos = {"symbol": "VTI", "shares": 10, "avg_entry": 300.0}
    fx = {"USD": pd.Series([1.4] * 5,
                           index=pd.date_range("2026-06-01", periods=5, freq="D"))}
    h = dv.holding_income(pos, _quarterly(1.0), price=400.0, target="CAD",
                          fx=fx, today=TODAY)
    assert h["currency"] == "USD" and h["converted"]
    assert h["per_share_annual"] == pytest.approx(4.0)       # native, unconverted
    assert h["annual_income"] == pytest.approx(56.0)         # 4.0 * 10 * 1.4
    # Yield is native-over-native, so FX must not change it.
    assert h["current_yield_pct"] == pytest.approx(1.0, abs=0.01)


# --- calendar & summary -----------------------------------------------------

def test_payment_calendar_spreads_income_over_paying_months():
    rows = [{"symbol": "A", "annual_income": 1200.0, "months": list(range(1, 13))},
            {"symbol": "B", "annual_income": 400.0, "months": [3, 6, 9, 12]}]
    cal = dv.payment_calendar(rows)
    assert len(cal) == 12
    assert cal[0]["amount"] == pytest.approx(100.0)            # Jan: A only
    assert cal[2]["amount"] == pytest.approx(200.0)            # Mar: A + B
    assert "B" in cal[2]["symbols"] and "B" not in cal[0]["symbols"]
    assert sum(m["amount"] for m in cal) == pytest.approx(1600.0)


def test_summarize_totals_and_text():
    pos = [{"symbol": "XDIV.TO", "shares": 300, "entry_price": 43.26},
           {"symbol": "KTOS", "shares": 1, "entry_price": 48.54}]
    divs = {"XDIV.TO": _monthly(0.12), "KTOS": pd.Series(dtype=float)}
    prices = {"XDIV.TO": 46.42, "KTOS": 47.35}
    r = dv.summarize(pos, divs, prices, target_currency="CAD", today=TODAY)
    assert r["payers"] == 1 and r["non_payers"] == ["KTOS"]
    assert r["total_annual_income"] == pytest.approx(432.0)
    assert r["monthly_average"] == pytest.approx(36.0)
    assert r["portfolio_yield_pct"] is not None
    assert "432" in r["text"] and "CAD" in r["text"]
    assert r["holdings"][0]["symbol"] == "XDIV.TO"             # biggest payer first


def test_summarize_empty_and_all_non_payers():
    assert "No positions" in dv.summarize([], {}, today=TODAY)["text"]
    r = dv.summarize([{"symbol": "KTOS", "shares": 1, "entry_price": 10}],
                     {"KTOS": pd.Series(dtype=float)}, today=TODAY)
    assert r["total_annual_income"] is None
    assert "None of your holdings" in r["text"]
