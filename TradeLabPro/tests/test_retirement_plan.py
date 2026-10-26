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
    # Zero return and zero inflation by default, so every figure below is one
    # you can check in your head. The tests that care about inflation turn it
    # on themselves.
    base = dict(
        people=[Person("me", 65)],
        accounts=[Account("CELI", TFSA, 100_000, "me")],
        spending=0.0,
        nominal_return=0.0,
        inflation=0.0,
        years=3,
    )
    base.update(kwargs)
    return Plan(**base)


def test_a_plan_with_no_spending_and_no_growth_holds_its_balance():
    rows = project(_plan())
    assert rows[-1]["closing"] == pytest.approx(100_000)
    assert depletion_year(rows) is None


def test_growth_is_the_nominal_return_and_compounds():
    rows = project(_plan(nominal_return=0.10))
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
    # It leaves the RRIF whether it is needed or not...
    assert rows[0]["balances"]["REER"] == pytest.approx(94_720)
    # ...but money nobody spent is not money lost: it is reinvested. This test
    # used to assert a total of 94,720 - the defect itself.
    assert rows[0]["closing"] == pytest.approx(100_000)


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
                 spending=0.0, years=1, tax_fn=lambda by_owner, ages, pension: sum(by_owner.values()) * 0.30)
    rows = project(plan)
    assert rows[0]["tax"] == pytest.approx(5_280 * 0.30)


def test_tax_makes_the_plan_draw_more_capital():
    without = project(_plan(spending=10_000,
                            incomes=[Income("RRQ", "me", 10_000, starts_at_age=65)]))
    with_tax = project(_plan(spending=10_000,
                             incomes=[Income("RRQ", "me", 10_000, starts_at_age=65)],
                             tax_fn=lambda by_owner, ages, pension: sum(by_owner.values()) * 0.25))
    assert without[0]["drawn_from_capital"] == 0
    assert with_tax[0]["drawn_from_capital"] == pytest.approx(2_500)


def test_the_tax_model_is_told_which_year_it_is():
    """Brackets are indexed, so a nominal projection has to say how far out it
    is; a model that did not know would invent bracket creep."""
    seen = []
    def tax_fn(by_owner, ages, pension, years_elapsed):
        seen.append(years_elapsed)
        return 0.0
    project(_plan(years=4, tax_fn=tax_fn))
    assert seen == [0, 1, 2, 3]


def test_a_tax_model_that_ignores_the_year_still_works():
    """The argument was added after the fact. A flat rate has no use for it and
    should not have to grow a parameter it never reads."""
    rows = project(_plan(
        people=[Person("me", 71)],
        accounts=[Account("REER", REGISTERED, 100_000, "me")],
        years=1, tax_fn=lambda by_owner, ages, pension: 1_000.0))
    assert rows[0]["tax"] == pytest.approx(1_000)


# -- deferring a public pension ----------------------------------------------

def test_taking_a_pension_at_65_is_the_base_amount():
    from tradelab.core.retirement_plan import DEFERRAL, deferred_amount
    assert deferred_amount(1_000, 65, DEFERRAL["RRQ"]) == pytest.approx(1_000)


def test_rrq_grows_by_seven_tenths_of_a_percent_a_month():
    """Retraite Québec: +0.7%/month, so +8.4% for a year's wait."""
    from tradelab.core.retirement_plan import DEFERRAL, deferred_amount
    assert deferred_amount(1_000, 66, DEFERRAL["RRQ"]) == pytest.approx(1_084)


def test_rrq_stops_growing_at_72():
    from tradelab.core.retirement_plan import DEFERRAL, deferred_amount
    at_72 = deferred_amount(1_000, 72, DEFERRAL["RRQ"])
    assert at_72 == pytest.approx(1_588)                 # +58.8%
    assert deferred_amount(1_000, 75, DEFERRAL["RRQ"]) == pytest.approx(at_72)


def test_psv_grows_more_slowly_and_stops_at_70():
    """canada.ca: +0.6%/month, capped at 60 months."""
    from tradelab.core.retirement_plan import DEFERRAL, deferred_amount
    assert deferred_amount(1_000, 70, DEFERRAL["PSV"]) == pytest.approx(1_360)
    assert deferred_amount(1_000, 72, DEFERRAL["PSV"]) == pytest.approx(1_360)


def test_taking_it_early_is_not_guessed_at():
    """Taking a pension before 65 reduces it by a different rule; returning
    the base unchanged is honest, inventing a reduction is not."""
    from tradelab.core.retirement_plan import DEFERRAL, deferred_amount
    assert deferred_amount(1_000, 60, DEFERRAL["RRQ"]) == pytest.approx(1_000)


def test_income_is_tracked_per_person_not_as_one_household_total():
    """A wage belongs to whoever earned it and cannot be moved to a spouse;
    only eligible pension income can. A single household figure forces the
    tax model to assume a split the rules do not allow."""
    plan = _plan(
        people=[Person("lui", 66), Person("elle", 66)],
        accounts=[Account("CELI", TFSA, 10_000, "lui")],
        incomes=[Income("Travail", "lui", 30_000),
                 Income("RRQ", "elle", 9_000, starts_at_age=65)],
        years=1)
    row = project(plan)[0]
    assert row["income_by_owner"] == {"lui": pytest.approx(30_000),
                                      "elle": pytest.approx(9_000)}


