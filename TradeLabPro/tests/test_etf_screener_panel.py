"""Headless tests for the ETF Screener panel.

No network: the refresh worker is never started against Yahoo here, only its
signal handlers are driven directly with metrics the tests supply.
"""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from tradelab.data.database import Database


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp, tmp_path):
    from tradelab.ui.app import EtfScreenerPanel
    return EtfScreenerPanel(Database(path=tmp_path / "etf_test.db"))


def _col(panel, key):
    return [i for i, c in enumerate(panel.COLUMNS) if c[0] == key][0]


def _cell(panel, row, key):
    return panel.table.item(row, _col(panel, key))


# -- adding and removing ----------------------------------------------------

def test_panel_constructs_empty(panel):
    assert panel.table.rowCount() == 0


def test_add_fund_populates_table_and_db(panel):
    panel.ticker_edit.setText("vfv")
    panel.yahoo_edit.setText("VFV.TO")
    panel.add_fund()
    assert panel.table.rowCount() == 1
    assert _cell(panel, 0, "ticker").text() == "VFV"
    assert panel.db.etf_get("VFV")["yahoo"] == "VFV.TO"


def test_add_fund_without_yahoo_defaults_to_the_ticker(panel):
    panel.ticker_edit.setText("XUU")
    panel.add_fund()
    assert panel.db.etf_get("XUU")["yahoo"] == "XUU"


def test_add_fund_requires_a_ticker(panel):
    panel.ticker_edit.setText("   ")
    panel.add_fund()
    assert panel.table.rowCount() == 0


