"""The Replay tab: a chart played back bar by bar."""
import os
import sys
import json
import logging
import re
import traceback
import time
from pathlib import Path
import pandas as pd
from PySide6.QtCore import (Qt, QThread, Signal, QSettings, QTimer, QUrl, QSize, QRect,
                            QPoint, QEvent, QObject, Slot)
from PySide6.QtGui import QAction, QImage, QTextCursor, QColor, QIcon, QPainter, QFont, QPen, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QSpinBox, QDoubleSpinBox, QComboBox,
    QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QSplitter, QFormLayout, QGroupBox, QCheckBox,
    QAbstractItemView, QTextEdit, QFileDialog, QProgressBar, QScrollArea, QHeaderView,
    QMenu, QToolButton, QSizePolicy, QDialog, QTextBrowser, QSystemTrayIcon, QStyle,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsSimpleTextItem, QFrame,
    QInputDialog, QSlider, QGraphicsItem, QLayout, QStackedWidget, QButtonGroup,
    QTableView
)
from tradelab.core.config import (APP_NAME, APP_VERSION, ScannerConfig, DATA_DIR,
                                  ROOT_DIR, LOG_DIR)
from tradelab.data.database import Database
from tradelab.data.universe import list_symbols, available_universes, refresh_exchange_cache, import_universe_file, universe_metadata
from tradelab.data.market_data import get_history, get_histories
from tradelab.core.scanner import scan_symbols
from tradelab.core.alerts import Alert, AlertStore
from tradelab.core.filters import FilterCondition
from tradelab.core.journal import Journal, JournalEntry, summarize, group_stats
from tradelab.core.risk import size_position, r_targets
from tradelab.core.links import Link, LinkStore
from tradelab.core.notes import load_notes, save_notes
from tradelab.core.news import fetch_news, MARKET_SYMBOLS, GEO_SYMBOLS, SECTOR_ETFS
from tradelab.core import heatmap as hm
from tradelab.core import freshness
from tradelab.core import backup, updates
from tradelab.core.updates import parse_version, version_text
from tradelab.data.universe import US_NASDAQ, US_NYSE, US_AMEX, CAN_TSX, CAN_TSX_EXPANDED
from tradelab.strategies import strategy_choices
from tradelab.ui.chart_widget import ChartWorkspace, ChartWidget
from tradelab.ui.widgets.equity_curve import EquityCurveWidget
from tradelab.ui.widgets.rebased_chart import RebasedChartWidget
from tradelab.ui.widgets.retirement_chart import RetirementChartWidget
from tradelab.ui import colors, theme
from tradelab.core.backtester import backtest_ema_macd
from tradelab.core.ai_ranker import explain_symbol
from tradelab.core.logging_config import get_logger
from tradelab.settings import SETTINGS_FILE_ENV, app_settings  # noqa: E402,F401
from tradelab.ui.common import (  # noqa: E402,F401
    StatusLabel,
    NO_POPUPS_ENV,
    _PROBLEMS_LISTED,
    _problem_box,
    _problem_lines,
    show_problem,
    _problem_closed,
    flag_problem,
    _ProblemBridge,
    _problem_bridge,
    report_problem,
    ProblemPopupHandler,
    install_problem_popups,
    _ASFW_ANY,
    open_external,
    _shell_open,
    _allow_foreground,
    browser_exe_from_command,
    _default_browser_exe,
    _bring_browser_forward_soon,
    _bring_forward,
    AUTO_REFRESH_KEY,
    AUTO_REFRESH_MINUTES_KEY,
    auto_refresh_settings,
    AutoRefresh,
    fmt_large,
    SortableTableWidgetItem,
    table_item,
    _hint,
    _prices_as_of,
    _READ_COLORS,
    _fill_table,
    _HistoryWorker,
    FlowLayout)

log = get_logger(__name__)


