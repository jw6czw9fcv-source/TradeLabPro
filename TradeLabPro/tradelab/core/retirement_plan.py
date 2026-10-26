"""Year-by-year retirement projection — the calculation half of the Retirement
simulator.

The Retirement tab *tracks* a workplace plan: what it was worth, what it
returned, whether a fund beat its own index. This module answers the other
question — given what you hold, what you'll draw, and what you assume, how
long does it last.

It computes; it does not advise. Every judgement is an input: the return, the
inflation rate, the spending, the order accounts are drawn from, the age each
benefit starts. Nothing here picks a withdrawal strategy or says whether a
plan is good.

**Everything is in the dollars of the year it happens.** The return you give
is the nominal one — what a fund actually reports — and `inflation` is
projected explicitly rather than folded into it. So the RRQ grows year by
year the way it really does, spending rises to match, and the balances are
the numbers that would appear on a statement.

The cost of that choice is that "$1.2M in 2055" is not a figure anyone can
price, so callers are expected to offer a deflated view; `real_from_nominal`
and the `deflate` helper are here for it. The gain is that every input is
something you can look up: nobody knows their real return, and everybody
knows what their pension is worth today.

Three things move with inflation and one deliberately does not:

* Incomes marked `indexed` — the RRQ, PSV and AOW, indexed by law — grow at
  the rate. A fixed private pension is marked `indexed=False` and stays at
  its nominal amount, which is exactly what such a pension does.
* Spending grows at the rate, since a household's costs do.
* The tax brackets and most credit amounts grow, because both governments
  index them. Leaving them frozen while incomes inflated would invent
  bracket creep that will not happen — an error that compounds with the
  horizon. See `TaxYear.inflated`.
* The federal pension income amount does not grow, because it is not
  indexed in law. In a nominal projection that falls out correctly for free.

Qt-free and offline-testable; no network, no I/O.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import date

# Account kinds. The difference that matters is how the money is taxed and
# whether a withdrawal can be forced:
#   REGISTERED   REER/FERR/FTQ - every withdrawal is the owner's income, taxed
#                like a RRIF payment (eligible pension income from 65), and
#                after the year the holder turns 71 a minimum *must* come out
#                whether it is needed or not. Covering a gap takes more than the
#                gap: the withdrawal has to pay its own tax too.
#   TFSA         CELI - neither growth nor withdrawals are income, and nothing
#                forces one. A withdrawal comes back as room the next year.
#   TAXABLE      non-registered - growth is taxed as a capital gain (half of it
#                is income) the year after it happens, as though the account
#                were realised every year. That is a little early for a
#                buy-and-hold investor, never late: deferring it instead would
#                leave a tax bill hidden inside the closing balance.
REGISTERED, TFSA, TAXABLE = "registered", "tfsa", "taxable"

# The year a registered plan must start paying out: the holder turns 71 during
# the previous year. Verified against the CRA's prescribed-factor chart, which
# also gives the factor for every age from 71.
RRIF_CONVERSION_AGE = 71

# CRA prescribed factors, "All other RRIFs" column (a plan opened after 1992).
# Source: canada.ca, Chart - Prescribed factors. Under 71 the factor is
# 1/(90-age), which is why only 71+ is tabulated here.
RRIF_FACTORS = {
    71: 0.0528, 72: 0.0540, 73: 0.0553, 74: 0.0567, 75: 0.0582,
    76: 0.0598, 77: 0.0617, 78: 0.0636, 79: 0.0658, 80: 0.0682,
    81: 0.0708, 82: 0.0738, 83: 0.0771, 84: 0.0808, 85: 0.0851,
    86: 0.0899, 87: 0.0955, 88: 0.1021, 89: 0.1099, 90: 0.1192,
    91: 0.1306, 92: 0.1449, 93: 0.1634, 94: 0.1879,
}
RRIF_FACTOR_95_PLUS = 0.2000


def rrif_minimum_factor(age: int) -> float:
    """The prescribed factor for a holder of this age on January 1.

    Under 71 the regulation gives 1/(90 - age) — which is why a plan converted
    early still has a minimum, a fact that surprises people who convert at 65
    to get the pension income credit.
    """
    if age >= 95:
        return RRIF_FACTOR_95_PLUS
    if age >= RRIF_CONVERSION_AGE:
        return RRIF_FACTORS[age]
    if age >= 90:                      # unreachable, but keeps the intent clear
        return RRIF_FACTOR_95_PLUS
    return 1.0 / (90 - age)


# Deferring a public pension raises it permanently, by a published rate per
# month of delay. These are the rules, not a view on whether to use them:
# whether a larger cheque later beats a smaller one sooner depends on how long
# you live, what the survivor keeps, and what you need in the meantime - none
# of which this module knows.
#
# RRQ:  +0.7%/month after 65, stopping at 72 (+58.8%). Source: Retraite Québec,
#       "At what age should you apply for your retirement pension?", read 2026-10-12.
# PSV:  +0.6%/month after 65, stopping at 70 (+36%); it cannot start before 65.
#       Source: canada.ca, "Old Age Security - When to start", read 2026-10-12.
# Starting the RRQ *before* 65 lowers it by 0.5% to 0.6% a month depending on the
# pension's size, which this cannot know - an amount typed for an earlier start is
# used as typed.
DEFERRAL = {
    "RRQ": {"rate_per_month": 0.007, "from_age": 65, "max_age": 72},
    "PSV": {"rate_per_month": 0.006, "from_age": 65, "max_age": 70},
}


def deferred_amount(base_at_65: float, start_age: int, rule: dict) -> float:
    """What a benefit becomes if taken at `start_age` instead of 65.

    Taking it *before* 65 also changes it, by a different rule that is not
    modelled here — this returns the base unchanged rather than guessing.
    """
    from_age, max_age = rule["from_age"], rule["max_age"]
    if start_age <= from_age:
        return float(base_at_65)
    months = (min(start_age, max_age) - from_age) * 12
    return float(base_at_65) * (1.0 + months * rule["rate_per_month"])


@dataclass
class Account:
    """One holding. `owner` matters because registered withdrawals are the
    owner's income, and the RRIF minimum follows the owner's age."""
    name: str
    kind: str
    balance: float
    owner: str


# What the OAS pension is called in an Incomes table, read case-insensitively.
OAS_NAMES = {"psv", "sv", "oas", "pension de la sécurité de la vieillesse",
             "sécurité de la vieillesse", "old age security"}
# And the Québec Pension Plan. The federal CPP is left out on purpose: its
# deferral stops at 70, not 72, and applying the RRQ's rule to it would be wrong.
QPP_NAMES = {"rrq", "qpp", "régime de rentes du québec", "quebec pension plan",
             "rente de retraite du rrq"}


@dataclass
class Income:
    """A benefit or wage, in today's dollars per year.

    `starts_at_age` is the owner's age when it begins and `ends_at_age` when
    it stops (None = for life). A wage is just an income that ends.

    `annual` is what it is worth *today*; the projection grows it from there.

    `indexed` says whether it rises with inflation. True for the RRQ, the PSV
    and the AOW, which are indexed by law; false for a fixed private pension,
    which pays the same cheque for thirty years and therefore buys steadily
    less. Defaulting to True keeps the common case right, and makes a frozen
    pension something you state deliberately rather than a silent surprise.
    """
    name: str
    owner: str
    annual: float
    starts_at_age: int = 0
    ends_at_age: int | None = None
    indexed: bool = True
    # Whether this is the OAS pension (PSV), which is clawed back above an
    # income threshold. None reads it from the name - see `is_oas`.
    oas: bool | None = None
    # For the RRQ and the PSV, `annual` is the amount at 65 and a later start
    # adds the increase the law gives for waiting (DEFERRAL). False uses the
    # amount as typed whatever the start.
    apply_deferral: bool = True

    def _plain_name(self) -> str:
        return " ".join(str(self.name or "").lower().split())

    @property
    def is_oas(self) -> bool:
        """The OAS pension, recognised by what people call it - PSV, SV, OAS,
        Old Age Security, Sécurité de la vieillesse - unless set explicitly."""
        if self.oas is not None:
            return bool(self.oas)
        name = self._plain_name()
        return (name in OAS_NAMES or name.startswith(("psv", "oas "))
                or "old age security" in name or "sécurité de la vieillesse" in name)

    @property
    def benefit(self) -> str | None:
        """'PSV' or 'RRQ' when this is one of the two public pensions whose
        deferral rule is modelled, else None."""
        if self.is_oas:
            return "PSV"
        name = self._plain_name()
        if name in QPP_NAMES or name.startswith("rrq"):
            return "RRQ"
        return None

    @property
    def deferral_increase(self) -> float:
        """The share added for starting after 65 - 0.36 for a PSV taken at 70,
        0 when nothing is added."""
        rule = DEFERRAL.get(self.benefit) if self.apply_deferral else None
        if not rule:
            return 0.0
        return deferred_amount(1.0, int(self.starts_at_age or 0), rule) - 1.0

    def amount_at(self, age: int, years_elapsed: int = 0,
                  inflation: float = 0.0) -> float:
        """The cheque actually written that year, in that year's dollars."""
        if age < self.starts_at_age:
            return 0.0
        if self.ends_at_age is not None and age > self.ends_at_age:
            return 0.0
        amount = float(self.annual) * (1.0 + self.deferral_increase)
        if self.indexed and inflation and years_elapsed > 0:
            amount *= (1.0 + inflation) ** years_elapsed
        return amount


