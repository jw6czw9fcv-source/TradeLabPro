"""Market heatmap engine (Qt-free, offline-testable).

Builds a Finviz-style market map: one tile per symbol, sized by market cap
(or dollar volume), coloured green->red by the day's % change, and grouped
into sector blocks via a squarified treemap layout.

Everything here is pure/deterministic and network-free except
default_quote_provider(), which is injectable so the whole thing lays out
and renders offline in tests. All Qt / threading lives in the UI layer
(HeatmapPanel), never here.

Pipeline:
    symbols -> quote_provider(symbols) -> quotes dict
            -> build_tiles(quotes, size_by) -> [HeatmapTile] (sorted big->small)
            -> layout_heatmap(tiles, w, h) -> [LayoutCell] (rects to draw)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

# --- data model -------------------------------------------------------------


@dataclass
class HeatmapTile:
    symbol: str
    name: str
    sector: str
    size: float          # market cap or dollar volume - drives tile area
    change_pct: float    # day % change - drives tile colour
    price: float = 0.0


@dataclass
class LayoutCell:
    """One rectangle to draw: either a sector header band (is_header) or a
    symbol tile (tile is set)."""
    tile: Optional[HeatmapTile]
    sector: str
    x: float
    y: float
    w: float
    h: float
    is_header: bool = False


# --- colour -----------------------------------------------------------------

_NEUTRAL = (65, 69, 84)      # #414554 - flat
_UP = (48, 158, 79)          # #309e4f - strong green
_DOWN = (203, 59, 59)        # #cb3b3b - strong red


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def color_for_change(pct: Optional[float], max_abs: float = 3.0) -> str:
    """Hex colour for a % change: flat->neutral grey, up->green, down->red,
    saturating at +/-max_abs percent. Missing/NaN -> a muted 'no data' grey."""
    if pct is None or pct != pct:  # NaN
        return "#2b2f3a"
    max_abs = max_abs or 3.0
    t = min(abs(float(pct)), max_abs) / max_abs
    target = _UP if pct >= 0 else _DOWN
    r = _lerp(_NEUTRAL[0], target[0], t)
    g = _lerp(_NEUTRAL[1], target[1], t)
    b = _lerp(_NEUTRAL[2], target[2], t)
    return f"#{r:02x}{g:02x}{b:02x}"


# --- tiles ------------------------------------------------------------------


def build_tiles(quotes: dict, size_by: str = "market_cap") -> list[HeatmapTile]:
    """Turn a quotes dict {symbol: {price, change_pct, market_cap,
    dollar_volume, sector, name}} into tiles sorted big->small. Symbols
    without a positive size are dropped (nothing to draw)."""
    key = "dollar_volume" if size_by == "dollar_volume" else "market_cap"
    tiles: list[HeatmapTile] = []
    for sym, q in quotes.items():
        try:
            size = float(q.get(key, 0) or 0)
        except Exception:
            size = 0.0
        if size <= 0:
            continue
        try:
            change = float(q.get("change_pct", 0) or 0)
        except Exception:
            change = 0.0
        try:
            price = float(q.get("price", 0) or 0)
        except Exception:
            price = 0.0
        tiles.append(HeatmapTile(
            symbol=sym,
            name=str(q.get("name", sym) or sym),
            sector=str(q.get("sector", "Unknown") or "Unknown"),
            size=size,
            change_pct=change,
            price=price,
        ))
    tiles.sort(key=lambda t: t.size, reverse=True)
    return tiles


def group_tiles_by_sector(tiles: list[HeatmapTile]) -> list[tuple[str, list[HeatmapTile], float]]:
    """[(sector, tiles_big_to_small, total_size), ...] ordered by total size
    descending. Preserves the incoming big->small order within each sector."""
    groups: dict[str, list[HeatmapTile]] = {}
    for t in tiles:
        groups.setdefault(t.sector, []).append(t)
    out = [(sector, ts, sum(t.size for t in ts)) for sector, ts in groups.items()]
    out.sort(key=lambda g: g[2], reverse=True)
    return out


# --- squarified treemap -----------------------------------------------------


def squarify(sizes: list[float], x: float, y: float, dx: float, dy: float) -> list[tuple[float, float, float, float]]:
    """Squarified treemap layout. Returns one (x, y, w, h) rect per input
    size, in the SAME order as `sizes`, tiling the rectangle (x, y, dx, dy)
    with near-square cells. Sizes should be positive; pass them big->small
    for the best (most square) result. Iterative (no recursion limit)."""
    vals = [float(s) for s in sizes if s is not None]
    n = len(vals)
    if n == 0:
        return []
    total = sum(vals)
    if total <= 0 or dx <= 0 or dy <= 0:
        return [(x, y, 0.0, 0.0) for _ in vals]

    # Normalise so the values sum to the available area.
    scaled = [v * dx * dy / total for v in vals]
    rects: list[tuple[float, float, float, float]] = []
    cx, cy, cw, ch = x, y, dx, dy
    i = 0
    while i < n:
        side = min(cw, ch)

        def worst(row: list[float]) -> float:
            s = sum(row)
            if s <= 0 or side <= 0:
                return math.inf
            mx, mn = max(row), min(row)
            return max(side * side * mx / (s * s), s * s / (side * side * mn))

        row = [scaled[i]]
        j = i + 1
        while j < n and worst(row + [scaled[j]]) <= worst(row):
            row.append(scaled[j])
            j += 1

        s = sum(row)
        if cw >= ch:
            # Lay the row as a column on the left, stacked down `ch`.
            w = s / ch if ch > 0 else 0.0
            yy = cy
            for val in row:
                h = val / w if w > 0 else 0.0
                rects.append((cx, yy, w, h))
                yy += h
            cx += w
            cw -= w
        else:
            # Lay the row along the top, stacked across `cw`.
            h = s / cw if cw > 0 else 0.0
            xx = cx
            for val in row:
                w = val / h if h > 0 else 0.0
                rects.append((xx, cy, w, h))
                xx += w
            cy += h
            ch -= h
        i = j
    return rects


def layout_heatmap(tiles: list[HeatmapTile], width: float, height: float,
                   header: float = 16.0, group_by_sector: bool = True) -> list[LayoutCell]:
    """Lay tiles into a (width x height) rectangle. When grouped, sectors are
    squarified into blocks; each block gets a small header band plus its
    tiles squarified below. Returns drawing cells (headers + tiles)."""
    cells: list[LayoutCell] = []
    if not tiles or width <= 0 or height <= 0:
        return cells

    if not group_by_sector:
        for t, (rx, ry, rw, rh) in zip(tiles, squarify([t.size for t in tiles], 0, 0, width, height)):
            cells.append(LayoutCell(t, t.sector, rx, ry, rw, rh))
        return cells

    groups = group_tiles_by_sector(tiles)
    sector_rects = squarify([g[2] for g in groups], 0, 0, width, height)
    for (sector, stiles, _total), (sx, sy, sw, sh) in zip(groups, sector_rects):
        if sw <= 0 or sh <= 0:
            continue
        head_h = min(header, sh)
        cells.append(LayoutCell(None, sector, sx, sy, sw, head_h, is_header=True))
        body_y, body_h = sy + head_h, sh - head_h
        if body_h <= 0:
            continue
        for t, (tx, ty, tw, th) in zip(stiles, squarify([t.size for t in stiles], sx, body_y, sw, body_h)):
            cells.append(LayoutCell(t, sector, tx, ty, tw, th))
    return cells


# --- quote provider (the only networked part) -------------------------------


# Performance windows the colour can represent (Finviz-style), each mapped to
# the yfinance history span to pull and the trading-day look-back for the
# reference close ("YTD" uses the prior year's last close instead).
HEATMAP_PERIODS = {
    "1 Day":   {"yf_period": "5d",  "trading_days": 1},
    "1 Week":  {"yf_period": "1mo", "trading_days": 5},
    "1 Month": {"yf_period": "3mo", "trading_days": 21},
    "3 Month": {"yf_period": "6mo", "trading_days": 63},
    "6 Month": {"yf_period": "1y",  "trading_days": 126},
    "1 Year":  {"yf_period": "2y",  "trading_days": 252},
    # Longer look-backs use bounded spans (10y, not "max") so the fetch stays
    # ~0.5s: yfinance's time is per-request latency, not bar count. The 10-year
    # reference is the oldest bar in the 10y span (~10 years back).
    "3 Year":  {"yf_period": "5y",  "trading_days": 756},
    "5 Year":  {"yf_period": "10y", "trading_days": 1260},
    "10 Year": {"yf_period": "10y", "trading_days": 2520},
    "YTD":     {"yf_period": "1y",  "ytd": True},
}
DEFAULT_PERIOD = "1 Day"


def period_choices() -> list[str]:
    return list(HEATMAP_PERIODS.keys())


def _spec_for(period: Optional[str]) -> dict:
    return HEATMAP_PERIODS.get(period or DEFAULT_PERIOD, HEATMAP_PERIODS[DEFAULT_PERIOD])


def _reference_close(closes, spec: dict) -> Optional[float]:
    """The close to measure % change against for this period."""
    if spec.get("ytd"):
        try:
            last_year = closes.index[-1].year
            prev = closes[closes.index.year < last_year]
            if len(prev):
                return float(prev.iloc[-1])          # last close of prior year
            this_year = closes[closes.index.year == last_year]
            if len(this_year):
                return float(this_year.iloc[0])      # else first close this year
        except Exception:
            pass
        return float(closes.iloc[0])
    td = int(spec.get("trading_days", 1))
    if len(closes) <= td:
        return float(closes.iloc[0])
    return float(closes.iloc[-1 - td])


def _stats_from_df(df, spec: dict) -> Optional[tuple[float, float, float]]:
    """(price, change_pct over the period, dollar_volume) from an OHLCV frame."""
    try:
        closes = df["Close"].dropna()
        if closes is None or len(closes) < 2:
            return None
        price = float(closes.iloc[-1])
        ref = _reference_close(closes, spec)
        if not ref:
            return None
        change = (price - ref) / ref * 100.0
        vol = df["Volume"].dropna()
        dvol = float(price * float(vol.iloc[-1])) if len(vol) else 0.0
        return price, change, dvol
    except Exception:
        return None


def _batch_prices(symbols: list[str], spec: dict) -> dict:
    """One batched yfinance download for all symbols -> {sym: (price,
    change_pct, dollar_volume)}. Empty dict if yfinance is unavailable so the
    caller falls back to per-symbol history (synthetic offline)."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    try:
        data = yf.download(symbols, period=spec["yf_period"], interval="1d", progress=False,
                           group_by="ticker", threads=True, auto_adjust=False)
    except Exception:
        return {}
    out: dict = {}
    multi = len(symbols) > 1
    for sym in symbols:
        try:
            sub = data[sym] if multi else data
            stats = _stats_from_df(sub, spec)
            if stats is not None:
                out[sym] = stats
        except Exception:
            continue
    return out


