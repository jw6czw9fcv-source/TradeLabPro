"""The Alerts tab: price conditions watched in the background."""
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
from tradelab.ui.common import (_build_condition_row, _row_to_condition)  # noqa: F401

log = get_logger(__name__)


class AlertCheckWorker(QThread):
    """Evaluates a snapshot of alerts off the UI thread (each check hits the
    network via get_history). Mutates the passed Alert objects' edge-detection
    state in place and emits the events that fired this pass."""
    done = Signal(object)  # list[AlertEvent]

    def __init__(self, alerts):
        super().__init__()
        self.alerts = alerts

    def run(self):
        try:
            from tradelab.core.alerts import evaluate_alerts
            events = evaluate_alerts(self.alerts)
        except BaseException:
            events = []
        try:
            self.done.emit(events)
        except RuntimeError:
            pass  # UI closed mid-check


class AlertsPanel(QWidget):
    """Price / indicator alerts. Build a condition on a symbol (the same
    FilterCondition the Scanner and Strategy Builder use); a background poller
    checks it on an interval and fires a desktop notification the moment the
    condition crosses from false to true. Simulated/analysis tool - alerts
    never place orders."""

    def __init__(self, symbol_provider=None):
        super().__init__()
        # symbol_provider() -> list[str] (e.g. the watchlist) for quick-add.
        self._symbol_provider = symbol_provider
        self.store = AlertStore()
        self._worker = None
        self._tray = None
        self._init_tray()

        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Get notified when a symbol meets a condition. Alerts are edge-triggered: "
            "'RSI Below 30' fires once as it drops through 30, not every check. "
            "Analysis tool only - alerts never place orders."))

        # --- builder ------------------------------------------------------
        builder = QGroupBox("New alert")
        bl = QVBoxLayout(builder)
        top = QHBoxLayout()
        self.symbol_edit = QLineEdit(); self.symbol_edit.setPlaceholderText("Symbol e.g. AAPL")
        self.symbol_edit.setMaximumWidth(160)
        top.addWidget(QLabel("Symbol")); top.addWidget(self.symbol_edit)
        if self._symbol_provider:
            self.watch_pick = QComboBox(); self.watch_pick.setMinimumWidth(120)
            self.watch_pick.setToolTip("Pick a symbol from your watchlist")
            self.watch_pick.activated.connect(self._pick_watch_symbol)
            top.addWidget(QLabel("from list")); top.addWidget(self.watch_pick)
        self.mode = QComboBox(); self.mode.addItems(["recurring", "once"])
        self.mode.setToolTip("recurring: re-arms and can fire again on the next crossing.\nonce: fires a single time, then turns itself off.")
        top.addWidget(QLabel("Mode")); top.addWidget(self.mode)
        self.interval_sel = QComboBox(); self.interval_sel.addItems(["1m","5m","15m","30m","60m","1h","1d"]); self.interval_sel.setCurrentText("1d")
        self.interval_sel.setToolTip("Bar interval the condition is evaluated on.")
        top.addWidget(QLabel("Bars")); top.addWidget(self.interval_sel)
        top.addStretch()
        bl.addLayout(top)

        cond_row = QHBoxLayout()
        cond_row.addWidget(QLabel("When"))
        self._cond_widgets = None
        row_widget, self._cond_widgets = _build_condition_row(
            FilterCondition(field="price", operator="Above", value1=0.0),
            on_change=None, on_remove=lambda r: None, removable=False)
        cond_row.addWidget(row_widget, 1)
        add_btn = QPushButton("Add alert"); add_btn.clicked.connect(self.add_alert)
        cond_row.addWidget(add_btn)
        bl.addLayout(cond_row)
        layout.addWidget(builder)

        # --- alert table --------------------------------------------------
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Symbol", "Condition", "Mode", "Status", "Last price", "Fired"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        controls = QHBoxLayout()
        self.toggle_btn = QPushButton("Enable / Disable"); self.toggle_btn.clicked.connect(self.toggle_selected)
        remove_btn = QPushButton("Remove"); remove_btn.clicked.connect(self.remove_selected)
        check_btn = QPushButton("Check now"); check_btn.clicked.connect(lambda: self.run_check(manual=True))
        controls.addWidget(self.toggle_btn); controls.addWidget(remove_btn); controls.addWidget(check_btn)
        controls.addStretch()
        self.auto_chk = QCheckBox("Auto-check every")
        self.auto_secs = QSpinBox(); self.auto_secs.setRange(15, 3600); self.auto_secs.setValue(60); self.auto_secs.setSuffix(" s")
        self.auto_chk.toggled.connect(self._on_auto_toggled)
        self.auto_secs.valueChanged.connect(self._on_auto_interval_changed)
        controls.addWidget(self.auto_chk); controls.addWidget(self.auto_secs)
        layout.addLayout(controls)

        layout.addWidget(QLabel("Triggered alerts:"))
        self.log = QListWidget(); self.log.setMaximumHeight(150)
        layout.addWidget(self.log)
        self.status = StatusLabel("Ready.")
        layout.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.run_check(manual=False))

        self.refresh_table()
        self._refresh_watch_pick()

    # --- tray / notifications --------------------------------------------
    def _init_tray(self):
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                icon = self.style().standardIcon(QStyle.SP_MessageBoxInformation)
                self._tray = QSystemTrayIcon(icon, self)
                self._tray.setToolTip(f"{APP_NAME} alerts")
                self._tray.show()
        except Exception:
            self._tray = None

    def _notify(self, title, message):
        if self._tray is not None:
            try:
                self._tray.showMessage(title, message, QSystemTrayIcon.Information, 8000)
                return
            except Exception:
                pass
        # Fallback: at least surface it in the status bar area.
        self.status.setText(message)

    # --- builder helpers --------------------------------------------------
    def _refresh_watch_pick(self):
        if not self._symbol_provider or not hasattr(self, "watch_pick"):
            return
        try:
            syms = list(self._symbol_provider() or [])
        except Exception:
            syms = []
        self.watch_pick.clear()
        self.watch_pick.addItem("—")
        self.watch_pick.addItems(syms)

    def _pick_watch_symbol(self, idx):
        if idx > 0:
            self.symbol_edit.setText(self.watch_pick.currentText())

    def add_alert(self):
        symbol = self.symbol_edit.text().strip().upper()
        if not symbol:
            flag_problem(self.status, "Enter a symbol first.")
            return
        condition = _row_to_condition(self._cond_widgets)
        alert = Alert(symbol=symbol, condition=condition,
                      trigger_mode=self.mode.currentText(),
                      interval=self.interval_sel.currentText())
        self.store.add(alert)
        self.symbol_edit.clear()
        self.refresh_table()
        self.status.setText(f"Added alert: {alert.label()}")

    # --- table ------------------------------------------------------------
    def refresh_table(self):
        alerts = self.store.all()
        self.table.setRowCount(len(alerts))
        for r, a in enumerate(alerts):
            cells = [a.symbol, a.condition.label(), a.trigger_mode, a.status(),
                     ("" if a.last_price is None else f"{a.last_price:,.2f}"),
                     str(a.trigger_count)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, a.id)
                if c == 3:  # colour the status
                    if a.status() == "Triggered":
                        item.setForeground(QColor("#f0a020"))
                    elif a.status() == "Off":
                        item.setForeground(QColor("#8b98a5"))
                    else:
                        item.setForeground(QColor("#3fb950"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        enabled = sum(1 for a in alerts if a.enabled)
        self.status.setText(f"{len(alerts)} alerts ({enabled} active).")

    def _selected_ids(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), 0)
            if item:
                ids.append(item.data(Qt.UserRole))
        return ids

    def toggle_selected(self):
        for aid in self._selected_ids():
            a = self.store.get(aid)
            if a:
                a.enabled = not a.enabled
                if a.enabled:
                    a.armed = True  # re-arm when switched back on
        self.store.save()
        self.refresh_table()

    def remove_selected(self):
        for aid in self._selected_ids():
            self.store.remove(aid)
        self.refresh_table()

    # --- checking ---------------------------------------------------------
    def _on_auto_toggled(self, on):
        if on:
            self._timer.start(self.auto_secs.value() * 1000)
            self.run_check(manual=False)
        else:
            self._timer.stop()

    def _on_auto_interval_changed(self, secs):
        if self._timer.isActive():
            self._timer.start(secs * 1000)

    def run_check(self, manual=False):
        if self._worker is not None and self._worker.isRunning():
            return  # a check is already in flight
        alerts = [a for a in self.store.all() if a.enabled]
        if not alerts:
            if manual:
                self.status.setText("No active alerts to check.")
            return
        self.status.setText("Checking alerts…")
        self._worker = AlertCheckWorker(alerts)
        self._worker.done.connect(self._on_check_done)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    def _clear_worker(self):
        self._worker = None

    def _on_check_done(self, events):
        self.store.save()  # persist mutated edge-state / trigger counts
        for ev in events:
            stamp = time.strftime("%H:%M:%S", time.localtime(ev.timestamp))
            self.log.insertItem(0, f"[{stamp}] {ev.message}")
            self._notify(f"{APP_NAME} alert", ev.message)
        if events:
            self.status.setText(f"{len(events)} alert(s) triggered.")
        self.refresh_table()

    def shutdown(self):
        """Stop the timer and any running worker cleanly on app close."""
        try:
            self._timer.stop()
        except Exception:
            pass
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        if self._tray is not None:
            self._tray.hide()
