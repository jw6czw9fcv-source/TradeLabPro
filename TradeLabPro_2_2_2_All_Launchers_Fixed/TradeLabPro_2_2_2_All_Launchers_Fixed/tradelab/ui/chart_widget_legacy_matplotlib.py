from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QDialog,
    QDialogButtonBox, QCheckBox, QSpinBox, QDoubleSpinBox, QColorDialog, QFormLayout,
    QGroupBox, QTabWidget, QToolButton, QMessageBox, QListWidget, QListWidgetItem,
    QComboBox, QInputDialog, QGridLayout, QFileDialog
)

try:
    import matplotlib.dates as mdates
    import matplotlib.patches as patches
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    from matplotlib.figure import Figure
    from matplotlib.transforms import blended_transform_factory
except Exception:  # pragma: no cover - shown in UI if missing
    mdates = None
    patches = None
    FigureCanvas = None
    NavigationToolbar = None
    Figure = None
    blended_transform_factory = None

from tradelab.core.config import DATA_DIR, ScannerConfig
from tradelab.core.indicators import add_indicators, ema, macd, rsi, bollinger, signal_series
from tradelab.data.market_data import get_history


def fmt_number(value, precision: int = 2) -> str:
    try:
        v = float(value)
        if math.isnan(v):
            return "-"
        return f"{v:,.{precision}f}"
    except Exception:
        return "-"


def fmt_volume(value) -> str:
    try:
        v = float(value)
        if abs(v) >= 1_000_000_000:
            return f"{v/1_000_000_000:.2f}B"
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"{v/1_000:.1f}K"
        return f"{v:.0f}"
    except Exception:
        return "-"


CHART_COLOR_PALETTE = [
    "#4aa3ff", "#fbc531", "#4cd137", "#e84118", "#9c88ff", "#00a8ff",
    "#ff9f43", "#00cec9", "#e056fd", "#badc58", "#ff6b81", "#7f8fa6",
    "#fdcb6e", "#55efc4", "#74b9ff", "#fab1a0", "#a29bfe", "#81ecec",
]


def next_unused_color(used: set[str]) -> str:
    normalized = {str(c).lower() for c in used if c}
    for c in CHART_COLOR_PALETTE:
        if c.lower() not in normalized:
            return c
    return CHART_COLOR_PALETTE[len(normalized) % len(CHART_COLOR_PALETTE)]


@dataclass
class EMASetting:
    length: int
    color: str
    width: float = 1.1
    visible: bool = True


@dataclass
class ChartSettings:
    chart_type: str = "Candles"
    show_volume: bool = True
    show_macd: bool = True
    show_rsi: bool = True
    show_bollinger: bool = True
    show_signals: bool = True
    show_dividends: bool = True
    show_grid: bool = True
    show_compare: bool = False
    compare_symbols: str = "SPY,QQQ"
    compare_colors: dict[str, str] = field(default_factory=dict)
    candle_up_color: str = "#00b894"
    candle_down_color: str = "#d63031"
    volume_up_color: str = "#00b894"
    volume_down_color: str = "#d63031"
    volume_avg_color: str = "#dcdde1"
    macd_line_color: str = "#0984e3"
    macd_signal_color: str = "#e17055"
    macd_hist_up_color: str = "#00b894"
    macd_hist_down_color: str = "#d63031"
    rsi_color: str = "#a29bfe"
    boll_upper_color: str = "#8395a7"
    boll_mid_color: str = "#576574"
    boll_lower_color: str = "#8395a7"
    rsi_length: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    boll_length: int = 20
    boll_mult: float = 2.0
    emas: list[EMASetting] = field(default_factory=lambda: [
        EMASetting(5, "#a55eea"),
        EMASetting(9, "#4cd137"),
        EMASetting(30, "#fbc531"),
    ])

    @staticmethod
    def path() -> Path:
        d = DATA_DIR / "chart"
        d.mkdir(parents=True, exist_ok=True)
        return d / "chart_settings.json"

    @classmethod
    def load(cls) -> "ChartSettings":
        path = cls.path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["emas"] = [EMASetting(**e) for e in raw.get("emas", [])]
            raw.setdefault("compare_colors", {})
            for key, value in {
                "candle_up_color": "#00b894", "candle_down_color": "#d63031",
                "volume_up_color": "#00b894", "volume_down_color": "#d63031", "volume_avg_color": "#dcdde1",
                "macd_line_color": "#0984e3", "macd_signal_color": "#e17055",
                "macd_hist_up_color": "#00b894", "macd_hist_down_color": "#d63031",
                "rsi_color": "#a29bfe",
                "boll_upper_color": "#8395a7", "boll_mid_color": "#576574", "boll_lower_color": "#8395a7",
            }.items():
                raw.setdefault(key, value)
            return cls(**raw)
        except Exception:
            return cls()

    def save(self):
        self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


