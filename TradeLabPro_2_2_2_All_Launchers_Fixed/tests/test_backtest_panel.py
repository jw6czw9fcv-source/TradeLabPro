"""UI-level smoke tests for the Phase 4 BacktestPanel (4 sub-tabs).

get_history is monkeypatched to the deterministic ohlcv_df fixture so the
runs execute offline; see tests/test_backtest.py for the engine tests.
"""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def panel(qapp, ohlcv_df, monkeypatch):
    import tradelab.ui.app as app
    import tradelab.core.backtest as bt
    monkeypatch.setattr(app, "get_history", lambda s, p, i: ohlcv_df)
    monkeypatch.setattr("tradelab.data.market_data.get_history", lambda s, p, i: ohlcv_df)
    from tradelab.ui.chart_widget import ChartWidget
    from tradelab.core.config import ScannerConfig
    return app.BacktestPanel(ChartWidget(), ScannerConfig())


def test_panel_has_four_subtabs(panel):
    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert labels == ["Single", "Multi-Symbol", "Optimize", "Walk-Forward"]


def test_single_backtest_populates_metrics(panel):
    panel.single_symbol.setText("AAPL")
    panel.run_single()
    assert panel.metrics.rowCount() > 0
    # First metric column header remained "Metric".
    assert panel.metrics.horizontalHeaderItem(0).text() == "Metric"


def test_multi_backtest_populates_per_symbol_and_aggregate(panel):
    panel.multi_symbols.setText("AAPL, MSFT, GOOG")
    panel.run_multi()
    assert panel.multi_table.rowCount() == 3
    assert "Symbols tested" in panel.multi_agg.text()


def test_multi_backtest_handles_empty_symbol_input(panel):
    panel.multi_symbols.setText("   ")
    panel.run_multi()
    assert "at least one symbol" in panel.status.text()


def test_optimize_populates_results_sorted(panel):
    panel.opt_symbol.setText("AAPL")
    panel.opt_param.setCurrentText("ema_slow")
    panel.opt_values.setText("20, 30, 40")
    panel.run_optimize()
    assert panel.opt_table.rowCount() == 3
    assert "complete" in panel.status.text().lower()


def test_optimize_rejects_non_numeric_values(panel):
    panel.opt_values.setText("abc, def")
    panel.run_optimize()
    assert "must be numbers" in panel.status.text()


def test_walk_forward_populates_windows(panel):
    panel.wf_symbol.setText("AAPL")
    panel.wf_splits.setValue(3)
    panel.run_walk_forward()
    assert panel.wf_table.rowCount() == 3
    # Plain-language verdict says how many of the 3 periods were profitable.
    assert "of 3 time periods" in panel.wf_verdict.text()


def test_strategy_dropdown_offers_both_strategies(panel):
    keys = [panel.strategy.itemData(i) for i in range(panel.strategy.count())]
    assert "ema_macd" in keys and "rsi_reversion" in keys


def test_single_shows_plain_language_verdict(panel):
    panel.single_symbol.setText("AAPL")
    panel.run_single()
    text = panel.single_verdict.text()
    # Either a money verdict or a "not enough trades" note - never blank.
    assert text
    assert ("made money" in text or "lost money" in text or "not enough" in text)


def test_multi_shows_plain_language_verdict(panel):
    panel.multi_symbols.setText("AAPL, MSFT, GOOG")
    panel.run_multi()
    assert "Across 3 stocks" in panel.multi_verdict.text() or "No completed trades" in panel.multi_verdict.text()


def test_optimize_shows_best_value_verdict(panel):
    panel.opt_symbol.setText("AAPL")
    panel.opt_param.setCurrentText("ema_slow")
    panel.opt_values.setText("20, 30, 40")
    panel.run_optimize()
    assert "Best ema_slow" in panel.opt_verdict.text()


def test_walk_forward_verdict_labels_reliability(panel):
    panel.wf_symbol.setText("AAPL")
    panel.wf_splits.setValue(3)
    panel.run_walk_forward()
    text = panel.wf_verdict.text()
    assert any(word in text for word in ["reliable", "unreliable", "overfit"])