@dataclass
class Person:
    name: str
    age: int


@dataclass
class Plan:
    """Everything the projection needs, all of it supplied by the person whose
    plan it is."""
    people: list[Person]
    accounts: list[Account]
    incomes: list[Income] = field(default_factory=list)
    # Household spending in *today's* dollars. It grows with inflation from
    # there: a retirement's costs rise like everything else, and holding this
    # flat in a nominal projection would flatter the plan enormously.
    spending: float = 0.0
    # The nominal return - what a fund reports, with inflation still in it.
    # 0.05 means five percent, full stop.
    nominal_return: float = 0.05
    # Projected explicitly rather than netted out of the return. It grows the
    # indexed incomes, the spending, and the tax brackets.
    inflation: float = 0.02
    # One return per year, when the caller has a sequence rather than an
    # average. This is what makes sequence risk visible: the same numbers in a
    # different order are a different retirement, and a single average cannot
    # say so.
    returns: list | None = None
    # Which accounts to draw from first. Order is a decision with real tax
    # consequences and it belongs to the person, not to this module; the
    # default is simply the order the accounts were given in.
    withdrawal_order: list[str] | None = None
    years: int = 35
    # The calendar year row 0 stands for. Defaults to the year the projection
    # is run: "2033" is something you can hold against a birthday, "year 7"
    # is arithmetic the reader has to do themselves.
    start_year: int | None = None
    # Tax on the year's taxable income. Called with ({owner: taxable},
    # {owner: age}, {owner: pension_income}, years_elapsed) - per person, not
    # as one household total, because two people are taxed as two people and
    # only *eligible pension* income can be moved between them. The last
    # argument lets the callee index the brackets to the right year; a tax_fn
    # that ignores it still works. Injected so the ledger can be tested
    # without a tax model and the rules can change without touching it.
    tax_fn: object = None
    # After-tax income beyond the spending - a RRIF minimum that was not
    # needed, a wage still coming in - is saved instead of vanishing from the
    # ledger: into the TFSA while there is room, then a non-registered account,
    # both drawn last. Until this existed it did vanish: on a real plan,
    # several hundred thousand dollars over thirty years, which made every
    # projection too pessimistic and made spending less look nearly worthless.
    # Off only for comparison.
    reinvest_surplus: bool = True
    # Unused TFSA contribution room each person has today, by name - CRA's My
    # Account shows it. A name left out counts as none, which can only make the
    # plan look poorer than it is, never richer.
    tfsa_room: dict | None = None
    # The TFSA dollar limit for a calendar year, per person - injected like the
    # tax model (see tax_quebec.tfsa_dollar_limit). None adds no new room.
    tfsa_limit: object = None
    # The share of a capital gain that is taxable income. One half: the
    # increase to two-thirds was cancelled federally (21 March 2025) and in
    # Québec (25 November 2025) - see tax_quebec.CAPITAL_GAINS_INCLUSION.
    gains_inclusion: float = 0.5
    # Drawing a REER down early: each year before `meltdown_until_age`, take
    # enough more from the registered accounts to bring each owner's taxable
    # income up to `meltdown_to` (today's dollars, indexed), even if the
    # spending does not need it - the extra is saved like any surplus (TFSA
    # first). None draws nothing extra. Taken as RRIF payments, so from 65 they
    # count as eligible pension income.
    meltdown_to: float | None = None
    meltdown_until_age: int = 71


