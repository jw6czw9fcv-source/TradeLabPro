"""The Guide: a beginner's path from "where do I start?" to a mix that suits
them (Qt-free, offline-testable).

Step 1 asks a few plain questions - when the money is needed, which accounts,
how much, and how big a drop the person could live through without selling.
Step 2 lays out six levels, from capital first to all stocks, each with:
- what it really returned a year, measured in CAD on real prices since 2003
  (October, when the exchange-rate history starts) and over the last 10
  years - unhedged, as an all-in-one ETF holds its foreign stocks;
- what it really lost: its worst fall, worst 12 months and worst 5 years;
- for comparison, what planners are told to assume: the FP Canada /
  Institute of Financial Planning 2026 Projection Assumption Guidelines
  (published 2026-04-16: short-term 2.4%, fixed income 3.2%, Canadian
  equities 6.3%, U.S. 6.4%, international developed 6.6%, emerging markets
  7.5%, inflation 2.1%), less an index fund's fee. They are deliberately
  cautious - well under what these mixes did since 2003 - and the person
  chooses which return the projection uses.
Return and loss side by side are the honest answer to "how much can I make,
and how much can I lose"; the past is no promise.

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

# How each level is measured: index funds with long histories in the same
# regional weights, the US-listed ones turned into CAD at each month's
# exchange rate (unhedged, as XEQT or VEQT hold them), cash at a steady
# short-term rate. They stand in for the asset classes; they are not picks.
STOCK_PROXIES = {"XIU.TO": 0.30, "SPY": 0.45, "EFA": 0.20, "EEM": 0.05}
USD_PROXIES = ("SPY", "EFA", "EEM")
FX = "CAD=X"          # Yahoo's USD/CAD: Canadian dollars per US dollar
BOND_PROXY = "XBB.TO"
PROXIES = list(STOCK_PROXIES) + [BOND_PROXY, FX]

# The stretches of history shown: (label, months - None for all of it), and
# which yearly return the projection uses - one of them, or the guidelines.
WINDOWS = [("since 2003", None), ("the last 10 years", 120), ("the last 3 years", 36),
           ("the last year", 12)]
BASES = [f"What it did {label}" for label, _m in WINDOWS] + ["Planners' guidelines (cautious)"]
GUIDELINES_BASIS = len(WINDOWS)

# The questions: (label, value) choices.
HORIZONS = [("Less than 2 years", 1, 0), ("2 to 3 years", 3, 1), ("4 to 5 years", 5, 2),
            ("6 to 9 years", 7, 3), ("10 to 14 years", 12, 4), ("15 years or more", 20, 5)]
DROPS = [("No drop at all", 0.0, "no drop at all"), ("About 5%", 0.05, "a drop of about 5%"),
         ("About 10%", 0.10, "a drop of about 10%"), ("About 20%", 0.20, "a drop of about 20%"),
         ("About 30%", 0.30, "a drop of about 30%"),
         ("More than 30%", 0.50, "a drop of more than 30%")]
ACCOUNTS = ["CELI and REER", "CELI only", "REER only", "Neither yet"]
YES_NO = ["Yes", "No", "Not sure"]


# Step 3 - the funds. Canadian-listed index ETFs, three providers side by side
# (iShares, Vanguard, BMO, plus the savings ETFs), each checked to exist on
# Yahoo on 2026-10-28. They are the candidates the guide checks, not picks:
# the person orders them by what matters to them and chooses.
ONE_FUND = {0: ["CASH.TO", "PSA.TO", "ZMMK.TO"],
            1: ["XINC.TO", "VCIP.TO"],
            2: ["XCNS.TO", "VCNS.TO", "ZCON.TO"],
            3: ["XBAL.TO", "VBAL.TO", "ZBAL.TO"],
            4: ["XGRO.TO", "VGRO.TO", "ZGRO.TO"],
            5: ["XEQT.TO", "VEQT.TO", "ZEQT.TO"]}
ONE_FUND_NOTE = {
    0: "Savings and money-market ETFs: high-interest bank deposits or short loans - the "
       "yield follows the Bank of Canada's rate, and the price barely moves.",
}
# (name, class, symbols, what it is)
BLOCKS = [
    ("Cash and savings", "cash", ["CASH.TO", "PSA.TO", "ZMMK.TO"],
     "High-interest deposits and money market: the price barely moves; the yield follows "
     "the Bank of Canada."),
    ("Short-term bonds", "bonds", ["XSB.TO", "VSB.TO", "ZSB.TO"],
     "Canadian bonds of 1 to 5 years: small moves when rates change - suits money needed soon."),
    ("Bonds, all terms", "bonds", ["XBB.TO", "VAB.TO", "ZAG.TO"],
     "All Canadian bonds: a little more yield, bigger drops when rates rise (as in 2022)."),
    ("Canadian stocks", "stocks", ["XIC.TO", "VCN.TO", "ZCN.TO"],
     "The whole Canadian market, about 200+ companies."),
    ("Canadian dividend stocks", "stocks", ["VDY.TO", "XEI.TO", "ZDV.TO"],
     "Canadian companies paying high dividends - still stocks: they rise and fall with the "
     "market, and are concentrated in a few sectors (banks, energy, telecoms)."),
    ("U.S. stocks (S&P 500)", "stocks", ["VFV.TO", "XUS.TO", "ZSP.TO"],
     "The 500 largest US companies, in CAD (unhedged)."),
    ("International stocks", "stocks", ["XEF.TO", "VIU.TO", "ZEA.TO"],
     "Developed markets outside North America: Europe, Japan, Australia."),
    ("Global stocks, outside Canada", "stocks", ["XAW.TO", "VXC.TO"],
     "The US, international and emerging markets in one fund."),
]


def block_amounts(level: int, amount: float) -> dict:
    """{class: dollars} of the level's mix for an amount."""
    _name, st, bo, ca = LEVELS[level]
    return {"stocks": amount * st, "bonds": amount * bo, "cash": amount * ca}