def test_adding_an_existing_ticker_does_not_duplicate_it(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    panel.ticker_edit.setText("VFV"); panel.yahoo_edit.setText("VFV.TO"); panel.add_fund()
    assert panel.table.rowCount() == 1
    assert panel.db.etf_get("VFV")["yahoo"] == "VFV.TO"


def test_remove_selected_deletes_from_db(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    panel.table.selectRow(0)
    panel.remove_selected()
    assert panel.table.rowCount() == 0
    assert panel.db.etf_get("VFV") is None


def test_remove_with_nothing_selected_is_a_noop(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    panel.table.clearSelection()
    panel.remove_selected()
    assert panel.table.rowCount() == 1


# -- editing cells ----------------------------------------------------------

def test_editing_ma_compo_persists_as_a_fraction(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    item = _cell(panel, 0, "ma_compo")
    item.setText("20")                     # typed as a percent
    assert panel.db.etf_get("VFV")["ma_compo"] == pytest.approx(0.20)
    assert item.text() == "20.0%"          # redrawn in the stored unit


def test_editing_accepts_a_typed_percent_sign_and_a_comma(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "pct_us").setText("62,5 %")
    assert panel.db.etf_get("VFV")["pct_us"] == pytest.approx(0.625)


def test_clearing_a_numeric_cell_stores_none_not_zero(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "ma_compo").setText("20")
    _cell(panel, 0, "ma_compo").setText("")
    assert panel.db.etf_get("VFV")["ma_compo"] is None


def test_editing_risk_stores_an_integer(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "risk").setText("4")
    assert panel.db.etf_get("VFV")["risk"] == 4


def test_editing_a_text_cell_persists_verbatim(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "notes").setText("cœur US, non couvert")
    assert panel.db.etf_get("VFV")["notes"] == "cœur US, non couvert"


def test_computed_columns_are_not_editable(panel):
    from PySide6.QtCore import Qt
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    for key in ("ticker", "ret_1a", "volatility", "sharpe", "updated_at"):
        assert not (_cell(panel, 0, key).flags() & Qt.ItemIsEditable), key
    for key in ("ma_compo", "notes", "mer", "risk"):
        assert _cell(panel, 0, key).flags() & Qt.ItemIsEditable, key


def test_percentages_are_displayed_as_percents(panel):
    panel.db.etf_upsert("VFV", ret_1a=0.25, mer=0.0009, sharpe=1.234)
    panel.reload()
    assert _cell(panel, 0, "ret_1a").text() == "25.0%"
    assert _cell(panel, 0, "mer").text() == "0.09%"      # MER needs 2 decimals
    assert _cell(panel, 0, "sharpe").text() == "1.23"


def test_missing_values_render_blank_not_none(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    assert _cell(panel, 0, "ret_10a").text() == ""


# -- composition summary ----------------------------------------------------

def test_summary_totals_the_allocation(panel):
    panel.db.etf_upsert("VFV", pct_us=1.0, ma_compo=0.6)
    panel.db.etf_upsert("VAB", pct_bond=1.0, ma_compo=0.4)
    panel.reload()
    assert "100.0%" in panel.summary.item(0, 1).text()
    assert "OK" in panel.summary.item(0, 1).text()


def test_summary_flags_an_allocation_that_does_not_add_up(panel):
    panel.db.etf_upsert("VFV", ma_compo=0.6)
    panel.reload()
    assert "ajuster" in panel.summary.item(0, 1).text()


def test_summary_updates_when_a_weight_is_edited(panel):
    panel.db.etf_upsert("VFV", pct_us=1.0)
    panel.reload()
    _cell(panel, 0, "ma_compo").setText("100")
    assert "100.0%" in panel.summary.item(0, 1).text()


def test_summary_names_partial_coverage(panel):
    panel.db.etf_upsert("VFV", ret_10a=0.16, ma_compo=0.5)
    panel.db.etf_upsert("GGOV", ma_compo=0.5)      # created 2025, no 10-year
    panel.reload()
    row = [i for i, (_l, col, _k) in enumerate(_composition_rows(), start=1)
           if col == "ret_10a"][0]
    assert "sur 50" in panel.summary.item(row, 1).text()


def _composition_rows():
    from tradelab.core.etf_metrics import COMPOSITION_ROWS
    return COMPOSITION_ROWS


# -- refresh ----------------------------------------------------------------

def test_refresh_is_a_noop_with_no_funds(panel):
    panel.refresh_metrics()          # must not raise or start a worker
    assert panel.worker is None


def test_row_done_writes_metrics_without_touching_user_fields(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    panel.db.etf_upsert("VFV", notes="cœur US", ma_compo=0.2)
    panel._on_row_done("VFV", {"ret_1a": 0.25, "volatility": 0.14})
    fund = panel.db.etf_get("VFV")
    assert fund["ret_1a"] == pytest.approx(0.25)
    assert fund["notes"] == "cœur US"
    assert fund["ma_compo"] == pytest.approx(0.2)


def test_row_done_with_no_metrics_leaves_the_row_alone(panel):
    panel.db.etf_upsert("VFV", ret_1a=0.25)
    panel._on_row_done("VFV", None)
    assert panel.db.etf_get("VFV")["ret_1a"] == pytest.approx(0.25)


def test_finish_handler_reports_and_re_enables_the_button(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    panel.refresh_btn.setEnabled(False)
    panel._on_refresh_finished(3, 1, False)
    assert panel.refresh_btn.isEnabled()
    assert not panel.progress.isVisible()
    assert "3" in panel.status.text() and "1" in panel.status.text()


def test_finish_handler_says_when_it_was_stopped(panel):
    panel._on_refresh_finished(1, 0, True)
    assert "Arrêté" in panel.status.text()


def test_worker_carries_the_yahoo_symbol_not_the_ticker(panel):
    from tradelab.ui.app import EtfMetricsWorker
    panel.db.etf_upsert("VFV", yahoo="VFV.TO")
    rows = [(f["ticker"], f["yahoo"] or f["ticker"]) for f in panel.db.etf_list()]
    worker = EtfMetricsWorker(rows)
    assert worker.rows == [("VFV", "VFV.TO")]
