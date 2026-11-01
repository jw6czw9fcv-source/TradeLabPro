"""The plan as one light on Home, and a word of calm when the market falls."""
import datetime as dt
import json

import pandas as pd
import pytest

from tradelab.core import allocation_plan as ap
from tradelab.core import guide as g


def test_the_plan_light():
    assert ap.status_light([]) == ("", "")
    assert ap.status_light([("ok", "a"), ("info", "b")]) == ("green", "Your plan is on track.")
    assert ap.status_light([("warn", "REER: off its target"), ("ok", "x")]) == \
        ("yellow", "REER: off its target")
    light, text = ap.status_light([("warn", "one"), ("warn", "two")])
    assert light == "yellow" and text == "one (and 1 more)"
    assert ap.status_light([("warn", "a"), ("warn", "b"), ("warn", "c")])[0] == "red"
    assert ap.status_light([("warn", "Spending $70,000 is above the safe budget")])[0] == "red"


def test_the_next_purchase_date():
    d = dt.date
    assert g.next_reminder(0, None, d(2026, 11, 5)) is None
    assert g.next_reminder(10, None, d(2026, 11, 5)) == d(2026, 11, 10)
    assert g.next_reminder(10, None, d(2026, 11, 12)) == d(2026, 11, 12)          # due now
    assert g.next_reminder(10, d(2026, 11, 12), d(2026, 11, 20)) == d(2026, 12, 10)
    assert g.next_reminder(31, d(2026, 12, 31), d(2026, 12, 31)) == d(2027, 1, 31)


def _series(values, start="2025-11-03"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def test_the_fall_from_the_high_and_each_step_told_once():
    fall, high = g.drop_from_high(_series([100, 110, 120, 102]))
    assert fall == pytest.approx(-0.15) and high == pd.Timestamp("2025-11-05")
    assert g.drop_from_high(None) is None
    assert g.drop_alert(-0.03, 0.0) == (None, 0.0)
    assert g.drop_alert(-0.12, 0.0) == (0.10, 0.10)          # 10%: told
    assert g.drop_alert(-0.15, 0.10) == (None, 0.10)         # still 10%: not again
    assert g.drop_alert(-0.22, 0.10) == (0.20, 0.20)         # 20%: told
    assert g.drop_alert(-0.08, 0.20) == (None, 0.20)         # partway back: remembered
    assert g.drop_alert(-0.04, 0.20) == (None, 0.0)          # back under 5%: starts over


def test_the_calm_message_carries_the_plans_record():
    record = {"worst_fall": -0.23, "worst_when": "May 2007-Feb 2009", "recovered": "Oct 2010",
              "recovery_months": 20}
    text = g.calm_text(-0.12, pd.Timestamp("2026-10-02"), "Balanced", record)
    assert "12% below their high of Oct 2" in text
    assert "Balanced fell 23% at worst" in text and "Oct 2010, 20 months later" in text
    assert "loss for good" in text
    assert "fell" not in g.calm_text(-0.12, pd.Timestamp("2026-10-02"), "Balanced", None).split(".")[1]


def test_a_levels_recovery_is_measured():
    idx = pd.date_range("2010-01-31", periods=8, freq="ME")
    r = pd.Series([0.0, -0.2, -0.1, 0.1, 0.2, 0.1, 0.0, 0.0], index=idx)
    s = g.stats(r)
    assert s["worst_fall"] < -0.25 and s["recovered"] and s["recovery_months"] >= 1


pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_home_shows_the_light_and_opens_the_plan(qapp, tmp_path):
    from tradelab.data.database import Database
    from tradelab.ui.panels.home import HomePanel
    db = Database(path=tmp_path / "h.db")
    home = HomePanel(db)
    opened = []
    home.on_open_plan = lambda: opened.append(1)
    home.show_plan([("warn", "CELI: off its target")], "Next purchase: Nov 10.")
    assert home.plan_light == "yellow" and not home.plan_line.isHidden()
    assert "CELI: off its target" in home.plan_line.text() and "Nov 10" in home.plan_line.text()
    home.plan_line.linkActivated.emit("plan")
    assert opened == [1]
    home.show_plan([])
    assert home.plan_line.isHidden()
    db.conn.close()


def test_a_fall_is_told_once_per_step(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from tradelab.ui.panels import guide as guide_panel
    told = []
    monkeypatch.setattr(guide_panel, "notify", lambda title, text: told.append(text) or True)
    s = QSettings(str(tmp_path / "g.ini"), QSettings.IniFormat)
    s.setValue(guide_panel.PROFILE_KEY, json.dumps({"level": 3}))
    panel = guide_panel.GuidePanel(None, settings=s)
    record = {"worst_fall": -0.23, "worst_when": "May 2007-Feb 2009", "recovered": "Oct 2010",
              "recovery_months": 20}
    panel.measured = [record] * len(g.LEVELS)
    high = pd.Timestamp("2026-10-02")
    panel._on_drop((-0.12, high), None)
    assert len(told) == 1 and "Balanced fell 23%" in told[0]
    panel._on_drop((-0.14, high), None)
    assert len(told) == 1                                   # same step: quiet
    panel._on_drop((-0.25, high), None)
    assert len(told) == 2
    panel._on_drop((-0.02, high), None)                    # recovered: starts over
    assert float(s.value(guide_panel.DROP_KEY)) == 0.0
    panel._on_drop(None, None)                             # no prices: nothing
    assert len(told) == 2