# Where the surplus goes: the TFSA first, while there is room, because what
# grows there is never taxed; then a non-registered account, whose growth is.
SURPLUS_TFSA_ACCOUNT = "Surplus in TFSA"
SURPLUS_ACCOUNT = "Surplus reinvested"


# What happens *during* the year — the cheques, the tax, the withdrawals — and
# the balance the year opens with. All of it is priced at the start of the year.
FLOW_KEYS = ("opening", "income", "forced_withdrawal", "tax", "oas_recovery",
             "drawn_from_capital", "surplus", "surplus_tfsa", "taxable_gains",
             "spending", "unfunded")
# Amounts measured *after* the year's growth, which is a year later and so a
# year further from today's prices. Deflating them by the opening factor,
# which an earlier draft did, quietly overstated every closing balance by one
# year of inflation.
CLOSING_KEYS = ("closing", "tfsa_room")


def deflate(rows: list[dict]) -> list[dict]:
    """The same rows read in today's dollars.

    A nominal projection is built from figures you can look up, and then ends
    with a balance in 2055 that means nothing to anybody. This converts it
    back for reading — every money column and the per-owner breakdown, using
    the deflators each row already carries. Rates, ages and years are left
    alone.
    """
    out = []
    for row in rows:
        opening = float(row.get("deflator") or 1.0) or 1.0
        closing = float(row.get("closing_deflator") or opening) or opening
        copy = dict(row)
        for key in FLOW_KEYS:
            if isinstance(copy.get(key), (int, float)):
                copy[key] = copy[key] / opening
        for key in CLOSING_KEYS:
            if isinstance(copy.get(key), (int, float)):
                copy[key] = copy[key] / closing
        if isinstance(copy.get("income_by_owner"), dict):
            copy["income_by_owner"] = {k: v / opening
                                       for k, v in copy["income_by_owner"].items()}
        if isinstance(copy.get("balances"), dict):
            copy["balances"] = {k: v / closing for k, v in copy["balances"].items()}
        out.append(copy)
    return out


def real_from_nominal(nominal: float, inflation: float) -> float:
    """The Fisher relation, not a subtraction.

    Most people know what they expect a portfolio to return in nominal terms
    and have no figure at all for the real one. 6% with 2% inflation is 3.92%
    real, not 4% — small here, but it compounds over thirty years, and the
    subtraction is always the optimistic direction.
    """
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


def nominal_from_real(real: float, inflation: float) -> float:
    """The inverse, for showing what a real return implies in nominal terms."""
    return (1.0 + real) * (1.0 + inflation) - 1.0


def _tax_caller(fn):
    """Normalise an injected `tax_fn` to the five-argument form ->
    (callable, whether it knows the OAS clawback).

    The year offset only matters to a model that indexes its brackets, and the
    OAS amounts only to one that claws them back; a flat rate, or any of the
    stand-ins the ledger is tested with, has no use for either and should not
    have to grow arguments it ignores. The arity is read once here rather than
    by catching TypeError around each call, which would silently swallow a
    real TypeError raised inside the callee.
    """
    if fn is None:
        return None, False
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):        # a builtin or C callable
        return (lambda by_owner, ages, pension, year, _oas: fn(by_owner, ages, pension, year)), False
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) >= 5 or any(p.kind == p.VAR_POSITIONAL for p in params):
        return fn, True
    if len(positional) == 4:
        return (lambda by_owner, ages, pension, year, _oas: fn(by_owner, ages, pension, year)), False
    return (lambda by_owner, ages, pension, _year, _oas: fn(by_owner, ages, pension)), False


