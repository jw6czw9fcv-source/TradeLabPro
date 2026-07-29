"""Strategy registry (SCN-030 multi-strategy scanning + Phase 5 custom).

Each strategy exposes NAME and score_symbol(df, cfg) / signal_series(df, cfg)
- built-ins are modules (ema_macd.py / rsi_reversion.py); user-defined
no-code strategies (Phase 5) are CustomStrategy instances with the same
interface, keyed "custom:<name>" and loaded from disk on demand.
"""
from tradelab.strategies import ema_macd, rsi_reversion
from tradelab.strategies.custom import (
    CUSTOM_PREFIX, list_custom_strategies, load_custom_strategy,
)

DEFAULT_STRATEGY = "ema_macd"

STRATEGIES = {
    "ema_macd": ema_macd,
    "rsi_reversion": rsi_reversion,
}


def strategy_module(key: str):
    if key and key.startswith(CUSTOM_PREFIX):
        custom = load_custom_strategy(key[len(CUSTOM_PREFIX):])
        if custom is not None:
            return custom
        return STRATEGIES[DEFAULT_STRATEGY]
    return STRATEGIES.get(key, STRATEGIES[DEFAULT_STRATEGY])


def strategy_choices() -> list[tuple[str, str]]:
    """[(key, display name), ...] for populating a UI dropdown - built-ins
    first, then any saved custom strategies from disk."""
    choices = [(key, getattr(mod, "NAME", key)) for key, mod in STRATEGIES.items()]
    for name in list_custom_strategies():
        choices.append((f"{CUSTOM_PREFIX}{name}", f"{name} (custom)"))
    return choices
