"""Tests for tradelab/core/confidence.py - transparent confidence scoring
tied to backtest stats (third piece of SCN-030).
"""
import numpy as np
import pandas as pd
import pytest

from tradelab.core.config import ScannerConfig
from tradelab.core.confidence import historical_confidence


class _FakeStrategy:
    """A strategy stub whose signal_series is fully controlled by the test,
    independent of any real indicator computation.
    """
    def __init__(self, signals):
        self._signals = signals

    def signal_series(self, df, cfg):
        return pd.Series(self._signals, index=df.index)


def _closes(values):
    return pd.DataFrame({"Close": values})


def test_no_buy_signals_returns_none_confidence():
    df = _closes([100] * 20)
    strat = _FakeStrategy([""] * 20)
    result = historical_confidence(df, strat, ScannerConfig(), horizon=5)
    assert result["confidence"] is None
    assert result["sample_size"] == 0


def test_all_winning_buy_signals_gives_100_percent_confidence():
    closes = list(range(100, 120))  # steadily rising
    df = _closes(closes)
    signals = [""] * 20
    signals[0] = "BUY"
    signals[5] = "BUY"
    strat = _FakeStrategy(signals)
    result = historical_confidence(df, strat, ScannerConfig(), horizon=5)
    assert result["confidence"] == 100.0
    assert result["sample_size"] == 2
    assert result["avg_forward_return"] > 0


def test_all_losing_buy_signals_gives_0_percent_confidence():
    closes = list(range(120, 100, -1))  # steadily falling
    df = _closes(closes)
    signals = [""] * 20
    signals[0] = "BUY"
    strat = _FakeStrategy(signals)
    result = historical_confidence(df, strat, ScannerConfig(), horizon=5)
    assert result["confidence"] == 0.0
    assert result["avg_forward_return"] < 0


def test_mixed_outcomes_gives_partial_confidence():
    closes = [100, 100, 100, 100, 100, 110,  # BUY at 0 -> +10% at horizon 5
              100, 100, 100, 100, 100, 90]   # BUY at 6 -> -10% at horizon 5 (index 6+5=11)
    df = _closes(closes)
    signals = [""] * len(closes)
    signals[0] = "BUY"
    signals[6] = "BUY"
    strat = _FakeStrategy(signals)
    result = historical_confidence(df, strat, ScannerConfig(), horizon=5)
    assert result["sample_size"] == 2
    assert result["confidence"] == 50.0


def test_buy_signal_too_close_to_end_is_excluded_no_forward_data():
    df = _closes([100] * 10)
    signals = [""] * 10
    signals[8] = "BUY"  # only 1 bar left, horizon=5 needs 5
    strat = _FakeStrategy(signals)
    result = historical_confidence(df, strat, ScannerConfig(), horizon=5)
    assert result["sample_size"] == 0
    assert result["confidence"] is None


def test_strategy_signal_series_raising_is_handled_gracefully():
    class _BrokenStrategy:
        def signal_series(self, df, cfg):
            raise RuntimeError("boom")
    df = _closes([100] * 10)
    result = historical_confidence(df, _BrokenStrategy(), ScannerConfig())
    assert result["confidence"] is None
    assert result["sample_size"] == 0
