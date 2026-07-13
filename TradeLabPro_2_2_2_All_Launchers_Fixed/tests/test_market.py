"""Tests for the Phase 3 Market Dashboard core logic (tradelab/core/market.py)."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core.market import SECTOR_ETFS, analyze_trend, sector_breadth, market_condition


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
    assert analyze_trend(pd.DataFrame()) == {"last": None, "change_pct": None, "above_sma50": None, "above_sma200": None}
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
