"""Headless smoke tests for the Alerts UI panel. The store is pointed at a
temp file and no network check is triggered."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(qapp, tmp_path):
    from tradelab.ui.app import AlertsPanel
    from tradelab.core.alerts import AlertStore
    panel = AlertsPanel(symbol_provider=lambda: ["AAPL", "MSFT"])
    panel.store = AlertStore(tmp_path / "alerts.json")  # isolate from real data
    panel.refresh_table()
    return panel


def test_panel_constructs_with_disclaimer(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    texts = " ".join(lbl.text() for lbl in panel.findChildren(QLabel))
    assert "never place orders" in texts.lower()


def test_add_alert_populates_table(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.symbol_edit.setText("aapl")
    panel._cond_widgets["field"].setCurrentIndex(
        panel._cond_widgets["field"].findData("rsi"))
    panel._cond_widgets["op"].setCurrentText("Below")
    panel._cond_widgets["v1"].setValue(30)
    panel.add_alert()
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 0).text() == "AAPL"
    assert "RSI" in panel.table.item(0, 1).text()
    # Persisted to the store.
    assert len(panel.store.all()) == 1


def test_add_alert_requires_symbol(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.symbol_edit.setText("")
    panel.add_alert()
    assert panel.table.rowCount() == 0


def test_toggle_and_remove_selected(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.symbol_edit.setText("MSFT")
    panel.add_alert()
    panel.table.selectRow(0)
    aid = panel.store.all()[0].id
    assert panel.store.get(aid).enabled is True
    panel.toggle_selected()
    assert panel.store.get(aid).enabled is False
    panel.table.selectRow(0)
    panel.remove_selected()
    assert panel.table.rowCount() == 0


def test_run_check_no_active_alerts_is_safe(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.run_check(manual=True)  # must not raise or start a worker
    assert panel._worker is None