def test_a_forced_withdrawal_is_taxed_to_the_account_owner(): 
    seen = {}
    def tax_fn(by_owner, ages, pension):
        seen.update(by_owner=dict(by_owner), pension=dict(pension))
        return 0.0
    plan = _plan(
        people=[Person("lui", 71), Person("elle", 65)],
        accounts=[Account("REER", REGISTERED, 100_000, "lui")],
        years=1, tax_fn=tax_fn)
    project(plan)
    assert seen["by_owner"]["lui"] == pytest.approx(5_280)
    assert seen["by_owner"]["elle"] == 0
    # And it is pension income, which is what the pension credit is for.
    assert seen["pension"]["lui"] == pytest.approx(5_280)


# -- calendar years ----------------------------------------------------------

def test_rows_carry_a_calendar_year_not_just_an_index():
    """"2033" is something you can hold against a birthday; "year 7" is
    arithmetic the reader has to do."""
    rows = project(_plan(start_year=2026, years=3))
    assert [r["calendar_year"] for r in rows] == [2026, 2027, 2028]
    assert [r["year"] for r in rows] == [0, 1, 2]


def test_the_calendar_year_defaults_to_this_year():
    from datetime import date
    rows = project(_plan(years=1))
    assert rows[0]["calendar_year"] == date.today().year


def test_the_year_and_the_ages_advance_together():
    rows = project(_plan(people=[Person("me", 64)], start_year=2026, years=4))
    for row in rows:
        assert row["ages"]["me"] == 64 + (row["calendar_year"] - 2026)


# -- many paths instead of one -----------------------------------------------

def test_a_return_sequence_is_used_year_by_year():
    from tradelab.core.retirement_plan import Plan
    plan = _plan(returns=[0.10, 0.0, -0.10], years=3)
    rows = project(plan)
    assert rows[0]["closing"] == pytest.approx(110_000)
    assert rows[1]["closing"] == pytest.approx(110_000)
    assert rows[2]["closing"] == pytest.approx(99_000)


def test_a_short_sequence_holds_its_last_value():
    rows = project(_plan(returns=[0.10], years=3))
    assert rows[2]["closing"] == pytest.approx(133_100)


def test_order_changes_the_outcome_when_you_are_withdrawing():
    """Sequence risk in one assertion: the same two returns, the same average,
    a different answer — because money taken out at the bottom never
    recovers. This is the whole reason for running many paths."""
    bad_first = project(_plan(returns=[-0.30, 0.30], spending=20_000, years=2))
    good_first = project(_plan(returns=[0.30, -0.30], spending=20_000, years=2))
    assert bad_first[-1]["closing"] < good_first[-1]["closing"]


def test_order_does_not_matter_when_nothing_is_withdrawn():
    """And the contrast that proves the point: with no withdrawals the order
    is irrelevant, so sequence risk is a *drawdown* problem."""
    a = project(_plan(returns=[-0.30, 0.30], spending=0, years=2))
    b = project(_plan(returns=[0.30, -0.30], spending=0, years=2))
    assert a[-1]["closing"] == pytest.approx(b[-1]["closing"])


def test_percentile_is_checkable_by_hand():
    from tradelab.core.retirement_plan import percentile
    assert percentile([1, 2, 3, 4, 5], 50) == pytest.approx(3)
    assert percentile([1, 2, 3, 4, 5], 0) == pytest.approx(1)
    assert percentile([1, 2, 3, 4, 5], 100) == pytest.approx(5)
    assert percentile([10, 20], 50) == pytest.approx(15)     # interpolated
    assert percentile([], 50) == 0


def test_sampling_is_repeatable_with_a_seed():
    from tradelab.core.retirement_plan import sample_returns
    a = sample_returns(5, 3, seed=42)
    b = sample_returns(5, 3, seed=42)
    assert a == b
    assert len(a) == 3 and len(a[0]) == 5


def test_bootstrapping_only_ever_draws_years_that_happened():
    """Resampling history keeps the bad years a bell curve smooths away."""
    from tradelab.core.retirement_plan import sample_returns
    history = [-0.37, 0.26, 0.15, -0.09]
    paths = sample_returns(20, 5, history=history, seed=1)
    assert all(r in history for path in paths for r in path)


def test_a_comfortable_plan_survives_most_paths():
    from tradelab.core.retirement_plan import simulate
    out = simulate(_plan(accounts=[Account("CELI", TFSA, 2_000_000, "me")],
                         spending=20_000, years=20),
                   paths=60, mean=0.03, sd=0.10, seed=7)
    assert out["success_rate"] > 0.95
    assert out["median_depletion_age"] is None


def test_a_stretched_plan_fails_in_most_paths_and_says_when():
    from tradelab.core.retirement_plan import simulate
    out = simulate(_plan(accounts=[Account("CELI", TFSA, 100_000, "me")],
                         spending=40_000, years=20),
                   paths=60, mean=0.03, sd=0.10, seed=7)
    assert out["success_rate"] < 0.2
    assert out["median_depletion_age"] is not None


