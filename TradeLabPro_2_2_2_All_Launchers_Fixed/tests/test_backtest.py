"""Tests for the Phase 4 Backtesting Lab engine (tradelab/core/backtest.py).

get_history is monkeypatched to the deterministic ohlcv_df fixture so these
run offline and reproducibly.
"""
import numpy as np
import pandas as pd
import pytest

import tradelab.core.backtest as bt
from tradelab.core.backtest import (
    simulate, backtest_symbol, backtest_multi, optimize, walk_forward, BacktestResult,
)
from tradelab.core.config import ScannerConfig
from tradelab.core.indicators import add_indicators


@pytest.fixture
def indicators(ohlcv_df):
    cfg = ScannerConfig()
    return add_indicators(ohlcv_df, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal).dropna()


@pytest.fixture(autouse=True)
def _fake_history(monkeypatch, ohlcv_df):
    monkeypatch.setattr("tradelab.data.market_data.get_history", lambda s, p, i: ohlcv_df)


def test_simulate_returns_result_with_metrics_and_equity(indicators):
    res = simulate(indicators, ScannerConfig(), __import__("tradelab.strategies.ema_macd", fromlist=["x"]))
    assert isinstance(res, BacktestResult)
    for key in ["Trades", "Win rate %", "Total return %", "Max drawdown %"]:
        assert key in res.metrics
    assert res.equity[0] == 100.0  # equity curve starts at base 100


def test_simulate_empty_frame_is_safe():
    res = simulate(pd.DataFrame(), ScannerConfig(), __import__("tradelab.strategies.ema_macd", fromlist=["x"]))
    assert res.trades.empty
    assert res.metrics["Trades"] == 0


def test_max_drawdown_is_nonnegative(indicators):
    from tradelab.strategies import ema_macd
    res = simulate(indicators, ScannerConfig(), ema_macd)
    assert res.metrics["Max drawdown %"] >= 0


def test_max_drawdown_computation_known_sequence():
    # +10%, -50%, then flat -> peak 1.1, trough 0.55 -> 50% drawdown.
    assert bt._max_drawdown_pct([10, -50]) == pytest.approx(50.0, abs=0.01)


def test_backtest_symbol_uses_selected_strategy(ohlcv_df):
    cfg = ScannerConfig()
    ema = backtest_symbol("AAPL", cfg, "ema_macd")
    rsi = backtest_symbol("AAPL", cfg, "rsi_reversion")
    # Both produce valid results; they need not be identical (different rules).
    assert "Total return %" in ema.metrics
    assert "Total return %" in rsi.metrics


def test_backtest_symbol_not_enough_data(monkeypatch):
    monkeypatch.setattr("tradelab.data.market_data.get_history", lambda s, p, i: pd.DataFrame({"Close": [1, 2, 3]}))
    res = backtest_symbol("AAPL", ScannerConfig())
    assert res.metrics.get("Error") == "Not enough data"


def test_backtest_multi_aggregates_across_symbols():
    result = backtest_multi(["AAPL", "MSFT", "GOOG"], ScannerConfig(), "ema_macd")
    per = result["per_symbol"]
    agg = result["aggregate"]
    assert len(per) == 3
    assert set(["Symbol", "Trades", "Win rate %", "Total return %"]).issubset(per.columns)
    assert agg["Symbols tested"] == 3
    assert "Overall win rate %" in agg


def test_backtest_multi_respects_should_stop():
    calls = {"n": 0}
    def should_stop():
        calls["n"] += 1
        return calls["n"] > 1  # stop after first symbol processed
    result = backtest_multi(["AAPL", "MSFT", "GOOG", "AMZN"], ScannerConfig(), "ema_macd", should_stop=should_stop)
    assert len(result["per_symbol"]) < 4


def test_optimize_sweeps_parameter_and_sorts_by_metric():
    df = optimize("AAPL", ScannerConfig(), "ema_slow", [20, 30, 40, 50], strategy_key="ema_macd", metric="Total return %")
    assert "ema_slow" in df.columns
    assert len(df) == 4
    # Sorted best-first by Total return %.
    assert df["Total return %"].tolist() == sorted(df["Total return %"].tolist(), reverse=True)


def test_walk_forward_splits_into_windows():
    result = walk_forward("AAPL", ScannerConfig(), n_splits=3, strategy_key="ema_macd")
    windows = result["windows"]
    assert len(windows) == 3
    assert list(windows["Window"]) == [1, 2, 3]
    assert 0 <= result["consistency"] <= 100


def test_walk_forward_windows_are_sequential_and_non_overlapping():
    result = walk_forward("AAPL", ScannerConfig(), n_splits=3, strategy_key="ema_macd")
    windows = result["windows"]
    tos = list(windows["To"])
    froms = list(windows["From"])
    # Each window starts on/after the previous window's start (sequential).
    assert froms == sorted(froms)
    assert tos == sorted(tos)


def test_walk_forward_too_few_bars_returns_empty(monkeypatch):
    monkeypatch.setattr("tradelab.data.market_data.get_history",
                        lambda s, p, i: pd.DataFrame({"Open": range(90), "High": range(90),
                                                      "Low": range(90), "Close": range(90), "Volume": [1]*90}))
    result = walk_forward("AAPL", ScannerConfig(), n_splits=4)
    assert result["windows"].empty
