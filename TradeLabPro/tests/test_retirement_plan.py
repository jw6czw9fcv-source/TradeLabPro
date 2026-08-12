"""Tests for tradelab.core.retirement_plan — the year-by-year projection.

No network, no Qt. Every figure here is chosen so the arithmetic can be
checked by hand, which is the only way a projection anyone relies on should
be tested.
"""
import pytest

from tradelab.core.retirement_plan import (
    REGISTERED, RRIF_CONVERSION_AGE, TAXABLE, TFSA, Account, Income, Person,
    Plan, depletion_year, project, rrif_minimum_factor,
)


# -- the prescribed factors --------------------------------------------------

def test_factor_under_71_is_one_over_ninety_minus_age():
    """The regulation's formula, which is why converting early still forces a
    withdrawal — 4% at 65, not zero."""
    assert rrif_minimum_factor(65) == pytest.approx(1 / 25)
    assert rrif_minimum_factor(65) == pytest.approx(0.04)
    assert rrif_minimum_factor(70) == pytest.approx(0.10 / 2)


def test_factors_match_the_cra_chart_at_the_ages_that_matter():
    # Source: canada.ca, Chart - Prescribed factors, "All other RRIFs".
    assert rrif_minimum_factor(71) == pytest.approx(0.0528)
    assert rrif_minimum_factor(80) == pytest.approx(0.0682)
    assert rrif_minimum_factor(90) == pytest.approx(0.1192)
    assert rrif_minimum_factor(94) == pytest.approx(0.1879)


def test_the_factor_stops_climbing_at_95():
    assert rrif_minimum_factor(95) == pytest.approx(0.20)
    assert rrif_minimum_factor(105) == pytest.approx(0.20)


def test_the_factors_only_ever_increase():
    factors = [rrif_minimum_factor(age) for age in range(60, 100)]
    assert factors == sorted(factors)


# -- income timing -----------------------------------------------------------

def test_an_income_is_nothing_before_it_starts():
    rrq = Income("RRQ", "me", 13_128, starts_at_age=65)
    assert rrq.amount_at(64) == 0
    assert rrq.amount_at(65) == 13_128


def test_an_income_can_stop():
    work = Income("Travail", "me", 30_000, ends_at_age=69)
    assert work.amount_at(69) == 30_000
    assert work.amount_at(70) == 0


# -- the ledger --------------------------------------------------------------

def _plan(**kwargs):
    base = dict(
        people=[Person("me", 65)],
        accounts=[Account("CELI", TFSA, 100_000, "me")],
        spending=0.0,
        real_return=0.0,
        years=3,
    )
    base.update(kwargs)
    return Plan(**base)


def test_a_plan_with_no_spending_and_no_growth_holds_its_balance():
    rows = project(_plan())
    assert rows[-1]["closing"] == pytest.approx(100_000)
    assert depletion_year(rows) is None


def test_growth_is_a_real_return_and_compounds():
    rows = project(_plan(real_return=0.10))
    assert rows[0]["closing"] == pytest.approx(110_000)
    assert rows[2]["closing"] == pytest.approx(133_100)


def test_spending_comes_out_of_capital_when_there_is_no_income():
    rows = project(_plan(spending=10_000))
    assert rows[0]["drawn_from_capital"] == pytest.approx(10_000)
    assert rows[0]["closing"] == pytest.approx(90_000)


def test_income_covers_spending_before_capital_is_touched():
    rows = project(_plan(spending=10_000,
                         incomes=[Income("RRQ", "me", 10_000, starts_at_age=65)]))
    assert rows[0]["drawn_from_capital"] == 0
    assert rows[0]["closing"] == pytest.approx(100_000)


def test_the_shortfall_is_reported_rather_than_hidden():
    """The number the whole projection exists to produce."""
    rows = project(_plan(accounts=[Account("CELI", TFSA, 5_000, "me")],
                         spending=10_000, years=2))
    assert rows[0]["unfunded"] == pytest.approx(5_000)
    assert depletion_year(rows) == 0


def test_the_projection_continues_past_the_failure():
    """Stopping at the year it fails leaves the reader guessing about the
    rest; the row count is the horizon asked for."""
    rows = project(_plan(accounts=[Account("CELI", TFSA, 1_000, "me")],
                         spending=10_000, years=5))
    assert len(rows) == 5
    assert all(row["unfunded"] > 0 for row in rows[1:])


