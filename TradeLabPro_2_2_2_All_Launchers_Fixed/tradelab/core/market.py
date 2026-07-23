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

# Major global equity indices, listed in TRADING-SESSION ORDER - the sequence
# markets actually open through the day (Tokyo -> Hong Kong -> London/Frankfurt
# -> New York/Toronto) - so the table reads like the trading day itself. We use
# the index symbols rather than ETFs so the trend reflects the market, not a
# fund's tracking.
# Each entry: (name, symbol, region, session open in minutes past UTC midnight,
# local open label). Open times are standard time; DST shifts them by an hour
# but never changes the relative order, which is all we sort on.
GLOBAL_INDICES = [
    ("Nikkei 225", "^N225", "Asia", 0, "09:00 JST"),
    ("Hang Seng", "^HSI", "Asia", 90, "09:30 HKT"),
    ("FTSE 100", "^FTSE", "Europe", 480, "08:00 GMT"),
    ("DAX", "^GDAXI", "Europe", 480, "09:00 CET"),
    ("S&P 500", "^GSPC", "US", 870, "09:30 ET"),
    ("Nasdaq Composite", "^IXIC", "US", 870, "09:30 ET"),
    ("Dow Jones", "^DJI", "US", 870, "09:30 ET"),
    ("TSX Composite", "^GSPTSE", "Canada", 870, "09:30 ET"),
]

# The liquid iShares S&P/TSX capped sector ETFs. Canada only has a genuinely
# tradable sector fund for 7 of the 11 GICS sectors - there is no liquid
# TSX-only Consumer Discretionary, Industrials, Communication Services or
# Health Care ETF - so those are simply absent rather than faked with a US
# proxy that would misreport what's happening in Canada.
CANADA_SECTOR_ETFS = [
    ("Energy", "XEG.TO"),
    ("Financials", "XFN.TO"),
    ("Materials", "XMA.TO"),
    ("Technology", "XIT.TO"),
    ("Utilities", "XUT.TO"),
    ("Consumer Staples", "XST.TO"),
    ("Real Estate", "XRE.TO"),
]

# Sector universes the Market tab can switch between, each with the broad-market
# benchmark its relative-strength read is measured against.
SECTOR_REGIONS = {
    "US": {
        "sectors": SECTOR_ETFS,
        "benchmark": "SPY",
        "benchmark_label": "SPY",
        "note": "11 SPDR select-sector ETFs vs SPY.",
    },
    "Canada": {
        "sectors": CANADA_SECTOR_ETFS,
        "benchmark": "XIC.TO",
        "benchmark_label": "TSX",
        "note": ("7 iShares S&P/TSX capped-sector ETFs vs the TSX composite (XIC). "
                 "Canada has no liquid sector ETF for Consumer Discretionary, "
                 "Industrials, Communication Services or Health Care."),
    },
}


def sector_region(region: str) -> dict:
    """Config for a sector universe ('US' / 'Canada'), falling back to US so a
    stale saved preference can never break the dashboard."""
    return SECTOR_REGIONS.get(region) or SECTOR_REGIONS["US"]


# Number of trading days used for the medium-term momentum read (~3 months).
MOMENTUM_LOOKBACK = 63


def analyze_trend(df: pd.DataFrame) -> dict:
    """Last price, % change vs the prior close, and whether the close is
    above its 50/200-day SMA. Returns Nones on insufficient data rather
    than raising, so one bad symbol never breaks a dashboard refresh.
    """
    result = {"last": None, "change_pct": None, "above_sma50": None,
              "above_sma200": None, "mom_pct": None}
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
    # Medium-term momentum: % change over ~3 months, used for sector ranking
    # and relative strength. None until there's enough history to be meaningful.
    if len(close) > MOMENTUM_LOOKBACK:
        past = float(close.iloc[-1 - MOMENTUM_LOOKBACK])
        result["mom_pct"] = ((last - past) / past * 100.0) if past else None
    return result


