"""User-defined no-code strategies (Phase 5, Strategy Builder).

A CustomStrategy is a name plus two lists of FilterConditions (the same
condition type the Scanner's SCN-026 filter builder uses): BUY fires on the
bar where *all* BUY conditions first become true (a rising edge, so it
behaves like a crossover event rather than staying triggered), and SELL
likewise. It exposes the exact same interface as the built-in strategy
modules (NAME / score_symbol / signal_series), so it drops straight into
the registry, the Scanner, the Backtest engine, and confidence scoring
with no special-casing.

Persisted as JSON under DATA_DIR/strategies/ so the builder UI can
save/load/delete them and they survive restarts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tradelab.core.config import DATA_DIR
from tradelab.core.filters import FilterCondition, ensure_columns, evaluate_condition
from tradelab.core.indicators import add_indicators

CUSTOM_PREFIX = "custom:"


def _strategies_dir() -> Path:
    d = DATA_DIR / "strategies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in (name or "")).strip() or "strategy"


class CustomStrategy:
    def __init__(self, name: str, buy_conditions: list, sell_conditions: list):
        self.name = name
        self.NAME = name
        self.buy_conditions = buy_conditions
        self.sell_conditions = sell_conditions

    # -- persistence ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "buy": [c.to_dict() for c in self.buy_conditions],
            "sell": [c.to_dict() for c in self.sell_conditions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CustomStrategy":
        return cls(
            name=data.get("name", "Custom Strategy"),
            buy_conditions=[FilterCondition.from_dict(c) for c in data.get("buy", [])],
            sell_conditions=[FilterCondition.from_dict(c) for c in data.get("sell", [])],
        )

    def save(self) -> Path:
        path = _strategies_dir() / f"{_safe_name(self.name)}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    # -- runnable strategy interface -----------------------------------
    def _all_true(self, df: pd.DataFrame, cfg, conditions: list) -> pd.Series:
        if not conditions:
            return pd.Series(False, index=df.index)
        active = pd.Series(True, index=df.index)
        for cond in conditions:
            active &= df.apply(lambda row: evaluate_condition(row, cfg, cond), axis=1)
        return active

    def signal_series(self, df: pd.DataFrame, cfg) -> pd.Series:
        # Compute any period-specific columns the conditions reference
        # (e.g. EMA20, RSI7) before evaluating them per bar.
        df = ensure_columns(df.copy(), self.buy_conditions + self.sell_conditions, cfg)
        out = pd.Series("", index=df.index)
        buy_active = self._all_true(df, cfg, self.buy_conditions)
        sell_active = self._all_true(df, cfg, self.sell_conditions)
        # Rising edge: fire only on the bar where the block first becomes true.
        buy_fire = buy_active & (~buy_active.shift(1, fill_value=False))
        sell_fire = sell_active & (~sell_active.shift(1, fill_value=False))
        out[buy_fire] = "BUY"
        out[sell_fire] = "SELL"  # SELL wins if both fire on the same bar
        return out

    def score_symbol(self, df: pd.DataFrame, cfg) -> dict:
        data = add_indicators(df, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        ensure_columns(data, self.buy_conditions + self.sell_conditions, cfg)
        signals = self.signal_series(data, cfg)
        last = data.iloc[-1]
        last_signal = signals.iloc[-1] or "HOLD"
        met = sum(1 for c in self.buy_conditions if evaluate_condition(last, cfg, c))
        total = len(self.buy_conditions) or 1
        score = 50 + int(40 * met / total)
        if last_signal == "BUY":
            score += 10
        elif last_signal == "SELL":
            score -= 25
        return {"signal": last_signal, "score": max(0, min(100, score)), "data": data}


def list_custom_strategies() -> list[str]:
    d = DATA_DIR / "strategies"
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_custom_strategy(name: str) -> CustomStrategy | None:
    path = _strategies_dir() / f"{_safe_name(name)}.json"
    if not path.exists():
        return None
    try:
        return CustomStrategy.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def delete_custom_strategy(name: str) -> bool:
    path = _strategies_dir() / f"{_safe_name(name)}.json"
    if path.exists():
        path.unlink()
        return True
    return False
