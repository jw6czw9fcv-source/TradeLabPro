"""UI smoke tests for the Dividends tab (DividendsPanel).

Histories and dividend series are fed straight into the render path (no network),
with a fake DB supplying positions, so everything is deterministic offline.
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


def _hist(price, n=260):
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="B")
    close = np.linspace(price * 0.9, price, n)
    return pd.DataFrame({"Close": close, "Open": close, "High": close,
                        "Low": close, "Volume": [0] * n}, index=idx)


def _monthly_divs(amount, n=14):
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=10)
    idx = pd.DatetimeIndex([end - pd.DateOffset(months=i) for i in range(n)][::-1])
    return pd.Series([amount] * n, index=idx)


def test_dividends_panel_populates(qapp):
    import tradelab.ui.app as app
    db = _FakeDB([{"symbol": "XDIV.TO", "shares": 300, "entry_price": 43.26},
                  {"symbol": "KTOS", "shares": 1, "entry_price": 48.54}])
    panel = app.DividendsPanel(db)
    panel._positions = db.positions()
    panel._target = "CAD"
    panel._fx_pairs = {"USD": "USDCAD=X"}

    history = {"XDIV.TO": _hist(46.42), "KTOS": _hist(47.35),
               "USDCAD=X": _hist(1.40)}
    divs = {"XDIV.TO": _monthly_divs(0.12), "KTOS": pd.Series(dtype=float)}
    panel._on_loaded(history, divs, "")

    assert panel.table.rowCount() == 2
    rows = {panel.table.item(r, 0).text(): r for r in range(panel.table.rowCount())}
    # The payer reports income and a frequency; the non-payer is blank, not fake.
    assert panel.table.item(rows["XDIV.TO"], 3).text() == "Monthly"
    assert panel.table.item(rows["XDIV.TO"], 5).text().startswith("$")
    assert panel.table.item(rows["KTOS"], 5).text() == "—"
    assert "KTOS" in panel.status.text()             # named as a non-payer
    # Headline tiles and the 12-month calendar fill in.
    assert panel.metrics["annual"].text().startswith("$")
    assert "CAD" in panel.metrics["annual"].text()
    assert panel.calendar.rowCount() == 12


def test_dividends_panel_empty_portfolio(qapp):
    import tradelab.ui.app as app
    panel = app.DividendsPanel(_FakeDB([]))
    panel.analyze()
    assert "No positions" in panel.headline.text()
    assert panel.table.rowCount() == 0


def test_dividends_panel_refuses_synthetic_prices(qapp):
    # Same rule as Analytics: a failed price download must not produce a
    # fabricated yield.
    import tradelab.ui.app as app
    from tradelab.data.market_data import synthetic_ohlcv
    db = _FakeDB([{"symbol": "FAKE", "shares": 100, "entry_price": 10.0}])
    panel = app.DividendsPanel(db)
    panel._positions = db.positions()
    panel._target = None
    panel._fx_pairs = {}
    panel._on_loaded({"FAKE": synthetic_ohlcv("FAKE")},
                     {"FAKE": _monthly_divs(0.05)}, "")
    # Income still known (dividends are real), but no price -> no yield.
    assert panel.table.item(0, 6).text() == "—"


def test_dividends_panel_reports_fetch_error(qapp):
    import tradelab.ui.app as app
    panel = app.DividendsPanel(_FakeDB([{"symbol": "A", "shares": 1, "entry_price": 1}]))
    panel._on_loaded(None, None, "network down")
    assert "network down" in panel.status.text()