def realized_vol(df: pd.DataFrame, window: int = 21) -> float | None:
    """Annualised realised volatility (%) from the last `window` daily returns.

    The VIX only exists for the US. Rather than leave every other market's
    volatility unscored, we measure what the index itself actually did: the
    standard deviation of its recent daily returns, annualised (x sqrt(252)).
    Roughly comparable to a VIX level for regime purposes - calm equity
    markets sit near 10-15, stressed ones above 25.
    """
    if df is None or df.empty or "Close" not in df:
        return None
    close = df["Close"].dropna()
    if len(close) < window + 1:
        return None
    returns = close.pct_change().dropna().iloc[-window:]
    if returns.empty:
        return None
    vol = float(returns.std() * (252 ** 0.5) * 100.0)
    return vol if vol == vol else None  # guard against NaN


def market_read(trend: dict) -> dict:
    """Per-market favorable/neutral/caution read from a single index's trend,
    using only its position vs the 50- and 200-day averages. Transparent and
    symmetric: both above -> Favorable, both below -> Caution, mixed/unknown ->
    Neutral. Returns a label plus the one-line reason behind it.
    """
    a50 = trend.get("above_sma50")
    a200 = trend.get("above_sma200")
    score = 0
    if a50 is True:
        score += 1
    elif a50 is False:
        score -= 1
    if a200 is True:
        score += 1
    elif a200 is False:
        score -= 1

    if a50 is None and a200 is None:
        return {"label": "Neutral", "reason": "Not enough history for a trend read"}
    if score >= 2:
        return {"label": "Favorable", "reason": "Above both the 50- and 200-day averages"}
    if score <= -2:
        return {"label": "Caution", "reason": "Below both the 50- and 200-day averages"}
    if score == 1:
        return {"label": "Neutral", "reason": "Above one of the 50/200-day averages"}
    if score == -1:
        return {"label": "Caution", "reason": "Below one of the 50/200-day averages"}
    return {"label": "Neutral", "reason": "Mixed signals vs the moving averages"}


def sector_breadth(sector_trends: dict) -> dict:
    """Summarize per-sector trend dicts (name -> analyze_trend result) into
    breadth counts: how many sectors are up on the day and how many are
    above their 50-day SMA.
    """
    total = len(sector_trends)
    advancing = sum(1 for t in sector_trends.values() if (t.get("change_pct") or 0) > 0)
    above_sma50 = sum(1 for t in sector_trends.values() if t.get("above_sma50"))
    measured_sma50 = sum(1 for t in sector_trends.values() if t.get("above_sma50") is not None)
    above_sma200 = sum(1 for t in sector_trends.values() if t.get("above_sma200"))
    measured_sma200 = sum(1 for t in sector_trends.values() if t.get("above_sma200") is not None)
    return {
        "total": total,
        "advancing": advancing,
        "declining": total - advancing,
        "above_sma50": above_sma50,
        "measured_sma50": measured_sma50,
        "above_sma200": above_sma200,
        "measured_sma200": measured_sma200,
    }


def sector_score_criteria(benchmark_label: str = "SPY") -> list:
    """The exact, on-screen-able rules behind the per-sector favorability score.
    The UI renders this verbatim in a "how this is scored" panel so the number
    is never a black box (same philosophy as market_condition's reason list).
    The benchmark name varies by region (SPY for US, TSX for Canada).
    """
    return [
        "Everyone starts at 50 (neutral).",
        "Above its 50-day average: +15   ·   below it: −15   (medium-term trend).",
        "Above its 200-day average: +10   ·   below it: −10   (long-term trend).",
        f"Relative strength vs {benchmark_label} over ~3 months: leading by >2%: +15, "
        "lagging by >2%: −15 (leaders keep leading).",
        "3-month momentum: up >5%: +10   ·   down >5%: −10.",
        "On the day: up: +5   ·   down: −5.",
        "Score is clamped to 0–100.   Label: ≥65 Favorable · 45–64 Neutral · <45 Avoid.",
    ]


