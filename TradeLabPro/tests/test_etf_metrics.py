"""Tests for tradelab.core.etf_metrics — synthetic price series only, no live
yfinance call, matching the rest of the suite's rule."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core.etf_metrics import (
    COMPOSITION_ROWS, PERIODS, composition_summary, compute_metrics,
    alternate_listing, build_allocation, csa_level, csa_volatility,
    dividend_yield,
    expand_compositions, fold_alternate_listings, fund_symbol,
    is_low_volatility, overlaps, pass_through_symbols, rebalance, risk_metrics,
    trailing_return,
)


def _flat(days: int, start: float = 100.0) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=days, freq="D")
    return pd.Series([start] * days, index=idx)


def _growth(days: int, daily_return: float, start: float = 100.0) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=days, freq="D")
    return pd.Series(start * (1 + daily_return) ** np.arange(days), index=idx)


# -- trailing returns -------------------------------------------------------

def test_trailing_return_flat_series_is_zero():
    assert trailing_return(_flat(400), 30, None) == pytest.approx(0.0, abs=1e-9)


def test_trailing_return_insufficient_history_is_none():
    assert trailing_return(_flat(20), 365, 1) is None


def test_trailing_return_annualizes_over_multiple_years():
    # +10%/year compounded for three years must come back as ~10%, not ~33%.
    prices = _growth(3 * 365 + 5, daily_return=(1.10 ** (1 / 365.25)) - 1)
    assert trailing_return(prices, 3 * 365, 3) == pytest.approx(0.10, abs=0.01)


def test_trailing_return_under_a_year_is_not_annualized():
    prices = _growth(200, daily_return=(1.10 ** (1 / 365.25)) - 1)
    six_months = trailing_return(prices, 182, None)
    assert 0.03 < six_months < 0.06     # roughly half a 10% year, un-annualized


def test_trailing_return_empty_series_is_none():
    assert trailing_return(pd.Series(dtype=float), 30, None) is None


# -- risk -------------------------------------------------------------------

def test_risk_metrics_insufficient_history_returns_none_triplet():
    assert risk_metrics(_flat(10)) == (None, None, None)


def test_risk_metrics_flat_series_has_zero_vol_and_drawdown():
    vol, dd, _sharpe = risk_metrics(_flat(400))
    assert vol == pytest.approx(0.0, abs=1e-9)
    assert dd == pytest.approx(0.0, abs=1e-9)


def test_risk_metrics_drawdown_is_negative_after_a_drop():
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=200, freq="D")
    prices = pd.Series([100.0] * 100 + [70.0] * 100, index=idx)
    _vol, dd, _sharpe = risk_metrics(prices)
    assert dd == pytest.approx(-0.30, abs=0.01)


def test_risk_metrics_sharpe_is_negative_when_growth_lags_the_risk_free_rate():
    # ~1%/year against a 3% risk-free rate: the excess return is negative, so
    # a positive Sharpe here would mean the risk-free rate was ignored.
    rng = np.random.default_rng(7)
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=800, freq="D")
    drift = (1.01 ** (1 / 365.25)) - 1
    noise = rng.normal(0, 0.004, size=800)
    prices = pd.Series(100 * np.cumprod(1 + drift + noise), index=idx)
    _vol, _dd, sharpe = risk_metrics(prices)
    assert sharpe is not None and sharpe < 0


# -- compute_metrics --------------------------------------------------------

def test_compute_metrics_with_short_history_returns_only_short_windows():
    metrics = compute_metrics("SYNTH", prices=_flat(100))   # 1M/3M yes, 1A no
    assert metrics is not None
    assert "ret_1m" in metrics
    assert "ret_1a" not in metrics      # never fabricated


def test_compute_metrics_too_short_returns_none():
    assert compute_metrics("SYNTH", prices=_flat(5)) is None


def test_compute_metrics_includes_risk_columns_on_long_history():
    metrics = compute_metrics("SYNTH", prices=_growth(800, 0.0002))
    assert {"volatility", "max_drawdown", "sharpe"} <= set(metrics)


def test_periods_cover_expected_columns():
    assert set(PERIODS) == {
        "ret_1m", "ret_3m", "ret_6m", "ret_1a", "ret_3a", "ret_5a", "ret_10a",
    }


# -- composition summary ----------------------------------------------------

def _book():
    return [
        {"ticker": "VFV", "pct_can": 0.0, "pct_us": 1.0, "pct_intl": 0.0,
         "pct_bond": 0.0, "pct_alt": 0.0, "risk": 4, "mer": 0.0009,
         "ret_10a": 0.16, "my_mix": 0.5, "mid_risk": 0.2},
        {"ticker": "VAB", "pct_can": 0.0, "pct_us": 0.0, "pct_intl": 0.0,
         "pct_bond": 1.0, "pct_alt": 0.0, "risk": 1, "mer": 0.0009,
         "ret_10a": 0.02, "my_mix": 0.5, "mid_risk": 0.8},
    ]


def test_composition_total_is_the_sum_of_weights():
    assert composition_summary(_book())["total"] == pytest.approx(1.0)


def test_composition_weights_the_regional_split():
    rows = composition_summary(_book())["rows"]
    assert rows["pct_us"]["value"] == pytest.approx(0.5)
    assert rows["pct_bond"]["value"] == pytest.approx(0.5)
    assert rows["pct_alt"]["value"] == pytest.approx(0.0)


def test_composition_reads_the_weight_column_it_is_given():
    rows = composition_summary(_book(), "mid_risk")["rows"]
    assert rows["pct_us"]["value"] == pytest.approx(0.2)
    assert rows["mer"]["value"] == pytest.approx(0.0009)


def test_composition_ignores_funds_with_no_weight():
    book = _book() + [{"ticker": "SMH", "pct_us": 1.0, "risk": 5}]  # no my_mix
    assert composition_summary(book)["total"] == pytest.approx(1.0)
    assert composition_summary(book)["rows"]["pct_us"]["value"] == pytest.approx(0.5)


def test_composition_reports_coverage_when_a_column_is_missing():
    book = _book()
    book[1]["ret_10a"] = None            # one fund has no ten-year number
    cell = composition_summary(book)["rows"]["ret_10a"]
    assert cell["value"] == pytest.approx(0.5 * 0.16)
    # Half the allocation is behind that figure; the caller has to say so.
    assert cell["covered"] == pytest.approx(0.5)


def test_composition_of_an_empty_book_is_all_zeros():
    summary = composition_summary([])
    assert summary["total"] == 0
    assert all(cell["covered"] == 0 for cell in summary["rows"].values())


def test_composition_rows_only_reference_real_columns():
    from tradelab.data.database import Database
    for _label, column, kind in COMPOSITION_ROWS:
        assert column in Database.ETF_COLUMNS
        assert kind in {"pct", "num"}


# -- rebalance: the target against what is actually held --------------------

def _plan():
    return [
        {"ticker": "VFV", "yahoo": "VFV.TO", "my_mix": 0.6},
        {"ticker": "VAB", "yahoo": "VAB.TO", "my_mix": 0.4},
    ]


def _holdings(vfv=60_000.0, vab=40_000.0):
    return [{"symbol": "VFV.TO", "market_value": vfv},
            {"symbol": "VAB.TO", "market_value": vab}]


def test_rebalance_on_plan_book_has_no_drift():
    result = rebalance(_plan(), _holdings())
    assert result["total"] == pytest.approx(100_000)
    for row in result["rows"]:
        assert row["drift_pct"] == pytest.approx(0.0)
        assert row["amount"] == pytest.approx(0.0)


def test_rebalance_reports_what_to_buy_and_trim():
    result = rebalance(_plan(), _holdings(vfv=80_000, vab=20_000))
    by_ticker = {r["ticker"]: r for r in result["rows"]}
    assert by_ticker["VFV"]["actual_pct"] == pytest.approx(0.8)
    assert by_ticker["VFV"]["amount"] == pytest.approx(-20_000)   # trim
    assert by_ticker["VAB"]["amount"] == pytest.approx(20_000)    # buy


def test_rebalance_matches_on_the_yahoo_symbol():
    # The book holds VFV.TO; the plan's ticker column says VFV.
    result = rebalance(_plan(), [{"symbol": "VFV.TO", "market_value": 100.0}])
    assert result["rows"][0]["market_value"] == pytest.approx(100.0)


def test_rebalance_measures_against_the_whole_book_not_just_the_plan():
    """A plan covering half the book must not report that half as the whole,
    or a target is 'met' while the rest sits somewhere it never mentioned."""
    book = _holdings(vfv=30_000, vab=20_000) + [{"symbol": "NVDA", "market_value": 50_000}]
    result = rebalance(_plan(), book)
    assert result["total"] == pytest.approx(100_000)
    assert result["covered"] == pytest.approx(0.5)
    assert result["unmatched"] == ["NVDA"]
    by_ticker = {r["ticker"]: r for r in result["rows"]}
    assert by_ticker["VFV"]["actual_pct"] == pytest.approx(0.3)   # not 0.6


def test_rebalance_lists_a_target_never_bought():
    result = rebalance(_plan(), [{"symbol": "VFV.TO", "market_value": 100.0}])
    vab = [r for r in result["rows"] if r["ticker"] == "VAB"][0]
    assert vab["market_value"] == 0
    assert vab["amount"] > 0


def test_rebalance_lists_a_holding_with_no_target():
    funds = [{"ticker": "VFV", "yahoo": "VFV.TO", "my_mix": 0.0}]
    result = rebalance(funds, [{"symbol": "VFV.TO", "market_value": 100.0}])
    assert result["rows"][0]["target_pct"] == 0
    assert result["rows"][0]["amount"] == pytest.approx(-100.0)


def test_rebalance_of_an_empty_book_does_not_divide_by_zero():
    result = rebalance(_plan(), [])
    assert result["total"] == 0
    assert all(r["actual_pct"] == 0 for r in result["rows"])


def test_rebalance_sorts_by_how_far_off_it_is():
    funds = _plan() + [{"ticker": "ZLB", "yahoo": "ZLB.TO", "my_mix": 0.0}]
    result = rebalance(funds, _holdings(vfv=90_000, vab=10_000))
    assert result["rows"][0]["ticker"] in {"VFV", "VAB"}
    drifts = [abs(r["drift_pct"]) for r in result["rows"]]
    assert drifts == sorted(drifts, reverse=True)


# -- overlaps: the same exposure bought twice --------------------------------

def _twins():
    canada = {"pct_can": 1.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 0.0, "pct_alt": 0.0}
    return [
        {"ticker": "VCN", "category": "Canadian equity", "my_mix": 0.2, **canada},
        {"ticker": "XIC", "category": "Canadian equity", "my_mix": 0.1, **canada},
        {"ticker": "VAB", "category": "Bonds", "my_mix": 0.3,
         "pct_can": 0.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 1.0, "pct_alt": 0.0},
    ]


def test_overlap_flags_two_funds_buying_the_same_market():
    found = overlaps(_twins())
    assert len(found) == 1
    assert {found[0]["a"], found[0]["b"]} == {"VCN", "XIC"}
    assert found[0]["combined_weight"] == pytest.approx(0.3)


def test_overlap_ignores_a_fund_with_no_weight():
    funds = _twins()
    funds[1]["my_mix"] = 0.0        # XIC listed but not allocated to
    assert overlaps(funds) == []


def test_overlap_does_not_flag_genuinely_different_exposures():
    funds = [
        {"ticker": "VFV", "category": "S&P 500", "my_mix": 0.5,
         "pct_can": 0.0, "pct_us": 1.0, "pct_intl": 0.0, "pct_bond": 0.0, "pct_alt": 0.0},
        {"ticker": "VAB", "category": "Bonds", "my_mix": 0.5,
         "pct_can": 0.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 1.0, "pct_alt": 0.0},
    ]
    assert overlaps(funds) == []


def test_overlap_falls_back_to_category_when_the_mix_is_blank():
    funds = [{"ticker": "VCN", "category": "Canadian equity", "my_mix": 0.2},
             {"ticker": "XIC", "category": "Canadian equity", "my_mix": 0.2}]
    found = overlaps(funds)
    assert found and found[0]["reason"] == "same category"
    assert found[0]["distance"] is None


def test_overlap_guesses_nothing_with_neither_mix_nor_category():
    funds = [{"ticker": "AAA", "my_mix": 0.5}, {"ticker": "BBB", "my_mix": 0.5}]
    assert overlaps(funds) == []


def test_overlap_reads_the_weight_column_it_is_given():
    funds = _twins()
    for fund in funds:
        fund["low_risk"] = 0.0
    assert overlaps(funds, "low_risk") == []
    assert overlaps(funds, "my_mix")


# -- opening a fund that holds another fund ---------------------------------

def _wrapper():
    """VFV.TO publishes one holding: VOO.TO at 100%. VOO.TO publishes its own
    top names, covering 60% of itself."""
    return {
        "VFV.TO": {"top_holdings": {"VOO.TO": 1.0}},
        "VOO.TO": {"top_holdings": {"AAPL": 0.4, "MSFT": 0.2}},
    }


def test_pass_through_finds_the_fund_worth_opening():
    assert pass_through_symbols({"VFV.TO": {"top_holdings": {"VOO.TO": 1.0}}}) == ["VOO.TO"]


def test_pass_through_ignores_ordinary_holdings():
    # A fund's ten top names at ~8% each are companies, not wrappers; opening
    # each of them would be hundreds of requests for nothing.
    comps = {"XIC.TO": {"top_holdings": {"RY.TO": 0.08, "TD.TO": 0.06}}}
    assert pass_through_symbols(comps) == []


def test_pass_through_ignores_a_merely_concentrated_fund():
    """60% in one name is a concentrated fund, not a wrapper around it."""
    comps = {"SMH": {"top_holdings": {"NVDA": 0.6, "TSM": 0.1}}}
    assert pass_through_symbols(comps) == []


def test_pass_through_skips_what_we_already_have():
    assert pass_through_symbols(_wrapper()) == []


def test_expand_replaces_a_wrapper_with_what_it_really_holds():
    holdings = expand_compositions(_wrapper())["VFV.TO"]["top_holdings"]
    assert holdings["AAPL"] == pytest.approx(0.4)
    assert holdings["MSFT"] == pytest.approx(0.2)


def test_expand_keeps_the_nested_unpublished_part_as_the_fund():
    """VOO.TO publishes 60% of itself; the other 40% must stay attributed to
    VOO.TO rather than being spread over AAPL and MSFT."""
    holdings = expand_compositions(_wrapper())["VFV.TO"]["top_holdings"]
    assert holdings["VOO.TO"] == pytest.approx(0.4)
    assert sum(holdings.values()) == pytest.approx(1.0)


def test_expand_leaves_ordinary_funds_untouched():
    comps = {"XIC.TO": {"top_holdings": {"RY.TO": 0.08, "TD.TO": 0.06}}}
    assert expand_compositions(comps) == comps


def test_expand_keeps_the_other_keys_of_a_composition():
    comps = {"XIC.TO": {"top_holdings": {"RY.TO": 0.08}, "sectors": {"financial": 0.3}}}
    assert expand_compositions(comps)["XIC.TO"]["sectors"] == {"financial": 0.3}


def test_expand_survives_a_fund_listing_itself():
    comps = {"AAA": {"top_holdings": {"AAA": 1.0}}}
    assert expand_compositions(comps)["AAA"]["top_holdings"] == {"AAA": 1.0}


def test_alternate_listing_drops_the_toronto_suffix():
    """A Canadian fund's holdings come back with .TO appended. Right for RY
    inside XIC.TO; wrong for VOO inside VFV.TO, and VOO.TO does not exist."""
    assert alternate_listing("VOO.TO") == "VOO"
    assert alternate_listing("voo.to") == "VOO"


def test_alternate_listing_is_none_for_an_ordinary_symbol():
    assert alternate_listing("VOO") is None
    assert alternate_listing("") is None
    assert alternate_listing(None) is None
    assert alternate_listing(".TO") is None


def test_fold_gives_a_dead_symbol_its_real_listings_holdings():
    comps = {"VOO.TO": {}, "VOO": {"top_holdings": {"AAPL": 0.4}}}
    folded = fold_alternate_listings(comps, ["VOO.TO"])
    assert folded["VOO.TO"]["top_holdings"] == {"AAPL": 0.4}


def test_fold_leaves_a_symbol_that_answered_for_itself():
    comps = {"XIC.TO": {"top_holdings": {"RY.TO": 0.08}},
             "XIC": {"top_holdings": {"SOMETHING": 1.0}}}
    folded = fold_alternate_listings(comps, ["XIC.TO"])
    assert folded["XIC.TO"]["top_holdings"] == {"RY.TO": 0.08}


def test_fold_does_nothing_without_an_alternate():
    comps = {"VAB.TO": {}}
    assert fold_alternate_listings(comps, ["VAB.TO"]) == comps


def test_expand_of_nothing_is_nothing():
    assert expand_compositions({}) == {}
    assert expand_compositions(None) == {}


# -- the low-volatility flag -------------------------------------------------

def test_low_volatility_flag_is_true_below_the_threshold():
    assert is_low_volatility({"volatility": 0.09}, 0.12) is True


def test_low_volatility_flag_is_false_above_the_threshold():
    assert is_low_volatility({"volatility": 0.30}, 0.12) is False


def test_low_volatility_flag_includes_the_threshold_itself():
    assert is_low_volatility({"volatility": 0.12}, 0.12) is True


def test_unmeasured_volatility_is_unknown_not_false():
    """A fund never refreshed has no volatility. Reporting it as failing the
    test would be an answer the data cannot support."""
    assert is_low_volatility({"volatility": None}, 0.12) is None
    assert is_low_volatility({}, 0.12) is None
    assert is_low_volatility({"volatility": ""}, 0.12) is None


def test_low_volatility_flag_follows_the_threshold_it_is_given():
    fund = {"volatility": 0.15}
    assert is_low_volatility(fund, 0.12) is False
    assert is_low_volatility(fund, 0.20) is True


def test_fund_symbol_prefers_the_yahoo_listing():
    assert fund_symbol({"ticker": "VFV", "yahoo": "VFV.TO"}) == "VFV.TO"
    assert fund_symbol({"ticker": "vug"}) == "VUG"
    assert fund_symbol({}) == ""


# -- the published Canadian risk rating (NI 81-102 Appendix F) --------------

def _monthly(years: float, monthly_sd: float, seed: int = 3) -> pd.Series:
    """Daily prices whose month-end returns have a known standard deviation."""
    rng = np.random.default_rng(seed)
    months = int(years * 12)
    idx = pd.date_range(end=pd.Timestamp("2026-08-01"), periods=months, freq="ME")
    steps = rng.normal(0, monthly_sd, size=months)
    return pd.Series(100 * np.cumprod(1 + steps), index=idx)


def test_csa_volatility_annualizes_monthly_by_root_twelve():
    prices = _monthly(12, monthly_sd=0.03)
    stdev, months = csa_volatility(prices)
    assert months == 120                     # capped at the ten-year window
    assert stdev == pytest.approx(0.03 * (12 ** 0.5), abs=0.02)


def test_csa_volatility_reports_how_many_months_it_used():
    stdev, months = csa_volatility(_monthly(5, 0.03))
    assert stdev is not None
    assert months == 59                      # 60 month-ends, 59 returns


def test_csa_volatility_refuses_too_short_a_history():
    stdev, months = csa_volatility(_monthly(2, 0.03))
    assert stdev is None                     # under three years, not reported
    assert months < 36


def test_csa_level_bands_match_appendix_f():
    # 0-6 low, 6-11 low to medium, 11-16 medium, 16-20 medium to high, 20+ high
    assert csa_level(0.0) == "Low"
    assert csa_level(0.059) == "Low"
    assert csa_level(0.06) == "Low to medium"
    assert csa_level(0.109) == "Low to medium"
    assert csa_level(0.11) == "Medium"
    assert csa_level(0.159) == "Medium"
    assert csa_level(0.16) == "Medium to high"
    assert csa_level(0.199) == "Medium to high"
    assert csa_level(0.20) == "High"
    assert csa_level(1.0) == "High"


def test_csa_level_of_nothing_is_nothing():
    assert csa_level(None) is None
    assert csa_level("n/a") is None


def test_compute_metrics_carries_the_rating_and_its_window():
    metrics = compute_metrics("SYNTH", prices=_monthly(12, 0.03), dividends=[])
    assert metrics["csa_level"] in {"Low", "Low to medium", "Medium",
                                    "Medium to high", "High"}
    assert metrics["csa_months"] == 120
    # The app's own volatility is a different measurement, kept alongside.
    assert metrics["csa_stdev"] != metrics.get("volatility")


# -- distribution yield ------------------------------------------------------

def _dividends(amounts, end="2026-08-01"):
    idx = pd.date_range(end=pd.Timestamp(end), periods=len(amounts), freq="QE")
    return pd.Series(amounts, index=idx)


def test_dividend_yield_is_trailing_twelve_months_over_price():
    divs = _dividends([0.25, 0.25, 0.25, 0.25])
    assert dividend_yield(divs, 100.0) == pytest.approx(0.01)


def test_dividend_yield_of_a_fund_paying_nothing_is_none():
    assert dividend_yield(pd.Series(dtype=float), 100.0) is None
    assert dividend_yield(None, 100.0) is None


def test_dividend_yield_needs_a_real_price():
    divs = _dividends([0.25, 0.25, 0.25, 0.25])
    assert dividend_yield(divs, 0) is None
    assert dividend_yield(divs, None) is None


# -- building an allocation from a rule --------------------------------------

def _candidates():
    """Four funds with published ratings, two of them the same exposure."""
    canada = {"pct_can": 1.0, "pct_us": 0.0, "pct_intl": 0.0, "pct_bond": 0.0,
              "pct_alt": 0.0, "category": "Canadian equity"}
    return [
        {"ticker": "VAB", "csa_level": "Low", "volatility": 0.06, "mer": 0.0009,
         "category": "Bonds", "pct_bond": 1.0, "pct_can": 0.0, "pct_us": 0.0,
         "pct_intl": 0.0, "pct_alt": 0.0},
        {"ticker": "VCN", "csa_level": "Medium", "volatility": 0.15, "mer": 0.0005, **canada},
        {"ticker": "XIC", "csa_level": "Medium", "volatility": 0.15, "mer": 0.0006, **canada},
        {"ticker": "SMH", "csa_level": "High", "volatility": 0.33, "mer": 0.0035,
         "category": "US semiconductors", "pct_us": 1.0, "pct_can": 0.0,
         "pct_intl": 0.0, "pct_bond": 0.0, "pct_alt": 0.0},
    ]


def test_build_allocation_equal_weights_the_eligible_funds():
    out = build_allocation(_candidates(), bands={"Low", "Medium"},
                           method="equal", drop_duplicates=False)
    assert out["weights"] == {"VAB": pytest.approx(1 / 3, abs=1e-3),
                              "VCN": pytest.approx(1 / 3, abs=1e-3),
                              "XIC": pytest.approx(1 / 3, abs=1e-3)}
    assert sum(out["weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_build_allocation_excludes_the_bands_you_did_not_pick():
    out = build_allocation(_candidates(), bands={"Low"}, drop_duplicates=False)
    assert list(out["weights"]) == ["VAB"]
    assert ("SMH", "rated High") in out["excluded"]


def test_build_allocation_says_a_fund_has_no_rating_yet():
    funds = _candidates() + [{"ticker": "NEW"}]
    out = build_allocation(funds, bands={"Low"}, drop_duplicates=False)
    assert ("NEW", "not rated yet") in out["excluded"]


def test_build_allocation_drops_one_of_a_duplicate_pair_by_cost():
    """VCN and XIC buy the same market; the cheaper one is kept, which is a
    rule rather than a preference."""
    out = build_allocation(_candidates(), bands={"Medium"}, drop_duplicates=True)
    assert list(out["weights"]) == ["VCN"]          # 0.05% vs 0.06% MER
    assert ("XIC", "same exposure as VCN") in out["excluded"]


def test_build_allocation_keeps_both_when_you_ask_it_to():
    out = build_allocation(_candidates(), bands={"Medium"}, drop_duplicates=False)
    assert set(out["weights"]) == {"VCN", "XIC"}


def test_inverse_volatility_gives_the_calmer_fund_more():
    out = build_allocation(_candidates(), bands={"Low", "Medium"},
                           method="inverse_vol", drop_duplicates=True)
    assert out["weights"]["VAB"] > out["weights"]["VCN"]      # 6% vol vs 15%
    assert sum(out["weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_inverse_volatility_skips_a_fund_with_nothing_measured():
    funds = _candidates() + [{"ticker": "GGOV", "csa_level": "Low"}]
    out = build_allocation(funds, bands={"Low"}, method="inverse_vol")
    assert "GGOV" not in out["weights"]
    assert ("GGOV", "no volatility measured") in out["excluded"]


def test_a_cap_moves_the_excess_to_the_others():
    out = build_allocation(_candidates(), bands={"Low", "Medium"},
                           method="equal", cap=0.40, drop_duplicates=False)
    assert max(out["weights"].values()) <= 0.40 + 1e-3
    assert sum(out["weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_a_cap_below_an_equal_share_leaves_everything_at_the_cap():
    # Three funds cannot each stay under 20%; the rule stops rather than loop.
    out = build_allocation(_candidates(), bands={"Low", "Medium"},
                           method="equal", cap=0.20, drop_duplicates=False)
    assert all(w == pytest.approx(0.20, abs=1e-3) for w in out["weights"].values())


def test_build_allocation_of_nothing_eligible_is_empty():
    out = build_allocation(_candidates(), bands=set())
    assert out["weights"] == {}
    assert len(out["excluded"]) == 4
