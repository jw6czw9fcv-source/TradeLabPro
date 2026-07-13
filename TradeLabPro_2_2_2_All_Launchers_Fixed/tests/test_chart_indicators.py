"""Tests for the configurable chart indicator system (chart overlays with
tunable periods + the ChartIndicatorsDialog)."""
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


def _df(n=300):
    rng = np.random.default_rng(2)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n)))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n)})


def test_default_chart_has_two_ema_overlays(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    w = PGChartWidget()
    inds = [(o["indicator"], o["period"]) for o in w._overlays]
    assert ("EMA", w.cfg.ema_fast) in inds
    assert ("EMA", w.cfg.ema_slow) in inds


def test_custom_period_overlays_render_each_as_a_line(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.config import ScannerConfig
    w = PGChartWidget()
    w._overlays = [{"indicator": "EMA", "period": 9}, {"indicator": "EMA", "period": 21},
                   {"indicator": "SMA", "period": 200}]
    w.plot("TEST", _df(), ScannerConfig())
    assert set(w._overlay_curves.keys()) == {"EMA 9", "EMA 21", "SMA 200"}


def test_bollinger_overlay_draws_three_lines(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.config import ScannerConfig
    w = PGChartWidget()
    w._overlays = [{"indicator": "Bollinger", "period": 20}]
    w.plot("TEST", _df(), ScannerConfig())
    assert set(w._overlay_curves.keys()) == {"BB Upper 20", "BB Mid 20", "BB Lower 20"}


def test_indicator_dialog_round_trips_overlays_signals_and_panes(qapp):
    from tradelab.ui.widgets.pg_chart_widget import ChartIndicatorsDialog
    overlays = [{"indicator": "EMA", "period": 12}, {"indicator": "VWAP", "period": None}]
    dlg = ChartIndicatorsDialog(overlays, show_signals=False,
                                sub_panels={"Volume": True, "MACD": False, "RSI": True})
    assert [(o["indicator"], o["period"]) for o in dlg.overlays()] == [("EMA", 12), ("VWAP", None)]
    assert dlg.show_signals() is False
    assert dlg.sub_panels() == {"Volume": True, "MACD": False, "RSI": True}


def test_indicator_dialog_add_and_remove_overlay(qapp):
    from tradelab.ui.widgets.pg_chart_widget import ChartIndicatorsDialog
    dlg = ChartIndicatorsDialog([{"indicator": "EMA", "period": 9}], True, {"Volume": True, "MACD": True, "RSI": True})
    dlg._add_row("SMA", 50)
    assert len(dlg.overlays()) == 2
    dlg._remove_row(dlg._rows[0]["row"])
    remaining = dlg.overlays()
    assert len(remaining) == 1
    assert remaining[0]["indicator"] == "SMA" and remaining[0]["period"] == 50


def test_no_period_indicator_reports_none_period(qapp):
    from tradelab.ui.widgets.pg_chart_widget import ChartIndicatorsDialog
    dlg = ChartIndicatorsDialog([{"indicator": "VWAP", "period": None}], True, {})
    assert dlg.overlays()[0]["period"] is None


def test_price_legend_shows_one_entry_per_overlay_line(qapp):
    from PySide6.QtWidgets import QPushButton
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.config import ScannerConfig
    w = PGChartWidget()
    w._overlays = [{"indicator": "EMA", "period": 9}, {"indicator": "SMA", "period": 50}]
    w.plot("TEST", _df(), ScannerConfig())
    legend = w._legends.get(w.price_plot)
    assert legend is not None
    texts = [b.text() for b in legend.findChildren(QPushButton)]
    assert "EMA 9" in texts and "SMA 50" in texts


def test_clicking_a_legend_entry_opens_the_indicators_dialog(qapp, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from tradelab.ui.widgets import pg_chart_widget as mod
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.config import ScannerConfig
    opened = {"n": 0}
    monkeypatch.setattr(PGChartWidget, "open_indicators_dialog", lambda self: opened.__setitem__("n", opened["n"] + 1))
    w = PGChartWidget()
    w._overlays = [{"indicator": "EMA", "period": 9}]
    w.plot("TEST", _df(), ScannerConfig())
    legend = w._legends[w.price_plot]
    legend.findChildren(QPushButton)[0].click()
    assert opened["n"] == 1


def test_empty_chart_clears_the_legend(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.config import ScannerConfig
    import pandas as pd
    w = PGChartWidget()
    w.plot("TEST", _df(), ScannerConfig())
    assert w._legends.get(w.price_plot) is not None
    w.plot("ZZZZ", pd.DataFrame(), ScannerConfig())  # empty -> placeholder
    assert w._legends.get(w.price_plot) is None


def test_open_indicators_dialog_applies_changes(qapp, monkeypatch):
    from tradelab.ui.widgets import pg_chart_widget as mod
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    w = PGChartWidget()

    # Simulate the user setting overlays + turning MACD pane off + tuning
    # RSI/MACD periods, then OK.
    class _FakeDialog:
        def __init__(self, *a, **k): pass
        def exec(self): return True
        def overlays(self): return [{"indicator": "SMA", "period": 100}]
        def show_signals(self): return False
        def sub_panels(self): return {"Volume": True, "MACD": False, "RSI": True}
        def rsi_period(self): return 7
        def macd_params(self): return (5, 13, 4)
    monkeypatch.setattr(mod, "ChartIndicatorsDialog", _FakeDialog)

    w.open_indicators_dialog()
    assert w._overlays == [{"indicator": "SMA", "period": 100}]
    assert w._show_signals is False
    assert w._sub_panel_flags["MACD"] is False
    assert w._rsi_period == 7
    assert (w._macd_fast, w._macd_slow, w._macd_signal) == (5, 13, 4)


def test_rsi_and_macd_periods_are_configurable_and_shown_in_legend(qapp):
    from PySide6.QtWidgets import QPushButton
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.config import ScannerConfig
    w = PGChartWidget()
    w._rsi_period = 7
    w._macd_fast, w._macd_slow, w._macd_signal = 5, 13, 4
    w.plot("TEST", _df(), ScannerConfig())
    rsi_legend = [b.text() for b in w._legends[w.rsi_plot].findChildren(QPushButton)]
    macd_legend = [b.text() for b in w._legends[w.macd_plot].findChildren(QPushButton)]
    assert "RSI 7" in rsi_legend
    assert "MACD 5/13/4" in macd_legend


def test_chart_indicators_dialog_returns_subpane_periods(qapp):
    from tradelab.ui.widgets.pg_chart_widget import ChartIndicatorsDialog
    dlg = ChartIndicatorsDialog([], True, {"Volume": True, "MACD": True, "RSI": True},
                                rsi_period=21, macd_params=(8, 21, 5))
    assert dlg.rsi_period() == 21
    assert dlg.macd_params() == (8, 21, 5)