def _order(plan: Plan) -> list[Account]:
    if not plan.withdrawal_order:
        return list(plan.accounts)
    rank = {name: i for i, name in enumerate(plan.withdrawal_order)}
    return sorted(plan.accounts, key=lambda a: rank.get(a.name, len(rank)))


def _unused_name(name: str, taken) -> str:
    """`name`, made distinct from every account the person named: a surplus
    account is never merged into a real one."""
    while name in taken:
        name += " "
    return name


def gross_up(needed: float, available: float, added_tax) -> tuple:
    """The withdrawal that still leaves `needed` once the tax it adds is paid.

    A dollar out of a RRIF is income, so covering a $10,000 gap takes more than
    $10,000 - how much more depends on where the withdrawal lands in the
    brackets and the credits it erodes, which is why this solves for it rather
    than assume a rate. `added_tax(w)` is the extra tax a withdrawal of `w`
    causes; at most `available` can come out. Returns (withdrawal, tax added).
    When even everything available does not cover the need, everything comes
    out.

    Regula falsi with the Illinois correction: what is left after tax rises
    with the withdrawal (no marginal rate reaches 100%), so the answer is
    always bracketed, and the correction keeps a kinked tax schedule from
    stalling it.
    """
    if needed <= 0 or available <= 0:
        return 0.0, 0.0
    tax_hi = added_tax(available)
    if available - tax_hi <= needed:
        return available, tax_hi
    lo, hi = needed, available
    tax_lo = added_tax(lo)
    f_lo, f_hi = lo - tax_lo - needed, available - tax_hi - needed
    if f_lo >= 0:                          # a withdrawal that adds no tax
        return lo, tax_lo
    side = 0
    for _ in range(100):
        x = (lo * f_hi - hi * f_lo) / (f_hi - f_lo)
        tax_x = added_tax(x)
        f_x = x - tax_x - needed
        if abs(f_x) < 0.01:
            return x, tax_x
        if f_x < 0:
            lo, f_lo = x, f_x
            if side == -1:
                f_hi /= 2.0
            side = -1
        else:
            hi, tax_hi, f_hi = x, tax_x, f_x
            if side == 1:
                f_lo /= 2.0
            side = 1
        if hi - lo < 0.01:
            break
    return hi, tax_hi                      # the side that never leaves the need short


