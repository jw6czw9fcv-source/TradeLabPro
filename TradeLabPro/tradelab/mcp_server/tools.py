"""What TradeLab Pro offers an AI assistant over MCP - read-only, Qt-free.

Each function answers one question from the data the app stored and with the
calculations its own tabs use, and returns plain JSON-able data. None of them
writes: the database is opened in SQLite's read-only mode, so a write would be
refused by the engine itself; the journal and preferences are only read; and
there is no order of any kind anywhere in TradeLab to place.

This file only gathers inputs and calls tradelab.core, the way a tab's worker
does - the rules themselves live in core, once. It is separate from server.py
so it can be tested without the MCP library installed.
"""
from __future__ import annotations

import math
from datetime import date, datetime

NOT_ADVICE = ("Calculations on your own figures and assumptions - not financial "
              "advice, and not a forecast.")

# Series longer than this are summarised rather than sent point by point: a
# year of daily values is noise to a reader and floods the conversation.
_MAX_SERIES_POINTS = 60


class ToolError(Exception):
    """Something the person can act on, said plainly - not a traceback."""


# -- turning results into JSON ----------------------------------------------------

def jsonable(obj):
    """Plain JSON types all the way down. NaN and infinities become None - a
    missing figure must read as missing, never as a number."""
    import numpy as np
    import pandas as pd

    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, np.generic):
        return jsonable(obj.item())
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, pd.Series):
        if len(obj) > _MAX_SERIES_POINTS:
            clean = obj.dropna()
            return {"points": int(len(obj)),
                    "first": jsonable(clean.iloc[0]) if len(clean) else None,
                    "last": jsonable(clean.iloc[-1]) if len(clean) else None,
                    "from": jsonable(clean.index[0]) if len(clean) else None,
                    "to": jsonable(clean.index[-1]) if len(clean) else None}
        return {str(jsonable(k)): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, pd.DataFrame):
        if len(obj) > _MAX_SERIES_POINTS:
            return {"rows": int(len(obj)), "columns": [str(c) for c in obj.columns]}
        return jsonable(obj.reset_index().to_dict("records"))
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return jsonable({k: v for k, v in vars(obj).items() if not k.startswith("_")})
    return str(obj)


# -- reading what the app stored -----------------------------------------------------

def open_database():
    """The app's database, read-only. Fails with something actionable when
    there is nothing to read yet or the file predates this code."""
    from tradelab.core import config
    from tradelab.data.database import Database
    if not config.DB_PATH.exists():
        raise ToolError("TradeLab Pro has no data yet - open the app once first.")
    db = Database(path=config.DB_PATH, read_only=True)
    behind = db.schema_behind()
    if behind:
        db.conn.close()
        raise ToolError(f"The TradeLab database is {behind} version(s) behind this code. "
                        "Open TradeLab Pro once so it can upgrade it, then ask again.")
    return db


def _positions(db) -> list:
    positions = [p for p in db.positions() if str(p.get("symbol") or "").strip()]
    if not positions:
        raise ToolError("No holdings in TradeLab yet - add them in the Portfolio tab "
                        "or import them from IBKR.")
    return positions


def _target_currency(currency: str):
    currency = (currency or "CAD").strip()
    return None if currency.lower().startswith("native") else currency.upper()


def _fx_pairs(symbols, target, extra=()):
    from tradelab.core.portfolio_analytics import currency_of, fx_pair_symbol
    if not target:
        return {}
    needed = {currency_of(s) for s in symbols} | {currency_of(s) for s in extra}
    return {ccy: fx_pair_symbol(ccy, target) for ccy in needed - {target}}


def _real_histories(symbols, period: str):
    """Price histories, with the synthetic fallback removed. Real money is
    never valued on generated prices - a failed download shows as missing,
    exactly as it does in the Analytics tab."""
    from tradelab.data.market_data import get_histories, is_synthetic
    history = get_histories(sorted(set(symbols)), period, "1d") or {}
    return {s: df for s, df in history.items() if df is not None and not is_synthetic(df)}


# -- the tools ------------------------------------------------------------------------

def portfolio() -> dict:
    """Holdings as TradeLab stores them."""
    db = open_database()
    try:
        positions = db.positions()
    finally:
        db.conn.close()
    return {"positions": jsonable(positions), "count": len(positions),
            "note": "Shares and entry (average cost) prices as stored in TradeLab - "
                    "for live quantities, ask the brokerage."}


def book_summary(currency: str = "CAD", period: str = "1y", benchmark: str = "SPY") -> dict:
    """What the Analytics tab shows: value, P&L, return vs benchmark, risk."""
    from tradelab.core import portfolio_analytics as pa
    db = open_database()
    try:
        positions = _positions(db)
    finally:
        db.conn.close()
    benchmark = (benchmark or "SPY").strip().upper()
    target = _target_currency(currency)
    holdings = sorted({str(p["symbol"]).upper() for p in positions})
    fx_pairs = _fx_pairs(holdings, target, extra=[benchmark])
    history = _real_histories(set(holdings) | {benchmark} | set(fx_pairs.values()), period)
    fx = {ccy: history.get(sym) for ccy, sym in fx_pairs.items()} if target else None
    data = pa.summarize(positions, history, benchmark_df=history.get(benchmark),
                        benchmark_symbol=benchmark, target_currency=target, fx=fx)
    data.pop("equity", None)                       # 260 daily points: noise here
    data["note"] = NOT_ADVICE
    return jsonable(data)


