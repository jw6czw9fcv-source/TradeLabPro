"""Money held where the app cannot reach it: a group RRSP, a pension, a
locked-in plan.

A group plan's funds are not listed anywhere public. There is no ticker, no
Yahoo quote, no API - the unit values live behind the plan administrator's
login and nowhere else. So this module is built around the only input that
actually exists: what the member reads off a statement, a few times a year.

The design follows from that scarcity:

* **No history required.** The first snapshot you enter is the starting stake.
  You do not need to reconstruct years of contributions to get a number out;
  two statements a few months apart are enough to rank one fund against another.
* **Two different questions, two different calculations.** "How did this fund
  do?" is the *unit value* moving - contributions cannot flatter or hurt it.
  "How did *my money* do?" is an XIRR over what I paid in and when. A member
  choosing between funds wants the first; a member checking their plan wants
  the second. Reporting both, separately labelled, is the whole point.
* **Degrade honestly.** With unit values, a fund's return is exact. With only
  dollar balances, it has to be corrected for contributions (Modified Dietz),
  which is sound but leans on the member having recorded them. Every result
  carries the `method` that produced it so the UI can say which one it is.

Qt-free and offline-testable, like every other core module. Reporting only:
nothing here recommends a fund, and comparisons to an index are stated as
facts, not as advice.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from tradelab.core.config import DATA_DIR

RETIREMENT_PATH = DATA_DIR / "retirement.json"

# Flow kinds. Employer money is tracked apart from your own: inside the fund it
# is identical dollars, but it is not *your* return - counting a 100% match as
# performance would report a spectacular fund that is really a payroll benefit.
CONTRIBUTION = "contribution"
EMPLOYER = "employer"
WITHDRAWAL = "withdrawal"
KINDS = (CONTRIBUTION, EMPLOYER, WITHDRAWAL)

# How a return was arrived at, reported alongside every figure.
BY_UNIT_VALUE = "unit_value"   # exact: the unit price moved this much
BY_DIETZ = "dietz"             # corrected for contributions from dollar balances

# Annualizing a short window is how "+3% in seven weeks" becomes "+24%/yr" and
# then becomes a decision. Below this, the cumulative figure is the only one
# reported and `annualized_pct` stays None.
ANNUALIZE_MIN_DAYS = 270

# A group plan statement arrives once or twice a year, so "stale" here is far
# looser than it would be for a brokerage account.
STALE_DAYS = 200

# XIRR over a handful of weeks is numerically fine and financially meaningless.
MIN_XIRR_DAYS = 120

# Fund fact sheets are struck quarterly, so a month or two behind the balances
# is normal; past this the two dates are describing different worlds.
SHEET_LAG_DAYS = 100


def _today() -> date:
    return date.today()


def _parse_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _iso(value) -> str:
    d = _parse_date(value)
    return d.isoformat() if d else str(value or "")


def parse_number(text) -> Optional[float]:
    """A number as a Canadian statement writes it.

    '12 049,25 $' and '1,234.56' and '18.4321' all have to land on the same
    float. The rule that separates them: whichever of ',' or '.' appears last
    is the decimal mark - '12,049.25' decides on the dot, '12 049,25' on the
    comma. Thin and non-breaking spaces are group separators here, not blanks.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace(" ", "").replace(" ", "")
    s = s.replace("$", "").replace("%", "").strip()
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = re.sub(r"[^0-9,.\-+]", "", s)
    if not s:
        return None
    last_comma, last_dot = s.rfind(","), s.rfind(".")
    if last_comma > last_dot:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


# --- data model --------------------------------------------------------------

@dataclass
class Snapshot:
    """One fund, as it stood on one statement.

    `unit_value` is the prize: it is the fund's price, independent of how much
    you happen to hold, so two snapshots of it are a clean return. `value` is
    the fallback when a statement shows only a dollar balance. Give either -
    units x unit_value fills in a missing `value`.
    """
    date: str
    units: Optional[float] = None
    unit_value: Optional[float] = None
    value: Optional[float] = None
    note: str = ""

    def __post_init__(self):
        self.date = _iso(self.date)
        for attr in ("units", "unit_value", "value"):
            raw = getattr(self, attr)
            setattr(self, attr, None if raw is None else float(raw))
        if self.value is None and self.units is not None and self.unit_value is not None:
            self.value = self.units * self.unit_value

    @property
    def on(self) -> Optional[date]:
        return _parse_date(self.date)

    @property
    def amount(self) -> Optional[float]:
        """What the holding was worth, however the statement expressed it."""
        if self.value is not None:
            return self.value
        if self.units is not None and self.unit_value is not None:
            return self.units * self.unit_value
        return None


@dataclass
class Flow:
    """Money moving into or out of one fund on one date. `amount` is always
    stored positive; `kind` carries the direction."""
    date: str
    amount: float = 0.0
    kind: str = CONTRIBUTION
    note: str = ""

    def __post_init__(self):
        self.date = _iso(self.date)
        self.amount = abs(float(self.amount or 0))
        if self.kind not in KINDS:
            self.kind = CONTRIBUTION

    @property
    def on(self) -> Optional[date]:
        return _parse_date(self.date)

    @property
    def signed(self) -> float:
        """Positive into the fund, negative out of it."""
        return -self.amount if self.kind == WITHDRAWAL else self.amount


