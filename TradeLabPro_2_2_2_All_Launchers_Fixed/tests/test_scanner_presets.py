"""Regression tests for the Scanner Preset Manager upgrade (SCN-029).

The Setup name field became an editable combo box so switching between
saved presets is a pick from a list instead of an Open file dialog every
time. DATA_DIR is monkeypatched to a tmp_path so these tests never touch
the real data/setups folder.
"""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def scanner_panel(qapp, tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setattr("tradelab.ui.app.DATA_DIR", tmp_path)
    from tradelab.data.database import Database
    from tradelab.ui.chart_widget import ChartWidget
    from tradelab.ui.app import ScannerPanel

    db = Database(tmp_db_path)
    chart = ChartWidget()
    panel = ScannerPanel(db, chart)
    yield panel
    db.conn.close()


def test_refresh_preset_list_starts_empty(scanner_panel):
    assert scanner_panel.setup_name.count() == 0
    assert scanner_panel.setup_name.currentText() == "Default Setup"


def test_save_setup_adds_it_to_the_preset_dropdown(scanner_panel):
    scanner_panel.setup_name.setEditText("My Swing Setup")
    scanner_panel.save_setup()

    items = [scanner_panel.setup_name.itemText(i) for i in range(scanner_panel.setup_name.count())]
    assert "My Swing Setup" in items
    assert scanner_panel.setup_name.currentText() == "My Swing Setup"


def test_save_setup_as_adds_new_name_to_dropdown(scanner_panel, tmp_path, monkeypatch):
    save_path = tmp_path / "setups" / "Breakout Scan.json"

    def fake_get_save_file_name(*args, **kwargs):
        return str(save_path), "JSON files (*.json)"

    monkeypatch.setattr("tradelab.ui.app.QFileDialog.getSaveFileName", fake_get_save_file_name)
    scanner_panel.save_setup_as()

    items = [scanner_panel.setup_name.itemText(i) for i in range(scanner_panel.setup_name.count())]
    assert "Breakout Scan" in items
    assert scanner_panel.setup_name.currentText() == "Breakout Scan"


def test_picking_a_preset_loads_its_saved_values(scanner_panel):
    scanner_panel.setup_name.setEditText("Aggressive")
    scanner_panel.min_score.setValue(85)
    scanner_panel.min_rsi.setValue(40)
    scanner_panel.save_setup()

    # Simulate switching to a different in-progress (unsaved) state...
    scanner_panel.min_score.setValue(10)
    scanner_panel.min_rsi.setValue(0)

    # ...then picking the saved preset back from the dropdown restores it.
    idx = scanner_panel.setup_name.findText("Aggressive")
    assert idx >= 0
    scanner_panel.on_preset_picked(idx)

    assert scanner_panel.min_score.value() == 85
    assert scanner_panel.min_rsi.value() == 40
    assert scanner_panel.setup_name.currentText() == "Aggressive"


def test_delete_setup_removes_it_from_dropdown(scanner_panel, monkeypatch):
    scanner_panel.setup_name.setEditText("Temp Setup")
    scanner_panel.save_setup()
    assert scanner_panel.setup_name.findText("Temp Setup") >= 0

    monkeypatch.setattr("tradelab.ui.app.QMessageBox.question", lambda *a, **k: __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.Yes)
    scanner_panel.delete_setup()

    assert scanner_panel.setup_name.findText("Temp Setup") == -1


def test_new_setup_names_it_new_setup_not_default(scanner_panel):
    """Regression test: default_setup() (called by both the Reset button
    and new_setup()) used to reset the name to "Default Setup" itself,
    so new_setup() setting the name to "New Setup" first and then calling
    default_setup() silently clobbered it right back.
    """
    scanner_panel.new_setup()
    assert scanner_panel.setup_name.currentText() == "New Setup"


def test_strategy_defaults_to_ema_macd(scanner_panel):
    assert scanner_panel.strategy.currentData() == "ema_macd"


def test_current_config_includes_selected_strategy(scanner_panel):
    scanner_panel.set_strategy("rsi_reversion")
    cfg = scanner_panel.current_config()
    assert cfg.strategy == "rsi_reversion"


def test_strategy_round_trips_through_save_and_load(scanner_panel):
    scanner_panel.setup_name.setEditText("Reversion Setup")
    scanner_panel.set_strategy("rsi_reversion")
    scanner_panel.save_setup()

    scanner_panel.set_strategy("ema_macd")  # simulate switching away
    assert scanner_panel.strategy.currentData() == "ema_macd"

    scanner_panel.load_setup_by_name("Reversion Setup")
    assert scanner_panel.strategy.currentData() == "rsi_reversion"


def test_default_setup_resets_strategy_to_ema_macd(scanner_panel):
    scanner_panel.set_strategy("rsi_reversion")
    scanner_panel.default_setup()
    assert scanner_panel.strategy.currentData() == "ema_macd"
