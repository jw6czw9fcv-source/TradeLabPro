"""The candidate check: the facts about a fund or stock before you buy it
(Qt-free, offline-testable).

It lists what matters for a low-effort, safe REER/CELI - what it costs, how
risky it has been, how far it has fallen, what it returned, how much of it you
already own, which part of your plan it adds to, and which account suits it.
Each line is a fact with its basis; none is a verdict, and nothing here says
buy or sell.

Account placement - the rule behind it:
- A fund or stock **listed in the US** that pays dividends: in a REER (an RRSP)
  the US does not withhold tax on them - Article XXI(2) of the Canada-US tax
  treaty exempts dividends paid to a trust operated to provide retirement
  benefits, and the IRS has ruled an RRSP is one (PLR-142074-07, 2007). A CELI
  (TFSA) is not a retirement plan, so the US generally withholds 15% (the
  treaty rate for a Canadian resident) and it cannot be recovered.
- A fund **listed in Canada** that holds US stocks has the US tax withheld
  inside the fund, before it pays you - the same in either account.
- Canadian dividends are sheltered in both.
"""
from __future__ import annotations

import pandas as pd

from tradelab.core import allocation_plan as ap

CANADIAN_SUFFIXES = (".TO", ".V", ".NE", ".CN")
US_WITHHOLDING = 0.15
PER = 10_000.0   # amounts are shown per $10,000 invested


def is_us_listed(symbol: str) -> bool:
    s = str(symbol or "").upper()
    return bool(s) and not s.endswith(CANADIAN_SUFFIXES) and "." not in s


def worst_drawdown(prices: pd.Series):
    """(fall as a fraction, peak date, trough date) - the deepest drop from a
    high to a later low; None when there is too little history."""
    p = pd.to_numeric(pd.Series(prices), errors="coerce").dropna()
    if p.shape[0] < 20:
        return None
    running = p.cummax()
    dd = p / running - 1.0
    trough = dd.idxmin()
    peak = p.loc[:trough].idxmax()
    return float(dd.min()), peak, trough


def annualized_return(prices: pd.Series, years: int):
    p = pd.to_numeric(pd.Series(prices), errors="coerce").dropna()
    if p.empty:
        return None
    start = p.index[-1] - pd.DateOffset(years=years)
    if p.index[0] > start + pd.Timedelta(days=7):
        return None
    first = float(p[p.index >= start].iloc[0])
    last = float(p.iloc[-1])
    return (last / first) ** (1.0 / years) - 1.0 if first > 0 else None


def placement(symbol: str, dividend_yield: float | None) -> dict:
    """Which account suits it, on US withholding alone - see the module doc."""
    yld = dividend_yield or 0.0
    if not is_us_listed(symbol):
        return {"suits": "either",
                "text": "Listed in Canada: any US tax on what it holds is withheld inside the "
                        "fund, the same in a REER or a CELI."}
    if yld <= 0:
        return {"suits": "either",
                "text": "Listed in the US but pays no dividend: no US withholding in either account."}
    lost = PER * yld * US_WITHHOLDING
    return {"suits": "REER",
            "text": (f"Listed in the US, yield {yld:.2%}: in the REER its dividends are not taxed "
                     f"by the US (treaty, Article XXI); in the CELI about 15% is withheld for good "
                     f"- roughly ${lost:,.0f} a year per $10,000.")}


def overlap(candidate_holdings: dict, owned: dict) -> dict:
    """How much of the candidate is in companies you already own.
    `candidate_holdings` {symbol: weight} (a fund's published top holdings, or
    {symbol: 1.0} for a stock); `owned` {symbol: where you own it}."""
    shared = {s: w for s, w in (candidate_holdings or {}).items() if s.upper() in owned}
    return {"pct": sum(shared.values()) * 100.0,
            "names": sorted(shared, key=lambda s: -shared[s]),
            "covered_pct": sum((candidate_holdings or {}).values()) * 100.0}


