"""Tests for the SCN-026 custom technical filter builder."""
import pandas as pd
import pytest

from tradelab.core.config import ScannerConfig
from tradelab.core.filters import FilterCondition, evaluate_condition, passes_custom_filters


@pytest.fixture
def row():
    return pd.Series({
        "Close": 100.0, "Volume": 1_000_000, "REL_VOL": 2.5,
        "RSI14": 75.0, "ATR14": 3.0, "ATRPCT14": 3.0, "ADX14": 28.0,
        "MACD": 1.2, "MACD_SIGNAL": 0.9, "MACD_HIST": 0.3,
        "EMA9": 101.0, "EMA30": 98.0,
        "SMA20": 99.0, "SMA50": 95.0, "SMA200": 90.0,
        "BB_UPPER": 105.0, "BB_LOWER": 95.0,
        "VWAP": 97.0, "STOCHK14": 82.0, "STOCHD14": 78.0, "WILLR14": -18.0,
        "CCI20": 120.0, "ROC12": 4.5, "OBV": 5_000_000.0, "MFI14": 60.0,
    })


@pytest.fixture
def cfg():
    return ScannerConfig()


def test_above_operator(row, cfg):
    assert evaluate_condition(row, cfg, FilterCondition(field="rsi14", operator="Above", value1=70)) is True
    assert evaluate_condition(row, cfg, FilterCondition(field="rsi14", operator="Above", value1=80)) is False


def test_below_operator(row, cfg):
    assert evaluate_condition(row, cfg, FilterCondition(field="rsi14", operator="Below", value1=80)) is True
    assert evaluate_condition(row, cfg, FilterCondition(field="rsi14", operator="Below", value1=70)) is False


def test_between_operator(row, cfg):
    cond = FilterCondition(field="rsi14", operator="Between", value1=60, value2=80)
    assert evaluate_condition(row, cfg, cond) is True
    cond = FilterCondition(field="rsi14", operator="Between", value1=80, value2=90)
    assert evaluate_condition(row, cfg, cond) is False


def test_between_operator_handles_reversed_bounds(row, cfg):
    # value1/value2 out of order (e.g. user typed max before min) should
    # still work rather than silently excluding every symbol.
    cond = FilterCondition(field="rsi14", operator="Between", value1=80, value2=60)
    assert evaluate_condition(row, cfg, cond) is True


def test_atr_percent_is_computed_not_a_raw_column(row, cfg):
    # ATR14=3.0, Close=100.0 -> 3% ATR.
    assert evaluate_condition(row, cfg, FilterCondition(field="atr_percent", operator="Above", value1=2)) is True
    assert evaluate_condition(row, cfg, FilterCondition(field="atr_percent", operator="Above", value1=4)) is False


def test_ema_fields_use_cfg_periods(row, cfg):
    cfg.ema_fast, cfg.ema_slow = 9, 30
    assert evaluate_condition(row, cfg, FilterCondition(field="ema_fast", operator="Above", value1=100)) is True
    assert evaluate_condition(row, cfg, FilterCondition(field="ema_slow", operator="Above", value1=100)) is False


def test_missing_value_fails_the_condition(cfg):
    row = pd.Series({"Close": 100.0})  # no RSI14 column at all
    assert evaluate_condition(row, cfg, FilterCondition(field="rsi14", operator="Above", value1=0)) is False


def test_nan_value_fails_the_condition(cfg):
    row = pd.Series({"RSI14": float("nan")})
    assert evaluate_condition(row, cfg, FilterCondition(field="rsi14", operator="Above", value1=0)) is False


def test_unknown_field_does_not_exclude_everything(row, cfg):
    # Forward-compat: a setup file from a newer version referencing a field
    # this version doesn't know about shouldn't silently zero out every scan.
    cond = FilterCondition(field="totally_made_up_field", operator="Above", value1=0)
    assert evaluate_condition(row, cfg, cond) is True


