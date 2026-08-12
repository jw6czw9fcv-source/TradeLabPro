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

**Everything is in today's dollars.** A projection in nominal dollars reads
as "$210,000 in 2048", which nobody can price. Working in real terms means
the spending figure means what it means today, and it is defensible because
the things being compared against — federal and Quebec tax brackets, the RRQ,
the PSV — are all indexed to inflation. That assumption is stated rather than
buried: if indexation stops, this projection is optimistic.

Qt-free and offline-testable; no network, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Account kinds. The difference that matters is how a withdrawal is taxed and
# whether it can be forced:
#   REGISTERED   REER/FERR/FTQ - fully taxable on withdrawal, and after the
#                year the holder turns 71 a minimum *must* come out whether it
#                is needed or not.
#   TFSA         CELI - withdrawals are not income, and nothing forces one.
#   TAXABLE      non-registered - only the gain is taxed, and this module does
#                not model an adjusted cost base, so it treats a withdrawal as
#                tax-free and says so rather than guessing at a capital gain.
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


@dataclass
class Account:
    """One holding. `owner` matters because registered withdrawals are the
    owner's income, and the RRIF minimum follows the owner's age."""
    name: str
    kind: str
    balance: float
    owner: str


@dataclass
class Income:
    """A benefit or wage, in today's dollars per year.

    `starts_at_age` is the owner's age when it begins and `ends_at_age` when
    it stops (None = for life). A wage is just an income that ends.
    """
    name: str
    owner: str
    annual: float
    starts_at_age: int = 0
    ends_at_age: int | None = None

    def amount_at(self, age: int) -> float:
        if age < self.starts_at_age:
            return 0.0
        if self.ends_at_age is not None and age > self.ends_at_age:
            return 0.0
        return float(self.annual)


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
    # Household spending per year, in today's dollars.
    spending: float = 0.0
    # Real return, i.e. after inflation. 0.03 means "three points above
    # inflation", not "three percent".
    real_return: float = 0.03
    # Which accounts to draw from first. Order is a decision with real tax
    # consequences and it belongs to the person, not to this module; the
    # default is simply the order the accounts were given in.
    withdrawal_order: list[str] | None = None
    years: int = 35
    # Tax on registered withdrawals and other taxable income. Injected so the
    # ledger can be tested without a tax model, and so the tax model can be
    # replaced without touching the ledger.
    tax_fn: object = None


def _order(plan: Plan) -> list[Account]:
    if not plan.withdrawal_order:
        return list(plan.accounts)
    rank = {name: i for i, name in enumerate(plan.withdrawal_order)}
    return sorted(plan.accounts, key=lambda a: rank.get(a.name, len(rank)))


def project(plan: Plan) -> list[dict]:
    """One row per year: incomes, forced withdrawals, what had to be drawn to
    meet the spending, tax, and the closing balance.

    Returns as many rows as `plan.years`, and keeps going after the money runs
    out — a plan that fails at 84 should show what the following years look
    like, not stop and leave the reader to guess.
    """
    balances = {a.name: float(a.balance) for a in plan.accounts}
    ages = {p.name: p.age for p in plan.people}
    accounts = _order(plan)
    rows = []

    for year in range(plan.years):
        opening = sum(balances.values())

        # 1. Income that arrives whether or not it is wanted.
        gross_income = 0.0
        for income in plan.incomes:
            gross_income += income.amount_at(ages.get(income.owner, 0))

        # 2. The registered minimum. It is forced, it is taxable, and it lands
        #    in the household's hands whether the spending needed it or not.
        forced = 0.0
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

        taxable = gross_income + forced
        tax = float(plan.tax_fn(taxable, ages)) if plan.tax_fn else 0.0
        available = taxable - tax

        # 3. Whatever the spending still needs comes out of capital, in the
        #    order the person chose.
        shortfall = max(0.0, plan.spending - available)
        drawn = 0.0
        for account in accounts:
            if shortfall <= 0:
                break
            take = min(balances[account.name], shortfall)
            balances[account.name] -= take
            drawn += take
            shortfall -= take

        # 4. Growth applies to what is left at the end of the year.
        for name in balances:
            balances[name] *= (1.0 + plan.real_return)

        rows.append({
            "year": year,
            "ages": dict(ages),
            "opening": opening,
            "income": gross_income,
            "forced_withdrawal": forced,
            "tax": tax,
            "drawn_from_capital": drawn,
            # What the plan could not fund this year. The whole point of the
            # projection is this number turning positive.
            "unfunded": shortfall,
            "closing": sum(balances.values()),
            "balances": dict(balances),
        })
        for name in ages:
            ages[name] += 1

    return rows


def depletion_year(rows: list[dict]) -> int | None:
    """The first year the plan could not fund the spending. None means it
    never failed over the horizon projected — which is not the same as "it
    never will", and the caller should say so."""
    for row in rows:
        if row["unfunded"] > 0.01:
            return row["year"]
    return None
