"""The Risk tab: position sizing and sector exposure."""
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


class SectorExposureWorker(QThread):
    """Computes portfolio sector exposure off the UI thread (sector lookups can
    hit the network on first use)."""
    done = Signal(object, float)   # rows [(sector, value, pct)], total

    def __init__(self, positions):
        super().__init__()
        self.positions = positions

    def run(self):
        try:
            from tradelab.core.risk import sector_exposure
            rows, total = sector_exposure(self.positions)
        except BaseException:
            rows, total = [], 0.0
        try:
            self.done.emit(rows, total)
        except RuntimeError:
            pass


class RiskPanel(AutoRefresh, QWidget):
    """Position-sizing calculator + R-multiple targets + portfolio sector
    exposure. Pure planning math - it never places orders."""

    # Brought up to date when the tab is opened, if stale - see AutoRefresh.
    REFRESH_METHOD = "load_exposure"
    REFRESH_WORKERS = ("_exposure_worker",)
    REFRESH_POLICY = freshness.DAILY

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._exposure_worker = None
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Size a trade by risk, not by gut: set how much of your account you'll "
            "risk and where your stop is, and get the share count that risks exactly "
            "that. See your R-multiple targets and how concentrated your portfolio is "
            "by sector. Planning tool only — it places no orders."))

        # --- position sizing ----------------------------------------------
        box = QGroupBox("Position sizing")
        grid = QFormLayout(box)
        self.equity = QDoubleSpinBox(); self.equity.setRange(0, 1e12); self.equity.setPrefix("$"); self.equity.setGroupSeparatorShown(True); self.equity.setValue(100_000)
        self.risk_pct = QDoubleSpinBox(); self.risk_pct.setRange(0, 100); self.risk_pct.setDecimals(2); self.risk_pct.setValue(1.0); self.risk_pct.setSuffix(" %")
        self.side = QComboBox(); self.side.addItems(["Long", "Short"])
        self.entry = QDoubleSpinBox(); self.entry.setRange(0, 1e9); self.entry.setDecimals(2); self.entry.setPrefix("$"); self.entry.setValue(100.0)
        self.stop = QDoubleSpinBox(); self.stop.setRange(0, 1e9); self.stop.setDecimals(2); self.stop.setPrefix("$"); self.stop.setValue(95.0)
        self.max_pos = QDoubleSpinBox(); self.max_pos.setRange(0, 100); self.max_pos.setDecimals(1); self.max_pos.setSuffix(" %"); self.max_pos.setSpecialValueText("off")
        self.max_pos.setToolTip("Optional cap on position size as % of account (0 = off).")
        use_paper = QPushButton("Use paper account equity")
        use_paper.setToolTip("Fill Account equity from your paper-trading account.")
        use_paper.clicked.connect(self._use_paper_equity)
        grid.addRow("Account equity", self.equity)
        grid.addRow("Risk per trade", self.risk_pct)
        grid.addRow("Side", self.side)
        grid.addRow("Entry price", self.entry)
        grid.addRow("Stop price", self.stop)
        grid.addRow("Max position", self.max_pos)
        grid.addRow("", use_paper)
        layout.addWidget(box)
        for w in (self.equity, self.risk_pct, self.entry, self.stop, self.max_pos):
            w.valueChanged.connect(self._recompute)
        self.side.currentTextChanged.connect(self._recompute)

        self.result = QLabel(); self.result.setWordWrap(True)
        self.result.setStyleSheet("padding:6px; font-size:13px;")
        layout.addWidget(self.result)

        # --- R targets ----------------------------------------------------
        layout.addWidget(QLabel("Targets (R = your stop distance):"))
        self.targets = QTableWidget(0, 4)
        self.targets.setHorizontalHeaderLabels(["R", "Target price", "$ / share", "Position $"])
        self.targets.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.targets.setMaximumHeight(150)
        layout.addWidget(self.targets)

        # --- sector exposure ----------------------------------------------
        exp = QHBoxLayout()
        load_btn = QPushButton("Load portfolio exposure"); load_btn.clicked.connect(self.load_exposure)
        exp.addWidget(QLabel("Portfolio sector exposure")); exp.addStretch(); exp.addWidget(load_btn); exp.addWidget(self.make_freshness_label())
        layout.addLayout(exp)
        self.exposure = QTableWidget(0, 3)
        self.exposure.setHorizontalHeaderLabels(["Sector", "Value", "% of portfolio"])
        self.exposure.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.exposure.setSortingEnabled(True)
        layout.addWidget(self.exposure)
        self.exposure_status = QLabel("Positions come from the Portfolio tab.")
        layout.addWidget(self.exposure_status)

        self._recompute()

    # --- sizing -----------------------------------------------------------
    def _use_paper_equity(self):
        path = DATA_DIR / "paper_account.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Equity ~= cash + cost basis of open positions (offline, no marks).
            equity = float(data.get("cash", 0.0))
            for p in data.get("positions", []):
                equity += float(p.get("qty", 0) or 0) * float(p.get("avg_price", 0) or 0)
            self.equity.setValue(equity)
            self.result.setText(self.result.text())  # keep; _recompute fired via valueChanged
        except Exception:
            self.exposure_status.setText("No paper account found yet.")

    def _recompute(self):
        entry, stop, side = self.entry.value(), self.stop.value(), self.side.currentText()
        res = size_position(self.equity.value(), self.risk_pct.value(), entry, stop,
                            side=side, max_position_pct=(self.max_pos.value() or None))
        if not res.valid:
            self.result.setText(f"<span style='color:#f0553a'>{res.reason or 'Enter valid inputs.'}</span>")
            self._fill_targets(entry, stop, side, 0)
            return
        verb = "Buy" if side == "Long" else "Short"
        cap = f" &nbsp;·&nbsp; <span style='color:#f0a020'>capped by {res.capped_by}</span>" if res.capped_by else ""
        self.result.setText(
            f"<b style='font-size:15px'>{verb} {res.shares:,} shares</b>{cap}<br>"
            f"Position <b>${res.position_value:,.0f}</b> ({res.position_pct:.1f}% of account) &nbsp;·&nbsp; "
            f"Risk <b>${res.actual_risk:,.0f}</b> ({res.actual_risk_pct:.2f}% of account)<br>"
            f"Stop {res.stop_pct:.1f}% away &nbsp;·&nbsp; ${res.risk_per_share:.2f}/share at risk")
        self._fill_targets(entry, stop, side, res.shares)

    def _fill_targets(self, entry, stop, side, shares):
        tgs = r_targets(entry, stop, side, multiples=(1, 2, 3), shares=shares)
        self.targets.setRowCount(len(tgs))
        for r, t in enumerate(tgs):
            for c, item in enumerate([
                QTableWidgetItem(f"{t.r:g}R"),
                QTableWidgetItem(f"${t.price:,.2f}"),
                QTableWidgetItem(f"${t.pnl_per_share:,.2f}"),
                QTableWidgetItem(f"${t.pnl:,.0f}" if shares else "—"),
            ]):
                self.targets.setItem(r, c, item)
        self.targets.resizeColumnsToContents()

    # --- exposure ---------------------------------------------------------
    def load_exposure(self):
        if self._exposure_worker is not None and self._exposure_worker.isRunning():
            return
        self.note_refresh_started()
        positions = []
        for p in self.db.positions():
            sym = str(p.get("symbol", "")).upper().strip()
            shares = float(p.get("shares", 0) or 0)
            entry = float(p.get("entry_price", 0) or 0)
            if sym and shares and entry:
                positions.append({"symbol": sym, "market_value": shares * entry})
        if not positions:
            self.exposure_status.setText("No portfolio positions — add some in the Portfolio tab.")
            self.exposure.setRowCount(0)
            return
        self.exposure_status.setText("Loading sectors…")
        self._exposure_worker = SectorExposureWorker(positions)
        self._exposure_worker.done.connect(self._on_exposure)
        self._exposure_worker.start()

    def _on_exposure(self, rows, total):
        self.mark_refreshed()
        self.exposure.setSortingEnabled(False)
        self.exposure.setRowCount(len(rows))
        top = rows[0] if rows else None
        for r, (sector, value, pct) in enumerate(rows):
            self.exposure.setItem(r, 0, QTableWidgetItem(sector))
            self.exposure.setItem(r, 1, SortableTableWidgetItem(f"${value:,.0f}", sort_value=value))
            pct_item = SortableTableWidgetItem(f"{pct:.1f}%", sort_value=pct)
            # Flag heavy concentration in a single sector.
            if pct >= 40:
                pct_item.setForeground(QColor("#f0a020"))
            self.exposure.setItem(r, 2, pct_item)
        self.exposure.setSortingEnabled(True)
        self.exposure.sortItems(1, Qt.DescendingOrder)
        self.exposure.resizeColumnsToContents()
        msg = f"Portfolio value ${total:,.0f} across {len(rows)} sector(s)."
        if top and top[2] >= 40:
            msg += f"  ⚠ {top[0]} is {top[2]:.0f}% of the book."
        self.exposure_status.setText(msg)

    def shutdown(self):
        if self._exposure_worker is not None and self._exposure_worker.isRunning():
            self._exposure_worker.wait(3000)
