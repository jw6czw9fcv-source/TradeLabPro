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
    assert m[-1]["cagr"] > m[0]["cagr"]
    assert [w["cagr"] is not None for w in m[-1]["windows"]] == [True] * len(g.WINDOWS)
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
    for i in range(len(g.WINDOWS)):
        assert g.rate_for(5, i, m) == m[5]["windows"][i]["cagr"]
    assert g.rate_for(5, g.GUIDELINES_BASIS, m) == g.expected_return(1, 0, 0)
    assert g.rate_for(5, 0, None) == g.expected_return(1, 0, 0)   # no record yet


def test_a_shorter_period_leaves_an_older_crash_out(prices):
    """The crash is in year 4 of 15: the last 10 years do not have it."""
    m = g.measure(prices)[5]
    whole, ten, three, one = m["windows"]
    assert whole["worst_fall"] == m["worst_fall"] < -0.3
    assert ten["worst_fall"] > whole["worst_fall"]
    assert ten["worst_when"] != whole["worst_when"]
    assert three["worst_5y"] is None and one["worst_5y"] is None
    assert one["worst_12m"] == pytest.approx(one["cagr"])          # one year is one 12 months
    # The guidelines basis shows the whole record beside it.
    assert g.window_record(5, g.GUIDELINES_BASIS, g.measure(prices)) == whole


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
    assert panel.table.item(5, 4).text().startswith("$")
    assert panel.table.item(5, 5).text().endswith(")")
    whole_fall = panel.table.item(5, 5).text()
    real = panel.table.item(5, 4).text()
    panel.basis.setCurrentIndex(1)                                   # the last 10 years
    assert panel.table.item(5, 5).text() != whole_fall
    assert "10 years" in panel.table.horizontalHeaderItem(5).text()
    panel.basis.setCurrentIndex(g.GUIDELINES_BASIS)
    assert panel.table.item(5, 4).text() != real
    assert panel.table.item(5, 5).text() == whole_fall
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


def test_every_level_has_one_fund_candidates_and_the_blocks_cover_each_class():
    assert set(g.ONE_FUND) == set(range(len(g.LEVELS)))
    assert all(s.endswith(".TO") for syms in g.ONE_FUND.values() for s in syms)
    assert {b[1] for b in g.BLOCKS} == {"cash", "bonds", "stocks"}
    assert g.block_amounts(3, 300_000) == {"stocks": 180_000, "bonds": 120_000, "cash": 0}


def test_step_3_checks_the_funds_side_by_side(tmp_path, prices, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from tradelab.data.database import Database
    from tradelab.settings import app_settings
    from tradelab.ui.panels import guide as guide_panel
    QApplication.instance() or QApplication([])
    started = []

    class NoNetwork:
        def __init__(self, symbols):
            started.append(list(symbols))
            self.done = type("S", (), {"connect": lambda *_a: None})()

        def start(self):
            pass

        def isRunning(self):
            return False

    monkeypatch.setattr(guide_panel, "_FundsWorker", NoNetwork)
    monkeypatch.setattr(guide_panel.GuidePanel, "_facts_cache", {})
    settings = app_settings(); settings.remove(guide_panel.PROFILE_KEY)
    db = Database(path=tmp_path / "f.db")
    panel = guide_panel.GuidePanel(db, settings=settings)
    panel.measured = g.measure(prices)
    panel.horizon.setCurrentIndex(5); panel.drop.setCurrentIndex(3)
    panel.lump.setValue(300_000)
    panel.show_levels()
    panel.show_funds()
    level = panel.recommended
    assert started[-1] == g.ONE_FUND[level]
    assert g.LEVELS[level][0] in panel.funds_intro.text() and "$" in panel.funds_intro.text()

    def info(name, mer):
        return {"prices": _prices(3, 0.006, 0.03), "yield": 0.02,
                "meta": {"quote_type": "ETF", "name": name, "expense_ratio": mer}}
    syms = g.ONE_FUND[level]
    panel._on_funds({syms[0]: info("A", 0.0025), syms[1]: info("B", 0.0018)}, [])
    panel.fund_sort.setCurrentText("Lowest fees")
    assert panel.fund_table.rowCount() == 2
    assert panel.fund_table.item(0, 0).text() == syms[1]            # the cheaper first
    assert "(Yahoo)" in panel.fund_table.item(0, 2).text()

    panel.fund_set.setCurrentIndex(5)                               # Canadian dividend stocks
    assert started[-1] == g.BLOCKS[4][2] and "dividends" in panel.fund_note.text()
    panel.fund_extra.setText("vfv.to")
    panel.check_funds()
    assert started[-1][-1] == "VFV.TO"
    settings.remove(guide_panel.PROFILE_KEY)
    db.conn.close()
