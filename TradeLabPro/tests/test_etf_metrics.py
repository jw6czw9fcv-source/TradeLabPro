"""Tests for tradelab.core.etf_metrics — synthetic price series only, no live
yfinance call, matching the rest of the suite's rule."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core.etf_metrics import (
    COMPOSITION_ROWS, PERIODS, composition_summary, compute_metrics,
    risk_metrics, trailing_return,
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
         "ret_10a": 0.16, "ma_compo": 0.5, "reco_star": 0.2},
        {"ticker": "VAB", "pct_can": 0.0, "pct_us": 0.0, "pct_intl": 0.0,
         "pct_bond": 1.0, "pct_gold": 0.0, "risk": 1, "mer": 0.0009,
         "ret_10a": 0.02, "ma_compo": 0.5, "reco_star": 0.8},
    ]


def test_composition_total_is_the_sum_of_weights():
    assert composition_summary(_book())["total"] == pytest.approx(1.0)


def test_composition_weights_the_regional_split():
    rows = composition_summary(_book())["rows"]
    assert rows["pct_us"]["value"] == pytest.approx(0.5)
    assert rows["pct_bond"]["value"] == pytest.approx(0.5)
    assert rows["pct_gold"]["value"] == pytest.approx(0.0)


def test_composition_reads_the_weight_column_it_is_given():
    rows = composition_summary(_book(), "reco_star")["rows"]
    assert rows["pct_us"]["value"] == pytest.approx(0.2)
    assert rows["risk"]["value"] == pytest.approx(0.2 * 4 + 0.8 * 1)


def test_composition_ignores_funds_with_no_weight():
    book = _book() + [{"ticker": "SMH", "pct_us": 1.0, "risk": 5}]  # no ma_compo
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
