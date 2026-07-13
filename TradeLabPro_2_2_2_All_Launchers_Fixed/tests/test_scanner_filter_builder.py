"""UI-level tests for the SCN-026 custom filter builder rows in ScannerPanel.

See tests/test_filters.py for the field/operator evaluation logic itself -
these tests only cover the widget wiring (add/remove row, read/write
values, persistence round-trip through save/load).
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


def test_starts_with_no_filter_rows(scanner_panel):
    assert scanner_panel.get_custom_filters() == []


def test_add_filter_row_appears_in_get_custom_filters(scanner_panel):
    scanner_panel.add_filter_row()
    filters = scanner_panel.get_custom_filters()
    assert len(filters) == 1
    assert filters[0]["operator"] == "Above"  # FilterCondition default


def test_editing_row_widgets_reflects_in_get_custom_filters(scanner_panel):
    scanner_panel.add_filter_row()
    w = scanner_panel._custom_filter_widgets[0]

    idx = w["field"].findData("rsi14")
    assert idx >= 0
    w["field"].setCurrentIndex(idx)
    w["op"].setCurrentText("Below")
    w["v1"].setValue(30)

    filters = scanner_panel.get_custom_filters()
    assert filters[0]["field"] == "rsi14"
    assert filters[0]["operator"] == "Below"
    assert filters[0]["value1"] == 30


def test_between_operator_shows_second_value_spinbox(scanner_panel):
    # isVisible() reflects actual on-screen visibility, which requires the
    # whole window to be shown - the panel is never .show()-n in this test,
    # so isHidden() (the widget's own explicit flag) is the right check.
    scanner_panel.add_filter_row()
    w = scanner_panel._custom_filter_widgets[0]
    assert w["v2"].isHidden()  # default operator is "Above"

    w["op"].setCurrentText("Between")
    assert not w["v2"].isHidden()

    w["v1"].setValue(30)
    w["v2"].setValue(70)
    filters = scanner_panel.get_custom_filters()
    assert filters[0]["value2"] == 70


def test_remove_filter_row(scanner_panel):
    scanner_panel.add_filter_row()
    scanner_panel.add_filter_row()
    assert len(scanner_panel.get_custom_filters()) == 2

    scanner_panel.remove_filter_row(scanner_panel._custom_filter_widgets[0]["row"])
    assert len(scanner_panel.get_custom_filters()) == 1


def test_set_custom_filters_replaces_existing_rows(scanner_panel):
    scanner_panel.add_filter_row()
    scanner_panel.set_custom_filters([
        {"field": "macd_hist", "operator": "Above", "value1": 0, "value2": None},
        {"field": "adx14", "operator": "Above", "value1": 25, "value2": None},
    ])
    filters = scanner_panel.get_custom_filters()
    assert len(filters) == 2
    assert [f["field"] for f in filters] == ["macd_hist", "adx14"]


def test_default_setup_clears_custom_filters(scanner_panel):
    scanner_panel.add_filter_row()
    scanner_panel.add_filter_row()
    assert len(scanner_panel.get_custom_filters()) == 2

    scanner_panel.default_setup()
    assert scanner_panel.get_custom_filters() == []


def test_custom_filters_round_trip_through_save_and_load(scanner_panel):
    scanner_panel.setup_name.setEditText("Filter Test")
    scanner_panel.set_custom_filters([{"field": "rsi14", "operator": "Above", "value1": 70, "value2": None}])
    scanner_panel.save_setup()

    scanner_panel.set_custom_filters([])  # simulate switching away
    assert scanner_panel.get_custom_filters() == []

    scanner_panel.load_setup_by_name("Filter Test")
    filters = scanner_panel.get_custom_filters()
    assert len(filters) == 1
    assert filters[0]["field"] == "rsi14"
    assert filters[0]["value1"] == 70


def test_current_config_includes_custom_filters(scanner_panel):
    scanner_panel.set_custom_filters([{"field": "rsi14", "operator": "Above", "value1": 70, "value2": None}])
    cfg = scanner_panel.current_config()
    assert len(cfg.custom_filters) == 1
    assert cfg.custom_filters[0]["field"] == "rsi14"