def test_passes_custom_filters_requires_all_conditions(row, cfg):
    conditions = [
        FilterCondition(field="rsi14", operator="Above", value1=70),
        FilterCondition(field="macd_hist", operator="Above", value1=0),
    ]
    assert passes_custom_filters(row, cfg, conditions) is True

    conditions.append(FilterCondition(field="adx14", operator="Above", value1=50))  # ADX is 28, fails
    assert passes_custom_filters(row, cfg, conditions) is False


def test_passes_custom_filters_with_no_conditions_always_passes(row, cfg):
    assert passes_custom_filters(row, cfg, []) is True


def test_condition_serialization_round_trip():
    cond = FilterCondition(field="rsi14", operator="Between", value1=30, value2=70)
    restored = FilterCondition.from_dict(cond.to_dict())
    assert restored == cond


def test_condition_label():
    assert FilterCondition(field="rsi14", operator="Above", value1=70).label() == "RSI 14 above 70"
    assert FilterCondition(field="rsi14", operator="Between", value1=30, value2=70).label() == "RSI 14 between 30 and 70"


def test_period_is_tunable_and_reflected_in_label_and_column():
    # Pick RSI but change its period to 7 - reads the RSI7 column.
    cond = FilterCondition(field="rsi", operator="Above", value1=50, period=7)
    row = pd.Series({"RSI7": 60.0, "RSI14": 40.0})
    assert evaluate_condition(row, ScannerConfig(), cond) is True  # RSI7=60 > 50
    assert cond.label() == "RSI 7 above 50"


def test_ensure_columns_computes_requested_period():
    import numpy as np
    from tradelab.core.filters import ensure_columns
    df = pd.DataFrame({"Open": range(1, 101), "High": range(2, 102),
                       "Low": range(0, 100), "Close": range(1, 101), "Volume": [1000] * 100})
    conds = [FilterCondition(field="ema", operator="Above", value1=0, period=15),
             FilterCondition(field="rsi", operator="Above", value1=0, period=9)]
    ensure_columns(df, conds)
    assert "EMA15" in df.columns
    assert "RSI9" in df.columns


# -- Phase 5: field-vs-field comparison (A) -------------------------------

def test_above_field_compares_two_indicators(row, cfg):
    # EMA9 (101) above EMA30 (98) -> a bullish trend / crossover condition.
    cond = FilterCondition(field="ema_fast", operator="Above field", field2="ema_slow")
    assert evaluate_condition(row, cfg, cond) is True
    # And the reverse is false.
    cond = FilterCondition(field="ema_slow", operator="Above field", field2="ema_fast")
    assert evaluate_condition(row, cfg, cond) is False


def test_below_field_compares_two_indicators(row, cfg):
    # Close (100) above VWAP (97) -> "Close below VWAP" is false.
    cond = FilterCondition(field="price", operator="Below field", field2="vwap")
    assert evaluate_condition(row, cfg, cond) is False
    cond = FilterCondition(field="price", operator="Above field", field2="vwap")
    assert evaluate_condition(row, cfg, cond) is True


def test_field_operator_label_reads_naturally():
    cond = FilterCondition(field="ema_fast", operator="Above field", field2="ema_slow")
    assert cond.label() == "EMA 9 above EMA 30"


def test_field_operator_unknown_compared_field_does_not_exclude(row, cfg):
    cond = FilterCondition(field="rsi14", operator="Above field", field2="made_up")
    assert evaluate_condition(row, cfg, cond) is True


def test_field_operator_round_trips_through_dict():
    cond = FilterCondition(field="macd", operator="Above field", field2="macd_signal")
    restored = FilterCondition.from_dict(cond.to_dict())
    assert restored == cond


@pytest.mark.parametrize("field,expected", [
    ("vwap", True), ("stoch_k", True), ("williams_r", False),  # WILLR -18 not > 0
    ("cci20", True), ("roc12", True), ("mfi14", True),
])
def test_new_indicator_fields_are_usable(row, cfg, field, expected):
    # Above 0 is true for the positive-valued new fields, false for Williams %R (negative).
    cond = FilterCondition(field=field, operator="Above", value1=0)
    assert evaluate_condition(row, cfg, cond) is expected
