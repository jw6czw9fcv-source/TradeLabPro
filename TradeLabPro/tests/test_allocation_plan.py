"""The investing plan check: classes, mix, drift, rebalancing, trading cap,
review rhythm - and the Plan tab that shows them."""
import datetime as dt

import pandas as pd
import pytest

from tradelab.core import allocation_plan as ap


def test_a_holding_is_classed_from_what_it_is():
    assert ap.guess_class({"quote_type": "EQUITY", "sector": "Technology"}) == "stocks"
    assert ap.guess_class({"quote_type": "ETF", "sector": "Canadian Fixed Income"}) == "bonds"
    assert ap.guess_class({"quote_type": "ETF", "sector": "Money Market"}) == "cash"
    assert ap.guess_class({"quote_type": "ETF", "sector": "Commodities Focused", "name": "Gold"}) == "other"
    assert ap.guess_class({"quote_type": "ETF", "sector": "Technology"}) == "stocks"
    assert ap.guess_class(None) == "stocks"


def test_a_screener_fund_is_split_by_its_published_composition_and_a_hand_class_wins():
    etfs = [{"ticker": "VBAL", "yahoo": "VBAL.TO", "pct_can": 0.18, "pct_us": 0.25,
             "pct_intl": 0.17, "pct_bond": 0.40, "pct_alt": 0.0}]
    split = ap.split_of("VBAL.TO", etfs)
    assert split == pytest.approx({"stocks": 0.60, "bonds": 0.40})
    assert ap.split_of("VBAL.TO", etfs, override="bonds") == {"bonds": 1.0}
    assert ap.split_of("XBB.TO", etfs, meta={"quote_type": "ETF", "sector": "Bond"}) == {"bonds": 1.0}


def test_the_mix_counts_split_funds_and_cash():
    mix = ap.current_mix([{"value": 10_000, "split": {"stocks": 0.6, "bonds": 0.4}},
                          {"value": 5_000, "split": {"stocks": 1.0}}], cash_value=1_000)
    assert mix == {"stocks": 11_000, "bonds": 4_000, "cash": 1_000, "other": 0.0}


def test_targets_must_add_up_to_100():
    assert ap.check_target({"stocks": 60, "bonds": 40, "cash": 0}) is None
    assert "add up to 90" in ap.check_target({"stocks": 60, "bonds": 30, "cash": 0})
    assert "negative" in ap.check_target({"stocks": 110, "bonds": -10, "cash": 0})


def test_drift_and_what_getting_back_would_take():
    out = ap.rebalance({"stocks": 90_000, "bonds": 10_000, "cash": 0, "other": 0},
                       {"stocks": 60, "bonds": 40, "cash": 0})
    rows = {r["class"]: r for r in out["rows"]}
    assert out["total"] == 100_000
    assert rows["stocks"]["change"] == pytest.approx(-30_000)
    assert rows["bonds"]["change"] == pytest.approx(30_000)
    assert sorted(out["drifted"]) == ["bonds", "stocks"]
    calm = ap.rebalance({"stocks": 62_000, "bonds": 38_000, "cash": 0, "other": 0},
                        {"stocks": 60, "bonds": 40, "cash": 0})
    assert calm["drifted"] == []


def test_the_trading_cap():
    ok = ap.trading_check(4_000, 100_000, 10)
    assert not ok["over"] and ok["room"] == pytest.approx(6_000)
    over = ap.trading_check(15_000, 100_000, 10)
    assert over["over"] and over["room"] == pytest.approx(-5_000)


def test_the_review_rhythm():
    today = dt.date(2026, 10, 18)
    assert ap.review_due(None, today)["due"]
    soon = ap.review_due(dt.date(2026, 9, 1), today)
    assert not soon["due"] and soon["next"] == dt.date(2026, 12, 1)
    assert ap.review_due(dt.date(2026, 6, 1), today)["due"]


# --- the tab --------------------------------------------------------------------------

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _daily(values):
    idx = pd.bdate_range(end=pd.Timestamp("2026-10-16"), periods=len(values))
    return pd.DataFrame({"Open": values, "High": values, "Low": values, "Close": values,
                         "Volume": [1000] * len(values)}, index=idx)


