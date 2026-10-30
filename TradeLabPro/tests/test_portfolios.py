"""Portfolios by name (add, rename, remove) and swing trades kept inside a
long-term portfolio. Made-up names and figures only."""
import json

import pytest

from tradelab.core import allocation_plan as ap
from tradelab.data.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "p.db")
    yield d
    d.conn.close()


def test_a_portfolio_can_exist_empty_and_is_listed_with_the_others(db):
    db.set_portfolio_positions("REER A", [{"symbol": "AAA", "shares": 1, "entry_price": 1}])
    db.set_cash("Cash only", "CAD", 10)
    db.set_plan_target("Target only", 60, 40, 0)
    db.add_portfolio("CELI B")
    assert db.portfolio_names() == ["CELI B", "Cash only", "REER A", "Target only"]
    with pytest.raises(ValueError, match="already"):
        db.add_portfolio("REER A")
    with pytest.raises(ValueError):
        db.add_portfolio("  ")


def test_rename_carries_everything_and_refuses_a_name_in_use(db):
    db.set_portfolio_positions("Old", [{"symbol": "AAA", "shares": 2, "entry_price": 1}])
    db.set_cash("Old", "CAD", 50)
    db.set_plan_target("Old", 80, 20, 0)
    db.add_portfolio("Other")
    with pytest.raises(ValueError, match="already"):
        db.rename_portfolio("Old", "Other")
    db.rename_portfolio("Old", "New")
    assert "Old" not in db.portfolio_names() and "New" in db.portfolio_names()
    assert {p["portfolio"] for p in db.positions()} == {"New"}
    assert db.cash()[0]["portfolio"] == "New"
    assert db.plan_targets() == {"New": {"stocks": 80, "bonds": 20, "cash": 0}}
    with pytest.raises(ValueError, match="no portfolio"):
        db.rename_portfolio("Gone", "X")


def test_remove_deletes_its_positions_cash_and_target_only(db):
    for name in ("Keep", "Drop"):
        db.set_portfolio_positions(name, [{"symbol": "AAA", "shares": 1, "entry_price": 1}])
        db.set_cash(name, "CAD", 5)
        db.set_plan_target(name, 100, 0, 0)
    assert db.portfolio_contents("Drop") == {"positions": 1, "cash": 1, "target": True}
    db.remove_portfolio("Drop")
    assert db.portfolio_names() == ["Keep"]
    assert db.portfolio_contents("Keep")["positions"] == 1


def test_swing_trades_stay_out_of_the_mix():
    holdings = [{"value": 900, "split": {"stocks": 1.0}},
                {"value": 100, "split": ap.split_of("ZZZ", [], ap.TRADING)}]
    mix = ap.current_mix(holdings, cash_value=0)
    assert mix["stocks"] == 900 and sum(mix.values()) == 900
    assert ap.trading_in(holdings) == 100


def test_renaming_or_removing_carries_the_settings(tmp_path):
    from PySide6.QtCore import QSettings
    from tradelab.ui.app import carry_portfolio_settings, save_sync_targets, sync_targets
    from tradelab.ui.panels.guide import PROFILE_KEY
    from tradelab.ui.panels.plan import TRADING_KEY
    s = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    save_sync_targets([{"portfolio": "Old", "query": "1"}, {"portfolio": "Other", "query": ""}], s)
    s.setValue(TRADING_KEY, "Old")
    s.setValue(PROFILE_KEY, json.dumps({"level": 3, "portfolio": "Old"}))
    carry_portfolio_settings("Old", "New", s)
    assert [t["portfolio"] for t in sync_targets(s)] == ["New", "Other"]
    assert sync_targets(s)[0]["query"] == "1"
    assert s.value(TRADING_KEY) == "New"
    assert json.loads(s.value(PROFILE_KEY))["portfolio"] == "New"
    carry_portfolio_settings("New", None, s)
    assert [t["portfolio"] for t in sync_targets(s)] == ["Other"]
    assert s.value(TRADING_KEY) == ""


pytest.importorskip("PySide6")


def test_the_portfolio_tab_adds_renames_and_removes(db, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from tradelab.ui import app as app_mod
    QApplication.instance() or QApplication([])
    carried = []
    monkeypatch.setattr(app_mod, "carry_portfolio_settings", lambda o, n: carried.append((o, n)))
    panel = app_mod.PortfolioPanel(db)
    panel.add_portfolio("CELI B")
    assert panel.portfolio_pick.currentText() == "CELI B"
    panel.sym.setText("aaa"); panel.shares.setValue(3); panel.entry.setValue(10)
    panel.add()
    assert db.positions()[0]["portfolio"] == "CELI B"          # Add Position goes there
    panel.rename_portfolio("CELI C")
    assert db.portfolio_names() == ["CELI C"] and carried == [("CELI B", "CELI C")]
    assert panel.portfolio_pick.currentText() == "CELI C"
    panel.remove_portfolio(confirm=False)
    assert db.portfolio_names() == [] and db.positions() == []
    assert carried[-1] == ("CELI C", None)


def test_the_plan_tab_caps_swing_trades_inside_each_portfolio(db, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from tradelab.ui.panels.plan import PlanPanel
    QApplication.instance() or QApplication([])
    db.set_plan_target("REER A", 100, 0, 0)
    panel = PlanPanel(db, settings=QSettings(str(tmp_path / "plan.ini"), QSettings.IniFormat))
    panel.cap.setValue(10)
    panel.holdings = [
        {"portfolio": "REER A", "symbol": "LONG", "value": 8500.0, "split": {"stocks": 1.0}, "auto": True},
        {"portfolio": "REER A", "symbol": "SWING", "value": 1500.0, "split": {ap.TRADING: 1.0}, "auto": False}]
    panel.recompute()
    texts = [t for _k, t in panel.check_items]
    swing = next(t for t in texts if "swing trades" in t)
    assert "15.0%" in swing and "above its 10% cap by $500" in swing
    assert any("REER A: on target" in t for t in texts)          # the trade is out of the mix
    assert not any("No trading portfolio chosen" in t for t in texts)
