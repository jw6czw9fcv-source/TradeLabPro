"""The tax-season summary: one year's figures gathered for the return (Qt-free).

What it can gather from what TradeLab holds:
- **gains and losses** on the trades the Journal closed that year, per currency;
- **contributions and withdrawals** recorded in the Retirement tab's plans.

What it cannot, and says so: whether a trade was in a REER, a CELI or a
taxable account (gains inside a REER or a CELI are not taxed), dividends
actually received, and anything on an official slip. The slips (T4RSP, T5,
T3, Relevé 1, Relevé 2...) and the broker's annual statements are the figures
to file; this is a checklist to compare them against, not a return.
"""
from __future__ import annotations

import csv
import io

from tradelab.core import retirement as rt


def _currency(symbol: str) -> str:
    try:
        from tradelab.core.portfolio_analytics import currency_of
        return currency_of(symbol)
    except Exception:
        return ""


def summary(year: int, entries: list, accounts: list) -> dict:
    """Year's closed trades (gains/losses by currency) and plan flows."""
    y = str(int(year))
    trades = []
    for e in entries or []:
        if e.is_open or not str(e.exit_date or "").startswith(y):
            continue
        pnl = e.pnl
        if pnl is None:
            continue
        trades.append({"symbol": e.symbol, "side": e.side, "qty": e.qty,
                       "entry_date": e.entry_date, "exit_date": e.exit_date,
                       "proceeds": float(e.exit_price) * e.qty,
                       "cost": e.entry_price * e.qty, "pnl": pnl,
                       "currency": _currency(e.symbol)})
    by_currency = {}
    for t in trades:
        c = by_currency.setdefault(t["currency"] or "?", {"gains": 0.0, "losses": 0.0, "net": 0.0,
                                                         "trades": 0})
        c["gains" if t["pnl"] >= 0 else "losses"] += t["pnl"]
        c["net"] += t["pnl"]
        c["trades"] += 1
    flows = []
    for account in accounts or []:
        contributed = withdrawn = 0.0
        for fund in account.funds:
            for f in fund.flows:
                if not str(f.date).startswith(y):
                    continue
                if f.kind == rt.WITHDRAWAL:
                    withdrawn += f.amount
                else:
                    contributed += f.amount
        if contributed or withdrawn:
            flows.append({"account": account.name, "currency": account.currency,
                          "contributed": contributed, "withdrawn": withdrawn})
    return {"year": int(year), "trades": sorted(trades, key=lambda t: t["exit_date"]),
            "by_currency": by_currency, "flows": flows}


def as_text(s: dict) -> str:
    lines = [f"Tax-season summary for {s['year']}", ""]
    if s["by_currency"]:
        lines.append("Trades closed in the Journal:")
        for ccy, c in sorted(s["by_currency"].items()):
            lines.append(f"  {ccy}: {c['trades']} trade(s) - gains {c['gains']:,.2f}, "
                         f"losses {c['losses']:,.2f}, net {c['net']:+,.2f}")
        lines.append("  Taxable only if they were in a non-registered account - gains inside a "
                     "REER or a CELI are not taxed. A foreign-currency gain is reported in CAD "
                     "at the exchange rates of the trade dates.")
    else:
        lines.append("No trades closed in the Journal this year.")
    lines.append("")
    if s["flows"]:
        lines.append("Retirement plans (Retirement tab):")
        for f in s["flows"]:
            lines.append(f"  {f['account']}: contributed {f['contributed']:,.2f} {f['currency']}, "
                         f"withdrawn {f['withdrawn']:,.2f} {f['currency']}")
        lines.append("  Contributions to a REER are deductible (within your room); withdrawals are "
                     "income. Your slips are the figures to file.")
    else:
        lines.append("No contributions or withdrawals recorded in the Retirement tab this year.")
    lines += ["", "Not from TradeLab: dividends and interest (T5, T3, Relevé 3/16), REER "
              "withdrawals (T4RSP, Relevé 2) and contributions receipts, OAS and RRQ (T4A(OAS), "
              "T4A(P), Relevé 2). Compare this list with them - it is not a tax return."]
    return "\n".join(lines)


def to_csv(s: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["section", "symbol / account", "currency", "entry date", "exit date",
                "quantity", "cost", "proceeds", "gain or loss", "contributed", "withdrawn"])
    for t in s["trades"]:
        w.writerow(["trade", t["symbol"], t["currency"], t["entry_date"], t["exit_date"],
                    t["qty"], f"{t['cost']:.2f}", f"{t['proceeds']:.2f}", f"{t['pnl']:.2f}", "", ""])
    for f in s["flows"]:
        w.writerow(["plan", f["account"], f["currency"], "", "", "", "", "", "",
                    f"{f['contributed']:.2f}", f"{f['withdrawn']:.2f}"])
    return out.getvalue()
