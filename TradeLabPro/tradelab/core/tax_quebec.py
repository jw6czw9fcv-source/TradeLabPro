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
    # Whether this figure rises with inflation. Nearly every amount here is
    # indexed by law, which is what stops a projection in future dollars from
    # inventing bracket creep that will not happen. Two kinds are marked
    # False: the federal pension income amount, which really is frozen at
    # $2,000 and so shrinks in real terms, and the rates, which are not
    # amounts at all.
    indexed: bool = True

    def __float__(self) -> float:
        return float(self.value)

    def scaled(self, factor: float) -> "Figure":
        if not self.indexed or factor == 1.0:
            return self
        return Figure(self.value * factor, self.source, self.verified, self.indexed)


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
    quebec_retirement_amount: Figure = None
    quebec_credit_threshold: Figure = None
    quebec_credit_reduction_rate: Figure = None
    federal_pension_amount: Figure = None
    quebec_abatement: Figure = None
    federal_credit_rate: Figure = None
    quebec_credit_rate: Figure = None
    oas_recovery_threshold: Figure = None

    def inflated(self, years: int, inflation: float) -> "TaxYear":
        """This table as it would read `years` years from now.

        Both governments index their brackets and most credit amounts to
        inflation each year. A projection in future dollars that left them
        frozen would push every retirement into higher brackets it will never
        actually reach — the error grows with the horizon, and at thirty years
        it is large. What is *not* indexed stays put, which is the whole
        reason `Figure` carries the flag.
        """
        if not inflation or years <= 0:
            return self
        factor = (1.0 + inflation) ** years
        out = TaxYear(year=self.year + years)
        for name, value in vars(self).items():
            if name == "year":
                continue
            if isinstance(value, Figure):
                setattr(out, name, value.scaled(factor))
            elif name.endswith("_brackets"):
                setattr(out, name, [(None if bound is None else bound * factor, rate)
                                    for bound, rate in value])
            else:
                setattr(out, name, value)
        return out

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
RQ_RATES = "revenuquebec.ca — Taux d'imposition, année 2026, read 2026-08-12"
RQ_FORM = ("revenuquebec.ca — TP-1015.3 (2026-01), Déclaration pour la retenue "
           "d'impôt, grilles de calcul 1 et 2, read 2026-08-12")
CRA_PENSION = ("canada.ca — Pension income amount, line 31400 (a fixed $2,000, "
               "not indexed), read 2026-08-12")
CRA_ABATEMENT = ("canada.ca — Line 44000 Refundable Quebec abatement + Department "
                 "of Finance, Quebec Abatement (13.5 + 3 = 16.5 points of basic "
                 "federal tax), read 2026-08-12")
CRA_RATE_CUT = ("canada.ca — Department of Finance, Report on the Impact of "
                "Reducing the Lowest Marginal Personal Income Tax Rate on "
                "Non-Refundable Tax Credits (15% -> 14% from 2026), read 2026-08-12")
RQ_CONVERSION = ("revenuquebec.ca — Baisse générale de l'impôt des particuliers "
                 "à compter de 2023: conversion rate for personal credits reduced "
                 "to 14%, read 2026-08-12")
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

        # Verified: TP-1015.3 (2026-01), the official withholding form.
        quebec_bpa=Figure(18_952, RQ_FORM, verified=True),
        quebec_age_amount=Figure(3_986, RQ_FORM, verified=True),
        quebec_retirement_amount=Figure(3_541, RQ_FORM, verified=True),
        # The age / retirement amounts are reduced by 18.75% of *family* net
        # income above this. Missing it overstates the credit badly, which is
        # what the first version of this module did.
        quebec_credit_threshold=Figure(42_955, RQ_FORM, verified=True),
        quebec_credit_reduction_rate=Figure(0.1875, RQ_FORM, verified=True, indexed=False),

        federal_pension_amount=Figure(2_000, CRA_PENSION, verified=True,
                                     # Frozen at $2,000 since 2006 and not
                                     # indexed, so it really does shrink.
                                     indexed=False),
        quebec_abatement=Figure(0.165, CRA_ABATEMENT, verified=True, indexed=False),
        federal_age_reduction_rate=Figure(0.15, CRA_INDEX, verified=True, indexed=False),
        # 2026 is the first year at 14%: the lowest bracket rate was cut from
        # 15%, and most non-refundable credits are converted at it. A Top-Up
        # Tax Credit keeps 15% for credit amounts above the first bracket
        # threshold - not modelled, because it cannot bite at the incomes this
        # is built for, and pretending otherwise would be a guess.
        federal_credit_rate=Figure(0.14, CRA_RATE_CUT, verified=True, indexed=False),
        quebec_credit_rate=Figure(0.14, RQ_CONVERSION, verified=True, indexed=False),
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


def quebec_age_credit_base(table: TaxYear, age: int, pension_income: float,
                           family_income: float) -> float:
    """Québec's age and retirement-income amounts, after the reduction.

    The reduction is on **family** net income, not the person's own — which
    is why this takes both. A per-person calculation that ignored the family
    figure would hand each spouse a full credit the household is not entitled
    to.
    """
    if age < 65:
        return 0.0
    base = float(table.quebec_age_amount)
    base += min(float(table.quebec_retirement_amount), max(0.0, pension_income))
    excess = max(0.0, family_income - float(table.quebec_credit_threshold))
    return max(0.0, base - excess * float(table.quebec_credit_reduction_rate))


def tax_for(taxable: float, age: int, pension_income: float = 0.0,
            table: TaxYear = None, family_income: float = None) -> dict:
    """Tax for one person on `taxable` income, at `age`.

    `pension_income` is the part eligible for the pension income amount —
    RRIF/FERR withdrawals at 65+, not RRQ or PSV. `family_income` drives
    Québec's reduction of the age amount and defaults to this person's own
    income when there is no spouse. Returns the pieces as well as the total,
    because a projection that only shows a total gives nobody a way to check
    it.
    """
    table = table or year_2026()
    family_income = taxable if family_income is None else family_income
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
    qc_credits = float(table.quebec_bpa) + quebec_age_credit_base(
        table, age, pension_income, family_income)
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
    family_income = sum(incomes.values())
    total = 0.0
    for name, income in incomes.items():
        total += tax_for(income, ages.get(name, 0),
                         pension_incomes.get(name, 0.0), table,
                         family_income=family_income)["total"]
    return total
