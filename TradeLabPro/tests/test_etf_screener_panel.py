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


@pytest.fixture
def no_network(monkeypatch):
    """Stop the analysis buttons from starting a real Yahoo worker.

    The suite's rule is no live calls. `show_look_through()` is tested for the
    state it sets up, then its handler is driven by hand with data the test
    supplies — but the real worker would otherwise be off fetching while that
    happens, which is both a live call and a thread outliving the test."""
    from tradelab.ui import app as appmod
    started = []

    class _NoWorker:
        def __init__(self, *args, **kwargs):
            started.append((args, kwargs))
            self.done = self
            self.progress = self
            self.finished = self        # the panel tracks workers by it

        def connect(self, *_a, **_k):
            pass

        def start(self):
            pass

        def isRunning(self):
            return False

    for name in ("_FundCompositionWorker", "_MarketRefreshWorker"):
        monkeypatch.setattr(appmod, name, _NoWorker)
    return started


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


def test_re_adding_a_ticker_does_not_wipe_its_yahoo_symbol(panel):
    """Re-adding VFV with the Yahoo box empty overwrote VFV.TO with VFV — a
    symbol Yahoo neither prices nor can open up, which quietly turned a fund
    into a "held directly" line in the look-through."""
    panel.ticker_edit.setText("VFV"); panel.yahoo_edit.setText("VFV.TO")
    panel.add_fund()
    panel.ticker_edit.setText("VFV"); panel.add_fund()      # Yahoo box empty
    assert panel.db.etf_get("VFV")["yahoo"] == "VFV.TO"
    assert "already listed" in panel.status.text()


def test_re_adding_with_a_symbol_typed_still_changes_it(panel):
    panel.ticker_edit.setText("VFV"); panel.yahoo_edit.setText("VFV.TO")
    panel.add_fund()
    panel.ticker_edit.setText("VFV"); panel.yahoo_edit.setText("VOO")
    panel.add_fund()
    assert panel.db.etf_get("VFV")["yahoo"] == "VOO"


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

