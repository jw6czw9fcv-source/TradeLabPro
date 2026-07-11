import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=int(length), adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(int(length)).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/length, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    a = df["High"] - df["Low"]
    b = (df["High"] - prev_close).abs()
    c = (df["Low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1/length, adjust=False).mean()


def bollinger(close: pd.Series, length: int = 20, mult: float = 2.0):
    mid = sma(close, length)
    sd = close.rolling(length).std()
    return mid, mid + mult * sd, mid - mult * sd


def adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr = true_range(df)
    atr_ = tr.ewm(alpha=1/length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/length, adjust=False).mean() / atr_.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1/length, adjust=False).mean() / atr_.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/length, adjust=False).mean()


def add_indicators(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 30, macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9) -> pd.DataFrame:
    out = df.copy()
    out[f"EMA{ema_fast}"] = ema(out["Close"], ema_fast)
    out[f"EMA{ema_slow}"] = ema(out["Close"], ema_slow)
    out["SMA20"] = sma(out["Close"], 20)
    out["SMA50"] = sma(out["Close"], 50)
    out["SMA200"] = sma(out["Close"], 200)
    out["RSI14"] = rsi(out["Close"], 14)
    out["ATR14"] = atr(out, 14)
    out["BB_MID"], out["BB_UPPER"], out["BB_LOWER"] = bollinger(out["Close"], 20, 2.0)
    out["ADX14"] = adx(out, 14)
    out["MACD"], out["MACD_SIGNAL"], out["MACD_HIST"] = macd(out["Close"], macd_fast, macd_slow, macd_signal)
    out["VOL_AVG20"] = out["Volume"].rolling(20).mean()
    out["REL_VOL"] = out["Volume"] / out["VOL_AVG20"].replace(0, np.nan)
    return out


def crossover_signal(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 30) -> str:
    f = f"EMA{ema_fast}"
    s = f"EMA{ema_slow}"
    if len(df) < 3 or f not in df or s not in df:
        return "HOLD"
    prev_fast, prev_slow = df[f].iloc[-2], df[s].iloc[-2]
    last_fast, last_slow = df[f].iloc[-1], df[s].iloc[-1]
    macd_ok_buy = df["MACD"].iloc[-1] > df["MACD_SIGNAL"].iloc[-1] and df["MACD_HIST"].iloc[-1] > 0
    macd_ok_sell = df["MACD"].iloc[-1] < df["MACD_SIGNAL"].iloc[-1] and df["MACD_HIST"].iloc[-1] < 0
    if prev_fast <= prev_slow and last_fast > last_slow and macd_ok_buy:
        return "BUY"
    if prev_fast >= prev_slow and last_fast < last_slow and macd_ok_sell:
        return "SELL"
    if last_fast > last_slow:
        return "WATCH"
    return "HOLD"


def signal_series(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 30) -> pd.Series:
    f, s = f"EMA{ema_fast}", f"EMA{ema_slow}"
    buy = (df[f].shift(1) <= df[s].shift(1)) & (df[f] > df[s]) & (df["MACD"] > df["MACD_SIGNAL"]) & (df["MACD_HIST"] > 0)
    sell = (df[f].shift(1) >= df[s].shift(1)) & (df[f] < df[s]) & (df["MACD"] < df["MACD_SIGNAL"]) & (df["MACD_HIST"] < 0)
    out = pd.Series("", index=df.index)
    out[buy] = "BUY"
    out[sell] = "SELL"
    return out


# ---------------------------------------------------------------------------
# Chart Engine (Phase 1) additions: overlays used by the new PyQtGraph chart.
# Kept as pure functions on plain Series/DataFrames so they're independently
# unit-testable without any Qt/plotting dependency.
# ---------------------------------------------------------------------------

