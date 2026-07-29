from tradelab.core.indicators import add_indicators, rsi_reversion_signal, rsi_reversion_signal_series

NAME = "RSI Mean-Reversion"


def signal_series(df, cfg):
    return rsi_reversion_signal_series(df)


def score_symbol(df, cfg) -> dict:
    data = add_indicators(df, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    signal = rsi_reversion_signal(data)
    last = data.iloc[-1]
    rsi = last.get("RSI14", 50) or 50
    score = 50
    if rsi < 20:
        score += 25
    elif rsi < 30:
        score += 15
    elif rsi < 40:
        score += 5
    if last.get("MACD_HIST", 0) > 0:
        score += 10  # momentum already turning, not just oversold
    if last["Volume"] > (last.get("VOL_AVG20", 0) or 0):
        score += 5
    if signal == "BUY":
        score += 15
    if signal == "SELL":
        score -= 25
    return {"signal": signal, "score": max(0, min(100, int(score))), "data": data}