def look_through(currency: str = "CAD") -> dict:
    """The book by underlying company: funds opened up to what they hold."""
    from tradelab.core import portfolio_analytics as pa
    from tradelab.data.market_data import canonical_sector, get_fund_composition, get_quote_meta
    valued = book_summary(currency=currency)
    rows = valued.get("holdings") or []
    if not rows:
        raise ToolError("No holding could be priced, so there is nothing to look through.")
    compositions, sectors = {}, {}
    for row in rows:
        symbol = row["symbol"]
        compositions[symbol] = get_fund_composition(symbol)
        if not (compositions[symbol] or {}).get("sectors"):
            sectors[symbol] = canonical_sector((get_quote_meta(symbol) or {}).get("sector")) or None
    result = {"companies": pa.look_through(rows, compositions),
              "sectors": pa.look_through_sectors(rows, compositions, sectors),
              "currency": valued.get("currency"),
              "note": ("Every figure is a floor: data sources publish only a fund's top "
                       "holdings, so the rest is reported as unallocated rather than "
                       "spread across the names that are visible.")}
    return jsonable(result)


def dividend_income(currency: str = "CAD") -> dict:
    """What the Dividends tab shows: annual income, yields, monthly calendar."""
    from tradelab.core import dividends as dv
    from tradelab.core import portfolio_analytics as pa
    from tradelab.data.market_data import get_dividends
    db = open_database()
    try:
        positions = _positions(db)
    finally:
        db.conn.close()
    target = _target_currency(currency)
    symbols = sorted({str(p["symbol"]).upper() for p in positions})
    fx_pairs = _fx_pairs(symbols, target)
    history = _real_histories(set(symbols) | set(fx_pairs.values()), "1y")
    fx = {ccy: history.get(sym) for ccy, sym in fx_pairs.items()} if target else None
    prices = {}
    for sym in symbols:
        close = pa._close(history.get(sym))
        if close is not None and not close.empty:
            prices[sym] = float(close.iloc[-1])
    data = dv.summarize(positions, {s: get_dividends(s) for s in symbols}, prices,
                        target_currency=target, fx=fx)
    data["note"] = ("Projected from past payments: companies can raise, cut or suspend a "
                    "dividend at any time. " + NOT_ADVICE)
    return jsonable(data)


# The Retirement Sim tab's own defaults, for whatever it has not saved yet.
_SIM_DEFAULTS = {"spending": 50_000.0, "inflation": 2.0, "until_age": 95,
                 "splitting": 0.0, "volatility": 10.0}


def _saved_sim_inputs() -> dict:
    """The assumptions last saved in the Retirement Sim tab."""
    from tradelab.core.retirement_plan import nominal_from_real
    from tradelab.settings import app_settings
    s = app_settings()
    s.beginGroup("RetirementSim")
    try:
        out = {k: float(s.value(k, v)) for k, v in _SIM_DEFAULTS.items()}
        nominal = s.value("nominal_return")
        if nominal is None:
            # The tab used to ask for a real return; convert it the way it does.
            real = s.value("real_return")
            nominal = (nominal_from_real(float(real) / 100.0, out["inflation"] / 100.0) * 100
                       if real is not None else 5.0)
        out["nominal_return"] = float(nominal)
    finally:
        s.endGroup()
    return out


