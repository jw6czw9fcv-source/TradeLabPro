"""Scanner result color standard (SCN-027).

A single source of truth for the semantic colors used in the Scanner
results table, so the score tiers, Signal/trend states, and RSI zones
stay visually consistent instead of being re-decided ad hoc per column.
Reuse these helpers for any other table that wants the same standard
(Watchlist, Portfolio, etc.) instead of picking new colors.
"""
from PySide6.QtGui import QColor

BULLISH = QColor(110, 240, 140)
BEARISH = QColor(240, 110, 110)
NEUTRAL = QColor(230, 190, 90)
ERROR_GRAY = QColor(170, 170, 170)

_SCORE_STRONG = QColor(20, 70, 35)   # score >= 85
_SCORE_GOOD = QColor(45, 70, 25)     # score >= 70
_SCORE_WEAK = QColor(70, 60, 20)     # score >= 55
_SCORE_POOR = QColor(65, 35, 30)     # score < 55
_SCORE_ERROR = QColor(55, 55, 55)    # row is a scan error, not a real score

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0

_SIGNAL_COLORS = {
    "BUY": BULLISH,
    "SELL": BEARISH,
    "WATCH": NEUTRAL,
    "ERROR": ERROR_GRAY,
}


def score_row_color(score: float, is_error: bool = False) -> QColor:
    """Row background tier. Errors always render as neutral gray, never
    the "poor score" red, so a scan failure can't be mistaken for a
    genuinely weak (but valid) result.
    """
    if is_error:
        return _SCORE_ERROR
    if score >= 85:
        return _SCORE_STRONG
    if score >= 70:
        return _SCORE_GOOD
    if score >= 55:
        return _SCORE_WEAK
    return _SCORE_POOR


def signal_color(signal: str):
    """Foreground color for the Signal cell. None (HOLD or unknown) means
    leave the default table text color alone.
    """
    return _SIGNAL_COLORS.get(str(signal or "").upper())


def trend_color(state: str):
    """Foreground color for Bull/Bear style cells (EMA Trend, MACD)."""
    state = str(state or "").upper()
    if state == "BULL":
        return BULLISH
    if state == "BEAR":
        return BEARISH
    return None


def rsi_zone_color(rsi: float):
    """Foreground color for the RSI14 cell when it's in an overbought or
    oversold zone; None inside the neutral 30-70 band.
    """
    try:
        rsi = float(rsi)
    except (TypeError, ValueError):
        return None
    if rsi >= RSI_OVERBOUGHT:
        return BEARISH
    if rsi <= RSI_OVERSOLD:
        return BULLISH
    return None
