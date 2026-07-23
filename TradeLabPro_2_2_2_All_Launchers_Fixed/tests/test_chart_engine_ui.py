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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tradelab.core.config import ScannerConfig
from tradelab.core.drawings import Drawing


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _offline_quote_meta(monkeypatch):
    monkeypatch.setattr("tradelab.ui.widgets.pg_chart_widget.get_quote_meta",
                        lambda s: {"name": s, "market_cap": 0.0, "sector": "X", "industry": "Y"})


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


def test_price_pane_y_axis_fits_real_data_after_empty_placeholder(qapp, ohlcv_df):
    """show_empty_placeholder() (shown once at construction) pins the Y-axis
    to a fixed [-1, 1] range. Regression test for a real bug where every
    chart's price pane stayed locked to that placeholder range forever -
    candles rendered, but squeezed into a sliver at the top of the pane
    instead of filling it. Y range is now set explicitly in replot() (like
    X already was) rather than left to pyqtgraph's auto-range, which only
    recomputes on the next paint and would leave a stale range on a chart
    replotted while its dock tab is hidden.
    """
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())

    assert widget._empty_text_item is None  # placeholder must be removed once real data loads

    y_lo, y_hi = widget.price_plot.getViewBox().viewRange()[1]
    visible = ohlcv_df.iloc[max(0, len(ohlcv_df) - 100):]
    close_lo, close_hi = float(visible["Low"].min()), float(visible["High"].max())
    # The view must actually fit the visible window's price range, not stay
    # pinned to the placeholder's [-1, 1].
    assert y_lo < close_lo
    assert y_hi > close_hi
    assert (y_hi - y_lo) < (close_hi - close_lo) * 3  # fits snugly, not diluted by a stray item


def test_price_pane_crosshair_and_signals_survive_construction(qapp):
    """show_empty_placeholder() (called once at the end of __init__) does
    price_plot.clear(), which - before this fix - silently orphaned every
    item added to price_plot before that point: the price pane's own
    crosshair InfiniteLines (_hline_price and _crosshair_lines[0]) and the
    BUY/SELL signal_scatter, none of which were ever re-added. The result
    was a crosshair that visually only worked in the volume/MACD/RSI
    sub-panes, and BUY/SELL markers that silently never appeared, no
    matter how much real signal data existed.
    """
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    import pyqtgraph as pg

    widget = PGChartWidget()
    item_types = [type(it) for it in widget.price_plot.getPlotItem().items]
    assert widget.signal_scatter.__class__ in item_types
    assert item_types.count(pg.InfiniteLine) == 2  # price pane's own vline + hline_price


def test_buy_sell_signals_computed_and_rendered(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())

    # signal_scatter must still be attached to the plot (see the orphaning
    # regression test above) and, for 260 bars of synthetic trending data,
    # must actually have found at least one EMA-crossover signal.
    assert widget.signal_scatter in widget.price_plot.getPlotItem().items
    assert len(widget.signal_scatter.data) > 0
    symbols = {rec["symbol"] for rec in widget.signal_scatter.data}
    assert symbols <= {"arrow_up", "arrow_down"}


