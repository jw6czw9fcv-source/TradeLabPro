"""Tests for Phase 5 user-defined no-code strategies."""
import importlib

import numpy as np
import pandas as pd
import pytest

from tradelab.core.config import ScannerConfig
from tradelab.core.filters import FilterCondition
from tradelab.core.indicators import add_indicators


@pytest.fixture
def custom_env(tmp_path, monkeypatch):
    """Point DATA_DIR at a tmp dir so saved strategies never touch the real
    data/ folder, and reload the modules that captured DATA_DIR at import."""
    monkeypatch.setattr("tradelab.core.config.DATA_DIR", tmp_path)
    import tradelab.strategies.custom as custom
    monkeypatch.setattr(custom, "DATA_DIR", tmp_path)
    return custom


def _indicators():
    rng = np.random.default_rng(7)
    n = 260
    dates = pd.date_range(end=pd.Timestamp("2026-07-01"), periods=n, freq="B")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.015, n)))
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                       "Close": close, "Volume": rng.integers(1e6, 5e6, n)}, index=dates)
    cfg = ScannerConfig()
    return add_indicators(df, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal).dropna()


def test_custom_strategy_round_trips_through_disk(custom_env):
    strat = custom_env.CustomStrategy(
        "My RSI Dip",
        buy_conditions=[FilterCondition(field="rsi14", operator="Below", value1=35)],
        sell_conditions=[FilterCondition(field="rsi14", operator="Above", value1=65)],
    )
    strat.save()
    assert "My RSI Dip" in custom_env.list_custom_strategies()

    loaded = custom_env.load_custom_strategy("My RSI Dip")
    assert loaded is not None
    assert loaded.name == "My RSI Dip"
    assert loaded.buy_conditions[0].field == "rsi"  # legacy "rsi14" migrated
    assert loaded.buy_conditions[0].period == 14
    assert loaded.sell_conditions[0].operator == "Above"


def test_delete_custom_strategy(custom_env):
    custom_env.CustomStrategy("Temp", [], []).save()
    assert "Temp" in custom_env.list_custom_strategies()
    assert custom_env.delete_custom_strategy("Temp") is True
    assert "Temp" not in custom_env.list_custom_strategies()
    assert custom_env.delete_custom_strategy("Temp") is False  # already gone


def test_load_missing_strategy_returns_none(custom_env):
    assert custom_env.load_custom_strategy("does-not-exist") is None


def test_signal_series_fires_on_rising_edge(custom_env):
    # BUY when RSI < 40 - should fire the bar RSI first drops below 40,
    # not on every subsequent oversold bar.
    strat = custom_env.CustomStrategy(
        "Dip", [FilterCondition(field="rsi14", operator="Below", value1=40)], [])
    df = _indicators()
    signals = strat.signal_series(df, ScannerConfig())
    assert set(signals.unique()) <= {"", "BUY", "SELL"}
    # Every BUY bar must have RSI < 40 and the prior bar must NOT (rising edge).
    for i in range(1, len(df)):
        if signals.iloc[i] == "BUY":
            assert df["RSI14"].iloc[i] < 40
            assert not (df["RSI14"].iloc[i - 1] < 40)


def test_no_buy_conditions_produces_no_buys(custom_env):
    strat = custom_env.CustomStrategy("Empty", [], [])
    signals = strat.signal_series(_indicators(), ScannerConfig())
    assert (signals == "BUY").sum() == 0


def test_ema_crossover_via_field_operator_produces_signals(custom_env):
    # The whole point of field-vs-field: express an EMA crossover with no code.
    # BUY when fast EMA crosses above slow EMA; SELL when it crosses below.
    strat = custom_env.CustomStrategy(
        "EMA Cross",
        buy_conditions=[FilterCondition(field="ema_fast", operator="Above field", field2="ema_slow")],
        sell_conditions=[FilterCondition(field="ema_fast", operator="Below field", field2="ema_slow")],
    )
    df = _indicators()
    cfg = ScannerConfig()
    signals = strat.signal_series(df, cfg)
    # A trending random series should cross at least once each way.
    assert (signals == "BUY").sum() >= 1
    assert (signals == "SELL").sum() >= 1
    # Each BUY bar: fast>slow now and NOT on the prior bar (a real crossover).
    fast, slow = f"EMA{cfg.ema_fast}", f"EMA{cfg.ema_slow}"
    for i in range(1, len(df)):
        if signals.iloc[i] == "BUY":
            assert df[fast].iloc[i] > df[slow].iloc[i]
            assert not (df[fast].iloc[i - 1] > df[slow].iloc[i - 1])


def test_score_symbol_returns_expected_shape(custom_env):
    strat = custom_env.CustomStrategy(
        "Trend", [FilterCondition(field="rsi14", operator="Above", value1=50)], [])
    rng = np.random.default_rng(1)
    n = 200
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    raw = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                        "Close": close, "Volume": [1_000_000] * n})
    result = strat.score_symbol(raw, ScannerConfig())
    assert set(result.keys()) >= {"signal", "score", "data"}
    assert 0 <= result["score"] <= 100
    assert result["signal"] in ("BUY", "SELL", "HOLD")


def test_registry_lists_custom_strategies(custom_env, monkeypatch):
    custom_env.CustomStrategy("Reg Test", [FilterCondition(field="rsi14", operator="Below", value1=30)], []).save()
    # Reload the registry so it picks up the tmp DATA_DIR + new file.
    import tradelab.strategies as registry
    importlib.reload(registry)
    monkeypatch.setattr(registry, "list_custom_strategies", custom_env.list_custom_strategies)
    monkeypatch.setattr(registry, "load_custom_strategy", custom_env.load_custom_strategy)

    choices = dict(registry.strategy_choices())
    assert "custom:Reg Test" in choices
    assert choices["custom:Reg Test"] == "Reg Test (custom)"

    strat = registry.strategy_module("custom:Reg Test")
    assert strat.name == "Reg Test"


def test_registry_unknown_custom_falls_back_to_default(custom_env, monkeypatch):
    import tradelab.strategies as registry
    monkeypatch.setattr(registry, "load_custom_strategy", lambda name: None)
    strat = registry.strategy_module("custom:ghost")
    assert strat is registry.STRATEGIES[registry.DEFAULT_STRATEGY]