def test_the_bands_are_ordered_and_cover_every_year():
    from tradelab.core.retirement_plan import simulate
    out = simulate(_plan(accounts=[Account("CELI", TFSA, 500_000, "me")],
                         spending=20_000, years=15),
                   paths=40, mean=0.03, sd=0.12, seed=3)
    for year in range(15):
        assert (out["percentiles"][10][year] <= out["percentiles"][50][year]
                <= out["percentiles"][90][year])
    assert len(out["calendar_years"]) == 15


def test_the_simulation_does_not_disturb_the_plan_it_was_given():
    from tradelab.core.retirement_plan import simulate
    plan = _plan(years=5)
    simulate(plan, paths=5, seed=1)
    assert plan.returns is None


# -- inflation, and what it is allowed to touch -------------------------------

def test_an_indexed_income_grows_with_inflation():
    """The RRQ and PSV are indexed by law, so the cheque itself rises. The
    `annual` figure is what it is worth today; the projection grows it."""
    income = Income("RRQ", "Pierre", 13_128, 65)
    assert income.amount_at(65, 0, 0.02) == pytest.approx(13_128)
    assert income.amount_at(85, 20, 0.02) == pytest.approx(13_128 * 1.02 ** 20)


def test_a_non_indexed_income_keeps_paying_the_same_cheque():
    """A fixed private pension pays the same number of dollars for thirty
    years, which is exactly how it loses half its worth."""
    income = Income("Rente privee", "Pierre", 10_000, 65, indexed=False)
    assert income.amount_at(65, 0, 0.02) == pytest.approx(10_000)
    assert income.amount_at(95, 30, 0.02) == pytest.approx(10_000)
    # Its purchasing power is what falls, and the deflator is what shows it.
    assert 10_000 / 1.02 ** 30 == pytest.approx(5_520, abs=5)


def test_an_income_is_indexed_unless_you_say_otherwise():
    """The common case here is RRQ/PSV/AOW, and a blank should not freeze them."""
    assert Income("PSV", "Pierre", 8_292, 65).indexed is True


def test_zero_inflation_leaves_every_income_flat():
    indexed = Income("RRQ", "Pierre", 10_000, 65)
    fixed = Income("Rente", "Pierre", 10_000, 65, indexed=False)
    assert indexed.amount_at(85, 20, 0.0) == pytest.approx(10_000)
    assert fixed.amount_at(85, 20, 0.0) == pytest.approx(10_000)


def test_a_fixed_pension_makes_the_plan_run_shorter():
    """End to end: the same numbers, the flag flipped, less money."""
    def plan_with(indexed):
        return Plan(
            people=[Person("Pierre", 65)],
            accounts=[Account("CELI", TFSA, 600_000, "Pierre")],
            incomes=[Income("Rente", "Pierre", 20_000, 65, indexed=indexed)],
            spending=30_000, nominal_return=0.03, inflation=0.03, years=25)
    kept = project(plan_with(True))[-1]["closing"]
    frozen = project(plan_with(False))[-1]["closing"]
    # Both plans hold - otherwise this compares two zeroes and proves nothing.
    assert frozen > 0
    assert frozen < kept


def test_the_spending_rises_with_inflation():
    """A retirement's costs do, and holding them flat in a projection that
    inflates everything else would flatter the plan enormously."""
    rows = project(_plan(accounts=[Account("CELI", TFSA, 2_000_000, "me")],
                         spending=40_000, inflation=0.02, years=11))
    assert rows[0]["spending"] == pytest.approx(40_000)
    assert rows[10]["spending"] == pytest.approx(40_000 * 1.02 ** 10)
    # And it is the spending that comes out of capital, not the flat figure.
    assert rows[10]["drawn_from_capital"] == pytest.approx(40_000 * 1.02 ** 10)


def test_inflation_costs_the_plan_real_money():
    """The contrast with the old real-terms ledger, where the rate could not
    reach the balances at all: here a higher rate empties them faster."""
    def plan_with(inflation):
        return Plan(people=[Person("Pierre", 65)],
                    accounts=[Account("CELI", TFSA, 500_000, "Pierre")],
                    spending=20_000, nominal_return=0.05, inflation=inflation,
                    years=20)
    assert (project(plan_with(0.05))[-1]["closing"]
            < project(plan_with(0.0))[-1]["closing"])


# -- reading a nominal projection in today's dollars --------------------------

def test_every_row_carries_the_factors_that_deflate_it():
    """Two of them, because the balance is measured after the year's growth
    and the year's cheques are not."""
    rows = project(_plan(inflation=0.03, years=4))
    assert rows[0]["deflator"] == pytest.approx(1.0)
    assert rows[3]["deflator"] == pytest.approx(1.03 ** 3)
    assert rows[3]["closing_deflator"] == pytest.approx(1.03 ** 4)


