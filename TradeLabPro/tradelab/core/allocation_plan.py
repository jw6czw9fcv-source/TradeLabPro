"""Your investing plan, checked (Qt-free, offline-testable).

The decisions are yours and stay typed in by you: the mix each account should
hold, which portfolio is for trading and how big it may get, how often you
review. This module only measures against them - what each account holds now,
how far it has drifted, what moving it back would take in dollars, whether the
trading side has outgrown its cap, whether a review is due. It never picks a
mix or a security.

Asset classes: stocks, bonds, cash and other (gold, commodities, anything that
is neither). A fund in the ETF Screener is split by its published composition
(a 60/40 fund counts 60% stocks, 40% bonds); anything else is classed from its
type and category, and any class can be set by hand.
"""
from __future__ import annotations

import datetime as dt

CLASSES = ("stocks", "bonds", "cash", "other")
TARGET_CLASSES = ("stocks", "bonds", "cash")
# A holding set to "trading" by hand is a swing trade kept inside a long-term
# account: it stays out of that account's mix and is held to the trading cap
# within the account instead.
TRADING = "trading"
DRIFT_PP = 5.0            # percentage points off target that counts as drift
REVIEW_EVERY_DAYS = 91    # about a quarter

_BOND_WORDS = ("bond", "fixed income", "obligation", "government", "treasury",
               "aggregate", "corporate", "revenu fixe")
_CASH_WORDS = ("money market", "marché monétaire", "cash", "savings", "high interest",
               "ultra short", "ultrashort", "t-bill")
_OTHER_WORDS = ("gold", "silver", "commodit", "precious", "lithium", "crypto", "bitcoin")


def guess_class(meta: dict | None) -> str:
    """A holding's class from its quote metadata: a single stock is stocks; a
    fund is read from its category; unknown is stocks - most funds are."""
    meta = meta or {}
    qtype = str(meta.get("quote_type") or "").upper()
    if qtype == "EQUITY":
        return "stocks"
    text = " ".join(str(meta.get(k) or "") for k in ("sector", "industry", "name")).lower() + " "
    if any(w in text for w in _CASH_WORDS):
        return "cash"
    if any(w in text for w in _BOND_WORDS):
        return "bonds"
    if any(w in text for w in _OTHER_WORDS):
        return "other"
    return "stocks"


def split_of(symbol: str, etf_rows: list, override: str | None = None,
             meta: dict | None = None) -> dict:
    """{class: share} for one holding. A class set by hand wins; then a fund's
    published composition from the ETF Screener; then a guess."""
    if override in CLASSES or override == TRADING:
        return {override: 1.0}
    sym = str(symbol or "").upper()
    for row in etf_rows or []:
        keys = {str(row.get("ticker") or "").upper(), str(row.get("yahoo") or "").upper()}
        if sym not in keys:
            continue
        stocks = sum(float(row.get(k) or 0) for k in ("pct_can", "pct_us", "pct_intl"))
        bonds = float(row.get("pct_bond") or 0)
        other = float(row.get("pct_alt") or 0)
        total = stocks + bonds + other
        if total > 0:
            parts = {"stocks": stocks / total, "bonds": bonds / total, "other": other / total}
            return {k: v for k, v in parts.items() if v > 0}
    return {guess_class(meta): 1.0}


def current_mix(holdings: list, cash_value: float = 0.0) -> dict:
    """Dollars per class for one account. `holdings` are dicts with `value`
    and `split` ({class: share}); recorded cash counts as cash. Swing trades
    (class "trading") are left out - see trading_in."""
    mix = {c: 0.0 for c in CLASSES}
    for h in holdings or []:
        value = float(h.get("value") or 0.0)
        for cls, share in (h.get("split") or {}).items():
            if cls == TRADING:
                continue
            mix[cls] = mix.get(cls, 0.0) + value * float(share)
    mix["cash"] += float(cash_value or 0.0)
    return mix


def trading_in(holdings: list) -> float:
    """Dollars of an account's holdings set to "trading"."""
    return sum(float(h.get("value") or 0.0) * float((h.get("split") or {}).get(TRADING, 0.0))
               for h in holdings or [])


