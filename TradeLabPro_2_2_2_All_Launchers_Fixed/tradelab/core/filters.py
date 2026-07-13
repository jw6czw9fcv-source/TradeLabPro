"""SCN-026: IBKR-style custom technical filter builder.

Complements (does not replace) ScannerConfig's fixed Price/Volume/RSI/ATR
fields, which stay as quick filters. This is the arbitrary "add a
condition on any field" layer: a scan matches only if every configured
FilterCondition passes, in addition to the fixed filters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

OPERATORS = ["Above", "Below", "Between"]


def _atr_percent(row: pd.Series) -> float:
    close = row.get("Close", 0.0)
    atr = row.get("ATR14", 0.0)
    return (atr / close * 100.0) if close else float("nan")


def _price_vs_sma20_pct(row: pd.Series) -> float:
    sma20 = row.get("SMA20", 0.0)
    close = row.get("Close", 0.0)
    return ((close - sma20) / sma20 * 100.0) if sma20 else float("nan")


# key -> (display label, resolver(row, cfg) -> float)
FILTER_FIELDS = {
    "price": ("Price ($)", lambda row, cfg: row.get("Close", float("nan"))),
    "volume": ("Volume", lambda row, cfg: row.get("Volume", float("nan"))),
    "rel_volume": ("Relative Volume (x)", lambda row, cfg: row.get("REL_VOL", float("nan"))),
    "rsi14": ("RSI (14)", lambda row, cfg: row.get("RSI14", float("nan"))),
    "atr_percent": ("ATR (%)", lambda row, cfg: _atr_percent(row)),
    "adx14": ("ADX (14)", lambda row, cfg: row.get("ADX14", float("nan"))),
    "macd": ("MACD", lambda row, cfg: row.get("MACD", float("nan"))),
    "macd_signal": ("MACD Signal", lambda row, cfg: row.get("MACD_SIGNAL", float("nan"))),
    "macd_hist": ("MACD Histogram", lambda row, cfg: row.get("MACD_HIST", float("nan"))),
    "ema_fast": ("EMA (fast)", lambda row, cfg: row.get(f"EMA{cfg.ema_fast}", float("nan"))),
    "ema_slow": ("EMA (slow)", lambda row, cfg: row.get(f"EMA{cfg.ema_slow}", float("nan"))),
    "sma20": ("SMA 20", lambda row, cfg: row.get("SMA20", float("nan"))),
    "sma50": ("SMA 50", lambda row, cfg: row.get("SMA50", float("nan"))),
    "sma200": ("SMA 200", lambda row, cfg: row.get("SMA200", float("nan"))),
    "bb_upper": ("Bollinger Upper", lambda row, cfg: row.get("BB_UPPER", float("nan"))),
    "bb_lower": ("Bollinger Lower", lambda row, cfg: row.get("BB_LOWER", float("nan"))),
    "price_vs_sma20_pct": ("Price vs SMA20 (%)", lambda row, cfg: _price_vs_sma20_pct(row)),
}


@dataclass
class FilterCondition:
    field: str
    operator: str = "Above"
    value1: float = 0.0
    value2: Optional[float] = None

    def to_dict(self) -> dict:
        return {"field": self.field, "operator": self.operator, "value1": self.value1, "value2": self.value2}

    @classmethod
    def from_dict(cls, data: dict) -> "FilterCondition":
        return cls(
            field=data.get("field", "price"),
            operator=data.get("operator", "Above"),
            value1=float(data.get("value1", 0.0)),
            value2=(float(data["value2"]) if data.get("value2") is not None else None),
        )

    def label(self) -> str:
        name = FILTER_FIELDS.get(self.field, (self.field,))[0]
        if self.operator == "Between":
            return f"{name} between {self.value1:g} and {self.value2:g}"
        return f"{name} {self.operator.lower()} {self.value1:g}"


def evaluate_condition(row: pd.Series, cfg, condition: FilterCondition) -> bool:
    field = FILTER_FIELDS.get(condition.field)
    if field is None:
        return True  # unknown field (e.g. from a newer version's setup file) - don't exclude everything
    _, resolver = field
    try:
        value = resolver(row, cfg)
    except Exception:
        return False
    if value is None or pd.isna(value):
        return False
    if condition.operator == "Above":
        return bool(value > condition.value1)
    if condition.operator == "Below":
        return bool(value < condition.value1)
    if condition.operator == "Between":
        lo, hi = sorted([condition.value1, condition.value2 if condition.value2 is not None else condition.value1])
        return bool(lo <= value <= hi)
    return True


def passes_custom_filters(row: pd.Series, cfg, conditions: list[FilterCondition]) -> bool:
    return all(evaluate_condition(row, cfg, c) for c in conditions)
