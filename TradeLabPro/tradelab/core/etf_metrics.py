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


# A fund whose largest published holding is at least this much of it is a
# wrapper around something else (VFV.TO is VOO.TO at 100%), and stopping there
# tells you nothing. Only these get a second lookup: opening every holding of
# every fund would be hundreds of requests for names that are already
# companies. Deliberately high — a fund with 60% in one name is concentrated,
# not a wrapper, and treating it as one would fetch it for no reason.
PASS_THROUGH_WEIGHT = 0.9


def pass_through_symbols(compositions: dict, min_weight: float = PASS_THROUGH_WEIGHT) -> list:
    """Holdings big enough inside their parent to be worth opening up in turn.

    Returns symbols that are held at `min_weight` or more of some fund and
    whose own composition we don't have yet — the second level of a
    look-through, kept to one extra request per fund.
    """
    known = set(compositions or {})
    found = set()
    for _symbol, composition in (compositions or {}).items():
        for held, weight in ((composition or {}).get("top_holdings") or {}).items():
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                continue
            if weight >= min_weight and held not in known:
                found.add(held)
    return sorted(found)


def expand_compositions(compositions: dict) -> dict:
    """Fold a fund-of-funds down a level.

    VFV.TO publishes exactly one holding: VOO.TO, at 100%. Looked through once,
    the answer is "you own VOO.TO", which is true and useless. Where a holding
    has its own published composition, its weight is distributed across what
    *it* holds.

    The part a nested fund does not publish stays attributed to that fund
    rather than being spread over the names it does publish — same rule as the
    single-level look-through, so every company weight stays a floor.
    """
    expanded = {}
    for symbol, composition in (compositions or {}).items():
        holdings = (composition or {}).get("top_holdings") or {}
        out = {}
        for held, weight in holdings.items():
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                continue
            inner = ((compositions or {}).get(held) or {}).get("top_holdings") or {}
            if not inner or held == symbol:
                out[held] = out.get(held, 0.0) + weight
                continue
            covered = 0.0
            for deep, deep_weight in inner.items():
                try:
                    deep_weight = float(deep_weight)
                except (TypeError, ValueError):
                    continue
                out[deep] = out.get(deep, 0.0) + weight * deep_weight
                covered += deep_weight
            rest = weight * max(0.0, 1.0 - covered)
            if rest > 0:
                out[held] = out.get(held, 0.0) + rest
        expanded[symbol] = {**(composition or {}), "top_holdings": out}
    return expanded


# Default for the low-volatility flag, in annualized volatility. Not a
# recommendation and not a rating: it is one number the person picks, applied
# to the volatility the Screener already measured.
LOW_VOL_THRESHOLD = 0.12


def is_low_volatility(fund: dict, threshold: float = LOW_VOL_THRESHOLD):
    """True / False / None for "this fund's measured volatility is at or below
    `threshold`".

    **None means not measured yet**, and is deliberately not False: a fund that
    has never been refreshed is unknown, not volatile, and reporting it as
    failing the test would be an answer the data can't support.
    """
    value = (fund or {}).get("volatility")
    if value is None or value == "":
        return None
    try:
        return float(value) <= float(threshold)
    except (TypeError, ValueError):
        return None


def rebased_series(histories: dict, base: float = 100.0) -> dict:
    """Several funds on one scale: each restated to `base` at the first date
    they all share.

    Funds trade at unrelated prices — one unit of VFV is $150, one unit of MNT
    is $40 — so plotting them raw is a set of lines at different altitudes and
    no comparison at all. Rebasing from a *common* start is what makes the
    laggard the line at the bottom; rebasing each from its own first bar would
    silently compare different periods.
    """
    closes = {}
    for symbol, df in (histories or {}).items():
        if df is None:
            continue
        series = df["Close"] if hasattr(df, "columns") and "Close" in getattr(df, "columns", []) else df
        try:
            series = series.dropna()
        except AttributeError:
            continue
        if series is None or len(series) < 2:
            continue
        closes[symbol] = series
    if not closes:
        return {}

    start = max(series.index[0] for series in closes.values())
    out = {}
    for symbol, series in closes.items():
        window = series[series.index >= start]
        if len(window) < 2:
            continue
        first = float(window.iloc[0])
        if first <= 0:
            continue
        out[symbol] = {
            "dates": list(window.index),
            "values": [float(v) / first * base for v in window],
        }
    return out


