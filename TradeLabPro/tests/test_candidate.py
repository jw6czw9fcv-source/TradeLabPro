"""The candidate check: facts about a fund or stock before buying it."""
import numpy as np
import pandas as pd
import pytest

from tradelab.core import candidate as cd


def _prices(values, end="2026-10-16"):
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def _ten_years(drift=0.0003, crash_at=None, seed=3):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, 0.008, 2660)                 # a little over ten years of sessions
    if crash_at is not None:
        r[crash_at:crash_at + 30] = -0.012          # a ~30% fall over six weeks
    return _prices(100 * np.exp(np.cumsum(r)))


def test_us_and_canadian_listings_are_told_apart():
    assert cd.is_us_listed("VTI") and cd.is_us_listed("NVDA")
    assert not cd.is_us_listed("XBB.TO") and not cd.is_us_listed("BRK.B") and not cd.is_us_listed("")


def test_the_worst_fall_and_when():
    p = _prices([100, 120, 90, 60, 80, 130] + [130] * 30)
    fall, peak, trough = cd.worst_drawdown(p)
    assert fall == pytest.approx(-0.5)
    assert peak == p.index[1] and trough == p.index[3]
    assert cd.worst_drawdown(_prices([1, 2, 3])) is None


def test_annualized_returns_need_the_history():
    p = _prices([100 * 1.10 ** (i / 260) for i in range(5 * 260 + 10)])
    assert cd.annualized_return(p, 1) == pytest.approx(0.10, abs=0.01)
    assert cd.annualized_return(p, 5) == pytest.approx(0.10, abs=0.01)
    assert cd.annualized_return(p, 10) is None


def test_placement_follows_the_us_withholding_rule():
    us = cd.placement("VTI", 0.013)
    assert us["suits"] == "REER" and "Article XXI" in us["text"] and "$20" in us["text"]
    assert cd.placement("XUU.TO", 0.012)["suits"] == "either"
    assert cd.placement("NVDA", 0.0)["suits"] == "either"


def test_overlap_counts_what_you_already_own():
    o = cd.overlap({"AAPL": 0.07, "MSFT": 0.06, "XOM": 0.03}, {"AAPL": "RRSP", "MSFT": "inside VGT"})
    assert o["pct"] == pytest.approx(13.0) and o["names"] == ["AAPL", "MSFT"]
    assert o["covered_pct"] == pytest.approx(16.0)


def _labels(items):
    return {label: (kind, text) for kind, label, text in items}


def test_a_fund_is_assessed_line_by_line():
    items = cd.assess("VTI", _ten_years(crash_at=1500), {"name": "Total Market", "quote_type": "ETF",
                                                          "sector": "Large Blend"},
                      mer=0.0003, dividend_yield=0.013, holdings={"AAPL": 0.06, "MSFT": 0.05},
                      owned={"AAPL": "RRSP"}, split={"stocks": 1.0}, account="CELI",
                      account_rows=[{"class": "stocks", "drift_pp": 12.0}])
    got = _labels(items)
    assert got["Fees"][0] == "ok" and "$3 a year" in got["Fees"][1]
    assert "CSA band" in got["Risk"][1]
    assert got["Worst fall"][0] == "warn"
    assert "10 yr" in got["Returns"][1]
    assert "AAPL" in got["Overlap"][1]
    assert got["Your plan"][0] == "warn" and "12 points over" in got["Your plan"][1]
    assert got["Account"][0] == "warn"                     # US dividends, going into a CELI


def test_a_stock_and_a_missing_fee_say_so():
    got = _labels(cd.assess("NVDA", _ten_years(), {"quote_type": "EQUITY"}, holdings={"NVDA": 1.0},
                            owned={}, split={"stocks": 1.0}))
    assert "no management fee" in got["Fees"][1] and got["Spread"][0] == "warn"
    fund = _labels(cd.assess("ZZZ.TO", None, {"quote_type": "ETF"}))
    assert "Not on file" in fund["Fees"][1] and "Too little" in fund["History"][1]


# --- in the Plan tab ------------------------------------------------------------------

pytest.importorskip("PySide6")


def test_the_plan_tab_checks_a_candidate(tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from tradelab.data.database import Database
    from tradelab.ui.panels.plan import PlanPanel
    QApplication.instance() or QApplication([])
    db = Database(path=tmp_path / "c.db")
    db.set_portfolio_positions("RRSP", [{"symbol": "VGT", "shares": 10, "entry_price": 500}])
    panel = PlanPanel(db, settings=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    panel._cand_symbol = "VTI"
    panel.cand_account.setCurrentText("RRSP")
    panel._on_candidate({"prices": _ten_years(), "meta": {"quote_type": "ETF", "name": "VTI"},
                         "yield": 0.013, "holdings": {"AAPL": 0.06, "XOM": 0.02},
                         "owned_comps": {"VGT": {"AAPL": 0.15}}}, "")
    texts = [panel.cand_list.item(i).text() for i in range(panel.cand_list.count())]
    assert any("Overlap" in t and "AAPL" in t for t in texts)
    assert any("Account" in t and "REER" in t for t in texts)
    assert "Facts, not advice" in panel.status.text()
    db.conn.close()


def test_an_empty_symbol_pops_up(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from tradelab.data.database import Database
    from tradelab.ui.panels.plan import PlanPanel
    QApplication.instance() or QApplication([])
    shown = []
    monkeypatch.setattr("tradelab.ui.common.show_problem", lambda text, parent=None: shown.append(text))
    db = Database(path=tmp_path / "c.db")
    panel = PlanPanel(db, settings=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    panel.check_candidate()
    assert shown and "Type a symbol" in shown[0]
    db.conn.close()


def test_a_fee_from_yahoo_is_named_as_such():
    items = cd.assess("XEQT.TO", None, {"quote_type": "ETF"}, mer=0.002, mer_source="Yahoo")
    fees = next(t for _k, label, t in items if label == "Fees")
    assert fees.startswith("MER 0.20% (Yahoo)") and "$20 a year" in fees


def test_yahoo_expense_ratios_are_read_as_percent(monkeypatch):
    from tradelab.data import market_data
    info = {"quoteType": "ETF", "netExpenseRatio": 0.2, "category": "Global Equity", "longName": "XEQT"}
    monkeypatch.setattr(market_data, "yf", type("_yf", (), {
        "Ticker": staticmethod(lambda s: type("_t", (), {"info": info})())}))
    meta = market_data._yahoo_quote_meta("XEQT.TO")
    assert meta["expense_ratio"] == pytest.approx(0.002)
