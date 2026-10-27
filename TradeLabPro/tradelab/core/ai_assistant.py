"""Phase 7 (option b): a real LLM-backed AI assistant.

This is the natural-language "AI Assist" the roadmap called for - it explains
scan results, charts and setups in plain English by calling an external LLM
(Anthropic's Messages API). It is deliberately kept **Qt-free and transport-
injectable** so it is fully unit-testable offline: the UI layer reads the
user's own API key + model choice from settings and passes them in here.

Design guarantees:
- **The user supplies their own API key** (real per-use cost). Nothing here
  ships a key; there is no default endpoint credential.
- **Graceful degradation**: with no key configured, `answer()` falls back to
  the offline, rules-based Trade Coach (`ai_ranker.explain_symbol`) so the
  feature is always usable without any external dependency or cost.
- **Not financial advice**: the system prompt hard-constrains the model to
  educational/explanatory output only - no buy/sell/hold calls, no price
  targets framed as recommendations. This is enforced server-side by the
  prompt and surfaced again in the UI disclaimer.
"""
from __future__ import annotations

import os

from tradelab.core.ai_ranker import explain_symbol

# Current Claude models (2026-10). Opus 5.5 is the default; Sonnet 5.5 is the
# faster, cheaper choice, Haiku 5.5 the cheapest. All think before answering
# (adaptive thinking is always on), so the answer budget below leaves room for
# that thinking - at the old 1024 the reply could come back empty.
DEFAULT_MODEL = "claude-opus-5-5"
MODELS = [
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
]

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MAX_TOKENS = 16000
TIMEOUT_SECONDS = 300
# A request the model's safety classifiers decline is re-run server-side on a
# recommended model instead of coming back as a refusal. Opus 5.5 and Sonnet
# 5.5 accept it; Haiku 5.5 has no server-side fallback.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")

SYSTEM_PROMPT = (
    "You are the built-in analysis assistant inside TradeLabPro, a desktop "
    "stock-charting and scanning app. Your job is EDUCATIONAL: explain what "
    "technical indicators, scan scores and chart setups mean, in clear plain "
    "language, so the user understands the data in front of them.\n\n"
    "Hard rules you must never break:\n"
    "- You are NOT a licensed financial advisor and must not give personalized "
    "investment advice. Never tell the user to buy, sell, hold, or size a "
    "position, and never give a price target framed as a recommendation.\n"
    "- Describe what the indicators show and what such conditions *generally* "
    "mean in technical analysis, always as education, not instruction.\n"
    "- Be honest about uncertainty. Past patterns do not predict the future.\n"
    "- When you state figures, use the numbers provided in the context; do not "
    "invent data you were not given.\n"
    "- Keep answers concise and end anything resembling a trade discussion with "
    "a brief reminder that this is educational information, not financial advice."
)


SHORTLIST_SYSTEM = (
    "You are the built-in assistant inside TradeLabPro. The user, a Canadian "
    "investor, has put a shortlist of funds or stocks side by side; the table "
    "below is computed by the app from ten years of prices and published data. "
    "Explain it in plain language so they can decide faster:\n"
    "- Say what stands out: the lowest fees, the deepest past fall, the steadiest, "
    "big overlaps with what they already own, which ones keep their US dividends "
    "whole in a REER rather than a CELI.\n"
    "- Point out trade-offs and anything worth a second look, and say what the "
    "table cannot show (future returns, a fund's strategy, the investor's needs).\n"
    "- Use only the figures in the table; say 'n/a' is unknown, never guess it.\n"
    "Hard rules: you are not a licensed financial advisor. Never tell the user to "
    "buy, sell or hold anything, never rank one as 'the best choice' for them, and "
    "never suggest amounts. Past returns do not predict future ones. End with one "
    "line saying this is information for their own decision, not advice. Be concise."
)


class AIAssistantError(RuntimeError):
    """Raised for configuration/transport/API failures so the UI can show a
    friendly message instead of crashing."""


