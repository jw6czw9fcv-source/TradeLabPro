"""CELI / REER contribution room, and the return with the money put in left
out, beside the Guide's level. Made-up amounts only."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from tradelab.core import guide as g
from tradelab.core import room
from tradelab.data.database import Database

D = dt.date


def test_celi_room_counts_deposits_and_gives_withdrawals_back_next_year():
    flows = [{"account": "CELI", "day": "2026-02-01", "amount": 5000},
             {"account": "CELI", "day": "2026-06-01", "amount": -2000},
             {"account": "REER", "day": "2026-03-01", "amount": 9999},       # other account
             {"account": "CELI", "day": "2025-12-01", "amount": 4000}]       # before the room date
    s = room.status("CELI", 10000, "2026-01-15", flows, today=D(2026, 11, 1))
    assert s["used"] == 5000 and s["left"] == 5000 and s["pending_back"] == 2000
    s = room.status("CELI", 10000, "2026-01-15", flows, today=D(2027, 1, 2))
    assert s["back"] == 2000 and s["unknown_years"] == [2027]               # 2027 limit not known
    s = room.status("CELI", 0, "2025-06-01", [], today=D(2026, 1, 2))
    assert s["added"] == 7000 and s["left"] == 7000                         # the 2026 limit


def test_over_the_room_and_the_reer_allowance():
    celi = room.status("CELI", 1000, "2026-01-01",
                       [{"account": "CELI", "day": "2026-03-01", "amount": 1500}], D(2026, 5, 1))
    assert celi["over"] == 500 and celi["excess"] == 500
    reer = room.status("REER", 1000, "2026-01-01",
                       [{"account": "REER", "day": "2026-03-01", "amount": 2500}], D(2026, 5, 1))
    assert reer["over"] == 1500 and reer["excess"] == 0                     # inside $2,000
    reer = room.status("REER", 1000, "2026-01-01",
                       [{"account": "REER", "day": "2026-03-01", "amount": 4000},
                        {"account": "REER", "day": "2026-04-01", "amount": -3000}], D(2026, 5, 1))
    assert reer["over"] == 3000 and reer["excess"] == 1000                  # a withdrawal gives nothing back
    kinds = [k for k, _t in room.check_items([celi, reer])]
    assert kinds == ["warn", "warn"]
    ok = room.status("CELI", 7000, "2026-01-01", [], D(2026, 5, 1))
    assert room.check_items([ok]) == [("ok", "CELI: $7,000 of room left.")]
    assert room.would_exceed(ok, 5000) == 0 and room.would_exceed(ok, 9000) == 2000


def test_the_return_leaves_the_money_put_in_out():
    # $10,000 grows to $12,100 with $1,000 deposited halfway: about 10%, not 21%.
    r = room.modified_dietz(10000, 12100, [("2026-07-02", 1000)], "2026-01-01", "2026-12-31")
    assert r == pytest.approx(0.105, abs=0.002)
    assert room.modified_dietz(10000, 11000, [], "2026-01-01", "2026-01-01") is None
    assert room.annualized(0.21, 730) == pytest.approx(0.1, abs=0.001)


def _daily(start, values):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def test_a_levels_growth_between_two_days():
    n = 30
    prices = {s: _daily("2026-01-01", np.linspace(100, 110, n)) for s in g.STOCK_PROXIES}
    prices[g.BOND_PROXY] = _daily("2026-01-01", np.full(n, 50.0))
    prices[g.FX] = _daily("2026-01-01", np.full(n, 1.35))
    end = prices[g.BOND_PROXY].index[-1]
    all_stocks = g.level_growth(prices, 5, "2026-01-01", end)
    assert all_stocks == pytest.approx(0.10, abs=0.001)
    balanced = g.level_growth(prices, 3, "2026-01-01", end)
    assert balanced == pytest.approx(0.06, abs=0.001)                      # 60% of it
    assert g.level_growth({}, 3, "2026-01-01", end) is None


def test_the_return_text():
    from PySide6.QtWidgets import QApplication  # noqa: F401 - the panel module imports Qt
    from tradelab.ui.panels.plan import return_text
    short = return_text(0.021, 0.015, "Balanced", D(2026, 10, 15), D(2026, 11, 1))
    assert "+2.1%" in short and "Balanced +1.5%" in short and "Too short" in short
    long = return_text(0.21, 0.16, "Balanced", D(2024, 11, 1), D(2026, 11, 1))
    assert "a year" in long and "Too short" not in long


pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_plan_tab_keeps_the_room_and_warns_before_an_excess(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QDate, QSettings
    from PySide6.QtWidgets import QMessageBox
    from tradelab.ui.panels import plan as plan_mod
    db = Database(path=tmp_path / "r.db")
    panel = plan_mod.PlanPanel(db, settings=QSettings(str(tmp_path / "p.ini"), QSettings.IniFormat))
    amount, day = panel.room_edits["CELI"]
    amount.setValue(7000); day.setDate(QDate(2026, 1, 1))
    panel.save_room("CELI")
    assert db.contribution_room()["CELI"] == {"room": 7000, "as_of": "2026-01-01"}
    panel.flow_day.setDate(QDate.currentDate())
    panel.flow_account.setCurrentText("CELI"); panel.flow_amount.setValue(5000)
    assert panel.record_flow()
    assert "$2,000 of room left" in panel.room_line.text()
    # Over the room: asked first, and No records nothing.
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    panel.flow_amount.setValue(3000)
    assert not panel.record_flow()
    assert "$1,000 past your CELI room" in asked[0] and len(db.contributions()) == 1
    assert any("room left" in t for _k, t in panel.check_items)
    panel.flow_table.selectRow(0)
    panel.remove_flows()
    assert db.contributions() == []
    db.conn.close()


def test_the_plan_tab_compares_the_return_with_the_level(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from tradelab.ui.panels import plan as plan_mod
    from tradelab.ui.panels.guide import PROFILE_KEY
    db = Database(path=tmp_path / "v.db")
    s = QSettings(str(tmp_path / "p.ini"), QSettings.IniFormat)
    panel = plan_mod.PlanPanel(db, settings=s)
    panel.compare_return()
    assert "few days" in panel.return_line.text()
    for day, value in (("2026-10-01", 10000), ("2026-10-31", 11100)):
        db.record_value({"day": day, "currency": "CAD", "value": value})
    db.add_contribution("CELI", "2026-10-15", 1000)
    panel.compare_return()
    assert "choose a level" in panel.return_line.text()
    s.setValue(PROFILE_KEY, json.dumps({"level": 3}))
    started = []
    monkeypatch.setattr(plan_mod, "_ReturnWorker", lambda period: started.append(period) or
                        type("W", (), {"done": type("S", (), {"connect": lambda *a: None})(),
                                       "start": lambda self: None, "isRunning": lambda self: False})())
    panel.compare_return()
    assert started == ["2y"]
    panel._on_return(None)
    assert "your book" in panel.return_line.text() and "deposits left out" in panel.return_line.text()
    db.conn.close()