def test_deflating_undoes_the_inflation_the_projection_put_in():
    """A balance in 2055 dollars is not a figure anyone can price. With the
    return and inflation equal, capital is flat in real terms — and that is
    what the deflated view has to show."""
    from tradelab.core.retirement_plan import deflate
    rows = project(_plan(nominal_return=0.03, inflation=0.03, years=10))
    real = deflate(rows)
    assert rows[-1]["closing"] > 100_000              # nominal, and growing
    assert real[-1]["closing"] == pytest.approx(100_000)
    assert real[-1]["balances"]["CELI"] == pytest.approx(100_000)


def test_deflated_spending_is_the_figure_you_typed():
    """The round trip: spending is entered in today's dollars, inflated to be
    lived, and reads back as what was typed."""
    from tradelab.core.retirement_plan import deflate
    rows = deflate(project(_plan(
        accounts=[Account("CELI", TFSA, 2_000_000, "me")],
        spending=40_000, inflation=0.025, years=15)))
    assert all(row["spending"] == pytest.approx(40_000) for row in rows)


def test_deflating_leaves_the_ages_and_the_rates_alone():
    from tradelab.core.retirement_plan import deflate
    rows = project(_plan(nominal_return=0.06, inflation=0.02, years=5))
    real = deflate(rows)
    assert real[3]["ages"] == rows[3]["ages"]
    assert real[3]["return"] == pytest.approx(0.06)
    assert real[3]["calendar_year"] == rows[3]["calendar_year"]


def test_deflating_does_not_disturb_the_rows_it_was_given():
    from tradelab.core.retirement_plan import deflate
    rows = project(_plan(nominal_return=0.05, inflation=0.02, years=5))
    closing = rows[-1]["closing"]
    deflate(rows)
    assert rows[-1]["closing"] == pytest.approx(closing)


# -- nominal and real ---------------------------------------------------------

def test_real_from_nominal_is_fisher_not_subtraction():
    from tradelab.core.retirement_plan import real_from_nominal
    assert real_from_nominal(0.06, 0.02) == pytest.approx(0.039215, abs=1e-6)
    # And the subtraction people reach for is the optimistic direction.
    assert real_from_nominal(0.06, 0.02) < 0.04


def test_nominal_and_real_are_inverses():
    from tradelab.core.retirement_plan import nominal_from_real, real_from_nominal
    assert real_from_nominal(nominal_from_real(0.03, 0.02), 0.02) == pytest.approx(0.03)


def test_with_no_inflation_real_and_nominal_agree():
    from tradelab.core.retirement_plan import real_from_nominal
    assert real_from_nominal(0.05, 0.0) == pytest.approx(0.05)


# -- what nobody spent is saved, not lost ------------------------------------------
#
# After-tax income beyond the spending used to vanish from the ledger. On a
# real plan that was several hundred thousand dollars over thirty years, and it
# made spending less look almost worthless: the money saved joined the money lost.

def test_income_beyond_the_spending_is_reinvested():
    from tradelab.core.retirement_plan import SURPLUS_ACCOUNT
    rows = project(_plan(spending=10_000, years=1,
                         incomes=[Income("Travail", "me", 30_000, starts_at_age=0)]))
    assert rows[0]["surplus"] == pytest.approx(20_000)
    assert rows[0]["balances"][SURPLUS_ACCOUNT] == pytest.approx(20_000)
    assert rows[0]["closing"] == pytest.approx(120_000)


def test_the_surplus_is_after_tax():
    rows = project(_plan(spending=10_000, years=1,
                         incomes=[Income("Travail", "me", 30_000, starts_at_age=0)],
                         tax_fn=lambda by_owner, ages, pension: 6_000.0))
    assert rows[0]["surplus"] == pytest.approx(14_000)          # 30k - 6k tax - 10k


def test_the_surplus_grows_with_the_rest():
    from tradelab.core.retirement_plan import SURPLUS_ACCOUNT
    rows = project(_plan(spending=0, nominal_return=0.10, years=1,
                         incomes=[Income("Travail", "me", 10_000, starts_at_age=0)]))
    assert rows[0]["balances"][SURPLUS_ACCOUNT] == pytest.approx(11_000)


def test_spending_less_now_leaves_more_capital():
    """The check that would have caught it: a plan whose income exceeds its
    needs must end richer when it spends less."""
    def final(spending):
        return project(_plan(spending=spending, years=10,
                             incomes=[Income("RRQ", "me", 40_000, starts_at_age=65)]))[-1]["closing"]
    assert final(20_000) - final(30_000) == pytest.approx(100_000)


def test_the_surplus_account_is_drawn_last():
    from tradelab.core.retirement_plan import SURPLUS_ACCOUNT
    rows = project(_plan(accounts=[Account("CELI", TFSA, 5_000, "me")], years=2,
                         spending=0,
                         incomes=[Income("Travail", "me", 8_000, starts_at_age=0, ends_at_age=65)]))
    # Year 1 (age 65): 8,000 surplus saved. Year 2 (age 66): no income, so the
    # spending of 0 needs nothing - the saved money simply stays.
    assert rows[1]["balances"][SURPLUS_ACCOUNT] == pytest.approx(8_000)
    short = project(_plan(accounts=[Account("CELI", TFSA, 5_000, "me")], years=2,
                          spending=6_000,
                          incomes=[Income("Travail", "me", 10_000, starts_at_age=0, ends_at_age=65)]))
    # Year 2 needs 6,000: the CELI's 5,000 goes first, then 1,000 of the surplus.
    assert short[1]["balances"]["CELI"] == pytest.approx(0)
    assert short[1]["balances"][SURPLUS_ACCOUNT] == pytest.approx(3_000)
    assert short[1]["unfunded"] == pytest.approx(0)