@dataclass
class Published:
    """A return the plan itself published, alongside the index it chose.

    A fund fact sheet already answers "did this fund beat its benchmark" over
    horizons no member could reconstruct - ten years of unit values are not
    something you hold in a drawer. And it uses the *right* index: the fund's
    stated benchmark, often a blend ('55% MSCI World Energy, 45% MSCI World
    Materials'), not an ETF standing in for one. When a sheet is on file it
    beats anything this module can compute, so it is stored verbatim and
    reported as the plan's own figure, dated.
    """
    as_of: str
    horizon: str                    # one of HORIZONS
    fund_pct: float = 0.0
    index_pct: Optional[float] = None
    index_name: str = ""

    def __post_init__(self):
        self.as_of = _iso(self.as_of)
        self.horizon = str(self.horizon)
        self.fund_pct = float(self.fund_pct or 0.0)
        self.index_pct = None if self.index_pct is None else float(self.index_pct)

    @property
    def excess_pct(self) -> Optional[float]:
        return None if self.index_pct is None else self.fund_pct - self.index_pct


# Horizons as a fund fact sheet prints them, shortest first. Everything past a
# year is annualized on the sheet itself, which is why the labels say so - a
# member reading "10 years: 18.5%" must not take it for a decade's total.
HORIZONS = ["3m", "1y", "2y", "3y", "4y", "5y", "10y"]
HORIZON_LABELS = {"3m": "3 months", "1y": "1 year", "2y": "2 years/yr",
                  "3y": "3 years/yr", "4y": "4 years/yr", "5y": "5 years/yr",
                  "10y": "10 years/yr"}


@dataclass
class Fund:
    """One line of the plan: a name, what you hold in it, what you paid in, and
    optionally the index you want it judged against."""
    name: str
    benchmark: str = ""
    snapshots: list = field(default_factory=list)
    flows: list = field(default_factory=list)
    published: list = field(default_factory=list)
    code: str = ""
    fee_pct: Optional[float] = None
    note: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        self.name = (self.name or "").strip()
        self.benchmark = (self.benchmark or "").strip().upper()
        self.code = (self.code or "").strip().upper()
        self.fee_pct = None if self.fee_pct is None else float(self.fee_pct)
        self.snapshots = [s if isinstance(s, Snapshot) else Snapshot(**s)
                          for s in self.snapshots]
        self.flows = [f if isinstance(f, Flow) else Flow(**f) for f in self.flows]
        self.published = [p if isinstance(p, Published) else Published(**p)
                          for p in self.published]
        self.sort()

    def sort(self):
        self.snapshots.sort(key=lambda s: s.date)
        self.flows.sort(key=lambda f: f.date)
        self.published.sort(key=lambda p: (p.as_of, HORIZONS.index(p.horizon)
                                           if p.horizon in HORIZONS else 99))

    def set_published(self, records: list):
        """Replace the sheet for a given date - re-entering a quarter corrects
        it rather than stacking a second copy behind the first."""
        dates = {r.as_of for r in records}
        self.published = [p for p in self.published if p.as_of not in dates]
        self.published.extend(records)
        self.sort()

    def published_on(self, as_of: str = None, horizon: str = "1y") -> Optional[Published]:
        """The published figure for one horizon, from the newest sheet on file
        unless a specific date is asked for."""
        rows = [p for p in self.published if p.horizon == horizon]
        if as_of:
            rows = [p for p in rows if p.as_of == _iso(as_of)]
        return rows[-1] if rows else None

    @property
    def latest_sheet(self) -> Optional[str]:
        return max((p.as_of for p in self.published), default=None)

    def add_snapshot(self, snapshot: Snapshot) -> Snapshot:
        """Add a statement line, replacing any snapshot already on that date -
        re-entering a statement should correct it, not double it."""
        self.snapshots = [s for s in self.snapshots if s.date != snapshot.date]
        self.snapshots.append(snapshot)
        self.sort()
        return snapshot

    def add_flow(self, flow: Flow) -> Flow:
        self.flows.append(flow)
        self.sort()
        return flow

    @property
    def latest(self) -> Optional[Snapshot]:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def value(self) -> Optional[float]:
        return self.latest.amount if self.latest else None


@dataclass
class Account:
    """A plan: several funds under one name, in one currency.

    `fee_pct` is the plan's investment management fee, the one a fund fact
    sheet leaves out - its returns are struck before it. Stored here because a
    group plan negotiates one fee schedule for the whole plan; a fund that
    charges something different overrides it on its own record.
    """
    name: str
    currency: str = "CAD"
    funds: list = field(default_factory=list)
    fee_pct: Optional[float] = None
    note: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        self.name = (self.name or "").strip()
        self.currency = (self.currency or "CAD").strip().upper()
        self.fee_pct = None if self.fee_pct is None else float(self.fee_pct)
        self.funds = [f if isinstance(f, Fund) else Fund(**f) for f in self.funds]

    def fee_for(self, fund: "Fund") -> Optional[float]:
        return fund.fee_pct if fund.fee_pct is not None else self.fee_pct

    def fund(self, name_or_id: str) -> Optional[Fund]:
        key = (name_or_id or "").strip().lower()
        for f in self.funds:
            if f.id == name_or_id or f.name.lower() == key:
                return f
        return None

    def add_fund(self, fund: Fund) -> Fund:
        self.funds.append(fund)
        return fund

    @property
    def value(self) -> float:
        return sum(f.value or 0.0 for f in self.funds)

    @property
    def statement_dates(self) -> list:
        """Every date any fund was snapshotted on, oldest first."""
        return sorted({s.date for f in self.funds for s in f.snapshots})


