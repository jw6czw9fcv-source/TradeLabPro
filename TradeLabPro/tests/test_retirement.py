"""Tests for the group-plan fund tracker (tradelab/core/retirement.py).

Pure/offline. Every figure here is checked against a hand-computable answer:
returns are built from unit values chosen so the arithmetic is exact, and the
XIRR cases are constructed so the correct rate is known in advance rather than
read back out of the function under test.

`today` is pinned throughout - a rate of return that drifts with the clock is
untestable.
"""
from datetime import date

import pandas as pd
import pytest

from tradelab.core import retirement as rt

TODAY = date(2026, 8, 8)


def _fund(name="Actions canadiennes", snaps=(), flows=(), benchmark=""):
    return rt.Fund(
        name=name,
        benchmark=benchmark,
        snapshots=[rt.Snapshot(**s) for s in snaps],
        flows=[rt.Flow(**f) for f in flows],
    )


# --- reading the numbers off a statement ------------------------------------

def test_parse_number_handles_canadian_and_us_formatting():
    assert rt.parse_number("12 049,25 $") == pytest.approx(12049.25)
    assert rt.parse_number("16 985,78 $") == pytest.approx(16985.78)
    assert rt.parse_number("1,234.56") == pytest.approx(1234.56)
    assert rt.parse_number("18.4321") == pytest.approx(18.4321)
    assert rt.parse_number("(250,00)") == pytest.approx(-250.0)
    assert rt.parse_number("") is None
    assert rt.parse_number(None) is None


def test_parse_number_decides_the_decimal_mark_by_position():
    """'12,049.25' and '12 049,25' are the same money written two ways; the
    separator that appears last is the decimal one."""
    assert rt.parse_number("12,049.25") == pytest.approx(12049.25)
    assert rt.parse_number("12.049,25") == pytest.approx(12049.25)


def test_snapshot_fills_value_from_units_and_unit_value():
    s = rt.Snapshot(date="2026-08-08", units=1000.0, unit_value=12.5)
    assert s.value == pytest.approx(12500.0)
    assert s.amount == pytest.approx(12500.0)


def test_snapshot_accepts_a_bare_balance():
    s = rt.Snapshot(date="2026-08-08", value=12049.25)
    assert s.amount == pytest.approx(12049.25)
    assert s.units is None


# --- the fund's own return (unit values) ------------------------------------

def test_fund_return_from_unit_values_ignores_contributions_entirely():
    """The point of the unit-value path: pouring money in cannot inflate it."""
    snaps = [{"date": "2025-08-08", "units": 100.0, "unit_value": 10.0},
             {"date": "2026-08-08", "units": 900.0, "unit_value": 11.0}]
    flows = [{"date": "2026-01-15", "amount": 8000.0}]
    r = rt.fund_return(_fund(snaps=snaps, flows=flows))
    assert r["method"] == rt.BY_UNIT_VALUE
    assert r["cumulative_pct"] == pytest.approx(10.0)
    # 365 days -> the annualized figure is the cumulative one.
    assert r["annualized_pct"] == pytest.approx(10.0)


def test_fund_return_needs_two_statements():
    r = rt.fund_return(_fund(snaps=[{"date": "2026-08-08", "value": 16985.78}]))
    assert r["usable"] is False
    assert "second date" in r["reason"]


def test_fund_return_with_no_statements_says_so():
    r = rt.fund_return(_fund())
    assert r["usable"] is False
    assert "No statement" in r["reason"]


def test_short_windows_are_not_annualized():
    """A 3% gain over seven weeks is not a 24% year, and reporting it as one is
    how a fund gets switched for no reason."""
    snaps = [{"date": "2026-06-20", "unit_value": 10.0, "units": 100.0},
             {"date": "2026-08-08", "unit_value": 10.3, "units": 100.0}]
    r = rt.fund_return(_fund(snaps=snaps))
    assert r["cumulative_pct"] == pytest.approx(3.0)
    assert r["annualized_pct"] is None


def test_annualize_below_threshold_returns_none():
    assert rt.annualize(0.05, 30) is None
    assert rt.annualize(0.10, 730) == pytest.approx((1.10) ** 0.5 - 1)


# --- the fund's own return (dollar balances only) ---------------------------

