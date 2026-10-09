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


# Deferring a public pension raises it permanently, by a published rate per
# month of delay. These are the rules, not a view on whether to use them:
# whether a larger cheque later beats a smaller one sooner depends on how long
# you live, what the survivor keeps, and what you need in the meantime - none
# of which this module knows.
#
# RRQ:  +0.7%/month after 65, stopping at 72 (+58.8%). Source: Retraite Québec.
# PSV:  +0.6%/month after 65, stopping at 70 (+36%).  Source: canada.ca.
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

    def amount_at(self, age: int, years_elapsed: int = 0,
                  inflation: float = 0.0) -> float:
        """The cheque actually written that year, in that year's dollars."""
        if age < self.starts_at_age:
            return 0.0
        if self.ends_at_age is not None and age > self.ends_at_age:
            return 0.0
        amount = float(self.annual)
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
    # needed, a wage still coming in - is reinvested in a non-registered
    # account drawn last, instead of vanishing from the ledger. Until this
    # existed it did vanish: on a real plan, several hundred thousand dollars
    # over thirty years, which made every projection too pessimistic and made
    # spending less look nearly worthless. Off only for comparison.
    reinvest_surplus: bool = True


# The account the surplus goes to. Non-registered, so - like every taxable
# account here - its withdrawals are not taxed and neither is its growth,
# which is optimistic and said so wherever the figure is shown.
SURPLUS_ACCOUNT = "Surplus reinvested"


# What happens *during* the year — the cheques, the tax, the withdrawals — and
# the balance the year opens with. All of it is priced at the start of the year.
FLOW_KEYS = ("opening", "income", "forced_withdrawal", "tax",
             "drawn_from_capital", "surplus", "spending", "unfunded")
# The balance *after* the year's growth, which is a year later and so a year
# further from today's prices. Deflating it by the opening factor, which an
# earlier draft did, quietly overstated every closing balance by one year of
# inflation.
CLOSING_KEYS = ("closing",)


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
    """Normalise an injected `tax_fn` to the four-argument form.

    The year offset only matters to a model that indexes its brackets; a flat
    rate, or any of the stand-ins the ledger is tested with, has no use for it
    and should not have to grow an argument it ignores. The arity is read once
    here rather than by catching TypeError around each call, which would
    silently swallow a real TypeError raised inside the callee.
    """
    if fn is None:
        return None
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):        # a builtin or C callable
        return fn
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in params):
        return fn
    return lambda by_owner, ages, pension, _year: fn(by_owner, ages, pension)


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
    start_year = plan.start_year or date.today().year
    accounts = _order(plan)
    tax_fn = _tax_caller(plan.tax_fn)
    surplus_name = None
    if plan.reinvest_surplus and plan.people:
        surplus_name = SURPLUS_ACCOUNT
        while surplus_name in balances:          # never merge into a real account
            surplus_name += " "
        balances[surplus_name] = 0.0
        # Last in the withdrawal order: it is what the plan saved beyond its
        # needs, so it is the last thing to spend.
        accounts = accounts + [Account(surplus_name, TAXABLE, 0.0, plan.people[0].name)]
    rows = []

    for year in range(plan.years):
        opening = sum(balances.values())

        # 1. Income that arrives whether or not it is wanted, kept per person:
        #    a wage belongs to whoever earned it and cannot be moved.
        by_owner = {name: 0.0 for name in ages}
        for income in plan.incomes:
            owner = income.owner
            by_owner[owner] = by_owner.get(owner, 0.0) + income.amount_at(
                ages.get(owner, 0), year, plan.inflation)
        gross_income = sum(by_owner.values())

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

        taxable = gross_income + forced
        tax = (float(tax_fn(by_owner, ages, pension_by_owner, year))
               if tax_fn else 0.0)
        available = taxable - tax

        # 3. Whatever the spending still needs comes out of capital, in the
        #    order the person chose. Spending is given in today's dollars and
        #    inflated to the year being lived, like the income it is met from.
        spending = plan.spending * (1.0 + plan.inflation) ** year
        shortfall = max(0.0, spending - available)
        drawn = 0.0
        for account in accounts:
            if shortfall <= 0:
                break
            take = min(balances[account.name], shortfall)
            balances[account.name] -= take
            drawn += take
            shortfall -= take

        # 4. Anything left after the spending is saved, not lost.
        surplus = max(0.0, available - spending)
        if surplus_name is not None and surplus > 0:
            balances[surplus_name] += surplus

        # 5. Growth applies to what is left at the end of the year.
        growth = plan.nominal_return
        if plan.returns:
            growth = plan.returns[year] if year < len(plan.returns) else plan.returns[-1]
        for name in balances:
            balances[name] *= (1.0 + growth)

        rows.append({
            "year": year,
            "calendar_year": start_year + year,
            "ages": dict(ages),
            "opening": opening,
            "income": gross_income,
            "income_by_owner": dict(by_owner),
            "forced_withdrawal": forced,
            "tax": tax,
            "drawn_from_capital": drawn,
            # After-tax income beyond the spending, put in the surplus account.
            "surplus": surplus if surplus_name is not None else 0.0,
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
    """
    override = {str(k).strip().lower(): float(v) for k, v in (balances or {}).items()}
    people_ = [Person(str(r["name"]), int(r.get("age") or 65))
               for r in people if str(r.get("name") or "").strip()]
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
    return Plan(people=people_, accounts=accounts_, incomes=incomes_,
                spending=float(spending), nominal_return=float(nominal_return),
                inflation=float(inflation), years=max(1, int(until_age) - oldest + 1),
                tax_fn=tax_fn)
