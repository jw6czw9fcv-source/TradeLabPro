"""Backtesting Lab engine (Phase 4).

A strategy-agnostic backtest engine that works with any strategy in the
SCN-030 registry (via its signal_series), plus the three things the
roadmap calls for on top of a single-symbol run: multi-symbol aggregation,
parameter optimization, and walk-forward analysis.

Kept Qt-free and network-optional (callers can inject history) so it's
unit-testable offline, same pattern as core/confidence.py and core/market.py.
The long-only entry/exit rule (enter on BUY when flat, exit on SELL) matches
the original backtester.py so results stay comparable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from tradelab.core.indicators import add_indicators
from tradelab.strategies import strategy_module


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    metrics: dict
    equity: list = field(default_factory=list)


def _empty_metrics() -> dict:
    return {
        "Trades": 0, "Closed trades": 0, "Win rate %": 0, "Avg return %": 0,
        "Best trade %": 0, "Worst trade %": 0, "Profit factor": 0,
        "Total return %": 0, "Max drawdown %": 0,
    }


def _max_drawdown_pct(returns_pct: list[float]) -> float:
    """Worst peak-to-trough decline of the compounded equity curve, as a
    positive percent (0 = no drawdown)."""
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns_pct:
        equity *= (1 + r / 100.0)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100.0
        max_dd = max(max_dd, dd)
    return round(max_dd, 2)


def _equity_curve(returns_pct: list[float]) -> list[float]:
    equity = 100.0
    curve = [equity]
    for r in returns_pct:
        equity *= (1 + r / 100.0)
        curve.append(round(equity, 2))
    return curve


def _metrics_from_trades(trades: list[dict]) -> dict:
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        return _empty_metrics()
    closed = tdf[tdf["Exit Date"] != "OPEN"]
    if closed.empty:
        m = _empty_metrics()
        m["Trades"] = len(tdf)
        return m
    rets = closed["Return %"].tolist()
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "Trades": int(len(tdf)),
        "Closed trades": int(len(closed)),
        "Win rate %": round(len(wins) / len(closed) * 100, 1),
        "Avg return %": round(sum(rets) / len(rets), 2),
        "Best trade %": round(max(rets), 2),
        "Worst trade %": round(min(rets), 2),
        "Profit factor": round(gross_win / gross_loss, 2) if gross_loss else 999,
        "Total return %": round(sum(rets), 2),
        "Max drawdown %": _max_drawdown_pct(rets),
    }


def simulate(indicators: pd.DataFrame, cfg, strategy) -> BacktestResult:
    """Long-only trade simulation over a fully-prepared indicators frame,
    using the strategy's per-bar signal_series."""
    if indicators is None or indicators.empty:
        return BacktestResult(pd.DataFrame(), _empty_metrics(), [])
    try:
        signals = strategy.signal_series(indicators, cfg)
    except Exception:
        return BacktestResult(pd.DataFrame(), _empty_metrics(), [])

    position = None
    trades = []
    for dt, row in indicators.iterrows():
        s = signals.loc[dt] if dt in signals.index else ""
        price = float(row["Close"])
        if position is None and s == "BUY":
            position = {"Entry Date": dt, "Entry": price}
        elif position is not None and s == "SELL":
            pnl = (price - position["Entry"]) / position["Entry"] * 100
            trades.append({
                "Entry Date": str(position["Entry Date"])[:10], "Exit Date": str(dt)[:10],
                "Entry": round(position["Entry"], 2), "Exit": round(price, 2), "Return %": round(pnl, 2),
            })
            position = None
    if position is not None:
        price = float(indicators["Close"].iloc[-1])
        pnl = (price - position["Entry"]) / position["Entry"] * 100
        trades.append({
            "Entry Date": str(position["Entry Date"])[:10], "Exit Date": "OPEN",
            "Entry": round(position["Entry"], 2), "Exit": round(price, 2), "Return %": round(pnl, 2),
        })

    metrics = _metrics_from_trades(trades)
    closed_rets = [t["Return %"] for t in trades if t["Exit Date"] != "OPEN"]
    return BacktestResult(pd.DataFrame(trades), metrics, _equity_curve(closed_rets))