# Default (US) criteria text, kept as a module constant for convenience.
SECTOR_SCORE_CRITERIA = sector_score_criteria("SPY")


def sector_favorability(sector_trend: dict, benchmark_trend: dict | None = None,
                        benchmark_label: str = "SPY") -> dict:
    """Transparent 0-100 favorability score for one sector, with the reasons
    that produced it. Blends trend (vs 50/200-day), relative strength vs the
    region's broad-market benchmark, medium-term momentum, and the day's move.
    Mirrors market_condition's additive, reason-listing style so it stays
    auditable. See sector_score_criteria() for the exact rules.
    """
    benchmark_trend = benchmark_trend or {}
    score = 50
    reasons = []

    if sector_trend.get("above_sma50"):
        score += 15
        reasons.append("Above its 50-day average")
    elif sector_trend.get("above_sma50") is False:
        score -= 15
        reasons.append("Below its 50-day average")

    if sector_trend.get("above_sma200"):
        score += 10
        reasons.append("Above its 200-day average")
    elif sector_trend.get("above_sma200") is False:
        score -= 10
        reasons.append("Below its 200-day average")

    mom = sector_trend.get("mom_pct")
    bench_mom = benchmark_trend.get("mom_pct")
    rel = None
    if mom is not None and bench_mom is not None:
        rel = mom - bench_mom
        if rel > 2:
            score += 15
            reasons.append(f"Outperforming {benchmark_label} by {rel:+.1f}% over ~3 months")
        elif rel < -2:
            score -= 15
            reasons.append(f"Lagging {benchmark_label} by {rel:.1f}% over ~3 months")

    if mom is not None:
        if mom > 5:
            score += 10
            reasons.append(f"Strong 3-month momentum ({mom:+.1f}%)")
        elif mom < -5:
            score -= 10
            reasons.append(f"Weak 3-month momentum ({mom:+.1f}%)")

    ch = sector_trend.get("change_pct")
    if ch is not None:
        if ch > 0:
            score += 5
        elif ch < 0:
            score -= 5

    score = max(0, min(100, score))
    if score >= 65:
        label = "Favorable"
    elif score >= 45:
        label = "Neutral"
    else:
        label = "Avoid"
    return {"score": score, "label": label, "reasons": reasons, "rel_strength": rel}


def rank_sectors(sector_trends: dict, benchmark_trend: dict | None = None,
                 region: str = "US") -> list:
    """Rank sectors best -> worst by favorability score. Takes name -> trend
    dict (analyze_trend results) and returns a list of dicts with the sector
    name, its ETF (looked up from the region's sector list), and its
    favorability result. Ties break alphabetically for a stable order.
    """
    cfg = sector_region(region)
    etf_by_name = dict(cfg["sectors"])
    label = cfg["benchmark_label"]
    ranked = []
    for name, trend in sector_trends.items():
        fav = sector_favorability(trend, benchmark_trend, label)
        ranked.append({
            "name": name,
            "etf": etf_by_name.get(name, ""),
            "trend": trend,
            **fav,
        })
    ranked.sort(key=lambda r: (-r["score"], r["name"]))
    return ranked