def fund_symbol(fund: dict) -> str:
    """The symbol a fund is priced and held under — the Yahoo listing when
    there is one, since VFV.TO is what a Canadian book actually holds and VFV
    is a different security."""
    return str(fund.get("yahoo") or fund.get("ticker") or "").strip().upper()


def rebalance(funds: list[dict], holding_rows: list[dict], weight_key: str = "my_mix") -> dict:
    """A target allocation against the book actually held.

    `holding_rows` is `portfolio_analytics.holdings()` output — symbol plus
    `market_value` already converted to the display currency. Matching is by
    the fund's Yahoo symbol.

    Percentages are of the **whole book**, not of the part the plan describes,
    and `unmatched` names the holdings the plan says nothing about. A target
    measured only against the funds it happens to mention would report a book
    as on-plan while half of it sat in something the plan never mentioned.
    """
    held = {}
    for row in holding_rows or []:
        symbol = str(row.get("symbol", "")).strip().upper()
        value = row.get("market_value")
        if symbol and value:
            held[symbol] = held.get(symbol, 0.0) + float(value)
    total = sum(held.values())

    rows, matched_value = [], 0.0
    for fund in funds:
        target = _weight(fund, weight_key)
        symbol = fund_symbol(fund)
        value = held.get(symbol, 0.0)
        if not target and not value:
            continue
        matched_value += value
        actual = (value / total) if total else 0.0
        rows.append({
            "ticker": fund.get("ticker", ""),
            "symbol": symbol,
            "target_pct": target,
            "actual_pct": actual,
            "drift_pct": actual - target,
            "market_value": value,
            # Positive = buy this much to reach the target, negative = trim.
            "amount": (target * total) - value if total else 0.0,
        })
    rows.sort(key=lambda r: abs(r["drift_pct"]), reverse=True)
    unmatched = sorted(s for s in held if s not in {r["symbol"] for r in rows})
    return {
        "rows": rows,
        "total": total,
        "covered": (matched_value / total) if total else 0.0,
        "unmatched": unmatched,
    }


# Two funds whose asset mixes differ by less than this (summed absolute
# difference across the five buckets) are treated as the same exposure. 0.10
# keeps VCN/XIC and VIU/XEF together without merging VFV and VGT.
OVERLAP_TOLERANCE = 0.10
_MIX_COLUMNS = ("pct_can", "pct_us", "pct_intl", "pct_bond", "pct_gold")


def _mix(fund: dict) -> list[float] | None:
    values = []
    for column in _MIX_COLUMNS:
        value = fund.get(column)
        if value is None or value == "":
            return None
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            return None
    return values


def overlaps(funds: list[dict], weight_key: str = "my_mix",
             tolerance: float = OVERLAP_TOLERANCE) -> list[dict]:
    """Pairs of funds in one allocation that buy the same thing twice.

    Holding VCN and XIC together is not diversification — it is the Canadian
    market at twice the trading cost. This flags pairs that both carry weight
    and whose published asset mix is the same within `tolerance`, saying which
    test caught them. It compares what the table knows; a pair with no mix
    filled in is compared on category alone, and a pair with neither is not
    guessed at.
    """
    weighted = [f for f in funds if _weight(f, weight_key) > 0]
    found = []
    for i, a in enumerate(weighted):
        for b in weighted[i + 1:]:
            mix_a, mix_b = _mix(a), _mix(b)
            distance = None
            if mix_a is not None and mix_b is not None:
                distance = sum(abs(x - y) for x, y in zip(mix_a, mix_b))
            same_category = bool(a.get("category")) and a.get("category") == b.get("category")
            if distance is not None and distance <= tolerance:
                reason = ("same category and near-identical mix" if same_category
                          else "near-identical asset mix")
            elif distance is None and same_category:
                reason = "same category"
            else:
                continue
            found.append({
                "a": a.get("ticker", ""), "b": b.get("ticker", ""),
                "reason": reason, "distance": distance,
                "combined_weight": _weight(a, weight_key) + _weight(b, weight_key),
            })
    found.sort(key=lambda o: o["combined_weight"], reverse=True)
    return found


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