def test_dietz_path_corrects_for_a_late_contribution():
    """$10,000 grows to $15,000 but $5,000 of that arrived two days before the
    closing balance. The fund did roughly nothing; a naive balance comparison
    would report +50%."""
    snaps = [{"date": "2026-01-01", "value": 10000.0},
             {"date": "2026-07-01", "value": 15000.0}]
    flows = [{"date": "2026-06-29", "amount": 5000.0}]
    r = rt.fund_return(_fund(snaps=snaps, flows=flows))
    assert r["method"] == rt.BY_DIETZ
    assert r["cumulative_pct"] == pytest.approx(0.0, abs=0.5)


def test_dietz_path_reports_real_growth():
    snaps = [{"date": "2026-01-01", "value": 10000.0},
             {"date": "2026-07-01", "value": 11000.0}]
    r = rt.fund_return(_fund(snaps=snaps))
    assert r["cumulative_pct"] == pytest.approx(10.0)


def test_unit_values_win_over_balances_when_both_are_present():
    snaps = [{"date": "2026-01-01", "units": 100.0, "unit_value": 10.0},
             {"date": "2026-07-01", "units": 200.0, "unit_value": 10.5}]
    r = rt.fund_return(_fund(snaps=snaps))
    assert r["method"] == rt.BY_UNIT_VALUE
    assert r["cumulative_pct"] == pytest.approx(5.0)


def test_modified_dietz_rejects_a_nonpositive_base():
    assert rt.modified_dietz(0.0, 100.0, [], date(2026, 1, 1), date(2026, 7, 1)) is None
    assert rt.modified_dietz(100.0, 110.0, [], date(2026, 1, 1), date(2026, 1, 1)) is None


# --- your own return (XIRR) -------------------------------------------------

def test_xirr_matches_a_known_rate():
    """$1,000 in, $1,100 back exactly one year later is 10%/yr."""
    rate = rt.xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1100.0)])
    assert rate == pytest.approx(0.10, abs=1e-4)


def test_xirr_needs_flows_in_both_directions():
    assert rt.xirr([(date(2025, 1, 1), -1000.0)]) is None
    assert rt.xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), -500.0)]) is None
    assert rt.xirr([]) is None


def test_xirr_handles_a_total_loss_gracefully():
    rate = rt.xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1.0)])
    assert rate is not None and rate < -0.9


def test_personal_return_treats_the_first_statement_as_the_opening_stake():
    """No history required: you start from the balance you can see."""
    snaps = [{"date": "2025-08-08", "value": 10000.0},
             {"date": "2026-08-08", "value": 12100.0}]
    flows = [{"date": "2026-08-07", "amount": 1000.0}]
    p = rt.personal_return(_fund(snaps=snaps, flows=flows), TODAY)
    assert p["usable"] is True
    assert p["invested"] == pytest.approx(1000.0)
    # 10,000 -> 12,100 with 1,000 added the day before: the gain is 1,100.
    assert p["gain"] == pytest.approx(1100.0)
    assert p["rate_pct"] == pytest.approx(11.0, abs=0.5)


def test_flows_dated_before_the_first_statement_are_ignored():
    """They are already inside the opening balance; counting them again would
    report the same dollars as both stake and contribution."""
    snaps = [{"date": "2025-08-08", "value": 10000.0},
             {"date": "2026-08-08", "value": 11000.0}]
    flows = [{"date": "2024-03-01", "amount": 5000.0}]
    p = rt.personal_return(_fund(snaps=snaps, flows=flows), TODAY)
    assert p["invested"] == pytest.approx(0.0)
    assert p["rate_pct"] == pytest.approx(10.0, abs=0.2)


def test_employer_money_is_reported_separately():
    """A dollar of match buys units like any other dollar, but it is not your
    performance - the excluding-employer rate is the honest personal number."""
    snaps = [{"date": "2025-08-08", "value": 10000.0},
             {"date": "2026-08-08", "value": 13200.0}]
    flows = [{"date": "2025-08-09", "amount": 1000.0, "kind": rt.CONTRIBUTION},
             {"date": "2025-08-09", "amount": 1000.0, "kind": rt.EMPLOYER}]
    p = rt.personal_return(_fund(snaps=snaps, flows=flows), TODAY)
    assert p["invested"] == pytest.approx(1000.0)
    assert p["employer"] == pytest.approx(1000.0)
    assert p["excluding_employer_pct"] > p["rate_pct"]


