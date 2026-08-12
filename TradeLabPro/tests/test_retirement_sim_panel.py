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
