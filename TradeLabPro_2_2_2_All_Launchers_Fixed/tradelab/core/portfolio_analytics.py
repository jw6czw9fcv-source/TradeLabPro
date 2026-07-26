"""Portfolio analytics (Qt-free, offline-testable).

Turns a list of holdings (symbol / shares / entry price) plus already-fetched
price history into the numbers a trader reviews about a *book* rather than a
single trade: current value and unrealized P&L per holding, how concentrated the
book is, and its risk profile over the history window — beta vs a benchmark,
annualized volatility, max drawdown, total return vs the benchmark, and the
correlation between holdings.

Pure and network-free: callers pass in histories (a dict of symbol -> OHLCV
DataFrame) and an optional benchmark frame, the same pattern as core/market.py,
core/coach.py and core/seasonality.py, so it's unit-testable offline.
"""
from __future__ import annotations

import pandas as pd

TRADING_DAYS = 252


def _close(df) -> pd.Series | None:
    """Numeric close series with a DatetimeIndex, or None. Mirrors the guard in
    seasonality/market: collapse a duplicated 2-D 'Close' and coerce the index to
    datetime so the alignment below can't blow up."""
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        return None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    if close.empty:
        return None
    if not isinstance(close.index, pd.DatetimeIndex):
        close.index = pd.to_datetime(close.index, errors="coerce")
        close = close[close.index.notna()]
    return close if not close.empty else None


# Native trading currency inferred from a Yahoo exchange suffix (US = no suffix).
_CCY_BY_SUFFIX = {
    ".TO": "CAD", ".V": "CAD", ".NE": "CAD", ".CN": "CAD",
    ".L": "GBP", ".DE": "EUR", ".F": "EUR", ".PA": "EUR", ".AS": "EUR",
    ".MI": "EUR", ".MC": "EUR", ".VI": "EUR", ".SW": "CHF",
    ".AX": "AUD", ".HK": "HKD", ".T": "JPY", ".SI": "SGD", ".SG": "EUR",
}


def currency_of(symbol: str) -> str:
    """Native trading currency of a Yahoo symbol, from its exchange suffix.
    Bare symbols (US listings) are USD."""
    s = str(symbol or "").upper()
    for suf, ccy in _CCY_BY_SUFFIX.items():
        if s.endswith(suf):
            return ccy
    return "USD"


def fx_pair_symbol(currency: str, target: str) -> str:
    """Yahoo FX symbol converting `currency` into `target`, e.g. USD->CAD is
    'USDCAD=X' (its price is how many CAD one unit of `currency` buys)."""
    return f"{str(currency).upper()}{str(target).upper()}=X"


def _rate_series(fx, cur, target, index):
    """FX rate series (cur -> target) aligned to `index`, or None if no
    conversion is needed or possible."""
    if not target or cur == target or not fx:
        return None
    rate = fx.get(cur)
    if rate is None:
        return None
    s = _close(rate) if not isinstance(rate, pd.Series) else pd.to_numeric(rate, errors="coerce").dropna()
    if s is None or s.empty:
        return None
    return s.reindex(index).ffill().bfill()


def _latest_rate(fx, cur, target):
    """Latest FX rate cur -> target: 1.0 when no conversion is needed, None when
    it's needed but unavailable (so the caller can flag it)."""
    if not target or cur == target:
        return 1.0
    if not fx or fx.get(cur) is None:
        return None
    s = fx.get(cur)
    s = _close(s) if not isinstance(s, pd.Series) else pd.to_numeric(s, errors="coerce").dropna()
    if s is None or s.empty:
        return None
    v = float(s.iloc[-1])
    return v if v == v else None


def aggregate_positions(positions: list) -> list:
    """Merge rows that share a symbol into one holding, summing shares and
    cost-weighting the entry price (a book can hold the same name in several
    portfolios / lots)."""
    agg: dict[str, dict] = {}
    for p in positions:
        sym = str(p.get("symbol", "")).upper().strip()
        if not sym:
            continue
        shares = float(p.get("shares", 0) or 0)
        entry = float(p.get("entry_price", p.get("entry", 0)) or 0)
        a = agg.setdefault(sym, {"symbol": sym, "shares": 0.0, "cost_basis": 0.0})
        a["shares"] += shares
        a["cost_basis"] += shares * entry
    out = []
    for a in agg.values():
        sh = a["shares"]
        out.append({"symbol": a["symbol"], "shares": sh, "cost_basis": a["cost_basis"],
                    "avg_entry": (a["cost_basis"] / sh) if sh else 0.0})
    return out