def vwap(df: pd.DataFrame) -> pd.Series:
    """Running (session-agnostic) VWAP. Fine for daily-bar swing charts."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
    cum_vol = df["Volume"].cumsum().replace(0, np.nan)
    cum_vol_price = (typical * df["Volume"]).cumsum()
    return cum_vol_price / cum_vol


def pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """Classic floor-trader pivots computed from the prior bar."""
    prev_high = df["High"].shift(1)
    prev_low = df["Low"].shift(1)
    prev_close = df["Close"].shift(1)
    pp = (prev_high + prev_low + prev_close) / 3.0
    r1 = 2 * pp - prev_low
    s1 = 2 * pp - prev_high
    r2 = pp + (prev_high - prev_low)
    s2 = pp - (prev_high - prev_low)
    r3 = prev_high + 2 * (pp - prev_low)
    s3 = prev_low - 2 * (prev_high - pp)
    return pd.DataFrame({
        "PP": pp, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3,
    }, index=df.index)


def supertrend(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0):
    """Returns (line, direction). direction is +1 bullish / -1 bearish."""
    hl2 = (df["High"] + df["Low"]) / 2.0
    atr_ = atr(df, length)
    upper_basic = hl2 + multiplier * atr_
    lower_basic = hl2 - multiplier * atr_
    upper = upper_basic.copy()
    lower = lower_basic.copy()
    close = df["Close"]

    for i in range(1, len(df)):
        upper.iloc[i] = upper_basic.iloc[i] if close.iloc[i - 1] > upper.iloc[i - 1] else min(upper_basic.iloc[i], upper.iloc[i - 1])
        lower.iloc[i] = lower_basic.iloc[i] if close.iloc[i - 1] < lower.iloc[i - 1] else max(lower_basic.iloc[i], lower.iloc[i - 1])

    direction = pd.Series(1, index=df.index)
    line = pd.Series(np.nan, index=df.index)
    line.iloc[0] = upper.iloc[0]
    direction.iloc[0] = -1
    for i in range(1, len(df)):
        if close.iloc[i] > upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
        line.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]

    return line, direction


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52):
    """Tenkan/Kijun/Senkou A&B (projected forward) + Chikou span."""
    high, low, close = df["High"], df["Low"], df["Close"]
    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2.0
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2.0
    senkou_a = ((tenkan_sen + kijun_sen) / 2.0).shift(kijun)
    senkou_b_line = ((high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2.0).shift(kijun)
    chikou = close.shift(-kijun)
    return pd.DataFrame({
        "TENKAN": tenkan_sen, "KIJUN": kijun_sen,
        "SENKOU_A": senkou_a, "SENKOU_B": senkou_b_line, "CHIKOU": chikou,
    }, index=df.index)


def volume_profile(df: pd.DataFrame, bins: int = 24) -> pd.DataFrame:
    """Fixed-range volume profile: bins the visible price range and sums
    volume traded (by typical price) in each bin."""
    if df.empty:
        return pd.DataFrame(columns=["price_low", "price_high", "volume"])
    typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    if hi <= lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, bins + 1)
    idx = np.clip(np.digitize(typical.values, edges) - 1, 0, bins - 1)
    vol_by_bin = np.zeros(bins)
    for i, v in zip(idx, df["Volume"].values):
        vol_by_bin[i] += float(v)
    return pd.DataFrame({"price_low": edges[:-1], "price_high": edges[1:], "volume": vol_by_bin})


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Converts OHLC candles to Heikin-Ashi (smoothed trend view)."""
    ha = pd.DataFrame(index=df.index)
    ha["Close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4.0
    ha_open = np.zeros(len(df))
    ha_open[0] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2.0
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i - 1] + ha["Close"].iloc[i - 1]) / 2.0
    ha["Open"] = ha_open
    ha["High"] = pd.concat([df["High"], ha["Open"], ha["Close"]], axis=1).max(axis=1)
    ha["Low"] = pd.concat([df["Low"], ha["Open"], ha["Close"]], axis=1).min(axis=1)
    ha["Volume"] = df["Volume"]
    return ha
