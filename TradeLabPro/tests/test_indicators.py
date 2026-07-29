import numpy as np
import pandas as pd

from tradelab.core.indicators import (
    add_indicators, ema, sma, rsi, atr, macd, bollinger, adx,
    vwap, pivot_points, supertrend, ichimoku, volume_profile, heikin_ashi,
    crossover_signal, signal_series, rsi_reversion_signal, rsi_reversion_signal_series,
)


def test_ema_matches_pandas_ewm(ohlcv_df):
    result = ema(ohlcv_df["Close"], 9)
    expected = ohlcv_df["Close"].ewm(span=9, adjust=False).mean()
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_sma_window(ohlcv_df):
    result = sma(ohlcv_df["Close"], 20)
    assert np.isnan(result.iloc[0])
    manual = ohlcv_df["Close"].iloc[-20:].mean()
    assert abs(result.iloc[-1] - manual) < 1e-9


def test_rsi_bounds(ohlcv_df):
    result = rsi(ohlcv_df["Close"], 14).dropna()
    assert (result >= 0).all() and (result <= 100).all()


def test_atr_non_negative(ohlcv_df):
    result = atr(ohlcv_df, 14).dropna()
    assert (result >= 0).all()


def test_macd_hist_equals_line_minus_signal(ohlcv_df):
    line, signal, hist = macd(ohlcv_df["Close"])
    diff = (line - signal - hist).dropna()
    assert (diff.abs() < 1e-9).all()


def test_bollinger_upper_above_lower(ohlcv_df):
    mid, upper, lower = bollinger(ohlcv_df["Close"])
    valid = upper.notna() & lower.notna()
    assert (upper[valid] >= lower[valid]).all()


def test_adx_bounds(ohlcv_df):
    result = adx(ohlcv_df, 14).dropna()
    assert (result >= 0).all() and (result <= 100).all()


def test_add_indicators_has_expected_columns(ohlcv_df):
    out = add_indicators(ohlcv_df)
    for col in ["EMA9", "EMA30", "RSI14", "ATR14", "MACD", "MACD_SIGNAL", "REL_VOL"]:
        assert col in out.columns
    assert len(out) == len(ohlcv_df)


def test_crossover_signal_returns_known_values(ohlcv_df):
    ind = add_indicators(ohlcv_df)
    signal = crossover_signal(ind)
    assert signal in {"BUY", "SELL", "WATCH", "HOLD"}


def test_signal_series_only_buy_sell_or_empty(ohlcv_df):
    ind = add_indicators(ohlcv_df)
    sig = signal_series(ind)
    assert set(sig.unique()).issubset({"", "BUY", "SELL"})


# -- Chart Engine overlays (new) --------------------------------------------

def test_vwap_between_low_and_high_bounds(ohlcv_df):
    result = vwap(ohlcv_df).dropna()
    assert (result >= ohlcv_df["Low"].min()).all()
    assert (result <= ohlcv_df["High"].max()).all()


def test_pivot_points_r1_above_pivot_above_s1(ohlcv_df):
    piv = pivot_points(ohlcv_df).dropna()
    assert (piv["R1"] >= piv["PP"]).all()
    assert (piv["S1"] <= piv["PP"]).all()


def test_supertrend_direction_is_plus_or_minus_one(ohlcv_df):
    _line, direction = supertrend(ohlcv_df)
    assert set(direction.unique()).issubset({1, -1})


def test_ichimoku_has_expected_columns(ohlcv_df):
    cloud = ichimoku(ohlcv_df)
    for col in ["TENKAN", "KIJUN", "SENKOU_A", "SENKOU_B", "CHIKOU"]:
        assert col in cloud.columns


def test_volume_profile_sums_to_total_volume(ohlcv_df):
    profile = volume_profile(ohlcv_df, bins=10)
    assert abs(profile["volume"].sum() - ohlcv_df["Volume"].sum()) < 1e-6


def test_volume_profile_empty_input_returns_empty_frame():
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    profile = volume_profile(empty)
    assert profile.empty


def test_heikin_ashi_close_is_ohlc_average(ohlcv_df):
    ha = heikin_ashi(ohlcv_df)
    expected_close = (ohlcv_df["Open"] + ohlcv_df["High"] + ohlcv_df["Low"] + ohlcv_df["Close"]) / 4.0
    pd.testing.assert_series_equal(ha["Close"], expected_close, check_names=False)


def test_heikin_ashi_high_low_contain_open_close(ohlcv_df):
    ha = heikin_ashi(ohlcv_df)
    assert (ha["High"] >= ha["Open"]).all() and (ha["High"] >= ha["Close"]).all()
    assert (ha["Low"] <= ha["Open"]).all() and (ha["Low"] <= ha["Close"]).all()


def _rsi_frame(values):
    return pd.DataFrame({"RSI14": values})


def test_rsi_reversion_signal_buy_on_bounce_out_of_oversold():
    df = _rsi_frame([50, 40, 28, 32])  # prev(28) <= 30, last(32) > 30
    assert rsi_reversion_signal(df) == "BUY"


def test_rsi_reversion_signal_sell_on_rollover_out_of_overbought():
    df = _rsi_frame([50, 60, 72, 68])  # prev(72) >= 70, last(68) < 70
    assert rsi_reversion_signal(df) == "SELL"


def test_rsi_reversion_signal_watch_while_still_oversold():
    df = _rsi_frame([50, 40, 25, 20])  # last < 30, no bounce yet
    assert rsi_reversion_signal(df) == "WATCH"


def test_rsi_reversion_signal_hold_in_neutral_zone():
    df = _rsi_frame([50, 52, 48, 50])
    assert rsi_reversion_signal(df) == "HOLD"


def test_rsi_reversion_signal_hold_on_short_or_nan_data():
    assert rsi_reversion_signal(_rsi_frame([50])) == "HOLD"
    assert rsi_reversion_signal(_rsi_frame([float("nan"), float("nan"), 32])) == "HOLD"


def test_rsi_reversion_signal_series_matches_scalar_signal_at_each_bar():
    values = [50, 40, 28, 32, 55, 72, 68, 50]
    df = _rsi_frame(values)
    series = rsi_reversion_signal_series(df)
    for i in range(2, len(values)):
        scalar = rsi_reversion_signal(df.iloc[: i + 1])
        if scalar in ("BUY", "SELL"):
            assert series.iloc[i] == scalar