# -- the forced withdrawal ---------------------------------------------------

def test_a_registered_account_is_untouched_before_the_conversion_age():
    rows = project(_plan(people=[Person("me", 65)],
                         accounts=[Account("REER", REGISTERED, 100_000, "me")]))
    assert rows[0]["forced_withdrawal"] == 0


def test_at_71_the_minimum_comes_out_whether_it_is_needed_or_not():
    rows = project(_plan(people=[Person("me", RRIF_CONVERSION_AGE)],
                         accounts=[Account("REER", REGISTERED, 100_000, "me")],
                         spending=0.0, years=1))
    assert rows[0]["forced_withdrawal"] == pytest.approx(5_280)   # 5.28%
    assert rows[0]["closing"] == pytest.approx(94_720)


def test_the_forced_withdrawal_follows_its_own_owner_age():
    """A couple's minimums are not the same number: each plan follows the age
    of the person who owns it."""
    plan = _plan(
        people=[Person("me", 71), Person("elle", 65)],
        accounts=[Account("REER-moi", REGISTERED, 100_000, "me"),
                  Account("REER-elle", REGISTERED, 100_000, "elle")],
        years=1)
    rows = project(plan)
    assert rows[0]["forced_withdrawal"] == pytest.approx(5_280)    # only his


def test_a_tfsa_is_never_forced():
    rows = project(_plan(people=[Person("me", 80)],
                         accounts=[Account("CELI", TFSA, 100_000, "me")], years=1))
    assert rows[0]["forced_withdrawal"] == 0


def test_the_minimum_cannot_exceed_the_balance():
    rows = project(_plan(people=[Person("me", 95)],
                         accounts=[Account("REER", REGISTERED, 100, "me")], years=1))
    assert rows[0]["forced_withdrawal"] == pytest.approx(20)


# -- withdrawal order --------------------------------------------------------

def test_capital_is_drawn_in_the_order_you_chose():
    plan = _plan(
        accounts=[Account("REER", REGISTERED, 50_000, "me"),
                  Account("CELI", TFSA, 50_000, "me")],
        withdrawal_order=["CELI", "REER"],
        spending=10_000, years=1)
    rows = project(plan)
    assert rows[0]["balances"]["CELI"] == pytest.approx(40_000)
    assert rows[0]["balances"]["REER"] == pytest.approx(50_000)


def test_the_order_defaults_to_how_the_accounts_were_listed():
    """The module picks no strategy: an unstated order is the given order,
    not a clever one."""
    plan = _plan(accounts=[Account("A", TAXABLE, 50_000, "me"),
                           Account("B", TFSA, 50_000, "me")],
                 spending=10_000, years=1)
    rows = project(plan)
    assert rows[0]["balances"]["A"] == pytest.approx(40_000)


def test_a_drained_account_spills_into_the_next():
    plan = _plan(accounts=[Account("A", TFSA, 4_000, "me"),
                           Account("B", TFSA, 50_000, "me")],
                 spending=10_000, years=1)
    rows = project(plan)
    assert rows[0]["balances"]["A"] == 0
    assert rows[0]["balances"]["B"] == pytest.approx(44_000)


# -- tax ---------------------------------------------------------------------

def test_tax_is_injected_not_assumed():
    """The ledger holds no tax model. It is given one, so it can be tested
    without one and so the tax rules can change without touching this."""
    plan = _plan(people=[Person("me", 71)],
                 accounts=[Account("REER", REGISTERED, 100_000, "me")],
                 spending=0.0, years=1, tax_fn=lambda taxable, ages: taxable * 0.30)
    rows = project(plan)
    assert rows[0]["tax"] == pytest.approx(5_280 * 0.30)


def test_tax_makes_the_plan_draw_more_capital():
    without = project(_plan(spending=10_000,
                            incomes=[Income("RRQ", "me", 10_000, starts_at_age=65)]))
    with_tax = project(_plan(spending=10_000,
                             incomes=[Income("RRQ", "me", 10_000, starts_at_age=65)],
                             tax_fn=lambda taxable, ages: taxable * 0.25))
    assert without[0]["drawn_from_capital"] == 0
    assert with_tax[0]["drawn_from_capital"] == pytest.approx(2_500)