def test_withdrawals_reduce_net_invested():
    snaps = [{"date": "2025-08-08", "value": 10000.0},
             {"date": "2026-08-08", "value": 6000.0}]
    flows = [{"date": "2026-01-05", "amount": 5000.0, "kind": rt.WITHDRAWAL}]
    p = rt.personal_return(_fund(snaps=snaps, flows=flows), TODAY)
    assert p["withdrawn"] == pytest.approx(5000.0)
    assert p["gain"] == pytest.approx(1000.0)


def test_personal_return_refuses_a_window_too_short_to_annualize():
    snaps = [{"date": "2026-07-01", "value": 10000.0},
             {"date": "2026-08-08", "value": 10500.0}]
    p = rt.personal_return(_fund(snaps=snaps), TODAY)
    assert p["usable"] is False
    assert p["gain"] == pytest.approx(500.0)      # the dollar figure still holds


# --- reconciliation ---------------------------------------------------------

def test_unrecorded_units_flags_a_contribution_that_was_never_entered():
    snaps = [{"date": "2026-01-01", "units": 1000.0, "unit_value": 10.0},
             {"date": "2026-07-01", "units": 1200.0, "unit_value": 10.0}]
    flags = rt.unrecorded_units(_fund(snaps=snaps))
    assert len(flags) == 1
    assert flags[0]["implied"] == pytest.approx(2000.0)
    assert flags[0]["recorded"] == pytest.approx(0.0)


def test_unrecorded_units_stays_quiet_when_the_flow_is_on_file():
    snaps = [{"date": "2026-01-01", "units": 1000.0, "unit_value": 10.0},
             {"date": "2026-07-01", "units": 1200.0, "unit_value": 10.0}]
    flows = [{"date": "2026-03-01", "amount": 2000.0}]
    assert rt.unrecorded_units(_fund(snaps=snaps, flows=flows)) == []


# --- benchmarks -------------------------------------------------------------

def test_suggest_benchmark_reads_the_mandate_out_of_the_name():
    assert rt.suggest_benchmark("EXPANSION CANADA (FIDELITY)") == "XIC.TO"
    assert rt.suggest_benchmark("MARCHES EMERGENTS (MACKENZIE)") == "XEC.TO"
    assert rt.suggest_benchmark("ACTIONS INTERNATIONALES Q (CCL)") == "XEF.TO"
    assert rt.suggest_benchmark("CROISSANCE AMERICAIN (AGF)") == "XUU.TO"
    assert rt.suggest_benchmark("INDICIEL EQUILIBRE (MACKENZIE)") == "XBAL.TO"
    assert rt.suggest_benchmark("Fonds obligataire") == "XBB.TO"
    assert rt.suggest_benchmark("Quelque chose d'inconnu") == ""


def test_suggest_benchmark_prefers_the_more_specific_mandate():
    """'Actions américaines mondiales' matches both 'américain' and 'mondial';
    the narrower mandate has to win or every equity fund becomes a world fund."""
    assert rt.suggest_benchmark("ACTIONS AMERICAINES MONDIALES") == "XUU.TO"


def test_window_return_uses_the_last_close_on_or_before_each_date():
    """Statement dates land on weekends; the index still has to be priced."""
    index = pd.date_range("2026-01-01", periods=200, freq="D")
    closes = pd.Series(range(100, 300), index=index, dtype=float)
    history = pd.DataFrame({"Close": closes})
    # 2026-01-31 -> 130, 2026-03-01 -> 159
    r = rt.window_return(history, "2026-01-31", "2026-03-01")
    assert r == pytest.approx(159 / 130 - 1)


def test_window_return_survives_missing_or_empty_history():
    assert rt.window_return(None, "2026-01-01", "2026-06-01") is None
    assert rt.window_return(pd.DataFrame({"Close": []}), "2026-01-01", "2026-06-01") is None


# --- the whole plan ---------------------------------------------------------

def _plan():
    return rt.Account(name="REER Canada Vie", funds=[
        _fund("Fonds A", snaps=[{"date": "2025-08-08", "units": 100.0, "unit_value": 10.0},
                                {"date": "2026-08-08", "units": 100.0, "unit_value": 12.0}]),
        _fund("Fonds B", snaps=[{"date": "2025-08-08", "units": 100.0, "unit_value": 10.0},
                                {"date": "2026-08-08", "units": 100.0, "unit_value": 9.0}]),
    ])