def project(plan: Plan) -> list[dict]:
    """One row per year: incomes, forced withdrawals, what had to be drawn to
    meet the spending, tax, and the closing balance.

    Returns as many rows as `plan.years`, and keeps going after the money runs
    out — a plan that fails at 84 should show what the following years look
    like, not stop and leave the reader to guess.
    """
    balances = {a.name: float(a.balance) for a in plan.accounts}
    ages = {p.name: p.age for p in plan.people}
    names = [p.name for p in plan.people]
    start_year = plan.start_year or date.today().year
    accounts = _order(plan)
    tax_fn, knows_oas = _tax_caller(plan.tax_fn)
    surplus_name = tfsa_name = None
    if plan.reinvest_surplus and plan.people:
        surplus_name = _unused_name(SURPLUS_ACCOUNT, balances)
        balances[surplus_name] = 0.0
        tfsa_name = _unused_name(SURPLUS_TFSA_ACCOUNT, balances)
        balances[tfsa_name] = 0.0
        # Last in the withdrawal order: they hold what the plan saved beyond
        # its needs, so they are the last thing to spend - the taxed one
        # before the one that grows tax-free.
        accounts = accounts + [Account(surplus_name, TAXABLE, 0.0, ""),
                               Account(tfsa_name, TFSA, 0.0, "")]
    # The household's TFSA room: what each person has today, then each year's
    # new limit per person and the withdrawals of the year before.
    room = sum(max(0.0, float((plan.tfsa_room or {}).get(name) or 0.0)) for name in names)
    restored = 0.0
    # Capital gains already earned and declared the following year, by owner;
    # losses carried forward against later gains, by account.
    gains_due, losses = {}, {}
    rows = []

    for year in range(plan.years):
        calendar_year = start_year + year
        if year:
            if plan.tfsa_limit is not None:
                room += float(plan.tfsa_limit(calendar_year)) * len(names)
            room += restored
        restored = 0.0
        opening = sum(balances.values())

        # 1. Income that arrives whether or not it is wanted, kept per person:
        #    a wage belongs to whoever earned it and cannot be moved.
        by_owner = {name: 0.0 for name in ages}
        oas_by_owner = {}                 # the part that can be clawed back
        for income in plan.incomes:
            owner = income.owner
            amount = income.amount_at(ages.get(owner, 0), year, plan.inflation)
            by_owner[owner] = by_owner.get(owner, 0.0) + amount
            if amount and income.is_oas:
                oas_by_owner[owner] = oas_by_owner.get(owner, 0.0) + amount
        gross_income = sum(by_owner.values())
        # Last year's taxable gains are this year's taxable income - not cash:
        # the money stays invested, only the tax on it is paid from the year.
        taxable_gains = sum(gains_due.values())
        for owner, amount in gains_due.items():
            by_owner[owner] = by_owner.get(owner, 0.0) + amount
        gains_due = {}

        # 2. The registered minimum. It is forced, it is taxable to the
        #    account's *owner*, and it lands in the household's hands whether
        #    the spending needed it or not.
        forced = 0.0
        pension_by_owner = {name: 0.0 for name in ages}
        for account in accounts:
            if account.kind != REGISTERED:
                continue
            age = ages.get(account.owner, 0)
            if age < RRIF_CONVERSION_AGE:
                continue
            take = min(balances[account.name],
                       balances[account.name] * rrif_minimum_factor(age))
            balances[account.name] -= take
            forced += take
            by_owner[account.owner] = by_owner.get(account.owner, 0.0) + take
            # A RRIF withdrawal is what the pension income amount is for.
            pension_by_owner[account.owner] = pension_by_owner.get(
                account.owner, 0.0) + take

        # 2b. A chosen early drawdown: top each owner's taxable income up to
        #     the target while the registered money is there to do it.
        if plan.meltdown_to:
            target = float(plan.meltdown_to) * (1.0 + plan.inflation) ** year
            for account in accounts:
                if account.kind != REGISTERED:
                    continue
                age = ages.get(account.owner, 0)
                if age >= int(plan.meltdown_until_age):
                    continue
                extra = min(balances[account.name],
                            max(0.0, target - by_owner.get(account.owner, 0.0)))
                if extra <= 0:
                    continue
                balances[account.name] -= extra
                forced += extra
                by_owner[account.owner] = by_owner.get(account.owner, 0.0) + extra
                if age >= 65:
                    pension_by_owner[account.owner] = pension_by_owner.get(
                        account.owner, 0.0) + extra

        tax = (float(tax_fn(by_owner, ages, pension_by_owner, year, oas_by_owner))
               if tax_fn else 0.0)
        available = gross_income + forced - tax

        # 3. Whatever the spending still needs comes out of capital, in the
        #    order the person chose. Spending is given in today's dollars and
        #    inflated to the year being lived, like the income it is met from.
        #    A registered withdrawal is the owner's income, so it is grossed up
        #    to pay its own tax; a TFSA or non-registered one is not income.
        spending = plan.spending * (1.0 + plan.inflation) ** year
        shortfall = max(0.0, spending - available)
        drawn = 0.0
        for account in accounts:
            if shortfall <= 0.01:
                break
            balance = balances[account.name]
            if balance <= 0:
                continue
            if account.kind == REGISTERED and tax_fn:
                owner = account.owner
                pension = ages.get(owner, 0) >= 65    # a RRIF payment from 65

                def added_tax(amount, owner=owner, pension=pension, base=tax):
                    incomes = dict(by_owner)
                    incomes[owner] = incomes.get(owner, 0.0) + amount
                    pensions = dict(pension_by_owner)
                    if pension:
                        pensions[owner] = pensions.get(owner, 0.0) + amount
                    return float(tax_fn(incomes, ages, pensions, year, oas_by_owner)) - base

                take, extra = gross_up(shortfall, balance, added_tax)
                by_owner[owner] = by_owner.get(owner, 0.0) + take
                if pension:
                    pension_by_owner[owner] = pension_by_owner.get(owner, 0.0) + take
                tax += extra
                received = take - extra
            else:
                take = received = min(balance, shortfall)
                if account.kind == TFSA:
                    restored += take          # room again next January
            balances[account.name] -= take
            drawn += take
            shortfall -= received
        shortfall = max(0.0, shortfall)
        # How much of the year's tax is OAS paid back: the same bill with and
        # without the clawback, on the year's final incomes.
        oas_recovery = 0.0
        if tax_fn and knows_oas and oas_by_owner:
            oas_recovery = max(0.0, tax - float(
                tax_fn(by_owner, ages, pension_by_owner, year, None)))

        # 4. Anything left after the spending is saved, not lost: into the
        #    TFSA while there is room, the rest where its growth is taxed.
        surplus = max(0.0, available - spending)
        into_tfsa = 0.0
        if surplus_name is not None and surplus > 0:
            into_tfsa = min(surplus, room)
            room -= into_tfsa
            balances[tfsa_name] += into_tfsa
            balances[surplus_name] += surplus - into_tfsa

        # 5. Growth applies to what is left at the end of the year. What a
        #    non-registered account gained is taxed as a capital gain, declared
        #    next year; a loss is carried against later gains.
        growth = plan.nominal_return
        if plan.returns:
            growth = plan.returns[year] if year < len(plan.returns) else plan.returns[-1]
        for account in accounts:
            if account.kind != TAXABLE:
                continue
            gain = balances[account.name] * growth
            carried = losses.get(account.name, 0.0)
            losses[account.name] = max(0.0, carried - gain)
            taxable = max(0.0, gain - carried) * float(plan.gains_inclusion)
            if taxable <= 0:
                continue
            # The surplus account is the household's; anyone else's is its owner's.
            owners = names if account.name == surplus_name else [account.owner]
            for owner in owners:
                gains_due[owner] = gains_due.get(owner, 0.0) + taxable / len(owners)
        for name in balances:
            balances[name] *= (1.0 + growth)

        rows.append({
            "year": year,
            "calendar_year": start_year + year,
            "ages": dict(ages),
            "opening": opening,
            "income": gross_income,
            # Taxable income by person: incomes, registered withdrawals and
            # last year's taxable gains.
            "income_by_owner": dict(by_owner),
            "forced_withdrawal": forced,
            "tax": tax,
            # The part of `tax` that is OAS paid back.
            "oas_recovery": oas_recovery,
            "drawn_from_capital": drawn,
            # After-tax income beyond the spending, saved - and how much of it
            # went into the TFSA.
            "surplus": surplus if surplus_name is not None else 0.0,
            "surplus_tfsa": into_tfsa,
            # Capital gains taxed this year (the taxable half, earned last year).
            "taxable_gains": taxable_gains,
            # TFSA room left at the end of the year, for the whole household.
            "tfsa_room": room,
            # What the spending had grown to by this year, so the reader can
            # see the cost rising rather than infer it from the drawdown.
            "spending": spending,
            # Divide by this to read the year's flows in today's dollars, and
            # by the one below for the balance, which is measured after the
            # year's growth and so is a year further out. Kept per row so a
            # deflated view needs no second run.
            "deflator": (1.0 + plan.inflation) ** year,
            "closing_deflator": (1.0 + plan.inflation) ** (year + 1),
            # What the plan could not fund this year. The whole point of the
            # projection is this number turning positive.
            "unfunded": shortfall,
            "return": growth,
            "closing": sum(balances.values()),
            "balances": dict(balances),
        })
        for name in ages:
            ages[name] += 1

    return rows


