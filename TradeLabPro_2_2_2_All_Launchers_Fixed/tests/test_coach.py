"""Tests for the AI Trading Coach core (tradelab/core/coach.py).

The coach is deterministic and offline: grading and the process report are pure
functions of journal entries, and the LLM path is transport-injected so nothing
here touches the network.
"""
import pytest

from tradelab.core.journal import JournalEntry
from tradelab.core import coach


def _trade(symbol="AAPL", side="Long", entry=100.0, exit=None, stop=None, qty=100,
           strategy="", notes="", entry_date="2026-01-01", exit_date=None):
    e = JournalEntry(symbol=symbol, side=side, qty=qty, entry_price=entry, stop=stop,
                     strategy=strategy, notes=notes, entry_date=entry_date)
    if exit is not None:
        e.close(exit, exit_date or "2026-01-10")
    return e


# --- grading rubric ---------------------------------------------------------

def test_textbook_trade_grades_A():
    # Stop defined, +2.5R win, documented -> top marks.
    e = _trade(entry=100, stop=96, exit=110, strategy="Breakout", notes="clean base")
    g = coach.grade_trade(e)
    assert g["gradeable"] and g["grade"] == "A" and g["score"] >= 85


def test_lucky_no_stop_win_grades_poorly():
    # A profitable trade with NO stop must still grade badly: risk was undefined.
    e = _trade(entry=100, stop=None, exit=140, strategy="YOLO")
    g = coach.grade_trade(e)
    assert g["grade"] == "F"
    assert any("No protective stop" in text for _, text in g["reasons"])


def test_disciplined_small_loss_beats_reckless_win():
    # Process over outcome: a contained -1R loss taken with a stop and a plan
    # should out-grade a bigger-dollar win taken with no stop.
    good_loss = _trade(entry=100, stop=95, exit=95, strategy="Pullback", notes="failed hold")
    reckless_win = _trade(entry=100, stop=None, exit=115)
    assert coach.grade_trade(good_loss)["score"] > coach.grade_trade(reckless_win)["score"]


def test_honored_stop_scores_above_broken_stop():
    honored = _trade(entry=100, stop=95, exit=95, strategy="X")     # -1R, at the stop
    gapped = _trade(entry=100, stop=95, exit=88, strategy="X")      # -2.4R, ran past it
    g_h, g_g = coach.grade_trade(honored), coach.grade_trade(gapped)
    assert g_h["score"] > g_g["score"]
    assert any("beyond the planned 1R" in text for _, text in g_g["reasons"])
    assert any("contained within the planned risk" in text for _, text in g_h["reasons"])


def test_undocumented_trade_penalised():
    doc = _trade(entry=100, stop=96, exit=104, strategy="Breakout")
    undoc = _trade(entry=100, stop=96, exit=104)
    assert coach.grade_trade(doc)["score"] > coach.grade_trade(undoc)["score"]


def test_open_trade_is_not_graded_but_gets_setup_read():
    e = _trade(entry=100, stop=96, exit=None, strategy="Breakout")   # still open
    g = coach.grade_trade(e)
    assert g["gradeable"] is False and g["score"] is None
    assert any("protective stop" in text for _, text in g["reasons"])


def test_letter_for_bands():
    assert coach.letter_for(90) == "A"
    assert coach.letter_for(70) == "B"
    assert coach.letter_for(55) == "C"
    assert coach.letter_for(40) == "D"
    assert coach.letter_for(10) == "F"


def test_score_is_clamped_to_0_100():
    for e in (_trade(entry=100, stop=96, exit=200, strategy="x", notes="y"),
              _trade(entry=100, stop=None, exit=50)):
        g = coach.grade_trade(e)
        assert 0 <= g["score"] <= 100


# --- aggregate report -------------------------------------------------------