# --- the two return calculations ---------------------------------------------

def xirr(cashflows: list, max_iter: int = 200) -> Optional[float]:
    """Money-weighted annual return over dated cashflows.

    `cashflows` are (date, amount) from the investor's side: negative is money
    you put in, positive is money coming back (including the closing value as a
    final positive). Returns a decimal rate (0.062 = 6.2%/yr), or None when the
    flows do not define one - all the same sign, a single flow, or a rate
    outside the bracket searched.

    Solved by bisection rather than Newton: an XIRR over irregular
    contributions can hand Newton a derivative near zero and send it off to
    nowhere. Bisection is slower and cannot diverge, and 200 halvings of this
    bracket is far past double precision anyway.
    """
    flows = [(_parse_date(d), float(a)) for d, a in cashflows]
    flows = [(d, a) for d, a in flows if d is not None and a]
    if len(flows) < 2:
        return None
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = min(d for d, _ in flows)

    def npv(rate: float) -> float:
        total = 0.0
        for d, a in flows:
            years = (d - t0).days / 365.0
            total += a / (1.0 + rate) ** years
        return total

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if f_mid == 0:
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def modified_dietz(start_value: float, end_value: float, flows: list,
                   start: date, end: date) -> Optional[float]:
    """Return over one period, correcting for money added or removed inside it.

    `flows` are (date, signed amount into the account). Each is weighted by the
    fraction of the period it was actually invested for, which is what makes
    this usable when a statement only gives dollar balances: a deposit made two
    days before the closing balance barely counts toward the denominator, so it
    is not mistaken for growth.
    """
    days = (end - start).days
    if days <= 0:
        return None
    net = 0.0
    weighted = 0.0
    for d, amount in flows:
        day = _parse_date(d)
        if day is None:
            continue
        net += amount
        elapsed = (day - start).days
        elapsed = max(0, min(days, elapsed))
        weighted += amount * ((days - elapsed) / days)
    denominator = start_value + weighted
    if denominator <= 0:
        return None
    return (end_value - start_value - net) / denominator


def annualize(cumulative: float, days: int) -> Optional[float]:
    """A cumulative return restated per year, or None when the window is too
    short for that to mean anything (see ANNUALIZE_MIN_DAYS)."""
    if days < ANNUALIZE_MIN_DAYS or days <= 0:
        return None
    if cumulative <= -1:
        return None
    return (1.0 + cumulative) ** (365.0 / days) - 1.0


def fund_return(fund: Fund) -> dict:
    """How the *fund* did, with your contributions taken out of the picture.

    Exact when the statements carry unit values: a unit price is per-unit, so
    buying more units cannot move it. Falls back to chain-linked Modified Dietz
    over dollar balances, which needs the flows to have been recorded.

    Returns cumulative_pct / annualized_pct / method / start / end / days, plus
    `usable` and, when it is False, a `reason` fit to show a user.
    """
    out = {"cumulative_pct": None, "annualized_pct": None, "method": None,
           "start": None, "end": None, "days": 0, "usable": False, "reason": ""}
    snaps = [s for s in fund.snapshots if s.on is not None]
    if len(snaps) < 2:
        out["reason"] = ("One statement is a balance, not a return — enter a "
                         "second date to measure anything.") if snaps else \
                        "No statement entered yet."
        return out

    first, last = snaps[0], snaps[-1]
    days = (last.on - first.on).days
    out.update(start=first.date, end=last.date, days=days)
    if days <= 0:
        out["reason"] = "Both statements are on the same date."
        return out

    priced = [s for s in snaps if s.unit_value]
    if len(priced) >= 2 and priced[0].unit_value > 0:
        # The clean path: the unit price is the fund's own performance.
        first, last = priced[0], priced[-1]
        days = (last.on - first.on).days
        cumulative = last.unit_value / first.unit_value - 1.0
        out.update(cumulative_pct=cumulative * 100.0, method=BY_UNIT_VALUE,
                   start=first.date, end=last.date, days=days, usable=True)
        ann = annualize(cumulative, days)
        out["annualized_pct"] = None if ann is None else ann * 100.0
        return out

    # Fallback: chain-link the periods between dollar balances.
    linked = 1.0
    usable_days = 0
    gaps = 0
    for a, b in zip(snaps, snaps[1:]):
        v0, v1 = a.amount, b.amount
        if v0 is None or v1 is None:
            gaps += 1
            continue
        window = [(f.date, f.signed) for f in fund.flows
                  if f.on is not None and a.on < f.on <= b.on]
        r = modified_dietz(v0, v1, window, a.on, b.on)
        if r is None:
            gaps += 1
            continue
        linked *= (1.0 + r)
        usable_days += (b.on - a.on).days
    if usable_days <= 0:
        out["reason"] = "Not enough balances to measure a return."
        return out
    cumulative = linked - 1.0
    out.update(cumulative_pct=cumulative * 100.0, method=BY_DIETZ,
               days=usable_days, usable=True)
    ann = annualize(cumulative, usable_days)
    out["annualized_pct"] = None if ann is None else ann * 100.0
    if gaps:
        out["reason"] = f"{gaps} period(s) skipped — incomplete data."
    return out


