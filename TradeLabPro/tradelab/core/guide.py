"""The Guide: a beginner's path from "where do I start?" to a mix that suits
them (Qt-free, offline-testable).

Step 1 asks a few plain questions - when the money is needed, which accounts,
how much, and how big a drop the person could live through without selling.
Step 2 lays out six levels, from capital first to all stocks, each with:
- what it may return a year, from the FP Canada / Institute of Financial
  Planning 2026 Projection Assumption Guidelines (published 2026-04-16:
  short-term 2.4%, fixed income 3.2%, Canadian equities 6.3%, U.S. 6.4%,
  international developed 6.6%, emerging markets 7.5%, inflation 2.1%),
  less an index fund's fee;
- what it actually did, measured on real prices since 2002: its worst fall,
  its worst and best 12 months, its worst 5 years.
Those two together are the honest answer to "how much can I make, and how
much can I lose" - the guidelines are for projections of 10 years or more,
and nothing here is a promise.

The level the answers point to is the highest one whose measured worst fall
the person said they could live with, and no higher than their horizon
allows. They choose; a level above it is allowed, with the reason shown.
Nothing here names a security or says buy or sell.
"""
from __future__ import annotations

import pandas as pd

GUIDELINES = "FP Canada / IQPF Projection Assumption Guidelines 2026"
SHORT_TERM = 0.024
FIXED_INCOME = 0.032
INFLATION = 0.021
# A typical global index mix for the stock part, with each region's
# guideline return.
STOCK_MIX = {"Canadian equities": (0.30, 0.063), "U.S. equities": (0.45, 0.064),
             "International developed": (0.20, 0.066), "Emerging markets": (0.05, 0.075)}
INDEX_FEE = 0.0025   # a low-cost index fund's MER, taken off every return

# The levels: (name, stocks, bonds, cash) in fractions.
LEVELS = [("Capital first", 0.0, 0.3, 0.7),
          ("Cautious", 0.2, 0.7, 0.1),
          ("Conservative", 0.4, 0.6, 0.0),
          ("Balanced", 0.6, 0.4, 0.0),
          ("Growth", 0.8, 0.2, 0.0),
          ("All stocks", 1.0, 0.0, 0.0)]

# How each level is measured: Canadian-listed index funds with a history back
# to 2001 (the US and international ones hedged to CAD), cash at a steady
# short-term rate. They stand in for the asset classes; they are not picks.
STOCK_PROXIES = {"XIU.TO": 0.30, "XSP.TO": 0.45, "XIN.TO": 0.25}
BOND_PROXY = "XBB.TO"
PROXIES = list(STOCK_PROXIES) + [BOND_PROXY]

# The questions: (label, value) choices.
HORIZONS = [("Less than 2 years", 1, 0), ("2 to 3 years", 3, 1), ("4 to 5 years", 5, 2),
            ("6 to 9 years", 7, 3), ("10 to 14 years", 12, 4), ("15 years or more", 20, 5)]
DROPS = [("No drop at all", 0.0, "no drop at all"), ("About 5%", 0.05, "a drop of about 5%"),
         ("About 10%", 0.10, "a drop of about 10%"), ("About 20%", 0.20, "a drop of about 20%"),
         ("About 30%", 0.30, "a drop of about 30%"),
         ("More than 30%", 0.50, "a drop of more than 30%")]
ACCOUNTS = ["CELI and REER", "CELI only", "REER only", "Neither yet"]
YES_NO = ["Yes", "No", "Not sure"]


def expected_return(stocks: float, bonds: float, cash: float, fee: float = INDEX_FEE) -> float:
    """A year's return from the guidelines, after the fee."""
    stock_r = sum(w * r for w, r in STOCK_MIX.values())
    return stocks * stock_r + bonds * FIXED_INCOME + cash * SHORT_TERM - fee


def future_value(lump: float, monthly: float, years: float, rate: float) -> float:
    """What a lump sum and a monthly saving grow to at a steady yearly rate."""
    months = int(round(years * 12))
    m = (1 + rate) ** (1 / 12) - 1
    fv = lump * (1 + m) ** months
    fv += monthly * (((1 + m) ** months - 1) / m if m else months)
    return fv


def monthly_returns(prices: dict) -> pd.DataFrame:
    """Month-end returns of each proxy, on the months they all have."""
    frames = {}
    for sym, s in (prices or {}).items():
        p = pd.to_numeric(pd.Series(s), errors="coerce").dropna()
        if p.empty:
            continue
        p.index = pd.to_datetime(p.index)
        frames[sym] = p.resample("ME").last().pct_change()
    df = pd.DataFrame(frames).dropna()
    return df


