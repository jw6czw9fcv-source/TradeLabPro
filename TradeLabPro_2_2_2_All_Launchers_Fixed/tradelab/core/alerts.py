"""Alerts engine (Qt-free, offline-testable).

An Alert watches one symbol for one condition (a FilterCondition - the same
type the Scanner filter builder and no-code strategies use) and fires when
that condition becomes true. Firing is *edge-triggered*: an alert fires when
the condition transitions from false to true, not on every check while it
stays true, so "RSI Below 30" fires once as price drops through 30 rather
than every poll. This gives natural "cross above / cross below" behaviour
out of the existing level comparisons.

Two trigger modes:
  * "once"      - fire a single time, then disarm (enabled -> False).
  * "recurring" - re-arm automatically once the condition goes false again,
                  so it can fire on the next crossing.

The engine is transport-injectable: evaluate_alerts() takes a history
provider (defaults to market_data.get_history) so the whole thing runs
offline in tests against synthetic data. All Qt / notification / threading
lives in the UI layer (AlertsPanel), never here.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from tradelab.core.config import DATA_DIR
from tradelab.core.filters import FilterCondition, ensure_columns, evaluate_condition
from tradelab.core.indicators import add_indicators

ALERTS_PATH = DATA_DIR / "alerts.json"

TRIGGER_MODES = ("once", "recurring")


@dataclass
class Alert:
    symbol: str
    condition: FilterCondition
    name: str = ""
    enabled: bool = True
    trigger_mode: str = "recurring"      # "once" | "recurring"
    interval: str = "1d"                  # bar interval to evaluate on
    period: str = "6mo"                   # history window to fetch
    note: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    last_triggered_at: Optional[float] = None
    last_price: Optional[float] = None
    trigger_count: int = 0
    # Internal edge-detection state: was the condition true at the last check?
    # Persisted so a restart doesn't immediately re-fire an already-true alert.
    armed: bool = True                    # ready to fire (condition currently false or never checked)

    def __post_init__(self):
        if self.symbol:
            self.symbol = self.symbol.strip().upper()
        if self.trigger_mode not in TRIGGER_MODES:
            self.trigger_mode = "recurring"

    def label(self) -> str:
        base = self.name.strip() or f"{self.symbol} {self.condition.label()}"
        return base

    def status(self) -> str:
        if not self.enabled:
            return "Off"
        if self.last_triggered_at and self.trigger_mode == "once":
            return "Triggered"
        return "Armed" if self.armed else "Waiting"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "condition": self.condition.to_dict(),
            "name": self.name,
            "enabled": self.enabled,
            "trigger_mode": self.trigger_mode,
            "interval": self.interval,
            "period": self.period,
            "note": self.note,
            "created_at": self.created_at,
            "last_triggered_at": self.last_triggered_at,
            "last_price": self.last_price,
            "trigger_count": self.trigger_count,
            "armed": self.armed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Alert":
        cond = FilterCondition.from_dict(data.get("condition", {}))
        alert = cls(
            symbol=data.get("symbol", ""),
            condition=cond,
            name=data.get("name", ""),
            enabled=bool(data.get("enabled", True)),
            trigger_mode=data.get("trigger_mode", "recurring"),
            interval=data.get("interval", "1d"),
            period=data.get("period", "6mo"),
            note=data.get("note", ""),
        )
        # Preserve stored identity / history if present.
        if data.get("id"):
            alert.id = data["id"]
        if data.get("created_at") is not None:
            alert.created_at = float(data["created_at"])
        alert.last_triggered_at = data.get("last_triggered_at")
        alert.last_price = data.get("last_price")
        alert.trigger_count = int(data.get("trigger_count", 0))
        alert.armed = bool(data.get("armed", True))
        return alert


@dataclass
class AlertEvent:
    """One firing of an alert, produced by evaluate_alerts()."""
    alert_id: str
    symbol: str
    message: str
    price: Optional[float]
    timestamp: float

    def to_dict(self) -> dict:
        return {"alert_id": self.alert_id, "symbol": self.symbol,
                "message": self.message, "price": self.price,
                "timestamp": self.timestamp}


def _latest_condition_state(df: pd.DataFrame, condition: FilterCondition) -> tuple[bool, Optional[float]]:
    """Return (condition_is_true, latest_close) for the most recent bar."""
    if df is None or df.empty or len(df) < 2:
        return False, None
    indicators = add_indicators(df)
    ensure_columns(indicators, [condition])
    last = indicators.iloc[-1]
    try:
        price = float(last.get("Close"))
    except Exception:
        price = None
    is_true = evaluate_condition(last, None, condition)
    return bool(is_true), price


def evaluate_alert(alert: Alert, history_provider: Callable[..., pd.DataFrame],
                   now: Optional[float] = None) -> Optional[AlertEvent]:
    """Evaluate one alert against fresh history. Mutates the alert's
    edge-detection state (armed / last_triggered_at / trigger_count) and
    returns an AlertEvent if it fired this check, else None.

    Edge-triggered: fires only when the condition transitions false -> true
    (i.e. the alert is currently `armed`). A `once` alert disables itself
    after firing; a `recurring` alert re-arms as soon as the condition is
    false again.
    """
    if not alert.enabled or not alert.symbol:
        return None
    now = time.time() if now is None else now
    try:
        df = history_provider(alert.symbol, alert.period, alert.interval)
    except Exception:
        return None

    is_true, price = _latest_condition_state(df, alert.condition)
    if price is not None:
        alert.last_price = round(price, 4)

    if is_true and alert.armed:
        # Fire: false -> true crossing.
        alert.armed = False
        alert.last_triggered_at = now
        alert.trigger_count += 1
        if alert.trigger_mode == "once":
            alert.enabled = False
        msg = f"{alert.symbol}: {alert.condition.label()}"
        if price is not None:
            msg += f"  (price ${price:,.2f})"
        return AlertEvent(alert.id, alert.symbol, msg, price, now)

    if not is_true and not alert.armed:
        # Condition released - re-arm for the next crossing.
        alert.armed = True

    return None


def evaluate_alerts(alerts: list[Alert], history_provider: Optional[Callable[..., pd.DataFrame]] = None,
                    now: Optional[float] = None) -> list[AlertEvent]:
    """Evaluate every enabled alert, returning the events that fired this
    pass. `history_provider(symbol, period, interval) -> DataFrame` defaults
    to market_data.get_history; inject a fake in tests to stay offline."""
    if history_provider is None:
        from tradelab.data.market_data import get_history
        history_provider = get_history
    events: list[AlertEvent] = []
    for alert in alerts:
        event = evaluate_alert(alert, history_provider, now=now)
        if event is not None:
            events.append(event)
    return events


class AlertStore:
    """JSON-backed persistence for a list of Alerts (data/alerts.json,
    gitignored - it is per-user runtime state, like data/paper_account.json).
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else ALERTS_PATH
        self._alerts: list[Alert] = []
        self.load()

    # --- collection helpers -------------------------------------------------
    def all(self) -> list[Alert]:
        return list(self._alerts)

    def get(self, alert_id: str) -> Optional[Alert]:
        return next((a for a in self._alerts if a.id == alert_id), None)

    def add(self, alert: Alert) -> Alert:
        self._alerts.append(alert)
        self.save()
        return alert

    def remove(self, alert_id: str) -> bool:
        before = len(self._alerts)
        self._alerts = [a for a in self._alerts if a.id != alert_id]
        changed = len(self._alerts) != before
        if changed:
            self.save()
        return changed

    def clear(self) -> None:
        self._alerts = []
        self.save()

    # --- persistence --------------------------------------------------------
    def load(self) -> list[Alert]:
        self._alerts = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._alerts = [Alert.from_dict(d) for d in data.get("alerts", [])]
            except Exception:
                # Corrupt file must never crash the app - start empty.
                self._alerts = []
        return self._alerts

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"alerts": [a.to_dict() for a in self._alerts]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