def test_summarize_ranks_the_funds_and_names_both_ends():
    d = rt.summarize(_plan(), TODAY)
    assert d["total_value"] == pytest.approx(2100.0)
    assert d["best"]["name"] == "Fonds A"
    assert d["worst"]["name"] == "Fonds B"
    assert d["comparable"] == 2
    assert "Fonds A" in d["text"] and "Fonds B" in d["text"]


def test_summarize_weights_sum_to_one_hundred():
    d = rt.summarize(_plan(), TODAY)
    assert sum(r["weight_pct"] for r in d["funds"]) == pytest.approx(100.0)


def test_summarize_compares_to_a_benchmark_when_history_is_supplied():
    plan = _plan()
    plan.funds[0].benchmark = "XIC.TO"
    index = pd.date_range("2025-08-01", periods=400, freq="D")
    # A flat index: the fund's +20% is entirely excess return.
    history = pd.DataFrame({"Close": [50.0] * 400}, index=index)
    d = rt.summarize(plan, TODAY, benchmarks={"XIC.TO": history})
    row = next(r for r in d["funds"] if r["name"] == "Fonds A")
    assert row["benchmark_pct"] == pytest.approx(0.0)
    assert row["excess_pct"] == pytest.approx(20.0)


def test_summarize_leaves_comparison_empty_without_history():
    plan = _plan()
    plan.funds[0].benchmark = "XIC.TO"
    d = rt.summarize(plan, TODAY)
    row = next(r for r in d["funds"] if r["name"] == "Fonds A")
    assert row["benchmark_pct"] is None and row["excess_pct"] is None


def test_summarize_on_an_empty_plan_asks_for_funds_rather_than_crashing():
    d = rt.summarize(rt.Account(name="Vide"), TODAY)
    assert d["total_value"] == 0
    assert d["funds"] == []
    assert "Add the funds" in d["text"]


def test_one_statement_only_says_it_cannot_rank_yet():
    account = rt.Account(name="Neuf", funds=[
        _fund("Fonds A", snaps=[{"date": "2026-08-08", "value": 12049.25}])])
    d = rt.summarize(account, TODAY)
    assert d["comparable"] == 0
    assert "second statement" in d["text"]
    assert any("second date" in n for n in d["needs"])


def test_needs_flags_a_stale_statement():
    account = rt.Account(name="Vieux", funds=[
        _fund("Fonds A", snaps=[{"date": "2024-01-01", "units": 10.0, "unit_value": 1.0},
                                {"date": "2025-01-01", "units": 10.0, "unit_value": 1.1}])])
    d = rt.summarize(account, TODAY)
    assert any("days old" in n for n in d["needs"])


def test_needs_flags_funds_with_no_index_to_compare_against():
    d = rt.summarize(_plan(), TODAY)
    assert any("No index set" in n for n in d["needs"])


def test_needs_warns_when_returns_lean_on_recorded_contributions():
    account = rt.Account(name="Soldes", funds=[
        _fund("Fonds A", snaps=[{"date": "2025-01-01", "value": 10000.0},
                                {"date": "2026-01-01", "value": 11000.0}])])
    d = rt.summarize(account, TODAY)
    assert any("corrected for contributions" in n for n in d["needs"])


# --- the comparison chart ---------------------------------------------------

def test_rebased_puts_every_fund_on_the_same_starting_line():
    r = rt.rebased(_plan())
    assert r["Fonds A"]["values"][0] == pytest.approx(100.0)
    assert r["Fonds A"]["values"][-1] == pytest.approx(120.0)
    assert r["Fonds B"]["values"][-1] == pytest.approx(90.0)


def test_rebased_skips_funds_priced_only_in_dollars():
    """A balance grows when you contribute; charting that as performance would
    be a lie, so those funds are left off rather than drawn wrong."""
    account = rt.Account(name="Mixte", funds=[
        _fund("Sans prix", snaps=[{"date": "2025-01-01", "value": 1000.0},
                                  {"date": "2026-01-01", "value": 2000.0}])])
    assert rt.rebased(account) == {}


