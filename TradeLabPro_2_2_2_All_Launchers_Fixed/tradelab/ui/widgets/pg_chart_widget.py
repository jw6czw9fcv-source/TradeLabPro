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
    QToolButton, QMenu, QLabel, QInputDialog, QSizePolicy,
    QDialog, QDialogButtonBox, QSpinBox, QCheckBox, QScrollArea
)

from tradelab.core.config import ScannerConfig
from tradelab.core.indicators import (
    add_indicators, ema, sma, rsi as rsi_ind, macd as macd_ind,
    vwap, pivot_points, supertrend, ichimoku, heikin_ashi,
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

# Price-pane overlay indicators the user can add to a chart with a tunable
# period, without touching code. Each compute() returns {line label: Series}
# (some indicators draw more than one line). "period" is the default; None
# means the indicator has no tunable period.
def _bollinger_lines(df, p):
    from tradelab.core.indicators import bollinger
    mid, up, lo = bollinger(df["Close"], p)
    return {f"BB Upper {p}": up, f"BB Mid {p}": mid, f"BB Lower {p}": lo}


def _ichimoku_lines(df, p):
    cloud = ichimoku(df)
    return {"Tenkan": cloud["TENKAN"], "Kijun": cloud["KIJUN"]}


def _pivot_lines(df, p):
    piv = pivot_points(df)
    return {"PP": piv["PP"], "R1": piv["R1"], "S1": piv["S1"]}


CHART_OVERLAYS = {
    "EMA": {"period": 20, "compute": lambda df, p: {f"EMA {p}": ema(df["Close"], p)}},
    "SMA": {"period": 50, "compute": lambda df, p: {f"SMA {p}": sma(df["Close"], p)}},
    "VWAP": {"period": None, "compute": lambda df, p: {"VWAP": vwap(df)}},
    "Bollinger": {"period": 20, "compute": _bollinger_lines},
    "SuperTrend": {"period": 10, "compute": lambda df, p: {"SuperTrend": supertrend(df, p)[0]}},
    "Ichimoku": {"period": None, "compute": _ichimoku_lines},
    "Pivots": {"period": None, "compute": _pivot_lines},
}

# Distinct colors cycled across whatever overlays the user adds.
_OVERLAY_COLORS = ["#fbc531", "#e84118", "#4cd137", "#00a8ff", "#9c88ff",
                   "#e056fd", "#badc58", "#ff9f43", "#00cec9", "#74b9ff"]


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


class ChartIndicatorsDialog(QDialog):
    """Manage which indicators are on the chart and their periods, with no
    code: add/remove overlay rows (indicator + period), toggle the BUY/SELL
    signal markers, and toggle the Volume/MACD/RSI sub-panes."""
    def __init__(self, overlays, show_signals, sub_panels, rsi_period=14, macd_params=(12, 26, 9), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chart Indicators")
        self.resize(440, 460)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Price overlays (pick an indicator, set its period):"))
        self._rows_layout = QVBoxLayout()
        self._rows = []
        holder = QWidget(); holder.setLayout(self._rows_layout)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(holder)
        layout.addWidget(scroll, 1)
        add = QPushButton("+ Add overlay"); add.clicked.connect(lambda: self._add_row())
        layout.addWidget(add)
        for e in overlays:
            self._add_row(e.get("indicator", "EMA"), e.get("period"))

        self._signals_cb = QCheckBox("Show BUY/SELL signal markers")
        self._signals_cb.setChecked(show_signals)
        layout.addWidget(self._signals_cb)

        layout.addWidget(QLabel("Sub-panes (toggle on/off and set their periods):"))
        self._panel_cbs = {}
        # Volume: just a toggle. RSI: toggle + period. MACD: toggle + fast/slow/signal.
        vol_row = QHBoxLayout()
        self._panel_cbs["Volume"] = QCheckBox("Volume"); self._panel_cbs["Volume"].setChecked(sub_panels.get("Volume", True))
        vol_row.addWidget(self._panel_cbs["Volume"]); vol_row.addStretch()
        layout.addLayout(vol_row)

        rsi_row = QHBoxLayout()
        self._panel_cbs["RSI"] = QCheckBox("RSI"); self._panel_cbs["RSI"].setChecked(sub_panels.get("RSI", True))
        self._rsi_spin = QSpinBox(); self._rsi_spin.setRange(1, 200); self._rsi_spin.setValue(int(rsi_period)); self._rsi_spin.setMaximumWidth(70)
        rsi_row.addWidget(self._panel_cbs["RSI"]); rsi_row.addWidget(QLabel("period")); rsi_row.addWidget(self._rsi_spin); rsi_row.addStretch()
        layout.addLayout(rsi_row)

        macd_row = QHBoxLayout()
        self._panel_cbs["MACD"] = QCheckBox("MACD"); self._panel_cbs["MACD"].setChecked(sub_panels.get("MACD", True))
        self._macd_fast = QSpinBox(); self._macd_fast.setRange(1, 200); self._macd_fast.setValue(int(macd_params[0])); self._macd_fast.setMaximumWidth(60)
        self._macd_slow = QSpinBox(); self._macd_slow.setRange(1, 300); self._macd_slow.setValue(int(macd_params[1])); self._macd_slow.setMaximumWidth(60)
        self._macd_signal = QSpinBox(); self._macd_signal.setRange(1, 100); self._macd_signal.setValue(int(macd_params[2])); self._macd_signal.setMaximumWidth(60)
        macd_row.addWidget(self._panel_cbs["MACD"]); macd_row.addWidget(QLabel("fast/slow/signal"))
        macd_row.addWidget(self._macd_fast); macd_row.addWidget(self._macd_slow); macd_row.addWidget(self._macd_signal); macd_row.addStretch()
        layout.addLayout(macd_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def rsi_period(self):
        return self._rsi_spin.value()

    def macd_params(self):
        return (self._macd_fast.value(), self._macd_slow.value(), self._macd_signal.value())

    def _add_row(self, indicator="EMA", period=None):
        row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
        combo = QComboBox()
        for name in CHART_OVERLAYS:
            combo.addItem(name, name)
        i = combo.findData(indicator); combo.setCurrentIndex(i if i >= 0 else 0)
        spin = QSpinBox(); spin.setRange(1, 500); spin.setMaximumWidth(70)
        spin.setValue(int(period or CHART_OVERLAYS.get(indicator, {}).get("period") or 14))

        def sync():
            spin.setVisible(CHART_OVERLAYS.get(combo.currentData(), {}).get("period") is not None)
        combo.currentTextChanged.connect(lambda *_: (self._on_indicator_changed(combo, spin), sync()))
        sync()

        rm = QToolButton(); rm.setText("×"); rm.setMaximumWidth(24)
        rm.clicked.connect(lambda: self._remove_row(row))
        h.addWidget(combo, 2); h.addWidget(spin); h.addWidget(rm)
        self._rows_layout.addWidget(row)
        self._rows.append({"row": row, "combo": combo, "spin": spin})

    def _on_indicator_changed(self, combo, spin):
        p = CHART_OVERLAYS.get(combo.currentData(), {}).get("period")
        if p:
            spin.setValue(p)

    def _remove_row(self, row):
        self._rows = [r for r in self._rows if r["row"] is not row]
        self._rows_layout.removeWidget(row); row.deleteLater()

    def overlays(self):
        out = []
        for r in self._rows:
            name = r["combo"].currentData()
            has_period = CHART_OVERLAYS.get(name, {}).get("period") is not None
            out.append({"indicator": name, "period": (r["spin"].value() if has_period else None)})
        return out

    def show_signals(self):
        return self._signals_cb.isChecked()

    def sub_panels(self):
        return {k: cb.isChecked() for k, cb in self._panel_cbs.items()}


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
        # User-configurable price-pane overlays: a list of {indicator, period}
        # the user adds/edits via the Indicators dialog. Defaults to the two
        # EMAs the chart previously showed out of the box.
        self._overlays = [
            {"indicator": "EMA", "period": self.cfg.ema_fast},
            {"indicator": "EMA", "period": self.cfg.ema_slow},
        ]
        self._show_signals = True
        self._sub_panel_flags = {"Volume": True, "MACD": True, "RSI": True}
        # Tunable periods for the oscillator sub-panes (standard defaults).
        self._rsi_period = 14
        self._macd_fast, self._macd_slow, self._macd_signal = 12, 26, 9
        self._rsi_series = None   # cached for the crosshair readout
        self._macd_series = None
        self._empty_text_item = None
        self._last_indicators: Optional[pd.DataFrame] = None
        self._last_display: Optional[pd.DataFrame] = None
        self._legends = {}  # plot -> in-pane clickable legend widget

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
        self.overlay_btn.setText("Indicators…")
        self.overlay_btn.setToolTip("Add/remove chart indicators and change their periods")
        self.overlay_btn.clicked.connect(self.open_indicators_dialog)
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

    def open_indicators_dialog(self):
        dlg = ChartIndicatorsDialog(
            self._overlays, self._show_signals, self._sub_panel_flags,
            self._rsi_period, (self._macd_fast, self._macd_slow, self._macd_signal), self)
        if dlg.exec():
            self._overlays = dlg.overlays()
            self._show_signals = dlg.show_signals()
            self._sub_panel_flags = dlg.sub_panels()
            self._rsi_period = dlg.rsi_period()
            self._macd_fast, self._macd_slow, self._macd_signal = dlg.macd_params()
            for key, plot in (("MACD", self.macd_plot), ("RSI", self.rsi_plot), ("Volume", self.volume_plot)):
                plot.setVisible(self._sub_panel_flags.get(key, True))
            if self.symbol:
                self.replot()

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

        legend_entries = []  # (label, color) for the in-pane clickable legend

        def add_line(series: pd.Series, color: str, name: str, width: float = 1.4):
            pen = pg.mkPen(color, width=width)
            curve = self.price_plot.plot(x, np.asarray(series, dtype=float), pen=pen, name=name)
            self._overlay_curves[name] = curve
            legend_entries.append((name, color))

        # Render each user-configured overlay (see CHART_OVERLAYS), cycling
        # colors. Runs off self.df_raw so any period is computed on demand.
        color_i = 0
        for entry in self._overlays:
            spec = CHART_OVERLAYS.get(entry.get("indicator"))
            if spec is None:
                continue
            period = entry.get("period") or spec["period"]
            try:
                lines = spec["compute"](self.df_raw, period)
            except Exception:
                continue
            for label, series in lines.items():
                add_line(series, _OVERLAY_COLORS[color_i % len(_OVERLAY_COLORS)], label)
                color_i += 1

        self._make_legend(self.price_plot, legend_entries)

    def _make_legend(self, plot, entries):
        """Draw a clickable legend of indicators in the top-left of a pane.
        Clicking any entry opens the Indicators dialog to edit them - the
        legend IS the editing entry point, not just a label. Rebuilt on each
        replot. Implemented as a child QWidget (not a scene item) so it stays
        pinned to the corner regardless of pan/zoom."""
        old = self._legends.get(plot)
        if old is not None:
            old.setParent(None); old.deleteLater()
        if not entries:
            self._legends[plot] = None
            return
        box = QWidget(plot)
        box.setStyleSheet("background: rgba(17,21,28,160); border-radius: 3px;")
        lay = QVBoxLayout(box); lay.setContentsMargins(6, 2, 6, 2); lay.setSpacing(0)
        for text, color in entries:
            btn = QPushButton(text); btn.setFlat(True); btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Click to edit chart indicators")
            btn.setStyleSheet(
                f"QPushButton {{ color: {color}; border: none; text-align: left; padding: 0 2px; font-size: 11px; }}"
                " QPushButton:hover { text-decoration: underline; }")
            btn.clicked.connect(self.open_indicators_dialog)
            lay.addWidget(btn)
        box.adjustSize()
        box.move(46, 6)  # top-left, clear of the price y-axis labels
        box.show(); box.raise_()
        self._legends[plot] = box

    def _plot_signals(self, ind: pd.DataFrame, display: pd.DataFrame, x: np.ndarray):
        """BUY/SELL triangle markers: EMA fast/slow crossover confirmed by
        MACD histogram sign, same rule the legacy matplotlib chart used
        (kept for continuity - this is what a "BUY"/"SELL" mark on this
        chart has always meant, not a new signal definition).
        """
        if not self._show_signals:
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
            self._make_legend(self.macd_plot, [])
            return
        # Computed from the user-set fast/slow/signal, not the fixed columns.
        line, sig, hist = macd_ind(self.df_raw["Close"], self._macd_fast, self._macd_slow, self._macd_signal)
        self._macd_series = np.asarray(line, dtype=float)
        self.macd_plot.plot(x, np.asarray(line, dtype=float), pen=pg.mkPen("#4aa3ff", width=1.2))
        self.macd_plot.plot(x, np.asarray(sig, dtype=float), pen=pg.mkPen("#fbc531", width=1.2))
        hist_colors = [BULL_COLOR if v >= 0 else BEAR_COLOR for v in hist.fillna(0)]
        self.macd_plot.addItem(pg.BarGraphItem(x=x, height=hist.fillna(0).to_numpy(), width=BAR_WIDTH, brushes=hist_colors))
        self._make_legend(self.macd_plot, [(f"MACD {self._macd_fast}/{self._macd_slow}/{self._macd_signal}", "#4aa3ff")])

    def _plot_rsi(self, ind: pd.DataFrame, x: np.ndarray):
        self.rsi_plot.clear()
        self.rsi_plot.addItem(self._crosshair_lines[3], ignoreBounds=True)  # see _plot_macd
        if not self._sub_panel_flags["RSI"]:
            self._make_legend(self.rsi_plot, [])
            return
        series = rsi_ind(self.df_raw["Close"], self._rsi_period)
        self._rsi_series = np.asarray(series, dtype=float)
        self.rsi_plot.plot(x, self._rsi_series, pen=pg.mkPen("#9c88ff", width=1.4))
        self.rsi_plot.addLine(y=70, pen=pg.mkPen("#e5534b", style=Qt.DashLine))
        self.rsi_plot.addLine(y=30, pen=pg.mkPen("#3fb950", style=Qt.DashLine))
        self._make_legend(self.rsi_plot, [(f"RSI {self._rsi_period}", "#9c88ff")])

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
            for e in self._overlays:
                if e.get("indicator") in ("EMA", "SMA"):
                    p = e.get("period") or CHART_OVERLAYS[e["indicator"]]["period"]
                    col = f"{e['indicator']}{p}"
                    val = ind_row.get(col)
                    if val is not None and not pd.isna(val):
                        parts.append(f"{e['indicator']} {p} {val:.2f}")
            if self._sub_panel_flags["RSI"] and self._rsi_series is not None and idx < len(self._rsi_series):
                parts.append(f"RSI {self._rsi_period} {self._rsi_series[idx]:.1f}")
            if self._sub_panel_flags["MACD"] and self._macd_series is not None and idx < len(self._macd_series):
                parts.append(f"MACD {self._macd_series[idx]:.3f}")
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
        for plot in (self.price_plot, self.macd_plot, self.rsi_plot):
            self._make_legend(plot, [])
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
