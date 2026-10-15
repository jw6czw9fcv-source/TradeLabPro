"""Retirement reminders dated from a birth month."""
import datetime as dt

import pytest

from tradelab.core.retirement_dates import checklist, parse_born


def test_birth_months_are_read_in_the_usual_forms():
    assert parse_born("1962-08") == dt.date(1962, 8, 1)
    assert parse_born("1962-08-14") == dt.date(1962, 8, 1)
    assert parse_born("08/1962") == dt.date(1962, 8, 1)
    assert parse_born("1962-13") is None and parse_born("") is None and parse_born(None) is None


def test_the_reminders_for_someone_born_in_august_1962():
    people = [{"name": "Anne", "born": "1962-08"}]
    incomes = [{"name": "RRQ", "owner": "Anne", "starts_at_age": 65},
               {"name": "PSV", "owner": "Anne", "starts_at_age": 70}]
    items = checklist(people, incomes, today=dt.date(2026, 10, 14))
    anne = [i for i in items if i["person"] == "Anne"]

    def on(day):
        return " | ".join(i["what"] for i in anne if i["date"] == day)

    assert "RRQ application opens" in on(dt.date(2026, 8, 1))              # 12 months before 65
    assert "enrolment letter" in on(dt.date(2026, 8, 1))                    # 64th birthday
    assert "Apply for the RRQ" in on(dt.date(2027, 5, 1))                   # 3 months before
    contact = next(i for i in anne if i["date"] == dt.date(2026, 9, 1))
    assert "Contact Service Canada" in contact["what"] and "at 70" in contact["what"]
    assert any(i["date"] == dt.date(2033, 12, 31) and "RRIF" in i["what"] for i in anne)
    tfsa = next(i for i in items if i["person"] == "Everyone")
    assert tfsa["date"] == dt.date(2027, 1, 1)
    # Sorted, past ones flagged, every row sourced.
    dated = [i["date"] for i in items if i["date"]]
    assert dated == sorted(dated)
    assert next(i for i in anne if i["date"] == dt.date(2026, 8, 1))["past"] is True
    assert all(i["source"] for i in items if i["date"])


def test_without_a_birth_month_it_asks_for_one():
    items = checklist([{"name": "Bob", "born": ""}], [], today=dt.date(2026, 10, 14))
    assert items[0]["person"] == "Bob" and items[0]["date"] is None
    assert "birth month" in items[0]["what"]


def test_a_pension_starting_at_65_adds_no_waiting_note():
    items = checklist([{"name": "Anne", "born": "1962-08"}],
                      [{"name": "PSV", "owner": "Anne", "starts_at_age": 65}],
                      today=dt.date(2026, 10, 14))
    contact = next(i for i in items if "Contact Service Canada" in i["what"])
    assert "waiting" not in contact["what"]


pytest.importorskip("PySide6")


def test_the_key_dates_window(tmp_path):
    from PySide6.QtWidgets import QApplication, QTableWidget
    from tradelab.data.database import Database
    from tradelab.ui.app import RetirementSimPanel, table_item
    QApplication.instance() or QApplication([])
    db = Database(path=tmp_path / "d.db")
    panel = RetirementSimPanel(db)
    people = panel.tables["people"]
    people.setRowCount(1)
    for c, value in enumerate(["Anne", 64, "", "1962-08"]):
        people.setItem(0, c, table_item(value))
    panel.show_key_dates()
    table = panel.dates_dialog.findChild(QTableWidget)
    assert table.rowCount() == len(panel.key_dates) >= 4
    # The birth month survives a save and a reload.
    panel.save()
    again = RetirementSimPanel(db)
    assert again.tables["people"].item(0, 3).text() == "1962-08"
    db.conn.close()
