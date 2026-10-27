"""The AI Assist shortlist check: candidates side by side, ordered by the
investor's own criteria, explained by the AI without a verdict."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core import ai_assistant
from tradelab.core import candidate as cd


def _prices(drift, vol, seed):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, 2660)
    idx = pd.bdate_range(end=pd.Timestamp("2026-10-16"), periods=2660)
    return pd.Series(100 * np.exp(np.cumsum(r)), index=idx)


def _row(symbol, **over):
    row = cd.facts(symbol, _prices(0.0003, 0.008, 1), {"quote_type": "ETF", "name": symbol},
                   mer=0.002, dividend_yield=0.0)
    row.update(over)
    return row


def test_facts_carry_the_numbers_of_the_check():
    row = cd.facts("VTI", _prices(0.0004, 0.01, 2), {"quote_type": "ETF", "name": "Total"},
                   mer=0.0003, mer_source="Yahoo", dividend_yield=0.013,
                   holdings={"AAPL": 0.06}, owned={"AAPL": "RRSP"}, split={"stocks": 1.0})
    assert row["mer"] == 0.0003 and row["band"] and row["worst_fall"] < 0
    assert row["ret10"] is not None and row["overlap_pct"] == pytest.approx(6.0)
    assert row["suits"] == "REER" and row["adds"] == "stocks"
    stock = cd.facts("NVDA", None, {"quote_type": "EQUITY"})
    assert stock["mer"] == 0.0 and stock["kind"] == "stock" and stock["stdev"] is None


def test_the_shortlist_is_ordered_by_the_chosen_criteria_with_unknowns_last():
    rows = [_row("A", mer=0.0025, worst_fall=-0.30), _row("B", mer=None, worst_fall=-0.10),
            _row("C", mer=0.0010, worst_fall=-0.20), _row("D", mer=0.0010, worst_fall=-0.15)]
    assert [r["symbol"] for r in cd.rank(rows, "Lowest fees")][:3] == ["C", "D", "A"]
    assert cd.rank(rows, "Lowest fees")[-1]["symbol"] == "B"
    assert [r["symbol"] for r in cd.rank(rows, "Lowest fees", "Smallest worst fall")][:2] == ["D", "C"]
    assert [r["symbol"] for r in cd.rank(rows, "Smallest worst fall")][0] == "B"


def test_the_table_the_ai_sees_has_every_figure_and_no_gaps_invented():
    text = cd.table_text([_row("XEQT.TO"), _row("ZZZ", ret10=None)])
    assert text.splitlines()[0].startswith("symbol | name")
    assert "XEQT.TO" in text and "n/a" in text


def test_the_ai_is_asked_without_a_verdict_on_the_current_model():
    sent = {}

    def transport(payload, key):
        sent.update(payload)
        return {"content": [{"type": "text", "text": "XEQT.TO has the lowest fees."}],
                "stop_reason": "end_turn"}

    reply = ai_assistant.ask([{"role": "user", "content": "Explain"}], "k",
                             system=ai_assistant.SHORTLIST_SYSTEM, context="table",
                             transport=transport)
    assert reply.startswith("XEQT.TO")
    assert sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"
    assert "Never tell the user to buy, sell or hold" in sent["system"]
    assert sent["max_tokens"] >= 16000


def test_a_declined_request_says_so():
    with pytest.raises(ai_assistant.AIAssistantError, match="declined"):
        ai_assistant.ask([{"role": "user", "content": "x"}], "k",
                         transport=lambda p, k: {"content": [], "stop_reason": "refusal"})


def test_haiku_is_sent_without_a_fallback():
    sent = {}
    ai_assistant.ask([{"role": "user", "content": "x"}], "k", model="claude-haiku-5-5",
                     transport=lambda p, k: sent.update(p) or {"content": [{"type": "text", "text": "ok"}]})
    assert "fallbacks" not in sent


pytest.importorskip("PySide6")


def test_the_ai_assist_tab_fills_and_orders_the_table(tmp_path):
    from PySide6.QtWidgets import QApplication
    from tradelab.data.database import Database
    from tradelab.ui.app import AIAssistantPanel
    QApplication.instance() or QApplication([])
    db = Database(path=tmp_path / "s.db")
    panel = AIAssistantPanel(db)
    gathered = {s: {"prices": _prices(d, 0.008, i), "meta": {"quote_type": "ETF", "name": s,
                                                             "expense_ratio": fee},
                    "yield": 0.0, "holdings": {}, "owned_comps": {}}
                for i, (s, d, fee) in enumerate([("AAA", 0.0003, 0.0025), ("BBB", 0.0004, 0.0005)])}
    panel.shortlist_sort.setCurrentText("Lowest fees")
    panel._on_shortlist(gathered, [])
    assert panel.shortlist_table.rowCount() == 2
    assert panel.shortlist_table.item(0, 0).text() == "BBB"
    assert "(Yahoo)" in panel.shortlist_table.item(0, 2).text()
    db.conn.close()


def test_explaining_needs_a_shortlist_and_a_key(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from tradelab.ui.app import AIAssistantPanel
    QApplication.instance() or QApplication([])
    shown = []
    monkeypatch.setattr("tradelab.ui.common.show_problem", lambda text, parent=None: shown.append(text))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    panel = AIAssistantPanel(None)
    panel.key_edit.setText("")
    panel.explain_shortlist()
    assert shown and "Check a shortlist first" in shown[-1]
    panel.shortlist = [_row("AAA")]
    panel.explain_shortlist()
    assert "API key" in shown[-1]
