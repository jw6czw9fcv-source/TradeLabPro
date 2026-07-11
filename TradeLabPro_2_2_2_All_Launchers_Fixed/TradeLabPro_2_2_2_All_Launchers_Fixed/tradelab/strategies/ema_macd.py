from tradelab.core.indicators import add_indicators, crossover_signal


def score_symbol(df, cfg) -> dict:
    data = add_indicators(df, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    signal = crossover_signal(data, cfg.ema_fast, cfg.ema_slow)
    last = data.iloc[-1]
    score = 50
    if last[f"EMA{cfg.ema_fast}"] > last[f"EMA{cfg.ema_slow}"]:
        score += 20
    if last["MACD"] > last["MACD_SIGNAL"]:
        score += 15
    if last["MACD_HIST"] > 0:
        score += 10
    if last["Volume"] > (last.get("VOL_AVG20", 0) or 0):
        score += 5
    if signal == "BUY":
        score += 10
    if signal == "SELL":
        score -= 25
    return {"signal": signal, "score": max(0, min(100, int(score))), "data": data}