def personal_return(fund: Fund, today: Optional[date] = None) -> dict:
    """How *your money* did in this fund: an XIRR over what you paid in, when
    you paid it, and what the holding is worth now.

    The first snapshot is treated as the opening stake, so no history is
    required - but that also means flows dated on or before it are ignored,
    because they are already inside that balance. Employer money counts as an
    inflow here (it bought units like any other dollar); `excluding_employer`
    reports the same calculation with the match treated as a gift instead,
    which is the honest way to read "what did my own contributions earn".
    """
    today = today or _today()
    out = {"rate_pct": None, "excluding_employer_pct": None, "usable": False,
           "reason": "", "start": None, "days": 0,
           "invested": 0.0, "employer": 0.0, "withdrawn": 0.0,
           "value": None, "gain": None}
    snaps = [s for s in fund.snapshots if s.on is not None and s.amount is not None]
    if not snaps:
        out["reason"] = "No statement entered yet."
        return out
    first, last = snaps[0], snaps[-1]
    out["start"] = first.date
    out["value"] = last.amount
    days = (last.on - first.on).days
    out["days"] = days

    after = [f for f in fund.flows if f.on is not None and f.on > first.on]
    own = sum(f.amount for f in after if f.kind == CONTRIBUTION)
    employer = sum(f.amount for f in after if f.kind == EMPLOYER)
    withdrawn = sum(f.amount for f in after if f.kind == WITHDRAWAL)
    out.update(invested=own, employer=employer, withdrawn=withdrawn)
    net_in = (first.amount or 0.0) + own + employer - withdrawn
    out["gain"] = (last.amount - net_in) if last.amount is not None else None

    if days < MIN_XIRR_DAYS:
        out["reason"] = ("Too short a window to annualize — enter a statement "
                         "from further back.")
        return out

    def rate(include_employer: bool) -> Optional[float]:
        cash = [(first.on, -(first.amount or 0.0))]
        for f in after:
            if f.kind == EMPLOYER and not include_employer:
                continue
            cash.append((f.on, -f.signed))
        cash.append((last.on, last.amount))
        return xirr(cash)

    r = rate(True)
    if r is None:
        out["reason"] = "Contributions do not define a rate of return."
        return out
    out.update(rate_pct=r * 100.0, usable=True)
    if employer:
        r2 = rate(False)
        out["excluding_employer_pct"] = None if r2 is None else r2 * 100.0
    return out


def unrecorded_units(fund: Fund) -> list:
    """Statements where the unit count jumped without a contribution on file.

    Units grow for two reasons: you bought more, or the fund handed out units.
    Either way, a jump you never recorded means the personal return is being
    computed from incomplete flows - so it is worth naming rather than silently
    absorbing into 'performance'. Reported as a suspicion, never auto-applied.
    """
    out = []
    snaps = [s for s in fund.snapshots if s.on is not None and s.units is not None]
    for a, b in zip(snaps, snaps[1:]):
        delta = b.units - a.units
        if abs(delta) < 1e-6:
            continue
        price = b.unit_value or a.unit_value
        if not price:
            continue
        recorded = sum(f.signed for f in fund.flows
                       if f.on is not None and a.on < f.on <= b.on)
        implied = delta * price
        if abs(implied - recorded) > max(25.0, abs(implied) * 0.05):
            out.append({"from": a.date, "to": b.date, "units": delta,
                        "implied": implied, "recorded": recorded})
    return out


# --- comparing a fund to an index --------------------------------------------

def window_return(history, start, end) -> Optional[float]:
    """An index's own return over the same window, as a decimal.

    `history` is a price frame (a Close column or a Series). Statement dates
    rarely fall on trading days, so each end is taken at the last close on or
    before it - the same convention a fund uses to strike its own unit value.
    """
    start, end = _parse_date(start), _parse_date(end)
    if history is None or start is None or end is None:
        return None
    try:
        import pandas as pd
        closes = history["Close"] if hasattr(history, "columns") and "Close" in history.columns else history
        closes = pd.Series(closes).dropna()
        if closes.empty:
            return None
        index = pd.to_datetime(closes.index)
        try:
            index = index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        closes.index = index
        before = closes[index <= pd.Timestamp(start)]
        after = closes[index <= pd.Timestamp(end)]
        if before.empty or after.empty:
            return None
        first, last = float(before.iloc[-1]), float(after.iloc[-1])
        if first <= 0:
            return None
        return last / first - 1.0
    except Exception:
        return None


