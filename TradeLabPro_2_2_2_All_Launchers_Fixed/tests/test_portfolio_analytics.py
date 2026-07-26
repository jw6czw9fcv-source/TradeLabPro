"""Tests for portfolio analytics (tradelab/core/portfolio_analytics.py).

All pure/offline: we build price frames with known behaviour and check the
valuation, concentration, correlation, and risk metrics fall out correctly.
"""
import numpy as np
import pandas as pd
import pytest

from tradelab.core import portfolio_analytics as pa


def _hist(values, start="2022-01-01"):
    idx = pd.date_range(start=start, periods=len(values), freq="B")
    v = np.asarray(values, dtype=float)
    return pd.DataFrame({"Close": v, "Open": v, "High": v, "Low": v,
                        "Volume": [0] * len(v)}, index=idx)


# --- positions & holdings ---------------------------------------------------

def test_aggregate_positions_merges_by_symbol():
    pos = [
        {"symbol": "AAPL", "shares": 100, "entry_price": 100.0},
        {"symbol": "AAPL", "shares": 100, "entry_price": 120.0},  # second lot
        {"symbol": "msft", "shares": 50, "entry_price": 300.0},
    ]
    agg = {a["symbol"]: a for a in pa.aggregate_positions(pos)}
    assert agg["AAPL"]["shares"] == 200
    assert agg["AAPL"]["avg_entry"] == pytest.approx(110.0)   # cost-weighted
    assert agg["MSFT"]["shares"] == 50


def test_holdings_valuation_and_weights():
    # AAPL: 100 sh, entry 100, last 150 -> mv 15000, +50%.
    # MSFT: 10 sh, entry 300, last 250 -> mv 2500, -16.7%.
    pos = [{"symbol": "AAPL", "shares": 100, "entry_price": 100.0},
           {"symbol": "MSFT", "shares": 10, "entry_price": 300.0}]
    hist = {"AAPL": _hist([100, 150]), "MSFT": _hist([300, 250])}
    rows, total = pa.holdings(pos, hist)
    assert total == pytest.approx(17500.0)
    by = {h["symbol"]: h for h in rows}
    assert by["AAPL"]["market_value"] == pytest.approx(15000.0)
    assert by["AAPL"]["unrealized"] == pytest.approx(5000.0)
    assert by["AAPL"]["unrealized_pct"] == pytest.approx(50.0)
    assert by["AAPL"]["weight_pct"] == pytest.approx(15000 / 17500 * 100, abs=0.1)
    assert by["MSFT"]["unrealized_pct"] == pytest.approx(-16.6667, abs=0.01)
    assert rows[0]["symbol"] == "AAPL"          # largest first


def test_holding_without_history_is_valued_none():
    pos = [{"symbol": "AAPL", "shares": 100, "entry_price": 100.0},
           {"symbol": "ZZZZ", "shares": 100, "entry_price": 10.0}]
    rows, total = pa.holdings(pos, {"AAPL": _hist([100, 110])})
    zz = next(h for h in rows if h["symbol"] == "ZZZZ")
    assert zz["market_value"] is None and zz["weight_pct"] is None
    assert total == pytest.approx(11000.0)      # only AAPL counted


# --- equity curve & risk metrics -------------------------------------------

def test_portfolio_equity_sums_shares_times_close():
    pos = [{"symbol": "A", "shares": 2, "entry_price": 1},
           {"symbol": "B", "shares": 3, "entry_price": 1}]
    hist = {"A": _hist([10, 11, 12]), "B": _hist([20, 20, 20])}
    eq = pa.portfolio_equity(pos, hist)
    # day0: 2*10+3*20=80 ; day2: 2*12+3*20=84
    assert eq.iloc[0] == pytest.approx(80.0)
    assert eq.iloc[-1] == pytest.approx(84.0)
    assert pa.total_return(eq) == pytest.approx((84 / 80 - 1) * 100)


def test_max_drawdown_is_worst_peak_to_trough():
    eq = pd.Series([100, 120, 90, 130], index=pd.date_range("2022-01-03", periods=4, freq="B"))
    # peak 120 -> trough 90 = -25%.
    assert pa.max_drawdown(eq) == pytest.approx(-25.0)


def test_beta_of_double_leveraged_series_is_two():
    idx = pd.date_range("2022-01-03", periods=60, freq="B")
    rng = np.random.default_rng(3)
    bench_ret = rng.normal(0, 0.01, size=len(idx))
    port_ret = 2.0 * bench_ret               # exactly 2x the benchmark's moves
    b = pa.beta(pd.Series(port_ret, index=idx), pd.Series(bench_ret, index=idx))
    assert b == pytest.approx(2.0, abs=1e-6)