# Step 4 - the purchases. A pick is (symbol, class): "all" for a fund that
# holds the whole level (step 3's one fund), else the block's class.
ALL = "all"


def default_weights(level: int, picks: list) -> dict:
    """Each picked fund's share of the money, from the level's mix: a class's
    share split evenly between the funds picked for it; one-fund picks share
    whatever the blocks do not cover. Returns {weights: {symbol: fraction},
    uncovered: {class: share}} - the part of the level no pick covers, which
    stays as cash until a fund is picked for it."""
    _name, *shares = LEVELS[level]
    share = dict(zip(("stocks", "bonds", "cash"), shares))
    by_class = {}
    for symbol, cls in picks:
        by_class.setdefault(cls, []).append(symbol)
    weights = {}
    covered = 0.0
    for cls in ("stocks", "bonds", "cash"):
        funds = by_class.get(cls) or []
        if funds and share[cls]:
            covered += share[cls]
            for s in funds:
                weights[s] = weights.get(s, 0.0) + share[cls] / len(funds)
    alls = by_class.get(ALL) or []
    rest = max(0.0, 1.0 - covered)
    for s in alls:
        weights[s] = weights.get(s, 0.0) + rest / len(alls)
    uncovered = {} if alls else {c: v for c, v in share.items()
                                 if v and not by_class.get(c)}
    return {"weights": weights, "uncovered": uncovered}