# Index proxies for the mandates a Canadian group plan typically offers. These
# are starting points the member can overwrite per fund, not claims that any
# particular ETF replicates any particular fund - a plan's fund is a mandate at
# a negotiated fee, and the point of comparing is to see the difference.
BENCHMARK_HINTS = [
    (("marché monétaire", "marche monetaire", "money market", "court terme"), "CASH.TO"),
    (("obligat", "bond", "revenu fixe", "fixed income"), "XBB.TO"),
    (("équilibr", "equilibr", "balanced", "diversifi"), "XBAL.TO"),
    (("marchés émergents", "marches emergents", "emerging"), "XEC.TO"),
    (("international", "eafe"), "XEF.TO"),
    (("américain", "americain", "america", "u.s.", "etats-unis", "états-unis"), "XUU.TO"),
    (("mondial", "monde", "global", "world"), "XWD.TO"),
    (("ressource", "resource", "matériaux", "materiaux", "materials", "énergie", "energie"), "XEG.TO"),
    (("immobilier", "real estate", "reit"), "XRE.TO"),
    (("canad", "canadian", "tsx"), "XIC.TO"),
]


def suggest_benchmark(fund_name: str) -> str:
    """A first guess at the index to judge a fund against, from its name.

    Group plan funds are named by mandate ('ACTIONS INTERNATIONALES', 'MARCHES
    EMERGENTS'), which is exactly the information needed. Order matters: a name
    can match twice ('actions américaines mondiales'), and the more specific
    mandate is listed first.
    """
    name = (fund_name or "").lower()
    for keywords, symbol in BENCHMARK_HINTS:
        if any(k in name for k in keywords):
            return symbol
    return ""


# --- the whole plan ----------------------------------------------------------

def summarize(account: Account, today: Optional[date] = None,
              benchmarks: Optional[dict] = None) -> dict:
    """Everything the Retirement tab shows, computed in one pass.

    `benchmarks` maps symbol -> price history; leave it out and the comparison
    columns simply stay empty. Assembly only - each figure comes from the
    function above that owns it, so the table and the chart can never disagree.
    """
    today = today or _today()
    benchmarks = benchmarks or {}
    total = account.value
    rows = []
    for fund in account.funds:
        perf = fund_return(fund)
        mine = personal_return(fund, today)
        value = fund.value
        row = {
            "id": fund.id,
            "name": fund.name,
            "value": value,
            "weight_pct": (value / total * 100.0) if (total and value) else None,
            "units": fund.latest.units if fund.latest else None,
            "unit_value": fund.latest.unit_value if fund.latest else None,
            "as_of": fund.latest.date if fund.latest else None,
            "statements": len(fund.snapshots),
            "benchmark": fund.benchmark,
            "benchmark_pct": None,
            "excess_pct": None,
            "invested": mine["invested"],
            "employer": mine["employer"],
            "gain": mine["gain"],
            "return": perf,
            "personal": mine,
            "flags": unrecorded_units(fund),
        }
        if fund.benchmark and perf["usable"] and perf["cumulative_pct"] is not None:
            bench = window_return(benchmarks.get(fund.benchmark), perf["start"], perf["end"])
            if bench is not None:
                row["benchmark_pct"] = bench * 100.0
                row["excess_pct"] = perf["cumulative_pct"] - bench * 100.0
        rows.append(row)

    rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0.0)))
    ranked = [r for r in rows if r["return"]["usable"]]
    ranked.sort(key=lambda r: r["return"]["cumulative_pct"], reverse=True)

    dates = account.statement_dates
    last_date = _parse_date(dates[-1]) if dates else None
    stale_days = (today - last_date).days if last_date else None

    invested = sum(r["invested"] or 0.0 for r in rows)
    employer = sum(r["employer"] or 0.0 for r in rows)
    gains = [r["gain"] for r in rows if r["gain"] is not None]

    data = {
        "account": account.name,
        "currency": account.currency,
        "total_value": total,
        "funds": rows,
        "ranked": ranked,
        "best": ranked[0] if ranked else None,
        "worst": ranked[-1] if len(ranked) > 1 else None,
        "statement_dates": dates,
        "as_of": dates[-1] if dates else None,
        "stale_days": stale_days,
        "invested_since_start": invested,
        "employer_since_start": employer,
        "gain": sum(gains) if gains else None,
        "comparable": len(ranked),
        "horizons": available_horizons(account),
        "published": plan_published(account, "1y"),
        "needs": _needs(account, rows, stale_days),
    }
    data["text"] = _headline(data)
    return data


