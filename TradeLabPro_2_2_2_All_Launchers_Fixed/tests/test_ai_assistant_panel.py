"""Headless smoke tests for the AI Assistant UI panel. No network: the panel's
offline path uses the rules-based coach, and the online path is exercised by
injecting a fake worker reply. Confirms the panel constructs, reflects key
state, and routes replies into the chat log."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _df(n=200):
    rng = np.random.default_rng(5)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.013, n)))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n)})


def test_panel_constructs_and_reports_off_without_key(qapp, monkeypatch):
    from tradelab.ui.app import AIAssistantPanel
    from tradelab.core import ai_assistant
    monkeypatch.setattr(ai_assistant, "api_key_from_env", lambda: None)
    panel = AIAssistantPanel()
    panel.key_edit.setText("")
    panel._refresh_status()
    assert "off" in panel.status.text().lower()


def test_panel_shows_no_live_data_disclaimer(qapp):
    from PySide6.QtWidgets import QLabel
    from tradelab.ui.app import AIAssistantPanel
    panel = AIAssistantPanel()
    texts = " ".join(lbl.text() for lbl in panel.findChildren(QLabel))
    assert "No live market data" in texts
    assert "not financial advice" in texts.lower()


def test_panel_reports_on_with_a_key(qapp):
    from tradelab.ui.app import AIAssistantPanel
    panel = AIAssistantPanel()
    panel.key_edit.setText("sk-ant-test")
    panel._refresh_status()
    assert "on" in panel.status.text().lower()


def test_send_without_key_uses_offline_coach(qapp, monkeypatch):
    from tradelab.ui import app as appmod
    from tradelab.core import ai_assistant
    monkeypatch.setattr(ai_assistant, "api_key_from_env", lambda: None)
    monkeypatch.setattr(appmod, "get_history", lambda *a, **k: _df())
    panel = appmod.AIAssistantPanel()
    panel.key_edit.setText("")
    panel.symbol.setText("AAPL")
    panel.prompt.setText("What does this look like?")
    panel._send()
    text = panel.log.toPlainText()
    assert "Coach" in text
    assert "AAPL" in text


def test_online_reply_lands_in_log_and_history(qapp):
    from tradelab.ui.app import AIAssistantPanel
    panel = AIAssistantPanel()
    panel._history = [{"role": "user", "content": "Explain RSI"}]
    panel._on_reply("RSI is a momentum oscillator.")
    assert panel._history[-1] == {"role": "assistant", "content": "RSI is a momentum oscillator."}
    assert "RSI is a momentum oscillator." in panel.log.toPlainText()


def test_error_drops_failed_user_turn(qapp):
    from tradelab.ui.app import AIAssistantPanel
    panel = AIAssistantPanel()
    panel._history = [{"role": "user", "content": "boom"}]
    panel._on_error("network down")
    assert panel._history == []
    assert "AI error" in panel.log.toPlainText()
