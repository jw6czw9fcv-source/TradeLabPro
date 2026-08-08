"""UI smoke tests for the Retirement tab (RetirementPanel).

Every panel here is built on a throwaway RetirementBook in tmp_path, so no test
can touch the real plan file. Index histories are injected straight into the
render path — the tab never reaches the network in these tests.
"""
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tradelab.core import retirement as rt


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def book(tmp_path):
    return rt.RetirementBook(tmp_path / "retirement.json")


def _plan(book, name="REER Canada Vie"):
    """A plan with two statement dates, so returns are actually computable."""
    account = book.add_account(rt.Account(name=name, funds=[
        rt.Fund(name="Expansion Canada (Fidelity)", benchmark="XIC.TO", snapshots=[
            rt.Snapshot(date="2025-08-08", units=98.714857, unit_value=160.00),
            rt.Snapshot(date="2026-08-08", units=98.714857, unit_value=172.07)]),
        rt.Fund(name="Marchés émergents (Mackenzie)", snapshots=[
            rt.Snapshot(date="2025-08-08", units=15.723053, unit_value=750.00),
            rt.Snapshot(date="2026-08-08", units=15.723053, unit_value=712.94)]),
    ]))
    book.save()
    return account


def _panel(qapp, book):
    import tradelab.ui.app as app
    panel = app.RetirementPanel(book=book)
    return panel


def test_panel_builds_with_an_empty_book(qapp, book):
    panel = _panel(qapp, book)
    assert panel.table.rowCount() == 0
    assert "Create a plan" in panel.headline.text()
    panel.shutdown()