def test_a_real_account_with_the_same_name_is_never_merged_into():
    from tradelab.core.retirement_plan import SURPLUS_ACCOUNT
    rows = project(_plan(accounts=[Account(SURPLUS_ACCOUNT, TAXABLE, 1_000, "me")],
                         spending=0, years=1,
                         incomes=[Income("Travail", "me", 500, starts_at_age=0)]))
    assert rows[0]["balances"][SURPLUS_ACCOUNT] == pytest.approx(1_000)
    assert sum(rows[0]["balances"].values()) == pytest.approx(1_500)


def test_the_surplus_reads_in_todays_dollars_too():
    from tradelab.core.retirement_plan import deflate
    rows = project(_plan(spending=10_000, inflation=0.03, years=3,
                         incomes=[Income("Travail", "me", 30_000, starts_at_age=0)]))
    real = deflate(rows)
    assert real[2]["surplus"] == pytest.approx(rows[2]["surplus"] / 1.03 ** 2)


def test_the_old_behaviour_is_still_there_to_compare_against():
    rows = project(_plan(spending=10_000, years=1, reinvest_surplus=False,
                         incomes=[Income("Travail", "me", 30_000, starts_at_age=0)]))
    assert rows[0]["closing"] == pytest.approx(100_000)
    assert rows[0]["surplus"] == 0


# -- a registered withdrawal pays its own tax --------------------------------------
#
# Until this existed, only the forced RRIF minimum was taxed: a withdrawal made
# to cover the spending came out of the REER tax-free.

def _flat(rate):
    return lambda by_owner, ages, pension: sum(by_owner.values()) * rate


def test_a_registered_withdrawal_is_grossed_up_to_pay_its_tax():
    # 10,000 needed at a flat 25%: 13,333 comes out, 3,333 of it is tax.
    rows = project(_plan(accounts=[Account("REER", REGISTERED, 100_000, "me")],
                         spending=10_000, years=1, tax_fn=_flat(0.25)))
    assert rows[0]["drawn_from_capital"] == pytest.approx(13_333.33, abs=0.02)
    assert rows[0]["tax"] == pytest.approx(3_333.33, abs=0.02)
    assert rows[0]["unfunded"] == pytest.approx(0)
    assert rows[0]["closing"] == pytest.approx(100_000 - 13_333.33, abs=0.02)


def test_a_tfsa_withdrawal_is_not_income():
    rows = project(_plan(spending=10_000, years=1, tax_fn=_flat(0.25)))
    assert rows[0]["drawn_from_capital"] == pytest.approx(10_000)
    assert rows[0]["tax"] == 0


def test_the_withdrawal_is_pension_income_from_65_only():
    # A RRIF payment qualifies for the pension amount and for splitting at 65.
    seen = []

    def tax_fn(by_owner, ages, pension):
        seen.append(pension.get("me", 0.0))
        return 0.0
    for age, expect in ((65, True), (64, False)):
        seen.clear()
        project(_plan(people=[Person("me", age)], years=1, spending=1_000, tax_fn=tax_fn,
                      accounts=[Account("REER", REGISTERED, 100_000, "me")]))
        assert (max(seen) > 0) is expect


def test_gross_up_solves_a_kinked_schedule():
    # Nothing on the first 5,000, then 30%: W - 0.3 (W - 5,000) = 10,000.
    from tradelab.core.retirement_plan import gross_up
    take, tax = gross_up(10_000, 50_000, lambda w: max(0.0, w - 5_000) * 0.30)
    assert take == pytest.approx(12_142.86, abs=0.02)
    assert take - tax == pytest.approx(10_000, abs=0.02)


def test_gross_up_takes_everything_when_it_is_not_enough():
    from tradelab.core.retirement_plan import gross_up
    assert gross_up(10_000, 5_000, lambda w: w * 0.25) == (5_000, 1_250)
    assert gross_up(0, 5_000, lambda w: w * 0.25) == (0.0, 0.0)


# -- the surplus goes to the TFSA first ----------------------------------------------

def test_the_surplus_fills_the_tfsa_room_before_anything_else():
    from tradelab.core.retirement_plan import SURPLUS_ACCOUNT, SURPLUS_TFSA_ACCOUNT
    rows = project(_plan(spending=10_000, years=2, tfsa_room={"me": 5_000},
                         tfsa_limit=lambda year: 1_000,
                         incomes=[Income("Travail", "me", 30_000, starts_at_age=0)]))
    # Year 1: 20,000 saved, the 5,000 of room first. Year 2: the new 1,000.
    assert rows[0]["surplus_tfsa"] == pytest.approx(5_000)
    assert rows[0]["balances"][SURPLUS_TFSA_ACCOUNT] == pytest.approx(5_000)
    assert rows[0]["balances"][SURPLUS_ACCOUNT] == pytest.approx(15_000)
    assert rows[1]["surplus_tfsa"] == pytest.approx(1_000)
    assert rows[1]["balances"][SURPLUS_TFSA_ACCOUNT] == pytest.approx(6_000)
    assert rows[1]["tfsa_room"] == pytest.approx(0)