# --- pasting a statement ----------------------------------------------------

def test_parse_statement_reads_a_balance_only_paste():
    text = """FONDS D'ACTIONS CANADIENNES
    EXPANSION CANADA (FIDELITY)   16 985,78 $
    MARCHES EMERGENTS (MACKENZIE)  11 209,67 $"""
    out = rt.parse_statement(text, on=date(2026, 8, 8))
    assert len(out["rows"]) == 2
    assert out["rows"][0]["name"] == "EXPANSION CANADA (FIDELITY)"
    assert out["rows"][0]["value"] == pytest.approx(16985.78)
    assert out["rows"][0]["units"] is None
    assert "FONDS D'ACTIONS CANADIENNES" in out["skipped"]


def test_parse_statement_reads_units_and_unit_value():
    text = "EXPANSION CANADA (FIDELITY)\t1 234,5678\t13,7590"
    out = rt.parse_statement(text, on=date(2026, 8, 8))
    row = out["rows"][0]
    assert row["units"] == pytest.approx(1234.5678)
    assert row["unit_value"] == pytest.approx(13.7590)
    assert row["value"] == pytest.approx(1234.5678 * 13.7590)


def test_parse_statement_takes_the_date_out_of_the_text():
    out = rt.parse_statement("Au 2026-06-30\nFONDS X 1 000,00 $")
    assert out["date"] == "2026-06-30"


def test_parse_statement_ignores_blank_input():
    out = rt.parse_statement("")
    assert out["rows"] == []


# --- published fund fact sheets ---------------------------------------------

SHEET = """Rendements composés au 31 mars 2026
             3 mois    1 an      2 ans**   3 ans**   4 ans**   5 ans**   10 ans**
Fonds*       5,15 %    40,99 %   26,51 %   30,97 %   20,59 %   17,06 %   18,47 %
Indice       1,99 %    28,46 %   21,92 %   20,81 %   14,18 %   15,07 %   13,42 %"""


def test_parse_published_reads_a_fact_sheet_block():
    out = rt.parse_published(SHEET)
    assert out["as_of"] == "2026-03-31"
    assert len(out["records"]) == 7
    one_year = next(r for r in out["records"] if r.horizon == "1y")
    assert one_year.fund_pct == pytest.approx(40.99)
    assert one_year.index_pct == pytest.approx(28.46)
    assert one_year.excess_pct == pytest.approx(12.53)


def test_parse_published_reads_the_french_worded_date():
    assert rt.parse_published(SHEET)["as_of"] == "2026-03-31"
    assert rt._find_date("au 8 août 2026") == date(2026, 8, 8)
    assert rt._find_date("as at 31 March 2026") == date(2026, 3, 31)


def test_parse_published_maps_columns_by_their_headings():
    """A fund too young for a 10-year column must not have its 5-year figure
    read as a decade's."""
    text = """au 31 mars 2026
    3 mois   1 an     3 ans**
    Fonds    1,00 %   10,00 %  20,00 %
    Indice   2,00 %   11,00 %  21,00 %"""
    out = rt.parse_published(text)
    got = {r.horizon: r.fund_pct for r in out["records"]}
    assert got == {"3m": 1.0, "1y": 10.0, "3y": 20.0}


def test_parse_published_refuses_a_mismatched_table():
    text = """au 31 mars 2026
    3 mois   1 an
    Fonds    1,00 %   10,00 %  20,00 %"""
    out = rt.parse_published(text)
    assert out["records"] == []
    assert "column headings" in out["reason"]


def test_parse_published_needs_a_date():
    out = rt.parse_published("Fonds 1,00 % 2,00 %")
    assert out["records"] == []
    assert "No date" in out["reason"]


def test_parse_published_needs_a_fund_row():
    out = rt.parse_published("au 31 mars 2026\nIndice 1,00 % 2,00 %")
    assert out["records"] == []
    assert "No 'Fonds' row" in out["reason"]


def test_parse_published_works_without_an_index_row():
    out = rt.parse_published("au 31 mars 2026\n3 mois 1 an\nFonds 1,00 % 10,00 %")
    assert len(out["records"]) == 2
    assert all(r.index_pct is None for r in out["records"])


