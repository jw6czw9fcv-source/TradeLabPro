"""The News tab: headlines for symbols, markets and sectors."""
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


class NewsWorker(QThread):
    """Fetches market headlines off the UI thread."""
    done = Signal(object)   # list[NewsItem]

    def __init__(self, symbols, macro_only, fetcher=None, geo_only=False):
        super().__init__()
        self.symbols = symbols
        self.macro_only = macro_only
        self.geo_only = geo_only
        self._fetcher = fetcher

    def run(self):
        try:
            items = fetch_news(self.symbols, fetcher=self._fetcher,
                               macro_only=self.macro_only, geo_only=self.geo_only)
        except BaseException:
            items = []
        try:
            self.done.emit(items)
        except RuntimeError:
            pass


class NewsPanel(QWidget):
    """Recent market headlines for a symbol or the broad market, with
    macro/political stories flagged. Double-click opens the article in your
    browser. Read-only — it fetches and displays news, nothing else."""

    _COLS = ["Time", "Source", "Headline", "Tickers"]

    def __init__(self, fetcher=None):
        super().__init__()
        self._fetcher = fetcher          # injectable for tests
        self._worker = None
        self._items = []
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Recent headlines by source: a Symbol, the broad Market, a Sector, or "
            "Geopolitical news. Macro/political stories (Fed, inflation, elections, "
            "tariffs, war, OPEC…) are flagged ⚑ — a light stand-in for a full "
            "economic/political calendar. Double-click a headline to open it in your browser."))

        controls = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(["Symbol", "Market", "Sectors", "Geopolitical"])
        self.mode.currentTextChanged.connect(self._sync_mode)
        self.symbol = QLineEdit("AAPL"); self.symbol.setMaximumWidth(110)
        self.symbol.returnPressed.connect(self.get_news)
        self.sector = QComboBox(); self.sector.addItems(list(SECTOR_ETFS.keys()))
        self.macro_only = QCheckBox("Macro / political only")
        get_btn = QPushButton("Get news"); get_btn.clicked.connect(self.get_news)
        controls.addWidget(QLabel("Source")); controls.addWidget(self.mode)
        controls.addWidget(self.symbol)
        controls.addWidget(self.sector)
        controls.addWidget(self.macro_only)
        controls.addWidget(get_btn); controls.addStretch()
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.table, 1)

        self.status = StatusLabel("Pick a source and click Get news.")
        layout.addWidget(self.status)
        self._sync_mode()

    def _sync_mode(self, *_):
        mode = self.mode.currentText()
        self.symbol.setVisible(mode == "Symbol")
        self.sector.setVisible(mode == "Sectors")
        # Geopolitical is inherently filtered; the checkbox only applies elsewhere.
        self.macro_only.setEnabled(mode != "Geopolitical")

    def _symbols(self):
        mode = self.mode.currentText()
        if mode == "Market":
            return list(MARKET_SYMBOLS)
        if mode == "Geopolitical":
            return list(GEO_SYMBOLS)
        if mode == "Sectors":
            return [SECTOR_ETFS.get(self.sector.currentText(), "SPY")]
        sym = self.symbol.text().strip().upper()
        return [sym] if sym else []

    def get_news(self):
        if self._worker is not None and self._worker.isRunning():
            return
        symbols = self._symbols()
        if not symbols:
            flag_problem(self.status, "Enter a symbol first.")
            return
        geo = self.mode.currentText() == "Geopolitical"
        macro = self.macro_only.isChecked() and not geo
        self.status.setText("Fetching headlines…")
        self._worker = NewsWorker(symbols, macro, self._fetcher, geo_only=geo)
        self._worker.done.connect(self._on_done)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    def _clear_worker(self):
        self._worker = None

    def _on_done(self, items):
        self._items = items
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(it.published)) if it.published else ""
            headline = ("⚑ " + it.title) if it.is_macro else it.title
            cells = [QTableWidgetItem(when), QTableWidgetItem(it.publisher),
                     QTableWidgetItem(headline), QTableWidgetItem(", ".join(it.tickers[:4]))]
            cells[2].setData(Qt.UserRole, r)
            cells[2].setToolTip(it.summary or it.title)
            if it.is_macro:
                cells[2].setForeground(QColor("#f0a020"))
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        macro = sum(1 for i in items if i.is_macro)
        self.status.setText(f"{len(items)} headlines ({macro} macro/political). "
                            "Double-click to open." if items else
                            "No headlines found for that source.")

    def _open_row(self, row, _col):
        if 0 <= row < len(self._items):
            url = self._items[row].url
            if not url:
                flag_problem(self.status, "No link available for that headline.")
                return
            reason = open_external(url)
            if reason is None:
                self.status.setText("Opened article in your browser.")
            else:
                flag_problem(self.status, f"Could not open the article: {reason}", url)

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
