"""UI smoke test for the Analytics tab (PortfolioAnalyticsPanel).

Histories are fed straight into the render path (no network); a fake DB supplies
positions, so the tables populate deterministically offline.
"""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeDB:
    def __init__(self, positions):
        self._p = positions

    def positions(self):
        return list(self._p)


def _hist(seed, n=200, start_price=100.0):
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    close = start_price * np.exp(np.cumsum(rng.normal(0.0004, 0.011, size=n)))
    return pd.DataFrame({"Close": close, "Open": close, "High": close,
                        "Low": close, "Volume": [0] * n}, index=idx)


def test_analytics_panel_populates(qapp):
    import tradelab.ui.app as app
    db = _FakeDB([
        {"symbol": "AAPL", "shares": 100, "entry_price": 90.0},
        {"symbol": "MSFT", "shares": 40, "entry_price": 200.0},
    ])
    panel = app.PortfolioAnalyticsPanel(db)

    panel._positions = db.positions()
    panel._bench_symbol = "SPY"
    panel._target = None          # native (mixed) currency mode
    panel._fx_pairs = {}
    history = {"AAPL": _hist(1, start_price=100), "MSFT": _hist(2, start_price=220),
               "SPY": _hist(3, start_price=400)}
    panel._on_loaded(history)

    assert panel.holdings.rowCount() == 2
    assert panel.metrics["beta"].text() != "—"
    assert panel.metrics["value"].text().startswith("$")
    assert "%" in panel.metrics["dd"].text()            # max drawdown shown
    # 2 priced holdings -> a 2x2 correlation grid.
    assert panel.corr.rowCount() == 2 and panel.corr.columnCount() == 2


def test_analytics_panel_refuses_synthetic_data(qapp):
    # A failed download falls back to synthetic data elsewhere in the app, but
    # the real-money Analytics view must show "no data", never fabricated prices.
    import tradelab.ui.app as app
    from tradelab.data.market_data import synthetic_ohlcv
    db = _FakeDB([{"symbol": "AAPL", "shares": 100, "entry_price": 90.0},
                  {"symbol": "FAKE", "shares": 10, "entry_price": 50.0}])
    panel = app.PortfolioAnalyticsPanel(db)
    panel._positions = db.positions()
    panel._bench_symbol = "SPY"
    panel._target = None
    panel._fx_pairs = {}
    history = {"AAPL": _hist(1, start_price=100),
               "FAKE": synthetic_ohlcv("FAKE"),          # tagged synthetic
               "SPY": _hist(3, start_price=400)}
    panel._on_loaded(history)

    by = {panel.holdings.item(r, 0).text(): r for r in range(panel.holdings.rowCount())}
    assert panel.holdings.item(by["FAKE"], 4).text() == "—"     # Last: no data, not fake
    assert "FAKE" in panel.status.text()                          # named in the note


def test_analytics_panel_empty_portfolio(qapp):
    import tradelab.ui.app as app
    panel = app.PortfolioAnalyticsPanel(_FakeDB([]))
    panel.analyze()
    assert "No positions" in panel.headline.text()
    assert panel.holdings.rowCount() == 0


# --- look-through -----------------------------------------------------------

def test_analytics_renders_look_through(qapp):
    import tradelab.ui.app as app
    from tradelab.core import portfolio_analytics as pa
    p = app.PortfolioAnalyticsPanel(_FakeDB([]))
    p._lt_currency = "CAD"
    rows = [{"symbol": "XDIV.TO", "market_value": 10000.0},
            {"symbol": "RY.TO", "market_value": 8000.0}]
    comps = {"XDIV.TO": {"top_holdings": {"RY.TO": 0.10, "TD.TO": 0.09},
                         "sectors": {"Financials": 0.6}},
             "RY.TO": {"top_holdings": {}, "sectors": {}}}
    p._lt_rows = rows
    p._on_compositions(comps, {"RY.TO": "Financials"}, "")

    assert p.lookthrough.item(0, 0).text() == "RY.TO"      # biggest exposure first
    assert p.lookthrough.item(0, 1).text() == "$9,000"     # 8000 direct + 1000 via
    assert p.lookthrough.item(0, 3).text() == "$8,000"     # held directly
    assert "XDIV.TO" in p.lookthrough.item(0, 4).text()    # and inside this fund
    line = p.lt_line.text()
    assert "RY.TO" in line and "largest company exposure" in line
    assert "floor" in line                                 # the unreported remainder
    assert "Financials" in p.sector_line.text()


def test_analytics_look_through_reports_a_fetch_failure(qapp):
    import tradelab.ui.app as app
    p = app.PortfolioAnalyticsPanel(_FakeDB([]))
    p._on_compositions(None, None, "network down")
    assert "network down" in p.lt_line.text()


def test_analytics_look_through_names_unreadable_funds(qapp):
    import tradelab.ui.app as app
    p = app.PortfolioAnalyticsPanel(_FakeDB([]))
    p._lt_currency = "CAD"
    p._lt_rows = [{"symbol": "XDIV.TO", "market_value": 1000.0}]
    p._on_compositions({}, {}, "")
    assert "No holdings data for XDIV.TO" in p.lt_line.text()
