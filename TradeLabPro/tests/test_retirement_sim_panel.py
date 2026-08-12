"""Headless tests for the Retirement Sim panel.

No network: the projection is pure arithmetic, so these run the real thing
rather than a double.
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
    from tradelab.ui.app import RetirementSimPanel
    return RetirementSimPanel(Database(path=tmp_path / "sim.db"))


def _fill(panel, people, accounts, incomes=()):
    for key, rows in (("people", people), ("accounts", accounts), ("incomes", incomes)):
        table = panel.tables[key]
        table.setRowCount(0)
        for row in rows:
            r = table.rowCount()
            table.insertRow(r)
            for c, value in enumerate(row):
                from tradelab.ui.app import table_item
                table.setItem(r, c, table_item("" if value is None else value))


# -- the inputs --------------------------------------------------------------

def test_a_new_panel_starts_empty_and_says_so(panel):
    assert panel.tables["people"].rowCount() == 0
    assert "Fill in" in panel.status.text()


def test_the_default_horizon_is_95(panel):
    """The age the person named, not one the app chose."""
    assert panel.until_age.value() == 95


def test_inputs_survive_a_save_and_reload(panel, qapp, tmp_path):
    from tradelab.ui.app import RetirementSimPanel
    _fill(panel, [["Pierre", 64]], [["REER", "registered", 164000, "Pierre"]])
    panel.spending.setValue(50_000)
    panel.save()
    again = RetirementSimPanel(Database(path=tmp_path / "sim.db"))
    assert again.tables["accounts"].item(0, 0).text() == "REER"
    assert again.tables["accounts"].item(0, 2).text() in ("164000.0", "164000")
    assert again.spending.value() == 50_000


def test_a_balance_typed_with_a_dollar_sign_and_commas_is_read(panel):
    _fill(panel, [["Pierre", 64]], [["REER", "registered", "$164,000", "Pierre"]])
    assert panel._read("accounts")[0]["balance"] == pytest.approx(164_000)


def test_a_blank_end_age_means_for_life(panel):
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 1000, "Pierre"]],
          [["RRQ", "Pierre", 13128, 65, ""]])
    assert panel._read("incomes")[0]["ends_at_age"] is None


# -- the projection ----------------------------------------------------------

def test_running_with_nothing_says_what_is_missing(panel):
    panel.run()
    assert "at least one person" in panel.status.text()
    assert panel.results.rowCount() == 0


def test_the_horizon_reaches_the_age_you_asked_for(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 500_000, "Pierre"]])
    panel.until_age.setValue(95)
    panel.spending.setValue(0)
    panel.run()
    assert panel.rows[-1]["ages"]["Pierre"] == 95


def test_a_plan_that_holds_says_what_is_left(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 1_000_000, "Pierre"]])
    panel.spending.setValue(10_000)
    panel.real_return.setValue(3.0)
    panel.run()
    assert "lasts to age" in panel.status.text()


def test_a_plan_that_fails_names_the_age(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 20_000, "Pierre"]])
    panel.spending.setValue(50_000)
    panel.real_return.setValue(0.0)
    panel.run()
    assert "Runs short at age" in panel.status.text()
    # And the years after the failure are still there to read.
    assert panel.results.rowCount() > 2


def test_the_forced_rrif_minimum_appears_in_the_results(panel):
    _fill(panel, [["Pierre", 71]], [["REER", "registered", 100_000, "Pierre"]])
    panel.spending.setValue(0)
    panel.real_return.setValue(0.0)
    panel.run()
    assert panel.rows[0]["forced_withdrawal"] == pytest.approx(5_280)


# -- tax, and what can actually be split -------------------------------------

def test_tax_is_the_real_model_not_a_flat_rate(panel):
    """A household on a modest income pays far less than any flat rate, and
    getting that wrong is worth years of projection."""
    _fill(panel, [["Pierre", 70]], [["CELI", "tfsa", 100_000, "Pierre"]],
          [["RRQ", "Pierre", 13_128, 65, ""]])
    panel.spending.setValue(0)
    panel.run()
    tax = panel.rows[0]["tax"]
    assert 0 <= tax < 13_128 * 0.15         # nothing like a flat 20%


def test_splitting_only_moves_pension_income(panel):
    """A wage cannot be split. Treating the household as one pot and halving
    it - which an earlier draft did - made the bill far too small."""
    _fill(panel, [["Pierre", 70], ["Conjointe", 70]],
          [["CELI", "tfsa", 10_000, "Pierre"]],
          [["Travail", "Pierre", 60_000, 0, ""]])
    panel.spending.setValue(0)
    panel.splitting.setValue(0)
    panel.run()
    without = panel.rows[0]["tax"]
    panel.splitting.setValue(50)
    panel.run()
    # No pension income exists, so the split changes nothing at all.
    assert panel.rows[0]["tax"] == pytest.approx(without)


def test_splitting_a_rrif_withdrawal_lowers_the_bill(panel):
    _fill(panel, [["Pierre", 75], ["Conjointe", 75]],
          [["REER", "registered", 800_000, "Pierre"]])
    panel.spending.setValue(0)
    panel.splitting.setValue(0)
    panel.run()
    without = panel.rows[0]["tax"]
    panel.splitting.setValue(50)
    panel.run()
    assert panel.rows[0]["tax"] < without


def test_the_results_show_calendar_years(panel):
    from datetime import date
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 500_000, "Pierre"]])
    panel.spending.setValue(0)
    panel.run()
    assert panel.results.item(0, 0).text() == str(date.today().year)
    assert panel.results.item(1, 0).text() == str(date.today().year + 1)


# -- many paths --------------------------------------------------------------

def test_many_paths_reports_a_share_not_a_certainty(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 2_000_000, "Pierre"]])
    panel.spending.setValue(20_000)
    panel.until_age.setValue(80)
    panel.paths.setValue(60)
    panel.run()                       # for the ages column
    panel.run_paths()
    text = panel.status.text()
    assert "paths" in text
    assert "not a probability" in text          # the caveat travels with the number


def test_many_paths_shows_a_band_not_a_line(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 500_000, "Pierre"]])
    panel.spending.setValue(30_000)
    panel.until_age.setValue(85)
    panel.paths.setValue(60)
    panel.volatility.setValue(12)
    panel.run()
    panel.run_paths()
    headers = [panel.results.horizontalHeaderItem(c).text()
               for c in range(panel.results.columnCount())]
    assert headers == ["Year", "Ages", "Worst 10%", "Median", "Best 10%", "Still solvent"]
    # And the band really is a band.
    worst = float(panel.results.item(5, 2).text().replace(",", ""))
    best = float(panel.results.item(5, 4).text().replace(",", ""))
    assert worst < best


def test_switching_back_to_one_path_restores_the_detailed_columns(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 500_000, "Pierre"]])
    panel.spending.setValue(20_000)
    panel.paths.setValue(60)
    panel.run()
    panel.run_paths()
    panel.run()
    headers = [panel.results.horizontalHeaderItem(c).text()
               for c in range(panel.results.columnCount())]
    assert "Tax" in headers and "RRIF minimum" in headers


def test_many_paths_needs_inputs_too(panel):
    panel.run_paths()
    assert "at least one person" in panel.status.text()


def test_the_volatility_widens_the_band(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 500_000, "Pierre"]])
    panel.spending.setValue(20_000)
    panel.until_age.setValue(85)
    panel.paths.setValue(80)
    panel.run()

    panel.volatility.setValue(2)
    panel.run_paths()
    narrow = (float(panel.results.item(10, 4).text().replace(",", ""))
              - float(panel.results.item(10, 2).text().replace(",", "")))
    panel.volatility.setValue(20)
    panel.run_paths()
    wide = (float(panel.results.item(10, 4).text().replace(",", ""))
            - float(panel.results.item(10, 2).text().replace(",", "")))
    assert wide > narrow


# -- the chart, and the run you keep beside it --------------------------------

def test_nothing_is_saved_until_you_ask(panel):
    assert panel.saved_sim() is None


def test_saving_before_running_says_so(panel):
    panel.save_sim()
    assert "nothing to save" in panel.status.text()
    assert panel.saved_sim() is None


def test_a_saved_run_outlives_the_panel(panel, qapp, tmp_path):
    """A baseline you have to rebuild every session is not a baseline."""
    from tradelab.ui.app import RetirementSimPanel
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 400_000, "Pierre"]])
    panel.spending.setValue(30_000)
    panel.run()
    panel.save_sim()

    again = RetirementSimPanel(Database(path=tmp_path / "sim.db"))
    saved = again.saved_sim()
    assert saved and len(saved["years"]) == len(panel.rows)
    assert saved["balances"][0] == pytest.approx(panel.rows[0]["closing"])
    again.clear_saved_sim()


def test_a_later_run_does_not_move_the_saved_line(panel):
    """It changes only on Save sim — that asymmetry is the whole point."""
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 400_000, "Pierre"]])
    panel.spending.setValue(30_000)
    panel.run()
    panel.save_sim()
    kept = panel.saved_sim()["balances"][:]

    panel.spending.setValue(60_000)     # a different experiment
    panel.run()
    assert panel.saved_sim()["balances"] == kept
    panel.clear_saved_sim()


def test_saving_again_replaces_it(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 400_000, "Pierre"]])
    panel.spending.setValue(30_000)
    panel.run(); panel.save_sim()
    first = panel.saved_sim()["balances"][-1]
    panel.spending.setValue(10_000)
    panel.run(); panel.save_sim()
    assert panel.saved_sim()["balances"][-1] != first
    panel.clear_saved_sim()


def test_clearing_removes_the_saved_line(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 400_000, "Pierre"]])
    panel.run(); panel.save_sim()
    panel.clear_saved_sim()
    assert panel.saved_sim() is None


def test_the_saved_label_says_what_it_was(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 400_000, "Pierre"]])
    panel.spending.setValue(45_000)
    panel.real_return.setValue(3.0)
    panel.run(); panel.save_sim()
    assert "45,000" in panel.saved_sim()["label"]
    panel.clear_saved_sim()


def test_a_many_path_run_is_saved_as_its_median(panel):
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 400_000, "Pierre"]])
    panel.spending.setValue(20_000)
    panel.until_age.setValue(80)
    panel.paths.setValue(60)
    panel.run(); panel.run_paths(); panel.save_sim()
    assert "paths" in panel.saved_sim()["label"]
    panel.clear_saved_sim()


def test_the_chart_is_optional(panel):
    """The panel is built before the window wires a chart to it, and the
    tests build it with none at all."""
    assert panel.chart is None
    _fill(panel, [["Pierre", 64]], [["CELI", "tfsa", 400_000, "Pierre"]])
    panel.run()             # must not raise


# -- inflation ----------------------------------------------------------------

def test_the_inflation_rate_has_a_sensible_default(panel):
    assert panel.inflation.value() == 2.0


def test_the_nominal_equivalent_is_shown_and_is_not_a_sum(panel):
    """3% real with 2% inflation is 5.06% nominal, not 5%."""
    panel.real_return.setValue(3.0)
    panel.inflation.setValue(2.0)
    assert "5.06" in panel.nominal_hint.text()
    assert "nominal" in panel.nominal_hint.text()


def test_the_nominal_hint_follows_both_inputs(panel):
    panel.real_return.setValue(4.0)
    panel.inflation.setValue(0.0)
    assert "4.00" in panel.nominal_hint.text()


def test_an_income_is_indexed_unless_the_cell_says_no(panel):
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 1000, "Pierre"]],
          [["RRQ", "Pierre", 13128, 65, "", ""]])
    assert panel._read("incomes")[0]["indexed"] == 1


def test_typing_no_marks_an_income_as_not_indexed(panel):
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 1000, "Pierre"]],
          [["Rente", "Pierre", 20000, 65, "", "No"]])
    assert panel._read("incomes")[0]["indexed"] == 0


def test_the_french_word_is_understood_too(panel):
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 1000, "Pierre"]],
          [["Rente", "Pierre", 20000, 65, "", "non"]])
    assert panel._read("incomes")[0]["indexed"] == 0


def test_the_flag_reaches_the_plan(panel):
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 1000, "Pierre"]],
          [["Rente", "Pierre", 20000, 65, "", "No"],
           ["RRQ", "Pierre", 13128, 65, "", ""]])
    plan = panel.build_plan()
    by_name = {i.name: i.indexed for i in plan.incomes}
    assert by_name == {"Rente": False, "RRQ": True}


def test_the_inflation_rate_reaches_the_plan(panel):
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 1000, "Pierre"]])
    panel.inflation.setValue(2.5)
    assert panel.build_plan().inflation == pytest.approx(0.025)


def test_a_fixed_pension_shrinks_across_the_projection(panel):
    """The income column falls even though the pension never changes."""
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 500_000, "Pierre"]],
          [["Rente", "Pierre", 20_000, 65, "", "No"]])
    panel.inflation.setValue(3.0)
    panel.spending.setValue(0)
    panel.until_age.setValue(90)
    panel.run()
    assert panel.rows[-1]["income"] < panel.rows[0]["income"]


def test_an_indexed_pension_holds_across_the_projection(panel):
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 500_000, "Pierre"]],
          [["RRQ", "Pierre", 13_128, 65, "", "Yes"]])
    panel.inflation.setValue(3.0)
    panel.spending.setValue(0)
    panel.until_age.setValue(90)
    panel.run()
    assert panel.rows[-1]["income"] == pytest.approx(panel.rows[0]["income"])


def test_the_indexed_flag_survives_a_save_and_reload(panel, qapp, tmp_path):
    from tradelab.ui.app import RetirementSimPanel
    _fill(panel, [["Pierre", 65]], [["CELI", "tfsa", 1000, "Pierre"]],
          [["Rente", "Pierre", 20000, 65, "", "No"]])
    panel.inflation.setValue(2.4)
    panel.save()
    again = RetirementSimPanel(Database(path=tmp_path / "sim.db"))
    assert again.tables["incomes"].item(0, 5).text() == "No"
    assert again.inflation.value() == pytest.approx(2.4)
