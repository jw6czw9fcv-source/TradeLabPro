from tradelab.core.indicators import add_indicators


def explain_symbol(symbol: str, df, cfg) -> dict:
    data = add_indicators(df, cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal).dropna()
    if data.empty:
        return {"score": 0, "summary": "Not enough data.", "parts": {}}
    last = data.iloc[-1]
    parts = {}
    parts["Trend"] = 20 if last[f"EMA{cfg.ema_fast}"] > last[f"EMA{cfg.ema_slow}"] else 5
    parts["Momentum"] = 20 if last["MACD"] > last["MACD_SIGNAL"] and last["MACD_HIST"] > 0 else 8
    rsi = float(last.get("RSI14", 50))
    parts["RSI"] = 15 if 45 <= rsi <= 70 else (8 if 35 <= rsi <= 80 else 3)
    rel_vol = float(last.get("REL_VOL", 1) or 1)
    parts["Volume"] = 15 if rel_vol >= 1.5 else (10 if rel_vol >= 1 else 5)
    adx = float(last.get("ADX14", 0) or 0)
    parts["Trend strength"] = 15 if adx >= 25 else (9 if adx >= 18 else 5)
    parts["Risk"] = 15 if last["Close"] > last.get("BB_LOWER", last["Close"]) else 5
    score = min(100, int(sum(parts.values())))
    summary = "Strong candidate" if score >= 85 else "Good watch candidate" if score >= 70 else "Neutral / needs confirmation" if score >= 50 else "Weak setup"
    return {"score": score, "summary": summary, "parts": parts}