def deferrals(plan: Plan) -> list[dict]:
    """The public pensions this plan starts after 65, with the increase the
    law adds for it - so a screen can say why a cheque is larger than the one
    typed, rather than leave it unexplained."""
    out = []
    for income in plan.incomes:
        increase = income.deferral_increase
        if increase > 0:
            out.append({"income": income.name, "owner": income.owner,
                        "starts_at_age": int(income.starts_at_age),
                        "increase_pct": round(increase * 100.0, 2)})
    return out


def compare_start_ages(plan: Plan) -> list[dict]:
    """Each RRQ and PSV of the plan started at every age from 65 to its last
    (72 and 70), one at a time, the rest of the plan as it is.

    One row per income and age: the increase the law adds, what is left at the
    end of the projection in today's dollars, and the calendar year the money
    runs out (None = never). `best` marks, per income, the start that leaves
    the most; `current` the one in the plan. An RRQ typed for a start before 65
    is left out - its amount is the reduced one, which a later start would not
    raise from.

    The ranking holds only for a life as long as the projection: a later start
    pays more each year but for fewer years, so it comes out ahead only past
    the break-even age. A calculation on the plan's assumptions, not advice.
    """
    from dataclasses import replace
    out = []
    for i, income in enumerate(plan.incomes):
        rule = DEFERRAL.get(income.benefit) if income.apply_deferral else None
        current = int(income.starts_at_age or 0)
        if not rule or current < rule["from_age"]:
            continue
        options = []
        for age in range(rule["from_age"], rule["max_age"] + 1):
            trial = replace(plan, incomes=[replace(inc, starts_at_age=age) if j == i else inc
                                           for j, inc in enumerate(plan.incomes)])
            rows = project(trial)
            last = rows[-1] if rows else None
            failed = depletion_year(rows)
            options.append({
                "income": income.name, "owner": income.owner, "starts_at_age": age,
                "increase_pct": round((deferred_amount(1.0, age, rule) - 1.0) * 100.0, 2),
                "capital_at_end": (last["closing"] / last["closing_deflator"]) if last else 0.0,
                "runs_out": rows[failed]["calendar_year"] if failed is not None else None,
                "current": age == current, "best": False,
            })
        best = max(options, key=lambda o: (o["runs_out"] is None, o["runs_out"] or 0,
                                           round(o["capital_at_end"], 2), -o["starts_at_age"]))
        best["best"] = True
        out.extend(options)
    return out


def _totals(rows: list) -> dict:
    """Capital left at the end, and tax / OAS clawback over the whole
    projection, all in today's dollars; plus when money runs out."""
    last = rows[-1]
    failed = depletion_year(rows)
    return {"capital_at_end": last["closing"] / last["closing_deflator"],
            "tax": sum(r["tax"] / r["deflator"] for r in rows),
            "oas_recovery": sum((r.get("oas_recovery") or 0.0) / r["deflator"] for r in rows),
            "runs_out": rows[failed]["calendar_year"] if failed is not None else None}


def _mark_best(rows: list, tie_key) -> list:
    if rows:
        best = max(rows, key=lambda r: (r["runs_out"] is None, r["runs_out"] or 0,
                                        round(r["capital_at_end"], 2), tie_key(r)))
        best["best"] = True
    return rows


def compare_splits(plan: Plan, tax_fn_for, splits=range(0, 51, 5), current=None) -> list[dict]:
    """The plan with each share of eligible pension income moved to the
    lower-income spouse. `tax_fn_for(fraction)` builds the tax model for a
    split (a fraction, 0.25 for 25%). One row per split, with what is left at
    the end, the tax and the OAS clawback over the projection (today's $);
    `best` leaves the most (the smaller split breaks a tie). Pension splitting
    needs two people - with one, every split is the same.

    The share is the same every year here; the law lets it change each year,
    so a year-by-year choice could do a little better. Not advice."""
    from dataclasses import replace
    rows = []
    for pct in splits:
        result = project(replace(plan, tax_fn=tax_fn_for(pct / 100.0)))
        if result:
            rows.append({"split_pct": pct, **_totals(result), "best": False,
                         "current": current is not None and abs(pct - current) < 1e-9})
    return _mark_best(rows, lambda r: -r["split_pct"])