def market_condition(spy_trend: dict, vix_last: float | None, breadth: dict,
                     benchmark_label: str = "SPY",
                     realized_vol_pct: float | None = None) -> dict:
    """Transparent 'is it a good day to trade' read: a 0-100 score, a
    plain-English label, the list of reasons that produced it (so the number is
    never a black box - same philosophy as the scanner's confidence score), and
    a one-line summary of the regime.

    Scored from the benchmark's trend (vs 50/200-day) and momentum, the
    volatility regime, and sector breadth at both 50- and 200-day. Every input
    is optional: whatever is missing is simply skipped rather than guessed.
    benchmark_label names the broad-market proxy in the reasons (SPY for US,
    TSX for Canada); realized_vol_pct stands in for the VIX outside the US.
    """
    score = 50
    reasons = []

    if spy_trend.get("above_sma50"):
        score += 15
        reasons.append(f"{benchmark_label} above its 50-day average (uptrend)")
    elif spy_trend.get("above_sma50") is False:
        score -= 15
        reasons.append(f"{benchmark_label} below its 50-day average (downtrend)")

    if spy_trend.get("above_sma200"):
        score += 10
        reasons.append(f"{benchmark_label} above its 200-day average (long-term uptrend)")
    elif spy_trend.get("above_sma200") is False:
        score -= 10
        reasons.append(f"{benchmark_label} below its 200-day average (long-term downtrend)")

    # Medium-term momentum of the benchmark itself.
    mom = spy_trend.get("mom_pct")
    if mom is not None:
        if mom > 5:
            score += 10
            reasons.append(f"{benchmark_label} up {mom:+.1f}% over ~3 months (momentum)")
        elif mom < -5:
            score -= 10
            reasons.append(f"{benchmark_label} down {mom:.1f}% over ~3 months (momentum)")

    # Volatility regime. The VIX is US-only, so any other market falls back to
    # the index's own realised volatility - same idea, always available.
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
    elif realized_vol_pct is not None:
        if realized_vol_pct < 15:
            score += 15
            reasons.append(f"Realised volatility low at {realized_vol_pct:.1f}% (calm)")
        elif realized_vol_pct > 28:
            score -= 20
            reasons.append(f"Realised volatility elevated at {realized_vol_pct:.1f}% (stressed)")
        else:
            score -= 5
            reasons.append(f"Realised volatility moderate at {realized_vol_pct:.1f}%")

    measured = breadth.get("measured_sma50", 0)
    if measured:
        frac = breadth.get("above_sma50", 0) / measured
        if frac >= 0.6:
            score += 10
            reasons.append(f"Broad participation ({breadth['above_sma50']}/{measured} sectors above 50-day avg)")
        elif frac <= 0.4:
            score -= 10
            reasons.append(f"Weak participation ({breadth['above_sma50']}/{measured} sectors above 50-day avg)")

    # Long-term breadth: how much of the market is in a structural uptrend.
    measured200 = breadth.get("measured_sma200", 0)
    if measured200:
        frac200 = breadth.get("above_sma200", 0) / measured200
        if frac200 >= 0.6:
            score += 5
            reasons.append(f"{breadth['above_sma200']}/{measured200} sectors above their 200-day avg")
        elif frac200 <= 0.4:
            score -= 5
            reasons.append(f"Only {breadth['above_sma200']}/{measured200} sectors above their 200-day avg")

    score = max(0, min(100, score))
    if score >= 70:
        label = "Favorable"
    elif score >= 45:
        label = "Neutral / mixed"
    else:
        label = "Caution"
    return {"score": score, "label": label, "reasons": reasons,
            "summary": _condition_summary(label, spy_trend, breadth, benchmark_label)}


def _condition_summary(label: str, trend: dict, breadth: dict, benchmark_label: str) -> str:
    """One plain-English line describing the regime behind the score. Purely
    descriptive - it characterises market conditions, it does not tell anyone
    what to do with their money.
    """
    if label == "Favorable":
        base = f"{benchmark_label} is trending up and participation is broad."
    elif label == "Caution":
        base = f"{benchmark_label} is under pressure and participation is narrow."
    else:
        base = f"{benchmark_label} is sending mixed signals — trend and breadth disagree."

    measured = breadth.get("measured_sma50", 0)
    if measured:
        base += (f" {breadth.get('above_sma50', 0)} of {measured} sectors are "
                 "above their 50-day average.")
    if trend.get("above_sma200") is False:
        base += " Note it is below its 200-day average (structural downtrend)."
    return base
