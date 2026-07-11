import pandas as pd

from tradelab.data.market_data import synthetic_ohlcv, get_history


def test_synthetic_ohlcv_returns_expected_columns():
    df = synthetic_ohlcv("AAPL")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        assert col in df.columns


def test_synthetic_ohlcv_index_length_matches_data_length():
    # Regression test: date_range(periods=N, freq="B") is not guaranteed to
    # return exactly N rows on every pandas version (observed 259 vs 260 on
    # pandas 3.x), which previously raised
    # "ValueError: Length of values (260) does not match length of index (259)".
    for periods in [50, 259, 260, 261, 500]:
        df = synthetic_ohlcv("TEST", periods=periods)
        assert len(df) == len(df.index)
        assert len(df["Close"]) == len(df.index)


def test_synthetic_ohlcv_is_deterministic_per_symbol():
    df1 = synthetic_ohlcv("AAPL")
    df2 = synthetic_ohlcv("AAPL")
    pd.testing.assert_frame_equal(df1, df2)


def test_synthetic_ohlcv_differs_across_symbols():
    df1 = synthetic_ohlcv("AAPL")
    df2 = synthetic_ohlcv("MSFT")
    assert not df1["Close"].equals(df2["Close"])


def test_get_history_never_raises_and_returns_dataframe():
    # No network in this sandbox -> should fall back to synthetic data
    # rather than raising or returning something malformed.
    df = get_history("AAPL", "6mo", "1d")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert len(df) == len(df.index)
