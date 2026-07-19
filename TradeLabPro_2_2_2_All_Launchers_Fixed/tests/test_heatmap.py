"""Heatmap engine tests - all pure/offline (no network)."""
import math

import numpy as np
import pandas as pd

from tradelab.core.heatmap import (HeatmapTile, build_tiles, color_for_change,
                                    default_quote_provider, group_tiles_by_sector,
                                    group_tiles, layout_heatmap, squarify, period_choices,
                                    theme_choices, THEMES, _spec_for, _stats_from_df)


# --- colour -----------------------------------------------------------------

def test_color_flat_is_neutral_grey():
    assert color_for_change(0.0).lower() == "#414554"


def test_color_up_is_green_ish_down_is_red_ish():
    up = color_for_change(3.0)
    down = color_for_change(-3.0)
    ur, ug, ub = int(up[1:3], 16), int(up[3:5], 16), int(up[5:7], 16)
    dr, dg, db = int(down[1:3], 16), int(down[3:5], 16), int(down[5:7], 16)
    assert ug > ur and ug > ub          # green dominates on a gain
    assert dr > dg and dr > db          # red dominates on a loss


def test_color_saturates_and_handles_nan():
    assert color_for_change(50.0) == color_for_change(3.0)   # clamped
    assert color_for_change(float("nan")) == "#2b2f3a"
    assert color_for_change(None) == "#2b2f3a"


# --- squarify ---------------------------------------------------------------

def _area(r):
    return r[2] * r[3]


def test_squarify_tiles_the_whole_area():
    sizes = [10, 8, 6, 4, 3, 2, 1]
    rects = squarify(sizes, 0, 0, 100, 50)
    assert len(rects) == len(sizes)
    covered = sum(_area(r) for r in rects)
    assert math.isclose(covered, 100 * 50, rel_tol=1e-6)


def test_squarify_rects_stay_within_bounds():
    rects = squarify([5, 3, 2, 1, 1], 0, 0, 80, 60)
    for x, y, w, h in rects:
        assert x >= -1e-6 and y >= -1e-6
        assert x + w <= 80 + 1e-6
        assert y + h <= 60 + 1e-6


def test_squarify_areas_proportional_to_sizes():
    sizes = [40, 20, 20, 10, 10]
    rects = squarify(sizes, 0, 0, 100, 100)
    total = sum(sizes)
    for size, r in zip(sizes, rects):
        assert math.isclose(_area(r), size / total * 100 * 100, rel_tol=1e-6)


def test_squarify_degenerate_inputs():
    assert squarify([], 0, 0, 10, 10) == []
    assert squarify([1, 2], 0, 0, 0, 10) == [(0, 0, 0, 0), (0, 0, 0, 0)]


# --- tiles / grouping -------------------------------------------------------

def _quotes():
    return {
        "AAPL": {"price": 190, "change_pct": 1.5, "market_cap": 3_000e9, "dollar_volume": 5e9, "sector": "Technology", "name": "Apple"},
        "MSFT": {"price": 420, "change_pct": -0.5, "market_cap": 3_100e9, "dollar_volume": 4e9, "sector": "Technology", "name": "Microsoft"},
        "XOM": {"price": 110, "change_pct": 0.8, "market_cap": 450e9, "dollar_volume": 2e9, "sector": "Energy", "name": "Exxon"},
        "ZERO": {"price": 0, "change_pct": 0, "market_cap": 0, "dollar_volume": 0, "sector": "Energy", "name": "Zero"},
    }


def test_build_tiles_sorted_and_drops_zero_size():
    tiles = build_tiles(_quotes(), size_by="market_cap")
    syms = [t.symbol for t in tiles]
    assert "ZERO" not in syms                 # zero market cap dropped
    assert syms == ["MSFT", "AAPL", "XOM"]    # sorted big -> small by cap


def test_build_tiles_size_by_dollar_volume_reorders():
    tiles = build_tiles(_quotes(), size_by="dollar_volume")
    assert [t.symbol for t in tiles] == ["AAPL", "MSFT", "XOM"]


def test_group_tiles_by_sector_orders_by_total():
    tiles = build_tiles(_quotes(), size_by="market_cap")
    groups = group_tiles_by_sector(tiles)
    assert [g[0] for g in groups] == ["Technology", "Energy"]
    assert [t.symbol for t in groups[0][1]] == ["MSFT", "AAPL"]


def test_group_tiles_by_industry_and_country():
    tiles = [
        HeatmapTile("AAPL", "Apple", "Technology", 3e12, 1.0, industry="Hardware", country="United States"),
        HeatmapTile("MSFT", "Microsoft", "Technology", 3e12, 1.0, industry="Software", country="United States"),
        HeatmapTile("TSM", "TSMC", "Technology", 1e12, 1.0, industry="Semiconductors", country="Taiwan"),
    ]
    inds = {g[0] for g in group_tiles(tiles, "industry")}
    assert inds == {"Hardware", "Software", "Semiconductors"}
    countries = {g[0] for g in group_tiles(tiles, "country")}
    assert countries == {"United States", "Taiwan"}


