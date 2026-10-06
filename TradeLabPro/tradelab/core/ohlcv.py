"""Making a downloaded price frame safe to compute on.

One shape of bad download has crashed this app more than once: yfinance's
MultiIndex flattening can hand back a frame with **two** 'Close' columns (an
adjusted one and a raw one). `df["Close"]` is then a *DataFrame*, not a Series,
and everything downstream breaks in a way that reads like a bug in the maths —
`float() argument must be ... not 'Series'` in a market refresh, or
`Cannot set a DataFrame with multiple columns to the single column EMA9` in a
backtest optimisation. The real cause is three columns up.

The rule used to be written out separately in `market` and in `seasonality`,
which is how `indicators` — the path every strategy, scan, alert and chart
actually runs through — ended up without it. One copy, imported.

Qt-free, no network.
"""
from __future__ import annotations

import pandas as pd

# The columns the indicator library reads. A duplicate in any of them is just
# as fatal as a duplicate Close: atr/adx want High and Low, obv and mfi want
# Volume.
OHLCV = ("Open", "High", "Low", "Close", "Adj Close", "Volume")


def flatten_ohlcv(df):
    """The same frame with one column per name.

    A MultiIndex (`('Close', 'AAPL')`) is reduced to its first level, and a
    duplicated column name keeps its **first** occurrence — for a Close pair
    that is the adjusted series, which is the one the rest of the app assumes.
    Anything already well-shaped is returned untouched, so this costs nothing
    on the normal path.
    """
    if df is None or getattr(df, "empty", True):
        return df
    columns = getattr(df, "columns", None)
    if columns is None:
        return df
    if isinstance(columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] if isinstance(c, tuple) and c else c for c in columns]
        columns = df.columns
    if pd.Index(columns).has_duplicates:
        df = df.loc[:, ~pd.Index(columns).duplicated()]
    return df


def close_series(df):
    """The numeric 1-D close series, or None when there isn't a usable one.

    Returning None rather than raising is deliberate: one oddly-shaped symbol
    should leave a dashboard with a gap, not take the refresh down with it.
    """
    df = flatten_ohlcv(df)
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        return None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):        # belt and braces
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    return close if not close.empty else None
