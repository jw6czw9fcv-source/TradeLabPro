"""Headless smoke tests for the Risk & position-sizing panel."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(qapp, tmp_path):
    from tradelab.ui.app import RiskPanel
    from tradelab.data.database import Database
    return RiskPanel(Database(tmp_path / "risk_test.db"))   # isolated DB


def test_panel_constructs_with_disclaimer(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    texts = " ".join(lbl.text() for lbl in panel.findChildren(QLabel))
    assert "places no orders" in texts.lower()


def test_sizing_updates_live(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.equity.setValue(100_000)
    panel.risk_pct.setValue(1.0)
    panel.entry.setValue(50.0)
    panel.stop.setValue(45.0)
    panel._recompute()
    # $1,000 risk / $5 per share = 200 shares.
    assert "200 shares" in panel.result.text()
    # R-target table filled: 1R/2R/3R with position $ for 200 shares.
    assert panel.targets.rowCount() == 3
    assert panel.targets.item(0, 1).text() == "$55.00"          # 1R price
    assert panel.targets.item(2, 3).text() == "$3,000"          # 3R position P&L


def test_invalid_stop_shows_message(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.entry.setValue(50.0)
    panel.stop.setValue(50.0)          # stop == entry
    panel._recompute()
    assert "different" in panel.result.text().lower()


def test_short_targets_go_down(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.side.setCurrentText("Short")
    panel.entry.setValue(45.0)
    panel.stop.setValue(50.0)
    panel._recompute()
    assert panel.targets.item(0, 1).text() == "$40.00"          # 1R below entry


def test_exposure_handler_populates_table(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel._on_exposure([("Technology", 8000.0, 80.0), ("Energy", 2000.0, 20.0)], 10000.0)
    assert panel.exposure.rowCount() == 2
    # Sorted by value desc: Technology first.
    assert panel.exposure.item(0, 0).text() == "Technology"
    assert "80" in panel.exposure_status.text() or "Technology" in panel.exposure_status.text()


def test_load_exposure_with_no_positions_is_safe(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.load_exposure()   # fresh DB has no positions -> must not raise/worker
    assert panel._exposure_worker is None
    assert "No portfolio positions" in panel.exposure_status.text()
