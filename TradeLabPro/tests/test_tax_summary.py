"""The tax-season summary: a year's closed trades and plan flows."""
import pytest

from tradelab.core import tax_summary as ts
from tradelab.core.journal import JournalEntry
from tradelab.core.retirement import Account, Flow, Fund


def _entries():
    return [
        JournalEntry(symbol="ABC.TO", qty=10, entry_price=20, entry_date="2025-03-01",
                     exit_price=25, exit_date="2025-06-01"),
        JournalEntry(symbol="XYZ", qty=5, entry_price=100, entry_date="2025-02-01",
                     exit_price=90, exit_date="2025-09-01"),
        JournalEntry(symbol="DEF.TO", qty=1, entry_price=10, entry_date="2025-01-05",
                     exit_price=12, exit_date="2026-01-10"),      # another year
        JournalEntry(symbol="OPEN.TO", qty=1, entry_price=10, entry_date="2025-01-05"),
    ]


def test_trades_closed_in_the_year_are_summed_per_currency():
    s = ts.summary(2025, _entries(), [])
    assert [t["symbol"] for t in s["trades"]] == ["ABC.TO", "XYZ"]
    assert s["by_currency"]["CAD"] == {"gains": 50.0, "losses": 0.0, "net": 50.0, "trades": 1}
    assert s["by_currency"]["USD"]["losses"] == pytest.approx(-50.0)


def test_plan_contributions_and_withdrawals_of_the_year():
    fund = Fund(name="F", flows=[Flow(date="2025-04-01", amount=3_000),
                                 Flow(date="2025-11-01", amount=1_000, kind="withdrawal"),
                                 Flow(date="2024-04-01", amount=9_999)])
    s = ts.summary(2025, [], [Account(name="Group plan", funds=[fund])])
    assert s["flows"] == [{"account": "Group plan", "currency": "CAD",
                           "contributed": 3_000.0, "withdrawn": 1_000.0}]


def test_the_text_says_what_it_cannot_know_and_the_csv_has_every_line():
    s = ts.summary(2025, _entries(), [])
    text = ts.as_text(s)
    assert "not taxed" in text and "Relevé" in text
    rows = ts.to_csv(s).strip().splitlines()
    assert len(rows) == 1 + 2 and rows[1].startswith("trade,ABC.TO")


pytest.importorskip("PySide6")


def test_the_journal_tab_opens_the_summary(tmp_path):
    from PySide6.QtWidgets import QApplication
    from tradelab.core.journal import Journal
    from tradelab.ui.app import JournalPanel
    QApplication.instance() or QApplication([])
    panel = JournalPanel(None, None)
    panel.journal = Journal(tmp_path / "j.json")
    for e in _entries():
        panel.journal.add(e)
    panel.retirement_path = tmp_path / "none.json"
    panel.tax_summary(2025)
    assert panel.tax_data["by_currency"]["CAD"]["net"] == 50.0
    panel.tax_dialog.close()
