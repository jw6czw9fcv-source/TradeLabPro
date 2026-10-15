"""The account value recorded day by day, and net worth across everything
TradeLab follows."""
import pytest

from tradelab.core.home import net_worth, recorded_curve, snapshot_of
from tradelab.core.retirement import Account, Fund, Snapshot
from tradelab.data.database import Database


def _analytics(**over):
    a = {"total_value": 27_000.0, "cash": [{"currency": "CAD"}], "cash_value": 3_000.0,
         "account_value": 30_000.0, "prices_as_of": "2026-10-09", "no_data": [],
         "fx_missing": [], "currency": "CAD"}
    a.update(over)
    return a


def test_a_fully_priced_book_is_recorded_under_its_price_date():
    snap = snapshot_of(_analytics())
    assert snap == {"day": "2026-10-09", "currency": "CAD", "value": 30_000.0,
                    "positions": 27_000.0, "cash": 3_000.0}


@pytest.mark.parametrize("over", [{"no_data": ["XYZ"]}, {"fx_missing": ["USD"]},
                                  {"currency": None}, {"total_value": 0.0},
                                  {"prices_as_of": None}])
def test_a_book_that_would_mislead_is_not_recorded(over):
    assert snapshot_of(_analytics(**over)) is None


def test_the_database_keeps_one_value_per_day_and_currency(tmp_path):
    db = Database(path=tmp_path / "v.db")
    db.record_value(snapshot_of(_analytics()))
    db.record_value(snapshot_of(_analytics(account_value=30_500.0)))        # later that day
    db.record_value(snapshot_of(_analytics(prices_as_of="2026-10-10", account_value=31_000.0)))
    db.record_value({"day": "2026-10-10", "currency": "USD", "value": 22_000.0})
    assert [(r["day"], r["value"]) for r in db.value_history("CAD")] == [
        ("2026-10-09", 30_500.0), ("2026-10-10", 31_000.0)]
    assert len(db.value_history()) == 3
    db.conn.close()


def test_the_recorded_curve_needs_two_days_and_counts_deposits_as_moves():
    rows = [{"day": "2026-10-09", "currency": "CAD", "value": 30_000.0}]
    assert recorded_curve(rows, "CAD") is None
    rows.append({"day": "2026-10-10", "currency": "CAD", "value": 31_500.0})
    rows.append({"day": "2026-10-10", "currency": "USD", "value": 99.0})
    curve = recorded_curve(rows, "CAD")
    assert list(curve["series"]) == [30_000.0, 31_500.0]
    assert curve["change"] == 1_500.0 and curve["change_pct"] == pytest.approx(5.0)
    assert "over 2 recorded days" in curve["text"]


def _plan(name, amount, currency="CAD"):
    fund = Fund(name="Fund", snapshots=[Snapshot(date="2026-09-30", value=amount)])
    return Account(name=name, currency=currency, funds=[fund])


def test_net_worth_adds_the_retirement_plans_in_the_same_currency():
    worth = net_worth(30_000.0, "CAD", [_plan("Canada Life", 97_000.0),
                                         _plan("US 401k", 5_000.0, "USD"),
                                         _plan("Empty", 0.0)])
    assert worth["total"] == 127_000.0
    assert [p["name"] for p in worth["parts"]] == ["Portfolios", "Canada Life"]
    assert worth["parts"][1]["as_of"] == "2026-09-30"
    assert [p["name"] for p in worth["apart"]] == ["US 401k"]


def test_net_worth_without_anything_priced_is_none():
    assert net_worth(None, "CAD", [])["total"] is None


# --- on screen -----------------------------------------------------------------------

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_home_records_the_value_and_shows_net_worth_and_history(qapp, tmp_path):
    import json
    from tradelab.ui.app import HomePanel
    db = Database(path=tmp_path / "h.db")
    db.record_value({"day": "2026-10-08", "currency": "CAD", "value": 29_000.0})
    (tmp_path / "retirement.json").write_text(json.dumps({"accounts": [
        {"name": "Canada Life", "currency": "CAD",
         "funds": [{"name": "F", "snapshots": [{"date": "2026-09-30", "value": 97000}]}]}]}))
    panel = HomePanel(db)
    panel.retirement_path = tmp_path / "retirement.json"
    panel._target = "CAD"
    panel._render({"currency": "CAD", "text": "x", "has_positions": True,
                   "analytics": _analytics(), "ytd": None, "income": {}})
    assert [r["day"] for r in db.value_history("CAD")] == ["2026-10-08", "2026-10-09"]
    assert panel.metrics["worth"].text() == "$127,000 CAD"
    assert "Canada Life: $97,000 CAD" in panel.metrics["worth"].toolTip()
    panel.chart_mode.setCurrentIndex(1)
    assert "Recorded since 08 Oct 2026" in panel.ytd_chart.readout.text()
    db.conn.close()


def test_retirement_sim_shows_what_is_tracked_beside_the_plan(qapp, tmp_path):
    import json
    from tradelab.ui.app import RetirementSimPanel
    db = Database(path=tmp_path / "s.db")
    db.record_value({"day": "2026-10-09", "currency": "CAD", "value": 30_000.0})
    path = tmp_path / "retirement.json"
    path.write_text(json.dumps({"accounts": [
        {"name": "Canada Life", "currency": "CAD",
         "funds": [{"name": "F", "snapshots": [{"date": "2026-09-30", "value": 97000}]}]}]}))
    panel = RetirementSimPanel(db)
    panel.retirement_path = path
    panel.show_tracked()
    text = panel.tracked_line.text()
    assert "portfolios $30,000 (2026-10-09)" in text and "Canada Life $97,000" in text
    assert "= $127,000" in text
    db.conn.close()
