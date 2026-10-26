"""The Dividends tab: the income your book pays."""
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


class _DividendWorker(QThread):
    """Fetches prices (for yields/FX) and dividend histories off the UI thread."""
    done = Signal(object, object, str)   # histories, dividends, error

    def __init__(self, symbols, fx_symbols, period="2y"):
        super().__init__()
        self.symbols = list(symbols)
        self.fx_symbols = list(fx_symbols)
        self.period = period

    def run(self):
        try:
            from tradelab.data.market_data import (get_histories, get_dividends,
                                                   with_latest_prices)
            hist = get_histories(sorted(set(self.symbols) | set(self.fx_symbols)),
                                 self.period, "1d")
            # Yields are read at today's price, not at a close Yahoo is late with.
            hist = with_latest_prices(hist, self.symbols)
            divs = {s: get_dividends(s) for s in self.symbols}
            self.done.emit(hist, divs, "")
        except Exception as exc:
            self.done.emit(None, None, str(exc))


class DividendsPanel(AutoRefresh, QWidget):
    """What your book pays you. Reads the Portfolio tab's holdings and shows the
    income each one generates: annual income, yield at today's price versus the
    yield on what you actually paid, how often it pays, whether the payout is
    growing, and which months the money lands in.

    All numbers come from tradelab.core.dividends (offline-testable). Income is
    reported in the chosen currency (CAD by default) while per-share amounts stay
    native, matching the Analytics tab. Reporting only — it never places orders,
    and it is not financial advice."""

    # Brought up to date when the tab is opened, if stale - see AutoRefresh.
    REFRESH_METHOD = "analyze"
    REFRESH_WORKERS = ("_worker",)
    REFRESH_POLICY = freshness.DAILY

    _TILES = [("annual", "Annual income"), ("monthly", "Average per month"),
              ("yield", "Portfolio yield"), ("oncost", "Yield on cost"),
              ("payers", "Paying holdings")]

    def __init__(self, db: Database, chart=None, cfg=None):
        super().__init__()
        self.db = db
        self.chart = chart
        self.cfg = cfg
        self._worker = None
        self._chart_worker = None
        layout = QVBoxLayout(self)

        layout.addWidget(_hint(
            "The income your holdings actually pay. Reads the Portfolio tab and shows each "
            "position's annual dividend, its yield at today's price versus the yield on what "
            "you paid, how often it pays, whether the payout is growing, and a month-by-month "
            "calendar of when the money arrives. Reporting only — not financial advice."))

        row = QHBoxLayout()
        self.currency = QComboBox(); self.currency.addItems(["CAD", "USD", "Native (mixed)"])
        go = QPushButton("Refresh"); go.clicked.connect(self.analyze)
        row.addWidget(QLabel("Currency")); row.addWidget(self.currency)
        row.addWidget(go); row.addWidget(self.make_freshness_label()); row.addStretch()
        self.status = StatusLabel(); self.status.setStyleSheet("color:#8a9099;")
        row.addWidget(self.status)
        layout.addLayout(row)

        self.headline = QLabel("Add holdings in the Portfolio tab, then click Refresh.")
        self.headline.setWordWrap(True)
        self.headline.setStyleSheet("font-size:14px;")
        layout.addWidget(self.headline)

        tiles = QHBoxLayout()
        self.metrics = {}
        for key, label in self._TILES:
            box = QVBoxLayout()
            cap = QLabel(label); cap.setStyleSheet("color:#8a9099; font-size:12px;")
            val = QLabel("—"); val.setStyleSheet("font-size:18px; font-weight:bold;")
            box.addWidget(cap); box.addWidget(val)
            holder = QWidget(); holder.setLayout(box)
            tiles.addWidget(holder)
            self.metrics[key] = val
        layout.addLayout(tiles)

        layout.addWidget(QLabel("Income by holding"))
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Symbol", "Ccy", "Shares", "Pays", "Div/share (yr)", "Annual income",
             "Yield", "On cost", "Growth"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setToolTip("Click a holding to chart it.")
        self.table.cellClicked.connect(self._chart_row)
        self._tips(self.table, {
            4: "Annual dividend per share, in the holding's own currency: the most recent "
               "payment annualized at its frequency (so a recent raise counts immediately).",
            6: "Annual dividend divided by today's price.",
            7: "Annual dividend divided by what you paid — higher than the current yield "
               "when the price has risen since you bought.",
            8: "Change in the average payment versus the prior 12 months.",
        })
        layout.addWidget(self.table)

        layout.addWidget(QLabel("When it arrives"))
        self.calendar = QTableWidget(0, 3)
        self.calendar.setHorizontalHeaderLabels(["Month", "Expected income", "From"])
        self.calendar.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.calendar.verticalHeader().setVisible(False)
        self.calendar.setToolTip("Projected from the months each holding paid in over the "
                                 "last year, at the current rate.")
        layout.addWidget(self.calendar)

        disclaimer = QLabel("Projected from past payments — dividends can be cut or raised "
                            "at any time. Reporting only — not financial advice.")
        disclaimer.setStyleSheet("color:#8a9099; font-size:11px;")
        layout.addWidget(disclaimer)

    @staticmethod
    def _tips(table, tips):
        for col, text in tips.items():
            item = table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(text)

    def showEvent(self, event):
        super().showEvent(event)
        if self.table.rowCount() == 0 and self.db.positions():
            self.analyze()

    def analyze(self):
        from tradelab.core.portfolio_analytics import currency_of, fx_pair_symbol
        if self._worker is not None and self._worker.isRunning():
            return
        self.note_refresh_started()
        positions = self.db.positions()
        if not positions:
            self.headline.setText("No positions yet — add holdings in the Portfolio tab first.")
            return
        self._positions = positions
        choice = self.currency.currentText()
        self._target = None if choice.startswith("Native") else choice
        symbols = sorted({str(p["symbol"]).upper() for p in positions})
        self._fx_pairs = {}
        if self._target:
            for ccy in {currency_of(s) for s in symbols} - {self._target}:
                self._fx_pairs[ccy] = fx_pair_symbol(ccy, self._target)
        self.status.setText(f"Loading dividends for {len(symbols)} holdings…")
        self._worker = _DividendWorker(symbols, self._fx_pairs.values())
        self._worker.done.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, history, divs, err):
        from tradelab.core import dividends as dv, portfolio_analytics as pa
        from tradelab.data.market_data import is_synthetic
        if err or history is None:
            flag_problem(self.status, f"Could not load dividends: {err or 'no data'}")
            return
        self.mark_refreshed()
        self.status.setText("")
        # Same rule as Analytics: never value real money on synthetic fallback data.
        history = {s: df for s, df in history.items()
                   if df is not None and not is_synthetic(df)}
        fx = ({ccy: history.get(sym) for ccy, sym in self._fx_pairs.items()}
              if self._target else None)
        prices = {}
        for sym in {str(p["symbol"]).upper() for p in self._positions}:
            c = pa._close(history.get(sym))
            if c is not None and not c.empty:
                prices[sym] = float(c.iloc[-1])
        data = dv.summarize(self._positions, divs or {}, prices,
                            target_currency=self._target, fx=fx)
        self._render(data)

    def _cell(self, table, r, c, text, colour=None, align_right=True):
        item = QTableWidgetItem(text)
        if align_right:
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if colour:
            item.setForeground(QColor(colour))
        table.setItem(r, c, item)

    def _render(self, d):
        cur = d.get("currency")
        suf = f" {cur}" if cur else ""
        self.headline.setText(d["text"])

        annual = d["total_annual_income"]
        self.metrics["annual"].setText(f"${annual:,.0f}{suf}" if annual else "—")
        self.metrics["annual"].setStyleSheet("font-size:18px; font-weight:bold; color:#3fb950;"
                                             if annual else "font-size:18px; font-weight:bold;")
        avg = d["monthly_average"]
        self.metrics["monthly"].setText(f"${avg:,.0f}{suf}" if avg else "—")
        py = d["portfolio_yield_pct"]
        self.metrics["yield"].setText(f"{py:.2f}%" if py is not None else "—")
        yoc = d["portfolio_yield_on_cost_pct"]
        self.metrics["oncost"].setText(f"{yoc:.2f}%" if yoc is not None else "—")
        self.metrics["payers"].setText(f"{d['payers']} of {len(d['holdings'])}")

        rows = d["holdings"]
        self.table.setRowCount(len(rows))
        for r, h in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(h["symbol"]))
            ccy = QTableWidgetItem(h.get("currency", ""))
            ccy.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 1, ccy)
            self._cell(self.table, r, 2, f"{h['shares']:g}")
            freq = QTableWidgetItem(h["frequency_label"])
            freq.setTextAlignment(Qt.AlignCenter)
            if not h["pays"]:
                freq.setForeground(QColor("#8a9099"))
            self.table.setItem(r, 3, freq)
            ps = h["per_share_annual"]
            self._cell(self.table, r, 4, f"${ps:,.3f}" if ps else "—")
            inc = h["annual_income"]
            self._cell(self.table, r, 5, f"${inc:,.0f}" if inc else "—",
                       "#3fb950" if inc else None)
            cy = h["current_yield_pct"]
            self._cell(self.table, r, 6, f"{cy:.2f}%" if cy is not None else "—")
            yc = h["yield_on_cost_pct"]
            # Green when your cost basis yields more than today's buyer gets.
            better = (yc is not None and cy is not None and yc > cy)
            self._cell(self.table, r, 7, f"{yc:.2f}%" if yc is not None else "—",
                       "#3fb950" if better else None)
            g = h["growth_pct"]
            self._cell(self.table, r, 8, f"{g:+.1f}%" if g is not None else "—",
                       ("#3fb950" if g >= 0 else "#e5534b") if g is not None else None)
        self.table.resizeColumnsToContents()

        cal = d["calendar"]
        self.calendar.setRowCount(len(cal))
        peak = max((m["amount"] for m in cal), default=0)
        for r, m in enumerate(cal):
            name = QTableWidgetItem(m["name"])
            self.calendar.setItem(r, 0, name)
            amt = m["amount"]
            item = QTableWidgetItem(f"${amt:,.0f}{suf}" if amt else "—")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if amt and peak:
                # Shade the heaviest months so the rhythm is visible at a glance.
                item.setBackground(QColor(hm.color_for_change(amt / peak * 3.0)))
                item.setForeground(QColor("#0b0e14"))
            self.calendar.setItem(r, 1, item)
            self.calendar.setItem(r, 2, QTableWidgetItem(", ".join(m["symbols"]) or "—"))
        self.calendar.resizeColumnsToContents()

        notes = []
        if d.get("non_payers"):
            notes.append("No dividend: " + ", ".join(d["non_payers"]) + ".")
        if d.get("fx_missing"):
            notes.append("No FX rate for " + ", ".join(d["fx_missing"])
                         + " — shown in native currency.")
        self.status.setText("  ".join(notes))

    def _chart_row(self, row, _col):
        if self.chart is None or self.cfg is None or row < 0:
            return
        item = self.table.item(row, 0)
        sym = (item.text().strip() if item else "")
        if not sym:
            return
        self.status.setText(f"Charting {sym}…")
        self._chart_worker = _HistoryWorker(sym, self.cfg.period, self.cfg.interval)
        self._chart_worker.done.connect(self._on_chart_loaded)
        self._chart_worker.start()

    def _on_chart_loaded(self, symbol, df, err):
        if err or df is None or getattr(df, "empty", False):
            flag_problem(self.status, f"Could not chart {symbol}: {err or 'no data'}")
            return
        try:
            self.chart.plot(symbol, df, self.cfg)
            self.status.setText(f"Charted {symbol}.")
        except Exception as exc:
            flag_problem(self.status, f"Could not chart {symbol}: {exc}")

    def shutdown(self):
        for attr in ("_worker", "_chart_worker"):
            worker = getattr(self, attr, None)
            if worker is None:
                continue
            try:
                worker.done.disconnect()
            except (RuntimeError, TypeError):
                pass
            worker.wait(3000)
            setattr(self, attr, None)