def test_each_person_brings_a_year_of_new_room():
    rows = project(_plan(people=[Person("a", 65), Person("b", 62)], years=2,
                         tfsa_limit=lambda year: 7_000,
                         incomes=[Income("Travail", "a", 50_000, starts_at_age=0)]))
    assert rows[0]["surplus_tfsa"] == 0                      # no room typed: none today
    assert rows[1]["surplus_tfsa"] == pytest.approx(14_000)  # two people, 7,000 each


def test_a_tfsa_withdrawal_comes_back_as_room_next_year():
    rows = project(_plan(accounts=[Account("CELI", TFSA, 10_000, "me")], years=2,
                         spending=5_000,
                         incomes=[Income("Travail", "me", 25_000, starts_at_age=1,
                                         ends_at_age=200)],
                         people=[Person("me", 0)]))
    # Age 0: no income, 5,000 out of the CELI. Age 1: 20,000 saved, and the
    # 5,000 withdrawn is room again.
    assert rows[0]["drawn_from_capital"] == pytest.approx(5_000)
    assert rows[1]["surplus_tfsa"] == pytest.approx(5_000)


# -- what grows outside the TFSA is taxed -----------------------------------------

def test_non_registered_growth_is_taxed_the_following_year():
    rows = project(_plan(accounts=[Account("Non-reg", TAXABLE, 100_000, "me")],
                         nominal_return=0.10, years=2, tax_fn=_flat(0.50)))
    # Year 1 gains 10,000; half of it is taxable income in year 2, taxed at 50%.
    assert rows[0]["tax"] == 0
    assert rows[1]["taxable_gains"] == pytest.approx(5_000)
    assert rows[1]["tax"] == pytest.approx(2_500)
    assert rows[1]["drawn_from_capital"] == pytest.approx(2_500)    # paid from the account


def test_a_loss_is_carried_against_later_gains():
    rows = project(_plan(accounts=[Account("Non-reg", TAXABLE, 100_000, "me")],
                         returns=[-0.10, 0.20, 0.0], years=3))
    # -10,000, then +18,000 on 90,000: only 8,000 is a gain, 4,000 taxable.
    assert rows[1]["taxable_gains"] == 0
    assert rows[2]["taxable_gains"] == pytest.approx(4_000)


def test_the_household_surplus_gains_are_shared_between_the_people():
    rows = project(_plan(people=[Person("a", 65), Person("b", 62)], years=2,
                         nominal_return=0.10,
                         incomes=[Income("Travail", "a", 20_000, starts_at_age=0)]))
    # 20,000 saved, 2,000 of growth, 1,000 taxable - half each.
    assert rows[1]["income_by_owner"]["b"] == pytest.approx(500)
    assert rows[1]["income_by_owner"]["a"] == pytest.approx(20_500)


def test_the_tfsa_part_of_the_surplus_is_never_taxed():
    rows = project(_plan(spending=10_000, years=2, nominal_return=0.10,
                         tfsa_room={"me": 100_000}, tax_fn=_flat(0.50),
                         incomes=[Income("Travail", "me", 30_000, starts_at_age=0)]))
    assert rows[1]["taxable_gains"] == 0


# -- the OAS clawback ------------------------------------------------------------

def test_an_income_named_psv_is_the_oas_pension():
    assert Income("PSV", "me", 8_000).is_oas
    assert Income("OAS", "me", 8_000).is_oas
    assert Income("Pension de la sécurité de la vieillesse", "me", 8_000).is_oas
    assert not Income("RRQ", "me", 13_000).is_oas
    assert not Income("Travail", "me", 1).is_oas
    assert Income("Mystery", "me", 1, oas=True).is_oas            # said explicitly


def test_the_oas_clawback_is_in_the_tax_and_reported_apart():
    from tradelab.core.tax_quebec import household_tax_fn
    incomes = [Income("Travail", "me", 120_000, starts_at_age=0),
               Income("PSV", "me", 8_000, starts_at_age=65)]
    rows = project(_plan(people=[Person("me", 66)], years=1, incomes=incomes,
                         tax_fn=household_tax_fn()))
    assert rows[0]["oas_recovery"] == pytest.approx((128_000 - 95_323) * 0.15)
    # A tax model that knows nothing of it reports none rather than a guess.
    flat = project(_plan(people=[Person("me", 66)], years=1, incomes=incomes,
                         tax_fn=_flat(0.30)))
    assert flat[0]["oas_recovery"] == 0


# -- waiting raises the RRQ and the PSV ---------------------------------------------
# Retraite Québec: +0.7% a month after 65, up to 72. canada.ca: +0.6% up to 70.

