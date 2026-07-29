"""Headless smoke tests for the bar-by-bar Chart Replay panel."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _df(n=200):
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    close = np.linspace(50, 80, n)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(n, 1_000_000)}, index=dates)


def _panel(qapp):
    from tradelab.ui.app import ReplayPanel
    from tradelab.ui.chart_widget import ChartWorkspace
    from tradelab.core.config import ScannerConfig
    panel = ReplayPanel(ChartWorkspace(), ScannerConfig())
    # Capture what gets plotted instead of touching the real chart.
    panel._plotted = []
    panel.chart.plot = lambda sym, df, cfg: panel._plotted.append((sym, len(df)))
    return panel


def test_load_reveals_only_start_bars(qapp):
    panel = _panel(qapp)
    panel.start_bars.setValue(60)
    panel.set_data("AAPL", _df(200))
    assert panel.index == 60
    assert panel._plotted[-1] == ("AAPL", 60)     # only 60 bars shown, no look-ahead
    assert panel.slider.maximum() == 200


def test_step_forward_and_back_stays_in_bounds(qapp):
    panel = _panel(qapp)
    panel.start_bars.setValue(60)
    panel.set_data("AAPL", _df(100))
    panel.step(1)
    assert panel.index == 61 and panel._plotted[-1] == ("AAPL", 61)
    panel.step(-5)
    assert panel.index == 56
    for _ in range(100):
        panel.step(-1)
    assert panel.index == 2                        # never below 2 bars
    panel.to_end()
    assert panel.index == 100 and panel._plotted[-1] == ("AAPL", 100)


def test_advance_pauses_at_the_end(qapp):
    panel = _panel(qapp)
    panel.start_bars.setValue(99)
    panel.set_data("AAPL", _df(100))
    panel.play()
    assert panel._timer.isActive()
    panel._advance()          # 99 -> 100
    panel._advance()          # at end -> should stop
    assert panel.index == 100
    assert not panel._timer.isActive()
    assert panel.play_btn.text().startswith("▶")


def test_reset_returns_to_start_bar(qapp):
    panel = _panel(qapp)
    panel.start_bars.setValue(30)
    panel.set_data("AAPL", _df(100))
    panel.to_end()
    assert panel.index == 100
    panel.reset()
    assert panel.index == 30 and not panel._timer.isActive()


def test_slider_scrubs_and_pauses(qapp):
    panel = _panel(qapp)
    panel.set_data("AAPL", _df(120))
    panel.play()
    panel.slider.setValue(90)         # user scrubs
    assert panel.index == 90
    assert not panel._timer.isActive()
    assert panel._plotted[-1] == ("AAPL", 90)


def test_controls_disabled_until_loaded(qapp):
    panel = _panel(qapp)
    assert not panel.play_btn.isEnabled()
    panel.set_data("AAPL", _df(50))
    assert panel.play_btn.isEnabled()
