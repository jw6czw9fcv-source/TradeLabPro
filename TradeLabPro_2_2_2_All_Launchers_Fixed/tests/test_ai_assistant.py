"""Tests for the Phase 7 LLM-backed AI assistant (tradelab/core/ai_assistant).

Every test injects a fake transport - the assistant NEVER touches the network
here. Covers configuration, offline fallback, context building, the request
payload/guardrails, and response parsing."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core import ai_assistant as ai
from tradelab.core.config import ScannerConfig


def _df(n=300):
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.014, n)))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n)})


def _fake_transport_returning(text, captured=None):
    def _t(payload, api_key):
        if captured is not None:
            captured["payload"] = payload
            captured["api_key"] = api_key
        return {"content": [{"type": "text", "text": text}]}
    return _t


def test_is_configured_reflects_key_presence():
    assert ai.is_configured(None) is False
    assert ai.is_configured("") is False
    assert ai.is_configured("   ") is False
    assert ai.is_configured("sk-ant-123") is True


def test_api_key_from_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai.api_key_from_env() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    assert ai.api_key_from_env() == "sk-ant-env"


def test_ask_without_key_raises():
    with pytest.raises(ai.AIAssistantError):
        ai.ask([{"role": "user", "content": "hi"}], api_key=None)


def test_ask_returns_model_text_via_injected_transport():
    captured = {}
    reply = ai.ask([{"role": "user", "content": "Explain RSI"}],
                   api_key="sk-ant-x", model="claude-sonnet-5",
                   transport=_fake_transport_returning("RSI measures momentum.", captured))
    assert reply == "RSI measures momentum."
    assert captured["api_key"] == "sk-ant-x"
    assert captured["payload"]["model"] == "claude-sonnet-5"
    assert captured["payload"]["messages"][0]["content"] == "Explain RSI"


def test_system_prompt_carries_the_no_financial_advice_guardrail():
    captured = {}
    ai.ask([{"role": "user", "content": "hi"}], api_key="k",
           transport=_fake_transport_returning("ok", captured))
    sys_prompt = captured["payload"]["system"].lower()
    assert "not a licensed financial advisor" in sys_prompt
    assert "buy, sell, hold" in sys_prompt


def test_context_is_prepended_to_the_system_prompt():
    captured = {}
    ai.ask([{"role": "user", "content": "hi"}], api_key="k", context="Symbol: AAPL score 82",
           transport=_fake_transport_returning("ok", captured))
    assert "Symbol: AAPL score 82" in captured["payload"]["system"]


def test_empty_model_response_raises():
    with pytest.raises(ai.AIAssistantError):
        ai.ask([{"role": "user", "content": "hi"}], api_key="k",
               transport=_fake_transport_returning("   "))


def test_build_symbol_context_includes_symbol_and_indicators():
    ctx = ai.build_symbol_context("AAPL", _df(), ScannerConfig())
    assert "AAPL" in ctx
    assert "score" in ctx.lower()
    assert "RSI14" in ctx


def test_offline_answer_is_rules_based_and_flags_missing_key():
    out = ai.offline_answer("MSFT", _df(), ScannerConfig())
    assert "MSFT" in out
    assert "not financial advice" in out.lower()
    assert "api key" in out.lower()


def test_default_model_is_a_current_claude_model():
    assert ai.DEFAULT_MODEL in ai.MODELS
    assert ai.DEFAULT_MODEL.startswith("claude-")