def _prepare(raw: pd.DataFrame, cfg) -> pd.DataFrame:
    if raw is None or raw.empty or len(raw) < 80:
        return pd.DataFrame()
    ind = add_indicators(raw, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    # Drop only rows where the actual signal inputs are still warming up
    # (EMA/MACD/RSI, ~35 bars) - NOT a blanket dropna(), which would throw
    # away the first ~199 bars just for SMA200 that no strategy signal uses,
    # crippling shorter backtests and walk-forward windows.
    signal_cols = ["Close", f"EMA{cfg.ema_fast}", f"EMA{cfg.ema_slow}",
                   "MACD", "MACD_SIGNAL", "MACD_HIST", "RSI14"]
    cols = [c for c in signal_cols if c in ind.columns]
    return ind.dropna(subset=cols)


def backtest_symbol(symbol: str, cfg, strategy_key: str | None = None) -> BacktestResult:
    from tradelab.data.market_data import get_history
    raw = get_history(symbol, cfg.period, cfg.interval)
    indicators = _prepare(raw, cfg)
    if indicators.empty:
        return BacktestResult(pd.DataFrame(), {"Error": "Not enough data"}, [])
    return simulate(indicators, cfg, strategy_module(strategy_key or cfg.strategy))


def backtest_multi(symbols: list[str], cfg, strategy_key: str | None = None,
                   progress_callback=None, should_stop=None) -> dict:
    """Run backtest_symbol across many symbols, returning a per-symbol
    summary table plus portfolio-level aggregate metrics."""
    per_symbol = []
    all_returns = []
    total = len(symbols)
    for idx, symbol in enumerate(symbols, start=1):
        if should_stop and should_stop():
            break
        try:
            res = backtest_symbol(symbol, cfg, strategy_key)
            m = res.metrics
            per_symbol.append({
                "Symbol": symbol,
                "Trades": m.get("Closed trades", 0),
                "Win rate %": m.get("Win rate %", 0),
                "Total return %": m.get("Total return %", 0),
                "Profit factor": m.get("Profit factor", 0),
                "Max drawdown %": m.get("Max drawdown %", 0),
            })
            if not res.trades.empty:
                closed = res.trades[res.trades["Exit Date"] != "OPEN"]
                all_returns.extend(closed["Return %"].tolist())
        except Exception as exc:
            per_symbol.append({"Symbol": symbol, "Trades": 0, "Win rate %": 0,
                               "Total return %": 0, "Profit factor": 0, "Max drawdown %": 0, "Error": str(exc)})
        if progress_callback:
            progress_callback(idx, total, symbol)

    wins = [r for r in all_returns if r > 0]
    aggregate = {
        "Symbols tested": len(per_symbol),
        "Total closed trades": len(all_returns),
        "Overall win rate %": round(len(wins) / len(all_returns) * 100, 1) if all_returns else 0,
        "Avg trade return %": round(sum(all_returns) / len(all_returns), 2) if all_returns else 0,
        "Max drawdown %": _max_drawdown_pct(all_returns),
    }
    return {"per_symbol": pd.DataFrame(per_symbol), "aggregate": aggregate}


def optimize(symbol: str, cfg, param: str, values: list, strategy_key: str | None = None,
             metric: str = "Total return %") -> pd.DataFrame:
    """Sweep one ScannerConfig parameter over a set of values, backtesting
    each, and return a table sorted best-first by the chosen metric. Uses a
    single history fetch, re-preparing indicators per value since params
    like ema_fast/ema_slow change the indicator columns themselves.
    """
    from copy import copy
    from tradelab.data.market_data import get_history
    raw = get_history(symbol, cfg.period, cfg.interval)
    rows = []
    for v in values:
        trial = copy(cfg)
        setattr(trial, param, v)
        indicators = _prepare(raw, trial)
        if indicators.empty:
            continue
        res = simulate(indicators, trial, strategy_module(strategy_key or cfg.strategy))
        row = {param: v}
        row.update({k: res.metrics.get(k, 0) for k in
                    ["Closed trades", "Win rate %", "Total return %", "Profit factor", "Max drawdown %"]})
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty and metric in df.columns:
        df = df.sort_values(metric, ascending=False).reset_index(drop=True)
    return df


def walk_forward(symbol: str, cfg, n_splits: int = 4, strategy_key: str | None = None) -> dict:
    """Split the history into n_splits sequential out-of-sample windows and
    backtest each separately. A strategy that only looks good on one stretch
    of history shows inconsistent per-window results here - the point of
    walk-forward vs a single full-period number.
    """
    from tradelab.data.market_data import get_history
    raw = get_history(symbol, cfg.period, cfg.interval)
    indicators = _prepare(raw, cfg)
    strat = strategy_module(strategy_key or cfg.strategy)
    rows = []
    if indicators.empty or n_splits < 1:
        return {"windows": pd.DataFrame(), "consistency": 0.0}
    n = len(indicators)
    size = n // n_splits
    if size < 30:  # windows too small to be meaningful
        return {"windows": pd.DataFrame(), "consistency": 0.0}
    for i in range(n_splits):
        start = i * size
        end = n if i == n_splits - 1 else (i + 1) * size
        window = indicators.iloc[start:end]
        res = simulate(window, cfg, strat)
        rows.append({
            "Window": i + 1,
            "From": str(window.index[0])[:10],
            "To": str(window.index[-1])[:10],
            "Trades": res.metrics.get("Closed trades", 0),
            "Win rate %": res.metrics.get("Win rate %", 0),
            "Total return %": res.metrics.get("Total return %", 0),
        })
    df = pd.DataFrame(rows)
    profitable = sum(1 for r in rows if r["Total return %"] > 0)
    consistency = round(profitable / len(rows) * 100, 1) if rows else 0.0
    return {"windows": df, "consistency": consistency}