def test_annualized_vol_scales_by_sqrt_252():
    r = pd.Series([0.01, -0.01] * 40)
    v = pa.annualized_vol(r)
    assert v == pytest.approx(float(r.std() * (252 ** 0.5) * 100.0))


# --- concentration & correlation -------------------------------------------

def test_concentration_effective_n_for_even_book():
    rows = [{"weight_pct": 25.0}, {"weight_pct": 25.0},
            {"weight_pct": 25.0}, {"weight_pct": 25.0}]
    c = pa.concentration(rows)
    assert c["largest_pct"] == pytest.approx(25.0)
    assert c["top3_pct"] == pytest.approx(75.0)
    assert c["effective_n"] == pytest.approx(4.0)     # evenly spread -> N=4


def test_concentration_flags_a_dominant_position():
    rows = [{"weight_pct": 90.0}, {"weight_pct": 5.0}, {"weight_pct": 5.0}]
    c = pa.concentration(rows)
    assert c["largest_pct"] == pytest.approx(90.0)
    assert c["effective_n"] < 1.3                     # dominated by one name


def _from_returns(rets, base=100.0):
    closes = [base]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    return _hist(closes)


def test_correlation_matrix_perfectly_correlated_and_inverse():
    rets = [0.02, -0.01, 0.03, -0.02, 0.015]
    up = _from_returns(rets, 100)
    also_up = _from_returns(rets, 50)              # same returns, different price -> corr 1
    down = _from_returns([-r for r in rets], 100)  # negated returns -> corr -1
    c = pa.correlation({"UP": up, "UP2": also_up, "DOWN": down})
    syms = c["symbols"]
    m = {(syms[i], syms[j]): c["matrix"][i][j]
         for i in range(len(syms)) for j in range(len(syms))}
    assert m[("UP", "UP2")] == pytest.approx(1.0, abs=0.01)
    assert m[("UP", "DOWN")] == pytest.approx(-1.0, abs=0.01)


def test_correlation_single_symbol_is_empty():
    c = pa.correlation({"AAPL": _hist([100, 101, 102])})
    assert c["matrix"] == [] and c["avg_pairwise"] is None


# --- summarize --------------------------------------------------------------

def _rate(n, val, start="2022-01-01"):
    return pd.Series([val] * n, index=pd.date_range(start, periods=n, freq="B"))


def test_currency_of():
    assert pa.currency_of("XDIV.TO") == "CAD"
    assert pa.currency_of("VTI") == "USD"
    assert pa.currency_of("VOD.L") == "GBP"


def test_holdings_native_prices_cad_aggregates():
    # Mirrors IBKR: per-share prices stay native; value/cost/P&L are in CAD.
    pos = [{"symbol": "VTI", "shares": 10, "entry_price": 300.0},     # native USD
           {"symbol": "XIC.TO", "shares": 100, "entry_price": 50.0}]  # native CAD
    hist = {"VTI": _hist([300, 320]), "XIC.TO": _hist([50, 55])}
    fx = {"USD": _rate(2, 1.4)}                                       # 1 USD = 1.4 CAD
    rows, total = pa.holdings(pos, hist, target="CAD", fx=fx)
    by = {h["symbol"]: h for h in rows}
    assert round(by["VTI"]["last"], 2) == 320.0                       # native, NOT converted
    assert round(by["VTI"]["avg_entry"], 2) == 300.0                  # native
    assert round(by["VTI"]["market_value"], 0) == 4480               # 320*10*1.4 (CAD)
    assert round(by["VTI"]["cost_basis"], 0) == 4200                 # 300*10*1.4 (CAD)
    assert round(by["VTI"]["unrealized"], 0) == 280                  # CAD
    assert by["VTI"]["unrealized_pct"] == pytest.approx(6.667, abs=0.01)  # native move
    assert round(by["XIC.TO"]["last"], 2) == 55.0                     # CAD holding unchanged
    assert round(total, 0) == 9980                                    # CAD market value


def test_portfolio_equity_in_target_currency():
    pos = [{"symbol": "VTI", "shares": 1, "entry_price": 1},
           {"symbol": "XIC.TO", "shares": 1, "entry_price": 1}]
    hist = {"VTI": _hist([100, 110]), "XIC.TO": _hist([10, 10])}
    eq = pa.portfolio_equity(pos, hist, target="CAD", fx={"USD": _rate(2, 2.0)})
    assert eq.iloc[0] == pytest.approx(210.0)     # 100*2 + 10
    assert eq.iloc[-1] == pytest.approx(230.0)    # 110*2 + 10