def test_crosshair_readout_shows_full_ohlcv_at_hovered_bar(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from PySide6.QtCore import QPointF

    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    widget.resize(800, 600)
    widget.show()
    qapp.processEvents()

    vb = widget.price_plot.getViewBox()
    (x0, x1), (y0, y1) = vb.viewRange()
    mid_view = QPointF((x0 + x1) / 2, (y0 + y1) / 2)
    widget._on_mouse_moved(vb.mapViewToScene(mid_view))

    text = widget.crosshair_info.text()
    assert "AAPL" in text
    for token in ("O ", "H ", "L ", "C ", "Vol "):
        assert token in text


def test_crosshair_tracks_mouse_over_volume_macd_rsi_panes(qapp, ohlcv_df):
    """Each PlotWidget owns its own QGraphicsScene. Regression test for a
    real bug where only price_plot's sigMouseMoved was connected, so the
    crosshair silently froze - never updating the vertical lines or the
    OHLCV readout - the instant the mouse moved into the volume/MACD/RSI
    panes below the main chart.
    """
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from PySide6.QtCore import QPointF

    widget = PGChartWidget()
    widget._toggle_subpanel("MACD", True)
    widget._toggle_subpanel("RSI", True)
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    widget.resize(800, 600)
    widget.show()
    qapp.processEvents()

    for plot in (widget.volume_plot, widget.macd_plot, widget.rsi_plot):
        vb = plot.getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        mid_view = QPointF((x0 + x1) / 2, (y0 + y1) / 2)
        widget._on_mouse_moved(vb.mapViewToScene(mid_view), plot)

        assert "AAPL" in widget.crosshair_info.text()
        positions = {round(line.getXPos(), 3) for line in widget._crosshair_lines}
        assert len(positions) == 1  # all four panes' vertical lines stay in sync


def test_macd_and_rsi_visible_by_default(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget

    widget = PGChartWidget()
    widget.resize(800, 600)
    widget.show()
    qapp.processEvents()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    qapp.processEvents()

    assert widget._sub_panel_flags["MACD"] is True
    assert widget._sub_panel_flags["RSI"] is True
    assert widget.macd_plot.isVisible()
    assert widget.rsi_plot.isVisible()


def test_macd_and_rsi_crosshair_line_survives_a_real_replot(qapp, ohlcv_df):
    """_plot_macd/_plot_rsi call .clear() on their own pane on every single
    replot (symbol change, overlay toggle, anything) - regression test for
    a bug where that wiped each pane's own crosshair InfiniteLine (added
    once at construction) without ever re-adding it. setPos() on the
    orphaned line object still "succeeded" silently, which is why this
    slipped past a test that only checked positions and not scene
    attachment - the crosshair simply never rendered on MACD/RSI after the
    first replot, no matter how correctly _on_mouse_moved computed the
    position.
    """
    import pyqtgraph as pg
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget

    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())  # first replot - the bug only appears after this

    for plot in (widget.macd_plot, widget.rsi_plot):
        items = plot.getPlotItem().items
        assert any(isinstance(it, pg.InfiniteLine) for it in items), (
            f"{plot} lost its crosshair line after replot()"
        )


@pytest.mark.parametrize("chart_type", ["Candlestick", "Heikin-Ashi", "Line", "Area"])
def test_all_chart_types_render_without_raising(qapp, ohlcv_df, chart_type):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    widget.chart_type = chart_type
    widget.replot()  # should not raise for any supported chart type


def test_drawing_added_programmatically_is_rendered_without_raising(qapp, ohlcv_df, tmp_path):
    # Isolated DB: plot() loads any saved drawings for the symbol, and the real
    # data DB can hold genuine AAPL annotations a user drew in the live app.
    widget = _isolated_chart(tmp_path)
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


# --- X axis dates (regression: the axis labelled bar indices, not dates) ---

def test_bar_date_axis_labels_indices_with_real_dates(qapp, ohlcv_df):
    """Candles are drawn at x = bar index so weekends leave no gap; the axis
    must translate those indices back into the bars' own timestamps."""
    from tradelab.ui.widgets.pg_chart_widget import BarDateAxis
    axis = BarDateAxis(orientation="bottom")
    axis.set_index(ohlcv_df.index)

    labels = axis.tickStrings([0, 100, len(ohlcv_df) - 1], 1, 1)
    assert all(labels), "every in-range tick should carry a date"
    assert not any(l.isdigit() for l in labels), "must not fall back to bar numbers"
    assert labels[0] == ohlcv_df.index[0].strftime("%d %b")


def test_bar_date_axis_blanks_ticks_past_the_data(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import BarDateAxis
    axis = BarDateAxis(orientation="bottom")
    axis.set_index(ohlcv_df.index)
    assert axis.tickStrings([len(ohlcv_df) + 50], 1, 1) == [""]
    assert axis.tickStrings([-10], 1, 1) == [""]


def test_bar_date_axis_shows_times_for_intraday_bars(qapp):
    from tradelab.ui.widgets.pg_chart_widget import BarDateAxis
    axis = BarDateAxis(orientation="bottom")
    axis.set_index(pd.date_range("2026-07-22 09:30", periods=40, freq="5min"))
    assert ":" in axis.tickStrings([0], 1, 1)[0], "intraday ticks need a clock time"


def test_bar_date_axis_uses_month_year_for_multi_year_spans(qapp):
    from tradelab.ui.widgets.pg_chart_widget import BarDateAxis
    axis = BarDateAxis(orientation="bottom")
    axis.set_index(pd.date_range("2018-01-02", periods=1500, freq="B"))
    assert axis.tickStrings([0], 1, 1)[0] == "Jan 2018"


def test_bar_date_axis_without_data_is_safe(qapp):
    from tradelab.ui.widgets.pg_chart_widget import BarDateAxis
    axis = BarDateAxis(orientation="bottom")
    assert axis.tickStrings([0, 1], 1, 1) == ["0", "1"]   # default numbering
    axis.set_index(pd.Index([]))
    assert axis.tickStrings([0], 1, 1) == ["0"]


def test_plotting_feeds_dates_to_every_pane_axis(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())

    assert set(widget._date_axes) == {"price", "volume", "macd", "rsi"}
    for axis in widget._date_axes.values():
        assert axis.tickStrings([0], 1, 1)[0] == ohlcv_df.index[0].strftime("%d %b")


def test_only_the_lowest_visible_pane_shows_the_dates(qapp, ohlcv_df):
    """Dates belong once, at the bottom of the pane stack - not repeated
    between every sub-panel."""
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())

    def showing():
        return {k for k, a in widget._date_axes.items() if a.style["showValues"]}

    # RSI is the lowest pane when every sub-panel is on.
    widget._toggle_subpanel("Volume", True)
    widget._toggle_subpanel("MACD", True)
    widget._toggle_subpanel("RSI", True)
    assert showing() == {"rsi"}

    # Turn the lower panes off and the labels move up to what's left.
    widget._toggle_subpanel("RSI", False)
    assert showing() == {"macd"}
    widget._toggle_subpanel("MACD", False)
    assert showing() == {"volume"}
    widget._toggle_subpanel("Volume", False)
    assert showing() == {"price"}


# --- Measure tool (restored from the legacy matplotlib chart's ruler) -------

def _isolated_chart(tmp_path):
    """A chart widget whose drawing storage is a throwaway DB, so click tests
    that persist drawings never leak into (or read from) the shared data DB."""
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.data.database import Database
    widget = PGChartWidget()
    widget._db = Database(tmp_path / "chart_test.db")
    return widget


def _click_price(widget, x, y):
    """Simulate a click at data-space (x, y) on the price pane."""
    from PySide6.QtCore import QPointF
    vb = widget.price_plot.getViewBox()
    scene_pos = vb.mapViewToScene(QPointF(x, y))

    class _Evt:
        def __init__(self, sp): self._sp = sp
        def scenePos(self): return self._sp
    # Make the price pane's scene rect contain the point.
    widget.price_plot.sceneBoundingRect = lambda: type(
        "R", (), {"contains": lambda self, p: True})()
    widget._on_mouse_clicked(_Evt(scene_pos))


def test_measure_tool_is_offered(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget, DRAWING_TOOLS
    assert "Measure" in DRAWING_TOOLS
    widget = PGChartWidget()
    items = [widget.tool_combo.itemText(i) for i in range(widget.tool_combo.count())]
    assert "Measure" in items


def test_measure_takes_two_clicks_to_make_one_measure_drawing(qapp, ohlcv_df, tmp_path):
    widget = _isolated_chart(tmp_path)
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    widget.tool_combo.setCurrentText("Measure")

    _click_price(widget, 10, 100.0)          # first click just arms the tool
    assert widget.drawings == []
    _click_price(widget, 30, 110.0)          # second click commits the measure
    assert len(widget.drawings) == 1
    d = widget.drawings[0]
    assert d.kind == "measure"
    assert (d.x1, d.y1, d.x2, d.y2) == pytest.approx((10, 100.0, 30, 110.0))


def test_measure_label_reports_move_percent_and_bars(qapp, ohlcv_df):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.drawings import Drawing
    widget = PGChartWidget()
    widget.plot("AAPL", ohlcv_df, ScannerConfig())

    label = widget._measure_label(Drawing(kind="measure", x1=10, y1=100.0, x2=30, y2=112.5))
    assert "+12.50" in label          # price change
    assert "+12.50%" in label         # percent (100 -> 112.5)
    assert "20 bars" in label         # bar count
    # A dated frame adds the calendar span.
    assert "→" in label or "d " in label


def test_measure_label_without_dates_omits_the_span(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    from tradelab.core.drawings import Drawing
    widget = PGChartWidget()            # never plotted -> no dated index
    label = widget._measure_label(Drawing(kind="measure", x1=0, y1=50.0, x2=5, y2=45.0))
    assert "-5.00" in label and "-10.00%" in label and "5 bars" in label


# --- Escape returns a drawing tool to the plain cursor ---------------------

def test_cancel_tool_returns_to_cursor(qapp):
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.tool_combo.setCurrentText("Measure")
    assert widget.active_tool == "Measure"

    assert widget.cancel_tool() is True          # something to cancel
    assert widget.active_tool == "Cursor"
    assert widget.tool_combo.currentText() == "Cursor"


def test_cancel_tool_drops_a_half_finished_measure(qapp, ohlcv_df, tmp_path):
    widget = _isolated_chart(tmp_path)
    widget.plot("AAPL", ohlcv_df, ScannerConfig())
    widget.tool_combo.setCurrentText("Measure")

    _click_price(widget, 10, 100.0)              # first point armed
    assert widget._pending_point is not None
    assert widget.cancel_tool() is True
    assert widget._pending_point is None
    assert widget.active_tool == "Cursor"
    assert widget.drawings == []                 # nothing committed


def test_cancel_tool_is_a_noop_in_plain_cursor(qapp):
    """Escape only cancels when there is a tool/point to cancel, so it does not
    swallow the key from anything else when the cursor is already plain."""
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    assert widget.active_tool == "Cursor"
    assert widget.cancel_tool() is False


def test_escape_key_cancels_the_active_tool(qapp):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    widget = PGChartWidget()
    widget.tool_combo.setCurrentText("Trendline")

    esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    widget.keyPressEvent(esc)
    assert widget.active_tool == "Cursor"
    assert esc.isAccepted()