def test_report_no_stop_percentage():
    entries = [
        _trade(stop=96, exit=104, strategy="a"),
        _trade(stop=None, exit=104),
        _trade(stop=None, exit=96),
        _trade(stop=95, exit=98, strategy="b"),
    ]
    r = coach.coach_report(entries)
    assert r["closed"] == 4
    assert r["no_stop_pct"] == 50.0


def test_report_stop_honored_percentage():
    # Two losers with stops: one honored (-1R), one gapped (-3R).
    entries = [
        _trade(entry=100, stop=95, exit=95, strategy="a"),   # honored loss
        _trade(entry=100, stop=95, exit=85, strategy="a"),   # gapped loss
        _trade(entry=100, stop=96, exit=110, strategy="a"),  # winner, ignored here
    ]
    r = coach.coach_report(entries)
    assert r["stop_honored_pct"] == pytest.approx(50.0)


def test_report_flags_riding_losers():
    # Winners held ~2 days, losers held ~20 days -> should warn about holding losers.
    entries = [
        _trade(entry=100, stop=96, exit=106, strategy="a",
               entry_date="2026-01-01", exit_date="2026-01-03"),
        _trade(entry=100, stop=96, exit=94, strategy="a",
               entry_date="2026-01-01", exit_date="2026-01-21"),
    ]
    r = coach.coach_report(entries)
    assert r["avg_hold_loss"] > r["avg_hold_win"]
    assert any("hold losers" in s["text"] for s in r["suggestions"])


def test_report_rewards_full_stop_discipline():
    entries = [_trade(entry=100, stop=96, exit=108, strategy="a", notes="n"),
               _trade(entry=100, stop=98, exit=99, strategy="b", notes="n")]
    r = coach.coach_report(entries)
    assert r["no_stop_pct"] == 0.0
    assert any(s["kind"] == "good" and "defined stop" in s["text"] for s in r["suggestions"])


def test_report_empty_journal_is_safe():
    r = coach.coach_report([])
    assert r["closed"] == 0
    assert r["suggestions"] and r["suggestions"][0]["kind"] == "info"


def test_report_small_sample_note():
    r = coach.coach_report([_trade(stop=96, exit=104, strategy="a")])
    assert any("directional" in s["text"] for s in r["suggestions"])


# --- context + offline report ----------------------------------------------

def test_offline_report_mentions_grade_and_disclaimer():
    entries = [_trade(entry=100, stop=96, exit=110, strategy="Breakout", notes="n"),
               _trade(entry=100, stop=None, exit=90)]
    text = coach.offline_coach_report(entries)
    assert "process grade" in text.lower()
    assert "not financial advice" in text.lower()


def test_offline_report_empty_journal():
    text = coach.offline_coach_report([])
    assert "No closed trades yet" in text
    assert "not financial advice" in text.lower()


def test_build_context_is_bounded_and_has_numbers():
    entries = [_trade(symbol=f"S{i}", entry=100, stop=96, exit=104 + i, strategy="a")
               for i in range(40)]
    ctx = coach.build_coach_context(entries, recent=25)
    assert "Journal process summary" in ctx
    assert "Win rate" in ctx
    # Only the most-recent `recent` trades are itemised, not all 40.
    assert ctx.count("· Long ·") <= 25


# --- LLM path (transport injected) ------------------------------------------

def test_coach_answer_uses_coach_system_prompt_and_context():
    captured = {}

    def fake_transport(payload, api_key):
        captured["payload"] = payload
        return {"content": [{"type": "text", "text": "Your stop discipline is the thing to fix."}]}

    entries = [_trade(entry=100, stop=None, exit=120)]   # no-stop trade in the data
    reply = coach.coach_answer([{"role": "user", "content": "What am I doing wrong?"}],
                               api_key="sk-test", model="claude-sonnet-5",
                               entries=entries, transport=fake_transport)
    assert "stop discipline" in reply
    system = captured["payload"]["system"]
    assert "AI Trading Coach" in system
    assert "never predict prices" in system.lower() or "never tell the user to buy" in system.lower()
    # The journal summary was passed as reference context.
    assert "Journal process summary" in system