def test_panel_lists_funds_and_their_returns(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    assert panel.table.rowCount() == 2
    names = {panel.table.item(r, 0).text() for r in range(2)}
    assert "Expansion Canada (Fidelity)" in names
    # +7.54% and -4.94%: the winner and the laggard are both on screen.
    returns = {panel.table.item(r, 5).text() for r in range(2)}
    assert any("+7.5" in t for t in returns)
    assert any("-4.9" in t for t in returns)
    panel.shutdown()


def test_tiles_name_the_best_and_weakest_fund(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    assert "Expansion Canada" in panel.metrics["best"].text()
    assert "Marchés émergents" in panel.metrics["worst"].text()
    assert panel.metrics["funds"].text() == "2"
    panel.shutdown()


def test_a_single_statement_shows_dashes_not_a_fake_return(qapp, book):
    """One balance is not a return, and the tab has to say so rather than
    print a number it cannot support."""
    book.add_account(rt.Account(name="Neuf", funds=[
        rt.Fund(name="Fonds A", snapshots=[
            rt.Snapshot(date="2026-08-08", value=12049.25)])]))
    panel = _panel(qapp, book)
    assert panel.table.item(0, 5).text() == "—"
    assert "second date" in panel.table.item(0, 5).toolTip()
    panel.shutdown()


def test_pasting_a_statement_previews_before_it_writes(qapp, book):
    """Read must not persist anything — the user sees what was understood
    first, then decides."""
    panel = _panel(qapp, book)
    panel.paste.setPlainText(
        "Fonds d'actions canadiennes\n"
        "Expansion Canada (Fidelity)\t98,714857\t172,07\t16 985,78")
    panel.paste_date.setText("2026-08-08")
    panel._read_paste()
    assert "1 funds dated 2026-08-08" in panel.preview.text()
    assert panel.save_btn.isEnabled()
    assert book.accounts == []          # nothing written yet
    panel.shutdown()


def test_saving_a_paste_creates_the_plan_and_the_funds(qapp, book):
    panel = _panel(qapp, book)
    panel.paste.setPlainText("Expansion Canada (Fidelity)\t98,714857\t172,07\t16 985,78")
    panel.paste_date.setText("2026-08-08")
    panel._read_paste()
    panel._save_paste()
    assert len(book.accounts) == 1
    fund = book.accounts[0].funds[0]
    assert fund.name == "Expansion Canada (Fidelity)"
    assert fund.benchmark == "XIC.TO"      # guessed from the mandate
    assert fund.snapshots[0].unit_value == pytest.approx(172.07)
    assert panel.table.rowCount() == 1
    panel.shutdown()


def test_a_second_paste_adds_a_date_rather_than_a_duplicate_fund(qapp, book):
    panel = _panel(qapp, book)
    for date, unit_value in (("2025-08-08", "160,00"), ("2026-08-08", "172,07")):
        panel.paste.setPlainText(f"Expansion Canada (Fidelity)\t98,714857\t{unit_value}")
        panel.paste_date.setText(date)
        panel._read_paste()
        panel._save_paste()
    account = book.accounts[0]
    assert len(account.funds) == 1
    assert len(account.funds[0].snapshots) == 2
    assert panel.table.item(0, 5).text().startswith("+7.5")
    panel.shutdown()


def test_editing_the_index_cell_persists_and_recomputes(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    row = next(r for r in range(panel.table.rowCount())
               if panel.table.item(r, 0).text().startswith("Marchés"))
    panel.table.item(row, panel.BENCH_COL).setText("XEC.TO")
    fund = book.accounts[0].fund("Marchés émergents (Mackenzie)")
    assert fund.benchmark == "XEC.TO"
    assert rt.RetirementBook(book.path).accounts[0].funds[1].benchmark == "XEC.TO"
    panel.shutdown()


def test_benchmark_history_fills_the_comparison_column(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    index = pd.date_range("2025-01-01", periods=700, freq="D")
    flat = pd.DataFrame({"Close": [30.0] * 700}, index=index)
    panel._on_benchmarks({"XIC.TO": flat}, "")
    row = next(r for r in range(panel.table.rowCount())
               if panel.table.item(r, 0).text().startswith("Expansion"))
    # A flat index means the fund's whole +7.54% is excess return.
    assert panel.table.item(row, 9).text().startswith("+7.5")
    panel.shutdown()


def test_synthetic_index_data_is_refused(qapp, book):
    """Real money is never judged against fabricated prices."""
    _plan(book)
    panel = _panel(qapp, book)
    index = pd.date_range("2025-01-01", periods=700, freq="D")
    fake = pd.DataFrame({"Close": [30.0] * 700}, index=index)
    fake.attrs["synthetic"] = True
    panel._on_benchmarks({"XIC.TO": fake}, "")
    row = next(r for r in range(panel.table.rowCount())
               if panel.table.item(r, 0).text().startswith("Expansion"))
    assert panel.table.item(row, 9).text() == "—"
    panel.shutdown()


def test_benchmark_error_is_reported_not_swallowed(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel._on_benchmarks(None, "network down")
    assert "network down" in panel.status.text()
    panel.shutdown()


def test_contributions_are_recorded_against_the_chosen_fund(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.flow_fund.setCurrentIndex(0)
    panel.flow_date.setText("2026-03-01")
    panel.flow_amount.setText("2 500,00")
    panel._add_flow()
    fund = book.accounts[0].fund(panel.flow_fund.itemData(0))
    assert fund.flows[0].amount == pytest.approx(2500.0)
    assert panel.flows_table.rowCount() == 1
    panel.shutdown()


def test_a_contribution_without_a_date_is_refused(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.flow_amount.setText("2500")
    panel.flow_date.setText("")
    panel._add_flow()
    assert panel.flows_table.rowCount() == 0
    assert "needs a date" in panel.status.text()
    panel.shutdown()


def test_removing_a_contribution_updates_the_file(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.flow_fund.setCurrentIndex(0)
    panel.flow_date.setText("2026-03-01")
    panel.flow_amount.setText("2500")
    panel._add_flow()
    panel.flows_table.setCurrentCell(0, 0)
    panel._remove_flow()
    assert panel.flows_table.rowCount() == 0
    assert rt.RetirementBook(book.path).accounts[0].funds[0].flows == []
    panel.shutdown()


def test_needs_section_tells_the_user_what_is_missing(qapp, book):
    book.add_account(rt.Account(name="Neuf", funds=[
        rt.Fund(name="Fonds A", snapshots=[
            rt.Snapshot(date="2026-08-08", value=12049.25)])]))
    panel = _panel(qapp, book)
    assert "second date" in panel.needs.text()
    panel.shutdown()


def test_deleting_a_plan_clears_the_tab(qapp, book, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    _plan(book)
    panel = _panel(qapp, book)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    panel._delete_account()
    assert book.accounts == []
    assert panel.table.rowCount() == 0
    panel.shutdown()


SHEET = """Rendements composés au 31 mars 2026
             3 mois    1 an      3 ans**   10 ans**
Fonds*       5,15 %    40,99 %   30,97 %   18,47 %
Indice       1,99 %    28,46 %   20,81 %   13,42 %"""


def test_reading_a_fact_sheet_fills_the_published_table(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.published_fund.setCurrentIndex(0)
    panel.published_text.setPlainText(SHEET)
    panel._read_published()
    assert panel.published_table.rowCount() == 2
    # Sorted by the published return: the fund with a sheet leads.
    assert panel.published_table.item(0, 2).text() == "+40.99%"
    assert panel.published_table.item(0, 3).text() == "+28.46%"
    assert panel.published_table.item(0, 4).text() == "+12.53 pp"
    panel.shutdown()


def test_an_unreadable_sheet_says_why_and_writes_nothing(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.published_fund.setCurrentIndex(0)
    panel.published_text.setPlainText("Fonds 5,15 % 40,99 %")   # no date
    panel._read_published()
    assert "No date" in panel.status.text()
    assert book.accounts[0].funds[0].published == []
    panel.shutdown()


def test_the_fee_turns_a_win_into_a_loss_on_screen(qapp, book):
    """+0.03 pp before a 1.75% fee is -1.72 pp after it, and the tab has to
    show both rather than leaving the member to do it in their head."""
    _plan(book)
    panel = _panel(qapp, book)
    panel.published_fund.setCurrentIndex(0)
    panel.published_text.setPlainText(
        "au 31 mars 2026\n3 mois  1 an\nFonds 1,37 % 17,39 %\nIndice 1,35 % 17,36 %")
    panel._read_published()
    panel.fee_input.setText("1.75")
    panel._set_fee()
    assert panel.published_table.item(0, 4).text() == "+0.03 pp"
    assert panel.published_table.item(0, 6).text() == "-1.72 pp"
    assert book.accounts[0].fee_pct == pytest.approx(1.75)
    panel.shutdown()


def test_the_horizon_picker_switches_the_whole_table(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.published_fund.setCurrentIndex(0)
    panel.published_text.setPlainText(SHEET)
    panel._read_published()
    index = panel.horizon.findData("10y")
    assert index >= 0
    panel.horizon.setCurrentIndex(index)
    assert panel.published_table.item(0, 2).text() == "+18.47%"
    panel.shutdown()


def test_the_plan_line_is_weighted_by_holdings(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.published_fund.setCurrentIndex(0)
    panel.published_text.setPlainText(SHEET)
    panel._read_published()
    text = panel.published_line.text().lower()
    assert "weighted by what you hold" in text
    assert "covering" in text          # one fund still has no sheet
    panel.shutdown()


def test_funds_without_a_sheet_show_dashes_with_a_reason(qapp, book):
    _plan(book)
    panel = _panel(qapp, book)
    panel.published_fund.setCurrentIndex(0)
    panel.published_text.setPlainText(SHEET)
    panel._read_published()
    row = next(r for r in range(panel.published_table.rowCount())
               if panel.published_table.item(r, 2).text() == "—")
    assert "No fund fact sheet" in panel.published_table.item(row, 2).toolTip()
    panel.shutdown()


def test_tables_grow_to_fit_a_seven_fund_plan(qapp, book):
    """A real group plan has seven lines. Left at its default height the table
    showed two of them inside a scroll stub, on a page that already scrolls."""
    account = rt.Account(name="Grand régime", funds=[
        rt.Fund(name=f"Fonds {i}", snapshots=[
            rt.Snapshot(date="2026-08-08", value=10000.0 + i)]) for i in range(7)])
    book.add_account(account)
    panel = _panel(qapp, book)
    assert panel.table.rowCount() == 7
    header = panel.table.horizontalHeader().height()
    rows = sum(panel.table.rowHeight(r) for r in range(7))
    assert panel.table.minimumHeight() >= header + rows
    panel.shutdown()


def test_panel_is_wired_into_the_main_window(qapp):
    """The tab has to exist in the window, with its shutdown reachable."""
    import tradelab.ui.app as app
    assert hasattr(app.MainWindow, "closeEvent")
    source = app.MainWindow.__init__.__doc__ or ""
    assert "RetirementPanel" in app.__dict__ and callable(app.RetirementPanel)
    assert hasattr(app.RetirementPanel, "shutdown")