def test_set_published_replaces_a_re_entered_quarter():
    fund = _fund()
    fund.set_published(rt.parse_published(SHEET)["records"])
    fund.set_published(rt.parse_published(SHEET)["records"])
    assert len(fund.published) == 7
    assert fund.latest_sheet == "2026-03-31"


def _sheeted_plan(fee=None):
    account = rt.Account(name="REER", fee_pct=fee, funds=[
        _fund("Expansion Canada", snaps=[{"date": "2026-08-08", "value": 16985.78}]),
        _fund("Indiciel équilibré", snaps=[{"date": "2026-08-08", "value": 12049.25}]),
    ])
    account.funds[0].set_published(rt.parse_published(SHEET)["records"])
    account.funds[1].set_published(rt.parse_published(
        "au 31 mars 2026\n3 mois 1 an\nFonds 1,37 % 17,39 %\n"
        "Indice 1,35 % 17,36 %")["records"])
    return account


def test_published_rows_rank_by_the_published_return():
    rows = rt.published_rows(_sheeted_plan(), "1y")
    assert rows[0]["name"] == "Expansion Canada"
    assert rows[0]["excess_pct"] == pytest.approx(12.53)
    assert rows[1]["excess_pct"] == pytest.approx(0.03, abs=0.01)


def test_the_fee_is_what_decides_whether_an_index_fund_kept_up():
    """+0.03 points before a 1.5% fee is -1.47 points after it. This is the
    whole reason the fee is modelled rather than mentioned in a footnote."""
    rows = rt.published_rows(_sheeted_plan(fee=1.5), "1y")
    index_fund = next(r for r in rows if r["name"] == "Indiciel équilibré")
    assert index_fund["excess_pct"] == pytest.approx(0.03, abs=0.01)
    assert index_fund["net_excess_pct"] == pytest.approx(-1.47, abs=0.01)
    active = next(r for r in rows if r["name"] == "Expansion Canada")
    assert active["net_excess_pct"] == pytest.approx(11.03, abs=0.01)


def test_an_annual_fee_is_not_charged_against_a_three_month_return():
    rows = rt.published_rows(_sheeted_plan(fee=1.5), "3m")
    assert all(r["net_pct"] is None for r in rows)


def test_a_fund_can_override_the_plan_fee():
    account = _sheeted_plan(fee=1.5)
    account.funds[1].fee_pct = 0.5
    rows = rt.published_rows(account, "1y")
    index_fund = next(r for r in rows if r["name"] == "Indiciel équilibré")
    assert index_fund["fee_pct"] == pytest.approx(0.5)
    assert index_fund["net_excess_pct"] == pytest.approx(-0.47, abs=0.01)


def test_plan_published_weights_by_what_you_actually_hold():
    """16,985.78 at 40.99% and 12,049.25 at 17.39% is 31.2%, not the 29.2%
    a plain average of the two funds would report."""
    d = rt.plan_published(_sheeted_plan(), "1y")
    assert d["fund_pct"] == pytest.approx(31.19, abs=0.05)
    assert d["covered_pct"] == pytest.approx(100.0)
    assert "weighted by what you hold" in d["text"].lower()


def test_plan_published_names_what_it_could_not_cover():
    account = _sheeted_plan()
    account.add_fund(_fund("Sans fiche", snaps=[{"date": "2026-08-08", "value": 10000.0}]))
    d = rt.plan_published(account, "1y")
    assert d["missing"] == ["Sans fiche"]
    assert d["covered_pct"] < 100.0
    assert "covering" in d["text"]


def test_plan_published_on_an_empty_plan_says_so():
    d = rt.plan_published(rt.Account(name="Vide"), "1y")
    assert d["fund_pct"] is None
    assert "No fund fact sheets" in d["text"]


def test_available_horizons_are_ordered_shortest_first():
    assert rt.available_horizons(_sheeted_plan()) == [
        "3m", "1y", "2y", "3y", "4y", "5y", "10y"]


def test_summarize_exposes_the_published_view():
    d = rt.summarize(_sheeted_plan(fee=1.5), TODAY)
    assert d["published"]["fund_pct"] == pytest.approx(31.19, abs=0.05)
    assert d["horizons"][0] == "3m"


def test_needs_asks_for_a_fee_once_sheets_are_on_file():
    d = rt.summarize(_sheeted_plan(), TODAY)
    assert any("No fee recorded" in n for n in d["needs"])


