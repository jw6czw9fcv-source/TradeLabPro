"""PyQtGraph-based chart panel (Chart Engine, Phase 1).

Replaces the previous matplotlib-based ChartWidget. PyQtGraph is GPU/OpenGL
friendly and built for exactly this use case: fast pan/zoom, live crosshair,
many overlays, without redrawing the whole figure on every interaction.

Public API kept intentionally compatible with the previous ChartWidget so
app.py did not need to change:
    - symbolChanged signal (str)
    - .symbol attribute
    - ._get_cached_history(symbol, period, interval)
    - .plot(symbol, df, cfg)
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPicture, QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QComboBox,
    QToolButton, QMenu, QLabel, QInputDialog, QSizePolicy
)

from tradelab.core.config import ScannerConfig
from tradelab.core.indicators import (
    add_indicators, vwap, pivot_points, supertrend, ichimoku, heikin_ashi,
)
from tradelab.core.drawings import Drawing, fib_levels, serialize, deserialize
from tradelab.data.market_data import get_history
from tradelab.data.database import Database
from tradelab.core.logging_config import get_logger

log = get_logger(__name__)

pg.setConfigOptions(antialias=True, background="#11151c", foreground="#c7d0d8")

BULL_COLOR = "#3fb950"
BEAR_COLOR = "#e5534b"
GRID_ALPHA = 0.15
BAR_WIDTH = 0.4  # candle/volume/MACD bar body width; bars sit 1 unit apart, so
                  # anything above ~0.6 makes adjacent bars look like they're touching.

CHART_TYPES = ["Candlestick", "Heikin-Ashi", "Line", "Area"]
DRAWING_TOOLS = ["Cursor", "Trendline", "H-Line", "V-Line", "Rect", "Fib", "Text"]
PERIOD_OPTIONS = ["3mo", "6mo", "1y", "2y", "5y", "max"]
INTERVAL_OPTIONS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo"]


class CandlestickItem(pg.GraphicsObject):
    """Efficient OHLC candle renderer using a cached QPicture (the standard
    pyqtgraph pattern for custom high-volume plot items)."""

    def __init__(self, df: pd.DataFrame):
        super().__init__()
        self.df = df
        self.picture = QPicture()
        self._generate()

    def set_data(self, df: pd.DataFrame):
        self.df = df
        self._generate()
        self.informViewBoundsChanged()
        self.update()

    def _generate(self):
        self.picture = QPicture()
        painter = QPainter(self.picture)
        if self.df is None or self.df.empty:
            painter.end()
            return
        width = BAR_WIDTH
        # Cosmetic pens stay a constant screen-pixel width regardless of
        # zoom. A non-cosmetic pen is measured in the same data-space units
        # as `width` (0.4) - a width of 1.0 there stretches half a unit past
        # each edge, comfortably bridging the 0.6-unit gap between candles
        # and fusing every body's outline into its neighbors.
        bull_pen = QPen(QColor(BULL_COLOR)); bull_pen.setCosmetic(True); bull_pen.setWidthF(1.2)
        bear_pen = QPen(QColor(BEAR_COLOR)); bear_pen.setCosmetic(True); bear_pen.setWidthF(1.2)
        bull_brush = QBrush(QColor(BULL_COLOR))
        bear_brush = QBrush(QColor(BEAR_COLOR))
        opens = self.df["Open"].to_numpy()
        highs = self.df["High"].to_numpy()
        lows = self.df["Low"].to_numpy()
        closes = self.df["Close"].to_numpy()
        for i in range(len(self.df)):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            bullish = c >= o
            painter.setPen(bull_pen if bullish else bear_pen)
            painter.drawLine(QPointF(i, l), QPointF(i, h))
            top, bottom = (c, o) if bullish else (o, c)
            # No outline on the body - fill only, so a wide stroke can never
            # bridge the gap into a neighboring candle regardless of zoom.
            painter.setPen(Qt.NoPen)
            painter.setBrush(bull_brush if bullish else bear_brush)
            painter.drawRect(pg.QtCore.QRectF(i - width / 2, bottom, width, max(top - bottom, 1e-6)))
        painter.end()

    def paint(self, painter, *args):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        if self.df is None or self.df.empty:
            return pg.QtCore.QRectF()
        lo = float(self.df["Low"].min())
        hi = float(self.df["High"].max())
        # Pad by a fraction of the visible High-Low span rather than a tiny
        # percent of price - a percent-of-price pad barely registers during
        # a tight consolidation, leaving wicks pinned to the plot edges.
        pad = (hi - lo) * 0.08 or (hi * 0.01) or 1.0
        return pg.QtCore.QRectF(
            -1, lo - pad,
            len(self.df) + 1, (hi - lo) + 2 * pad,
        )


class PGChartWidget(QWidget):
    symbolChanged = Signal(str)

    _history_cache: dict = {}
    CACHE_TTL_SECONDS = 60

    def __init__(self):
        super().__init__()
        self.symbol = ""
        self.df_raw: pd.DataFrame = pd.DataFrame()
        self.cfg = ScannerConfig()
        self.chart_type = "Candlestick"
        self.active_tool = "Cursor"
        self.drawings: list[Drawing] = []
        self._pending_point: Optional[tuple] = None
        self._db: Optional[Database] = None
        self._overlay_flags = {
            "EMA": True, "SMA": False, "Bollinger": False, "VWAP": False,
            "SuperTrend": False, "Ichimoku": False, "Pivots": False, "Signals": True,
        }
        self._sub_panel_flags = {"Volume": True, "MACD": True, "RSI": True}
        self._empty_text_item = None
        self._last_indicators: Optional[pd.DataFrame] = None
        self._last_display: Optional[pd.DataFrame] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        toolbar = QHBoxLayout()
        self.symbol_edit = QLineEdit()
        self.symbol_edit.setPlaceholderText("Symbol…")
        self.symbol_edit.setMaximumWidth(110)
        self.symbol_edit.returnPressed.connect(self.search_symbol)
        toolbar.addWidget(self.symbol_edit)

        go_btn = QPushButton("Go")
        go_btn.setMaximumWidth(36)
        go_btn.clicked.connect(self.search_symbol)
        toolbar.addWidget(go_btn)

        self.period_combo = QComboBox()
        self.period_combo.addItems(PERIOD_OPTIONS)
        self.period_combo.setCurrentText(self.cfg.period)
        self.period_combo.currentTextChanged.connect(self._on_period_changed)
        toolbar.addWidget(self.period_combo)

        self.interval_combo = QComboBox()
        self.interval_combo.addItems(INTERVAL_OPTIONS)
        self.interval_combo.setCurrentText(self.cfg.interval)
        self.interval_combo.setToolTip("Bar duration")
        self.interval_combo.currentTextChanged.connect(self._on_interval_changed)
        toolbar.addWidget(self.interval_combo)

        self.chart_type_combo = QComboBox()
        self.chart_type_combo.addItems(CHART_TYPES)
        self.chart_type_combo.currentTextChanged.connect(self._on_chart_type_changed)
        toolbar.addWidget(self.chart_type_combo)

        self.tool_combo = QComboBox()
        self.tool_combo.addItems(DRAWING_TOOLS)
        self.tool_combo.currentTextChanged.connect(self._on_tool_changed)
        toolbar.addWidget(self.tool_combo)

        self.overlay_btn = QToolButton()
        self.overlay_btn.setText("Overlays ▾")
        self.overlay_btn.setPopupMode(QToolButton.InstantPopup)
        self._build_overlay_menu()
        toolbar.addWidget(self.overlay_btn)

        clear_btn = QToolButton()
        clear_btn.setText("Clear drawings")
        clear_btn.clicked.connect(self.clear_drawings)
        toolbar.addWidget(clear_btn)

        toolbar.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9aa4ad;")
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        # Price pane + optional sub panes, all sharing the x axis.
        self.price_plot = pg.PlotWidget()
        self.price_plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self.price_plot.setMouseEnabled(x=True, y=True)
        self.candle_item = CandlestickItem(pd.DataFrame())
        self.line_item = self.price_plot.plot([], [], pen=pg.mkPen("#4aa3ff", width=1.5))
        self.line_item.setVisible(False)
        self.price_plot.addItem(self.candle_item)
        self.signal_scatter = pg.ScatterPlotItem()
        self.price_plot.addItem(self.signal_scatter)
        layout.addWidget(self.price_plot, stretch=3)

        self.volume_plot = pg.PlotWidget()
        self.volume_plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self.volume_plot.setXLink(self.price_plot)
        self.volume_bars = pg.BarGraphItem(x=[], height=[], width=0.6, brush="#4a6a8a")
        self.volume_plot.addItem(self.volume_bars)
        layout.addWidget(self.volume_plot, stretch=1)

        self.macd_plot = pg.PlotWidget()
        self.macd_plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self.macd_plot.setXLink(self.price_plot)
        layout.addWidget(self.macd_plot, stretch=1)

        self.rsi_plot = pg.PlotWidget()
        self.rsi_plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self.rsi_plot.setXLink(self.price_plot)
        layout.addWidget(self.rsi_plot, stretch=1)

        self._overlay_curves = {}
        self._drawing_items = []

        # Crosshair (synced across price/volume/macd/rsi panes).
        self._crosshair_lines = []
        for plot in (self.price_plot, self.volume_plot, self.macd_plot, self.rsi_plot):
            v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#666f78", width=1))
            plot.addItem(v_line, ignoreBounds=True)
            self._crosshair_lines.append(v_line)
        self._hline_price = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#666f78", width=1))
        self.price_plot.addItem(self._hline_price, ignoreBounds=True)

        # Each PlotWidget owns its own QGraphicsScene - connecting only
        # price_plot's sigMouseMoved means the crosshair simply freezes the
        # moment the mouse crosses into the volume/MACD/RSI panes below it.
        # Wire every pane (including any added later) into the same handler.
        for plot in (self.price_plot, self.volume_plot, self.macd_plot, self.rsi_plot):
            plot.scene().sigMouseMoved.connect(lambda pos, p=plot: self._on_mouse_moved(pos, p))
        self.price_plot.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        # Crosshair readout: date/time + full OHLCV + visible-indicator values
        # at the hovered bar, anchored at the bottom instead of floating over
        # the candles (where it can obscure the very bar it describes).
        self.crosshair_info = QLabel("Move mouse over chart for OHLCV / indicator values")
        self.crosshair_info.setStyleSheet("color:#b8b8b8; font-size:11px;")
        self.crosshair_info.setWordWrap(True)
        layout.addWidget(self.crosshair_info)

        self.show_empty_placeholder()

    def _build_overlay_menu(self):
        menu = QMenu(self)
        for key in self._overlay_flags:
            action = menu.addAction(key)
            action.setCheckable(True)
            action.setChecked(self._overlay_flags[key])
            action.toggled.connect(lambda checked, k=key: self._toggle_overlay(k, checked))
        menu.addSeparator()
        for key in self._sub_panel_flags:
            action = menu.addAction(f"Panel: {key}")
            action.setCheckable(True)
            action.setChecked(self._sub_panel_flags[key])
            action.toggled.connect(lambda checked, k=key: self._toggle_subpanel(k, checked))
        self.overlay_btn.setMenu(menu)

    # ------------------------------------------------------------------
    # Data loading / caching (kept same name/signature as before)
    # ------------------------------------------------------------------
    def _get_cached_history(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        key = (symbol.upper(), period, interval)
        now = time.time()
        cached = self._history_cache.get(key)
        if cached and (now - cached[0]) < self.CACHE_TTL_SECONDS:
            return cached[1]
        df = get_history(symbol, period, interval)
        self._history_cache[key] = (now, df)
        return df

    def search_symbol(self):
        sym = self.symbol_edit.text().strip().upper()
        if not sym:
            return
        df = self._get_cached_history(sym, self.cfg.period, self.cfg.interval)
        self.plot(sym, df, self.cfg)

    def _on_period_changed(self, period: str):
        self.cfg.period = period
        if self.symbol:
            df = self._get_cached_history(self.symbol, self.cfg.period, self.cfg.interval)
            self.plot(self.symbol, df, self.cfg)

    def _on_interval_changed(self, interval: str):
        self.cfg.interval = interval
        if self.symbol:
            df = self._get_cached_history(self.symbol, self.cfg.period, self.cfg.interval)
            self.plot(self.symbol, df, self.cfg)

    def _on_chart_type_changed(self, chart_type: str):
        self.chart_type = chart_type
        if self.symbol:
            self.replot()

    def _on_tool_changed(self, tool: str):
        self.active_tool = tool
        self._pending_point = None

    def _toggle_overlay(self, key: str, checked: bool):
        self._overlay_flags[key] = checked
        if self.symbol:
            self.replot()

    def _toggle_subpanel(self, key: str, checked: bool):
        self._sub_panel_flags[key] = checked
        plot_map = {"Volume": self.volume_plot, "MACD": self.macd_plot, "RSI": self.rsi_plot}
        plot_map[key].setVisible(checked)
        if self.symbol:
            self.replot()

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------
    def plot(self, symbol: str, df: pd.DataFrame, cfg: ScannerConfig):
        self.symbol = symbol.upper()
        self.cfg = cfg
        self.df_raw = df if df is not None else pd.DataFrame()
        self.symbol_edit.setText(self.symbol)
        self.status_label.setText(f"{self.symbol} · {len(self.df_raw)} bars")
        # cfg may come from elsewhere (e.g. a Scanner result) with a
        # different period/interval than what the toolbar shows - keep the
        # combos in sync without re-triggering their change handlers.
        for combo, value in ((self.period_combo, self.cfg.period), (self.interval_combo, self.cfg.interval)):
            combo.blockSignals(True)
            if value and combo.findText(value) >= 0:
                combo.setCurrentText(value)
            combo.blockSignals(False)
        self._load_drawings_for_symbol()
        self.replot()
        self.symbolChanged.emit(self.symbol)

    def replot(self):
        if self.df_raw is None or self.df_raw.empty:
            self.show_empty_placeholder()
            return

        if self._empty_text_item is not None:
            # Left over from show_empty_placeholder(); its bounding rect
            # sits near (0, 0) and was dragging the price pane's Y
            # auto-range toward zero instead of fitting the real price data.
            self.price_plot.removeItem(self._empty_text_item)
            self._empty_text_item = None

        indicators = add_indicators(
            self.df_raw, self.cfg.ema_fast, self.cfg.ema_slow,
            self.cfg.macd_fast, self.cfg.macd_slow, self.cfg.macd_signal,
        )

        if self.chart_type == "Heikin-Ashi":
            display = heikin_ashi(self.df_raw)
        else:
            display = self.df_raw

        x = np.arange(len(display))

        if self.chart_type in ("Candlestick", "Heikin-Ashi"):
            self.candle_item.set_data(display.reset_index(drop=True))
            self.candle_item.setVisible(True)
            self.line_item.setVisible(False)
        else:
            self.candle_item.setVisible(False)
            self.line_item.setVisible(True)
            self.line_item.setData(x, display["Close"].to_numpy())
            if self.chart_type == "Area":
                self.line_item.setFillLevel(float(display["Close"].min()))
                self.line_item.setBrush(pg.mkBrush(74, 163, 255, 60))
            else:
                self.line_item.setFillLevel(None)

        self._plot_overlays(indicators, x)
        self._plot_signals(indicators, display, x)
        self._plot_volume(display, x)
        self._plot_macd(indicators, x)
        self._plot_rsi(indicators, x)
        self._plot_drawings()

        # Kept for the crosshair readout (_on_mouse_moved), which needs the
        # same indicator/display values used to draw the chart.
        self._last_indicators = indicators
        self._last_display = display

        # Default zoom: fewer visible bars means more screen pixels per bar,
        # so the gap between candle bodies (BAR_WIDTH) is actually visible
        # instead of shrinking to sub-pixel and looking like one solid block.
        visible_start = max(0, len(x) - 100)
        self.price_plot.setXRange(visible_start, len(x), padding=0.02)

        # Y range is set explicitly (like X above) rather than left to
        # pyqtgraph's auto-range, which only recomputes on the next paint -
        # a chart replotted while its dock tab is hidden would silently keep
        # a stale range. show_empty_placeholder() also pins Y to a fixed
        # [-1, 1] at construction, which must be overridden here or every
        # chart's price pane stays locked to that placeholder range forever.
        visible = display.iloc[visible_start:]
        if self.chart_type in ("Candlestick", "Heikin-Ashi"):
            y_lo, y_hi = float(visible["Low"].min()), float(visible["High"].max())
        else:
            y_lo, y_hi = float(visible["Close"].min()), float(visible["Close"].max())
        self.price_plot.setYRange(y_lo, y_hi, padding=0.08)

    def _plot_overlays(self, ind: pd.DataFrame, x: np.ndarray):
        for name, curve in self._overlay_curves.items():
            self.price_plot.removeItem(curve)
        self._overlay_curves = {}

        def add_line(series: pd.Series, color: str, name: str, width: float = 1.2, dash=False):
            pen = pg.mkPen(color, width=width, style=(Qt.DashLine if dash else Qt.SolidLine))
            curve = self.price_plot.plot(x, series.to_numpy(), pen=pen, name=name)
            self._overlay_curves[name] = curve

        if self._overlay_flags["EMA"]:
            add_line(ind[f"EMA{self.cfg.ema_fast}"], "#fbc531", f"EMA{self.cfg.ema_fast}")
            add_line(ind[f"EMA{self.cfg.ema_slow}"], "#e84118", f"EMA{self.cfg.ema_slow}")
        if self._overlay_flags["SMA"]:
            add_line(ind["SMA20"], "#4cd137", "SMA20")
            add_line(ind["SMA50"], "#00a8ff", "SMA50")
            add_line(ind["SMA200"], "#9c88ff", "SMA200")
        if self._overlay_flags["Bollinger"]:
            add_line(ind["BB_UPPER"], "#74b9ff", "BB_UPPER", dash=True)
            add_line(ind["BB_LOWER"], "#74b9ff", "BB_LOWER", dash=True)
        if self._overlay_flags["VWAP"]:
            add_line(vwap(self.df_raw), "#00cec9", "VWAP", width=1.6)
        if self._overlay_flags["SuperTrend"]:
            line, _direction = supertrend(self.df_raw)
            add_line(line, "#ff9f43", "SuperTrend", width=1.6)
        if self._overlay_flags["Ichimoku"]:
            cloud = ichimoku(self.df_raw)
            add_line(cloud["TENKAN"], "#e056fd", "Tenkan")
            add_line(cloud["KIJUN"], "#badc58", "Kijun")
        if self._overlay_flags["Pivots"]:
            piv = pivot_points(self.df_raw)
            add_line(piv["PP"], "#c7d0d8", "PP", dash=True)
            add_line(piv["R1"], "#e5534b", "R1", dash=True)
            add_line(piv["S1"], "#3fb950", "S1", dash=True)

    def _plot_signals(self, ind: pd.DataFrame, display: pd.DataFrame, x: np.ndarray):
        """BUY/SELL triangle markers: EMA fast/slow crossover confirmed by
        MACD histogram sign, same rule the legacy matplotlib chart used
        (kept for continuity - this is what a "BUY"/"SELL" mark on this
        chart has always meant, not a new signal definition).
        """
        if not self._overlay_flags["Signals"]:
            self.signal_scatter.setData([])
            return
        fast_col, slow_col = f"EMA{self.cfg.ema_fast}", f"EMA{self.cfg.ema_slow}"
        if fast_col not in ind.columns or slow_col not in ind.columns:
            self.signal_scatter.setData([])
            return

        fast = ind[fast_col].to_numpy()
        slow = ind[slow_col].to_numpy()
        prev_fast = np.roll(fast, 1); prev_fast[0] = fast[0]
        prev_slow = np.roll(slow, 1); prev_slow[0] = slow[0]
        macd_hist = ind["MACD_HIST"].fillna(0).to_numpy() if "MACD_HIST" in ind.columns else np.zeros(len(ind))

        cross_up = (fast > slow) & (prev_fast <= prev_slow)
        cross_down = (fast < slow) & (prev_fast >= prev_slow)
        buy_mask = cross_up & (macd_hist >= 0)
        sell_mask = cross_down & (macd_hist <= 0)

        lows = display["Low"].to_numpy()
        highs = display["High"].to_numpy()
        # A white outline and a larger size than you'd guess are both needed
        # here - at the candle body's own fill color and a "reasonable"
        # ~14px size, an arrow_up/arrow_down marker is nearly invisible
        # sitting next to a same-colored candle.
        outline = pg.mkPen("#f5f6fa", width=1.5)
        spots = [
            dict(pos=(x[i], lows[i] * 0.985), symbol="arrow_up", size=36,
                 brush=pg.mkBrush(BULL_COLOR), pen=outline)
            for i in np.nonzero(buy_mask)[0]
        ] + [
            dict(pos=(x[i], highs[i] * 1.015), symbol="arrow_down", size=36,
                 brush=pg.mkBrush(BEAR_COLOR), pen=outline)
            for i in np.nonzero(sell_mask)[0]
        ]
        self.signal_scatter.setData(spots)

    def _plot_volume(self, display: pd.DataFrame, x: np.ndarray):
        colors = [
            BULL_COLOR if c >= o else BEAR_COLOR
            for o, c in zip(display["Open"], display["Close"])
        ]
        self.volume_plot.removeItem(self.volume_bars)
        self.volume_bars = pg.BarGraphItem(x=x, height=display["Volume"].to_numpy(), width=BAR_WIDTH, brushes=colors)
        self.volume_plot.addItem(self.volume_bars)

    def _plot_macd(self, ind: pd.DataFrame, x: np.ndarray):
        self.macd_plot.clear()
        # clear() wipes this pane's own crosshair vline (added once at
        # construction) on every single replot - a symbol change, an
        # overlay toggle, anything - so without re-adding it here the
        # crosshair silently stops rendering on this pane after the very
        # first replot, even though _on_mouse_moved keeps "moving" it.
        self.macd_plot.addItem(self._crosshair_lines[2], ignoreBounds=True)
        if not self._sub_panel_flags["MACD"]:
            return
        self.macd_plot.plot(x, ind["MACD"].to_numpy(), pen=pg.mkPen("#4aa3ff", width=1.2))
        self.macd_plot.plot(x, ind["MACD_SIGNAL"].to_numpy(), pen=pg.mkPen("#fbc531", width=1.2))
        hist_colors = [BULL_COLOR if v >= 0 else BEAR_COLOR for v in ind["MACD_HIST"].fillna(0)]
        self.macd_plot.addItem(pg.BarGraphItem(x=x, height=ind["MACD_HIST"].fillna(0).to_numpy(), width=BAR_WIDTH, brushes=hist_colors))

    def _plot_rsi(self, ind: pd.DataFrame, x: np.ndarray):
        self.rsi_plot.clear()
        self.rsi_plot.addItem(self._crosshair_lines[3], ignoreBounds=True)  # see _plot_macd
        if not self._sub_panel_flags["RSI"]:
            return
        self.rsi_plot.plot(x, ind["RSI14"].to_numpy(), pen=pg.mkPen("#9c88ff", width=1.4))
        self.rsi_plot.addLine(y=70, pen=pg.mkPen("#e5534b", style=Qt.DashLine))
        self.rsi_plot.addLine(y=30, pen=pg.mkPen("#3fb950", style=Qt.DashLine))

    # ------------------------------------------------------------------
    # Crosshair
    # ------------------------------------------------------------------
    def _on_mouse_moved(self, scene_pos, source_plot=None):
        source_plot = source_plot or self.price_plot
        if not source_plot.sceneBoundingRect().contains(scene_pos):
            return
        # Each pane has its own scene, so scene_pos is only meaningful
        # mapped through the ViewBox of whichever pane the mouse is
        # actually over - price and RSI, say, are on wildly different
        # value scales, and mapping through the wrong one would put the
        # horizontal line and OHLCV lookup at a nonsense position.
        view_pos = source_plot.getViewBox().mapSceneToView(scene_pos)
        x_val, y_val = view_pos.x(), view_pos.y()
        for line in self._crosshair_lines:
            line.setPos(x_val)
        if source_plot is self.price_plot:
            self._hline_price.setPos(y_val)

        idx = int(round(x_val))
        if not (0 <= idx < len(self.df_raw)):
            return

        row = self.df_raw.iloc[idx]
        ts = pd.Timestamp(self.df_raw.index[idx])
        # Intraday intervals need a time-of-day; daily+ bars don't.
        date_str = ts.strftime("%a %d %b %Y" if self.cfg.interval in ("1d", "5d", "1wk", "1mo") else "%a %d %b %Y  %H:%M")

        parts = [
            self.symbol, date_str,
            f"O {row['Open']:.2f}", f"H {row['High']:.2f}", f"L {row['Low']:.2f}", f"C {row['Close']:.2f}",
            f"Vol {row['Volume']:,.0f}",
        ]
        ind = self._last_indicators
        if ind is not None and idx < len(ind):
            ind_row = ind.iloc[idx]
            if self._overlay_flags["EMA"]:
                parts.append(f"EMA{self.cfg.ema_fast} {ind_row.get(f'EMA{self.cfg.ema_fast}', float('nan')):.2f}")
                parts.append(f"EMA{self.cfg.ema_slow} {ind_row.get(f'EMA{self.cfg.ema_slow}', float('nan')):.2f}")
            if self._sub_panel_flags["RSI"] and "RSI14" in ind.columns:
                parts.append(f"RSI {ind_row['RSI14']:.1f}")
            if self._sub_panel_flags["MACD"] and "MACD" in ind.columns:
                parts.append(f"MACD {ind_row['MACD']:.3f}")
        self.crosshair_info.setText("   |   ".join(parts))

    def _on_mouse_clicked(self, event):
        if self.active_tool == "Cursor":
            return
        scene_pos = event.scenePos()
        if not self.price_plot.sceneBoundingRect().contains(scene_pos):
            return
        view_pos = self.price_plot.getViewBox().mapSceneToView(scene_pos)
        x_val, y_val = float(view_pos.x()), float(view_pos.y())

        if self.active_tool == "H-Line":
            self.drawings.append(Drawing(kind="hline", x1=x_val, y1=y_val))
            self._plot_drawings(); self._save_drawings_for_symbol(); return
        if self.active_tool == "V-Line":
            self.drawings.append(Drawing(kind="vline", x1=x_val, y1=y_val))
            self._plot_drawings(); self._save_drawings_for_symbol(); return
        if self.active_tool == "Text":
            text, ok = QInputDialog.getText(self, "Chart note", "Text:")
            if ok and text:
                self.drawings.append(Drawing(kind="text", x1=x_val, y1=y_val, text=text))
                self._plot_drawings(); self._save_drawings_for_symbol()
            return

        # Two-click tools: trendline, rect, fib
        if self._pending_point is None:
            self._pending_point = (x_val, y_val)
            return
        x1, y1 = self._pending_point
        self._pending_point = None
        kind_map = {"Trendline": "trendline", "Rect": "rect", "Fib": "fib"}
        kind = kind_map.get(self.active_tool)
        if kind:
            self.drawings.append(Drawing(kind=kind, x1=x1, y1=y1, x2=x_val, y2=y_val))
            self._plot_drawings()
            self._save_drawings_for_symbol()

    # ------------------------------------------------------------------
    # Drawings render / persistence
    # ------------------------------------------------------------------
    def _plot_drawings(self):
        for item in self._drawing_items:
            self.price_plot.removeItem(item)
        self._drawing_items = []

        for d in self.drawings:
            if d.kind == "hline":
                item = pg.InfiniteLine(pos=d.y1, angle=0, pen=pg.mkPen(d.color, width=d.line_width))
            elif d.kind == "vline":
                item = pg.InfiniteLine(pos=d.x1, angle=90, pen=pg.mkPen(d.color, width=d.line_width))
            elif d.kind == "trendline":
                item = pg.PlotDataItem([d.x1, d.x2], [d.y1, d.y2], pen=pg.mkPen(d.color, width=d.line_width))
            elif d.kind == "rect":
                x0, x1v = sorted([d.x1, d.x2])
                y0, y1v = sorted([d.y1, d.y2])
                item = pg.QtWidgets.QGraphicsRectItem(x0, y0, x1v - x0, y1v - y0)
                item.setPen(pg.mkPen(d.color, width=d.line_width))
            elif d.kind == "fib":
                levels = fib_levels(d.y1, d.y2)
                x0, x1v = sorted([d.x1, d.x2])
                items = []
                for ratio, price in levels.items():
                    line = pg.PlotDataItem([x0, x1v], [price, price], pen=pg.mkPen(d.color, width=1, style=Qt.DashLine))
                    self.price_plot.addItem(line)
                    items.append(line)
                self._drawing_items.extend(items)
                continue
            elif d.kind == "text":
                item = pg.TextItem(d.text, color=d.color, anchor=(0, 1))
                item.setPos(d.x1, d.y1)
            else:
                continue
            self.price_plot.addItem(item)
            self._drawing_items.append(item)

    def clear_drawings(self):
        self.drawings = []
        self._plot_drawings()
        self._save_drawings_for_symbol()

    def _get_db(self) -> Database:
        if self._db is None:
            self._db = Database()
        return self._db

    def _save_drawings_for_symbol(self):
        if not self.symbol:
            return
        try:
            self._get_db().save_drawings(self.symbol, self.cfg.interval, serialize(self.drawings))
        except Exception:
            log.exception("Failed to save drawings for %s", self.symbol)

    def _load_drawings_for_symbol(self):
        self.drawings = []
        if not self.symbol:
            return
        try:
            payload = self._get_db().load_drawings(self.symbol, self.cfg.interval)
            if payload:
                self.drawings = deserialize(payload)
        except Exception:
            log.exception("Failed to load drawings for %s", self.symbol)

    # ------------------------------------------------------------------
    def show_empty_placeholder(self):
        self.candle_item.set_data(pd.DataFrame())
        self.line_item.setData([], [])
        self.signal_scatter.setData([])
        self.price_plot.clear()
        self.price_plot.addItem(self.candle_item)
        self.price_plot.addItem(self.signal_scatter)
        # price_plot.clear() also strips the price pane's own crosshair
        # lines (added once at construction, before this method's very
        # first call) - without re-adding them, the crosshair silently
        # never worked in the price pane, only in the volume/MACD/RSI
        # sub-panes (which are never cleared).
        self.price_plot.addItem(self._crosshair_lines[0], ignoreBounds=True)
        self.price_plot.addItem(self._hline_price, ignoreBounds=True)
        text = pg.TextItem("Empty chart — search a symbol", color="#9aa4ad", anchor=(0.5, 0.5))
        self.price_plot.addItem(text)
        self._empty_text_item = text
        self.price_plot.setXRange(-1, 1)
        self.price_plot.setYRange(-1, 1)