def compare_meltdown(plan: Plan, targets=(None, 40_000, 50_000, 60_000, 70_000),
                     until_age: int = 71) -> list[dict]:
    """The plan with the REER drawn down early to each target taxable income
    (today's dollars) until `until_age`, against drawing nothing extra (None).
    What is left at the end, the tax and the OAS clawback over the whole
    projection (today's $); `best` leaves the most (drawing less breaks a tie).
    A calculation on the plan's assumptions, not advice."""
    from dataclasses import replace
    rows = []
    for target in targets:
        result = project(replace(plan, meltdown_to=target, meltdown_until_age=until_age))
        if result:
            rows.append({"target": target, **_totals(result), "best": False,
                         "current": target is None})
    return _mark_best(rows, lambda r: -(r["target"] or 0))


KIND_LABELS = {REGISTERED: "REER/FERR", TFSA: "CELI", TAXABLE: "Non-registered"}


def compare_withdrawal_orders(plan: Plan) -> list[dict]:
    """The plan run with every order of account kinds - REER/FERR, CELI,
    non-registered - that it holds, accounts of a kind kept in their own
    order. One row per order: what is left at the end (today's dollars), the
    tax paid over the whole projection and the OAS clawback within it (both in
    today's dollars), and the year money runs out (None = never). `best` marks
    the order that leaves the most (less tax breaks a tie); `current` the order
    the accounts are entered in.

    The forced RRIF minimum is drawn whatever the order - only what is drawn
    beyond it follows the order. A calculation on the plan's own assumptions:
    it does not try strategies beyond an order (drawing more than needed in a
    low-tax year, say), and it is not advice.
    """
    from dataclasses import replace
    from itertools import permutations
    kinds = []
    for account in plan.accounts:
        if account.kind not in kinds:
            kinds.append(account.kind)
    current = tuple(kinds)
    rows = []
    for order in permutations(kinds):
        rank = {k: i for i, k in enumerate(order)}
        names = [a.name for a in sorted(plan.accounts, key=lambda a: rank[a.kind])]
        result = project(replace(plan, withdrawal_order=names))
        if not result:
            continue
        last = result[-1]
        failed = depletion_year(result)
        rows.append({
            "order": [KIND_LABELS.get(k, k) for k in order],
            "capital_at_end": last["closing"] / last["closing_deflator"],
            "tax": sum(r["tax"] / r["deflator"] for r in result),
            "oas_recovery": sum((r.get("oas_recovery") or 0.0) / r["deflator"] for r in result),
            "runs_out": result[failed]["calendar_year"] if failed is not None else None,
            "current": order == current and not plan.withdrawal_order,
            "best": False,
        })
    if rows:
        best = max(rows, key=lambda r: (r["runs_out"] is None, r["runs_out"] or 0,
                                        round(r["capital_at_end"], 2), -r["tax"]))
        best["best"] = True
    return rows


