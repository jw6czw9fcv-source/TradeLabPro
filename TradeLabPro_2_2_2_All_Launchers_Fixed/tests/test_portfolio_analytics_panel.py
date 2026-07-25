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


def test_analytics_panel_empty_portfolio(qapp):
    import tradelab.ui.app as app
    panel = app.PortfolioAnalyticsPanel(_FakeDB([]))
    panel.analyze()
    assert "No positions" in panel.headline.text()
    assert panel.holdings.rowCount() == 0