def retirement_projection(spending: float | None = None,
                          nominal_return_pct: float | None = None,
                          inflation_pct: float | None = None,
                          until_age: int | None = None,
                          pension_split_pct: float | None = None,
                          balances: dict | None = None,
                          todays_dollars: bool = False,
                          paths: int = 0,
                          volatility_pct: float | None = None) -> dict:
    """The Retirement Sim tab's projection, from its stored plan."""
    from tradelab.core import retirement_plan as rp
    from tradelab.core.tax_quebec import household_tax_fn
    db = open_database()
    try:
        people = db.retirement_rows("people")
        accounts = db.retirement_rows("accounts")
        incomes = db.retirement_rows("incomes")
    finally:
        db.conn.close()

    saved = _saved_sim_inputs()
    a = {"spending": saved["spending"] if spending is None else float(spending),
         "nominal_return_pct": saved["nominal_return"] if nominal_return_pct is None
         else float(nominal_return_pct),
         "inflation_pct": saved["inflation"] if inflation_pct is None else float(inflation_pct),
         "until_age": int(saved["until_age"] if until_age is None else until_age),
         "pension_split_pct": saved["splitting"] if pension_split_pct is None
         else float(pension_split_pct)}
    if not 0 <= a["pension_split_pct"] <= 50:
        raise ToolError("Pension income splitting is capped at 50% by the rules.")

    known = {str(r.get("name") or "").strip().lower() for r in accounts}
    unknown = [n for n in (balances or {}) if str(n).strip().lower() not in known]
    if unknown:
        raise ToolError(f"No account named {', '.join(map(str, unknown))} in the plan. "
                        f"Accounts are: {', '.join(sorted(r['name'] for r in accounts)) or 'none'}.")

    plan = rp.plan_from_rows(
        people, accounts, incomes, spending=a["spending"],
        nominal_return=a["nominal_return_pct"] / 100.0,
        inflation=a["inflation_pct"] / 100.0, until_age=a["until_age"],
        tax_fn=household_tax_fn(a["pension_split_pct"] / 100.0, a["inflation_pct"] / 100.0),
        balances=balances)
    if plan is None:
        raise ToolError("The Retirement Sim plan has no people or no accounts yet - "
                        "fill them in on that tab first.")

    rows = rp.project(plan)
    shown = rp.deflate(rows) if todays_dollars else rows
    failed = rp.depletion_year(rows)
    last = shown[-1]
    summary = {"dollars": "today's" if todays_dollars else "each year's own",
               "final_balance": last["closing"],
               "final_age": max(last["ages"].values())}
    if failed is None:
        summary["lasts_to_age"] = summary["final_age"]
    else:
        summary["runs_short_at_age"] = max(rows[failed]["ages"].values())
        summary["first_year_short_by"] = shown[failed]["unfunded"]

    result = {
        "assumptions": {**a, "balances_overridden": sorted(balances) if balances else []},
        "summary": summary,
        "years": [{"year": r["calendar_year"], "ages": r["ages"], "income": r["income"],
                   "rrif_minimum": r["forced_withdrawal"], "tax": r["tax"],
                   "spending": r["spending"], "from_capital": r["drawn_from_capital"],
                   "reinvested": r.get("surplus", 0.0),
                   "unfunded": r["unfunded"], "closing": r["closing"]} for r in shown],
        "notes": [
            "Nominal return and inflation are projected explicitly; indexed benefits, "
            "spending and the tax brackets rise with inflation, a fixed pension does not.",
            "After-tax income beyond the spending is reinvested in a non-registered "
            "account drawn last ('reinvested'); its growth is not taxed in this model, "
            "which is somewhat optimistic.",
            "One return path says nothing about the order returns arrive in - ask for "
            "paths > 0 to see sequence risk.",
            NOT_ADVICE],
    }

    if paths and int(paths) > 0:
        vol = saved["volatility"] if volatility_pct is None else float(volatility_pct)
        out = rp.simulate(plan, paths=int(paths), mean=a["nominal_return_pct"] / 100.0,
                          sd=vol / 100.0, seed=1)
        result["paths"] = {
            "paths": out["paths"], "volatility_pct": vol,
            "share_never_short": out["success_rate"],
            "median_age_short": out["median_depletion_age"],
            "worst_decile_age_short": out["worst_decile_age"],
            "note": ("The share of simulated paths under the assumptions chosen - not a "
                     "probability that a retirement works. Returns are drawn from a normal "
                     "curve, which has fewer very bad years than markets do.")}
    return jsonable(result)


def quebec_tax(income: float, age: int, pension_income: float = 0.0,
               family_income: float | None = None, years_ahead: int = 0,
               inflation_pct: float = 2.0) -> dict:
    """Quebec + federal income tax for one person, 2026 tables."""
    from tradelab.core.tax_quebec import marginal_rate, tax_for, year_2026
    if income < 0 or pension_income < 0:
        raise ToolError("Income cannot be negative.")
    table = year_2026().inflated(int(years_ahead), float(inflation_pct) / 100.0)
    out = tax_for(float(income), int(age), float(pension_income), table,
                  family_income=None if family_income is None else float(family_income))
    out["marginal_rate"] = marginal_rate(float(income), int(age), table)
    out["tax_year"] = table.year
    out["notes"] = [
        "2026 brackets and credits read off canada.ca and revenuquebec.ca; later years "
        "are the 2026 table indexed by the inflation given.",
        "Modelled: basic personal amounts, age amount, pension income amount, Quebec's "
        "reduction on family income, the Quebec abatement. Not modelled: the OAS "
        "recovery tax, and any credit beyond these.",
        NOT_ADVICE]
    return jsonable(out)


def etf_screener() -> dict:
    """The ETF Screener's stored comparison table - no download."""
    db = open_database()
    try:
        funds = db.etf_list()
    finally:
        db.conn.close()
    return {"funds": jsonable(funds), "count": len(funds),
            "note": ("Figures as last refreshed in the ETF Screener tab; percentages are "
                     "fractions (0.05 = 5%). Risk is the regulator's NI 81-102 band.")}


def journal_summary() -> dict:
    """Trade journal statistics and the Coach's process grades."""
    from tradelab.core import coach
    from tradelab.core import journal as jr
    entries = jr.Journal().all()
    if not entries:
        raise ToolError("The trade journal is empty.")
    report = coach.coach_report(entries)
    return jsonable({"stats": jr.summarize(entries), "coach": report,
                     "note": "Grades judge execution - plan, stop, sizing - not outcome."})
