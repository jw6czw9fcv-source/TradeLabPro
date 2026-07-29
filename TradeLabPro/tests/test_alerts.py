"""Alerts engine tests - all offline via an injected history provider."""
import numpy as np
import pandas as pd

from tradelab.core.alerts import (Alert, AlertStore, evaluate_alert,
                                   evaluate_alerts)
from tradelab.core.filters import FilterCondition


def _history(close_last: float, n: int = 120) -> pd.DataFrame:
    """A synthetic OHLCV frame whose final Close is `close_last`."""
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="B")
    close = np.linspace(50.0, close_last, n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": np.full(n, 1_000_000)},
        index=dates,
    )


def _price_alert(threshold: float, operator: str = "Above", **kw) -> Alert:
    cond = FilterCondition(field="price", operator=operator, value1=threshold)
    return Alert(symbol="TEST", condition=cond, **kw)


def test_roundtrip_to_from_dict_preserves_identity_and_state():
    a = _price_alert(100.0, name="cross 100", trigger_mode="once")
    a.trigger_count = 3
    a.armed = False
    restored = Alert.from_dict(a.to_dict())
    assert restored.id == a.id
    assert restored.symbol == "TEST"
    assert restored.name == "cross 100"
    assert restored.trigger_mode == "once"
    assert restored.trigger_count == 3
    assert restored.armed is False
    assert restored.condition.value1 == 100.0
    assert restored.condition.operator == "Above"


def test_symbol_is_uppercased():
    a = Alert(symbol=" aapl ", condition=FilterCondition(field="price", value1=1))
    assert a.symbol == "AAPL"


def test_fires_once_on_false_to_true_crossing():
    # Price ends at 150, threshold 100 Above -> condition true.
    alert = _price_alert(100.0, operator="Above")
    provider = lambda sym, period, interval: _history(150.0)

    ev1 = evaluate_alert(alert, provider)
    assert ev1 is not None
    assert ev1.symbol == "TEST"
    assert "price" in ev1.message.lower() or "$" in ev1.message
    assert alert.trigger_count == 1
    assert alert.armed is False

    # Still true on the next check -> must NOT re-fire (edge-triggered).
    ev2 = evaluate_alert(alert, provider)
    assert ev2 is None
    assert alert.trigger_count == 1


def test_recurring_rearms_after_condition_releases():
    alert = _price_alert(100.0, operator="Above", trigger_mode="recurring")

    high = lambda sym, period, interval: _history(150.0)   # condition true
    low = lambda sym, period, interval: _history(80.0)     # condition false

    assert evaluate_alert(alert, high) is not None          # fires
    assert evaluate_alert(alert, high) is None              # stays true, no re-fire
    assert evaluate_alert(alert, low) is None               # releases, re-arms
    assert alert.armed is True
    assert evaluate_alert(alert, high) is not None          # fires again on re-cross
    assert alert.trigger_count == 2


def test_once_mode_disables_after_firing():
    alert = _price_alert(100.0, operator="Above", trigger_mode="once")
    high = lambda sym, period, interval: _history(150.0)
    assert evaluate_alert(alert, high) is not None
    assert alert.enabled is False
    # Disabled -> never evaluated again even if re-armed conditions occur.
    assert evaluate_alert(alert, high) is None
    assert alert.trigger_count == 1


def test_disabled_alert_never_fires():
    alert = _price_alert(100.0, operator="Above", enabled=False)
    high = lambda sym, period, interval: _history(150.0)
    assert evaluate_alert(alert, high) is None
    assert alert.trigger_count == 0


def test_provider_exception_is_swallowed():
    alert = _price_alert(100.0)
    def boom(sym, period, interval):
        raise RuntimeError("network down")
    assert evaluate_alert(alert, boom) is None
    assert alert.trigger_count == 0


def test_evaluate_alerts_batch_returns_only_fired():
    fired = _price_alert(100.0, operator="Above")     # 150 > 100 true
    quiet = _price_alert(200.0, operator="Above")     # 150 > 200 false
    provider = lambda sym, period, interval: _history(150.0)
    events = evaluate_alerts([fired, quiet], provider)
    assert len(events) == 1
    assert events[0].alert_id == fired.id


def test_last_price_recorded_even_without_firing():
    alert = _price_alert(500.0, operator="Above")     # stays false
    provider = lambda sym, period, interval: _history(150.0)
    assert evaluate_alert(alert, provider) is None
    assert alert.last_price == 150.0


def test_store_add_remove_persist(tmp_path):
    path = tmp_path / "alerts.json"
    store = AlertStore(path)
    assert store.all() == []
    a = store.add(_price_alert(100.0, name="one"))
    assert len(store.all()) == 1
    assert path.exists()

    # Reload from disk - should round-trip.
    reloaded = AlertStore(path)
    assert len(reloaded.all()) == 1
    assert reloaded.get(a.id).name == "one"

    assert reloaded.remove(a.id) is True
    assert reloaded.all() == []
    assert AlertStore(path).all() == []


def test_store_survives_corrupt_file(tmp_path):
    path = tmp_path / "alerts.json"
    path.write_text("{ not valid json", encoding="utf-8")
    store = AlertStore(path)   # must not raise
    assert store.all() == []


def test_status_strings():
    a = _price_alert(100.0)
    assert a.status() == "Armed"
    a.armed = False
    assert a.status() == "Waiting"
    a.enabled = False
    assert a.status() == "Off"
    once = _price_alert(100.0, trigger_mode="once")
    once.last_triggered_at = 1.0
    assert once.status() == "Triggered"