def _closes_frame(histories: dict) -> pd.DataFrame:
    """A wide close-price frame (one column per symbol) from a histories dict."""
    cols = {}
    for sym, df in (histories or {}).items():
        c = _close(df)
        if c is not None and not c.empty:
            cols[str(sym).upper()] = c
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def holdings(positions: list, histories: dict, target: str = None, fx: dict = None):
    """Per-holding valuation: last price, market value, unrealized P&L (vs the
    real entry price), and weight of the book. Returns (rows, total_value), rows
    sorted largest position first.

    This mirrors how an IBKR CAD account displays a mixed book: **per-share prices
    (last, avg entry) stay in each holding's native currency**, while the **dollar
    aggregates (market value, cost basis, unrealized P&L) are reported in the
    target currency** (e.g. CAD), converting the native amounts via `fx` (a dict
    currency -> rate series into the target) at the current rate. The unrealized %
    is the native price move and is unaffected by FX. Each row carries `currency`
    (the native trading currency), `avg_entry` and `last` (native), and
    `converted` (False if conversion was needed but no FX rate was available)."""
    agg = aggregate_positions(positions)
    rows = []
    for a in agg:
        c = _close((histories or {}).get(a["symbol"]))
        cur = currency_of(a["symbol"])
        rate = _latest_rate(fx, cur, target)
        converted = target is None or cur == target or rate is not None
        conv = rate if rate is not None else 1.0
        last_native = float(c.iloc[-1]) if c is not None and not c.empty else None  # display: native
        mv = last_native * a["shares"] * conv if last_native is not None else None  # value in target
        cost = a["cost_basis"] * conv                                               # cost in target
        pnl = (mv - cost) if mv is not None else None
        pnl_pct = (pnl / cost * 100.0) if (pnl is not None and cost) else None
        rows.append({**a, "cost_basis": cost, "currency": cur, "converted": converted,
                     "last": last_native, "market_value": mv,
                     "unrealized": pnl, "unrealized_pct": pnl_pct})
    total = sum(h["market_value"] for h in rows if h["market_value"])
    for h in rows:
        h["weight_pct"] = (h["market_value"] / total * 100.0) if (h["market_value"] and total) else None
    rows.sort(key=lambda h: (h["market_value"] or 0), reverse=True)
    return rows, total


def _converted_close(symbol: str, histories: dict, target: str, fx: dict):
    """A holding's close series, converted to `target` currency over time using
    the FX rate series (so the equity curve reflects FX moves too)."""
    c = _close((histories or {}).get(symbol))
    if c is None or c.empty:
        return None
    rate = _rate_series(fx, currency_of(symbol), target, c.index)
    return (c * rate) if rate is not None else c


def portfolio_equity(positions: list, histories: dict, target: str = None,
                     fx: dict = None) -> pd.Series:
    """The book's daily market-value curve: sum over holdings of shares x close,
    on the dates every valued holding has in common (inner join). This is the
    real equity curve given the share counts, so drawdown and volatility are
    exact. With `target`/`fx`, each holding is converted to the target currency
    (time-varying) before summing, so a mixed CAD/USD book is valued in one
    currency."""
    shares = {a["symbol"]: a["shares"] for a in aggregate_positions(positions)}
    cols = {}
    for sym, sh in shares.items():
        c = _converted_close(sym, histories, target, fx)
        if c is not None and not c.empty:
            cols[sym] = c * sh
    if not cols:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(cols).dropna()          # intersection of dates
    return frame.sum(axis=1) if not frame.empty else pd.Series(dtype=float)


