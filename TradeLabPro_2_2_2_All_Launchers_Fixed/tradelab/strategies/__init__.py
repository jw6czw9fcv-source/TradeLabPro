"""Strategy registry (SCN-030 multi-strategy scanning).

Each strategy module exposes NAME and score_symbol(df, cfg) -> dict with
keys "signal", "score", "data" - see ema_macd.py / rsi_reversion.py.
Not a formal plugin/auto-discovery system (that's tracked separately,
planned for Phase 2/5) - just a small dict so the Scanner can offer more
than one hardcoded strategy.
"""
from tradelab.strategies import ema_macd, rsi_reversion

DEFAULT_STRATEGY = "ema_macd"

STRATEGIES = {
    "ema_macd": ema_macd,
    "rsi_reversion": rsi_reversion,
}


def strategy_module(key: str):
    return STRATEGIES.get(key, STRATEGIES[DEFAULT_STRATEGY])


def strategy_choices() -> list[tuple[str, str]]:
    """[(key, display name), ...] for populating a UI dropdown."""
    return [(key, getattr(mod, "NAME", key)) for key, mod in STRATEGIES.items()]