def test_theme_choices_and_baskets():
    choices = theme_choices()
    assert "Semiconductors" in choices and "AI & Big Data" in choices
    assert "NVDA" in THEMES["Semiconductors"]
    assert all(isinstance(v, list) and v for v in THEMES.values())


def test_build_tiles_carries_industry_and_country():
    quotes = {"AAPL": {"price": 1, "change_pct": 0, "market_cap": 1e12,
                       "sector": "Technology", "industry": "Hardware", "country": "United States"}}
    t = build_tiles(quotes)[0]
    assert t.industry == "Hardware" and t.country == "United States"


# --- layout -----------------------------------------------------------------

def test_layout_grouped_has_headers_and_tiles_within_bounds():
    tiles = build_tiles(_quotes(), size_by="market_cap")
    cells = layout_heatmap(tiles, 400, 300, group_by="sector")
    headers = [c for c in cells if c.is_header]
    tile_cells = [c for c in cells if not c.is_header]
    assert {c.sector for c in headers} == {"Technology", "Energy"}
    assert len(tile_cells) == len(tiles)
    for c in cells:
        assert c.x >= -1e-6 and c.y >= -1e-6
        assert c.x + c.w <= 400 + 1e-6
        assert c.y + c.h <= 300 + 1e-6


def test_layout_ungrouped_has_no_headers():
    tiles = build_tiles(_quotes(), size_by="market_cap")
    cells = layout_heatmap(tiles, 400, 300, group_by=None)
    assert all(not c.is_header for c in cells)
    assert len(cells) == len(tiles)


def test_layout_empty_is_empty():
    assert layout_heatmap([], 400, 300) == []
    assert layout_heatmap(build_tiles(_quotes()), 0, 0) == []


# --- performance period -----------------------------------------------------

def _daily(closes):
    n = len(closes)
    dates = pd.date_range(end=pd.Timestamp("2024-06-28"), periods=n, freq="B")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": np.full(n, 1_000_000)}, index=dates)


def test_period_choices_include_finviz_windows():
    choices = period_choices()
    for p in ["1 Day", "1 Week", "1 Month", "1 Year", "3 Year", "5 Year", "10 Year", "YTD"]:
        assert p in choices


def test_long_periods_use_bounded_spans_not_max():
    # Long look-backs must fetch a bounded span (<= 10y), never "max", so the
    # download stays fast.
    for p in ["3 Year", "5 Year", "10 Year"]:
        assert _spec_for(p)["yf_period"] in {"5y", "10y"}


def test_ten_year_reference_falls_back_to_oldest_available_bar():
    # A 10y span holds ~2514 bars; a 2520-day look-back exceeds that, so the
    # reference is the oldest bar (~10 years back) rather than crashing.
    closes = list(range(100, 100 + 300))          # 300 bars, oldest = 100
    df = _daily([float(c) for c in closes])
    price, change, _ = _stats_from_df(df, _spec_for("10 Year"))
    assert math.isclose(change, (price - 100.0) / 100.0 * 100.0, rel_tol=1e-9)


def test_one_day_change_uses_previous_close():
    df = _daily([100.0, 110.0])          # +10% day
    price, change, _ = _stats_from_df(df, _spec_for("1 Day"))
    assert price == 110.0
    assert math.isclose(change, 10.0, rel_tol=1e-9)


def test_one_week_change_looks_back_five_trading_days():
    # 6 bars: ref is 5 trading days back (the first bar here).
    df = _daily([100.0, 101, 102, 103, 104, 120.0])
    _, change, _ = _stats_from_df(df, _spec_for("1 Week"))
    assert math.isclose(change, 20.0, rel_tol=1e-9)   # 120 vs 100


def test_ytd_change_uses_prior_year_last_close():
    dates = pd.to_datetime(["2023-12-29", "2024-01-02", "2024-03-01", "2024-06-28"])
    closes = [200.0, 210.0, 220.0, 260.0]
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                       "Close": closes, "Volume": [1_000_000] * 4}, index=dates)
    _, change, _ = _stats_from_df(df, _spec_for("YTD"))
    assert math.isclose(change, 30.0, rel_tol=1e-9)   # 260 vs 200 (last 2023 close)


# --- provider (offline via synthetic history fallback) ----------------------

def test_default_quote_provider_offline_builds_quotes(monkeypatch):
    import tradelab.core.heatmap as hm

    # Force the batched-download path to return nothing so it falls back to
    # per-symbol history (synthetic, offline-deterministic), and stub meta so
    # nothing touches the network.
    monkeypatch.setattr(hm, "_batch_prices", lambda syms, spec: {})
    import tradelab.data.market_data as md
    monkeypatch.setattr(md, "get_quote_meta",
                        lambda s: {"market_cap": 1e9, "sector": "Technology", "name": s})
    seen = []
    quotes = default_quote_provider(["AAA", "BBB"], progress=lambda i, t, s: seen.append(s))
    assert set(quotes) == {"AAA", "BBB"}
    for q in quotes.values():
        assert "change_pct" in q and "market_cap" in q and "sector" in q
    assert seen == ["AAA", "BBB"]
    # And those quotes flow through into drawable tiles.
    tiles = build_tiles(quotes, size_by="market_cap")
    assert len(tiles) == 2
