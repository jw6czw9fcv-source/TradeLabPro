"""Market Dashboard core logic (Phase 3).

Pure, Qt-free functions for the "is it a good day to trade" macro read:
sector breadth from the SPDR sector ETFs, per-symbol trend analysis, and
a transparent overall condition score. Kept independent of the UI and of
any live data fetch (callers pass in already-fetched history), same
pattern as tradelab/core/confidence.py, so it's unit-testable offline.
"""
from __future__ import annotations

import pandas as pd

from tradelab.core.indicators import sma

# The 11 SPDR select-sector ETFs - a standard, liquid proxy for how each
# sector of the US market is doing today, without scanning thousands of
# individual names.
SECTOR_ETFS = [
    ("Technology", "XLK"),
    ("Financials", "XLF"),
    ("Health Care", "XLV"),
    ("Energy", "XLE"),
    ("Industrials", "XLI"),
    ("Consumer Staples", "XLP"),
    ("Consumer Discretionary", "XLY"),
    ("Utilities", "XLU"),
    ("Materials", "XLB"),
    ("Real Estate", "XLRE"),
    ("Communication Svcs", "XLC"),
]


def analyze_trend(df: pd.DataFrame) -> dict:
    """Last price, % change vs the prior close, and whether the close is
    above its 50/200-day SMA. Returns Nones on insufficient data rather
    than raising, so one bad symbol never breaks a dashboard refresh.
    """
    result = {"last": None, "change_pct": None, "above_sma50": None, "above_sma200": None}
    if df is None or df.empty or "Close" not in df:
        return result
    close = df["Close"].dropna()
    if close.empty:
        return result
    last = float(close.iloc[-1])
    result["last"] = last
    if len(close) >= 2:
        prev = float(close.iloc[-2])
        result["change_pct"] = ((last - prev) / prev * 100.0) if prev else None
    if len(close) >= 50:
        result["above_sma50"] = bool(last > float(sma(close, 50).iloc[-1]))
    if len(close) >= 200:
        result["above_sma200"] = bool(last > float(sma(close, 200).iloc[-1]))
    return result


def sector_breadth(sector_trends: dict) -> dict:
    """Summarize per-sector trend dicts (name -> analyze_trend result) into
    breadth counts: how many sectors are up on the day and how many are
    above their 50-day SMA.
    """
    total = len(sector_trends)
    advancing = sum(1 for t in sector_trends.values() if (t.get("change_pct") or 0) > 0)
    above_sma50 = sum(1 for t in sector_trends.values() if t.get("above_sma50"))
    measured_sma50 = sum(1 for t in sector_trends.values() if t.get("above_sma50") is not None)
    return {
        "total": total,
        "advancing": advancing,
        "declining": total - advancing,
        "above_sma50": above_sma50,
        "measured_sma50": measured_sma50,
    }


def market_condition(spy_trend: dict, vix_last: float | None, breadth: dict) -> dict:
    """Transparent 'is it a good day to trade' read: a 0-100 score, a
    plain-English label, and the list of reasons that produced it (so the
    number is never a black box - same philosophy as the scanner's
    confidence score).
    """
    score = 50
    reasons = []

    if spy_trend.get("above_sma50"):
        score += 15
        reasons.append("SPY above its 50-day average (uptrend)")
    elif spy_trend.get("above_sma50") is False:
        score -= 15
        reasons.append("SPY below its 50-day average (downtrend)")

    if spy_trend.get("above_sma200"):
        score += 10
        reasons.append("SPY above its 200-day average (long-term uptrend)")
    elif spy_trend.get("above_sma200") is False:
        score -= 10
        reasons.append("SPY below its 200-day average (long-term downtrend)")

    if vix_last is not None:
        if vix_last < 20:
            score += 15
            reasons.append(f"VIX low at {vix_last:.1f} (calm)")
        elif vix_last > 30:
            score -= 20
            reasons.append(f"VIX elevated at {vix_last:.1f} (fear)")
        else:
            score -= 5
            reasons.append(f"VIX moderate at {vix_last:.1f}")

    measured = breadth.get("measured_sma50", 0)
    if measured:
        frac = breadth.get("above_sma50", 0) / measured
        if frac >= 0.6:
            score += 10
            reasons.append(f"Broad participation ({breadth['above_sma50']}/{measured} sectors above 50-day avg)")
        elif frac <= 0.4:
            score -= 10
            reasons.append(f"Weak participation ({breadth['above_sma50']}/{measured} sectors above 50-day avg)")

    score = max(0, min(100, score))
    if score >= 70:
        label = "Favorable"
    elif score >= 45:
        label = "Neutral / mixed"
    else:
        label = "Caution"
    return {"score": score, "label": label, "reasons": reasons}