def test_editing_an_allocation_persists_as_a_fraction(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    item = _cell(panel, 0, "mid_risk")
    item.setText("20")                     # typed as a percent
    assert panel.db.etf_get("VFV")["mid_risk"] == pytest.approx(0.20)
    assert item.text() == "20.0%"          # redrawn in the stored unit


def test_editing_accepts_a_typed_percent_sign_and_a_comma(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "pct_us").setText("62,5 %")
    assert panel.db.etf_get("VFV")["pct_us"] == pytest.approx(0.625)


def test_clearing_a_numeric_cell_stores_none_not_zero(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "mid_risk").setText("20")
    _cell(panel, 0, "mid_risk").setText("")
    assert panel.db.etf_get("VFV")["mid_risk"] is None


def test_editing_a_weight_column_stores_a_fraction(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "low_risk").setText("28")
    assert panel.db.etf_get("VFV")["low_risk"] == pytest.approx(0.28)


def test_editing_a_text_cell_persists_verbatim(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    _cell(panel, 0, "notes").setText("cœur US, non couvert")
    assert panel.db.etf_get("VFV")["notes"] == "cœur US, non couvert"


def test_computed_columns_are_not_editable(panel):
    from PySide6.QtCore import Qt
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    for key in ("ticker", "ret_1a", "volatility", "csa_level", "updated_at"):
        assert not (_cell(panel, 0, key).flags() & Qt.ItemIsEditable), key
    for key in ("mid_risk", "notes", "mer", "category"):
        assert _cell(panel, 0, key).flags() & Qt.ItemIsEditable, key


def test_percentages_are_displayed_as_percents(panel):
    panel.db.etf_upsert("VFV", ret_1a=0.25, mer=0.0009, dividend_yield=0.033)
    panel.reload()
    assert _cell(panel, 0, "ret_1a").text() == "25.0%"
    assert _cell(panel, 0, "mer").text() == "0.09%"      # MER needs 2 decimals
    assert _cell(panel, 0, "dividend_yield").text() == "3.3%"


def test_missing_values_render_blank_not_none(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    assert _cell(panel, 0, "ret_10a").text() == ""


# -- composition summary ----------------------------------------------------

def _summary_col(panel, weight_key):
    """Column index of one allocation in the summary table (column 0 is the
    row label), resolved by name so reordering them can't silently make a
    test read a different mix."""
    return 1 + [k for _label, k in panel.COMPOSITIONS].index(weight_key)


def _summary_row(panel, column):
    from tradelab.core.etf_metrics import COMPOSITION_ROWS
    return 1 + [col for _l, col, _k in COMPOSITION_ROWS].index(column)


def test_the_allocations_are_a_low_mid_high_ladder(panel):
    """"My mix" is gone: it duplicated Mid risk on every row of the workbook
    it came from, so it was a second name for the same column."""
    assert [k for _label, k in panel.COMPOSITIONS] == [
        "low_risk", "mid_risk", "high_risk"]
    headers = [panel.summary.horizontalHeaderItem(c).text()
               for c in range(1, panel.summary.columnCount())]
    assert headers == ["Low risk", "Mid risk", "High risk"]


def test_summary_totals_the_allocation(panel):
    panel.db.etf_upsert("VFV", pct_us=1.0, mid_risk=0.6)
    panel.db.etf_upsert("VAB", pct_bond=1.0, mid_risk=0.4)
    panel.reload()
    cell = panel.summary.item(0, _summary_col(panel, "mid_risk")).text()
    assert "100.0%" in cell
    assert "OK" in cell


def test_summary_flags_an_allocation_that_does_not_add_up(panel):
    panel.db.etf_upsert("VFV", mid_risk=0.6)
    panel.reload()
    assert "adjust" in panel.summary.item(0, _summary_col(panel, "mid_risk")).text()


def test_summary_updates_when_a_weight_is_edited(panel):
    panel.db.etf_upsert("VFV", pct_us=1.0)
    panel.reload()
    _cell(panel, 0, "mid_risk").setText("100")
    assert "100.0%" in panel.summary.item(0, _summary_col(panel, "mid_risk")).text()


def test_each_allocation_is_totalled_from_its_own_column(panel):
    # A weight typed under Low risk must not leak into the other three.
    panel.db.etf_upsert("VAB", pct_bond=1.0, low_risk=1.0)
    panel.reload()
    assert "100.0%" in panel.summary.item(0, _summary_col(panel, "low_risk")).text()
    for key in ("low_risk", "mid_risk", "high_risk"):
        assert "0.0%" in panel.summary.item(0, _summary_col(panel, key)).text()


def test_editing_low_risk_persists(panel):
    panel.ticker_edit.setText("VAB"); panel.add_fund()
    _cell(panel, 0, "low_risk").setText("28")
    assert panel.db.etf_get("VAB")["low_risk"] == pytest.approx(0.28)


def test_summary_names_partial_coverage(panel):
    panel.db.etf_upsert("VFV", ret_10a=0.16, mid_risk=0.5)
    panel.db.etf_upsert("GGOV", mid_risk=0.5)      # created 2025, no 10-year
    panel.reload()
    cell = panel.summary.item(_summary_row(panel, "ret_10a"),
                              _summary_col(panel, "mid_risk"))
    assert "of 50%" in cell.text()


# -- refresh ----------------------------------------------------------------

def test_refresh_is_a_noop_with_no_funds(panel):
    panel.refresh_metrics()          # must not raise or start a worker
    assert panel.worker is None


def test_row_done_writes_metrics_without_touching_user_fields(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    panel.db.etf_upsert("VFV", notes="cœur US", mid_risk=0.2)
    panel._on_row_done("VFV", {"ret_1a": 0.25, "volatility": 0.14})
    fund = panel.db.etf_get("VFV")
    assert fund["ret_1a"] == pytest.approx(0.25)
    assert fund["notes"] == "cœur US"
    assert fund["mid_risk"] == pytest.approx(0.2)


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
    assert "Stopped" in panel.status.text()


# -- filter, watchlist / portfolio, export ----------------------------------

def _add(panel, *tickers):
    for ticker in tickers:
        panel.ticker_edit.setText(ticker)
        panel.add_fund()


def test_filter_hides_rows_that_do_not_match(panel):
    panel.db.etf_upsert("VFV", name="Vanguard S&P 500", category="S&P 500")
    panel.db.etf_upsert("VAB", name="Vanguard Bonds", category="Bonds")
    panel.reload()
    panel.filter_edit.setText("bond")
    hidden = [panel.table.isRowHidden(r) for r in range(panel.table.rowCount())]
    assert hidden.count(False) == 1
    assert not panel.table.isRowHidden(
        [r for r in range(2) if _cell(panel, r, "ticker").text() == "VAB"][0])


def test_filter_matches_the_ticker_too(panel):
    _add(panel, "VFV", "XUU")
    panel.filter_edit.setText("xuu")
    assert sum(not panel.table.isRowHidden(r) for r in range(2)) == 1


def test_clearing_the_filter_shows_everything_again(panel):
    _add(panel, "VFV", "XUU")
    panel.filter_edit.setText("vfv")
    panel.filter_edit.setText("")
    assert all(not panel.table.isRowHidden(r) for r in range(2))


def test_filtering_does_not_change_the_totals(panel):
    """Hiding a row is a view change; the allocation still holds what it holds."""
    panel.db.etf_upsert("VFV", mid_risk=0.5)
    panel.db.etf_upsert("VAB", mid_risk=0.5)
    panel.reload()
    before = panel.summary.item(0, _summary_col(panel, "mid_risk")).text()
    panel.filter_edit.setText("VFV")
    assert panel.summary.item(0, _summary_col(panel, "mid_risk")).text() == before


def test_add_selected_to_watchlist_uses_the_yahoo_symbol(panel):
    panel.db.etf_upsert("VFV", yahoo="VFV.TO")
    panel.reload()
    panel.table.selectRow(0)
    panel.add_selected_to_watchlist()
    assert "VFV.TO" in panel.db.watch_symbols()


def test_add_selected_to_portfolio_adds_at_zero_shares(panel):
    panel.db.etf_upsert("VFV", yahoo="VFV.TO")
    panel.reload()
    panel.table.selectRow(0)
    panel.add_selected_to_portfolio()
    positions = panel.db.positions()
    assert [p["symbol"] for p in positions] == ["VFV.TO"]
    assert positions[0]["shares"] == 0      # the share count is yours to fill in


def test_add_to_portfolio_does_not_duplicate_a_holding(panel):
    panel.db.etf_upsert("VFV", yahoo="VFV.TO")
    panel.reload()
    panel.table.selectRow(0)
    panel.add_selected_to_portfolio()
    panel.add_selected_to_portfolio()
    assert len(panel.db.positions()) == 1
    assert "already" in panel.status.text()


def test_add_buttons_need_a_selection(panel):
    _add(panel, "VFV")
    panel.table.clearSelection()
    panel.add_selected_to_watchlist()
    assert panel.db.watch_symbols() == []
    assert "Select" in panel.status.text()


def test_export_writes_every_column_as_stored(panel, tmp_path, monkeypatch):
    import csv
    from tradelab.ui import app as appmod
    panel.db.etf_upsert("VFV", name="Vanguard S&P 500", ret_1a=0.25, mid_risk=0.2)
    panel.reload()
    out = tmp_path / "etf.csv"
    monkeypatch.setattr(appmod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    panel.export_csv()
    rows = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0][0] == "Ticker"
    body = dict(zip(rows[0], rows[1]))
    assert body["Ticker"] == "VFV"
    assert body["Ret 1Y"] == "0.25"      # the number, not "25.0%"


def test_export_cancelled_writes_nothing(panel, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    monkeypatch.setattr(appmod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    panel.export_csv()      # must not raise
    assert not list(tmp_path.glob("*.csv"))


# -- overlap warning ---------------------------------------------------------

def _canada(**extra):
    return {"pct_can": 1.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 0.0,
            "pct_alt": 0.0, "category": "Canadian equity", **extra}


def test_overlap_warning_names_the_pair(panel):
    panel.db.etf_upsert("VCN", **_canada(mid_risk=0.2))
    panel.db.etf_upsert("XIC", **_canada(mid_risk=0.1))
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    text = panel.overlap_label.text()
    assert "VCN" in text and "XIC" in text


def test_no_overlap_warning_for_different_exposures(panel):
    panel.db.etf_upsert("VCN", **_canada(mid_risk=0.5))
    panel.db.etf_upsert("VAB", category="Bonds", mid_risk=0.5, pct_can=0.0, pct_us=0.0,
                        pct_intl=0.0, pct_bond=1.0, pct_alt=0.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    assert panel.overlap_label.text() == ""


def test_overlap_warning_follows_the_selected_allocation(panel):
    panel.db.etf_upsert("VCN", **_canada(mid_risk=0.2, low_risk=0.0))
    panel.db.etf_upsert("XIC", **_canada(mid_risk=0.1, low_risk=0.0))
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk: both weighted
    assert panel.overlap_label.text()
    low = [i for i, (_l, k) in enumerate(panel.COMPOSITIONS) if k == "low_risk"][0]
    panel.composition_combo.setCurrentIndex(low)
    assert panel.overlap_label.text() == ""


# -- the analyses ------------------------------------------------------------

def test_compare_needs_at_least_two_funds(panel):
    _add(panel, "VFV")
    panel.table.selectRow(0)
    panel.compare_selected()
    assert panel._analysis_worker is None
    assert "at least two" in panel.status.text()


def test_target_vs_held_says_when_there_are_no_positions(panel):
    _add(panel, "VFV")
    panel.compare_to_portfolio()
    assert panel._analysis_worker is None
    assert "Portfolio tab" in panel.status.text()


def test_look_through_says_when_the_allocation_is_empty(panel):
    _add(panel, "VFV")           # listed, but no weight typed
    panel.show_look_through()
    assert panel._analysis_worker is None
    assert "empty" in panel.status.text()


def test_look_through_reads_the_exposures_key(panel, monkeypatch, no_network):
    """Regression: the panel read a `rows` key look_through has never
    returned, so the report was always empty."""
    shown = {}
    from tradelab.ui import app as appmod
    monkeypatch.setattr(appmod._EtfReportDialog, "__init__",
                        lambda self, parent, title, headers, rows, footnote="":
                            shown.update(rows=rows, footnote=footnote) or None)
    monkeypatch.setattr(appmod._EtfReportDialog, "exec", lambda self: None)

    panel.db.etf_upsert("XIC", yahoo="XIC.TO", mid_risk=1.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    panel.show_look_through()      # sets _lt_rows without starting the worker
    panel._on_look_through_loaded(
        {"XIC.TO": {"top_holdings": {"RY.TO": 0.6, "TD.TO": 0.2}}}, {}, "")

    companies = [row[0] for row in shown["rows"]]
    assert "RY.TO" in companies and "TD.TO" in companies
    # 20% of the fund is below what the source publishes; that is stated, not spread.
    assert "20%" in shown["footnote"]


def test_look_through_says_why_when_no_fund_publishes_holdings(panel, monkeypatch, no_network):
    from tradelab.ui import app as appmod
    monkeypatch.setattr(appmod._EtfReportDialog, "exec", lambda self: None)
    panel.db.etf_upsert("VAB", yahoo="VAB.TO", mid_risk=1.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    panel.show_look_through()
    panel._on_look_through_loaded({"VAB.TO": {}}, {}, "")
    assert "No holdings published" in panel.status.text()
    assert "VAB.TO" in panel.status.text()


def test_look_through_opens_a_fund_held_whole_inside_a_fund(panel, monkeypatch, no_network):
    """VFV.TO publishes one holding: VOO.TO at 100%. Stopping there answers
    "you own VOO.TO", which is true and useless."""
    from tradelab.ui import app as appmod
    shown = {}
    monkeypatch.setattr(appmod._EtfReportDialog, "__init__",
                        lambda self, parent, title, headers, rows, footnote="":
                            shown.update(rows=rows, footnote=footnote) or None)
    monkeypatch.setattr(appmod._EtfReportDialog, "exec", lambda self: None)

    panel.db.etf_upsert("VFV", yahoo="VFV.TO", mid_risk=1.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    panel.show_look_through()
    # First pass: a wrapper, so the panel asks for the nested fund instead of
    # rendering.
    panel._on_look_through_loaded({"VFV.TO": {"top_holdings": {"VOO.TO": 1.0}}}, {}, "")
    assert not shown
    panel._on_look_through_second_level(
        {"VOO.TO": {"top_holdings": {"AAPL": 0.4, "MSFT": 0.2}}}, {}, "")

    companies = {row[0]: row[1][2] for row in shown["rows"]}
    assert companies["AAPL"] == pytest.approx(40.0)
    # The 40% VOO.TO doesn't publish stays VOO.TO rather than being spread.
    assert companies["VOO.TO"] == pytest.approx(40.0)
    assert "second level" in shown["footnote"]


def test_look_through_falls_back_to_the_us_listing_of_a_nested_fund(panel, monkeypatch, no_network):
    """VFV.TO's holdings arrive as "VOO.TO" — the data layer appends .TO to a
    bare ticker inside a Canadian fund. That listing does not exist, so the
    second level has to ask for VOO as well or it fetches nothing for exactly
    the funds this was built for."""
    from tradelab.ui import app as appmod
    shown = {}
    monkeypatch.setattr(appmod._EtfReportDialog, "__init__",
                        lambda self, parent, title, headers, rows, footnote="":
                            shown.update(rows=rows) or None)
    monkeypatch.setattr(appmod._EtfReportDialog, "exec", lambda self: None)

    panel.db.etf_upsert("VFV", yahoo="VFV.TO", mid_risk=1.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    panel.show_look_through()
    panel._on_look_through_loaded({"VFV.TO": {"top_holdings": {"VOO.TO": 1.0}}}, {}, "")
    # Both listings were requested.
    assert set(no_network[-1][0][0]) == {"VOO.TO", "VOO"}
    # Yahoo knows VOO, not VOO.TO.
    panel._on_look_through_second_level(
        {"VOO.TO": {}, "VOO": {"top_holdings": {"AAPL": 0.4, "MSFT": 0.2}}}, {}, "")
    companies = {row[0]: row[1][2] for row in shown["rows"]}
    assert companies["AAPL"] == pytest.approx(40.0)


def test_look_through_still_renders_when_the_second_level_fails(panel, monkeypatch, no_network):
    from tradelab.ui import app as appmod
    shown = {}
    monkeypatch.setattr(appmod._EtfReportDialog, "__init__",
                        lambda self, parent, title, headers, rows, footnote="":
                            shown.update(rows=rows) or None)
    monkeypatch.setattr(appmod._EtfReportDialog, "exec", lambda self: None)
    panel.db.etf_upsert("VFV", yahoo="VFV.TO", mid_risk=1.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    panel.show_look_through()
    panel._on_look_through_loaded({"VFV.TO": {"top_holdings": {"VOO.TO": 1.0}}}, {}, "")
    panel._on_look_through_second_level(None, None, "network down")
    # Degrades to one level rather than reporting nothing at all.
    assert [row[0] for row in shown["rows"]] == ["VOO.TO"]


def test_look_through_reports_a_fetch_error(panel, no_network):
    panel.db.etf_upsert("XIC", yahoo="XIC.TO", mid_risk=1.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)      # Mid risk
    panel.show_look_through()
    panel._on_look_through_loaded(None, None, "network down")
    assert "network down" in panel.status.text()


# -- the choice filter -------------------------------------------------------

def test_choice_filter_lists_what_the_table_contains(panel):
    panel.db.etf_upsert("VFV", category="S&P 500", region="United States")
    panel.db.etf_upsert("VAB", category="Bonds", region="Bonds")
    panel.reload()
    labels = [panel.filter_choice.itemText(i) for i in range(panel.filter_choice.count())]
    assert labels[0] == "All funds"
    assert "Category: Bonds" in labels
    assert "Region: United States" in labels
    assert "Category: " not in labels        # blanks are not offered


def test_choice_filter_narrows_to_that_value(panel):
    panel.db.etf_upsert("VFV", category="S&P 500")
    panel.db.etf_upsert("VAB", category="Bonds")
    panel.reload()
    panel.filter_choice.setCurrentIndex(
        panel.filter_choice.findText("Category: Bonds"))
    visible = [_cell(panel, r, "ticker").text() for r in range(panel.table.rowCount())
               if not panel.table.isRowHidden(r)]
    assert visible == ["VAB"]


def test_choice_and_typed_filter_apply_together(panel):
    panel.db.etf_upsert("VAB", category="Bonds", name="Vanguard aggregate")
    panel.db.etf_upsert("GGOV", category="Bonds", name="Global government")
    panel.reload()
    panel.filter_choice.setCurrentIndex(
        panel.filter_choice.findText("Category: Bonds"))
    panel.filter_edit.setText("global")
    visible = [_cell(panel, r, "ticker").text() for r in range(panel.table.rowCount())
               if not panel.table.isRowHidden(r)]
    assert visible == ["GGOV"]


def test_choice_filter_survives_a_reload(panel):
    panel.db.etf_upsert("VFV", category="S&P 500")
    panel.db.etf_upsert("VAB", category="Bonds")
    panel.reload()
    panel.filter_choice.setCurrentIndex(
        panel.filter_choice.findText("Category: Bonds"))
    panel.reload()          # e.g. after a metrics refresh
    assert panel.filter_choice.currentText() == "Category: Bonds"
    visible = [r for r in range(panel.table.rowCount()) if not panel.table.isRowHidden(r)]
    assert len(visible) == 1


def test_exposure_filter_finds_a_fund_its_label_would_hide(panel):
    """XAW is labelled Global and is 60% US. Filtering on the region label
    alone would miss it, which is the point of the exposure entries."""
    panel.db.etf_upsert("XAW", region="Global", pct_us=0.6, pct_intl=0.4)
    panel.db.etf_upsert("VAB", region="Bonds", pct_us=0.0, pct_bond=1.0)
    panel.reload()
    panel.filter_choice.setCurrentIndex(
        panel.filter_choice.findText("Holds United States"))
    visible = [_cell(panel, r, "ticker").text() for r in range(panel.table.rowCount())
               if not panel.table.isRowHidden(r)]
    assert visible == ["XAW"]


def test_exposure_filter_excludes_a_zero_share(panel):
    panel.db.etf_upsert("VAB", pct_alt=0.0, pct_bond=1.0)
    panel.reload()
    # Nothing holds gold, so the entry isn't even offered.
    assert panel.filter_choice.findText("Holds Commodities") == -1
    panel.db.etf_upsert("MNT", pct_alt=1.0)
    panel.reload()
    panel.filter_choice.setCurrentIndex(
        panel.filter_choice.findText("Holds Commodities"))
    visible = [_cell(panel, r, "ticker").text() for r in range(panel.table.rowCount())
               if not panel.table.isRowHidden(r)]
    assert visible == ["MNT"]


def test_all_funds_clears_the_choice(panel):
    panel.db.etf_upsert("VFV", category="S&P 500")
    panel.db.etf_upsert("VAB", category="Bonds")
    panel.reload()
    panel.filter_choice.setCurrentIndex(
        panel.filter_choice.findText("Category: Bonds"))
    panel.filter_choice.setCurrentIndex(0)
    assert all(not panel.table.isRowHidden(r) for r in range(2))


def test_the_analyses_read_the_selected_allocation(panel):
    panel.composition_combo.setCurrentIndex(0)
    assert panel.current_weight_key() == "low_risk"
    panel.composition_combo.setCurrentIndex(1)
    assert panel.current_weight_key() == "mid_risk"


# -- the published risk rating ----------------------------------------------

def test_risk_column_shows_the_published_band(panel):
    panel.db.etf_upsert("ZLB", csa_stdev=0.09, csa_level="Low to medium", csa_months=120)
    panel.reload()
    assert _cell(panel, 0, "csa_level").text() == "Low to medium"


def test_a_fund_never_refreshed_has_no_rating(panel):
    panel.ticker_edit.setText("NEW"); panel.add_fund()
    assert _cell(panel, 0, "csa_level").text() == ""
    assert "refresh" in _cell(panel, 0, "csa_level").toolTip().lower()


def test_the_rating_tooltip_says_it_used_the_full_window(panel):
    panel.db.etf_upsert("VFV", csa_stdev=0.145, csa_level="Medium", csa_months=120)
    panel.reload()
    tip = _cell(panel, 0, "csa_level").toolTip()
    assert "14.5%" in tip and "ten-year" in tip


def test_the_rating_tooltip_warns_on_a_short_history(panel):
    """A level standing on four years is not the regulator's ten-year level,
    and the cell has to say which one you are looking at."""
    panel.db.etf_upsert("GGOV", csa_stdev=0.04, csa_level="Low", csa_months=48)
    panel.reload()
    tip = _cell(panel, 0, "csa_level").toolTip()
    assert "4.0 years" in tip
    assert "reference index" in tip


def test_filtering_by_risk_band(panel):
    panel.db.etf_upsert("ZLB", csa_level="Low")
    panel.db.etf_upsert("SMH", csa_level="High")
    panel.reload()
    index = panel.filter_choice.findText("Risk: Low")
    assert index > 0
    panel.filter_choice.setCurrentIndex(index)
    visible = [_cell(panel, r, "ticker").text() for r in range(panel.table.rowCount())
               if not panel.table.isRowHidden(r)]
    assert visible == ["ZLB"]


# -- language & reference notes ---------------------------------------------

FRENCH_LETTERS = set("àâäçéèêëîïôöùûüÀÂÄÇÉÈÊËÎÏÔÖÙÛÜ")


def test_the_tab_reads_in_english(panel):
    """The rest of the app is in English; this tab was built from a French
    workbook and drifted. Guard every string it owns."""
    from tradelab.core.etf_metrics import COMPOSITION_ROWS
    texts = [label for _key, label, _editable in panel.COLUMNS]
    texts += [label for label, _key in panel.COMPOSITIONS]
    texts += [label for label, _column, _kind in COMPOSITION_ROWS]
    texts += [panel.EQUIVALENTS, panel.status.text(),
              panel.ticker_edit.placeholderText(), panel.yahoo_edit.placeholderText(),
              panel.refresh_btn.text(), panel.stop_btn.text()]
    panel._on_refresh_finished(1, 1, False)
    texts.append(panel.status.text())
    offenders = [t for t in texts if FRENCH_LETTERS & set(t)]
    assert not offenders, f"French text left in the ETF Screener: {offenders}"


def test_the_cad_us_equivalents_note_is_shown(panel):
    from PySide6.QtWidgets import QLabel
    rendered = [label.text() for label in panel.findChildren(QLabel)]
    assert any("XUU" in t and "VTI" in t for t in rendered)
    assert any("DRAM" in t for t in rendered)      # the no-CAD-equivalent list
    assert any("TEC" in t for t in rendered)       # and the VGT caveat


# -- frozen ticker column, charting, and the wrapping toolbar ---------------

def test_the_ticker_column_is_pinned_over_the_table(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    frozen = panel.frozen
    assert frozen.model() is panel.table.model()          # one model, no syncing
    assert not frozen.isColumnHidden(0)
    assert all(frozen.isColumnHidden(c) for c in range(1, panel.table.columnCount()))
    assert frozen.width() == panel.table.columnWidth(0)


def test_the_pinned_column_scrolls_with_the_table(panel):
    """Offscreen the views are too short to actually scroll, so give both
    scrollbars a range and check the two stay in step."""
    for ticker in ("VFV", "XUU", "VAB", "ZLB", "VGT"):
        panel.ticker_edit.setText(ticker); panel.add_fund()
    table_bar = panel.table.verticalScrollBar()
    frozen_bar = panel.frozen.verticalScrollBar()
    table_bar.setRange(0, 10); frozen_bar.setRange(0, 10)

    table_bar.setValue(3)
    assert frozen_bar.value() == 3          # rows and pinned column agree
    frozen_bar.setValue(1)
    assert table_bar.value() == 1           # and the other way round


def test_double_clicking_a_ticker_charts_its_yahoo_symbol(panel, monkeypatch):
    from tradelab.ui import app as appmod
    started = {}

    class _FakeWorker:
        def __init__(self, symbol, period, interval):
            started["symbol"] = symbol
        done = None
        def __getattr__(self, name):           # .done.connect(...) / .start()
            return lambda *a, **k: None

    monkeypatch.setattr(appmod, "_HistoryWorker", _FakeWorker)
    panel.chart = object()
    panel.cfg = appmod.ScannerConfig()
    panel.db.etf_upsert("VFV", yahoo="VFV.TO")
    panel.reload()
    panel.table.cellDoubleClicked.emit(0, 0)
    # VFV alone has no prices on Yahoo; VFV.TO does.
    assert started["symbol"] == "VFV.TO"


def test_double_clicking_an_editable_cell_does_not_chart(panel, monkeypatch):
    from tradelab.ui import app as appmod
    called = []
    monkeypatch.setattr(appmod, "_HistoryWorker",
                        lambda *a, **k: called.append(a) or pytest.fail("charted"))
    panel.chart = object()
    panel.cfg = appmod.ScannerConfig()
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    notes_col = _col(panel, "notes")
    panel.table.cellDoubleClicked.emit(0, notes_col)
    assert not called


def test_charting_is_inert_without_a_chart_workspace(panel):
    panel.ticker_edit.setText("VFV"); panel.add_fund()
    panel.table.cellDoubleClicked.emit(0, 0)      # chart is None in these tests
    assert panel._chart_worker is None


def test_the_toolbar_wraps_instead_of_clipping_when_narrow(panel):
    """Dragging the chart splitter right used to cut Refresh and Stop off the
    end of a fixed row."""
    bar = panel.refresh_btn.parentWidget()
    wide = bar.layout().heightForWidth(1200)
    narrow = bar.layout().heightForWidth(320)
    assert narrow > wide          # it grew a row rather than losing a button
    assert panel.stop_btn.parentWidget() is bar


def test_shutdown_is_safe_with_nothing_running(panel):
    panel.shutdown()              # must not raise


def test_a_running_worker_is_held_until_it_finishes(panel):
    """The look-through hands off to a second worker from inside the first
    one's signal handler. Without a reference held elsewhere, that assignment
    frees a QThread still inside run() and Qt takes the process down with no
    traceback."""
    from PySide6.QtCore import QThread

    class _Slow(QThread):
        def run(self):
            self.msleep(150)

    first, second = _Slow(), _Slow()
    panel._track(first).start()
    panel._track(second).start()            # the hand-off
    assert first in panel._workers          # still referenced while running
    assert panel._analysis_worker is second
    panel.shutdown()                        # joins both
    assert not any(w.isRunning() for w in (first, second))


def test_a_finished_worker_is_let_go(panel):
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    class _Quick(QThread):
        def run(self):
            return

    worker = _Quick()
    panel._track(worker).start()
    worker.wait(2000)
    QApplication.processEvents()            # deliver finished()
    assert worker not in panel._workers


def test_worker_carries_the_yahoo_symbol_not_the_ticker(panel):
    from tradelab.ui.app import EtfMetricsWorker
    panel.db.etf_upsert("VFV", yahoo="VFV.TO")
    rows = [(f["ticker"], f["yahoo"] or f["ticker"]) for f in panel.db.etf_list()]
    worker = EtfMetricsWorker(rows)
    assert worker.rows == [("VFV", "VFV.TO")]


# -- the totals row under the table ------------------------------------------

def _total_cell(panel, key):
    return panel.totals.item(0, _col(panel, key))


def test_each_allocation_column_is_totalled_beneath_it(panel):
    panel.db.etf_upsert("VFV", mid_risk=0.6, low_risk=0.25)
    panel.db.etf_upsert("VAB", mid_risk=0.4, low_risk=0.75)
    panel.reload()
    assert _total_cell(panel, "mid_risk").text() == "100.0%"
    assert _total_cell(panel, "low_risk").text() == "100.0%"
    assert panel.totals.item(0, 0).text() == "Total"


def test_a_column_that_is_not_an_allocation_has_no_total(panel):
    panel.db.etf_upsert("VFV", pct_us=1.0, mer=0.0009, mid_risk=1.0)
    panel.reload()
    for key in ("pct_us", "mer", "volatility", "notes"):
        assert _total_cell(panel, key) is None, key


def test_the_total_updates_when_a_weight_is_edited(panel):
    panel.db.etf_upsert("VFV")
    panel.reload()
    _cell(panel, 0, "high_risk").setText("40")
    assert _total_cell(panel, "high_risk").text() == "40.0%"


def test_an_incomplete_total_is_flagged_by_colour(panel):
    from tradelab.ui import theme
    panel.db.etf_upsert("VFV", mid_risk=0.6, low_risk=1.0)
    panel.reload()
    assert _total_cell(panel, "mid_risk").foreground().color().name() == theme.NEUTRAL
    assert _total_cell(panel, "low_risk").foreground().color().name() == theme.UP


def test_the_totals_row_tracks_the_table_columns(panel):
    panel.db.etf_upsert("VFV", mid_risk=1.0)
    panel.reload()
    column = _col(panel, "mid_risk")
    assert panel.totals.columnWidth(column) == panel.table.columnWidth(column)
    panel.table.setColumnWidth(column, 140)
    assert panel.totals.columnWidth(column) == 140


def test_the_totals_row_is_not_a_fund(panel):
    """It lives under the table, not as a last row inside it — a total row in
    the table would sort with the funds and vanish under a filter."""
    panel.db.etf_upsert("VFV", mid_risk=1.0)
    panel.reload()
    assert panel.table.rowCount() == 1
    panel.filter_edit.setText("zzz")            # matches nothing
    assert _total_cell(panel, "mid_risk").text() == "100.0%"


# -- the pinned column stays in step -----------------------------------------

def test_both_views_scroll_in_the_same_unit(panel):
    """Forwarding a scrollbar value between two views only works if they
    count the same thing — mixing per-item and per-pixel parked the pinned
    column half a row out of step."""
    from PySide6.QtWidgets import QAbstractItemView
    assert panel.table.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert panel.frozen.verticalScrollMode() == QAbstractItemView.ScrollPerPixel


def test_the_pinned_column_uses_the_tables_row_height(panel):
    panel.table.verticalHeader().setDefaultSectionSize(37)
    panel.db.etf_upsert("VFV")
    panel.reload()
    assert panel.frozen.verticalHeader().defaultSectionSize() == 37
    assert panel.frozen.rowHeight(0) == panel.table.rowHeight(0)


# -- full screen for the table ------------------------------------------------

def test_the_button_asks_the_window_and_the_label_flips(panel):
    calls = []
    panel.on_toggle_fullscreen = lambda: calls.append(1)
    assert panel.fullscreen_btn.text() == panel.FULLSCREEN_ENTER
    panel.fullscreen_btn.click()
    assert calls == [1]
    panel.set_fullscreen_label(True)
    assert panel.fullscreen_btn.text() == panel.FULLSCREEN_EXIT
    panel.set_fullscreen_label(False)
    assert panel.fullscreen_btn.text() == panel.FULLSCREEN_ENTER


def test_the_button_is_inert_without_a_window(panel):
    panel.fullscreen_btn.click()        # on_toggle_fullscreen is None here


# -- building an allocation from a rule --------------------------------------

def _rated(panel):
    panel.db.etf_upsert("VAB", csa_level="Low", volatility=0.06, mer=0.0009,
                        category="Bonds", pct_bond=1.0, pct_can=0.0, pct_us=0.0,
                        pct_intl=0.0, pct_alt=0.0)
    panel.db.etf_upsert("VCN", csa_level="Medium", volatility=0.15, mer=0.0005,
                        category="Canadian equity", pct_can=1.0, pct_us=0.0,
                        pct_intl=0.0, pct_bond=0.0, pct_alt=0.0)
    panel.db.etf_upsert("SMH", csa_level="High", volatility=0.33, mer=0.0035,
                        category="US semis", pct_us=1.0, pct_can=0.0,
                        pct_intl=0.0, pct_bond=0.0, pct_alt=0.0)
    panel.reload()


def _dialog(panel, key="low_risk"):
    from tradelab.ui.app import _BuildAllocationDialog
    return _BuildAllocationDialog(panel, panel.COMPOSITIONS, key, panel.db.etf_list())


def test_the_form_pre_ticks_the_bands_named_like_the_column(panel):
    """A naming correspondence, not a view on what you should hold."""
    _rated(panel)
    assert _dialog(panel, "low_risk").selected_bands() == {"Low", "Low to medium"}
    assert _dialog(panel, "high_risk").selected_bands() == {"Medium to high", "High"}


def test_the_form_previews_what_it_would_write(panel):
    _rated(panel)
    dialog = _dialog(panel, "low_risk")
    assert "VAB" in dialog.preview.text()
    assert "SMH" not in dialog.preview.text()          # rated High, not ticked


def test_the_form_refuses_to_fill_when_nothing_matches(panel):
    _rated(panel)
    dialog = _dialog(panel, "low_risk")
    for box in dialog.bands.values():
        box.setChecked(False)
    assert dialog.apply_btn.isEnabled() is False
    assert "No fund matches" in dialog.preview.text()


def test_the_rule_writes_the_column_and_the_total_reaches_100(panel, monkeypatch):
    from tradelab.ui import app as appmod
    _rated(panel)
    monkeypatch.setattr(appmod.QDialog, "exec", lambda self: appmod.QDialog.Accepted)
    panel.composition_combo.setCurrentIndex(0)          # Low risk
    panel.build_allocation()
    assert panel.db.etf_get("VAB")["low_risk"] == pytest.approx(1.0)
    assert _total_cell(panel, "low_risk").text() == "100.0%"


def test_the_rule_clears_a_fund_it_left_out(panel, monkeypatch):
    """A weight left from an earlier run must not survive into a mix the rule
    no longer puts that fund in."""
    from tradelab.ui import app as appmod
    _rated(panel)
    panel.db.etf_upsert("SMH", low_risk=0.5)            # stale weight
    monkeypatch.setattr(appmod.QDialog, "exec", lambda self: appmod.QDialog.Accepted)
    panel.composition_combo.setCurrentIndex(0)
    panel.build_allocation()
    assert panel.db.etf_get("SMH")["low_risk"] is None


def test_the_rule_leaves_the_other_allocations_alone(panel, monkeypatch):
    from tradelab.ui import app as appmod
    _rated(panel)
    panel.db.etf_upsert("VCN", high_risk=0.42)
    monkeypatch.setattr(appmod.QDialog, "exec", lambda self: appmod.QDialog.Accepted)
    panel.composition_combo.setCurrentIndex(0)
    panel.build_allocation()
    assert panel.db.etf_get("VCN")["high_risk"] == pytest.approx(0.42)


def test_cancelling_writes_nothing(panel, monkeypatch):
    from tradelab.ui import app as appmod
    _rated(panel)
    monkeypatch.setattr(appmod.QDialog, "exec", lambda self: appmod.QDialog.Rejected)
    panel.build_allocation()
    assert panel.db.etf_get("VAB")["low_risk"] is None


def test_building_with_no_funds_says_so(panel):
    panel.build_allocation()
    assert "Add some funds" in panel.status.text()


def test_the_form_explains_an_impossible_cap(panel):
    _rated(panel)
    dialog = _dialog(panel, "low_risk")
    for label, box in dialog.bands.items():
        box.setChecked(label in {"Low", "Medium"})
    dialog.cap.setValue(20)                      # 3 funds x 20% = 60%
    assert "Can't do that" in dialog.preview.text()
    assert dialog.apply_btn.isEnabled() is False


def test_the_form_remembers_the_last_rule(panel):
    from tradelab.ui.app import _BuildAllocationDialog
    _BuildAllocationDialog.LAST = {}
    _rated(panel)
    first = _dialog(panel, "low_risk")
    first.method.setCurrentIndex(1)              # inverse volatility
    first.cap.setValue(45)
    first.accept()

    second = _dialog(panel, "low_risk")
    assert second.method.currentData() == "inverse_vol"
    assert second.cap.value() == 45
    _BuildAllocationDialog.LAST = {}


def test_a_cancelled_form_does_not_change_what_is_remembered(panel):
    from tradelab.ui.app import _BuildAllocationDialog
    _BuildAllocationDialog.LAST = {}
    _rated(panel)
    dialog = _dialog(panel, "low_risk")
    dialog.cap.setValue(12)
    dialog.reject()
    assert _dialog(panel, "low_risk").cap.value() == 100.0


# -- what each fund contains --------------------------------------------------

def test_fund_holdings_lists_every_fund_and_its_contents(panel, monkeypatch, no_network):
    from tradelab.ui import app as appmod
    shown = {}
    monkeypatch.setattr(appmod._EtfReportDialog, "__init__",
                        lambda self, parent, title, headers, rows, footnote="":
                            shown.update(rows=rows, headers=headers) or None)
    monkeypatch.setattr(appmod._EtfReportDialog, "exec", lambda self: None)

    panel.db.etf_upsert("XIC", yahoo="XIC.TO")
    panel.db.etf_upsert("VAB", yahoo="VAB.TO")
    panel.reload()
    panel.show_fund_holdings()
    panel._on_look_through_loaded(
        {"XIC.TO": {"top_holdings": {"RY.TO": 0.6, "TD.TO": 0.2}}, "VAB.TO": {}}, {}, "")

    assert shown["headers"] == ["Fund", "Holding", "% of the fund"]
    funds = [row[0] for row in shown["rows"]]
    assert funds.count("VAB") == 1 and funds.count("XIC") == 3   # 2 holdings + remainder
    assert "1 of 2 funds publish holdings" in panel.status.text()


def test_fund_holdings_shows_the_unpublished_share(panel, monkeypatch, no_network):
    from tradelab.ui import app as appmod
    shown = {}
    monkeypatch.setattr(appmod._EtfReportDialog, "__init__",
                        lambda self, parent, title, headers, rows, footnote="":
                            shown.update(rows=rows) or None)
    monkeypatch.setattr(appmod._EtfReportDialog, "exec", lambda self: None)
    panel.db.etf_upsert("XIC", yahoo="XIC.TO")
    panel.reload()
    panel.show_fund_holdings()
    panel._on_look_through_loaded({"XIC.TO": {"top_holdings": {"RY.TO": 0.6}}}, {}, "")
    labels = [row[1][0] for row in shown["rows"]]
    assert "— not published —" in labels
    assert "40.0%" in [row[2][0] for row in shown["rows"]]


def test_fund_holdings_needs_funds(panel, no_network):
    panel.show_fund_holdings()
    assert "Add some funds" in panel.status.text()


def test_the_two_views_share_one_fetch_but_render_differently(panel, no_network):
    panel.db.etf_upsert("XIC", yahoo="XIC.TO", mid_risk=1.0)
    panel.reload()
    panel.composition_combo.setCurrentIndex(1)
    panel.show_look_through()
    assert panel._lt_render == panel._render_look_through
    panel.show_fund_holdings()
    assert panel._lt_render == panel._render_fund_holdings