class ReplayPanel(QWidget):
    """Bar-by-bar chart replay: load history, hide the future, and step or
    auto-play forward one candle at a time to practice reading a chart as it
    develops. Indicators recompute only on the revealed bars, so there is no
    look-ahead."""

    # Label -> milliseconds between bars while playing.
    _SPEEDS = {"0.5×": 1600, "1×": 800, "2×": 400, "4×": 200, "8×": 100}

    def __init__(self, chart: ChartWidget, cfg: ScannerConfig):
        super().__init__()
        self.chart = chart
        self.cfg = ScannerConfig()
        self.cfg.interval = "1d"
        self.data = None
        self.symbol_text = ""
        self.index = 0
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Practice reading a chart with the future hidden. Load a symbol, pick where "
            "to start, then Play or step candle by candle. Indicators only use the "
            "revealed bars — no peeking ahead."))

        row = QHBoxLayout()
        self.symbol = QLineEdit("AAPL"); self.symbol.setMaximumWidth(110)
        self.period = QComboBox(); self.period.addItems(["1y", "2y", "5y", "10y", "max"]); self.period.setCurrentText("2y")
        self.start_bars = QSpinBox(); self.start_bars.setRange(2, 5000); self.start_bars.setValue(60)
        self.start_bars.setToolTip("How many bars to reveal before you start stepping.")
        load = QPushButton("Load replay"); load.clicked.connect(self.load_replay)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.symbol)
        row.addWidget(QLabel("Period")); row.addWidget(self.period)
        row.addWidget(QLabel("Start at bar")); row.addWidget(self.start_bars)
        row.addWidget(load); row.addStretch()
        layout.addLayout(row)

        controls = QHBoxLayout()
        self.reset_btn = QToolButton(); self.reset_btn.setText("⏮"); self.reset_btn.setToolTip("Back to the start bar"); self.reset_btn.clicked.connect(self.reset)
        self.back_btn = QToolButton(); self.back_btn.setText("◀"); self.back_btn.setToolTip("Step back one bar"); self.back_btn.clicked.connect(lambda: self.step(-1))
        self.play_btn = QToolButton(); self.play_btn.setText("▶ Play"); self.play_btn.clicked.connect(self.toggle_play)
        self.fwd_btn = QToolButton(); self.fwd_btn.setText("▶"); self.fwd_btn.setToolTip("Step forward one bar"); self.fwd_btn.clicked.connect(lambda: self.step(1))
        self.end_btn = QToolButton(); self.end_btn.setText("⏭"); self.end_btn.setToolTip("Reveal all bars"); self.end_btn.clicked.connect(self.to_end)
        self.speed = QComboBox(); self.speed.addItems(list(self._SPEEDS.keys())); self.speed.setCurrentText("1×")
        self.speed.currentTextChanged.connect(self._on_speed_changed)
        for w in (self.reset_btn, self.back_btn, self.play_btn, self.fwd_btn, self.end_btn):
            controls.addWidget(w)
        controls.addWidget(QLabel("Speed")); controls.addWidget(self.speed)
        controls.addStretch()
        layout.addLayout(controls)

        self.slider = QSlider(Qt.Horizontal); self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

        self.status = StatusLabel("Load a symbol to begin.")
        layout.addWidget(self.status)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._set_controls_enabled(False)

    # --- loading ----------------------------------------------------------
    def load_replay(self):
        self.symbol_text = self.symbol.text().strip().upper()
        if not self.symbol_text:
            flag_problem(self.status, "Enter a symbol first.")
            return
        self.cfg.period = self.period.currentText()
        self.cfg.interval = "1d"
        self.data = get_history(self.symbol_text, self.cfg.period, self.cfg.interval)
        if self.data is None or self.data.empty:
            self.status.setText(f"No data for {self.symbol_text}.")
            return
        n = len(self.data)
        self.index = max(2, min(self.start_bars.value(), n))
        self.slider.blockSignals(True)
        self.slider.setRange(2, n); self.slider.setValue(self.index); self.slider.setEnabled(True)
        self.slider.blockSignals(False)
        self._set_controls_enabled(True)
        self._plot()

    def set_data(self, symbol, df):
        """Test/programmatic hook: use a supplied DataFrame instead of fetching."""
        self.symbol_text = symbol.upper()
        self.data = df
        n = len(df)
        self.index = max(2, min(self.start_bars.value(), n))
        self.slider.blockSignals(True)
        self.slider.setRange(2, n); self.slider.setValue(self.index); self.slider.setEnabled(True)
        self.slider.blockSignals(False)
        self._set_controls_enabled(True)
        self._plot()

    # --- transport --------------------------------------------------------
    def reset(self):
        self.pause()
        self.index = max(2, min(self.start_bars.value(), self._len()))
        self._plot()

    def step(self, delta):
        if self.data is None:
            return
        self.index = max(2, min(self._len(), self.index + int(delta)))
        self._plot()
        if self.index >= self._len():
            self.pause()

    def to_end(self):
        self.pause()
        self.index = self._len()
        self._plot()

    def toggle_play(self):
        if self._timer.isActive():
            self.pause()
        else:
            self.play()

    def play(self):
        if self.data is None or self.index >= self._len():
            return
        self._timer.start(self._SPEEDS[self.speed.currentText()])
        self.play_btn.setText("⏸ Pause")

    def pause(self):
        self._timer.stop()
        self.play_btn.setText("▶ Play")

    def _advance(self):
        if self.index >= self._len():
            self.pause(); return
        self.step(1)

    def _on_speed_changed(self, _label):
        if self._timer.isActive():
            self._timer.start(self._SPEEDS[self.speed.currentText()])

    def _on_slider(self, value):
        if self.data is None:
            return
        self.pause()
        self.index = int(value)
        self._plot()

    # --- helpers ----------------------------------------------------------
    def _len(self):
        return len(self.data) if self.data is not None else 0

    def _set_controls_enabled(self, on):
        for w in (self.reset_btn, self.back_btn, self.play_btn, self.fwd_btn, self.end_btn, self.speed):
            w.setEnabled(on)

    def _plot(self):
        if self.data is None or self.data.empty:
            return
        view = self.data.iloc[:self.index]
        self.chart.plot(self.symbol_text, view, self.cfg)
        self.slider.blockSignals(True); self.slider.setValue(self.index); self.slider.blockSignals(False)
        try:
            last_date = str(view.index[-1])[:10]
        except Exception:
            last_date = "?"
        at_end = " (end)" if self.index >= self._len() else ""
        self.status.setText(f"{self.symbol_text}  ·  bar {self.index}/{self._len()}  ·  {last_date}{at_end}")

    def shutdown(self):
        self.pause()
