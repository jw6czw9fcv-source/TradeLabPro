"""The Paper Trading tab: simulated orders, no real money."""
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


class PaperTradingPanel(QWidget):
    """Phase 8: paper-trading desk. A fully simulated account (local ledger,
    no real money, no live order routing) with order entry, positions, and
    live P&L. Backed by tradelab.core.broker.PaperBroker."""

    def __init__(self):
        super().__init__()
        from tradelab.core.broker import (PaperBroker, BUY, SELL, MARKET, LIMIT,
                                          STOP, STOP_LIMIT, TRAILING_STOP)
        self._BUY, self._SELL = BUY, SELL
        self._MARKET, self._LIMIT = MARKET, LIMIT
        self._STOP, self._STOP_LIMIT, self._TRAIL = STOP, STOP_LIMIT, TRAILING_STOP
        self.broker = PaperBroker(starting_cash=100_000.0,
                                  persist_path=DATA_DIR / "paper_account.json")
        layout = QVBoxLayout(self)

        banner = QLabel("PAPER TRADING — simulated account. No real money, no live "
                        "orders are ever placed. For practice and testing only.")
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#3a2f00; color:#ffd24a; padding:6px; "
                             "border-radius:4px; font-weight:bold;")
        layout.addWidget(banner)

        # --- account summary ---
        self._summary = QLabel(); self._summary.setStyleSheet("font-size:12px;")
        layout.addWidget(self._summary)

        # --- order entry ---
        entry = QHBoxLayout()
        self.o_symbol = QLineEdit("AAPL"); self.o_symbol.setMaximumWidth(80)
        self.o_side = QComboBox(); self.o_side.addItems([BUY, SELL])
        self.o_qty = QSpinBox(); self.o_qty.setRange(1, 1_000_000); self.o_qty.setValue(10)
        self.o_type = QComboBox(); self.o_type.addItems([MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP])
        self.o_limit = QDoubleSpinBox(); self.o_limit.setRange(0.0, 1e7); self.o_limit.setDecimals(2); self.o_limit.setMaximumWidth(90); self.o_limit.setPrefix("$")
        self.o_stop = QDoubleSpinBox(); self.o_stop.setRange(0.0, 1e7); self.o_stop.setDecimals(2); self.o_stop.setMaximumWidth(90); self.o_stop.setPrefix("$")
        self.o_trail = QDoubleSpinBox(); self.o_trail.setRange(0.0, 1e7); self.o_trail.setDecimals(2); self.o_trail.setMaximumWidth(80)
        self.o_trail_unit = QComboBox(); self.o_trail_unit.addItems(["$", "%"]); self.o_trail_unit.setMaximumWidth(48)
        self.o_type.currentTextChanged.connect(self._sync_order_fields)
        place = QPushButton("Place order"); place.clicked.connect(self._place)
        for w in (QLabel("Symbol"), self.o_symbol, QLabel("Side"), self.o_side,
                  QLabel("Qty"), self.o_qty, QLabel("Type"), self.o_type,
                  QLabel("Limit"), self.o_limit, QLabel("Stop"), self.o_stop,
                  QLabel("Trail"), self.o_trail, self.o_trail_unit, place):
            entry.addWidget(w)
        entry.addStretch()
        layout.addLayout(entry)

        # --- bracket (optional attached exits) ---
        brow = QHBoxLayout()
        self.o_bracket = QCheckBox("Bracket:")
        self.o_bracket.setToolTip("Attach a take-profit and/or stop-loss to a Market or Limit entry (one cancels the other).")
        self.o_tp = QDoubleSpinBox(); self.o_tp.setRange(0.0, 1e7); self.o_tp.setDecimals(2); self.o_tp.setMaximumWidth(90); self.o_tp.setPrefix("$")
        self.o_sl = QDoubleSpinBox(); self.o_sl.setRange(0.0, 1e7); self.o_sl.setDecimals(2); self.o_sl.setMaximumWidth(90); self.o_sl.setPrefix("$")
        self.o_bracket.toggled.connect(self._sync_order_fields)
        brow.addWidget(self.o_bracket)
        brow.addWidget(QLabel("Take-profit")); brow.addWidget(self.o_tp)
        brow.addWidget(QLabel("Stop-loss")); brow.addWidget(self.o_sl)
        brow.addWidget(_hint("0 = leave that exit off. Bracket uses a Market or Limit entry."))
        brow.addStretch()
        layout.addLayout(brow)
        self._sync_order_fields()

        # --- actions ---
        actions = QHBoxLayout()
        refresh = QPushButton("Refresh (mark-to-market + trigger stops/limits)")
        refresh.clicked.connect(self.refresh)
        cancel_btn = QPushButton("Cancel selected order"); cancel_btn.clicked.connect(self._cancel_selected)
        reset = QPushButton("Reset account"); reset.clicked.connect(self._reset)
        actions.addWidget(refresh); actions.addWidget(cancel_btn); actions.addWidget(reset); actions.addStretch()
        layout.addLayout(actions)

        # --- positions table ---
        layout.addWidget(QLabel("Positions"))
        self.pos_table = QTableWidget(0, 6)
        self.pos_table.setHorizontalHeaderLabels(
            ["Symbol", "Qty", "Avg price", "Last", "Mkt value", "Unrealized P&L"])
        self.pos_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.pos_table)

        # --- orders table ---
        layout.addWidget(QLabel("Orders"))
        self.ord_table = QTableWidget(0, 9)
        self.ord_table.setHorizontalHeaderLabels(
            ["ID", "Symbol", "Side", "Qty", "Type", "Limit", "Stop", "Status", "Fill price"])
        self.ord_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ord_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.ord_table)

        self.refresh()

    def _sync_order_fields(self, *_):
        t = self.o_type.currentText()
        bracket = self.o_bracket.isChecked()
        self.o_limit.setEnabled(t in (self._LIMIT, self._STOP_LIMIT))
        self.o_stop.setEnabled(t in (self._STOP, self._STOP_LIMIT))
        self.o_trail.setEnabled(t == self._TRAIL)
        self.o_trail_unit.setEnabled(t == self._TRAIL)
        self.o_tp.setEnabled(bracket)
        self.o_sl.setEnabled(bracket)

    def _place(self):
        from tradelab.core.broker import BrokerError
        sym = self.o_symbol.text().strip().upper()
        side = self.o_side.currentText()
        qty = self.o_qty.value()
        otype = self.o_type.currentText()
        try:
            if self.o_bracket.isChecked():
                entry_type = otype if otype in (self._MARKET, self._LIMIT) else self._MARKET
                entry_price = self.o_limit.value() if entry_type == self._LIMIT else None
                order = self.broker.place_bracket(
                    sym, side, qty, entry_type=entry_type, entry_price=entry_price,
                    take_profit=(self.o_tp.value() or None), stop_loss=(self.o_sl.value() or None))
            else:
                limit = self.o_limit.value() if otype in (self._LIMIT, self._STOP_LIMIT) else None
                stop = self.o_stop.value() if otype in (self._STOP, self._STOP_LIMIT) else None
                trail_amount = trail_pct = None
                if otype == self._TRAIL:
                    if self.o_trail_unit.currentText() == "%":
                        trail_pct = self.o_trail.value()
                    else:
                        trail_amount = self.o_trail.value()
                order = self.broker.place_order(sym, side, qty, otype, limit_price=limit,
                                                stop_price=stop, trail_amount=trail_amount,
                                                trail_pct=trail_pct)
        except BrokerError as e:
            QMessageBox.warning(self, "Order rejected", str(e)); return
        if order.status == "REJECTED":
            QMessageBox.warning(self, "Order rejected", order.note or "Could not fill.")
        self.refresh()

    def _cancel_selected(self):
        rows = {idx.row() for idx in self.ord_table.selectionModel().selectedRows()}
        for row in rows:
            item = self.ord_table.item(row, 0)
            if item:
                try:
                    self.broker.cancel_order(int(item.text()))
                except Exception:
                    pass
        self.refresh()

    def _reset(self):
        if QMessageBox.question(self, "Reset paper account",
                                "Wipe all positions, orders and P&L back to the starting "
                                "cash? This cannot be undone.") == QMessageBox.Yes:
            self.broker.reset()
            self.refresh()

    def refresh(self):
        self.broker.poll()  # fill any resting limit orders at the current price
        s = self.broker.account_summary()
        self._summary.setText(
            f"Cash ${s['cash']:,.2f}   |   Positions ${s['positions_value']:,.2f}   |   "
            f"Equity ${s['equity']:,.2f}   |   Realized P&L ${s['realized_pnl']:,.2f}   |   "
            f"Unrealized P&L ${s['unrealized_pnl']:,.2f}   |   Total P&L ${s['total_pnl']:,.2f}")

        positions = self.broker.positions()
        self.pos_table.setRowCount(len(positions))
        for r, p in enumerate(positions):
            try:
                last = self.broker.price(p.symbol)
            except Exception:
                last = p.avg_price
            cells = [p.symbol, f"{p.qty:g}", f"{p.avg_price:.2f}", f"{last:.2f}",
                     f"{p.market_value(last):,.2f}", f"{p.unrealized_pnl(last):,.2f}"]
            for c, val in enumerate(cells):
                self.pos_table.setItem(r, c, QTableWidgetItem(val))

        orders = list(reversed(self.broker.orders()))
        self.ord_table.setRowCount(len(orders))
        for r, o in enumerate(orders):
            cells = [str(o.id), o.symbol, o.side, f"{o.qty:g}", o.order_type,
                     f"{o.limit_price:.2f}" if o.limit_price else "-",
                     f"{o.stop_price:.2f}" if o.stop_price else "-", o.status,
                     f"{o.filled_price:.2f}" if o.filled_price else "-"]
            for c, val in enumerate(cells):
                self.ord_table.setItem(r, c, QTableWidgetItem(val))
