"""The Guide: the questions, the levels with their returns and real records,
the level the answers point to, and making it the Plan tab's target mix."""
import json

import numpy as np
import pandas as pd
import pytest

from tradelab.core import guide as g


def _prices(seed, drift, vol, crash=0.0):
    """Fifteen years of month-ends with an optional crash in year 4."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-31", periods=180, freq="ME")
    r = rng.normal(drift, vol, 180)
    r[40:46] += crash / 6
    return pd.Series(100 * np.cumprod(1 + r), index=idx)


@pytest.fixture
def prices():
    out = {s: _prices(i, 0.007, 0.04, crash=-0.5) for i, s in enumerate(g.STOCK_PROXIES)}
    out[g.BOND_PROXY] = _prices(9, 0.002, 0.008)
    out[g.FX] = pd.Series(1.30, index=out[g.BOND_PROXY].index)
    return out


def test_guideline_returns_after_the_fee():
    assert g.expected_return(0, 0, 1) == pytest.approx(0.024 - 0.0025)
    assert g.expected_return(0, 1, 0) == pytest.approx(0.032 - 0.0025)
    stocks = 0.30 * 0.063 + 0.45 * 0.064 + 0.20 * 0.066 + 0.05 * 0.075
    assert g.expected_return(1, 0, 0) == pytest.approx(stocks - 0.0025)
    rates = [g.expected_return(*lv[1:]) for lv in g.LEVELS]
    assert rates == sorted(rates)          # more stocks, more expected


def test_future_value():
    assert g.future_value(1000, 0, 1, 0.05) == pytest.approx(1050)
    assert g.future_value(0, 100, 1, 0.0) == pytest.approx(1200)
    assert g.future_value(10_000, 100, 5, 0.04) > 10_000 * 1.04 ** 5 + 6000


def test_measured_records_get_worse_with_more_stocks(prices):
    m = g.measure(prices)
    assert [x["name"] for x in m] == [lv[0] for lv in g.LEVELS]
    falls = [x["worst_fall"] for x in m]
    assert falls == sorted(falls, reverse=True) and falls[-1] < -0.3
    assert m[0]["worst_fall"] > -0.05             # mostly cash and bonds
    assert m[-1]["worst_when"] and m[-1]["since"] == "2010"
    assert m[-1]["cagr"] > m[0]["cagr"] and m[-1]["cagr_10y"] is not None
    assert g.measure({}) is None
    assert g.measure({"XIU.TO": prices["XIU.TO"]}) is None
    no_fx = {k: v for k, v in prices.items() if k != g.FX}
    assert g.measure(no_fx) is None


def test_us_listed_funds_are_counted_in_cad():
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    rets = g.monthly_returns({"SPY": pd.Series([100, 100, 100], index=idx),
                              "XIU.TO": pd.Series([10, 10, 10], index=idx),
                              g.FX: pd.Series([1.30, 1.43, 1.43], index=idx)})
    assert rets["SPY"].iloc[0] == pytest.approx(0.10)     # the US dollar rose 10%
    assert rets["XIU.TO"].iloc[0] == 0


def test_the_projection_rate_follows_the_chosen_basis(prices):
    m = g.measure(prices)
    assert g.rate_for(5, 0, m) == m[5]["cagr"]
    assert g.rate_for(5, 1, m) == m[5]["cagr_10y"]
    assert g.rate_for(5, 2, m) == g.expected_return(1, 0, 0)
    assert g.rate_for(5, 0, None) == g.expected_return(1, 0, 0)   # no record yet


def test_the_level_follows_the_tighter_of_horizon_and_drop(prices):
    m = g.measure(prices)
    long_horizon, any_drop = 5, 5
    assert g.recommend(long_horizon, any_drop, m)["level"] == 5
    assert g.recommend(0, any_drop, m)["level"] == 0          # money needed soon
    rec = g.recommend(long_horizon, 3, m)                     # about 20%
    assert -m[rec["level"]]["worst_fall"] <= 0.20
    assert rec["level"] == 5 or -m[rec["level"] + 1]["worst_fall"] > 0.20
    assert "20%" in rec["why"]
    none = g.recommend(long_horizon, 0, m)                    # no drop at all
    assert none["level"] == 0 and "GIC" in none["note"]
    # Without records each answer stands for one level.
    assert g.recommend(5, 2, None)["level"] == 2


def test_first_steps_and_a_choice_above_the_answers(prices):
    m = g.measure(prices)
    steps = g.first_steps("No", "Yes", "Neither yet")
    assert len(steps) == 3
    assert g.first_steps("Yes", "No", "CELI and REER") == []
    assert g.check_choice(2, 3, m) == ""
    text = g.check_choice(5, 2, m)
    assert "above the level" in text and "your choice" in text.lower()


pytest.importorskip("PySide6")


def test_the_guide_tab_sets_the_plan(tmp_path, prices):
    from PySide6.QtWidgets import QApplication
    from tradelab.data.database import Database
    from tradelab.settings import app_settings
    from tradelab.ui.panels.guide import PROFILE_KEY, GuidePanel
    QApplication.instance() or QApplication([])
    settings = app_settings(); settings.remove(PROFILE_KEY)
    db = Database(path=tmp_path / "g.db")
    db.set_plan_target("REER Test", 50, 50, 0)
    changed = []
    panel = GuidePanel(db, settings=settings, on_plan_changed=lambda: changed.append(1))
    assert not panel.has_profile()
    GuidePanel._measured_cache = None
    panel.measured = g.measure(prices)          # as if downloaded
    panel.horizon.setCurrentIndex(5); panel.drop.setCurrentIndex(5)
    panel.lump.setValue(10_000)
    panel.show_levels()
    if panel._worker is not None:
        panel._worker.wait(1)
    assert panel.recommended == 5
    assert panel.table.item(5, 0).text().startswith("★")
    assert panel.table.item(5, 2).text().endswith("%")              # since the start
    assert panel.table.item(5, 5).text().startswith("$")
    assert panel.table.item(5, 6).text().endswith(")")
    real = panel.table.item(5, 5).text()
    panel.basis.setCurrentIndex(2)                                   # the guidelines
    assert panel.table.item(5, 5).text() != real
    panel.table.selectRow(3)
    panel.portfolio.setCurrentText("REER Test")
    panel.use_level()
    assert db.plan_targets()["REER Test"] == {"stocks": 60, "bonds": 40, "cash": 0}
    assert changed == [1]
    saved = json.loads(settings.value(PROFILE_KEY, "", type=str))
    assert saved["level"] == 3 and saved["answers"]["horizon"] == 5
    again = GuidePanel(db, settings=settings)
    assert again.has_profile() and "Balanced" in again.saved_line.text()
    assert again.horizon.currentIndex() == 5 and again.lump.value() == 10_000
    settings.remove(PROFILE_KEY)
    db.conn.close()
