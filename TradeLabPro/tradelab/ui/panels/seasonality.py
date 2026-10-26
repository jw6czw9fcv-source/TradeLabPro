"""The Seasonality tab: how a symbol has behaved by calendar."""
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


class _SeasonalityWorker(QThread):
    """Fetches a symbol's long history off the UI thread for seasonality."""
    done = Signal(str, object, str)      # symbol, DataFrame|None, error

    def __init__(self, symbol, period):
        super().__init__()
        self.symbol = symbol
        self.period = period

    def run(self):
        df, err = None, ""
        try:
            df = get_history(self.symbol, self.period, "1d")
        except BaseException as exc:
            err = str(exc)
        try:
            self.done.emit(self.symbol, df, err)
        except RuntimeError:
            pass


class SeasonalityPanel(QWidget):
    """Seasonality analysis for one symbol: how each calendar month and weekday
    has historically treated the stock, plus a year-by-year performance table.
    Purely descriptive of the past — it summarizes what price did in prior
    calendars, it does not predict the next one. All numbers come from
    tradelab.core.seasonality (offline-testable)."""

    def __init__(self):
        super().__init__()
        self._worker = None
        layout = QVBoxLayout(self)

        layout.addWidget(_hint(
            "Seasonality: how a stock has behaved by calendar. Enter a symbol and the app "
            "measures the average return and win rate for each month and weekday over its "
            "history, and its year-by-year performance — so you can see whether the current "
            "month has tended to be kind or cruel to that name. Descriptive of the past, not "
            "a prediction of the future."))

        row = QHBoxLayout()
        self.symbol = QLineEdit("SPY"); self.symbol.setMaximumWidth(120)
        self.symbol.returnPressed.connect(self.analyze)
        self.period = QComboBox(); self.period.addItems(["2y", "5y", "10y", "max"])
        self.period.setCurrentText("10y")
        go = QPushButton("Analyze"); go.clicked.connect(self.analyze)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.symbol)
        row.addWidget(QLabel("History")); row.addWidget(self.period)
        row.addWidget(go); row.addStretch()
        self.status = StatusLabel(); self.status.setStyleSheet("color:#8a9099;")
        row.addWidget(self.status)
        layout.addLayout(row)

        self.headline = QLabel("Enter a symbol and click Analyze.")
        self.headline.setWordWrap(True)
        self.headline.setStyleSheet("font-size:14px;")
        layout.addWidget(self.headline)

        # Monthly seasonality — the centrepiece.
        layout.addWidget(QLabel("By month"))
        self.month_table = QTableWidget(0, 6)
        self.month_table.setHorizontalHeaderLabels(
            ["Month", "Avg %", "Win %", "Best %", "Worst %", "Years"])
        self.month_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.month_table.verticalHeader().setVisible(False)
        self._tooltip_headers(self.month_table, {
            1: "Average month-over-month return for this calendar month across all years.",
            2: "Share of those years this month closed higher.",
            5: "How many years of this month are in the sample.",
        })
        layout.addWidget(self.month_table)

        # Weekday + annual, side by side.
        split = QHBoxLayout()
        dow_box = QVBoxLayout()
        dow_box.addWidget(QLabel("By weekday"))
        self.dow_table = QTableWidget(0, 3)
        self.dow_table.setHorizontalHeaderLabels(["Day", "Avg %", "Win %"])
        self.dow_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.dow_table.verticalHeader().setVisible(False)
        dow_box.addWidget(self.dow_table)
        split.addLayout(dow_box, 1)

        yr_box = QVBoxLayout()
        yr_box.addWidget(QLabel("By year"))
        self.year_table = QTableWidget(0, 2)
        self.year_table.setHorizontalHeaderLabels(["Year", "Return %"])
        self.year_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.year_table.verticalHeader().setVisible(False)
        yr_box.addWidget(self.year_table)
        split.addLayout(yr_box, 1)
        layout.addLayout(split)

        disclaimer = QLabel("Descriptive of past calendars only — not a forecast and not "
                            "financial advice.")
        disclaimer.setStyleSheet("color:#8a9099; font-size:11px;")
        layout.addWidget(disclaimer)

    def _tooltip_headers(self, table, tips):
        for col, text in tips.items():
            item = table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(text)

    def analyze(self):
        if self._worker is not None and self._worker.isRunning():
            return
        sym = self.symbol.text().strip().upper()
        if not sym:
            return
        self.status.setText(f"Loading {sym}…")
        self._worker = _SeasonalityWorker(sym, self.period.currentText())
        self._worker.done.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, symbol, df, err):
        from tradelab.core import seasonality as sz
        if err or df is None or getattr(df, "empty", True):
            flag_problem(self.status, f"Could not load {symbol}: {err or 'no data'}")
            return
        self.status.setText("")
        data = sz.summarize(df)
        self._render(symbol, data)

    def _pct_item(self, value, colorize=True, bold=False):
        item = QTableWidgetItem(f"{value:+.1f}%" if value is not None else "—")
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if colorize and value is not None:
            item.setForeground(QColor("#3fb950" if value >= 0 else "#e5534b"))
        if bold:
            f = item.font(); f.setBold(True); item.setFont(f)
        return item

    def _render(self, symbol, data):
        read_col = {"historically strong": "#3fb950", "historically weak": "#e5534b"}
        cur = data.get("current") or {}
        colour = read_col.get(cur.get("read"), "#c7d0d8")
        self.headline.setText(f"<b>{symbol}</b> — {data['text']}")
        self.headline.setStyleSheet(f"font-size:14px; color:{colour};")

        months = data["months"]
        best = data.get("best_month") or {}
        worst = data.get("worst_month") or {}
        self.month_table.setRowCount(len(months))
        for r, m in enumerate(months):
            is_extreme = m["label"] in (best.get("label"), worst.get("label")) and m["count"]
            name = QTableWidgetItem(m["label"])
            if is_extreme:
                f = name.font(); f.setBold(True); name.setFont(f)
            self.month_table.setItem(r, 0, name)
            # Avg cell is a heatmap cell: green→red by the average return.
            avg = m["avg"]
            avg_item = QTableWidgetItem(f"{avg:+.1f}%" if avg is not None else "—")
            avg_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if avg is not None:
                avg_item.setBackground(QColor(hm.color_for_change(avg)))
                avg_item.setForeground(QColor("#0b0e14"))
            self.month_table.setItem(r, 1, avg_item)
            wr = m["win_rate"]
            wr_item = QTableWidgetItem(f"{wr:.0f}%" if wr is not None else "—")
            wr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.month_table.setItem(r, 2, wr_item)
            self.month_table.setItem(r, 3, self._pct_item(m["best"]))
            self.month_table.setItem(r, 4, self._pct_item(m["worst"]))
            cnt = QTableWidgetItem(str(m["count"]))
            cnt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.month_table.setItem(r, 5, cnt)
        self.month_table.resizeColumnsToContents()

        dows = data["weekdays"]
        self.dow_table.setRowCount(len(dows))
        for r, d in enumerate(dows):
            self.dow_table.setItem(r, 0, QTableWidgetItem(d["label"]))
            self.dow_table.setItem(r, 1, self._pct_item(d["avg"]))
            wr = d["win_rate"]
            wr_item = QTableWidgetItem(f"{wr:.0f}%" if wr is not None else "—")
            wr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.dow_table.setItem(r, 2, wr_item)
        self.dow_table.resizeColumnsToContents()

        annual = list(reversed(data["annual"]))     # most recent year first
        self.year_table.setRowCount(len(annual))
        for r, a in enumerate(annual):
            self.year_table.setItem(r, 0, QTableWidgetItem(str(a["year"])))
            self.year_table.setItem(r, 1, self._pct_item(a["return_pct"]))
        self.year_table.resizeColumnsToContents()

    def shutdown(self):
        worker = self._worker
        if worker is not None:
            try:
                worker.done.disconnect()
            except (RuntimeError, TypeError):
                pass
            worker.wait(3000)
            self._worker = None
