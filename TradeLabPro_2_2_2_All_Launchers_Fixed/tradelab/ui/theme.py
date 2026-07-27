"""Shared UI palette and copy.

One place for the colours that carry *meaning* — up/down, good/bad, caution —
so the same idea looks the same on every tab. Before this existed the app had
three greens and three reds for identical concepts (a rising price was
`#3fb950` on the Analytics table but `#26a65b` in the chart header, and "down"
was `#e5534b`, `#f85149` or `#e5484d` depending on which panel you were
looking at).

Only *semantic* colours belong here. The chart's categorical overlay palette
(`_OVERLAY_COLORS`) is deliberately separate: those colours distinguish one
indicator line from another and carry no good/bad meaning.
"""
from __future__ import annotations

# --- semantic colours -------------------------------------------------------

UP = "#3fb950"          # gains, advancing, favorable, above average
DOWN = "#e5534b"        # losses, declining, caution, below average
NEUTRAL = "#e3b341"     # mixed / middling / neither clearly good nor bad
MUTED = "#8a9099"       # secondary text, status lines, "no data"
TEXT = "#c7d0d8"        # default body text on the dark panels
WARN = "#c9a227"        # cautionary notices (disclaimers, safety banners)

# Candles reuse the semantic pair so a green candle and a green P&L match.
BULL = UP
BEAR = DOWN


def pnl_color(value) -> str:
    """Colour for a gain/loss figure. Zero counts as up (flat is not a loss)."""
    return UP if (value or 0) >= 0 else DOWN


def pct_color(pct, good_above: float = 60.0, bad_below: float = 40.0) -> str:
    """Traffic-light for a percentage where higher is better (breadth, win
    rates, participation)."""
    if pct is None:
        return MUTED
    if pct >= good_above:
        return UP
    if pct < bad_below:
        return DOWN
    return NEUTRAL


# --- standard copy ----------------------------------------------------------
#
# The app makes the same promise on several tabs; saying it the same way each
# time is part of meaning it. Em dashes throughout (the codebase mixed "-" and
# "—" in user-facing text).

NOT_ADVICE = "Not financial advice."
EDUCATIONAL_ONLY = "Educational information only — not financial advice."
ANALYSIS_ONLY = "Analysis only — this never places or tracks live orders."