def daily_returns(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    return series.pct_change().dropna()


def max_drawdown(equity: pd.Series):
    """Largest peak-to-trough drop of the equity curve, as a negative %."""
    if equity is None or equity.empty:
        return None
    dd = equity / equity.cummax() - 1.0
    return float(dd.min() * 100.0)


def annualized_vol(returns: pd.Series):
    """Annualized volatility (%) from daily returns."""
    if returns is None or returns.shape[0] < 2:
        return None
    v = float(returns.std() * (TRADING_DAYS ** 0.5) * 100.0)
    return v if v == v else None


def total_return(series: pd.Series):
    if series is None or series.shape[0] < 2 or series.iloc[0] == 0:
        return None
    return float((series.iloc[-1] / series.iloc[0] - 1.0) * 100.0)


def cagr(equity: pd.Series):
    """Compound annual growth rate (%) of the equity curve over its span."""
    if equity is None or equity.shape[0] < 2 or equity.iloc[0] <= 0:
        return None
    days = (equity.index[-1] - equity.index[0]).days
    if days <= 0:
        return None
    years = days / 365.25
    return float(((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0) * 100.0)


def beta(port_returns: pd.Series, bench_returns: pd.Series):
    """Portfolio beta vs the benchmark: cov(port, bench) / var(bench) over the
    dates they share. ~1 moves with the market, <1 is defensive, >1 amplifies."""
    if port_returns is None or bench_returns is None:
        return None
    df = pd.concat([port_returns.rename("p"), bench_returns.rename("b")], axis=1).dropna()
    if df.shape[0] < 2:
        return None
    var = float(df["b"].var())
    if not var:
        return None
    return float(df["p"].cov(df["b"]) / var)


def concentration(rows: list) -> dict:
    """How concentrated the book is: the biggest position, the top-3 share, and
    the Herfindahl index with its 'effective number of positions' (1/HHI) — a
    book split evenly across 5 names has an effective N of 5; one dominated by a
    single name is far lower."""
    weights = [h["weight_pct"] / 100.0 for h in rows if h.get("weight_pct")]
    if not weights:
        return {"largest_pct": None, "top3_pct": None, "hhi": None,
                "effective_n": None, "positions": 0}
    ordered = sorted(weights, reverse=True)
    hhi = sum(w * w for w in weights)
    return {
        "largest_pct": max(weights) * 100.0,
        "top3_pct": sum(ordered[:3]) * 100.0,
        "hhi": hhi,
        "effective_n": (1.0 / hhi) if hhi else None,
        "positions": len(weights),
    }


def correlation(histories: dict) -> dict:
    """Correlation of daily returns between holdings, plus the average pairwise
    correlation (a quick 'how diversified is this book?' number — low/negative is
    diversified, near 1 means everything moves together)."""
    rets = _closes_frame(histories).dropna().pct_change().dropna()
    syms = list(rets.columns)
    if len(syms) < 2 or rets.empty:
        return {"symbols": syms, "matrix": [], "avg_pairwise": None}
    corr = rets.corr()
    matrix = [[round(float(corr.loc[a, b]), 2) for b in syms] for a in syms]
    pairs = [float(corr.loc[a, b]) for i, a in enumerate(syms)
             for j, b in enumerate(syms) if i < j]
    avg = (sum(pairs) / len(pairs)) if pairs else None
    return {"symbols": syms, "matrix": matrix, "avg_pairwise": avg}


def summarize(positions: list, histories: dict, benchmark_df=None,
              benchmark_symbol: str = "SPY", target_currency: str = None,
              fx: dict = None) -> dict:
    """Everything the Portfolio Analytics tab renders, computed offline. When
    `target_currency` (e.g. "CAD") and `fx` are supplied, all money is reported
    in that currency; otherwise values are in each holding's native currency
    (the legacy mixed-currency behaviour)."""
    target = target_currency
    rows, total_mv = holdings(positions, histories, target, fx)
    total_cost = sum(h["cost_basis"] for h in rows)
    # Correlation is between the user's holdings only — never the benchmark.
    hold_hist = {h["symbol"]: histories.get(h["symbol"]) for h in rows
                 if (histories or {}).get(h["symbol"]) is not None}
    equity = portfolio_equity(positions, histories, target, fx)
    pr = daily_returns(equity)

    br, bench_total = None, None
    if benchmark_df is not None and not equity.empty:
        bc = _close(benchmark_df)
        if bc is not None and not bc.empty:
            brate = _rate_series(fx, currency_of(benchmark_symbol), target, bc.index)
            if brate is not None:
                bc = bc * brate            # benchmark in target currency too
            bc = bc.reindex(equity.index).dropna()
            br = daily_returns(bc)
            bench_total = total_return(bc)

    # Per-holding: the stock's return over the window and how it compares to the
    # benchmark over the SAME dates (each holding aligned to the benchmark
    # separately, so a holding with less history is still compared fairly).
    bench_full = None
    if benchmark_df is not None:
        bfc = _close(benchmark_df)
        if bfc is not None and not bfc.empty:
            r = _rate_series(fx, currency_of(benchmark_symbol), target, bfc.index)
            bench_full = (bfc * r) if r is not None else bfc
    for h in rows:
        sc = _converted_close(h["symbol"], histories, target, fx)
        h["window_return_pct"] = total_return(sc) if sc is not None else None
        h["vs_benchmark_pct"] = None
        if bench_full is not None and sc is not None and not sc.empty:
            aligned = pd.concat([sc, bench_full], axis=1).dropna()
            if aligned.shape[0] >= 2:
                sr = aligned.iloc[-1, 0] / aligned.iloc[0, 0] - 1.0
                bnr = aligned.iloc[-1, 1] / aligned.iloc[0, 1] - 1.0
                h["vs_benchmark_pct"] = (sr - bnr) * 100.0

    # Unrealized P&L must compare like with like: only the cost of holdings that
    # actually have a market value. Including an unpriced holding's cost would
    # silently understate the P&L whenever one symbol has no data.
    priced = [h for h in rows if h["market_value"] is not None]
    priced_cost = sum(h["cost_basis"] for h in priced)
    unreal = (total_mv - priced_cost) if priced else None

    # Window truncation: the equity curve only spans dates ALL holdings share,
    # so one short-history holding shortens the whole analysis. Name the culprit
    # when it cuts more than ~10% off the longest holding's span.
    window_limited_by = None
    if equity.shape[0] >= 2:
        starts = {}
        for h in rows:
            sc = _close((histories or {}).get(h["symbol"]))
            if sc is not None and sc.shape[0] >= 2:
                starts[h["symbol"]] = sc.index[0]
        if len(starts) >= 2:
            earliest = min(starts.values())
            full_days = (equity.index[-1] - earliest).days
            eq_days = (equity.index[-1] - equity.index[0]).days
            if full_days > 0 and eq_days < 0.9 * full_days:
                window_limited_by = max(starts, key=lambda s: starts[s])

    result = {
        "holdings": rows,
        "total_value": total_mv,
        "total_cost": total_cost,
        "total_unrealized": unreal,
        "total_unrealized_pct": (unreal / priced_cost * 100.0) if (unreal is not None and priced_cost) else None,
        "beta": beta(pr, br),
        "ann_vol_pct": annualized_vol(pr),
        "max_drawdown_pct": max_drawdown(equity),
        "total_return_pct": total_return(equity),
        "cagr_pct": cagr(equity),
        "benchmark_symbol": benchmark_symbol,
        "benchmark_return_pct": bench_total,
        "concentration": concentration(rows),
        "correlation": correlation(hold_hist),
        "window_days": int((equity.index[-1] - equity.index[0]).days) if equity.shape[0] >= 2 else 0,
        "window_limited_by": window_limited_by,
        # Holdings that had no usable price data (shown as "—" in the table).
        "no_data": sorted(h["symbol"] for h in rows if h["market_value"] is None),
        "equity": equity,
        "currency": target,
        # Currencies that needed converting to the target but had no FX rate.
        "fx_missing": sorted({h["currency"] for h in rows
                              if target and not h["converted"]}),
    }
    result["text"] = _summary_text(result)
    return result


def _summary_text(r: dict) -> str:
    if not r["holdings"]:
        return "No positions yet — add holdings in the Portfolio tab, then refresh."
    n = r["concentration"]["positions"]
    ccy = f" {r['currency']}" if r.get("currency") else ""
    parts = [f"{n} position(s) worth ${r['total_value']:,.0f}{ccy}"]
    if r["total_unrealized"] is not None:
        seg = f"unrealized {r['total_unrealized']:+,.0f}"
        if r["total_unrealized_pct"] is not None:      # None when cost basis is 0
            seg += f" ({r['total_unrealized_pct']:+.1f}%)"
        parts.append(seg)
    if r["beta"] is not None:
        parts.append(f"beta {r['beta']:.2f} vs {r['benchmark_symbol']}")
    if r["max_drawdown_pct"] is not None:
        parts.append(f"max drawdown {r['max_drawdown_pct']:.1f}%")
    avg = r["correlation"]["avg_pairwise"]
    if avg is not None:
        shape = "well diversified" if avg < 0.3 else ("moderately correlated" if avg < 0.6 else "highly correlated")
        parts.append(f"holdings are {shape} (avg pairwise correlation {avg:.2f})")
    return " · ".join(parts) + "."