def test_needs_flags_a_fact_sheet_lagging_the_balances():
    d = rt.summarize(_sheeted_plan(fee=1.5), TODAY)
    assert any("behind your balances" in n for n in d["needs"])


def test_needs_names_funds_with_no_sheet():
    account = _sheeted_plan(fee=1.5)
    account.add_fund(_fund("Sans fiche", snaps=[{"date": "2026-08-08", "value": 100.0}]))
    d = rt.summarize(account, TODAY)
    assert any("Sans fiche" in n and "fund fact sheet" in n for n in d["needs"])


# --- persistence ------------------------------------------------------------

def test_book_round_trips_through_json(tmp_path):
    path = tmp_path / "retirement.json"
    book = rt.RetirementBook(path)
    account = book.add_account(rt.Account(name="REER Canada Vie", funds=[
        _fund("EXPANSION CANADA (FIDELITY)",
              snaps=[{"date": "2026-08-08", "units": 1000.0, "unit_value": 16.98578}],
              flows=[{"date": "2026-03-01", "amount": 2500.0}],
              benchmark="XIC.TO")]))
    book.save()

    reloaded = rt.RetirementBook(path)
    assert len(reloaded.accounts) == 1
    fund = reloaded.accounts[0].funds[0]
    assert fund.name == "EXPANSION CANADA (FIDELITY)"
    assert fund.benchmark == "XIC.TO"
    assert fund.snapshots[0].units == pytest.approx(1000.0)
    assert fund.flows[0].amount == pytest.approx(2500.0)
    assert reloaded.account("REER Canada Vie").id == account.id


def test_published_returns_and_fees_survive_a_round_trip(tmp_path):
    path = tmp_path / "retirement.json"
    book = rt.RetirementBook(path)
    account = _sheeted_plan(fee=1.75)
    account.funds[0].code = "CGCF"
    account.funds[1].fee_pct = 0.5
    book.add_account(account)

    reloaded = rt.RetirementBook(path).accounts[0]
    assert reloaded.fee_pct == pytest.approx(1.75)
    assert reloaded.funds[0].code == "CGCF"
    assert reloaded.funds[1].fee_pct == pytest.approx(0.5)
    one_year = reloaded.funds[0].published_on(horizon="1y")
    assert one_year.fund_pct == pytest.approx(40.99)
    assert one_year.index_pct == pytest.approx(28.46)


def test_book_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "retirement.json"
    path.write_text("{ not json", encoding="utf-8")
    assert rt.RetirementBook(path).accounts == []


def test_missing_file_is_an_empty_book(tmp_path):
    assert rt.RetirementBook(tmp_path / "nope.json").accounts == []


def test_apply_statement_adds_new_funds_and_updates_existing_ones(tmp_path):
    book = rt.RetirementBook(tmp_path / "retirement.json")
    account = book.add_account(rt.Account(name="REER"))
    first = rt.parse_statement("EXPANSION CANADA 16 985,78 $", on=date(2026, 1, 31))
    result = book.apply_statement(account, first["rows"])
    assert result["added"] == ["EXPANSION CANADA"]

    second = rt.parse_statement("EXPANSION CANADA 17 500,00 $", on=date(2026, 8, 8))
    result = book.apply_statement(account, second["rows"])
    assert result["updated"] == ["EXPANSION CANADA"]
    assert len(account.funds) == 1
    assert len(account.funds[0].snapshots) == 2


def test_apply_statement_sets_a_benchmark_guess_on_new_funds(tmp_path):
    book = rt.RetirementBook(tmp_path / "retirement.json")
    account = book.add_account(rt.Account(name="REER"))
    book.apply_statement(account, rt.parse_statement(
        "MARCHES EMERGENTS (MACKENZIE) 11 209,67 $", on=date(2026, 8, 8))["rows"])
    assert account.funds[0].benchmark == "XEC.TO"


def test_re_entering_the_same_statement_corrects_it_rather_than_doubling_it():
    fund = _fund(snaps=[{"date": "2026-08-08", "value": 100.0}])
    fund.add_snapshot(rt.Snapshot(date="2026-08-08", value=200.0))
    assert len(fund.snapshots) == 1
    assert fund.value == pytest.approx(200.0)