def highest_spending(holds, start: float = 50_000.0, step: float = 500.0,
                     cap: float = 2_000_000.0) -> float:
    """The highest yearly spending (to the `step`) for which `holds(spending)`
    is true - found by doubling to bracket it, then halving. 0 when even a
    spending of one step fails."""
    # Searched in whole steps: `good` steps hold, `bad` ones do not.
    good, bad = 0, max(int(start // step), 1)
    while holds(bad * step):
        good, bad = bad, bad * 2
        if bad * step > cap:
            return float(cap)
    while bad - good > 1:
        mid = (good + bad) // 2
        good, bad = (mid, bad) if holds(mid * step) else (good, mid)
    return float(good * step)


def safe_budget(make_plan, mean: float, sd: float, share: float = 0.90,
                paths: int = 300, seed: int = 1, start: float = 50_000.0) -> dict:
    """How much a plan can spend a year, in today's dollars, to its last age.

    `make_plan(spending)` builds the plan at a given spending. Two answers:
    `average` - the most it can spend if every year earns exactly the average
    return; `safe` - the most for which `share` of `paths` simulated return
    orderings (mean, sd) never run short. The second is the one to plan on:
    above it, the bad orderings - not the average - decide.

    A calculation on the plan's own assumptions, not a probability that a
    retirement works, and not advice.
    """
    def lasts(spending):
        return depletion_year(project(make_plan(spending))) is None

    def mostly_lasts(spending):
        return simulate(make_plan(spending), paths=paths, mean=mean, sd=sd,
                        seed=seed)["success_rate"] >= share

    return {"average": highest_spending(lasts, start),
            "safe": highest_spending(mostly_lasts, start),
            "share": share, "paths": paths, "mean": mean, "sd": sd}


def depletion_year(rows: list[dict]) -> int | None:
    """The first year the plan could not fund the spending. None means it
    never failed over the horizon projected — which is not the same as "it
    never will", and the caller should say so."""
    for row in rows:
        if row["unfunded"] > 0.01:
            return row["year"]
    return None


# --- many paths instead of one ---------------------------------------------
#
# A single average return says nothing about the *order* returns arrive in,
# and order is what decides a drawdown. Losing 20% in the first two years of
# withdrawing is not the same as losing it in the last two, even though the
# average is identical - money taken out at the bottom never recovers. That is
# sequence risk, and running the same plan over many orderings is the only way
# to see it.

def sample_returns(years: int, paths: int, mean: float = 0.03,
                   sd: float = 0.10, history=None, seed: int | None = None):
    """`paths` sequences of `years` returns, on the same footing as
    `Plan.nominal_return`.

    With `history` — a series of past annual returns — this resamples it
    with replacement, which keeps the shape of what actually happened,
    including the bad years a normal curve smooths away. Without it, returns
    are drawn from a normal distribution around `mean`, which is easier to
    reason about and **understates the tails**: real markets have more very
    bad years than a bell curve allows.
    """
    import random
    rng = random.Random(seed)
    out = []
    for _path in range(paths):
        if history:
            out.append([rng.choice(list(history)) for _ in range(years)])
        else:
            out.append([rng.gauss(mean, sd) for _ in range(years)])
    return out


def percentile(values: list, p: float) -> float:
    """The p-th percentile (0-100) by linear interpolation. Written out rather
    than pulled from numpy so the number can be checked by hand."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * (p / 100.0)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def simulate(plan: Plan, paths: int = 500, mean: float | None = None,
             sd: float = 0.10, history=None, seed: int | None = None) -> dict:
    """Run `plan` over many return sequences and report the spread.

    Returns the share of paths that never ran short, the age each failing path
    ran short at, and percentile bands of the closing balance per year.

    A success rate here is **the share of simulated paths under assumptions
    you chose** — not a probability that a retirement works. Change the
    spending by five thousand and it moves more than any market ever will.
    """
    mean = plan.nominal_return if mean is None else mean
    sequences = sample_returns(plan.years, paths, mean, sd, history, seed)

    balances_by_year = [[] for _ in range(plan.years)]
    depletion_ages, survived = [], 0
    calendar_years, first_rows = [], None
    for sequence in sequences:
        run = Plan(**{**vars(plan), "returns": sequence})
        rows = project(run)
        if first_rows is None:
            first_rows = rows
            calendar_years = [row["calendar_year"] for row in rows]
        failed = depletion_year(rows)
        if failed is None:
            survived += 1
            depletion_ages.append(None)
        else:
            depletion_ages.append(max(rows[failed]["ages"].values()))
        for i, row in enumerate(rows):
            balances_by_year[i].append(row["closing"])

    failed_ages = [age for age in depletion_ages if age is not None]
    return {
        "paths": paths,
        "success_rate": survived / paths if paths else 0.0,
        "depletion_ages": depletion_ages,
        "median_depletion_age": (percentile(failed_ages, 50) if failed_ages else None),
        "worst_decile_age": (percentile(failed_ages, 10) if failed_ages else None),
        "calendar_years": calendar_years,
        "percentiles": {p: [percentile(year, p) for year in balances_by_year]
                        for p in (10, 25, 50, 75, 90)},
    }


def plan_from_rows(people: list, accounts: list, incomes: list, *,
                   spending: float, nominal_return: float, inflation: float,
                   until_age: int, tax_fn=None, balances: dict | None = None) -> "Plan | None":
    """A Plan from the rows the Retirement Sim tables store.

    `people` / `accounts` / `incomes` are dicts as the database returns them.
    Rates are fractions (0.05 for 5%). Rows without a name are skipped, as the
    tables skip them. None when there is nobody to project or nothing to draw
    from - a projection of nothing is not a projection.

    `balances` replaces stored balances by account name (case-insensitive),
    for when a fresher figure is at hand - a brokerage's live balance, say -
    and the rows themselves should not be edited to try it.

    Each person's `tfsa_room` (blank = none) is the TFSA room they have today;
    the yearly limit and the taxable share of a capital gain come from
    tax_quebec, which carries their sources.
    """
    from tradelab.core.tax_quebec import CAPITAL_GAINS_INCLUSION, tfsa_dollar_limit
    override = {str(k).strip().lower(): float(v) for k, v in (balances or {}).items()}
    people_ = [Person(str(r["name"]), int(r.get("age") or 65))
               for r in people if str(r.get("name") or "").strip()]
    room = {str(r["name"]): float(r.get("tfsa_room") or 0.0)
            for r in people if str(r.get("name") or "").strip()}
    accounts_ = [Account(str(r["name"]), str(r.get("kind") or "registered").lower(),
                         override.get(str(r["name"]).strip().lower(),
                                      float(r.get("balance") or 0)),
                         str(r.get("owner") or ""))
                 for r in accounts if str(r.get("name") or "").strip()]
    incomes_ = [Income(str(r["name"]), str(r.get("owner") or ""),
                       float(r.get("annual") or 0), int(r.get("starts_at_age") or 0),
                       r.get("ends_at_age"), bool(r.get("indexed", 1)))
                for r in incomes if str(r.get("name") or "").strip()]
    if not people_ or not accounts_:
        return None
    oldest = max(p.age for p in people_)
    inflation = float(inflation)
    return Plan(people=people_, accounts=accounts_, incomes=incomes_,
                spending=float(spending), nominal_return=float(nominal_return),
                inflation=inflation, years=max(1, int(until_age) - oldest + 1),
                tax_fn=tax_fn, tfsa_room=room,
                tfsa_limit=lambda year: tfsa_dollar_limit(year, inflation),
                gains_inclusion=float(CAPITAL_GAINS_INCLUSION))
