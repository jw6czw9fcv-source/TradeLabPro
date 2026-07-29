"""Tests for the SCN-030 multi-strategy registry and both strategy modules."""
import pandas as pd
import pytest

from tradelab.core.config import ScannerConfig
from tradelab.core.indicators import add_indicators
from tradelab.strategies import STRATEGIES, DEFAULT_STRATEGY, strategy_module, strategy_choices
from tradelab.strategies import ema_macd, rsi_reversion


def test_default_strategy_is_registered():
    assert DEFAULT_STRATEGY in STRATEGIES


def test_strategy_module_falls_back_to_default_for_unknown_key():
    assert strategy_module("totally_made_up") is STRATEGIES[DEFAULT_STRATEGY]


def test_strategy_module_returns_correct_module_for_known_key():
    assert strategy_module("rsi_reversion") is rsi_reversion


def test_strategy_choices_include_both_strategies_with_display_names():
    choices = dict(strategy_choices())
    assert choices["ema_macd"] == "EMA/MACD Trend"
    assert choices["rsi_reversion"] == "RSI Mean-Reversion"


@pytest.mark.parametrize("module", [ema_macd, rsi_reversion])
def test_each_strategy_module_has_the_expected_interface(module):
    assert hasattr(module, "NAME")
    assert hasattr(module, "score_symbol")
    assert hasattr(module, "signal_series")


@pytest.mark.parametrize("module", [ema_macd, rsi_reversion])
def test_score_symbol_returns_expected_shape(module, ohlcv_df):
    cfg = ScannerConfig()
    result = module.score_symbol(ohlcv_df, cfg)
    assert set(result.keys()) >= {"signal", "score", "data"}
    assert result["signal"] in ("BUY", "SELL", "WATCH", "HOLD")
    assert 0 <= result["score"] <= 100
    assert isinstance(result["data"], pd.DataFrame)


@pytest.mark.parametrize("module", [ema_macd, rsi_reversion])
def test_signal_series_returns_a_series_aligned_to_input(module, ohlcv_df):
    cfg = ScannerConfig()
    indicators = add_indicators(ohlcv_df, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    series = module.signal_series(indicators, cfg)
    assert len(series) == len(indicators)
    assert set(series.unique()) <= {"", "BUY", "SELL"}
