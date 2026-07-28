from datetime import date, datetime

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


def is_synthetic(df) -> bool:
    """True when a frame came from the synthetic fallback rather than a real
    feed. Surfaces that render real-money numbers (e.g. Portfolio Analytics)
    check this and show 'no data' instead of fabricated prices."""
    try:
        return bool(getattr(df, "attrs", {}).get("synthetic"))
    except Exception:
        return False


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
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)
    df.attrs["synthetic"] = True     # mark as generated so is_synthetic() can tell
    return df


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Price history from the active data provider (Yahoo by default). See
    tradelab.data.providers for source selection."""
    from tradelab.data import providers
    return providers.active().get_history(symbol, period, interval)


def _yahoo_history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Yahoo (yfinance) history with an offline synthetic fallback. This is the
    Yahoo provider's implementation; call get_history() rather than this."""
    if yf is not None:
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
            df = _flatten_yf(df)
            if not df.empty and {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
                return df.dropna(subset=["Close"])
        except Exception:
            pass
    return synthetic_ohlcv(symbol)


# Symbols per Yahoo batch request. yfinance packs a whole ticker list into one
# download, so a Market refresh of ~90 names becomes ~2 requests instead of 90 -
# which is what kept the serial loop tripping Yahoo's per-request rate limit.
# Kept moderate so one dud symbol can't sink too large a batch.
_BATCH_CHUNK = 40

_OHLCV = {"Open", "High", "Low", "Close", "Volume"}


def get_histories(symbols, period: str = "1y", interval: str = "1d") -> dict:
    """Batch price history for many symbols from the active data provider.

    Returns {symbol: DataFrame | None}. Providers that can fetch a whole list in
    one request (Yahoo) do so, avoiding the per-symbol rate-limiting a serial
    loop over get_history() runs into on a large refresh. Order and de-duping of
    the input are preserved by the provider implementations."""
    from tradelab.data import providers
    return providers.active().get_histories(symbols, period, interval)


def _yahoo_histories(symbols, period: str = "1y", interval: str = "1d",
                     chunk_size: int = _BATCH_CHUNK) -> dict:
    """Yahoo (yfinance) multi-symbol download in chunks - one HTTP batch per
    chunk instead of one request per symbol. Any symbol Yahoo returns nothing
    usable for falls back to synthetic data, exactly like the single-symbol
    path, so a partial outage never leaves a gap in the dashboard."""
    unique = list(dict.fromkeys(symbols))       # de-dup, preserve order
    if yf is None:
        return {s: synthetic_ohlcv(s) for s in unique}
    out: dict = {}
    for start in range(0, len(unique), chunk_size):
        chunk = unique[start:start + chunk_size]
        frames = _yahoo_download_chunk(chunk, period, interval)
        for sym in chunk:
            df = frames.get(sym)
            if df is None or df.empty or not _OHLCV.issubset(df.columns):
                out[sym] = synthetic_ohlcv(sym)
            else:
                out[sym] = df.dropna(subset=["Close"])
    return out


def _yahoo_download_chunk(symbols, period: str, interval: str) -> dict:
    """One yf.download batch for a handful of tickers -> {symbol: OHLCV frame}.

    Handles yfinance's two column shapes (a flat frame for a single ticker, a
    (ticker, field) MultiIndex for several) and never raises: a symbol Yahoo
    couldn't fill is simply absent from the returned dict, and the caller
    substitutes synthetic data for it.
    """
    result: dict = {}
    if not symbols:
        return result
    try:
        raw = yf.download(list(symbols), period=period, interval=interval,
                          progress=False, auto_adjust=False, group_by="ticker",
                          threads=True)
    except Exception:
        return result
    if raw is None or getattr(raw, "empty", True):
        return result
    # One ticker: yfinance returns a flat (field) frame, not a (ticker, field)
    # MultiIndex - handle it the same way the single-symbol path does.
    if len(symbols) == 1:
        df = _flatten_yf(raw.copy())
        if not df.empty and _OHLCV.issubset(df.columns):
            result[symbols[0]] = df
        return result
    if isinstance(raw.columns, pd.MultiIndex):
        tickers = set(raw.columns.get_level_values(0))
        for sym in symbols:
            if sym not in tickers:
                continue
            sub = raw[sym].dropna(how="all")    # failed tickers come back all-NaN
            if not sub.empty and _OHLCV.issubset(sub.columns):
                result[sym] = sub
    return result


def get_dividends(symbol: str) -> pd.Series:
    """Dividend-per-share history for a symbol from the active provider, as a
    date-indexed Series (empty when the name pays none, or the source has no
    data). See tradelab.data.providers for source selection."""
    from tradelab.data import providers
    return providers.active().get_dividends(symbol)


def _yahoo_dividends(symbol: str) -> pd.Series:
    """Yahoo (yfinance) dividend history. Unlike prices there is NO synthetic
    fallback: fabricated income would be misleading in a way fake prices on a
    practice chart are not, so a failure returns an empty series and the UI
    reports 'no data' instead."""
    if yf is None:
        return pd.Series(dtype=float)
    try:
        divs = yf.Ticker(symbol).dividends
    except Exception:
        return pd.Series(dtype=float)
    if divs is None or getattr(divs, "empty", True):
        return pd.Series(dtype=float)
    divs = pd.to_numeric(divs, errors="coerce").dropna()
    # yfinance returns a tz-aware index; drop the tz so callers can compare
    # against plain timestamps without tz-mismatch errors.
    try:
        if getattr(divs.index, "tz", None) is not None:
            divs.index = divs.index.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return divs


_fund_composition_cache: dict = {}

# Yahoo names the same sector two different ways depending on where you ask:
# a fund's weightings come back as "financial_services", while a stock's profile
# says "Financial Services". Left alone the two never merge, so a book split
# between funds and single stocks reports one sector twice under two labels.
# Everything is normalised through here to the names the rest of the app uses
# (see core.sectors / the Market tab).
_SECTOR_DISPLAY_NAMES = {
    "realestate": "Real Estate", "consumercyclical": "Consumer Discretionary",
    "consumerdiscretionary": "Consumer Discretionary", "basicmaterials": "Materials",
    "materials": "Materials", "consumerdefensive": "Consumer Staples",
    "consumerstaples": "Consumer Staples", "technology": "Technology",
    "informationtechnology": "Technology", "communicationservices": "Communication Services",
    "financialservices": "Financials", "financials": "Financials",
    "utilities": "Utilities", "industrials": "Industrials", "energy": "Energy",
    "healthcare": "Health Care",
}


def canonical_sector(name: str) -> str:
    """One display name per sector, whatever spelling the source used."""
    key = "".join(ch for ch in str(name or "").lower() if ch.isalpha())
    if not key:
        return ""
    return _SECTOR_DISPLAY_NAMES.get(key, str(name).replace("_", " ").title())


def get_fund_composition(symbol: str) -> dict:
    """What a fund holds, from the active provider and cached per symbol:
    {"top_holdings": {symbol: weight}, "sectors": {name: weight}}. An ordinary
    stock returns empty dicts. See tradelab.data.providers for source selection.
    """
    from tradelab.data import providers
    key = (providers.active_name(), symbol)
    if key not in _fund_composition_cache:
        _fund_composition_cache[key] = providers.active().get_fund_composition(symbol)
    return _fund_composition_cache[key]


def _yahoo_fund_composition(symbol: str) -> dict:
    """Yahoo (yfinance) fund holdings and sector weights.

    Like dividends, there is NO synthetic fallback: a made-up composition would
    misstate what a book is actually exposed to. A failure, or a symbol that
    isn't a fund, returns empty dicts and the UI says so.

    Yahoo reports only the top ~10 holdings, so the weights deliberately do not
    sum to 1 — callers must treat the remainder as unallocated rather than
    scaling these up to 100%.
    """
    empty = {"top_holdings": {}, "sectors": {}}
    if yf is None:
        return empty
    try:
        funds = yf.Ticker(symbol).funds_data
    except Exception:
        return empty
    if funds is None:
        return empty

    top = {}
    try:
        frame = funds.top_holdings
        if frame is not None and not frame.empty:
            weights = frame[frame.columns[-1]]
            for holding, weight in zip(frame.index, weights):
                try:
                    w = float(weight)
                except (TypeError, ValueError):
                    continue
                if w > 0:
                    top[_fund_holding_symbol(symbol, str(holding))] = w
    except Exception:
        pass

    sectors = {}
    try:
        for key, weight in (funds.sector_weightings or {}).items():
            try:
                w = float(weight)
            except (TypeError, ValueError):
                continue
            if w > 0:
                sectors[canonical_sector(key)] = w
    except Exception:
        pass
    return {"top_holdings": top, "sectors": sectors}


def _fund_holding_symbol(fund_symbol: str, holding: str) -> str:
    """Resolve a holding ticker reported inside a fund to a full Yahoo symbol.

    Yahoo is inconsistent here: a TSX fund lists its Canadian holdings as a mix
    of bare tickers and suffixed ones ("RY", "TD", "MFC.TO"). A bare "RY" inside
    a Canadian fund means the Toronto listing — taken literally it would resolve
    to Royal Bank's NYSE line, a different security at a different price, and
    silently split one exposure into two.
    """
    holding = (holding or "").strip().upper()
    if not holding or "." in holding:
        return holding
    fund = (fund_symbol or "").upper()
    for suffix in (".TO", ".V", ".CN", ".NE"):
        if fund.endswith(suffix):
            return holding + ".TO"
    return holding


_calendar_cache: dict = {}


def get_calendar(symbol: str) -> dict:
    """Scheduled dates for a symbol from the active provider, cached per symbol:
    {"earnings": date|None, "ex_dividend": date|None}. See
    tradelab.data.providers for source selection."""
    from tradelab.data import providers
    key = (providers.active_name(), symbol)
    if key not in _calendar_cache:
        _calendar_cache[key] = providers.active().get_calendar(symbol)
    return _calendar_cache[key]


def _yahoo_calendar(symbol: str) -> dict:
    """Yahoo (yfinance) earnings and ex-dividend dates.

    No synthetic fallback and no inference: a date is either published or it is
    absent. ETFs have no earnings and typically return nothing at all here,
    which is correct — an invented date on a real-money screen is worse than no
    date, and the caller says nothing rather than guessing.
    """
    empty = {"earnings": None, "ex_dividend": None}
    if yf is None:
        return empty
    try:
        cal = yf.Ticker(symbol).calendar
    except Exception:
        return empty
    if not isinstance(cal, dict) or not cal:
        return empty
    return {"earnings": _first_date(cal.get("Earnings Date")),
            "ex_dividend": _first_date(cal.get("Ex-Dividend Date"))}


def _first_date(value):
    """Yahoo returns earnings as a list (a confirmed date, or a low/high
    estimate range) and the ex-dividend date as a bare date. Take the earliest
    real date out of either shape."""
    if value is None:
        return None
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    dates = []
    for item in values:
        if isinstance(item, datetime):
            dates.append(item.date())
        elif isinstance(item, date):
            dates.append(item)
    return min(dates) if dates else None


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
    """Market cap + sector/industry/country/name from the active data provider,
    cached in-process so a symbol is only fetched once per run. Switching
    provider clears this cache (see providers.set_active)."""
    cached = _quote_meta_cache.get(symbol)
    if cached is not None:
        return cached
    from tradelab.data import providers
    meta = providers.active().get_quote_meta(symbol)
    _quote_meta_cache[symbol] = meta
    return meta


def _yahoo_quote_meta(symbol: str) -> dict:
    """Yahoo (yfinance) quote metadata with an offline deterministic fallback.
    The Yahoo provider's implementation; call get_quote_meta() instead."""
    meta = {"market_cap": 0.0, "sector": "Unknown", "industry": "Unknown",
            "country": "Unknown", "name": symbol, "quote_type": ""}
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
            meta["country"] = info.get("country") or "Unknown"
            meta["name"] = _company_name_from_info(info, symbol)
            meta["quote_type"] = info.get("quoteType") or ""
        except Exception:
            pass

    if not meta["market_cap"]:
        # Offline/error fallback so the scanner stays usable without
        # network access, same philosophy as synthetic_ohlcv() above -
        # deterministic per symbol rather than a hard failure.
        meta["market_cap"] = float(3_000_000_000 + (abs(hash(symbol)) % 300_000_000_000))

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
