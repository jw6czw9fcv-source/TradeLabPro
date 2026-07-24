"""UI smoke tests for the Coach tab (CoachPanel).

A temp-file Journal is injected so grading runs deterministically offline; the
LLM path is never exercised here (no key), so the panel uses its offline review.
"""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tradelab.core.journal import Journal, JournalEntry


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _journal(tmp_path):
    j = Journal(path=tmp_path / "journal.json")
    # A textbook trade and a reckless no-stop trade.
    good = JournalEntry(symbol="AAPL", side="Long", qty=100, entry_price=100,
                        stop=96, strategy="Breakout", notes="clean base")
    good.close(110, "2026-01-10")
    bad = JournalEntry(symbol="TSLA", side="Long", qty=50, entry_price=200,
                       entry_date="2026-01-02")
    bad.close(180, "2026-01-05")           # no stop, a loss
    j.add(good); j.add(bad)
    return j


def test_coach_panel_grades_and_reports(qapp, tmp_path, monkeypatch):
    import tradelab.ui.app as app
    # Ensure no API key so the panel stays in offline mode.
    monkeypatch.setattr(app, "get_history", lambda *a, **k: None)
    panel = app.CoachPanel(journal=_journal(tmp_path))

    # Both closed trades appear, graded.
    assert panel.table.rowCount() == 2
    grades = {panel.table.item(r, 1).text(): panel.table.item(r, 0).text()
              for r in range(panel.table.rowCount())}
    assert grades["AAPL"] == "A"          # stop, +2.5R, documented
    assert grades["TSLA"] == "F"          # no stop -> poor process despite being a real loss

    # Headline grade + offline report populated, with the safety disclaimer.
    assert panel.grade_label.text() not in ("", "—")
    report = panel.report.toPlainText()
    assert "process" in report.lower()
    assert "not financial advice" in report.lower()


def test_coach_chat_without_key_falls_back_to_offline_review(qapp, tmp_path, monkeypatch):
    import tradelab.ui.app as app
    from tradelab.core import ai_assistant
    monkeypatch.setattr(ai_assistant, "api_key_from_env", lambda: None)
    panel = app.CoachPanel(journal=_journal(tmp_path))
    panel.key_edit.clear()                 # no key in the field either

    panel.prompt.setText("What am I doing wrong?")
    panel._send()
    log = panel.log.toPlainText()
    assert "needs an Anthropic API key" in log
    assert "not financial advice" in log.lower()


def test_coach_panel_empty_journal_is_safe(qapp, tmp_path):
    import tradelab.ui.app as app
    panel = app.CoachPanel(journal=Journal(path=tmp_path / "empty.json"))
    assert panel.table.rowCount() == 0
    assert panel.grade_label.text() == "—"
    assert "No closed trades yet" in panel.report.toPlainText()
