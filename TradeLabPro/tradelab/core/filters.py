"""IBKR-style condition builder (SCN-026 + Phase 5).

A FilterCondition is one comparison: a field (optionally with a tunable
period, e.g. RSI 14, EMA 20) compared to a fixed number, a range, or
ANOTHER field (crossovers like EMA 9 above EMA 30). Used by the Scanner's
custom filters and by no-code custom strategies.

Fields are defined once in FIELD_SPECS with a default period and a compute
function; ensure_columns() adds any period-specific columns a set of
conditions needs (e.g. EMA20, RSI9) to a DataFrame on demand, so users can
pick any indicator and change its period inline without a fixed precomputed
column having to exist ahead of time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from tradelab.core import indicators as ind

OPERATORS = ["Above", "Below", "Between", "Above field", "Below field"]
FIELD_OPERATORS = ("Above field", "Below field")


# Each field: label, default period (None = no period / not tunable),
# col(period) -> column name, compute(df, period) -> Series.
# Column names for the tunable oscillators/averages match what
# add_indicators() already emits at the standard period (RSI14, EMA9,
# SMA50, ADX14, CCI20, ROC12, MFI14, WILLR14...), so the common case reuses
# precomputed columns; a non-standard period is computed on demand.
def _spec(label, period, col, compute):
    return {"label": label, "period": period, "col": col, "compute": compute}


FIELD_SPECS = {
    "price": _spec("Price ($)", None, lambda p: "Close", lambda df, p: df["Close"]),
    "volume": _spec("Volume", None, lambda p: "Volume", lambda df, p: df["Volume"]),
    "rel_volume": _spec("Relative Volume (x)", None, lambda p: "REL_VOL",
                        lambda df, p: df["Volume"] / df["Volume"].rolling(20).mean().replace(0, np.nan)),
    "vwap": _spec("VWAP", None, lambda p: "VWAP", lambda df, p: ind.vwap(df)),
    "obv": _spec("OBV", None, lambda p: "OBV", lambda df, p: ind.obv(df)),
    "macd": _spec("MACD", None, lambda p: "MACD", lambda df, p: ind.macd(df["Close"])[0]),
    "macd_signal": _spec("MACD Signal", None, lambda p: "MACD_SIGNAL", lambda df, p: ind.macd(df["Close"])[1]),
    "macd_hist": _spec("MACD Histogram", None, lambda p: "MACD_HIST", lambda df, p: ind.macd(df["Close"])[2]),
    "bb_upper": _spec("Bollinger Upper", None, lambda p: "BB_UPPER", lambda df, p: ind.bollinger(df["Close"])[1]),
    "bb_lower": _spec("Bollinger Lower", None, lambda p: "BB_LOWER", lambda df, p: ind.bollinger(df["Close"])[2]),
    "ema": _spec("EMA", 20, lambda p: f"EMA{p}", lambda df, p: ind.ema(df["Close"], p)),
    "sma": _spec("SMA", 50, lambda p: f"SMA{p}", lambda df, p: ind.sma(df["Close"], p)),
    "rsi": _spec("RSI", 14, lambda p: f"RSI{p}", lambda df, p: ind.rsi(df["Close"], p)),
    "atr_pct": _spec("ATR (%)", 14, lambda p: f"ATRPCT{p}",
                     lambda df, p: ind.atr(df, p) / df["Close"].replace(0, np.nan) * 100.0),
    "adx": _spec("ADX", 14, lambda p: f"ADX{p}", lambda df, p: ind.adx(df, p)),
    "stoch_k": _spec("Stochastic %K", 14, lambda p: f"STOCHK{p}", lambda df, p: ind.stochastic(df, p, 3)[0]),
    "stoch_d": _spec("Stochastic %D", 14, lambda p: f"STOCHD{p}", lambda df, p: ind.stochastic(df, p, 3)[1]),
    "williams_r": _spec("Williams %R", 14, lambda p: f"WILLR{p}", lambda df, p: ind.williams_r(df, p)),
    "cci": _spec("CCI", 20, lambda p: f"CCI{p}", lambda df, p: ind.cci(df, p)),
    "roc": _spec("Rate of Change", 12, lambda p: f"ROC{p}", lambda df, p: ind.roc(df["Close"], p)),
    "mfi": _spec("Money Flow Index", 14, lambda p: f"MFI{p}", lambda df, p: ind.mfi(df, p)),
}

# Old field keys (pre-parameterization) -> (new key, period), so saved
# presets and custom strategies keep working after the upgrade.
_LEGACY_FIELDS = {
    "rsi14": ("rsi", 14), "adx14": ("adx", 14), "atr_percent": ("atr_pct", 14),
    "cci20": ("cci", 20), "roc12": ("roc", 12), "mfi14": ("mfi", 14),
    "williams_r": ("williams_r", 14),
    "ema_fast": ("ema", 9), "ema_slow": ("ema", 30),
    "sma20": ("sma", 20), "sma50": ("sma", 50), "sma200": ("sma", 200),
    "price_vs_sma20_pct": ("price", None),  # closest surviving field
}


def field_choices() -> list[tuple[str, str]]:
    """[(key, label), ...] for a field dropdown."""
    return [(key, spec["label"]) for key, spec in FIELD_SPECS.items()]


def field_has_period(key: str) -> bool:
    spec = FIELD_SPECS.get(key)
    return bool(spec and spec["period"] is not None)


def field_default_period(key: str) -> Optional[int]:
    spec = FIELD_SPECS.get(key)
    return spec["period"] if spec else None


def field_display(key: str, period: Optional[int]) -> str:
    spec = FIELD_SPECS.get(key)
    if spec is None:
        return key
    if spec["period"] is not None:
        return f"{spec['label']} {period or spec['period']}"
    return spec["label"]


def _column_for(key: str, period: Optional[int]) -> Optional[str]:
    spec = FIELD_SPECS.get(key)
    if spec is None:
        return None
    return spec["col"](period or spec["period"])


@dataclass
class FilterCondition:
    field: str
    operator: str = "Above"
    value1: float = 0.0
    value2: Optional[float] = None
    field2: Optional[str] = None   # compared-to field for "Above/Below field"
    period: Optional[int] = None   # tunable period for `field` (None = field default)
    period2: Optional[int] = None  # tunable period for `field2`

    def __post_init__(self):
        # Migrate legacy field keys (e.g. "rsi14" -> "rsi"/14) on any
        # construction path, so old code, saved presets, and existing tests
        # keep working after the fields became period-parameterized.
        self.field, self.period = _migrate(self.field, self.period)
        self.field2, self.period2 = _migrate(self.field2, self.period2)

    def to_dict(self) -> dict:
        return {"field": self.field, "operator": self.operator, "value1": self.value1,
                "value2": self.value2, "field2": self.field2,
                "period": self.period, "period2": self.period2}

    @classmethod
    def from_dict(cls, data: dict) -> "FilterCondition":
        # __post_init__ handles legacy-key migration.
        return cls(
            field=data.get("field", "price"),
            operator=data.get("operator", "Above"),
            value1=float(data.get("value1", 0.0)),
            value2=(float(data["value2"]) if data.get("value2") is not None else None),
            field2=data.get("field2"),
            period=data.get("period"),
            period2=data.get("period2"),
        )

    def label(self) -> str:
        name = field_display(self.field, self.period)
        if self.operator in FIELD_OPERATORS:
            word = "above" if self.operator == "Above field" else "below"
            return f"{name} {word} {field_display(self.field2 or '', self.period2)}"
        if self.operator == "Between":
            return f"{name} between {self.value1:g} and {self.value2:g}"
        return f"{name} {self.operator.lower()} {self.value1:g}"


def _migrate(field, period):
    """Map a possibly-legacy field key to the current (key, period)."""
    if field in _LEGACY_FIELDS:
        return _LEGACY_FIELDS[field]
    return field, period


def ensure_columns(df: pd.DataFrame, conditions: list, cfg=None) -> pd.DataFrame:
    """Add any indicator columns the given conditions reference (at their
    chosen periods) that aren't already present. Returns df (mutated in
    place). Call this before evaluating conditions on a per-row basis."""
    for cond in conditions:
        for key, period in ((cond.field, cond.period), (cond.field2, cond.period2)):
            spec = FIELD_SPECS.get(key)
            if spec is None:
                continue
            col = spec["col"](period or spec["period"])
            if col not in df.columns:
                try:
                    df[col] = spec["compute"](df, period or spec["period"])
                except Exception:
                    df[col] = float("nan")
    return df


def _value(row: pd.Series, key: str, period: Optional[int]):
    col = _column_for(key, period)
    if col is None:
        return None
    return row.get(col, float("nan"))


def evaluate_condition(row: pd.Series, cfg, condition: FilterCondition) -> bool:
    if condition.field not in FIELD_SPECS:
        return True  # unknown field (e.g. from a newer version's file) - don't exclude everything
    value = _value(row, condition.field, condition.period)
    if value is None or pd.isna(value):
        return False
    if condition.operator in FIELD_OPERATORS:
        if condition.field2 not in FIELD_SPECS:
            return True  # forward-compat: unknown compared-to field
        other = _value(row, condition.field2, condition.period2)
        if other is None or pd.isna(other):
            return False
        return bool(value > other) if condition.operator == "Above field" else bool(value < other)
    if condition.operator == "Above":
        return bool(value > condition.value1)
    if condition.operator == "Below":
        return bool(value < condition.value1)
    if condition.operator == "Between":
        lo, hi = sorted([condition.value1, condition.value2 if condition.value2 is not None else condition.value1])
        return bool(lo <= value <= hi)
    return True


def passes_custom_filters(row: pd.Series, cfg, conditions: list) -> bool:
    return all(evaluate_condition(row, cfg, c) for c in conditions)