def _needs(account: Account, rows: list, stale_days: Optional[int]) -> list:
    """What is stopping this from being a full picture, in plain language."""
    out = []
    if not account.funds:
        out.append("No funds yet — add one per line of your statement.")
        return out
    thin = [r["name"] for r in rows if r["statements"] < 2]
    if thin:
        out.append("Only one statement on file for " + ", ".join(thin)
                   + " — a second date is what turns a balance into a return.")
    if stale_days is not None and stale_days > STALE_DAYS:
        out.append(f"Your newest statement is {stale_days} days old.")
    unpriced = [r["name"] for r in rows
                if r["statements"] >= 2 and r["return"].get("method") == BY_DIETZ]
    if unpriced:
        out.append("No unit values for " + ", ".join(unpriced)
                   + " — returns there are corrected for contributions rather "
                     "than measured, so they depend on every contribution "
                     "being recorded.")
    no_sheet = [f.name for f in account.funds if not f.published]
    if no_sheet:
        out.append("No fund fact sheet on file for " + ", ".join(no_sheet)
                   + " — the plan publishes each fund against its own benchmark "
                     "over horizons you cannot rebuild from statements.")
    elif account.fee_pct is None and all(f.fee_pct is None for f in account.funds):
        out.append("No fee recorded — published returns are struck before the "
                   "plan's investment management fee, so 'beats its index' is "
                   "not yet 'beats its index after what you pay'.")
    sheets = [f.latest_sheet for f in account.funds if f.latest_sheet]
    statements = [r["as_of"] for r in rows if r["as_of"]]
    if sheets and statements:
        # A sheet is quarterly and a statement is whenever you looked; saying so
        # stops the two dates being read as one picture of the same day.
        gap = (_parse_date(max(statements)) - _parse_date(max(sheets))).days
        if gap > SHEET_LAG_DAYS:
            out.append(f"Newest fund fact sheet is dated {max(sheets)}, "
                       f"{gap} days behind your balances — published returns "
                       "describe the fund up to that date, not since.")
    unmatched = [r["name"] for r in rows if not r["benchmark"]]
    if unmatched:
        out.append("No index set for " + ", ".join(unmatched)
                   + " — used only between fact sheets; the plan's own benchmark "
                     "is the better comparison when a sheet is on file.")
    for r in rows:
        for flag in r["flags"]:
            out.append(f"{r['name']}: units changed between {flag['from']} and "
                       f"{flag['to']} by about ${flag['implied']:,.0f} with "
                       f"${flag['recorded']:,.0f} recorded — a missing contribution?")
    return out


def _headline(data: dict) -> str:
    if not data["funds"]:
        return "Add the funds from your statement to see how each one is doing."
    total = data["total_value"]
    ccy = data["currency"]
    head = f"{data['account'] or 'Plan'}: ${total:,.2f} {ccy}"
    if data["as_of"]:
        head += f" as of {data['as_of']}"
    head += f" across {len(data['funds'])} funds."
    if data["comparable"] < 2:
        return head + (" Enter a second statement date to rank them against "
                       "each other.")
    best, worst = data["best"], data["worst"]
    head += (f" Best {best['name']} {best['return']['cumulative_pct']:+.1f}%, "
             f"weakest {worst['name']} {worst['return']['cumulative_pct']:+.1f}%")
    days = best["return"]["days"]
    if days:
        head += f" over {days} days"
    return head + "."


def rebased(account: Account, base: float = 100.0) -> dict:
    """Every fund's price history restated to a common starting point.

    Funds priced in dollars per unit at wildly different levels ($9.85 versus
    $61.40) cannot be read against each other on one chart; rebased to 100 at
    each fund's first statement, the lines are directly comparable and the
    laggard is visible without reading a single number. Only unit values are
    used - a dollar balance grows when you contribute, and a chart that treats
    that as performance would be actively misleading.
    """
    out = {}
    for fund in account.funds:
        priced = [s for s in fund.snapshots if s.on is not None and s.unit_value]
        if len(priced) < 2:
            continue
        first = priced[0].unit_value
        if not first:
            continue
        out[fund.name] = {"dates": [s.date for s in priced],
                          "values": [s.unit_value / first * base for s in priced]}
    return out


# --- pasting a statement -----------------------------------------------------

_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b"), (1, 2, 3)),
    (re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b"), (3, 2, 1)),
]


# Fund fact sheets date themselves in words ("au 31 mars 2026"), and a Canadian
# plan's are issued in both languages, so both are read.
_MONTHS = {
    "janvier": 1, "january": 1, "fevrier": 2, "février": 2, "february": 2,
    "mars": 3, "march": 3, "avril": 4, "april": 4, "mai": 5, "may": 5,
    "juin": 6, "june": 6, "juillet": 7, "july": 7, "aout": 8, "août": 8,
    "august": 8, "septembre": 9, "september": 9, "octobre": 10, "october": 10,
    "novembre": 11, "november": 11, "decembre": 12, "décembre": 12,
    "december": 12,
}
_WORD_DATE = re.compile(r"\b(\d{1,2})\s+([a-zA-Zéèûôàî]+)\s+(\d{4})\b")


def _find_date(text: str) -> Optional[date]:
    for pattern, (y, m, d) in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return date(int(match.group(y)), int(match.group(m)), int(match.group(d)))
            except ValueError:
                continue
    match = _WORD_DATE.search(text or "")
    if match:
        month = _MONTHS.get(match.group(2).strip().lower())
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                return None
    return None