def purchases(weights: dict, prices: dict, held: dict | None, cash: float) -> dict:
    """Whole shares to buy with `cash` so the funds move toward their shares
    (`weights`, fractions of the account) without selling: each fund below
    its share gets money in proportion to how far below it is, any rest goes
    by the shares, then what is left buys single shares of the fund furthest
    behind while it can. `prices` and `held` are in the same currency as the
    cash. Returns {rows: [{symbol, weight, price, shares, cost}], spent, left}."""
    held = {s: float((held or {}).get(s) or 0.0) for s in weights}
    priced = {s: w for s, w in weights.items() if w > 0 and (prices.get(s) or 0) > 0}
    total = sum(held.values()) + cash
    target = {s: w * total for s, w in priced.items()}
    short = {s: max(0.0, target[s] - held[s]) for s in priced}
    need = sum(short.values())
    if need >= cash and need > 0:
        dollars = {s: cash * short[s] / need for s in priced}
    else:
        wsum = sum(priced.values())
        dollars = {s: short[s] + (cash - need) * (w / wsum if wsum else 0.0)
                   for s, w in priced.items()}
        # Weights under 100% leave the rest as cash on purpose.
        dollars = {s: min(d, max(0.0, target[s] - held[s]) if wsum < 0.999 else d)
                   for s, d in dollars.items()}
    shares = {s: int(dollars[s] // prices[s]) for s in priced}
    left = cash - sum(shares[s] * prices[s] for s in priced)
    for _ in range(10_000):
        gaps = {s: target[s] - held[s] - shares[s] * prices[s] for s in priced
                if prices[s] <= left + 1e-9 and target[s] - held[s] - shares[s] * prices[s] > 0}
        if not gaps:
            break
        s = max(gaps, key=gaps.get)
        shares[s] += 1
        left -= prices[s]
    rows = [{"symbol": s, "weight": weights[s], "price": prices.get(s),
             "shares": shares.get(s, 0), "cost": shares.get(s, 0) * (prices.get(s) or 0.0)}
            for s in weights]
    spent = sum(r["cost"] for r in rows)
    return {"rows": rows, "spent": spent, "left": cash - spent}


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
    """Month-end returns of each proxy in CAD, on the months they all have."""
    ends = {}
    for sym, s in (prices or {}).items():
        p = pd.to_numeric(pd.Series(s), errors="coerce").dropna() if s is not None else pd.Series()
        if p.empty:
            continue
        p.index = pd.to_datetime(p.index)
        ends[sym] = p.resample("ME").last()
    if FX not in ends:
        return pd.DataFrame()
    frames = {sym: (p * ends[FX] if sym in USD_PROXIES else p).pct_change()
              for sym, p in ends.items() if sym != FX}
    return pd.DataFrame(frames).dropna()


def level_returns(rets: pd.DataFrame, stocks: float, bonds: float, cash: float) -> pd.Series:
    """A level's month-by-month return, rebalanced every month."""
    stock_part = sum(rets[s] * w for s, w in STOCK_PROXIES.items()) / sum(STOCK_PROXIES.values())
    cash_m = (1 + SHORT_TERM) ** (1 / 12) - 1
    return stocks * stock_part + bonds * rets[BOND_PROXY] + cash * cash_m


def stats(r: pd.Series) -> dict:
    """One stretch of monthly returns: its yearly return, worst fall from a
    high (counting from the stretch's start), worst and best 12 months and
    worst 5 years a year - None where the stretch is too short for one."""
    start = r.index[0] - pd.offsets.MonthEnd(1)
    growth = pd.concat([pd.Series([1.0], index=[start]), (1 + r).cumprod()])
    years = len(r) / 12
    dd = growth / growth.cummax() - 1
    trough = dd.idxmin()
    peak = growth.loc[:trough].idxmax()
    y1 = (growth / growth.shift(12) - 1).dropna()
    y5 = ((growth / growth.shift(60)) ** (1 / 5) - 1).dropna()
    return {"cagr": float(growth.iloc[-1] ** (1 / years) - 1),
            "worst_fall": float(min(dd.min(), 0.0)),
            "worst_when": f"{peak:%b %Y}-{trough:%b %Y}" if dd.min() < 0 else "",
            "worst_12m": float(y1.min()) if len(y1) else None,
            "best_12m": float(y1.max()) if len(y1) else None,
            "worst_5y": float(y5.min()) if len(y5) else None,
            "loss_5y": float((y5 < 0).mean()) if len(y5) else None}


def measure(prices: dict) -> list | None:
    """Each level's real record since the proxies' common start (the top-level
    figures - what the recommendation reads, 2008 included) and over each of
    WINDOWS (`windows`, in the same order). None when the prices are missing."""
    rets = monthly_returns(prices)
    if rets.empty or any(s not in rets for s in PROXIES if s != FX) or len(rets) < 120:
        return None
    out = []
    for name, st, bo, ca in LEVELS:
        r = level_returns(rets, st, bo, ca)
        windows = [stats(r if months is None else r.iloc[-months:]) for _label, months in WINDOWS]
        out.append({"name": name, **windows[0], "windows": windows,
                    "since": f"{rets.index[0]:%Y}"})
    return out


def rate_for(level: int, basis: int, measured: list | None) -> float:
    """The yearly return the projection uses: what the level really did over
    the chosen stretch, or the guidelines - the guidelines too when there is
    no record."""
    m = measured[level] if measured else None
    if m and basis < len(WINDOWS):
        return m["windows"][basis]["cagr"]
    return expected_return(*LEVELS[level][1:])


def window_record(level: int, basis: int, measured: list | None) -> dict | None:
    """The record shown beside the chosen basis - the whole history when the
    basis is the guidelines."""
    if not measured:
        return None
    m = measured[level]
    return m["windows"][basis] if basis < len(WINDOWS) else m["windows"][0]


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
    top = len(LEVELS) - 1
    if cap_h <= cap_d and cap_h < top:
        reasons.append(f"you need the money in {HORIZONS[horizon_idx][0].lower()}, and a "
                       f"higher level can take longer than that to recover from a fall")
    elif level == top:
        reasons.append(f"you need the money in {HORIZONS[horizon_idx][0].lower()} - time to "
                       f"wait out a fall")
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
