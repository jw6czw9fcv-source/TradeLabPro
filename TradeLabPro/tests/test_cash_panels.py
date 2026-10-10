"""Cash on screen: entered on the Portfolio tab, counted on Analytics and Home,
with the date of the prices beside the totals."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tradelab.data.database import Database


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "panels.db")
    d.set_portfolio_positions("RRSP", [{"symbol": "NVDA", "shares": 10, "entry_price": 240.0}])
    yield d
    d.conn.close()


def _hist(n=120, start=100.0, end="2026-10-09"):
    idx = pd.date_range(end=end, periods=n, freq="B")
    close = start * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, n)))
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close,
                         "Volume": [0] * n}, index=idx)


def test_the_portfolio_tab_sets_and_removes_cash(qapp, db):
    import tradelab.ui.app as app
    panel = app.PortfolioPanel(db)
    assert panel.cash_portfolio.currentText() == "RRSP"          # offered from the positions
    panel.cash_currency.setCurrentText("cad")
    panel.cash_amount.setValue(2500.25)
    panel.set_cash()
    assert [(c["portfolio"], c["currency"], c["amount"]) for c in db.cash()] == [
        ("RRSP", "CAD", 2500.25)]
    assert panel.cash_table.rowCount() == 1
    assert panel.cash_table.item(0, 2).text() == "2,500.25"
    panel.cash_table.selectRow(0)
    panel.delete_cash()
    assert db.cash() == [] and panel.cash_table.rowCount() == 0


def test_the_portfolio_tab_wants_a_currency_code(qapp, db):
    import tradelab.ui.app as app
    panel = app.PortfolioPanel(db)
    panel.cash_currency.setCurrentText("dollars")
    panel.cash_amount.setValue(100)
    panel.set_cash()
    assert db.cash() == []
    assert "three-letter" in panel.status.text()


def test_analytics_shows_the_account_value_and_the_date_of_its_prices(qapp, db):
    import tradelab.ui.app as app
    db.set_cash("RRSP", "CAD", 2500.0)
    panel = app.PortfolioAnalyticsPanel(db)
    panel._positions = db.positions()
    panel._cash = db.cash()
    panel._bench_symbol = "SPY"
    panel._target = None
    panel._fx_pairs = {}
    panel._on_loaded({"NVDA": _hist(start=230.0), "SPY": _hist(start=600.0)})
    assert panel.metrics["value"].toolTip().startswith("Positions $")
    assert "cash $2,500" in panel.headline.text()
    assert "Prices as of Fri 09 Oct" in panel.conc.text()


def test_home_counts_the_cash_and_dates_its_prices(qapp, db):
    import tradelab.ui.app as app
    db.set_cash("RRSP", "CAD", 2500.0)
    panel = app.HomePanel(db)
    panel._positions = db.positions()
    panel._cash = db.cash()
    panel._target = None
    panel._bench = "SPY"
    panel._fx_pairs = {}
    panel._on_loaded({"NVDA": _hist(start=230.0), "SPY": _hist(start=600.0)}, {}, {}, {}, "")
    assert "of it in cash" in panel.headline.text()
    assert panel.metrics["value"].toolTip().startswith("Positions $")
    assert "prices as of Fri 09 Oct" in panel.status.text()
