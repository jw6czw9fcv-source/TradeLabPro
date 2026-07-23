"""Tests for the Phase 3 Market Dashboard core logic (tradelab/core/market.py)."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core.market import (
    SECTOR_ETFS, GLOBAL_INDICES, SECTOR_SCORE_CRITERIA, CANADA_SECTOR_ETFS,
    SECTOR_REGIONS, analyze_trend, sector_breadth, market_condition,
    market_read, sector_favorability, rank_sectors, sector_region,
    sector_score_criteria, realized_vol,
)


def _rising_closes(n=250, start=100.0, step=0.5):
    return pd.DataFrame({"Close": [start + step * i for i in range(n)]})


def _falling_closes(n=250, start=200.0, step=0.5):
    return pd.DataFrame({"Close": [start - step * i for i in range(n)]})


def test_sector_etfs_has_eleven_standard_sectors():
    assert len(SECTOR_ETFS) == 11
    tickers = [t for _, t in SECTOR_ETFS]
    assert "XLK" in tickers and "XLF" in tickers and "XLE" in tickers


def test_analyze_trend_rising_series_is_above_both_smas():
    t = analyze_trend(_rising_closes())
    assert t["last"] == pytest.approx(224.5)
    assert t["change_pct"] > 0
    assert t["above_sma50"] is True
    assert t["above_sma200"] is True


def test_analyze_trend_falling_series_is_below_both_smas():
    t = analyze_trend(_falling_closes())
    assert t["change_pct"] < 0
    assert t["above_sma50"] is False
    assert t["above_sma200"] is False


def test_analyze_trend_short_series_leaves_smas_none():
    t = analyze_trend(pd.DataFrame({"Close": [100, 101, 102]}))
    assert t["last"] == 102
    assert t["above_sma50"] is None
    assert t["above_sma200"] is None


def test_analyze_trend_empty_or_missing_is_safe():
    assert analyze_trend(pd.DataFrame()) == {"last": None, "change_pct": None, "above_sma50": None, "above_sma200": None, "mom_pct": None}
    assert analyze_trend(None)["last"] is None


def test_sector_breadth_counts_advancers_and_sma():
    trends = {
        "A": {"change_pct": 1.0, "above_sma50": True},
        "B": {"change_pct": -0.5, "above_sma50": True},
        "C": {"change_pct": 0.2, "above_sma50": False},
        "D": {"change_pct": -1.0, "above_sma50": None},  # unmeasured SMA
    }
    b = sector_breadth(trends)
    assert b["total"] == 4
    assert b["advancing"] == 2
    assert b["declining"] == 2
    assert b["above_sma50"] == 2
    assert b["measured_sma50"] == 3  # D excluded


def test_market_condition_favorable_when_everything_bullish():
    spy = {"above_sma50": True, "above_sma200": True}
    breadth = {"above_sma50": 9, "measured_sma50": 11}
    result = market_condition(spy, vix_last=14.0, breadth=breadth)
    assert result["score"] >= 70
    assert result["label"] == "Favorable"
    assert any("VIX" in r for r in result["reasons"])


def test_market_condition_caution_when_everything_bearish():
    spy = {"above_sma50": False, "above_sma200": False}
    breadth = {"above_sma50": 2, "measured_sma50": 11}
    result = market_condition(spy, vix_last=35.0, breadth=breadth)
    assert result["score"] < 45
    assert result["label"] == "Caution"


def test_market_condition_neutral_in_the_middle():
    spy = {"above_sma50": True, "above_sma200": False}
    breadth = {"above_sma50": 5, "measured_sma50": 11}  # ~45%, no swing
    result = market_condition(spy, vix_last=24.0, breadth=breadth)
    assert 45 <= result["score"] < 70
    assert result["label"] == "Neutral / mixed"


def test_market_condition_score_clamped_0_100():
    spy = {"above_sma50": True, "above_sma200": True}
    breadth = {"above_sma50": 11, "measured_sma50": 11}
    result = market_condition(spy, vix_last=10.0, breadth=breadth)
    assert 0 <= result["score"] <= 100


def test_market_condition_handles_missing_vix_and_unmeasured_breadth():
    spy = {"above_sma50": None, "above_sma200": None}
    breadth = {"above_sma50": 0, "measured_sma50": 0}
    result = market_condition(spy, vix_last=None, breadth=breadth)
    assert result["score"] == 50  # nothing to move it off neutral
    assert result["reasons"] == []


# --- Global indices & momentum -------------------------------------------

def test_global_indices_cover_the_major_regions():
    tickers = [row[1] for row in GLOBAL_INDICES]
    for expected in ("^GSPC", "^IXIC", "^DJI", "^GSPTSE", "^FTSE", "^GDAXI", "^N225", "^HSI"):
        assert expected in tickers
    regions = {row[2] for row in GLOBAL_INDICES}
    assert {"US", "Canada", "Europe", "Asia"} <= regions


def test_global_indices_are_listed_in_market_open_order():
    opens = [row[3] for row in GLOBAL_INDICES]
    assert opens == sorted(opens), "indices must be listed in session-open order"
    # Asia opens first, North America last.
    assert GLOBAL_INDICES[0][1] == "^N225"
    assert GLOBAL_INDICES[-1][1] == "^GSPTSE"
    names = [row[0] for row in GLOBAL_INDICES]
    assert names.index("Hang Seng") < names.index("FTSE 100") < names.index("S&P 500")


def test_global_indices_carry_a_local_open_label():
    for name, sym, region, open_utc, open_local in GLOBAL_INDICES:
        assert isinstance(open_utc, int) and 0 <= open_utc < 24 * 60
        assert open_local and ":" in open_local


def test_analyze_trend_computes_medium_term_momentum():
    t = analyze_trend(_rising_closes())  # steadily rising over 250 bars
    assert t["mom_pct"] is not None and t["mom_pct"] > 0
    # Short series can't measure 3-month momentum.
    assert analyze_trend(pd.DataFrame({"Close": [100, 101, 102]}))["mom_pct"] is None


def test_market_read_favorable_neutral_caution():
    assert market_read({"above_sma50": True, "above_sma200": True})["label"] == "Favorable"
    assert market_read({"above_sma50": False, "above_sma200": False})["label"] == "Caution"
    # Mixed -> neutral; a single below -> caution-leaning.
    assert market_read({"above_sma50": True, "above_sma200": False})["label"] == "Neutral"
    assert market_read({"above_sma50": False, "above_sma200": None})["label"] == "Caution"


def test_market_read_no_history_is_neutral():
    r = market_read({"above_sma50": None, "above_sma200": None})
    assert r["label"] == "Neutral"
    assert "history" in r["reason"].lower()


# --- Sector favorability & ranking ---------------------------------------

def test_sector_favorability_leader_scores_high():
    sector = {"change_pct": 1.2, "above_sma50": True, "above_sma200": True, "mom_pct": 12.0}
    spy = {"mom_pct": 4.0}
    fav = sector_favorability(sector, spy)
    assert fav["label"] == "Favorable"
    assert fav["score"] >= 65
    assert fav["rel_strength"] == pytest.approx(8.0)
    assert any("Outperforming" in r for r in fav["reasons"])


def test_sector_favorability_laggard_scores_low():
    sector = {"change_pct": -0.8, "above_sma50": False, "above_sma200": False, "mom_pct": -9.0}
    spy = {"mom_pct": 3.0}
    fav = sector_favorability(sector, spy)
    assert fav["label"] == "Avoid"
    assert fav["score"] < 45


def test_sector_favorability_clamped_and_neutral_without_data():
    fav = sector_favorability({"change_pct": None, "above_sma50": None,
                               "above_sma200": None, "mom_pct": None})
    assert fav["score"] == 50 and fav["label"] == "Neutral"
    assert 0 <= fav["score"] <= 100


def test_rank_sectors_orders_best_to_worst_with_etfs():
    trends = {
        "Technology": {"change_pct": 1.0, "above_sma50": True, "above_sma200": True, "mom_pct": 15.0},
        "Utilities": {"change_pct": -0.5, "above_sma50": False, "above_sma200": False, "mom_pct": -8.0},
        "Financials": {"change_pct": 0.2, "above_sma50": True, "above_sma200": False, "mom_pct": 3.0},
    }
    spy = {"mom_pct": 5.0}
    ranked = rank_sectors(trends, spy)
    assert [r["name"] for r in ranked] == ["Technology", "Financials", "Utilities"]
    assert ranked[0]["etf"] == "XLK"  # ETF looked up from SECTOR_ETFS
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_sector_score_criteria_is_nonempty_text():
    assert SECTOR_SCORE_CRITERIA and all(isinstance(s, str) and s for s in SECTOR_SCORE_CRITERIA)


# --- US / Canada sector regions ------------------------------------------

def test_sector_regions_offer_us_and_canada():
    assert set(SECTOR_REGIONS) == {"US", "Canada"}
    assert sector_region("US")["sectors"] is SECTOR_ETFS
    assert sector_region("Canada")["sectors"] is CANADA_SECTOR_ETFS
    assert sector_region("US")["benchmark"] == "SPY"
    assert sector_region("Canada")["benchmark"] == "XIC.TO"


def test_unknown_region_falls_back_to_us():
    assert sector_region("Atlantis") is SECTOR_REGIONS["US"]
    assert sector_region("") is SECTOR_REGIONS["US"]


def test_canada_sectors_are_tsx_listed_and_unique():
    names = [n for n, _ in CANADA_SECTOR_ETFS]
    tickers = [t for _, t in CANADA_SECTOR_ETFS]
    assert len(set(names)) == len(names) == 7
    assert all(t.endswith(".TO") for t in tickers), "Canadian sectors must be TSX symbols"
    assert "XEG.TO" in tickers and "XFN.TO" in tickers and "XIT.TO" in tickers


def test_rank_sectors_uses_the_regions_etfs_and_benchmark_label():
    trends = {
        "Energy": {"change_pct": 1.0, "above_sma50": True, "above_sma200": True, "mom_pct": 14.0},
        "Utilities": {"change_pct": -0.4, "above_sma50": False, "above_sma200": False, "mom_pct": -6.0},
    }
    ranked = rank_sectors(trends, {"mom_pct": 3.0}, region="Canada")
    assert [r["name"] for r in ranked] == ["Energy", "Utilities"]
    assert ranked[0]["etf"] == "XEG.TO"  # Canadian ETF, not the US XLE
    assert any("TSX" in reason for reason in ranked[0]["reasons"])
    assert not any("SPY" in reason for reason in ranked[0]["reasons"])


def test_sector_score_criteria_names_the_benchmark():
    assert any("TSX" in line for line in sector_score_criteria("TSX"))
    assert any("SPY" in line for line in sector_score_criteria("SPY"))


# --- Enhanced condition score: volatility fallback, momentum, 200d breadth ---

def test_realized_vol_is_higher_for_a_choppier_series():
    calm = pd.DataFrame({"Close": [100 + 0.1 * i for i in range(120)]})
    choppy = pd.DataFrame({"Close": [100 + (5 if i % 2 else -5) for i in range(120)]})
    assert realized_vol(calm) < realized_vol(choppy)


def test_realized_vol_needs_enough_history():
    assert realized_vol(pd.DataFrame({"Close": [100, 101, 102]})) is None
    assert realized_vol(pd.DataFrame()) is None


def test_realized_vol_scores_the_read_when_no_vix_available():
    """Canada has no VIX, so realised volatility must drive the same swing."""
    trend = {"above_sma50": True, "above_sma200": True}
    breadth = {"above_sma50": 5, "measured_sma50": 7}
    calm = market_condition(trend, None, breadth, "TSX", realized_vol_pct=11.0)
    stressed = market_condition(trend, None, breadth, "TSX", realized_vol_pct=35.0)
    assert calm["score"] > stressed["score"]
    assert any("Realised volatility low" in r for r in calm["reasons"])
    assert any("elevated" in r for r in stressed["reasons"])


def test_vix_takes_precedence_over_realized_vol_when_both_given():
    trend = {"above_sma50": True, "above_sma200": True}
    breadth = {"above_sma50": 7, "measured_sma50": 11}
    result = market_condition(trend, 14.0, breadth, "SPY", realized_vol_pct=40.0)
    assert any("VIX low" in r for r in result["reasons"])
    assert not any("Realised" in r for r in result["reasons"])


def test_benchmark_momentum_moves_the_score():
    breadth = {"above_sma50": 6, "measured_sma50": 11}
    up = market_condition({"above_sma50": True, "mom_pct": 12.0}, 18.0, breadth)
    down = market_condition({"above_sma50": True, "mom_pct": -12.0}, 18.0, breadth)
    assert up["score"] > down["score"]
    assert any("~3 months" in r for r in up["reasons"])


def test_long_term_breadth_contributes():
    trend = {"above_sma50": True, "above_sma200": True}
    strong = market_condition(trend, 18.0, {"above_sma50": 7, "measured_sma50": 11,
                                            "above_sma200": 9, "measured_sma200": 11})
    weak = market_condition(trend, 18.0, {"above_sma50": 7, "measured_sma50": 11,
                                          "above_sma200": 2, "measured_sma200": 11})
    assert strong["score"] > weak["score"]
    assert any("200-day avg" in r for r in strong["reasons"])


def test_sector_breadth_also_counts_the_200_day():
    trends = {
        "A": {"change_pct": 1.0, "above_sma50": True, "above_sma200": True},
        "B": {"change_pct": -0.5, "above_sma50": True, "above_sma200": False},
        "C": {"change_pct": 0.2, "above_sma50": False, "above_sma200": None},
    }
    b = sector_breadth(trends)
    assert b["above_sma200"] == 1
    assert b["measured_sma200"] == 2  # C excluded


def test_condition_summary_is_plain_english():
    result = market_condition({"above_sma50": True, "above_sma200": True}, 14.0,
                              {"above_sma50": 9, "measured_sma50": 11})
    assert result["summary"]
    assert "sectors are above their 50-day average" in result["summary"]
    # Descriptive, not a recommendation to act.
    assert "should" not in result["summary"].lower()


def test_market_condition_reasons_use_the_benchmark_label():
    spy = {"above_sma50": True, "above_sma200": False}
    breadth = {"above_sma50": 4, "measured_sma50": 7}
    result = market_condition(spy, vix_last=18.0, breadth=breadth, benchmark_label="TSX")
    assert any(r.startswith("TSX above") for r in result["reasons"])
    assert not any("SPY" in r for r in result["reasons"])
