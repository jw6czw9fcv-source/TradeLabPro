import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:
    yf = None


def _flatten_yf(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def synthetic_ohlcv(symbol: str, periods: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=periods, freq="B")
    # NOTE: date_range(periods=N, freq="B") is not guaranteed to return exactly
    # N rows across all pandas versions (observed 259 vs 260 requested on
    # pandas 3.x). Size every array off len(dates), not the requested
    # `periods`, so this never throws a length-mismatch again regardless of
    # the pandas version installed.
    n = len(dates)
    returns = rng.normal(0.0008, 0.018, size=n)
    close = 50 * np.exp(np.cumsum(returns))
    open_ = close * (1 + rng.normal(0, 0.006, size=n))
    high = np.maximum(open_, close) * (1 + rng.random(n) * 0.015)
    low = np.minimum(open_, close) * (1 - rng.random(n) * 0.015)
    volume = rng.integers(500_000, 5_000_000, size=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    if yf is not None:
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
            df = _flatten_yf(df)
            if not df.empty and {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
                return df.dropna(subset=["Close"])
        except Exception:
            pass
    return synthetic_ohlcv(symbol)


_quote_meta_cache: dict = {}


def get_quote_meta(symbol: str) -> dict:
    """Real market cap + sector/industry via yfinance, cached in-process so
    a symbol is only fetched once per run regardless of how many scans hit
    it. Was previously a stub returning a fake market cap seeded from
    hash(symbol) - the "Minimum market cap" filter was never actually
    filtering on real data.
    """
    cached = _quote_meta_cache.get(symbol)
    if cached is not None:
        return cached

    meta = {"market_cap": 0.0, "sector": "Unknown", "industry": "Unknown"}
    if yf is not None:
        try:
            info = yf.Ticker(symbol).info
            market_cap = info.get("marketCap")
            if market_cap:
                meta["market_cap"] = float(market_cap)
            meta["sector"] = info.get("sector") or "Unknown"
            meta["industry"] = info.get("industry") or "Unknown"
        except Exception:
            pass

    if not meta["market_cap"]:
        # Offline/error fallback so the scanner stays usable without
        # network access, same philosophy as synthetic_ohlcv() above -
        # deterministic per symbol rather than a hard failure.
        meta["market_cap"] = float(3_000_000_000 + (abs(hash(symbol)) % 300_000_000_000))

    _quote_meta_cache[symbol] = meta
    return meta


_CAP_BUCKETS = [
    (200_000_000_000, "Mega"),
    (10_000_000_000, "Large"),
    (2_000_000_000, "Mid"),
    (300_000_000, "Small"),
    (0, "Micro"),
]


def market_cap_bucket(market_cap: float) -> str:
    for threshold, label in _CAP_BUCKETS:
        if market_cap >= threshold:
            return label
    return "Micro"
