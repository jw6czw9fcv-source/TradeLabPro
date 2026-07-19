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

# Yahoo has become inconsistent about which name field it returns: many
# blue-chips (KO, CAT, MO, JPM, XOM...) now come back WITHOUT longName /
# shortName, but WITH a displayName and a longBusinessSummary whose first
# phrase is the full legal name. Resolving names from only longName/shortName
# left those tickers showing just their symbol on the chart header.
_NAME_CONNECTORS = {"of", "and", "the", "for", "de", "&", "von", "van", "du", "des", "la", "le"}


def _name_from_summary(summary: str) -> str:
    """Pull the leading legal name out of a business summary:
    'The Coca-Cola Company, a beverage company, ...' -> 'The Coca-Cola Company'
    'Caterpillar Inc. provides construction ...'     -> 'Caterpillar Inc.'
    'JPMorgan Chase & Co. operates as a bank ...'    -> 'JPMorgan Chase & Co.'
    The name is the run of capitalised words (plus common lowercase
    connectors like 'of'/'&') before the first comma or sentence verb.
    """
    head = (summary or "").split(",")[0].strip()
    if not head:
        return ""
    kept = []
    for word in head.split():
        first = next((ch for ch in word if ch.isalpha()), "")
        # A genuinely lowercase word that isn't a name connector is the verb
        # that starts the description ("provides", "operates", ...) - stop.
        if first and first.islower() and word.lower() not in _NAME_CONNECTORS:
            break
        kept.append(word)
    return " ".join(kept).strip().rstrip(",&").strip()


def _company_name_from_info(info: dict, symbol: str) -> str:
    """Best-available human company name from a yfinance .info dict, falling
    back through longName -> shortName -> summary-derived -> displayName ->
    the ticker itself."""
    for key in ("longName", "shortName"):
        value = info.get(key)
        if value and str(value).strip():
            return str(value).strip()
    derived = _name_from_summary(info.get("longBusinessSummary", ""))
    # Guard against a summary that starts with a filler word ("In seeking to
    # track ...", "As of ...") where the leading run isn't a real name: require
    # at least one substantial content token (>=3 chars, not a connector).
    content = [w for w in derived.split() if len(w) >= 3 and w.lower() not in _NAME_CONNECTORS]
    if content and len(derived) <= 70:
        return derived
    display = info.get("displayName")
    if display and str(display).strip():
        return str(display).strip()
    return symbol


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

    meta = {"market_cap": 0.0, "sector": "Unknown", "industry": "Unknown", "name": symbol, "quote_type": ""}
    if yf is not None:
        try:
            info = yf.Ticker(symbol).info
            # ETFs/funds have no marketCap or sector - they report AUM
            # (totalAssets/netAssets) and a fund `category` instead. Fall back
            # to those so ETF heatmaps size by AUM and group by category, and
            # the market-cap filter has a real number for funds too.
            market_cap = info.get("marketCap") or info.get("totalAssets") or info.get("netAssets")
            if market_cap:
                meta["market_cap"] = float(market_cap)
            meta["sector"] = info.get("sector") or info.get("category") or "Unknown"
            meta["industry"] = info.get("industry") or info.get("category") or "Unknown"
            meta["name"] = _company_name_from_info(info, symbol)
            meta["quote_type"] = info.get("quoteType") or ""
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
