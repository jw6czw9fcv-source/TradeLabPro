"""Headless (QT_QPA_PLATFORM=offscreen, set in conftest.py) smoke tests for
the Chart Engine UI layer. These don't check pixels, but they do check that
the widgets construct, accept data, and don't throw - which is exactly the
class of bug ("crashes on click", "chart never renders") that regression
testing is meant to catch before a release closes.
"""
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from tradelab.core.config import ScannerConfig
from tradelab.core.drawings import Drawing


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_chart_widget_constructs_empty(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    assert widget.symbol == ""
    assert widget.chart_type == "Candlestick"


def test_chart_widget_plots_data_without_raising(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    assert widget.symbol == "AAPL"
    assert len(widget.df_raw) == len(ohlcv_df)


def test_chart_widget_handles_empty_dataframe_gracefully(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("ZZZZ", pd.DataFrame(), ScannerConfig())
    assert widget.symbol == "ZZZZ"  # should not raise, just shows placeholder


@pytest.mark.parametrize("chart_type", ["Candlestick", "Heikin-Ashi", "Line", "Area"])
def test_all_chart_types_render_without_raising(qapp, ohlcv_df, chart_type):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    widget.chart_type = chart_type
    widget.replot()  # should not raise for any supported chart type


def test_drawing_added_programmatically_is_rendered_without_raising(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    widget.drawings.append(Drawing(kind="trendline", x1=0, y1=float(ohlcv_df["Close"].iloc[0]), x2=50, y2=float(ohlcv_df["Close"].iloc[50])))
    widget._plot_drawings()  # should not raise
    assert len(widget._drawing_items) == 1


def test_chart_workspace_constructs_with_default_chart(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace
    workspace = ChartWorkspace()
    assert workspace.current_chart() is not None
    assert len(workspace._panels) == 1


def test_chart_workspace_add_chart_creates_new_dock(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace
    workspace = ChartWorkspace()
    before = len(workspace._panels)
    workspace.add_chart("MSFT")
    assert len(workspace._panels) == before + 1


def test_chart_workspace_plot_delegates_to_current_chart(qapp, ohlcv_df):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace
    workspace = ChartWorkspace()
    workspace.plot("AAPL", ohlcv_df, ScannerConfig())
    assert workspace.current_chart().symbol == "AAPL"