def check_target(target: dict) -> str | None:
    """None if a target mix is usable, else why not."""
    values = [float(target.get(c) or 0) for c in TARGET_CLASSES]
    if any(v < 0 for v in values):
        return "a share cannot be negative"
    if abs(sum(values) - 100.0) > 0.5:
        return f"the shares add up to {sum(values):g}%, not 100%"
    return None


def rebalance(mix: dict, target: dict, drift_pp: float = DRIFT_PP) -> dict:
    """Against a target ({stocks, bonds, cash} in %): per class the dollars
    held, the share held, the target share and dollars, and the change that
    would bring it back (+ buy, - sell). `drifted` lists the classes more than
    `drift_pp` points off. Moves are what it would take, not what to do."""
    total = sum(mix.values())
    rows = []
    for cls in CLASSES:
        held = float(mix.get(cls, 0.0))
        share = held / total * 100.0 if total else 0.0
        goal = float(target.get(cls) or 0.0) if cls in TARGET_CLASSES else 0.0
        goal_value = total * goal / 100.0
        rows.append({"class": cls, "value": held, "pct": share, "target_pct": goal,
                     "target_value": goal_value, "change": goal_value - held,
                     "drift_pp": share - goal})
    drifted = [r["class"] for r in rows
               if abs(r["drift_pp"]) > drift_pp and (r["value"] or r["target_pct"])]
    return {"total": total, "rows": rows, "drifted": drifted}


def deploy_cash(mix: dict, target: dict) -> dict:
    """How the cash an account holds beyond its target cash share would be put
    to work without selling anything: each class short of its target gets a
    share of it in proportion to how short it is; if the cash covers every
    shortfall, the rest goes by the target mix. Returns {investable, buys:
    {class: dollars}, after_pct: {class: % after}}. Amounts are what the target
    implies, not what to do."""
    total = sum(float(v) for v in mix.values())
    cash = float(mix.get("cash", 0.0))
    keep = total * float(target.get("cash") or 0.0) / 100.0
    investable = max(0.0, cash - keep)
    buys = {c: 0.0 for c in TARGET_CLASSES if c != "cash"}
    if investable <= 0 or total <= 0:
        return {"investable": 0.0, "buys": buys, "after_pct": {}}
    short = {c: max(0.0, total * float(target.get(c) or 0.0) / 100.0 - float(mix.get(c, 0.0)))
             for c in buys}
    need = sum(short.values())
    if need >= investable and need > 0:
        for c in buys:
            buys[c] = investable * short[c] / need
    else:
        for c in buys:
            buys[c] = short[c]
        rest = investable - need
        weights = {c: float(target.get(c) or 0.0) for c in buys}
        wsum = sum(weights.values())
        for c in buys:
            buys[c] += rest * (weights[c] / wsum if wsum else 0.0)
    after = {c: float(mix.get(c, 0.0)) + buys.get(c, 0.0) for c in CLASSES}
    after["cash"] = cash - sum(buys.values())
    return {"investable": investable, "buys": buys,
            "after_pct": {c: v / total * 100.0 for c, v in after.items()}}


def trading_check(trading_value: float, total_value: float, cap_pct: float) -> dict:
    """Whether the trading portfolio stays inside its cap of the whole book."""
    share = trading_value / total_value * 100.0 if total_value else 0.0
    room = total_value * cap_pct / 100.0 - trading_value
    return {"share_pct": share, "cap_pct": cap_pct, "over": share > cap_pct + 1e-9,
            "room": room}


def review_due(last: dt.date | None, today: dt.date | None = None,
               every_days: int = REVIEW_EVERY_DAYS) -> dict:
    """When the next review is, and whether it is due."""
    today = today or dt.date.today()
    if last is None:
        return {"due": True, "next": today, "days_left": 0, "last": None}
    nxt = last + dt.timedelta(days=every_days)
    return {"due": today >= nxt, "next": nxt, "days_left": (nxt - today).days, "last": last}
