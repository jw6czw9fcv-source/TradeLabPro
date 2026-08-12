"""Tests for tradelab.core.tax_quebec.

The bracket boundaries here are the ones read off canada.ca and
revenuquebec.ca during this work. If a future year's table is edited, these
tests are what catch a typo in a threshold.
"""
import pytest

from tradelab.core.tax_quebec import (
    Figure, TaxYear, age_amount, bracket_tax, household_tax, marginal_rate,
    split_pension, tax_for, year_2026,
)


# -- the bracket arithmetic --------------------------------------------------

def test_each_rate_applies_only_to_its_own_slice():
    brackets = [(10_000, 0.10), (20_000, 0.20), (None, 0.30)]
    assert bracket_tax(5_000, brackets) == pytest.approx(500)
    assert bracket_tax(10_000, brackets) == pytest.approx(1_000)
    # Not 15_000 x 20%: only the part above 10,000 is taxed at 20%.
    assert bracket_tax(15_000, brackets) == pytest.approx(1_000 + 1_000)
    assert bracket_tax(25_000, brackets) == pytest.approx(1_000 + 2_000 + 1_500)


def test_no_tax_on_nothing_or_less():
    brackets = [(10_000, 0.10), (None, 0.30)]
    assert bracket_tax(0, brackets) == 0
    assert bracket_tax(-500, brackets) == 0


def test_the_2026_thresholds_are_the_ones_that_were_verified():
    """Read off canada.ca and revenuquebec.ca. Two finance blogs had both of
    these wrong during the same research."""
    table = year_2026()
    assert table.federal_brackets[0] == (58_523, 0.14)
    assert table.quebec_brackets[0] == (54_345, 0.14)
    assert table.quebec_brackets[1] == (108_680, 0.19)


# -- the age amount ----------------------------------------------------------

def test_no_age_amount_before_65():
    assert age_amount(40_000, year_2026(), 64) == 0


def test_the_full_age_amount_below_the_threshold():
    table = year_2026()
    assert age_amount(40_000, table, 65) == pytest.approx(9_208)


def test_the_age_amount_shrinks_above_the_threshold():
    table = year_2026()
    # 46,432 is the threshold; 15% of the excess is clawed back.
    assert age_amount(56_432, table, 70) == pytest.approx(9_208 - 10_000 * 0.15)


def test_the_age_amount_never_goes_negative():
    assert age_amount(200_000, year_2026(), 80) == 0


# -- tax for one person ------------------------------------------------------

def test_a_small_income_is_covered_by_the_personal_amounts():
    """Below the basic personal amounts there is no tax to pay, which is the
    single most important thing for a household living on modest income."""
    assert tax_for(12_000, 66)["total"] == pytest.approx(0.0, abs=1.0)


def test_tax_rises_with_income():
    low = tax_for(30_000, 66)["total"]
    high = tax_for(60_000, 66)["total"]
    assert 0 < low < high


def test_being_65_costs_less_than_being_64_on_the_same_income():
    """The age amount is the whole reason, and it is worth checking that it
    actually reaches the total."""
    assert tax_for(45_000, 65)["total"] < tax_for(45_000, 64)["total"]


def test_pension_income_only_counts_from_65():
    at_64 = tax_for(45_000, 64, pension_income=10_000)["total"]
    plain_64 = tax_for(45_000, 64)["total"]
    assert at_64 == pytest.approx(plain_64)


def test_the_pieces_add_up_to_the_total():
    out = tax_for(50_000, 70)
    assert out["federal"] + out["quebec"] == pytest.approx(out["total"])
    assert out["average_rate"] == pytest.approx(out["total"] / 50_000)


# -- the marginal rate, which is what "staying under a bracket" means --------

def test_the_marginal_rate_climbs_across_a_bracket():
    below = marginal_rate(40_000, 70)
    above = marginal_rate(70_000, 70)
    assert above > below


def test_the_marginal_rate_is_measured_not_assumed():
    """Between 54,345 and 58,523 Québec has stepped up but the federal rate
    has not — a case a single bracket table would get wrong."""
    rate = marginal_rate(56_000, 70)
    assert 0.15 < rate < 0.65          # sane, and it exists


# -- household ---------------------------------------------------------------

def test_a_couple_is_taxed_as_two_people_not_one():
    """Two basic personal amounts and two age amounts are worth much more
    than one of each; treating a couple as a single taxpayer overstates the
    bill badly at these incomes."""
    together = tax_for(80_000, 70)["total"]
    apart = household_tax({"a": 40_000, "b": 40_000}, {"a": 70, "b": 70})
    assert apart < together


def test_household_tax_of_nothing_is_nothing():
    assert household_tax({}, {}) == 0


# -- pension splitting -------------------------------------------------------

def test_splitting_moves_income_to_the_lower_earner():
    higher, lower = split_pension(40_000, 10_000, fraction=0.5)
    assert higher == pytest.approx(20_000)
    assert lower == pytest.approx(30_000)


def test_splitting_is_capped_at_half():
    higher, lower = split_pension(40_000, 0, fraction=0.9)
    assert higher == pytest.approx(20_000)          # not 4,000


def test_splitting_nothing_changes_nothing():
    assert split_pension(40_000, 10_000, fraction=0.0) == (40_000, 10_000)


def test_splitting_can_lower_a_couples_tax():
    without = household_tax({"a": 60_000, "b": 5_000}, {"a": 70, "b": 70})
    a, b = split_pension(60_000, 5_000, fraction=0.5)
    with_split = household_tax({"a": a, "b": b}, {"a": 70, "b": 70})
    assert with_split < without


# -- honesty about the figures themselves ------------------------------------

def test_every_figure_says_where_it_came_from():
    table = year_2026()
    for name, value in vars(table).items():
        if isinstance(value, Figure):
            assert value.source, f"{name} has no source"


def test_the_unverified_figures_are_named_rather_than_hidden():
    """A tax number written from memory is how a projection quietly becomes
    wrong, and there is no way to tell by looking at it. These are listed so
    the interface can show them differently."""
    pending = year_2026().unverified()
    assert "quebec_bpa" in pending
    assert "quebec_abatement" in pending
    # And the ones read off the government's own pages are not in the list.
    assert "federal_bpa" not in pending
    assert "federal_age_amount" not in pending
    assert "oas_recovery_threshold" not in pending


def test_the_verified_federal_figures_carry_their_source():
    table = year_2026()
    assert "canada.ca" in table.federal_bpa.source
    assert table.federal_bpa.verified is True
