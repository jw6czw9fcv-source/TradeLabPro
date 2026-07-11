"""Shared pytest fixtures.

Tests must never depend on live network calls (yfinance is flaky/rate
limited) - everything here is deterministic synthetic data, matching the
existing synthetic_ohlcv() fallback already used by the app itself.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Headless Qt for any widget-instantiation tests.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    periods = 260
    dates = pd.date_range(end=pd.Timestamp("2026-07-01"), periods=periods, freq="B")
    returns = rng.normal(0.0006, 0.015, size=periods)
    close = 100 * np.exp(np.cumsum(returns))
    open_ = close * (1 + rng.normal(0, 0.005, size=periods))
    high = np.maximum(open_, close) * (1 + rng.random(periods) * 0.012)
    low = np.minimum(open_, close) * (1 - rng.random(periods) * 0.012)
    volume = rng.integers(400_000, 4_000_000, size=periods)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


@pytest.fixture
def tmp_db_path(tmp_path):
    return tmp_path / "test_tradelab.db"