def test_a_psv_started_at_70_is_36_percent_larger():
    psv = Income("PSV", "me", 10_000, starts_at_age=70)
    assert psv.amount_at(69) == 0
    assert psv.amount_at(70) == pytest.approx(13_600)
    # Nothing more for waiting past 70.
    assert Income("PSV", "me", 10_000, starts_at_age=75).amount_at(75) == pytest.approx(13_600)


def test_an_rrq_started_later_grows_by_the_month_up_to_72():
    assert Income("RRQ", "me", 10_000, starts_at_age=66).amount_at(66) == pytest.approx(10_840)
    assert Income("RRQ", "me", 10_000, starts_at_age=72).amount_at(72) == pytest.approx(15_880)


def test_anything_else_is_used_as_typed():
    # An early RRQ's reduction depends on its size; the CPP stops at 70, not 72.
    assert Income("RRQ", "me", 10_000, starts_at_age=60).amount_at(60) == pytest.approx(10_000)
    assert Income("CPP", "me", 10_000, starts_at_age=70).amount_at(70) == pytest.approx(10_000)
    assert Income("AOW (Pays-Bas)", "me", 10_000, starts_at_age=67).amount_at(67) == 10_000
    assert Income("PSV", "me", 10_000, starts_at_age=70,
                  apply_deferral=False).amount_at(70) == pytest.approx(10_000)


def test_the_increase_rides_on_top_of_indexation():
    psv = Income("PSV", "me", 10_000, starts_at_age=70)
    assert psv.amount_at(70, years_elapsed=5, inflation=0.02) == pytest.approx(
        13_600 * 1.02 ** 5)


def test_the_plan_names_what_started_late():
    from tradelab.core.retirement_plan import deferrals
    plan = _plan(incomes=[Income("PSV", "me", 8_000, starts_at_age=70),
                          Income("RRQ", "me", 12_000, starts_at_age=65)])
    assert deferrals(plan) == [{"income": "PSV", "owner": "me", "starts_at_age": 70,
                                "increase_pct": 36.0}]


def test_a_plan_from_the_tables_carries_the_tfsa_rules():
    from tradelab.core.retirement_plan import plan_from_rows
    plan = plan_from_rows([{"name": "Pierre", "age": 64, "tfsa_room": 12_000},
                           {"name": "Conjointe", "age": 61, "tfsa_room": None}],
                          [{"name": "REER", "kind": "registered", "balance": 1, "owner": "Pierre"}],
                          [], spending=0, nominal_return=0.05, inflation=0.0, until_age=95)
    assert plan.tfsa_room == {"Pierre": 12_000, "Conjointe": 0.0}
    assert plan.tfsa_limit(2026) == 7_000
    assert plan.gains_inclusion == 0.5


# -- comparing start ages -------------------------------------------------------------

def test_every_start_age_of_each_pension_is_compared():
    from tradelab.core.retirement_plan import compare_start_ages
    plan = _plan(people=[Person("me", 65)], years=40, spending=20_000,
                 incomes=[Income("RRQ", "me", 10_000, starts_at_age=65),
                          Income("PSV", "me", 8_000, starts_at_age=67),
                          Income("Travail", "me", 5_000)])
    options = compare_start_ages(plan)
    rrq = [o for o in options if o["income"] == "RRQ"]
    psv = [o for o in options if o["income"] == "PSV"]
    assert [o["starts_at_age"] for o in rrq] == list(range(65, 73))
    assert [o["starts_at_age"] for o in psv] == list(range(65, 71))
    assert rrq[-1]["increase_pct"] == pytest.approx(58.8)
    assert psv[-1]["increase_pct"] == pytest.approx(36.0)
    assert [o["current"] for o in psv] == [False, False, True, False, False, False]
    assert sum(o["best"] for o in rrq) == 1 and sum(o["best"] for o in psv) == 1
    # Only one income moves at a time: the plan given is left as it was.
    assert plan.incomes[1].starts_at_age == 67


def test_a_long_life_favours_waiting_and_a_short_one_does_not():
    from tradelab.core.retirement_plan import compare_start_ages

    def best_age(years):
        plan = _plan(people=[Person("me", 65)], years=years, spending=0.0,
                     incomes=[Income("PSV", "me", 10_000, starts_at_age=65)])
        return next(o["starts_at_age"] for o in compare_start_ages(plan) if o["best"])

    # Zero return: waiting to 70 gives up 5 x 10,000 and gains 3,600 a year,
    # so it pays only after ~14 years of payments - past 84.
    assert best_age(10) == 65
    assert best_age(30) == 70


def test_an_rrq_typed_for_a_start_before_65_is_not_compared():
    from tradelab.core.retirement_plan import compare_start_ages
    plan = _plan(incomes=[Income("RRQ", "me", 7_000, starts_at_age=62),
                          Income("Pension", "me", 5_000, starts_at_age=65)])
    assert compare_start_ages(plan) == []


# -- the safe budget ------------------------------------------------------------------

