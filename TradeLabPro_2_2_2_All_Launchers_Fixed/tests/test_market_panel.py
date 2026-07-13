"""UI-level smoke tests for the Phase 3 MarketPanel.

get_history is monkeypatched so the dashboard refresh runs deterministically
offline - see tests/test_market.py for the underlying logic tests.
"""
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _rising(n=250, start=100.0):
    return pd.DataFrame({
        "Open": [start + i for i in range(n)],
        "High": [start + i + 1 for i in range(n)],
        "Low": [start + i - 1 for i in range(n)],
        "Close": [start + i for i in range(n)],
        "Volume": [1_000_000] * n,
    })


def test_market_panel_constructs_with_regime_and_sector_rows(qapp):
    import tradelab.ui.app as app
    from tradelab.core.market import SECTOR_ETFS

    panel = app.MarketPanel()
    assert panel.table.rowCount() == len(panel.rows)
    assert panel.sector_table.rowCount() == len(SECTOR_ETFS)


def test_refresh_market_populates_read_and_breadth(qapp, monkeypatch):
    import tradelab.ui.app as app

    # Rising series for everything except a low VIX -> should read Favorable.
    def fake_history(symbol, period, interval):
        if symbol == "^VIX":
            return pd.DataFrame({"Close": [14.0] * 250, "Open": [14.0]*250, "High": [14.0]*250, "Low": [14.0]*250, "Volume": [0]*250})
        return _rising()

    monkeypatch.setattr(app, "get_history", fake_history)
    panel = app.MarketPanel()
    panel.refresh_market()

    assert "Favorable" in panel.read_headline.text()
    assert "/100" in panel.read_headline.text()
    assert panel.read_reasons.text()  # reasons populated
    # Sector table "vs 50-day" column filled in (rising series -> Above).
    assert panel.sector_table.item(0, 3).text() == "Above"
    assert "sectors up today" in panel.status.text()


def test_refresh_market_survives_a_failing_symbol(qapp, monkeypatch):
    import tradelab.ui.app as app

    def flaky_history(symbol, period, interval):
        if symbol == "XLK":
            raise RuntimeError("network blip")
        return _rising()

    monkeypatch.setattr(app, "get_history", flaky_history)
    panel = app.MarketPanel()
    panel.refresh_market()  # must not raise

    # The failing sector shows ERR but the panel still produced a read.
    assert panel.sector_table.item(0, 2).text() == "ERR"
    assert "/100" in panel.read_headline.text()