def level_returns(rets: pd.DataFrame, stocks: float, bonds: float, cash: float) -> pd.Series:
    """A level's month-by-month return, rebalanced every month."""
    stock_part = sum(rets[s] * w for s, w in STOCK_PROXIES.items()) / sum(STOCK_PROXIES.values())
    cash_m = (1 + SHORT_TERM) ** (1 / 12) - 1
    return stocks * stock_part + bonds * rets[BOND_PROXY] + cash * cash_m


def measure(prices: dict) -> list | None:
    """Each level's real record since the proxies' common start: worst fall
    (and when), worst and best 12 months, worst 5 years a year, and how many
    5-year stretches lost money. None when the prices are missing."""
    rets = monthly_returns(prices)
    if rets.empty or any(s not in rets for s in PROXIES) or len(rets) < 72:
        return None
    out = []
    for name, st, bo, ca in LEVELS:
        r = level_returns(rets, st, bo, ca)
        growth = (1 + r).cumprod()
        dd = growth / growth.cummax() - 1
        trough = dd.idxmin()
        peak = growth.loc[:trough].idxmax()
        y1 = growth / growth.shift(12) - 1
        y5 = (growth / growth.shift(60)) ** (1 / 5) - 1
        out.append({"name": name, "worst_fall": float(min(dd.min(), 0.0)),
                    "worst_when": f"{peak:%b %Y}-{trough:%b %Y}" if dd.min() < 0 else "",
                    "worst_12m": float(y1.min()), "best_12m": float(y1.max()),
                    "worst_5y": float(y5.min()), "loss_5y": float((y5 < 0).mean()),
                    "since": f"{rets.index[0]:%Y}"})
    return out


def recommend(horizon_idx: int, drop_idx: int, measured: list | None = None) -> dict:
    """The level the answers point to, and why. With measured records the
    drop limit is read against each level's real worst fall; without them,
    each answer stands for one level."""
    cap_h = HORIZONS[horizon_idx][2]
    _label, limit, phrase = DROPS[drop_idx]
    fits = None
    if measured:
        fits = [i for i, m in enumerate(measured) if -m["worst_fall"] <= limit + 1e-9]
        cap_d = max(fits) if fits else 0
    else:
        cap_d = drop_idx
    level = min(cap_h, cap_d)
    reasons = []
    if cap_h <= cap_d:
        reasons.append(f"you need the money in {HORIZONS[horizon_idx][0].lower()}, and a "
                       f"higher level can take longer than that to recover from a fall")
    if cap_d <= cap_h:
        if fits == []:
            reasons.append(f"you want {phrase}, and {LEVELS[0][0]} is the level that fell least "
                           f"({-measured[0]['worst_fall']:.0%})")
        elif measured:
            reasons.append(f"you could live with {phrase}, and {LEVELS[level][0]} fell "
                           f"{-measured[level]['worst_fall']:.0%} at worst")
        else:
            reasons.append(f"you could live with {phrase}")
    note = ""
    if fits == []:
        note = "Only savings accounts and GICs (term deposits) never drop."
    return {"level": level, "why": "Because " + " - and ".join(reasons) + ".", "note": note}


def first_steps(emergency: str, debt: str, accounts: str) -> list:
    """What usually comes before investing, from the answers - plain facts."""
    steps = []
    if emergency != "Yes":
        steps.append("Keep a few months of expenses in a savings account first, so an "
                     "emergency never forces you to sell after a drop.")
    if debt == "Yes":
        steps.append("A credit card or loan at 15-20% costs more than any level here "
                     "is expected to earn: paying it off is a sure return.")
    if accounts == "Neither yet":
        steps.append("A CELI or a REER keeps the growth from being taxed every year. "
                     "The next step of the guide places funds by account.")
    return steps


def check_choice(chosen: int, recommended: int, measured: list | None) -> str:
    """What choosing above the answers' level means - "" when it does not."""
    if chosen <= recommended:
        return ""
    fall = f" It fell {-measured[chosen]['worst_fall']:.0%} at worst." if measured else ""
    return (f"{LEVELS[chosen][0]} is above the level your answers point to "
            f"({LEVELS[recommended][0]}).{fall} It is your choice.")