def assess(symbol: str, prices: pd.Series | None, meta: dict | None, *,
           mer: float | None = None, mer_source: str = "", dividend_yield: float | None = None,
           holdings: dict | None = None, owned: dict | None = None,
           split: dict | None = None, account: str | None = None,
           account_rows: list | None = None) -> list:
    """The facts, as [(kind, label, text)] - kind is info / warn / ok, where
    warn only marks something worth a second look, never a "no"."""
    from tradelab.core.etf_metrics import csa_level, csa_volatility
    meta = meta or {}
    items = []
    name = meta.get("name") or symbol
    qtype = str(meta.get("quote_type") or "").upper()
    single = qtype == "EQUITY"
    items.append(("info", "What it is",
                  f"{name} - {'a single company' if single else 'a fund'}"
                  + (f", {meta.get('sector')}" if meta.get("sector") not in (None, "", "Unknown") else "")
                  + "."))

    # Cost.
    if single:
        items.append(("ok", "Fees", "A stock has no management fee (only the trade's commission)."))
    elif mer is not None:
        items.append(("warn" if mer > 0.005 else "ok", "Fees",
                      f"MER {mer:.2%}" + (f" ({mer_source})" if mer_source else "")
                      + f" - ${PER * mer:,.0f} a year per $10,000"
                      + (", high for an index fund." if mer > 0.005 else ".")))
    else:
        items.append(("warn", "Fees", "Not on file - add the fund to the ETF Screener with its MER, "
                                      "or read it on its fact sheet."))

    # Risk and history.
    if prices is None or pd.Series(prices).dropna().shape[0] < 60:
        items.append(("warn", "History", "Too little price history to measure risk or returns."))
    else:
        stdev, months = csa_volatility(prices)
        if stdev is not None:
            band = csa_level(stdev)
            items.append(("warn" if band in ("Medium to high", "High") else "info", "Risk",
                          f"Yearly swings {stdev:.1%} over {months} months - CSA band \"{band}\""
                          + (" (a single stock; the bands are for funds)." if single else ".")))
        dd = worst_drawdown(prices)
        if dd:
            fall, peak, trough = dd
            items.append(("warn" if fall < -0.30 else "info", "Worst fall",
                          f"{fall:.0%} from {peak:%b %Y} to {trough:%b %Y} - $10,000 would have "
                          f"dropped to ${PER * (1 + fall):,.0f}."))
        parts = []
        for years in (1, 5, 10):
            r = annualized_return(prices, years)
            if r is not None:
                parts.append(f"{years} yr {r:+.1%}")
        if parts:
            items.append(("info", "Returns", "Per year, dividends included: " + ", ".join(parts)
                          + ". The past says nothing sure about the future."))

    # Concentration and overlap.
    if single:
        items.append(("warn", "Spread", "One company: its own setbacks are not spread out."))
    if holdings:
        o = overlap(holdings, owned or {})
        if o["names"]:
            items.append(("warn" if o["pct"] >= 20 else "info", "Overlap",
                          f"{o['pct']:.0f}% of it is in companies you already own ("
                          + ", ".join(o["names"][:5]) + ")"
                          + (f" - of the {o['covered_pct']:.0f}% its top holdings cover."
                             if not single and o["covered_pct"] < 99 else ".")))
        else:
            items.append(("ok", "Overlap", "None of its top holdings are already in your portfolios."))

    # Plan fit.
    if split:
        adds = ", ".join(f"{k} {v:.0%}" for k, v in split.items()) if len(split) > 1 else next(iter(split))
        fit = f"It adds to {adds}."
        kind = "info"
        rows = {r["class"]: r for r in account_rows or []}
        for cls in split:
            row = rows.get(cls)
            if row and account:
                gap = row["drift_pp"]
                if gap > ap.DRIFT_PP:
                    fit += (f" In {account}, {cls} is already {gap:.0f} points over your target.")
                    kind = "warn"
                elif gap < -ap.DRIFT_PP:
                    fit += (f" In {account}, {cls} is {-gap:.0f} points under your target - "
                            f"this moves it toward the target.")
                    kind = "ok"
        if account and not account_rows:
            fit += f" {account} has no target mix yet (Plan tab)."
        items.append((kind, "Your plan", fit))

    # Account.
    place = placement(symbol, dividend_yield)
    kind = "info"
    if account and place["suits"] == "REER" and "REER" not in account.upper() \
            and "RRSP" not in account.upper():
        kind = "warn"
    items.append((kind, "Account", place["text"]))
    return items
