"""Tests for tradelab.core.ohlcv — making a bad download safe to compute on.

The crash these guard against is not hypothetical: a backtest optimisation on
2026-07-28 died with "Cannot set a DataFrame with multiple columns to the
single column EMA9", logged as an uncaught exception. The same shape of frame
had already been fixed twice elsewhere (market, seasonality) and the fix had
never reached `indicators` — which is the path the scanner, the alerts poller,
both backtesters, every strategy and the chart all run through.
"""
import numpy as np
import pandas as pd
import pytest

from tradelab.core.ohlcv import close_series, flatten_ohlcv


def _frame(rows=120):
    """A plain, well-formed OHLCV frame.

    It has to rise *and* fall: a monotonic series leaves RSI undefined (no down
    moves, so the average loss is zero), and a backtest then drops every row
    for want of a signal input — which looks exactly like a bug in the code
    under test.
    """
    idx = pd.date_range("2024-01-01", periods=rows, freq="B")
    drift = np.linspace(100.0, 160.0, rows)
    wave = 4.0 * np.sin(np.arange(rows) / 3.0)
    close = pd.Series(drift + wave, index=idx)
    return pd.DataFrame({
        "Open": close * 0.99, "High": close * 1.01, "Low": close * 0.98,
        "Close": close, "Volume": pd.Series(1_000_000.0, index=idx),
    })


def _with_duplicate_close(rows=120):
    """What yfinance's MultiIndex flattening can hand back: two Close columns,
    the adjusted one first."""
    df = _frame(rows)
    dup = pd.concat([df, df[["Close"]] * 1.5], axis=1)
    dup.columns = list(df.columns) + ["Close"]
    return dup


# -- the normaliser ------------------------------------------------------------

def test_a_well_formed_frame_is_left_alone():
    df = _frame()
    out = flatten_ohlcv(df)
    pd.testing.assert_frame_equal(out, df)


def test_a_duplicated_column_keeps_the_first():
    """First, not last: for a Close pair that is the adjusted series, which is
    what the rest of the app assumes it is reading."""
    out = flatten_ohlcv(_with_duplicate_close())
    assert list(out.columns).count("Close") == 1
    assert isinstance(out["Close"], pd.Series)
    assert out["Close"].iloc[0] == pytest.approx(100.0)      # not 150.0, the 1.5x copy


def test_a_multiindex_is_reduced_to_its_field_names():
    df = _frame(10)
    df.columns = pd.MultiIndex.from_product([df.columns, ["AAPL"]])
    out = flatten_ohlcv(df)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_nothing_to_work_with_is_returned_as_is():
    assert flatten_ohlcv(None) is None
    empty = pd.DataFrame()
    assert flatten_ohlcv(empty) is empty


def test_close_series_is_numeric_and_one_dimensional():
    close = close_series(_with_duplicate_close())
    assert isinstance(close, pd.Series)
    assert close.dtype.kind == "f"
    assert float(close.iloc[-1]) == pytest.approx(_frame()["Close"].iloc[-1])


def test_close_series_says_none_rather_than_raising():
    """One oddly-shaped symbol should leave a gap in a dashboard, not take the
    whole refresh down."""
    assert close_series(None) is None
    assert close_series(pd.DataFrame()) is None
    assert close_series(pd.DataFrame({"Open": [1.0]})) is None
    assert close_series(pd.DataFrame({"Close": ["x", "y"]})) is None


# -- the path that actually crashed --------------------------------------------

def test_indicators_survive_a_duplicate_close_column():
    """The regression itself. Every strategy, scan and alert goes through here."""
    from tradelab.core.indicators import add_indicators
    out = add_indicators(_with_duplicate_close())
    assert isinstance(out["EMA9"], pd.Series)
    assert isinstance(out["MACD"], pd.Series)
    assert out["EMA9"].notna().any()


def test_indicators_give_the_same_answer_as_on_a_clean_frame():
    """Not merely "it didn't raise" — the duplicate must be dropped, not
    averaged into the maths."""
    from tradelab.core.indicators import add_indicators
    clean = add_indicators(_frame())
    patched = add_indicators(_with_duplicate_close())
    assert patched["EMA9"].iloc[-1] == pytest.approx(clean["EMA9"].iloc[-1])
    assert patched["RSI14"].iloc[-1] == pytest.approx(clean["RSI14"].iloc[-1])


def test_a_backtest_prepares_a_duplicated_frame():
    """The exact call in the logged traceback: optimize -> _prepare ->
    add_indicators."""
    from tradelab.core.backtest import _prepare
    from tradelab.core.config import ScannerConfig
    out = _prepare(_with_duplicate_close(200), ScannerConfig())
    assert not out.empty
    assert isinstance(out["Close"], pd.Series)


def test_a_duplicated_volume_does_not_break_the_volume_indicators():
    """Close is the one that bit, but atr/adx read High and Low and obv/mfi
    read Volume — a duplicate in any of them is just as fatal."""
    from tradelab.core.indicators import add_indicators
    df = _frame()
    dup = pd.concat([df, df[["Volume"]]], axis=1)
    dup.columns = list(df.columns) + ["Volume"]
    out = add_indicators(dup)
    assert isinstance(out["OBV"], pd.Series)
    assert isinstance(out["MFI14"], pd.Series)
