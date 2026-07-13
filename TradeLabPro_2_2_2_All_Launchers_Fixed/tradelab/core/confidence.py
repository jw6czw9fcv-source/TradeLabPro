"""Transparent confidence scoring tied to backtest stats (SCN-030, third
piece of Phase 2's "multi-strategy scanning, sector/market-cap context,
transparent confidence scoring tied to backtest stats").

The existing per-symbol Score is a fixed heuristic point system (see
strategies/ema_macd.py, strategies/rsi_reversion.py) - it doesn't tell you
whether this strategy's past signals on this symbol actually worked.
Confidence does: of this strategy's historical BUY signals in the already-
fetched price window, what fraction were profitable a fixed horizon later?
Reuses the indicators DataFrame scan_symbols() already computed - no extra
network fetch, no trade-simulation loop - so it stays fast enough to run
inline during a scan instead of requiring a separate backtest pass.
"""
from __future__ import annotations

import pandas as pd


def historical_confidence(indicators: pd.DataFrame, strategy_module, cfg, horizon: int = 10) -> dict:
    try:
        signals = strategy_module.signal_series(indicators, cfg)
    except Exception:
        return {"confidence": None, "sample_size": 0, "avg_forward_return": None}

    closes = indicators["Close"].to_numpy()
    signal_values = signals.to_numpy()
    n = len(indicators)

    forward_returns = []
    for i in range(n - horizon):
        if signal_values[i] != "BUY":
            continue
        entry = closes[i]
        if not entry:
            continue
        exit_price = closes[i + horizon]
        forward_returns.append((exit_price - entry) / entry * 100.0)

    if not forward_returns:
        return {"confidence": None, "sample_size": 0, "avg_forward_return": None}

    wins = sum(1 for r in forward_returns if r > 0)
    return {
        "confidence": round(wins / len(forward_returns) * 100.0, 1),
        "sample_size": len(forward_returns),
        "avg_forward_return": round(sum(forward_returns) / len(forward_returns), 2),
    }