def test_summarize_reports_currency_and_missing_fx():
    pos = [{"symbol": "VTI", "shares": 1, "entry_price": 300},
           {"symbol": "XYZ.L", "shares": 1, "entry_price": 10}]     # GBP, no rate supplied
    hist = {"VTI": _hist([300, 310]), "XYZ.L": _hist([10, 11])}
    r = pa.summarize(pos, hist, target_currency="CAD", fx={"USD": _rate(2, 1.4)})
    assert r["currency"] == "CAD"
    assert r["fx_missing"] == ["GBP"]             # GBP couldn't be converted


def test_summarize_unrealized_excludes_unpriced_cost():
    # Regression: a holding with no price data must not drag its cost into the
    # unrealized P&L (that silently understated the total).
    pos = [{"symbol": "AAA", "shares": 10, "entry_price": 100},   # priced
           {"symbol": "ZZZZ", "shares": 10, "entry_price": 50}]   # no data
    r = pa.summarize(pos, {"AAA": _hist([100, 110])})
    assert r["total_value"] == pytest.approx(1100.0)
    assert r["total_unrealized"] == pytest.approx(100.0)          # 1100 - 1000, not -400
    assert r["total_unrealized_pct"] == pytest.approx(10.0)
    assert r["no_data"] == ["ZZZZ"]
    assert r["total_cost"] == pytest.approx(1500.0)               # full cost still reported


def test_summarize_flags_window_truncation():
    # One holding has far less history -> the common window shrinks and the
    # culprit is named; equal histories -> no flag.
    long_h = _hist([100 + i for i in range(100)])
    short_h = _hist([50 + i for i in range(20)], start="2022-04-25")
    pos = [{"symbol": "LONG", "shares": 1, "entry_price": 1},
           {"symbol": "SHORT", "shares": 1, "entry_price": 1}]
    r = pa.summarize(pos, {"LONG": long_h, "SHORT": short_h})
    assert r["window_limited_by"] == "SHORT"
    r2 = pa.summarize(pos, {"LONG": long_h, "SHORT": _hist([50 + i for i in range(100)])})
    assert r2["window_limited_by"] is None


def test_summarize_per_holding_vs_benchmark():
    # Holding up 20% over the window, benchmark up 5% -> vs = +15% over same dates.
    pos = [{"symbol": "AAA", "shares": 10, "entry_price": 100}]
    hist = {"AAA": _hist([100, 120])}
    r = pa.summarize(pos, hist, benchmark_df=_hist([100, 105]), benchmark_symbol="SPY")
    h = r["holdings"][0]
    assert round(h["window_return_pct"], 1) == 20.0
    assert round(h["vs_benchmark_pct"], 1) == 15.0


def test_summarize_empty_is_safe():
    r = pa.summarize([], {})
    assert r["total_value"] == 0
    assert "No positions" in r["text"]


def test_summarize_zero_cost_basis_does_not_crash():
    # Regression: a position entered at $0 (no cost basis) has an unrealized
    # dollar figure but no unrealized %, which must not break the summary text.
    pos = [{"symbol": "A", "shares": 100, "entry_price": 0.0}]
    hist = {"A": _hist([10, 11, 12])}
    r = pa.summarize(pos, hist)
    assert r["total_unrealized"] is not None
    assert r["total_unrealized_pct"] is None       # 0 cost -> undefined %
    assert "unrealized" in r["text"]               # text builds without error


def test_summarize_end_to_end_with_benchmark():
    idx = pd.date_range("2022-01-03", periods=120, freq="B")
    rng = np.random.default_rng(11)
    bench = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, size=len(idx))))
    a = 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, size=len(idx))))
    pos = [{"symbol": "A", "shares": 100, "entry_price": 45.0}]
    hist = {"A": pd.DataFrame({"Close": a, "Open": a, "High": a, "Low": a,
                              "Volume": [0] * len(a)}, index=idx)}
    bdf = pd.DataFrame({"Close": bench, "Open": bench, "High": bench, "Low": bench,
                       "Volume": [0] * len(bench)}, index=idx)
    r = pa.summarize(pos, hist, benchmark_df=bdf, benchmark_symbol="SPY")
    assert r["total_value"] > 0
    assert r["beta"] is not None
    assert r["max_drawdown_pct"] is not None and r["max_drawdown_pct"] <= 0
    assert r["benchmark_return_pct"] is not None
    assert r["window_days"] > 0
    assert "beta" in r["text"]
