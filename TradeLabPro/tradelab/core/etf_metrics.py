"""ETF return & risk metrics — the calculation half of the ETF Screener.

This is the logic of the standalone `tools/maj_rendements.py` script, ported
into the app so the Screener panel can call it directly instead of shelling
out to a script that rewrites a spreadsheet. Behaviour is unchanged: trailing
returns over 1M/3M/6M/1A/3A/5A/10A (anything >= 1 year annualized), plus
annualized volatility, worst drawdown and Sharpe over whatever history is
available. Dividends are reinvested (adjusted close).

The rule that matters: a fund with less history than a column asks for does
not get that column written. A five-year-old ETF has no ten-year return, and
inventing one is how a fund gets picked for a decade it never lived through.

Qt-free and offline-testable — the only network call is `get_prices`.
"""
from __future__ import annotations

import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover - matches market_data.py's own guard
    yf = None

RISK_FREE = 0.03  # annual risk-free rate for Sharpe, as in maj_rendements.py

# column name -> (days back, annualize over N years or None)
PERIODS: dict[str, tuple[int, int | None]] = {
    "ret_1m":  (30,        None),
    "ret_3m":  (91,        None),
    "ret_6m":  (182,       None),
    "ret_1a":  (365,       1),
    "ret_3a":  (3 * 365,   3),
    "ret_5a":  (5 * 365,   5),
    "ret_10a": (10 * 365,  10),
}

# What a composition (a set of weights across funds) is summarised by. Each
# entry is (label, source column, kind) where kind decides the formatting:
# "pct" for a share of the book, "num" for a plain weighted average.
COMPOSITION_ROWS = [
    ("% Canada", "pct_can", "pct"),
    ("% United States", "pct_us", "pct"),
    ("% International", "pct_intl", "pct"),
    ("% Bonds", "pct_bond", "pct"),
    ("% Gold / alternatives", "pct_gold", "pct"),
    ("Average risk (1→5)", "risk", "num"),
    ("Weighted MER", "mer", "pct"),
    ("Weighted 10-year return", "ret_10a", "pct"),
]


def trailing_return(prices: pd.Series, days: int, annualize_years: int | None):
    """Total return over the trailing `days`; annualized when
    `annualize_years` is given. None when there isn't enough history (with a
    week's tolerance, so a fund that listed on a Tuesday still counts)."""
    if prices is None or prices.empty:
        return None
    end_date = prices.index[-1]
    end_price = float(prices.iloc[-1])
    target = end_date - pd.Timedelta(days=days)
    if prices.index[0] > target + pd.Timedelta(days=7):
        return None
    sub = prices[prices.index <= target]
    if sub.empty:
        return None
    start_price = float(sub.iloc[-1])
    if start_price <= 0:
        return None
    total = end_price / start_price - 1.0
    if annualize_years:
        return (1.0 + total) ** (1.0 / annualize_years) - 1.0
    return total


def risk_metrics(prices: pd.Series):
    """(annualized volatility, worst drawdown, Sharpe) over the available
    history. Any entry can be None when the history can't support it — under
    60 closes returns the empty triplet rather than a number built on a
    handful of days."""
    if prices is None or len(prices) < 60:
        return None, None, None
    daily = prices.pct_change().dropna()
    if daily.empty:
        return None, None, None
    vol = float(daily.std()) * (252 ** 0.5)
    running_max = prices.cummax()
    drawdown = prices / running_max - 1.0
    max_dd = float(drawdown.min())
    years = (prices.index[-1] - prices.index[0]).days / 365.25
    if years <= 0 or float(prices.iloc[0]) <= 0:
        return round(vol, 4), round(max_dd, 4), None
    ann_ret = (float(prices.iloc[-1]) / float(prices.iloc[0])) ** (1.0 / years) - 1.0
    sharpe = (ann_ret - RISK_FREE) / vol if vol > 0 else None
    return round(vol, 4), round(max_dd, 4), (round(sharpe, 2) if sharpe is not None else None)


def get_prices(symbol: str, period: str = "11y") -> pd.Series | None:
    """Adjusted-close series (dividends reinvested) for one Yahoo symbol.
    None on any failure — the caller skips the fund rather than writing a
    fabricated value, exactly as the script did."""
    if yf is None or not symbol:
        return None
    try:
        df = yf.download(symbol, period=period, interval="1d",
                         auto_adjust=True, progress=False, threads=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    # yfinance returns multi-indexed columns on some versions.
    if isinstance(df.columns, pd.MultiIndex):
        try:
            close = df["Close"][symbol]
        except Exception:
            close = df["Close"].iloc[:, 0]
    else:
        close = df["Close"]
    close = close.dropna()
    if close.empty:
        return None
    close.index = pd.to_datetime(close.index)
    return close.sort_index()


def compute_metrics(symbol: str, prices: pd.Series | None = None) -> dict | None:
    """Every metric for one fund, keyed by its `etf_screener` column and ready
    for `Database.etf_update_metrics()`. Pass `prices` to reuse an
    already-fetched series (and to test without a network). None when no
    usable history could be obtained at all."""
    if prices is None:
        prices = get_prices(symbol)
    if prices is None or len(prices) < 20:
        return None
    out: dict = {}
    for name, (days, ann) in PERIODS.items():
        val = trailing_return(prices, days, ann)
        if val is not None:
            out[name] = round(val, 4)
    vol, max_dd, sharpe = risk_metrics(prices)
    if vol is not None:
        out["volatility"] = vol
    if max_dd is not None:
        out["max_drawdown"] = max_dd
    if sharpe is not None:
        out["sharpe"] = sharpe
    return out or None


def _weight(fund: dict, weight_key: str) -> float:
    try:
        return float(fund.get(weight_key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def composition_summary(funds: list[dict], weight_key: str = "my_mix") -> dict:
    """What a set of weights adds up to — the workbook's "RÉSULTATS DE LA
    COMPOSITION" block, computed instead of held in spreadsheet formulas.

    Returns the total allocated, and per COMPOSITION_ROWS entry a `value` (the
    plain weighted sum, as the workbook computed it) alongside `covered` — the
    share of the allocation whose funds actually carry that column. A weighted
    ten-year return over half a book is not a ten-year return, and the caller
    is expected to say so rather than let a figure that treats the missing
    half as zero pass for the whole.
    """
    total = sum(_weight(f, weight_key) for f in funds)
    rows = {}
    for _label, column, _kind in COMPOSITION_ROWS:
        weighted = 0.0
        covered = 0.0
        for fund in funds:
            w = _weight(fund, weight_key)
            if w == 0:
                continue
            value = fund.get(column)
            if value is None or value == "":
                continue
            try:
                weighted += w * float(value)
            except (TypeError, ValueError):
                continue
            covered += w
        rows[column] = {"value": weighted, "covered": covered}
    return {"total": total, "rows": rows}
