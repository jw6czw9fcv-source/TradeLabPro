"""Tests for tradelab.core.etf_metrics — synthetic price series only, no live
yfinance call, matching the rest of the suite's rule."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core.etf_metrics import (
    COMPOSITION_ROWS, PERIODS, composition_summary, compute_metrics,
    fund_symbol, overlaps, rebalance, risk_metrics, trailing_return,
)


def _flat(days: int, start: float = 100.0) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=days, freq="D")
    return pd.Series([start] * days, index=idx)


def _growth(days: int, daily_return: float, start: float = 100.0) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=days, freq="D")
    return pd.Series(start * (1 + daily_return) ** np.arange(days), index=idx)


# -- trailing returns -------------------------------------------------------

def test_trailing_return_flat_series_is_zero():
    assert trailing_return(_flat(400), 30, None) == pytest.approx(0.0, abs=1e-9)


def test_trailing_return_insufficient_history_is_none():
    assert trailing_return(_flat(20), 365, 1) is None


def test_trailing_return_annualizes_over_multiple_years():
    # +10%/year compounded for three years must come back as ~10%, not ~33%.
    prices = _growth(3 * 365 + 5, daily_return=(1.10 ** (1 / 365.25)) - 1)
    assert trailing_return(prices, 3 * 365, 3) == pytest.approx(0.10, abs=0.01)


def test_trailing_return_under_a_year_is_not_annualized():
    prices = _growth(200, daily_return=(1.10 ** (1 / 365.25)) - 1)
    six_months = trailing_return(prices, 182, None)
    assert 0.03 < six_months < 0.06     # roughly half a 10% year, un-annualized


def test_trailing_return_empty_series_is_none():
    assert trailing_return(pd.Series(dtype=float), 30, None) is None


# -- risk -------------------------------------------------------------------

def test_risk_metrics_insufficient_history_returns_none_triplet():
    assert risk_metrics(_flat(10)) == (None, None, None)


def test_risk_metrics_flat_series_has_zero_vol_and_drawdown():
    vol, dd, _sharpe = risk_metrics(_flat(400))
    assert vol == pytest.approx(0.0, abs=1e-9)
    assert dd == pytest.approx(0.0, abs=1e-9)


def test_risk_metrics_drawdown_is_negative_after_a_drop():
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=200, freq="D")
    prices = pd.Series([100.0] * 100 + [70.0] * 100, index=idx)
    _vol, dd, _sharpe = risk_metrics(prices)
    assert dd == pytest.approx(-0.30, abs=0.01)


def test_risk_metrics_sharpe_is_negative_when_growth_lags_the_risk_free_rate():
    # ~1%/year against a 3% risk-free rate: the excess return is negative, so
    # a positive Sharpe here would mean the risk-free rate was ignored.
    rng = np.random.default_rng(7)
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=800, freq="D")
    drift = (1.01 ** (1 / 365.25)) - 1
    noise = rng.normal(0, 0.004, size=800)
    prices = pd.Series(100 * np.cumprod(1 + drift + noise), index=idx)
    _vol, _dd, sharpe = risk_metrics(prices)
    assert sharpe is not None and sharpe < 0


# -- compute_metrics --------------------------------------------------------

def test_compute_metrics_with_short_history_returns_only_short_windows():
    metrics = compute_metrics("SYNTH", prices=_flat(100))   # 1M/3M yes, 1A no
    assert metrics is not None
    assert "ret_1m" in metrics
    assert "ret_1a" not in metrics      # never fabricated


def test_compute_metrics_too_short_returns_none():
    assert compute_metrics("SYNTH", prices=_flat(5)) is None


def test_compute_metrics_includes_risk_columns_on_long_history():
    metrics = compute_metrics("SYNTH", prices=_growth(800, 0.0002))
    assert {"volatility", "max_drawdown", "sharpe"} <= set(metrics)


def test_periods_cover_expected_columns():
    assert set(PERIODS) == {
        "ret_1m", "ret_3m", "ret_6m", "ret_1a", "ret_3a", "ret_5a", "ret_10a",
    }


# -- composition summary ----------------------------------------------------

def _book():
    return [
        {"ticker": "VFV", "pct_can": 0.0, "pct_us": 1.0, "pct_intl": 0.0,
         "pct_bond": 0.0, "pct_gold": 0.0, "risk": 4, "mer": 0.0009,
         "ret_10a": 0.16, "my_mix": 0.5, "mid_risk": 0.2},
        {"ticker": "VAB", "pct_can": 0.0, "pct_us": 0.0, "pct_intl": 0.0,
         "pct_bond": 1.0, "pct_gold": 0.0, "risk": 1, "mer": 0.0009,
         "ret_10a": 0.02, "my_mix": 0.5, "mid_risk": 0.8},
    ]


def test_composition_total_is_the_sum_of_weights():
    assert composition_summary(_book())["total"] == pytest.approx(1.0)


def test_composition_weights_the_regional_split():
    rows = composition_summary(_book())["rows"]
    assert rows["pct_us"]["value"] == pytest.approx(0.5)
    assert rows["pct_bond"]["value"] == pytest.approx(0.5)
    assert rows["pct_gold"]["value"] == pytest.approx(0.0)


def test_composition_reads_the_weight_column_it_is_given():
    rows = composition_summary(_book(), "mid_risk")["rows"]
    assert rows["pct_us"]["value"] == pytest.approx(0.2)
    assert rows["risk"]["value"] == pytest.approx(0.2 * 4 + 0.8 * 1)


def test_composition_ignores_funds_with_no_weight():
    book = _book() + [{"ticker": "SMH", "pct_us": 1.0, "risk": 5}]  # no my_mix
    assert composition_summary(book)["total"] == pytest.approx(1.0)
    assert composition_summary(book)["rows"]["pct_us"]["value"] == pytest.approx(0.5)


def test_composition_reports_coverage_when_a_column_is_missing():
    book = _book()
    book[1]["ret_10a"] = None            # one fund has no ten-year number
    cell = composition_summary(book)["rows"]["ret_10a"]
    assert cell["value"] == pytest.approx(0.5 * 0.16)
    # Half the allocation is behind that figure; the caller has to say so.
    assert cell["covered"] == pytest.approx(0.5)


def test_composition_of_an_empty_book_is_all_zeros():
    summary = composition_summary([])
    assert summary["total"] == 0
    assert all(cell["covered"] == 0 for cell in summary["rows"].values())


def test_composition_rows_only_reference_real_columns():
    from tradelab.data.database import Database
    for _label, column, kind in COMPOSITION_ROWS:
        assert column in Database.ETF_COLUMNS
        assert kind in {"pct", "num"}


# -- rebalance: the target against what is actually held --------------------

def _plan():
    return [
        {"ticker": "VFV", "yahoo": "VFV.TO", "my_mix": 0.6},
        {"ticker": "VAB", "yahoo": "VAB.TO", "my_mix": 0.4},
    ]


def _holdings(vfv=60_000.0, vab=40_000.0):
    return [{"symbol": "VFV.TO", "market_value": vfv},
            {"symbol": "VAB.TO", "market_value": vab}]


def test_rebalance_on_plan_book_has_no_drift():
    result = rebalance(_plan(), _holdings())
    assert result["total"] == pytest.approx(100_000)
    for row in result["rows"]:
        assert row["drift_pct"] == pytest.approx(0.0)
        assert row["amount"] == pytest.approx(0.0)


def test_rebalance_reports_what_to_buy_and_trim():
    result = rebalance(_plan(), _holdings(vfv=80_000, vab=20_000))
    by_ticker = {r["ticker"]: r for r in result["rows"]}
    assert by_ticker["VFV"]["actual_pct"] == pytest.approx(0.8)
    assert by_ticker["VFV"]["amount"] == pytest.approx(-20_000)   # trim
    assert by_ticker["VAB"]["amount"] == pytest.approx(20_000)    # buy


def test_rebalance_matches_on_the_yahoo_symbol():
    # The book holds VFV.TO; the plan's ticker column says VFV.
    result = rebalance(_plan(), [{"symbol": "VFV.TO", "market_value": 100.0}])
    assert result["rows"][0]["market_value"] == pytest.approx(100.0)


def test_rebalance_measures_against_the_whole_book_not_just_the_plan():
    """A plan covering half the book must not report that half as the whole,
    or a target is 'met' while the rest sits somewhere it never mentioned."""
    book = _holdings(vfv=30_000, vab=20_000) + [{"symbol": "NVDA", "market_value": 50_000}]
    result = rebalance(_plan(), book)
    assert result["total"] == pytest.approx(100_000)
    assert result["covered"] == pytest.approx(0.5)
    assert result["unmatched"] == ["NVDA"]
    by_ticker = {r["ticker"]: r for r in result["rows"]}
    assert by_ticker["VFV"]["actual_pct"] == pytest.approx(0.3)   # not 0.6


def test_rebalance_lists_a_target_never_bought():
    result = rebalance(_plan(), [{"symbol": "VFV.TO", "market_value": 100.0}])
    vab = [r for r in result["rows"] if r["ticker"] == "VAB"][0]
    assert vab["market_value"] == 0
    assert vab["amount"] > 0


def test_rebalance_lists_a_holding_with_no_target():
    funds = [{"ticker": "VFV", "yahoo": "VFV.TO", "my_mix": 0.0}]
    result = rebalance(funds, [{"symbol": "VFV.TO", "market_value": 100.0}])
    assert result["rows"][0]["target_pct"] == 0
    assert result["rows"][0]["amount"] == pytest.approx(-100.0)


def test_rebalance_of_an_empty_book_does_not_divide_by_zero():
    result = rebalance(_plan(), [])
    assert result["total"] == 0
    assert all(r["actual_pct"] == 0 for r in result["rows"])


def test_rebalance_sorts_by_how_far_off_it_is():
    funds = _plan() + [{"ticker": "ZLB", "yahoo": "ZLB.TO", "my_mix": 0.0}]
    result = rebalance(funds, _holdings(vfv=90_000, vab=10_000))
    assert result["rows"][0]["ticker"] in {"VFV", "VAB"}
    drifts = [abs(r["drift_pct"]) for r in result["rows"]]
    assert drifts == sorted(drifts, reverse=True)


# -- overlaps: the same exposure bought twice --------------------------------

def _twins():
    canada = {"pct_can": 1.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 0.0, "pct_gold": 0.0}
    return [
        {"ticker": "VCN", "category": "Canadian equity", "my_mix": 0.2, **canada},
        {"ticker": "XIC", "category": "Canadian equity", "my_mix": 0.1, **canada},
        {"ticker": "VAB", "category": "Bonds", "my_mix": 0.3,
         "pct_can": 0.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 1.0, "pct_gold": 0.0},
    ]


def test_overlap_flags_two_funds_buying_the_same_market():
    found = overlaps(_twins())
    assert len(found) == 1
    assert {found[0]["a"], found[0]["b"]} == {"VCN", "XIC"}
    assert found[0]["combined_weight"] == pytest.approx(0.3)


def test_overlap_ignores_a_fund_with_no_weight():
    funds = _twins()
    funds[1]["my_mix"] = 0.0        # XIC listed but not allocated to
    assert overlaps(funds) == []


def test_overlap_does_not_flag_genuinely_different_exposures():
    funds = [
        {"ticker": "VFV", "category": "S&P 500", "my_mix": 0.5,
         "pct_can": 0.0, "pct_us": 1.0, "pct_intl": 0.0, "pct_bond": 0.0, "pct_gold": 0.0},
        {"ticker": "VAB", "category": "Bonds", "my_mix": 0.5,
         "pct_can": 0.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 1.0, "pct_gold": 0.0},
    ]
    assert overlaps(funds) == []


def test_overlap_falls_back_to_category_when_the_mix_is_blank():
    funds = [{"ticker": "VCN", "category": "Canadian equity", "my_mix": 0.2},
             {"ticker": "XIC", "category": "Canadian equity", "my_mix": 0.2}]
    found = overlaps(funds)
    assert found and found[0]["reason"] == "same category"
    assert found[0]["distance"] is None


def test_overlap_guesses_nothing_with_neither_mix_nor_category():
    funds = [{"ticker": "AAA", "my_mix": 0.5}, {"ticker": "BBB", "my_mix": 0.5}]
    assert overlaps(funds) == []


def test_overlap_reads_the_weight_column_it_is_given():
    funds = _twins()
    for fund in funds:
        fund["low_risk"] = 0.0
    assert overlaps(funds, "low_risk") == []
    assert overlaps(funds, "my_mix")


def test_fund_symbol_prefers_the_yahoo_listing():
    assert fund_symbol({"ticker": "VFV", "yahoo": "VFV.TO"}) == "VFV.TO"
    assert fund_symbol({"ticker": "vug"}) == "VUG"
    assert fund_symbol({}) == ""