def test_the_plan_tab_checks_each_portfolio_against_its_target(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from tradelab.data.database import Database
    from tradelab.ui.panels.plan import PlanPanel
    db = Database(path=tmp_path / "p.db")
    db.set_portfolio_positions("RRSP", [{"symbol": "VTI", "shares": 100, "entry_price": 200}])
    db.set_portfolio_positions("Swing", [{"symbol": "ABC.TO", "shares": 10, "entry_price": 10}])
    db.set_cash("RRSP", "CAD", 2_000)
    db.set_plan_target("RRSP", 60, 40, 0)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    panel = PlanPanel(db, settings=settings)
    panel.trading.setCurrentText("Swing")
    panel.cap.setValue(5)
    panel._fx_pairs = {"USD": "USDCAD=X"}
    histories = {"VTI": _daily([300.0, 300.0]), "ABC.TO": _daily([100.0, 100.0]),
                 "USDCAD=X": _daily([1.4, 1.4])}
    metas = {"VTI": {"quote_type": "ETF", "sector": "Large Blend"},
             "ABC.TO": {"quote_type": "EQUITY", "sector": "Industrials"}}
    panel._on_priced(histories, metas, "")
    texts = [t for _k, t in panel.check_items]
    # RRSP: 42,000 of VTI (stocks) + 2,000 cash against 60/40/0.
    rrsp = next(t for t in texts if t.startswith("RRSP") and "off its target" in t)
    assert any(t.startswith("RRSP") and "$2,000 bonds" in t for t in texts)   # its cash, put to work
    assert "off its target" in rrsp and "sell $15,600 stocks" in rrsp and "buy $17,600 bonds" in rrsp
    swing = next(t for t in texts if t.startswith("Trading"))
    assert "inside its 5% cap" in swing                     # 1,000 of 45,000
    assert any("Review due" in t for t in texts)
    assert any("Safe budget not checked" in t for t in texts)
    # A class set by hand changes the check at once.
    panel._set_class("VTI", 2)                              # bonds
    rrsp = next(t for _k, t in panel.check_items if t.startswith("RRSP") and "target" in t and "cash beyond" not in t)
    assert "buy" in rrsp and "stocks" in rrsp
    db.conn.close()


def test_a_bad_target_is_refused_with_a_popup(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QTableWidgetItem
    from tradelab.data.database import Database
    from tradelab.ui.panels.plan import PlanPanel
    shown = []
    monkeypatch.setattr("tradelab.ui.common.show_problem", lambda text, parent=None: shown.append(text))
    db = Database(path=tmp_path / "p.db")
    db.set_cash("CELI", "CAD", 1_000)
    panel = PlanPanel(db, settings=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    for c, v in enumerate(["70", "20", "0"], start=1):
        panel.targets.setItem(0, c, QTableWidgetItem(v))
    panel.save_targets()
    assert shown and "add up to 90" in shown[0]
    assert db.plan_targets() == {}
    db.conn.close()


def test_cash_beyond_the_target_is_spread_by_shortfall_without_selling():
    # 90k cash, 10k stocks, target 60/40/0: 50k short of stocks, 40k of bonds.
    out = ap.deploy_cash({"stocks": 10_000, "bonds": 0, "cash": 90_000, "other": 0},
                         {"stocks": 60, "bonds": 40, "cash": 0})
    assert out["investable"] == pytest.approx(90_000)
    assert out["buys"]["stocks"] == pytest.approx(50_000)
    assert out["buys"]["bonds"] == pytest.approx(40_000)
    assert out["after_pct"]["stocks"] == pytest.approx(60) and out["after_pct"]["cash"] == pytest.approx(0)


def test_cash_short_of_the_gaps_goes_in_proportion_and_the_target_cash_is_kept():
    # 20k cash, target keeps 5% cash (5k): 15k to spread over 40k/20k of gaps.
    out = ap.deploy_cash({"stocks": 20_000, "bonds": 60_000, "cash": 20_000, "other": 0},
                         {"stocks": 60, "bonds": 35, "cash": 5})
    assert out["investable"] == pytest.approx(15_000)
    assert out["buys"]["stocks"] == pytest.approx(15_000)        # bonds are over target
    assert out["buys"]["bonds"] == pytest.approx(0)
    none = ap.deploy_cash({"stocks": 60_000, "bonds": 40_000, "cash": 0, "other": 0},
                          {"stocks": 60, "bonds": 40, "cash": 0})
    assert none["investable"] == 0
