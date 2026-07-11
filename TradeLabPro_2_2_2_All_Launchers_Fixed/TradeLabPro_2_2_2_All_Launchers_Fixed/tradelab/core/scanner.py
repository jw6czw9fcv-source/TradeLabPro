import pandas as pd

from tradelab.core.config import ScannerConfig
from tradelab.core.indicators import add_indicators
from tradelab.data.market_data import get_history, get_quote_meta
from tradelab.strategies.ema_macd import score_symbol


def _safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _passes_professional_filters(indicators: pd.DataFrame, cfg: ScannerConfig) -> tuple[bool, str]:
    if indicators.empty:
        return False, "No data"

    last = indicators.iloc[-1]
    close = _safe_float(last.get("Close"))
    rsi14 = _safe_float(last.get("RSI14"))
    rel_vol = _safe_float(last.get("REL_VOL"))
    atr14 = _safe_float(last.get("ATR14"))
    atr_pct = (atr14 / close * 100.0) if close > 0 else 0.0
    ema_fast_col = f"EMA{cfg.ema_fast}"
    ema_slow_col = f"EMA{cfg.ema_slow}"
    ema_fast = _safe_float(last.get(ema_fast_col))
    ema_slow = _safe_float(last.get(ema_slow_col))
    macd = _safe_float(last.get("MACD"))
    macd_signal = _safe_float(last.get("MACD_SIGNAL"))

    if rel_vol < float(cfg.min_rel_volume or 0):
        return False, "RelVol"
    if rsi14 < float(cfg.min_rsi or 0) or rsi14 > float(cfg.max_rsi or 100):
        return False, "RSI"
    if atr_pct < float(cfg.min_atr_percent or 0) or atr_pct > float(cfg.max_atr_percent or 100):
        return False, "ATR%"
    if cfg.require_ema_trend and not (ema_fast > ema_slow):
        return False, "EMA trend"
    if cfg.require_positive_macd and not (macd > macd_signal):
        return False, "MACD"
    return True, ""


def scan_symbols(symbols: list[str], cfg: ScannerConfig, progress_callback=None, should_stop=None) -> pd.DataFrame:
    rows = []
    scan_list = symbols if int(cfg.max_symbols or 0) <= 0 else symbols[: int(cfg.max_symbols)]
    total = len(scan_list)

    for idx, symbol in enumerate(scan_list, start=1):
        if should_stop and should_stop():
            break
        try:
            df = get_history(symbol, cfg.period, cfg.interval)
            if df.empty or len(df) < 60:
                if progress_callback:
                    progress_callback(idx, total, symbol, len(rows))
                continue

            indicators = add_indicators(
                df,
                ema_fast=cfg.ema_fast,
                ema_slow=cfg.ema_slow,
                macd_fast=cfg.macd_fast,
                macd_slow=cfg.macd_slow,
                macd_signal=cfg.macd_signal,
            )
            last = indicators.iloc[-1]
            price = _safe_float(last.get("Close"))
            volume = _safe_float(last.get("Volume"))
            rsi14 = _safe_float(last.get("RSI14"))
            rel_vol = _safe_float(last.get("REL_VOL"))
            atr14 = _safe_float(last.get("ATR14"))
            atr_pct = (atr14 / price * 100.0) if price > 0 else 0.0
            ema_fast = _safe_float(last.get(f"EMA{cfg.ema_fast}"))
            ema_slow = _safe_float(last.get(f"EMA{cfg.ema_slow}"))
            macd = _safe_float(last.get("MACD"))
            macd_signal = _safe_float(last.get("MACD_SIGNAL"))

            meta = get_quote_meta(symbol)
            market_cap = _safe_float(meta.get("market_cap"))

            if price < cfg.min_price or price > cfg.max_price:
                if progress_callback:
                    progress_callback(idx, total, symbol, len(rows))
                continue
            if volume < cfg.min_volume:
                if progress_callback:
                    progress_callback(idx, total, symbol, len(rows))
                continue
            if market_cap < cfg.min_market_cap:
                if progress_callback:
                    progress_callback(idx, total, symbol, len(rows))
                continue

            ok, reason = _passes_professional_filters(indicators, cfg)
            if not ok:
                if progress_callback:
                    progress_callback(idx, total, symbol, len(rows))
                continue

            result = score_symbol(indicators, cfg)
            if result["score"] < cfg.min_score:
                if progress_callback:
                    progress_callback(idx, total, symbol, len(rows))
                continue

            rows.append({
                "Symbol": symbol,
                "Signal": result["signal"],
                "Score": result["score"],
                "Price": round(price, 2),
                "Volume": int(volume),
                "RelVol": round(rel_vol, 2),
                "Market Cap": int(market_cap),
                "RSI14": round(rsi14, 1),
                "ATR%": round(atr_pct, 2),
                "EMA Trend": "Bull" if ema_fast > ema_slow else "Bear",
                "MACD": "Bull" if macd > macd_signal else "Bear",
            })
        except Exception as exc:
            rows.append({
                "Symbol": symbol,
                "Signal": "ERROR",
                "Score": 0,
                "Price": 0,
                "Volume": 0,
                "RelVol": 0,
                "Market Cap": 0,
                "RSI14": 0,
                "ATR%": 0,
                "EMA Trend": "",
                "MACD": "",
                "Error": str(exc),
            })
        if progress_callback:
            progress_callback(idx, total, symbol, len(rows))

    columns = ["Symbol", "Signal", "Score", "Price", "Volume", "RelVol", "Market Cap", "RSI14", "ATR%", "EMA Trend", "MACD"]
    return pd.DataFrame(rows).sort_values("Score", ascending=False) if rows else pd.DataFrame(columns=columns)