class IndicatorSettingsDialog(QDialog):
    """Unified indicator/settings dialog.

    CHT-027: every indicator row uses the same pattern:
    [visible checkbox] [indicator name] [parameter input] [color box].
    """
    def __init__(self, settings: ChartSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Indicator Manager / Chart Settings")
        self.settings = settings
        self.resize(720, 620)
        self.ema_rows: list[dict] = []
        self.color_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)

        chart_box = QGroupBox("Chart")
        chart_form = QFormLayout(chart_box)
        self.chart_type = QComboBox()
        self.chart_type.addItems(["Candles", "OHLC", "Line"])
        self.chart_type.setCurrentText(settings.chart_type)
        self.grid = QCheckBox("Show grid")
        self.grid.setChecked(settings.show_grid)
        self.signals = QCheckBox("BUY/SELL arrows")
        self.signals.setChecked(settings.show_signals)
        self.dividends = QCheckBox("Dividend D markers")
        self.dividends.setChecked(settings.show_dividends)
        chart_form.addRow("Chart type", self.chart_type)
        chart_form.addRow(self.grid)
        chart_form.addRow(self.signals)
        chart_form.addRow(self.dividends)
        layout.addWidget(chart_box)

        self.indicator_box = QGroupBox("Indicators")
        self.indicator_grid = QGridLayout(self.indicator_box)
        self.indicator_grid.setColumnStretch(1, 1)
        self.indicator_grid.addWidget(QLabel("On"), 0, 0)
        self.indicator_grid.addWidget(QLabel("Indicator"), 0, 1)
        self.indicator_grid.addWidget(QLabel("Parameter"), 0, 2)
        self.indicator_grid.addWidget(QLabel("Color"), 0, 3)
        self._row = 1

        self.volume_on = self._add_fixed_row("Volume", checked=settings.show_volume, value="Panel", color_attr="volume_up_color")
        self.macd_on, self.macd_params, self.macd_color_btn = self._add_text_param_row("MACD", settings.show_macd, f"{settings.macd_fast},{settings.macd_slow},{settings.macd_signal}", "macd_line_color")
        self.rsi_on, self.rsi_len, self.rsi_color_btn = self._add_spin_row("RSI", settings.show_rsi, settings.rsi_length, 2, 100, "rsi_color")
        self.boll_on, self.boll_len, self.boll_color_btn = self._add_spin_row("Bollinger", settings.show_bollinger, settings.boll_length, 2, 300, "boll_upper_color")
        self.boll_mult = QDoubleSpinBox(); self.boll_mult.setRange(0.1, 10.0); self.boll_mult.setDecimals(2); self.boll_mult.setValue(settings.boll_mult)
        self.indicator_grid.addWidget(QLabel("Bollinger std dev"), self._row, 1)
        self.indicator_grid.addWidget(self.boll_mult, self._row, 2)
        self._row += 1

        self._ema_start_row = self._row
        for ema_setting in settings.emas:
            self._add_ema_row(ema_setting)

        ema_buttons = QHBoxLayout()
        add_ema = QPushButton("Add EMA")
        add_ema.clicked.connect(self.add_ema)
        remove_ema = QPushButton("Remove last EMA")
        remove_ema.clicked.connect(self.remove_last_ema)
        ema_buttons.addWidget(add_ema)
        ema_buttons.addWidget(remove_ema)
        ema_buttons.addStretch()
        layout.addWidget(self.indicator_box)
        layout.addLayout(ema_buttons)

        compare = QGroupBox("Compare overlay")
        compare_form = QFormLayout(compare)
        self.show_compare = QCheckBox("Show compare overlay")
        self.show_compare.setChecked(settings.show_compare)
        self.compare_symbols = QLineEdit(settings.compare_symbols)
        compare_form.addRow(self.show_compare)
        compare_form.addRow("Symbols", self.compare_symbols)
        layout.addWidget(compare)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _color_button(self, color: str, callback) -> QPushButton:
        btn = QPushButton(color)
        btn.setMaximumWidth(92)
        btn.setStyleSheet(f"background-color: {color}; color: white; border: 1px solid #777;")
        btn.clicked.connect(callback)
        return btn

    def _choose_button_color(self, button: QPushButton) -> str:
        color = QColorDialog.getColor(QColor(button.text()), self, "Select color")
        if color.isValid():
            button.setText(color.name())
            button.setStyleSheet(f"background-color: {color.name()}; color: white; border: 1px solid #777;")
        return button.text()

    def _add_fixed_row(self, name: str, checked: bool, value: str, color_attr: str):
        cb = QCheckBox(); cb.setChecked(checked)
        val = QLabel(value)
        btn = self._color_button(getattr(self.settings, color_attr), lambda: self._choose_button_color(btn))
        self.color_buttons[color_attr] = btn
        self.indicator_grid.addWidget(cb, self._row, 0)
        self.indicator_grid.addWidget(QLabel(name), self._row, 1)
        self.indicator_grid.addWidget(val, self._row, 2)
        self.indicator_grid.addWidget(btn, self._row, 3)
        self._row += 1
        return cb

    def _add_spin_row(self, name: str, checked: bool, value: int, min_value: int, max_value: int, color_attr: str):
        cb = QCheckBox(); cb.setChecked(checked)
        spin = QSpinBox(); spin.setRange(min_value, max_value); spin.setValue(int(value)); spin.setMaximumWidth(90)
        btn = self._color_button(getattr(self.settings, color_attr), lambda: self._choose_button_color(btn))
        self.color_buttons[color_attr] = btn
        self.indicator_grid.addWidget(cb, self._row, 0)
        self.indicator_grid.addWidget(QLabel(name), self._row, 1)
        self.indicator_grid.addWidget(spin, self._row, 2)
        self.indicator_grid.addWidget(btn, self._row, 3)
        self._row += 1
        return cb, spin, btn

    def _add_text_param_row(self, name: str, checked: bool, value: str, color_attr: str):
        cb = QCheckBox(); cb.setChecked(checked)
        text = QLineEdit(value); text.setMaximumWidth(120)
        btn = self._color_button(getattr(self.settings, color_attr), lambda: self._choose_button_color(btn))
        self.color_buttons[color_attr] = btn
        self.indicator_grid.addWidget(cb, self._row, 0)
        self.indicator_grid.addWidget(QLabel(name), self._row, 1)
        self.indicator_grid.addWidget(text, self._row, 2)
        self.indicator_grid.addWidget(btn, self._row, 3)
        self._row += 1
        return cb, text, btn

    def _add_ema_row(self, setting: EMASetting):
        cb = QCheckBox(); cb.setChecked(setting.visible)
        spin = QSpinBox(); spin.setRange(2, 500); spin.setValue(int(setting.length)); spin.setMaximumWidth(90)
        btn = self._color_button(setting.color, lambda b=None, button=None: None)
        btn.clicked.disconnect()
        btn.clicked.connect(lambda _=False, button=btn: self._choose_button_color(button))
        self.indicator_grid.addWidget(cb, self._row, 0)
        self.indicator_grid.addWidget(QLabel("EMA"), self._row, 1)
        self.indicator_grid.addWidget(spin, self._row, 2)
        self.indicator_grid.addWidget(btn, self._row, 3)
        self.ema_rows.append({"checkbox": cb, "length": spin, "color": btn, "width": setting.width})
        self._row += 1

    def add_ema(self):
        used = {row["color"].text() for row in self.ema_rows}
        used.update(self.settings.compare_colors.values())
        self._add_ema_row(EMASetting(50, next_unused_color(used), visible=True))

    def remove_last_ema(self):
        if not self.ema_rows:
            return
        row = self.ema_rows.pop()
        for widget in [row["checkbox"], row["length"], row["color"]]:
            widget.setParent(None)
        # QLabel cells are harmless; they will be rebuilt next time dialog opens.

    def apply_to_settings(self):
        s = self.settings
        s.chart_type = self.chart_type.currentText()
        s.show_grid = self.grid.isChecked()
        s.show_signals = self.signals.isChecked()
        s.show_dividends = self.dividends.isChecked()
        s.show_volume = self.volume_on.isChecked()
        s.show_macd = self.macd_on.isChecked()
        s.show_rsi = self.rsi_on.isChecked()
        s.show_bollinger = self.boll_on.isChecked()
        s.rsi_length = self.rsi_len.value()
        try:
            fast, slow, sig = [int(x.strip()) for x in self.macd_params.text().split(",")[:3]]
            s.macd_fast, s.macd_slow, s.macd_signal = fast, slow, sig
        except Exception:
            pass
        s.boll_length = self.boll_len.value()
        s.boll_mult = self.boll_mult.value()
        s.volume_up_color = self.color_buttons["volume_up_color"].text()
        s.macd_line_color = self.color_buttons["macd_line_color"].text()
        s.rsi_color = self.color_buttons["rsi_color"].text()
        s.boll_upper_color = self.color_buttons["boll_upper_color"].text()
        s.boll_mid_color = s.boll_upper_color
        s.boll_lower_color = s.boll_upper_color
        # Keep existing companion colors unless explicitly redesigned later.
        s.emas = [EMASetting(row["length"].value(), row["color"].text(), float(row.get("width", 1.1)), row["checkbox"].isChecked()) for row in self.ema_rows]
        s.show_compare = self.show_compare.isChecked()
        s.compare_symbols = self.compare_symbols.text().strip()