def api_key_from_env() -> str | None:
    """Fallback key source: the standard ANTHROPIC_API_KEY environment
    variable. The UI prefers a key the user saved in settings, then this."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def is_configured(api_key: str | None) -> bool:
    return bool(api_key and api_key.strip())


def build_symbol_context(symbol: str, df, cfg) -> str:
    """Turn a symbol's latest indicator readout into a compact text block the
    LLM can reason over. Reuses the offline coach's scoring so the numbers the
    assistant sees match what the rest of the app computes."""
    info = explain_symbol(symbol, df, cfg)
    lines = [f"Symbol: {symbol}", f"Rules-based score: {info['score']}/100 ({info['summary']})"]
    if info.get("parts"):
        lines.append("Score components:")
        lines += [f"  - {k}: {v}" for k, v in info["parts"].items()]
    try:
        from tradelab.core.indicators import add_indicators
        data = add_indicators(df, cfg.ema_fast, cfg.ema_slow,
                              cfg.macd_fast, cfg.macd_slow, cfg.macd_signal).dropna()
        if not data.empty:
            last = data.iloc[-1]
            def g(col):
                try:
                    return round(float(last[col]), 2)
                except Exception:
                    return None
            snapshot = {
                "Close": g("Close"),
                f"EMA{cfg.ema_fast}": g(f"EMA{cfg.ema_fast}"),
                f"EMA{cfg.ema_slow}": g(f"EMA{cfg.ema_slow}"),
                "RSI14": g("RSI14"),
                "MACD": g("MACD"),
                "MACD_SIGNAL": g("MACD_SIGNAL"),
                "ADX14": g("ADX14"),
                "REL_VOL": g("REL_VOL"),
            }
            lines.append("Latest indicator values:")
            lines += [f"  - {k}: {v}" for k, v in snapshot.items() if v is not None]
    except Exception:
        pass
    return "\n".join(lines)


def offline_answer(symbol: str, df, cfg) -> str:
    """No-key / no-network fallback: the rules-based Trade Coach, formatted as
    a plain-language block, with an explicit note that full AI is off."""
    info = explain_symbol(symbol, df, cfg)
    lines = [
        f"{symbol} - offline Trade Coach (rules-based; no API key set)",
        "",
        f"Score: {info['score']}/100 - {info['summary']}",
    ]
    if info.get("parts"):
        lines.append("")
        lines.append("Breakdown:")
        lines += [f"  - {k}: {v}" for k, v in info["parts"].items()]
    lines += [
        "",
        "Add your Anthropic API key in the field above to get full natural-"
        "language answers from the AI assistant.",
        "",
        "Educational information only - not financial advice.",
    ]
    return "\n".join(lines)


def _default_transport(payload: dict, api_key: str) -> dict:
    """Real network call to the Anthropic Messages API via requests (already
    available through yfinance). Isolated here so tests inject a fake and never
    touch the network."""
    try:
        import requests
    except ImportError as e:  # pragma: no cover - requests ships with yfinance
        raise AIAssistantError("The 'requests' library is required for the AI assistant.") from e
    headers = {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    if "fallbacks" in payload:
        headers["anthropic-beta"] = FALLBACK_BETA
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
    except Exception as e:
        raise AIAssistantError(f"Could not reach the AI service: {e}") from e
    if resp.status_code == 401:
        raise AIAssistantError("Authentication failed - check your API key.")
    if resp.status_code == 429:
        raise AIAssistantError("Rate limited by the AI service - try again shortly.")
    if resp.status_code >= 400:
        raise AIAssistantError(f"AI service error {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except Exception as e:
        raise AIAssistantError("AI service returned an unreadable response.") from e


def ask(messages: list[dict], api_key: str | None, model: str = DEFAULT_MODEL,
        system: str = SYSTEM_PROMPT, context: str | None = None,
        max_tokens: int = MAX_TOKENS, transport=None) -> str:
    """Send a chat turn to the LLM and return its text reply.

    `messages` is a list of {"role": "user"|"assistant", "content": str}.
    `context` (optional) is prepended to the system prompt as reference data
    (e.g. a symbol's indicator snapshot). `transport` is injectable for tests.
    """
    if not is_configured(api_key):
        raise AIAssistantError("No API key configured.")
    if not messages:
        raise AIAssistantError("Nothing to ask.")
    sys_prompt = system
    if context:
        sys_prompt = f"{system}\n\nReference data for this session:\n{context}"
    model = model or DEFAULT_MODEL
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": sys_prompt,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
    }
    if model in FALLBACK_MODELS:
        payload["fallbacks"] = "default"
    transport = transport or _default_transport
    data = transport(payload, api_key.strip())
    if isinstance(data, dict) and data.get("stop_reason") == "refusal":
        raise AIAssistantError("The AI declined this request. Rephrase it as a question about "
                               "the data, or try another model.")
    # Anthropic Messages API: {"content": [{"type": "text", "text": "..."}], ...}
    try:
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except AttributeError as e:
        raise AIAssistantError("Unexpected response shape from the AI service.") from e
    if not text.strip():
        raise AIAssistantError("The AI service returned an empty answer.")
    return text.strip()
