"""UI smoke test for the Seasonality tab (SeasonalityPanel).

Data is fed straight into the render path (no network), so the tables populate
deterministically offline.
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


def _multiyear_frame():
    # ~4 years of daily data with an upward drift so seasonality has real numbers.
    idx = pd.date_range("2020-01-01", periods=4 * 365, freq="D")
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, size=len(idx))))
    return pd.DataFrame({"Close": close, "Open": close, "High": close,
                        "Low": close, "Volume": [0] * len(idx)}, index=idx)


def test_seasonality_panel_populates_all_tables(qapp):
    import tradelab.ui.app as app
    panel = app.SeasonalityPanel()

    panel._on_loaded("SPY", _multiyear_frame(), "")

    assert panel.month_table.rowCount() == 12          # Jan..Dec always present
    assert panel.dow_table.rowCount() == 5             # Mon..Fri
    assert panel.year_table.rowCount() >= 4            # ~4 calendar years
    assert "SPY" in panel.headline.text()
    # Every month has a measurable average with ~4 years of history.
    assert all(panel.month_table.item(r, 1).text() != "—" for r in range(12))


def test_seasonality_panel_handles_bad_symbol_gracefully(qapp):
    import tradelab.ui.app as app
    panel = app.SeasonalityPanel()
    panel._on_loaded("ZZZZ", None, "no data")
    assert "Could not load" in panel.status.text()
    assert panel.month_table.rowCount() == 0