def default_quote_provider(symbols: list[str], period: str = DEFAULT_PERIOD,
                           progress: Optional[Callable[[int, int, str], None]] = None) -> dict:
    """Fetch heatmap quotes for `symbols`, with the % change measured over
    `period` (see HEATMAP_PERIODS). Prices/change come from a single batched
    download; market cap + sector come from the cached get_quote_meta (warm
    after any prior scan). Falls back to per-symbol synthetic history offline
    so the map always renders."""
    from tradelab.data.market_data import get_history, get_quote_meta

    spec = _spec_for(period)
    prices = _batch_prices(symbols, spec)
    quotes: dict = {}
    total = len(symbols)
    for idx, sym in enumerate(symbols, start=1):
        stats = prices.get(sym)
        if stats is None:
            stats = _stats_from_df(get_history(sym, spec["yf_period"], "1d"), spec)
        if stats is None:
            if progress:
                progress(idx, total, sym)
            continue
        price, change, dvol = stats
        meta = get_quote_meta(sym)
        quotes[sym] = {
            "price": price,
            "change_pct": change,
            "dollar_volume": dvol,
            "market_cap": float(meta.get("market_cap", 0.0) or 0.0),
            "sector": meta.get("sector", "Unknown") or "Unknown",
            "name": meta.get("name", sym) or sym,
        }
        if progress:
            progress(idx, total, sym)
    return quotes