def test_the_highest_spending_is_found_to_the_step():
    from tradelab.core.retirement_plan import highest_spending
    assert highest_spending(lambda x: x <= 61_234, start=10_000) == 61_000
    assert highest_spending(lambda x: x <= 120, start=50_000) == 0
    assert highest_spending(lambda x: True, start=50_000, cap=400_000) == 400_000


def test_the_safe_budget_of_a_plan_that_earns_nothing():
    # 100,000 over 10 years at no return, no tax, no inflation: 10,000 a year
    # either way, since with no volatility every ordering is the average.
    from tradelab.core.retirement_plan import safe_budget

    def make(spending):
        return _plan(years=10, spending=spending)

    out = safe_budget(make, mean=0.0, sd=0.0, paths=20)
    assert out["average"] == 10_000 and out["safe"] == 10_000
    assert out["share"] == 0.90 and out["paths"] == 20


def test_volatility_lowers_the_safe_budget_below_the_average_one():
    from tradelab.core.retirement_plan import safe_budget

    def make(spending):
        return _plan(years=25, spending=spending, nominal_return=0.05)

    out = safe_budget(make, mean=0.05, sd=0.15, paths=200)
    assert out["safe"] < out["average"]


# -- withdrawal order ---------------------------------------------------------------

def test_every_order_of_account_kinds_is_compared():
    from tradelab.core.retirement_plan import compare_withdrawal_orders
    plan = _plan(people=[Person("me", 66)], years=25, spending=30_000,
                 accounts=[Account("REER", REGISTERED, 300_000, "me"),
                           Account("CELI", TFSA, 100_000, "me"),
                           Account("Cash", TAXABLE, 50_000, "me")],
                 tax_fn=_flat(0.30))
    rows = compare_withdrawal_orders(plan)
    assert len(rows) == 6
    assert sorted(" → ".join(r["order"]) for r in rows)[0] == "CELI → Non-registered → REER/FERR"
    assert sum(r["best"] for r in rows) == 1 and sum(r["current"] for r in rows) == 1
    current = next(r for r in rows if r["current"])
    assert current["order"] == ["REER/FERR", "CELI", "Non-registered"]
    # With a flat tax every order pays tax on the same registered money sooner
    # or later; the comparison still reports the tax for each.
    assert all(r["tax"] > 0 for r in rows)


def test_one_kind_of_account_has_no_order_to_compare():
    from tradelab.core.retirement_plan import compare_withdrawal_orders
    plan = _plan(accounts=[Account("A", TFSA, 1_000, "me"), Account("B", TFSA, 1_000, "me")])
    assert len(compare_withdrawal_orders(plan)) == 1


# -- pension splitting ----------------------------------------------------------------

def test_every_split_is_compared_and_one_is_best():
    from tradelab.core.retirement_plan import compare_splits
    from tradelab.core.tax_quebec import household_tax_fn
    plan = _plan(people=[Person("lui", 70), Person("elle", 70)], years=10, spending=40_000,
                 accounts=[Account("FERR", REGISTERED, 400_000, "lui")],
                 incomes=[Income("Pension", "lui", 60_000, starts_at_age=65)])
    rows = compare_splits(plan, lambda f: household_tax_fn(f), current=0)
    assert [r["split_pct"] for r in rows] == list(range(0, 51, 5))
    assert sum(r["best"] for r in rows) == 1
    none, half = rows[0], rows[-1]
    # One earner: moving pension income to the spouse lowers the household's tax.
    assert half["tax"] < none["tax"]
    best = next(r for r in rows if r["best"])
    assert best["split_pct"] > 0 and best["capital_at_end"] >= none["capital_at_end"]
    assert rows[0]["current"] is True


# -- drawing the REER down early -------------------------------------------------------

def test_an_early_drawdown_tops_income_up_to_the_target_until_71():
    plan = _plan(people=[Person("me", 66)], years=8, spending=0,
                 accounts=[Account("REER", REGISTERED, 500_000, "me"),
                           Account("CELI", TFSA, 0, "me")],
                 incomes=[Income("RRQ", "me", 15_000, starts_at_age=65)],
                 tax_fn=_flat(0.20), meltdown_to=50_000, meltdown_until_age=71)
    rows = project(plan)
    # Ages 66-70: 35,000 more each year to reach 50,000; at 71 only the RRIF minimum.
    assert [round(r["forced_withdrawal"]) for r in rows[:5]] == [35_000] * 5
    assert rows[5]["ages"]["me"] == 71 and rows[5]["forced_withdrawal"] < 35_000


def test_early_drawdowns_are_compared_with_drawing_nothing_extra():
    from tradelab.core.retirement_plan import compare_meltdown
    plan = _plan(people=[Person("me", 66)], years=25, spending=30_000,
                 accounts=[Account("REER", REGISTERED, 600_000, "me"),
                           Account("CELI", TFSA, 50_000, "me")],
                 incomes=[Income("RRQ", "me", 15_000, starts_at_age=65)], tax_fn=_flat(0.25))
    rows = compare_meltdown(plan, targets=(None, 40_000, 60_000))
    assert [r["target"] for r in rows] == [None, 40_000, 60_000]
    assert sum(r["best"] for r in rows) == 1 and rows[0]["current"]
