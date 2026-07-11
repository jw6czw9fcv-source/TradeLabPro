from dataclasses import dataclass
import pandas as pd
from tradelab.core.config import ScannerConfig
from tradelab.core.indicators import add_indicators, signal_series
from tradelab.data.market_data import get_history

@dataclass
class BacktestResult:
    trades: pd.DataFrame
    metrics: dict


def backtest_ema_macd(symbol: str, cfg: ScannerConfig, initial_cash: float = 10000.0) -> BacktestResult:
    raw = get_history(symbol, cfg.period, cfg.interval)
    if raw.empty or len(raw) < 80:
        return BacktestResult(pd.DataFrame(), {"Error": "Not enough data"})
    df = add_indicators(raw, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal).dropna()
    sig = signal_series(df, cfg.ema_fast, cfg.ema_slow)
    position = None
    trades = []
    for dt, row in df.iterrows():
        s = sig.loc[dt]
        price = float(row["Close"])
        if position is None and s == "BUY":
            position = {"Entry Date": dt, "Entry": price}
        elif position is not None and s == "SELL":
            pnl_pct = (price - position["Entry"]) / position["Entry"] * 100
            trades.append({
                "Entry Date": str(position["Entry Date"])[:10],
                "Exit Date": str(dt)[:10],
                "Entry": round(position["Entry"], 2),
                "Exit": round(price, 2),
                "Return %": round(pnl_pct, 2),
            })
            position = None
    if position is not None:
        price = float(df["Close"].iloc[-1])
        pnl_pct = (price - position["Entry"]) / position["Entry"] * 100
        trades.append({
            "Entry Date": str(position["Entry Date"])[:10],
            "Exit Date": "OPEN",
            "Entry": round(position["Entry"], 2),
            "Exit": round(price, 2),
            "Return %": round(pnl_pct, 2),
        })
    tdf = pd.DataFrame(trades)
    closed = tdf[tdf["Exit Date"] != "OPEN"] if not tdf.empty else tdf
    if closed.empty:
        return BacktestResult(tdf, {"Trades": len(tdf), "Closed trades": 0, "Win rate %": 0, "Avg return %": 0, "Profit factor": 0})
    wins = closed[closed["Return %"] > 0]
    losses = closed[closed["Return %"] <= 0]
    gross_win = wins["Return %"].sum()
    gross_loss = abs(losses["Return %"].sum())
    metrics = {
        "Trades": int(len(tdf)),
        "Closed trades": int(len(closed)),
        "Win rate %": round(len(wins) / len(closed) * 100, 1),
        "Avg return %": round(closed["Return %"].mean(), 2),
        "Best trade %": round(closed["Return %"].max(), 2),
        "Worst trade %": round(closed["Return %"].min(), 2),
        "Profit factor": round(gross_win / gross_loss, 2) if gross_loss else 999,
        "Total return %": round(closed["Return %"].sum(), 2),
    }
    return BacktestResult(tdf, metrics)
