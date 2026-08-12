"""Québec + federal income tax, at the level of detail a retirement
projection needs — and no more.

Scope was set deliberately: this models the brackets and credits that bite
around a household living on retirement income, not the whole Income Tax Act.
Brackets above the second one are carried so the arithmetic never breaks, but
the credits modelled are the ones that actually apply here — basic personal
amount, the age amount at 65, and pension income.

**Every constant carries its source and a `verified` flag.** A tax figure
written from memory is how a projection quietly becomes wrong, and there is
no way to tell by looking at the number. Anything not confirmed against the
government's own page is marked `verified=False` so the interface can show it
in amber and the person can correct it. The table is meant to be edited each
year; that is a feature of the design, not a gap in it.

Qt-free, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Figure:
    """One tax constant, with where it came from.

    `verified` means: read off the government's own page during this work,
    not from a blog, a summary, or memory. Two figures from finance blogs
    were wrong when checked against the source during this project — Québec's
    second bracket and the federal one — which is why this field exists.
    """
    value: float
    source: str
    verified: bool = False

    def __float__(self) -> float:
        return float(self.value)


@dataclass
class TaxYear:
    """Everything the tax calculation needs for one year. Edit it annually."""
    year: int

    # (upper bound of the bracket, rate). The last entry's bound is None.
    federal_brackets: list = field(default_factory=list)
    quebec_brackets: list = field(default_factory=list)

    federal_bpa: Figure = None
    quebec_bpa: Figure = None
    federal_age_amount: Figure = None
    federal_age_threshold: Figure = None
    federal_age_reduction_rate: Figure = None
    quebec_age_amount: Figure = None
    federal_pension_amount: Figure = None
    quebec_abatement: Figure = None
    federal_credit_rate: Figure = None
    quebec_credit_rate: Figure = None
    oas_recovery_threshold: Figure = None

    def unverified(self) -> list:
        """Which figures still need checking against the source. The panel
        shows this rather than letting an unchecked number pass as fact."""
        out = []
        for name, value in vars(self).items():
            if isinstance(value, Figure) and not value.verified:
                out.append(name)
        return sorted(out)


CRA_RATES = ("canada.ca — Current year tax rates and income brackets (2026), "
             "read 2026-08-12")
CRA_INDEX = ("canada.ca — Indexation adjustment for personal income tax and "
             "benefit amounts, read 2026-08-12")
RQ_RATES = ("revenuquebec.ca — Taux d'imposition, année 2026, read 2026-08-12")
UNCHECKED = "NOT YET CHECKED against the government page — correct before relying on it"


def year_2026() -> TaxYear:
    """2026. The bracket tables and the federal amounts were read off the
    government's own pages; the rest is flagged and waiting."""
    return TaxYear(
        year=2026,
        # Verified: canada.ca, current-year rates.
        federal_brackets=[(58_523, 0.14), (117_045, 0.205), (181_440, 0.26),
                          (258_482, 0.29), (None, 0.33)],
        # Verified: revenuquebec.ca, taux d'imposition 2026.
        quebec_brackets=[(54_345, 0.14), (108_680, 0.19), (132_245, 0.24),
                         (None, 0.2575)],
        federal_bpa=Figure(16_452, CRA_INDEX, verified=True),
        federal_age_amount=Figure(9_208, CRA_INDEX, verified=True),
        federal_age_threshold=Figure(46_432, CRA_INDEX, verified=True),
        oas_recovery_threshold=Figure(95_323, CRA_INDEX, verified=True),

        # Still to confirm. Values are placeholders from secondary sources so
        # the arithmetic runs; they are NOT to be trusted until checked.
        quebec_bpa=Figure(18_952, UNCHECKED),
        quebec_age_amount=Figure(3_986, UNCHECKED),
        federal_pension_amount=Figure(2_000, UNCHECKED),
        quebec_abatement=Figure(0.165, UNCHECKED),
        federal_age_reduction_rate=Figure(0.15, UNCHECKED),
        federal_credit_rate=Figure(0.14, UNCHECKED),
        quebec_credit_rate=Figure(0.14, UNCHECKED),
    )