class ChartWidget(QWidget):
    symbolChanged = Signal(str)
    PERIODS = [("1d", "1d"), ("1w", "5d"), ("1m", "1mo"), ("3m", "3mo"), ("6m", "6mo"), ("1y", "1y"), ("5y", "5y"), ("Max", "max")]

    def __init__(self):
        super().__init__()
        self.settings = ChartSettings.load()
        self.symbol = "AAPL"
        self.cfg = ScannerConfig()
        self.raw_df: Optional[pd.DataFrame] = None
        self.data: Optional[pd.DataFrame] = None
        self.compare_data: dict[str, pd.DataFrame] = {}
        self.history_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self.active_tool: Optional[str] = None
        self.pending_point: Optional[tuple[float, float]] = None
        self.drawn_objects = []
        self.fullscreen = False
        self._date_nums = None
        self._last_hover_row = None
        self._last_mouse_redraw_ms = 0

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)

        top = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search symbol…")
        self.search.setMaximumWidth(180); self.search.returnPressed.connect(self.search_symbol)
        top.addWidget(self.search)
        self.btn_settings = QToolButton(); self.btn_settings.setText("⚙"); self.btn_settings.setToolTip("Chart / Indicator settings"); self.btn_settings.clicked.connect(self.open_settings)
        self.btn_compare = QToolButton(); self.btn_compare.setText("⇄"); self.btn_compare.setToolTip("Toggle compare overlay"); self.btn_compare.clicked.connect(self.toggle_compare)
        self.btn_hline = QToolButton(); self.btn_hline.setText("─"); self.btn_hline.setToolTip("Add horizontal line"); self.btn_hline.clicked.connect(lambda: self.set_tool("hline"))
        self.btn_trend = QToolButton(); self.btn_trend.setText("╱"); self.btn_trend.setToolTip("Add trend line"); self.btn_trend.clicked.connect(lambda: self.set_tool("trend"))
        self.btn_ruler = QToolButton(); self.btn_ruler.setText("📏"); self.btn_ruler.setToolTip("Ruler tool"); self.btn_ruler.clicked.connect(lambda: self.set_tool("ruler"))
        self.btn_auto_sr = QToolButton(); self.btn_auto_sr.setText("S/R"); self.btn_auto_sr.setToolTip("Auto support / resistance"); self.btn_auto_sr.clicked.connect(self.auto_support_resistance)
        self.btn_delete_line = QToolButton(); self.btn_delete_line.setText("⌫"); self.btn_delete_line.setToolTip("Remove selected/last drawing"); self.btn_delete_line.clicked.connect(self.remove_drawing)
        self.btn_default = QToolButton(); self.btn_default.setText("↺"); self.btn_default.setToolTip("Default chart setup"); self.btn_default.clicked.connect(self.default_chart_setup)
        self.btn_save = QToolButton(); self.btn_save.setText("💾"); self.btn_save.setToolTip("Save chart setup"); self.btn_save.clicked.connect(self.save_chart_setup)
        self.btn_load = QToolButton(); self.btn_load.setText("📂"); self.btn_load.setToolTip("Load chart setup"); self.btn_load.clicked.connect(self.load_chart_setup)
        self.btn_full = QToolButton(); self.btn_full.setText("⛶"); self.btn_full.setToolTip("Full screen / default view"); self.btn_full.clicked.connect(self.toggle_fullscreen)
        for b in [self.btn_settings, self.btn_compare, self.btn_hline, self.btn_trend, self.btn_ruler, self.btn_auto_sr, self.btn_delete_line, self.btn_default, self.btn_save, self.btn_load, self.btn_full]:
            top.addWidget(b)
        top.addStretch()
        self.clock = QLabel("")
        self.clock.setStyleSheet("color: #a0a0a0;")
        top.addWidget(self.clock)
        self.layout.addLayout(top)

        if FigureCanvas is None:
            self.layout.addWidget(QLabel("Matplotlib not available. Install requirements.txt."))
            self.canvas = None
            return

        self.figure = Figure(figsize=(12, 8), facecolor="#11151c")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.nav = NavigationToolbar(self.canvas, self)
        self.nav.setVisible(True)  # CHT-037: restore standard chart toolbar (home/back/forward/pan/zoom/save)
        self.layout.addWidget(self.nav)
        self.layout.addWidget(self.canvas)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.period_buttons = []
        for label, period in self.PERIODS:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setMaximumWidth(46)
            btn.clicked.connect(lambda _=False, p=period: self.change_period(p))
            self.period_buttons.append(btn)
            bottom.addWidget(btn)
        self.layout.addLayout(bottom)

        self.info = QLabel("Move mouse over chart for OHLC / indicator values")
        self.info.setStyleSheet("color: #b8b8b8; font-size: 10px;")
        self.info.setWordWrap(True)
        self.layout.addWidget(self.info)

        self._connect_events()
        timer = QTimer(self); timer.timeout.connect(self._update_clock); timer.start(1000); self._update_clock()

    def _connect_events(self):
        self.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.canvas.mpl_connect("button_press_event", self.on_click)
        self.canvas.mpl_connect("scroll_event", self.on_scroll)
        self.canvas.mpl_connect("key_press_event", self.on_key)

    def _update_clock(self):
        self.clock.setText(pd.Timestamp.now().strftime("%H:%M:%S"))

    def search_symbol(self):
        symbol = self.search.text().strip().upper()
        if not symbol:
            return
        self.plot(symbol, self._get_cached_history(symbol, self.cfg.period, self.cfg.interval), self.cfg)
        self.search.clear()

    def _get_cached_history(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        key = (symbol.upper(), period, interval)
        if key not in self.history_cache:
            self.history_cache[key] = get_history(symbol, period, interval)
        return self.history_cache[key]

    def change_period(self, period: str):
        self.cfg.period = period
        if self.symbol:
            # Use in-memory cache so repeated period clicks feel instant.
            self.plot(self.symbol, self._get_cached_history(self.symbol, self.cfg.period, self.cfg.interval), self.cfg)

    def set_tool(self, tool: str):
        self.active_tool = tool
        self.pending_point = None
        self.info.setText(f"Tool active: {tool}. Click on the chart.")

    def toggle_compare(self):
        self.settings.show_compare = not self.settings.show_compare
        self.settings.save()
        self.replot()
        self.info.setText("Compare overlay " + ("ON" if self.settings.show_compare else "OFF"))

    def open_settings(self):
        dlg = IndicatorSettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_to_settings()
            self.settings.save()
            self.replot()

    def toggle_fullscreen(self):
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()

    def plot(self, symbol: str, df: pd.DataFrame, cfg: ScannerConfig):
        self.symbol = symbol.upper()
        self.symbolChanged.emit(self.symbol)
        self.search.clear()
        self.cfg = cfg
        self.raw_df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        self.replot()

    def replot(self):
        if self.canvas is None:
            return
        self.figure.clear()
        if self.raw_df is None or self.raw_df.empty:
            ax = self.figure.add_subplot(1, 1, 1)
            ax.text(0.5, 0.5, f"{self.symbol} - no data", ha="center", va="center")
            self.canvas.draw_idle(); return

        data = self._prepare_data(self.raw_df)
        self.data = data
        self._date_nums = mdates.date2num(pd.to_datetime(data.index).to_pydatetime()) if not data.empty else []
        self._last_hover_row = None
        panel_count = 1 + int(self.settings.show_volume) + int(self.settings.show_macd) + int(self.settings.show_rsi)
        heights = [5] + ([1.3] if self.settings.show_volume else []) + ([1.6] if self.settings.show_macd else []) + ([1.4] if self.settings.show_rsi else [])
        axes = self.figure.subplots(panel_count, 1, sharex=True, gridspec_kw={"height_ratios": heights})
        if panel_count == 1:
            axes = [axes]
        self.ax_price = axes[0]
        next_ax = 1
        self.ax_volume = axes[next_ax] if self.settings.show_volume else None; next_ax += int(self.settings.show_volume)
        self.ax_macd = axes[next_ax] if self.settings.show_macd else None; next_ax += int(self.settings.show_macd)
        self.ax_rsi = axes[next_ax] if self.settings.show_rsi else None
        for ax in axes:
            ax.set_facecolor("#11151c")
            ax.tick_params(colors="#d0d0d0", labelsize=8)
            for spine in ax.spines.values():
                spine.set_color("#444")
            if self.settings.show_grid:
                ax.grid(True, color="#2c3440", alpha=0.55, linewidth=0.6)
        self._plot_price(data)
        if self.ax_volume is not None: self._plot_volume(data)
        if self.ax_macd is not None: self._plot_macd(data)
        if self.ax_rsi is not None: self._plot_rsi(data)
        self._plot_compare(data)
        self._plot_dividends(data)
        self._plot_drawn_objects()
        self._autoscale_visible_all()
        self._refresh_price_legend()
        self._install_crosshair(axes)
        self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %Y\n%H:%M" if self.cfg.interval not in ["1d", "5d", "1wk", "1mo"] else "%d %b %Y"))
        self.figure.autofmt_xdate(rotation=0, ha="center")
        self.figure.subplots_adjust(left=0.035, right=0.965, top=0.965, bottom=0.055, hspace=0.04)
        self.canvas.draw_idle()

    def _visible_slice(self, data: pd.DataFrame) -> pd.DataFrame:
        if data is None or data.empty or not hasattr(self, "ax_price"):
            return data
        try:
            xmin, xmax = self.ax_price.get_xlim()
            nums = self._date_nums
            if nums is None or len(nums) != len(data):
                nums = mdates.date2num(pd.to_datetime(data.index).to_pydatetime())
            mask = (nums >= xmin) & (nums <= xmax)
            visible = data.loc[mask]
            return visible if not visible.empty else data
        except Exception:
            return data

    def _autoscale_axis(self, ax, values, pad_ratio: float = 0.08, force_zero: bool = False):
        try:
            vals = pd.Series(values).dropna().astype(float)
            if vals.empty:
                return
            ymin = float(vals.min()); ymax = float(vals.max())
            if force_zero:
                ymin = min(0.0, ymin)
            if ymin == ymax:
                pad = abs(ymax) * 0.02 or 1.0
            else:
                pad = (ymax - ymin) * pad_ratio
            ax.set_ylim(ymin - pad, ymax + pad)
        except Exception:
            return

    def _autoscale_visible_all(self):
        if self.data is None or self.data.empty or not hasattr(self, "ax_price"):
            return
        visible = self._visible_slice(self.data)
        price_cols = ["Low", "High", "Close"]
        for e in self.settings.emas:
            col = f"EMA{e.length}"
            if e.visible and col in visible:
                price_cols.append(col)
        if self.settings.show_bollinger:
            price_cols += [c for c in ["BB_UPPER", "BB_LOWER"] if c in visible]
        price_values = pd.concat([visible[c] for c in price_cols if c in visible], axis=0)
        self._autoscale_axis(self.ax_price, price_values, 0.06, False)
        if getattr(self, "ax_volume", None) is not None and "Volume" in visible:
            vol_values = visible[[c for c in ["Volume", "VOL_AVG20"] if c in visible]].stack()
            self._autoscale_axis(self.ax_volume, vol_values, 0.12, True)
        if getattr(self, "ax_macd", None) is not None:
            cols = [c for c in ["MACD", "MACD_SIGNAL", "MACD_HIST"] if c in visible]
            if cols:
                self._autoscale_axis(self.ax_macd, visible[cols].stack(), 0.18, False)
        if getattr(self, "ax_rsi", None) is not None:
            self.ax_rsi.set_ylim(0, 100)

    def _prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out = out.dropna(subset=["Open", "High", "Low", "Close"])
        for e in self.settings.emas:
            out[f"EMA{e.length}"] = ema(out["Close"], e.length)
        out["RSI"] = rsi(out["Close"], self.settings.rsi_length)
        out["MACD"], out["MACD_SIGNAL"], out["MACD_HIST"] = macd(out["Close"], self.settings.macd_fast, self.settings.macd_slow, self.settings.macd_signal)
        out["BB_MID"], out["BB_UPPER"], out["BB_LOWER"] = bollinger(out["Close"], self.settings.boll_length, self.settings.boll_mult)
        out["VOL_AVG20"] = out["Volume"].rolling(20).mean()
        return out.dropna(subset=["Close"])

    def _dates_width(self, data):
        x = mdates.date2num(pd.to_datetime(data.index).to_pydatetime())
        if len(x) > 1:
            return x, max((x[-1] - x[0]) / len(x) * 0.65, 0.0005)
        return x, 0.6

    def _plot_price(self, data):
        ax = self.ax_price
        x, width = self._dates_width(data)
        ctype = self.settings.chart_type
        if ctype == "Line":
            ax.plot(data.index, data["Close"], color="#4aa3ff", linewidth=1.1, label="Close")
        else:
            for xi, (_, row) in zip(x, data.iterrows()):
                color = self.settings.candle_up_color if row["Close"] >= row["Open"] else self.settings.candle_down_color
                ax.vlines(xi, row["Low"], row["High"], color=color, linewidth=0.8, alpha=0.95)
                if ctype == "Candles":
                    lower = min(row["Open"], row["Close"])
                    height = abs(row["Close"] - row["Open"])
                    height = height if height > 0 else max(row["High"] - row["Low"], 0.01) * 0.02
                    ax.add_patch(patches.Rectangle((xi - width/2, lower), width, height, facecolor=color, edgecolor=color, linewidth=0.7, alpha=0.9))
                else:  # OHLC
                    ax.hlines(row["Open"], xi - width/2, xi, color=color, linewidth=1.0)
                    ax.hlines(row["Close"], xi, xi + width/2, color=color, linewidth=1.0)
        # EMAs and legend values.
        legend = []
        for e in self.settings.emas:
            col = f"EMA{e.length}"
            if e.visible and col in data:
                ax.plot(data.index, data[col], color=e.color, linewidth=e.width, label=f"EMA {e.length} {fmt_number(data[col].iloc[-1])}")
        if self.settings.show_bollinger and "BB_UPPER" in data:
            ax.plot(data.index, data["BB_UPPER"], color=self.settings.boll_upper_color, linewidth=0.8, alpha=0.75, label=f"BB upper {fmt_number(data['BB_UPPER'].iloc[-1])}")
            ax.plot(data.index, data["BB_MID"], color=self.settings.boll_mid_color, linewidth=0.75, alpha=0.7, label=f"BB mid {fmt_number(data['BB_MID'].iloc[-1])}")
            ax.plot(data.index, data["BB_LOWER"], color=self.settings.boll_lower_color, linewidth=0.8, alpha=0.75, label=f"BB lower {fmt_number(data['BB_LOWER'].iloc[-1])}")
        if self.settings.show_signals:
            try:
                # BUG-002: BUY/SELL markers are derived from the visible EMA 9/30 crossover
                # with MACD confirmation.  This keeps markers consistent with the chart.
                fast_col = "EMA9" if "EMA9" in data.columns else f"EMA{self.cfg.ema_fast}"
                slow_col = "EMA30" if "EMA30" in data.columns else f"EMA{self.cfg.ema_slow}"
                if fast_col in data.columns and slow_col in data.columns:
                    fast = data[fast_col]
                    slow = data[slow_col]
                    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
                    cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
                    macd_ok_buy = data.get("MACD_HIST", pd.Series(index=data.index, data=1)).fillna(0) >= 0
                    macd_ok_sell = data.get("MACD_HIST", pd.Series(index=data.index, data=-1)).fillna(0) <= 0
                    buys = data.loc[cross_up & macd_ok_buy]
                    sells = data.loc[cross_down & macd_ok_sell]
                    if not buys.empty:
                        ax.scatter(buys.index, buys["Low"] * 0.985, marker="^", s=125, color="#44bd32", label="BUY", zorder=9)
                    if not sells.empty:
                        ax.scatter(sells.index, sells["High"] * 1.015, marker="v", s=125, color="#e84118", label="SELL", zorder=9)
            except Exception:
                pass
        ax.set_title(f"{self.symbol}  {self.cfg.period}  {self.cfg.interval}", color="#e6e6e6", fontsize=11, loc="left")
        ax.yaxis.tick_right(); ax.yaxis.set_label_position("right")

    def _refresh_price_legend(self):
        """Low-contrast transparent legend after all overlays are added."""
        handles, labels = self.ax_price.get_legend_handles_labels()
        if not handles:
            return
        leg = self.ax_price.legend(handles, labels, loc="upper left", fontsize=6.2, ncols=3, frameon=False, labelcolor="#9aa4ad", handlelength=1.2, handletextpad=0.35, columnspacing=0.8, borderaxespad=0.2)
        if leg:
            leg.get_frame().set_facecolor("none")
            leg.get_frame().set_edgecolor("none")
            for txt in leg.get_texts():
                txt.set_color("#8f9aa3")
                txt.set_alpha(0.85)

    def _panel_label(self, ax, text: str):
        # CHT-033: panel names are vertical and close to the left graph line.
        ax.set_ylabel("")
        ax.text(0.006, 0.5, text, transform=ax.transAxes, rotation=90,
                va="center", ha="left", color="#b8b8b8", fontsize=8,
                zorder=20, clip_on=False)

    def _plot_volume(self, data):
        colors = [self.settings.volume_up_color if c >= o else self.settings.volume_down_color for o, c in zip(data["Open"], data["Close"])]
        self.ax_volume.bar(data.index, data["Volume"], color=colors, width=0.8, alpha=0.55)
        if "VOL_AVG20" in data:
            self.ax_volume.plot(data.index, data["VOL_AVG20"], color=self.settings.volume_avg_color, linewidth=0.75, alpha=0.7)
        self._panel_label(self.ax_volume, "Volume")
        self.ax_volume.yaxis.set_major_formatter(lambda v, _pos: fmt_volume(v))
        self.ax_volume.yaxis.tick_right()

    def _plot_macd(self, data):
        hist = data["MACD_HIST"].fillna(0)
        colors = []
        for i, v in enumerate(hist):
            prev = hist.iloc[i-1] if i else 0
            if v >= 0 and v >= prev: colors.append(self.settings.macd_hist_up_color)
            elif v >= 0: colors.append(self.settings.macd_hist_up_color)
            elif v < prev: colors.append(self.settings.macd_hist_down_color)
            else: colors.append(self.settings.macd_hist_down_color)
        self.ax_macd.bar(data.index, hist, color=colors, width=0.8, alpha=0.75)
        self.ax_macd.plot(data.index, data["MACD"], color=self.settings.macd_line_color, linewidth=0.9, label=f"MACD {fmt_number(data['MACD'].iloc[-1])}")
        self.ax_macd.plot(data.index, data["MACD_SIGNAL"], color=self.settings.macd_signal_color, linewidth=0.9, label=f"Signal {fmt_number(data['MACD_SIGNAL'].iloc[-1])}")
        self.ax_macd.axhline(0, color="#888", linewidth=0.6)
        leg = self.ax_macd.legend(loc="upper left", fontsize=7, frameon=False)
        if leg:
            for txt in leg.get_texts(): txt.set_color("#9aa4ad")
        self._panel_label(self.ax_macd, "MACD")
        self.ax_macd.yaxis.tick_right()

    def _plot_rsi(self, data):
        self.ax_rsi.plot(data.index, data["RSI"], color=self.settings.rsi_color, linewidth=0.9, label=f"RSI {self.settings.rsi_length} {fmt_number(data['RSI'].iloc[-1])}")
        self.ax_rsi.axhline(70, color="#555", linestyle="--", linewidth=0.6)
        self.ax_rsi.axhline(50, color="#555", linestyle=":", linewidth=0.6)
        self.ax_rsi.axhline(30, color="#555", linestyle="--", linewidth=0.6)
        self.ax_rsi.set_ylim(0, 100)
        leg = self.ax_rsi.legend(loc="upper left", fontsize=7, frameon=False)
        if leg:
            for txt in leg.get_texts(): txt.set_color("#9aa4ad")
        self._panel_label(self.ax_rsi, "RSI")
        self.ax_rsi.yaxis.tick_right()

    def _plot_compare(self, data):
        if not self.settings.show_compare or not self.settings.compare_symbols.strip():
            return
        base = data["Close"].dropna()
        if base.empty:
            return
        for sym in [s.strip().upper() for s in self.settings.compare_symbols.split(",") if s.strip()][:5]:
            try:
                cdf = self._get_cached_history(sym, self.cfg.period, self.cfg.interval)
                if cdf.empty or "Close" not in cdf:
                    continue
                # Synchronize compare to the exact visible chart range and timestamps.
                close = cdf["Close"].dropna()
                close = close.reindex(data.index, method="nearest")
                close = close.dropna()
                if close.empty:
                    continue
                common = data.index.intersection(close.index)
                if len(common) == 0:
                    close = close.reindex(data.index, method="nearest").dropna()
                    common = close.index
                if len(common) == 0:
                    continue
                base_common = data.loc[common, "Close"].dropna()
                close = close.loc[base_common.index].dropna()
                if close.empty or base_common.empty:
                    continue
                comp = close / close.iloc[0] * base_common.iloc[0]
                pct = (close.iloc[-1] / close.iloc[0] - 1.0) * 100 if close.iloc[0] else 0.0
                if sym not in self.settings.compare_colors:
                    used = {e.color for e in self.settings.emas}
                    used.update(self.settings.compare_colors.values())
                    self.settings.compare_colors[sym] = next_unused_color(used)
                    self.settings.save()
                self.ax_price.plot(comp.index, comp, color=self.settings.compare_colors.get(sym), linewidth=0.95, linestyle="--", alpha=0.85, label=f"{sym} {fmt_number(close.iloc[-1])} ({pct:+.1f}%)")
            except Exception:
                continue

    def _plot_dividends(self, data):
        if not self.settings.show_dividends:
            return
        # If real dividend data exists in future data provider, draw it. Lightweight fallback: quarterly markers on long daily views.
        dates = []
        if "Dividends" in data.columns:
            dates = list(data.index[data["Dividends"].fillna(0) > 0])
        elif self.cfg.interval in ["1d", "5d", "1wk", "1mo"] and len(data) > 80:
            dates = list(data.index[::max(60, len(data)//6)])[1:]
        if not dates:
            return
        ymin, ymax = self.ax_price.get_ylim()
        y = ymin + (ymax - ymin) * 0.08
        for d in dates:
            self.ax_price.scatter([d], [y], s=70, color="#050505", edgecolor="#1e90ff", linewidth=1.4, zorder=7)
            self.ax_price.text(d, y, "D", color="#1e90ff", fontsize=7, ha="center", va="center", zorder=8)

    def _plot_drawn_objects(self):
        for obj in self.drawn_objects:
            kind = obj.get("kind")
            if kind == "hline":
                if self.data is not None and not self.data.empty:
                    self.ax_price.plot([self.data.index[0], self.data.index[-1]], [obj["y"], obj["y"]], color="white", linewidth=0.9, alpha=0.85)
                else:
                    self.ax_price.axhline(obj["y"], color="white", linewidth=0.9, alpha=0.85)
            elif kind in ["trend", "ruler"]:
                x1, y1, x2, y2 = obj["x1"], obj["y1"], obj["x2"], obj["y2"]
                color = "#f5f6fa" if kind == "trend" else "#00a8ff"
                self.ax_price.plot([x1, x2], [y1, y2], color=color, linewidth=1.0, alpha=0.9)
                if kind == "ruler":
                    pct = (y2 - y1) / y1 * 100 if y1 else 0
                    bars = abs(int(round(x2 - x1)))
                    label = f"{y2-y1:+.2f}  {pct:+.2f}%  {bars} bars"
                    xmin, xmax = self.ax_price.get_xlim(); ymin, ymax = self.ax_price.get_ylim()
                    xpad = (xmax - xmin) * 0.03; ypad = (ymax - ymin) * 0.04
                    lx = min(max(x2, xmin + xpad), xmax - xpad)
                    ly = min(max(y2, ymin + ypad), ymax - ypad)
                    ha = "right" if lx > xmin + (xmax - xmin) * 0.72 else "left"
                    self.ax_price.text(lx, ly, label, color="#dff9fb", fontsize=8, ha=ha, clip_on=True, bbox=dict(facecolor="#111", alpha=0.7, edgecolor="#00a8ff"))

    def _install_crosshair(self, axes):
        self.vlines = []
        self.hline = None
        for ax in axes:
            self.vlines.append(ax.axvline(data_to_num(self.data.index[-1]) if self.data is not None and not self.data.empty else 0, color="#c8d6e5", linewidth=0.55, alpha=0.0, linestyle="--"))
        self.hline = self.ax_price.axhline(0, color="#c8d6e5", linewidth=0.55, alpha=0.0, linestyle="--")
        # BUG-001: use a figure-level overlay so the date/time label is never hidden
        # behind subplots. It sits just above the x-axis/date area.
        # BUG-003: figure-level overlay.  It is positioned dynamically from
        # the bottom shared x-axis so it stays above the date/time axis and
        # remains visible over every chart layer.
        self.date_label = self.figure.text(0.5, 0.065, "", color="#f5f6fa", fontsize=8,
                                          ha="center", va="bottom", zorder=1000,
                                          bbox=dict(facecolor="#222", alpha=0.88, edgecolor="#555", pad=2.0))

    def on_motion(self, event):
        if self.data is None or self.data.empty or event.xdata is None:
            return
        idx = nearest_index(self.data.index, event.xdata, self._date_nums)
        if idx is None:
            return
        # Crosshair lines update continuously, but expensive text lookup is updated only when candle changes.
        for vl in getattr(self, "vlines", []):
            vl.set_xdata([event.xdata, event.xdata]); vl.set_alpha(0.75)
        if event.inaxes == self.ax_price and event.ydata is not None:
            self.hline.set_ydata([event.ydata, event.ydata]); self.hline.set_alpha(0.55)
        # BUG-003: the crosshair date/time label must update on every mouse
        # move, not only when the nearest candle changes.  The label follows
        # the vertical crosshair and shows the x-axis date/time under it.
        try:
            cursor_dt = mdates.num2date(event.xdata).replace(tzinfo=None)
            if self.cfg.interval not in ["1d", "5d", "1wk", "1mo"]:
                dt_label = pd.Timestamp(cursor_dt).strftime("%a %d %b %Y  %H:%M")
            else:
                dt_label = pd.Timestamp(cursor_dt).strftime("%a %d %b %Y")
        except Exception:
            dt_label = pd.to_datetime(idx).strftime("%a %d %b %Y  %H:%M")

        # Position the label just above the lowest panel's x-axis/date labels.
        try:
            bottom_ax = self.figure.axes[-1] if self.figure.axes else self.ax_price
            label_y = max(0.055, bottom_ax.get_position().y0 + 0.012)
            xfig = self.figure.transFigure.inverted().transform(
                self.ax_price.transData.transform((event.xdata, self.ax_price.get_ylim()[0]))
            )[0]
            xfig = max(0.065, min(0.935, xfig))
            self.date_label.set_position((xfig, label_y))
            self.date_label.set_text(dt_label)
            self.date_label.set_visible(True)
        except Exception:
            pass

        if idx != self._last_hover_row:
            self._last_hover_row = idx
            row = self.data.loc[idx]
            candle_dt = pd.to_datetime(idx).strftime("%a %d %b %Y  %H:%M")
            vals = [
                f"{self.symbol}  {candle_dt}",
                f"O {fmt_number(row.get('Open'))}", f"H {fmt_number(row.get('High'))}", f"L {fmt_number(row.get('Low'))}", f"C {fmt_number(row.get('Close'))}",
                f"Vol {fmt_volume(row.get('Volume'))}",
            ]
            for e in self.settings.emas:
                col = f"EMA{e.length}"
                if e.visible and col in self.data:
                    vals.append(f"EMA{e.length} {fmt_number(row.get(col))}")
            if "RSI" in self.data: vals.append(f"RSI {fmt_number(row.get('RSI'))}")
            if "MACD" in self.data: vals.append(f"MACD {fmt_number(row.get('MACD'))}")
            self.info.setText("   |   ".join(vals))
        self.canvas.draw_idle()

    def on_click(self, event):
        if event.inaxes != self.ax_price or event.xdata is None or event.ydata is None or not self.active_tool:
            return
        if self.active_tool == "hline":
            self.drawn_objects.append({"kind": "hline", "y": float(event.ydata)})
            self.active_tool = None
            self.replot(); return
        if self.pending_point is None:
            self.pending_point = (float(event.xdata), float(event.ydata))
            self.info.setText("First point saved. Click second point.")
            return
        x1, y1 = self.pending_point
        self.drawn_objects.append({"kind": self.active_tool, "x1": x1, "y1": y1, "x2": float(event.xdata), "y2": float(event.ydata)})
        self.pending_point = None
        self.active_tool = None
        self.replot()

    def on_scroll(self, event):
        if event.inaxes not in [getattr(self, "ax_price", None), getattr(self, "ax_volume", None), getattr(self, "ax_macd", None), getattr(self, "ax_rsi", None)] or event.xdata is None:
            return
        ax = self.ax_price
        cur_min, cur_max = ax.get_xlim()
        scale = 0.85 if event.button == "up" else 1.18
        center = event.xdata
        new_min = center - (center - cur_min) * scale
        new_max = center + (cur_max - center) * scale
        for a in self.figure.axes:
            a.set_xlim(new_min, new_max)
        self._autoscale_visible_all()
        self.canvas.draw_idle()

    def on_key(self, event):
        if event.key == "escape":
            self.active_tool = None; self.pending_point = None; self.info.setText("Tool cancelled.")
        elif event.key == "delete":
            if self.drawn_objects:
                self.drawn_objects.pop(); self.replot()

    def remove_drawing(self):
        if not self.drawn_objects:
            self.info.setText("No drawing objects to remove.")
            return
        items = []
        for i, obj in enumerate(self.drawn_objects):
            if obj.get("kind") == "hline":
                items.append(f"{i+1}: Horizontal line @ {obj.get('y', 0):.2f}")
            else:
                items.append(f"{i+1}: {obj.get('kind', 'line')} line")
        choice, ok = QInputDialog.getItem(self, "Remove drawing", "Select drawing to remove", items, len(items)-1, False)
        if ok and choice:
            idx = int(choice.split(":", 1)[0]) - 1
            if 0 <= idx < len(self.drawn_objects):
                self.drawn_objects.pop(idx)
                self.replot()

    def default_chart_setup(self):
        self.settings = ChartSettings()
        self.drawn_objects = []
        self.settings.save()
        self.replot()
        self.info.setText("Default chart setup restored.")

    def _template_dir(self) -> Path:
        d = DATA_DIR / "chart"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _template_path(self) -> Path:
        return self._template_dir() / "chart_template_default.json"

    def save_chart_setup(self):
        path_str, _ = QFileDialog.getSaveFileName(self, "Save chart setup", str(self._template_path()), "Chart setup (*.json)")
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        payload = {"settings": asdict(self.settings), "drawings": self.drawn_objects}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.info.setText(f"Chart setup saved: {path.name}")

    def load_chart_setup(self):
        path_str, _ = QFileDialog.getOpenFileName(self, "Load chart setup", str(self._template_dir()), "Chart setup (*.json)")
        if not path_str:
            return
        path = Path(path_str)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            settings_raw = raw.get("settings", {})
            settings_raw["emas"] = [EMASetting(**e) for e in settings_raw.get("emas", [])]
            self.settings = ChartSettings(**settings_raw)
            self.drawn_objects = raw.get("drawings", [])
            self.settings.save()
            self.replot()
            self.info.setText(f"Chart setup loaded: {path.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Load chart setup", f"Could not load chart setup:\n{exc}")

    def auto_support_resistance(self):
        if self.data is None or self.data.empty:
            return
        recent = self.data.tail(min(180, len(self.data)))
        support = float(recent["Low"].quantile(0.08))
        resistance = float(recent["High"].quantile(0.92))
        self.drawn_objects.append({"kind": "hline", "y": support})
        self.drawn_objects.append({"kind": "hline", "y": resistance})
        self.info.setText(f"Auto S/R added: support {support:.2f}, resistance {resistance:.2f}")
        self.replot()


def data_to_num(dt) -> float:
    return mdates.date2num(pd.to_datetime(dt).to_pydatetime())


def nearest_index(index, xnum, nums=None):
    if index is None or len(index) == 0 or xnum is None:
        return None
    if nums is None or len(nums) != len(index):
        nums = mdates.date2num(pd.to_datetime(index).to_pydatetime())
    i = int(abs(nums - xnum).argmin())
    return index[i]

class ChartWorkspace(QWidget):
    """Small tabbed chart workspace.

    The rest of the application can still call .plot(symbol, df, cfg).  The
    current tab is updated, and users can add more independent chart tabs with
    the + button.  This preserves the previous ChartWidget API while enabling
    multiple charts.
    """
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.setContentsMargins(2, 2, 2, 0)
        self.btn_new = QToolButton(); self.btn_new.setText("+"); self.btn_new.setToolTip("Open new chart tab")
        self.btn_new.clicked.connect(lambda: self.add_chart(""))
        row.addStretch(); row.addWidget(self.btn_new)
        layout.addLayout(row)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        layout.addWidget(self.tabs)
        self.add_chart("AAPL")

    def current_chart(self) -> ChartWidget:
        w = self.tabs.currentWidget()
        if w is None:
            w = self.add_chart("AAPL")
        return w

    def add_chart(self, symbol: str = "") -> ChartWidget:
        chart = ChartWidget()
        tab_name = symbol.upper() if symbol else "Empty"
        idx = self.tabs.addTab(chart, tab_name)
        chart.symbolChanged.connect(lambda sym, c=chart: self._update_tab_for_chart(c, sym))
        self.tabs.setCurrentIndex(idx)
        if symbol:
            try:
                cfg = ScannerConfig()
                df = chart._get_cached_history(symbol.upper(), cfg.period, cfg.interval)
                chart.plot(symbol.upper(), df, cfg)
            except Exception:
                pass
        else:
            chart.symbol = ""
            if getattr(chart, "ax_price", None) is None and chart.canvas is not None:
                chart.figure.clear()
                ax = chart.figure.add_subplot(1, 1, 1)
                ax.set_facecolor("#11151c")
                ax.text(0.5, 0.5, "Empty chart - search a symbol", color="#9aa4ad", ha="center", va="center", transform=ax.transAxes)
                chart.canvas.draw_idle()
        return chart

    def _update_tab_for_chart(self, chart: ChartWidget, symbol: str):
        idx = self.tabs.indexOf(chart)
        if idx >= 0:
            self.tabs.setTabText(idx, symbol.upper())

    def close_tab(self, index: int):
        if self.tabs.count() <= 1:
            return
        w = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if w is not None:
            w.deleteLater()

    def plot(self, symbol: str, df: pd.DataFrame, cfg: ScannerConfig):
        chart = self.current_chart()
        chart.plot(symbol, df, cfg)
        self.tabs.setTabText(self.tabs.currentIndex(), symbol.upper())