def parse_statement(text: str, on: Optional[date] = None) -> dict:
    """Turn a statement pasted out of the plan's website into fund rows.

    One fund per line. The line is read as: a name, then its numbers in the
    order the statement prints them. Two numbers are read as units and unit
    value (their product being the balance); one number is read as the balance
    alone. Lines with no number at all are section headings ('FONDS D'ACTIONS
    CANADIENNES') and are skipped rather than turned into empty funds.

    A date anywhere in the text applies to every row; `on` is the fallback.
    Returns {"date", "rows", "skipped"} - never writes anything itself, so the
    UI can show what it understood before committing.
    """
    when = _find_date(text or "") or on or _today()
    rows, skipped = [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # Numbers first: a name is whatever is left once they are removed.
        numbers = re.findall(r"-?\d[\d\s  ]*(?:[.,]\d+)?\s*\$?", line)
        cleaned = [parse_number(n) for n in numbers]
        cleaned = [c for c in cleaned if c is not None]
        name = line
        for token in numbers:
            name = name.replace(token, " ")
        name = re.sub(r"[\s\|\t;,]+", " ", name).strip(" -|\t;:")
        if not name:
            skipped.append(line)
            continue
        if not cleaned:
            skipped.append(line)          # a section heading, not a fund
            continue
        if len(cleaned) >= 2:
            units, unit_value = cleaned[0], cleaned[1]
            rows.append({"name": name, "units": units, "unit_value": unit_value,
                         "value": units * unit_value, "date": when.isoformat()})
        else:
            rows.append({"name": name, "units": None, "unit_value": None,
                         "value": cleaned[0], "date": when.isoformat()})
    return {"date": when.isoformat(), "rows": rows, "skipped": skipped}


# --- reading a fund fact sheet -----------------------------------------------

_HORIZON_WORDS = [
    (("10 an", "10 year", "10ans"), "10y"),
    (("5 an", "5 year", "5ans"), "5y"),
    (("4 an", "4 year", "4ans"), "4y"),
    (("3 an", "3 year", "3ans"), "3y"),
    (("2 an", "2 year", "2ans"), "2y"),
    (("1 an", "1 year", "1an"), "1y"),
    (("3 mois", "3 month", "3mois"), "3m"),
]


def _horizons_in(line: str) -> list:
    """Read a sheet's column headers in the order they are printed.

    Never assume the order: a sheet that drops the 10-year column (a fund
    younger than that) would otherwise shift every figure one column left and
    report the 5-year return as a decade's.
    """
    text = (line or "").lower()
    found = []
    for keywords, horizon in _HORIZON_WORDS:
        for keyword in keywords:
            position = text.find(keyword)
            if position >= 0:
                found.append((position, horizon))
                break
    found.sort()
    return [h for _, h in found]


def _percentages(line: str) -> list:
    """Every percentage on a line, in order. '-2,41 %' and '17,84 %' both."""
    out = []
    for token in re.findall(r"-?\d+[.,]?\d*\s*%", line or ""):
        value = parse_number(token)
        if value is not None:
            out.append(value)
    return out


def parse_published(text: str, as_of: Optional[date] = None) -> dict:
    """Read the 'compound returns' block off a fund fact sheet.

    Expects the two lines the sheet prints - one starting 'Fonds'/'Fund', one
    starting 'Indice'/'Index' - and, when it is included, the header row naming
    the horizons. The date is taken from anywhere in the text ('au 31 mars
    2026'), because a return without the date it was struck on is unusable a
    quarter later.

    Returns {"as_of", "records", "reason"}; `records` is empty and `reason`
    explains why when the block could not be read.
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    when = _find_date(text or "") or as_of
    if when is None:
        return {"as_of": None, "records": [],
                "reason": "No date found — a published return needs the date it "
                          "was struck on ('au 31 mars 2026')."}

    horizons, fund_row, index_row = [], None, None
    for line in lines:
        lowered = line.lower()
        if not horizons:
            candidates = _horizons_in(line)
            # A header row names horizons and carries no percentages of its own.
            if len(candidates) >= 2 and not _percentages(line):
                horizons = candidates
                continue
        if fund_row is None and (lowered.startswith("fonds") or lowered.startswith("fund")):
            fund_row = _percentages(line)
        elif index_row is None and (lowered.startswith("indice") or lowered.startswith("index")):
            index_row = _percentages(line)
    if not fund_row:
        return {"as_of": when.isoformat(), "records": [],
                "reason": "No 'Fonds' row found — paste the compound returns "
                          "table, including its row labels."}
    if not horizons:
        horizons = HORIZONS[:len(fund_row)]
    if len(horizons) != len(fund_row):
        return {"as_of": when.isoformat(), "records": [],
                "reason": f"{len(fund_row)} fund figures against {len(horizons)} "
                          f"column headings — paste the header row too."}

    records = []
    for i, horizon in enumerate(horizons):
        index_pct = (index_row[i] if index_row and i < len(index_row) else None)
        records.append(Published(as_of=when.isoformat(), horizon=horizon,
                                 fund_pct=fund_row[i], index_pct=index_pct))
    return {"as_of": when.isoformat(), "records": records, "reason": ""}


def published_rows(account: Account, horizon: str = "1y") -> list:
    """Every fund's published return over one horizon, with the fee applied.

    A sheet's return is struck *before* the plan's investment management fee,
    so 'beat the index by 1.5 points' and 'beat the index after what you pay'
    are different statements. Both are reported: `excess_pct` as published,
    `net_excess_pct` with the fee subtracted. The fee is an annual rate, so it
    is left off the 3-month row rather than pretending a quarter costs a year.
    """
    out = []
    total = account.value
    for fund in account.funds:
        record = fund.published_on(horizon=horizon)
        value = fund.value
        fee = account.fee_for(fund)
        row = {"id": fund.id, "name": fund.name, "code": fund.code,
               "value": value,
               "weight_pct": (value / total * 100.0) if (total and value) else None,
               "as_of": record.as_of if record else None,
               "fund_pct": record.fund_pct if record else None,
               "index_pct": record.index_pct if record else None,
               "excess_pct": record.excess_pct if record else None,
               "fee_pct": fee, "net_pct": None, "net_excess_pct": None}
        if record and fee is not None and horizon != "3m":
            row["net_pct"] = record.fund_pct - fee
            if record.excess_pct is not None:
                row["net_excess_pct"] = record.excess_pct - fee
        out.append(row)
    out.sort(key=lambda r: (r["fund_pct"] is None, -(r["fund_pct"] or 0.0)))
    return out


def plan_published(account: Account, horizon: str = "1y") -> dict:
    """The plan's own return over a horizon, weighted by what you actually hold.

    Not an average of the funds - a 17% weight and a 12% weight do not count
    the same. Funds with no sheet on file are excluded and named, and
    `covered_pct` says how much of the plan the figure actually speaks for: a
    number covering 60% of the money is worth reading differently from one
    covering all of it.
    """
    rows = published_rows(account, horizon)
    priced = [r for r in rows if r["fund_pct"] is not None and r["weight_pct"]]
    covered = sum(r["weight_pct"] for r in priced)
    if not priced or covered <= 0:
        return {"horizon": horizon, "fund_pct": None, "index_pct": None,
                "excess_pct": None, "net_pct": None, "covered_pct": 0.0,
                "missing": [r["name"] for r in rows if r["fund_pct"] is None],
                "as_of": None, "text": "No fund fact sheets on file yet."}

    def weighted(key):
        parts = [(r["weight_pct"], r[key]) for r in priced if r[key] is not None]
        weight = sum(w for w, _ in parts)
        return (sum(w * v for w, v in parts) / weight) if weight else None

    fund_pct = weighted("fund_pct")
    index_pct = weighted("index_pct")
    net_pct = weighted("net_pct")
    as_of = max((r["as_of"] for r in priced if r["as_of"]), default=None)
    label = HORIZON_LABELS.get(horizon, horizon)
    text = f"Weighted by what you hold, your plan returned {fund_pct:+.2f}% over {label}"
    if index_pct is not None:
        text += f" against {index_pct:+.2f}% for the funds' own benchmarks"
    if net_pct is not None:
        text += f"; {net_pct:+.2f}% after the fee you pay"
    if covered < 99.5:
        text += f" (covering {covered:.0f}% of the plan)"
    return {"horizon": horizon, "fund_pct": fund_pct, "index_pct": index_pct,
            "excess_pct": (None if index_pct is None else fund_pct - index_pct),
            "net_pct": net_pct, "covered_pct": covered,
            "missing": [r["name"] for r in rows if r["fund_pct"] is None],
            "as_of": as_of, "text": text + "."}


def available_horizons(account: Account) -> list:
    """Horizons at least one fund has a published figure for, shortest first."""
    have = {p.horizon for f in account.funds for p in f.published}
    return [h for h in HORIZONS if h in have]


# --- persistence -------------------------------------------------------------

class RetirementBook:
    """JSON-backed list of Account (retirement.json in the data folder).

    Deliberately a file rather than a table in the app database: it is a small,
    hand-maintained record the user may well want to read, copy or hand-edit,
    the same reasoning as the trade journal.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else RETIREMENT_PATH
        self.accounts: list = []
        self.load()

    def load(self):
        self.accounts = []
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item in (raw.get("accounts") if isinstance(raw, dict) else raw) or []:
            try:
                self.accounts.append(Account(**item))
            except TypeError:
                continue

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"accounts": [asdict(a) for a in self.accounts]}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    def account(self, name_or_id: str) -> Optional[Account]:
        key = (name_or_id or "").strip().lower()
        for a in self.accounts:
            if a.id == name_or_id or a.name.lower() == key:
                return a
        return None

    def add_account(self, account: Account) -> Account:
        self.accounts.append(account)
        self.save()
        return account

    def remove_account(self, name_or_id: str) -> bool:
        account = self.account(name_or_id)
        if account is None:
            return False
        self.accounts = [a for a in self.accounts if a.id != account.id]
        self.save()
        return True

    def apply_statement(self, account: Account, rows: list) -> dict:
        """Write parsed statement rows into `account`, creating funds that are
        new and dating every row the same day. Returns what changed, so the UI
        can report '3 funds updated, 1 added' instead of going quiet."""
        added, updated = [], []
        for row in rows:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            fund = account.fund(name)
            if fund is None:
                fund = account.add_fund(Fund(name=name,
                                             benchmark=suggest_benchmark(name)))
                added.append(name)
            else:
                updated.append(name)
            fund.add_snapshot(Snapshot(date=row.get("date"), units=row.get("units"),
                                       unit_value=row.get("unit_value"),
                                       value=row.get("value")))
        self.save()
        return {"added": added, "updated": updated}