def bracket_tax(taxable: float, brackets: list) -> float:
    """Tax before credits. Each rate applies only to its own slice."""
    taxable = max(0.0, float(taxable))
    tax, lower = 0.0, 0.0
    for upper, rate in brackets:
        top = taxable if upper is None else min(taxable, upper)
        if top > lower:
            tax += (top - lower) * rate
        lower = upper if upper is not None else lower
        if upper is not None and taxable <= upper:
            break
    return tax


def age_amount(taxable: float, table: TaxYear, age: int) -> float:
    """The federal age amount, reduced once income passes the threshold. Zero
    before 65 — it is an age credit, not a retirement one."""
    if age < 65:
        return 0.0
    amount = float(table.federal_age_amount)
    threshold = float(table.federal_age_threshold)
    if taxable > threshold:
        amount -= (taxable - threshold) * float(table.federal_age_reduction_rate)
    return max(0.0, amount)


def tax_for(taxable: float, age: int, pension_income: float = 0.0,
            table: TaxYear = None) -> dict:
    """Tax for one person on `taxable` income, at `age`.

    `pension_income` is the part eligible for the pension income amount —
    RRIF/FERR withdrawals at 65+, not RRQ or PSV. Returns the pieces as well
    as the total, because a projection that only shows a total gives nobody a
    way to check it.
    """
    table = table or year_2026()
    taxable = max(0.0, float(taxable))

    federal = bracket_tax(taxable, table.federal_brackets)
    credits = float(table.federal_bpa) + age_amount(taxable, table, age)
    if age >= 65:
        credits += min(float(table.federal_pension_amount), max(0.0, pension_income))
    federal = max(0.0, federal - credits * float(table.federal_credit_rate))
    # Québec residents pay a reduced federal tax; the province funds programs
    # Ottawa runs elsewhere.
    federal *= (1.0 - float(table.quebec_abatement))

    quebec = bracket_tax(taxable, table.quebec_brackets)
    qc_credits = float(table.quebec_bpa)
    if age >= 65:
        qc_credits += float(table.quebec_age_amount)
    quebec = max(0.0, quebec - qc_credits * float(table.quebec_credit_rate))

    total = federal + quebec
    return {
        "federal": federal,
        "quebec": quebec,
        "total": total,
        "average_rate": (total / taxable) if taxable else 0.0,
    }


def marginal_rate(taxable: float, age: int, table: TaxYear = None,
                  step: float = 100.0) -> float:
    """The combined rate on the next dollar — what "staying under a bracket"
    actually means. Measured rather than derived, so credits that phase out
    (the age amount) show up in it, which a bracket table alone would miss."""
    table = table or year_2026()
    here = tax_for(taxable, age, table=table)["total"]
    there = tax_for(taxable + step, age, table=table)["total"]
    return (there - here) / step


def split_pension(higher: float, lower: float, fraction: float = 0.5) -> tuple:
    """Move up to `fraction` of eligible pension income to the lower-income
    spouse, which is what the rules permit at 65.

    How much to move is a decision with a right answer only once you know
    both returns — this module moves what it is told to and never picks the
    fraction itself.
    """
    fraction = min(max(float(fraction), 0.0), 0.5)
    moved = max(0.0, float(higher)) * fraction
    return higher - moved, lower + moved


def household_tax(incomes: dict, ages: dict, pension_incomes: dict = None,
                  table: TaxYear = None) -> float:
    """Total tax for a household — each person taxed separately, as they are.

    Treating a couple as one taxpayer overstates the bill badly at these
    income levels: two basic personal amounts and two age amounts are worth
    more than one of each.
    """
    table = table or year_2026()
    pension_incomes = pension_incomes or {}
    total = 0.0
    for name, income in incomes.items():
        total += tax_for(income, ages.get(name, 0),
                         pension_incomes.get(name, 0.0), table)["total"]
    return total
