"""The Retirement tab: a workplace plan TradeLab cannot connect to."""
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


class _BenchmarkWorker(QThread):
    """Fetches the index histories a plan's funds are compared against.

    Five years because a statement can be years old — the window is whatever
    the member's two statements span, and an index that only reaches back a
    year would silently drop the comparison for the older ones."""
    done = Signal(object, str)   # {symbol: DataFrame}, error

    def __init__(self, symbols, period="5y"):
        super().__init__()
        self.symbols = sorted({s for s in symbols if s})
        self.period = period

    def run(self):
        try:
            if not self.symbols:
                self.done.emit({}, "")
                return
            self.done.emit(get_histories(self.symbols, self.period, "1d"), "")
        except Exception as exc:
            self.done.emit(None, str(exc))


class RetirementPanel(AutoRefresh, QWidget):
    """A group plan the app cannot reach: a workplace RRSP, a pension.

    There is no ticker for a group plan's funds — the unit values exist only
    behind the plan administrator's login. So this tab is built around pasting
    what the statement says, a couple of times a year, and getting back the one
    thing the statement never shows: how each fund did *against the others*.

    Two returns are reported side by side because they answer different
    questions. "Fund return" is the unit value moving, which contributions
    cannot flatter — that is the column to read when comparing funds. "Your
    return" is an XIRR over what you actually paid in and when.

    Reporting only. It never says which fund to hold, and the index comparison
    is stated as a fact about two numbers, not as a recommendation."""

    # Brought up to date when the tab is opened, if stale - see AutoRefresh.
    REFRESH_METHOD = "refresh"
    REFRESH_WORKERS = ("_worker",)
    REFRESH_POLICY = freshness.DAILY

    _TILES = [("value", "Plan value"), ("gain", "Gain since first statement"),
              ("best", "Best fund"), ("worst", "Weakest fund"),
              ("funds", "Funds")]

    _COLS = ["Fund", "Weight", "Units", "Unit value", "Value", "Fund return",
             "Over", "Your return", "Index", "vs index"]
    BENCH_COL = 8

    def __init__(self, chart=None, cfg=None, book=None):
        super().__init__()
        self.chart = chart
        self.cfg = cfg
        from tradelab.core.retirement import RetirementBook
        self.book = book if book is not None else RetirementBook()
        self._worker = None
        self._benchmarks = {}
        self._parsed = None
        self._loading = False
        layout = QVBoxLayout(self)

        layout.addWidget(_hint(
            "A workplace plan the app can't connect to — a group RRSP, a pension. Paste the "
            "fund table from your statement and each fund is measured against the others and "
            "against an index. Two statement dates are what turn a balance into a return, so "
            "the first paste starts the clock and the next one answers the question. "
            "Reporting only — not financial advice."))

        row = QHBoxLayout()
        self.accounts = QComboBox()
        self.accounts.currentIndexChanged.connect(lambda _i: self.refresh())
        new = QPushButton("New plan"); new.clicked.connect(self._new_account)
        rename = QPushButton("Rename"); rename.clicked.connect(self._rename_account)
        delete = QPushButton("Delete"); delete.clicked.connect(self._delete_account)
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        row.addWidget(QLabel("Plan")); row.addWidget(self.accounts, 1)
        for btn in (new, rename, delete, refresh):
            row.addWidget(btn)
        row.addStretch()
        self.status = StatusLabel(); self.status.setStyleSheet(f"color:{theme.MUTED};")
        row.addWidget(self.status)
        layout.addLayout(row)

        self.headline = QLabel("Create a plan, then paste your statement below.")
        self.headline.setWordWrap(True)
        self.headline.setStyleSheet("font-size:14px;")
        layout.addWidget(self.headline)

        tiles = QHBoxLayout()
        self.metrics = {}
        for key, label in self._TILES:
            box = QVBoxLayout()
            cap = QLabel(label); cap.setStyleSheet(f"color:{theme.MUTED}; font-size:12px;")
            val = QLabel("—"); val.setStyleSheet("font-size:18px; font-weight:bold;")
            val.setWordWrap(True)
            box.addWidget(cap); box.addWidget(val)
            holder = QWidget(); holder.setLayout(box)
            tiles.addWidget(holder)
            self.metrics[key] = val
        layout.addLayout(tiles)

        layout.addWidget(self._build_paste_box())
        layout.addWidget(self._build_published_box())

        layout.addWidget(QLabel("Your funds"))
        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        # Everything is read-only except the index column, whose items opt back
        # in per row: picking what a fund is judged against is the one thing on
        # this table the user is meant to change.
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_item_changed)
        self._tips(self.table, {
            5: "How the fund itself did: the change in its unit value, which your "
               "contributions can't move. This is the column to compare funds on.",
            6: "The window those two statements span. A short window is a real "
               "number but a weak signal.",
            7: "How your money did: an XIRR over what you paid in and when, "
               "starting from your first statement as the opening stake.",
            8: "Double-click to set the index this fund is judged against "
               "(a Yahoo symbol, e.g. XIC.TO). Clear it to drop the comparison.",
            9: "Fund return minus the index's return over the same days. "
               "A fact about two numbers — not a recommendation.",
        })
        layout.addWidget(self.table)

        self.chart_widget = RebasedChartWidget()
        layout.addWidget(self.chart_widget)

        layout.addWidget(self._build_flows_box())

        self.needs = QLabel()
        self.needs.setWordWrap(True)
        self.needs.setStyleSheet(f"color:{theme.NEUTRAL}; font-size:12px;")
        layout.addWidget(self.needs)

        disclaimer = QLabel(
            "Your own figures, recalculated — not a statement from your plan. "
            + theme.NOT_ADVICE)
        disclaimer.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(disclaimer)

        self._reload_accounts()

    # --- construction helpers ------------------------------------------------

    def _build_paste_box(self) -> QGroupBox:
        box = QGroupBox("Enter a statement")
        outer = QVBoxLayout(box)
        outer.addWidget(_hint(
            "Copy the fund table straight off your plan's website and paste it here — one "
            "fund per line. Two numbers on a line are read as units and unit value; one is "
            "read as a balance. Category headings are ignored."))
        self.paste = QTextEdit()
        self.paste.setPlaceholderText(
            "Indiciel équilibré (Mackenzie)\t23,875174\t504,68\t12 049,25\n"
            "Expansion Canada (Fidelity)\t98,714857\t172,07\t16 985,78")
        self.paste.setMaximumHeight(110)
        outer.addWidget(self.paste)

        row = QHBoxLayout()
        self.paste_date = QLineEdit()
        self.paste_date.setPlaceholderText("YYYY-MM-DD")
        self.paste_date.setMaximumWidth(120)
        read = QPushButton("Read"); read.clicked.connect(self._read_paste)
        self.save_btn = QPushButton("Save to plan")
        self.save_btn.clicked.connect(self._save_paste)
        self.save_btn.setEnabled(False)
        row.addWidget(QLabel("Statement date")); row.addWidget(self.paste_date)
        row.addWidget(read); row.addWidget(self.save_btn)
        row.addStretch()
        outer.addLayout(row)

        # Nothing is written until the user has seen what was understood.
        self.preview = QLabel("Paste a statement and click Read.")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        outer.addWidget(self.preview)
        return box

    def _build_published_box(self) -> QGroupBox:
        """The plan's own published returns — the better comparison whenever a
        fact sheet exists, because it uses the fund's real benchmark over
        horizons no member could rebuild from statements."""
        box = QGroupBox("Published fund returns (from your fund fact sheets)")
        outer = QVBoxLayout(box)
        outer.addWidget(_hint(
            "Your plan publishes each fund against its own benchmark. Paste a sheet's "
            "'compound returns' table — the header row plus the Fonds/Indice rows — and pick "
            "the fund it belongs to. These returns are struck before the plan's investment "
            "management fee, so set that fee to see what's left after what you pay."))

        row = QHBoxLayout()
        self.published_fund = QComboBox()
        read = QPushButton("Read sheet"); read.clicked.connect(self._read_published)
        row.addWidget(QLabel("Fund")); row.addWidget(self.published_fund, 1)
        row.addWidget(read)
        row.addWidget(QLabel("Plan fee %"))
        self.fee_input = QLineEdit(); self.fee_input.setMaximumWidth(70)
        self.fee_input.setPlaceholderText("1.75")
        self.fee_input.setToolTip(
            "The plan's annual investment management fee, which fund fact sheet "
            "returns are struck before. Applied to every fund unless one carries "
            "its own.")
        self.fee_input.editingFinished.connect(self._set_fee)
        row.addWidget(self.fee_input)
        row.addWidget(QLabel("Horizon"))
        self.horizon = QComboBox()
        self.horizon.currentIndexChanged.connect(lambda _i: self._render_published())
        row.addWidget(self.horizon)
        row.addStretch()
        outer.addLayout(row)

        # What the fees cost, against a lower fee - the same return before
        # fees for both, so the gap is the fees alone.
        drag_row = QHBoxLayout()
        drag_row.addWidget(QLabel("Compare the fees with"))
        self.low_fee = QDoubleSpinBox(); self.low_fee.setRange(0, 3); self.low_fee.setDecimals(2)
        self.low_fee.setSingleStep(0.05); self.low_fee.setSuffix(" %"); self.low_fee.setValue(0.25)
        self.low_fee.setToolTip("A low-cost index fund's yearly fee - yours to set.")
        drag_row.addWidget(self.low_fee)
        drag_row.addWidget(QLabel("at a return before fees of"))
        self.gross_return = QDoubleSpinBox(); self.gross_return.setRange(0, 15)
        self.gross_return.setDecimals(1); self.gross_return.setSuffix(" %")
        self.gross_return.setValue(5.0)
        drag_row.addWidget(self.gross_return)
        drag_row.addStretch()
        outer.addLayout(drag_row)
        self.fee_drag_line = QLabel("")
        self.fee_drag_line.setWordWrap(True)
        outer.addWidget(self.fee_drag_line)
        self.low_fee.valueChanged.connect(lambda _v: self._render_fee_drag())
        self.gross_return.valueChanged.connect(lambda _v: self._render_fee_drag())

        self.published_text = QTextEdit()
        self.published_text.setMaximumHeight(90)
        self.published_text.setPlaceholderText(
            "Rendements composés au 31 mars 2026\n"
            "            3 mois   1 an     2 ans**  3 ans**  4 ans**  5 ans**  10 ans**\n"
            "Fonds       5,15 %   40,99 %  26,51 %  30,97 %  20,59 %  17,06 %  18,47 %\n"
            "Indice      1,99 %   28,46 %  21,92 %  20,81 %  14,18 %  15,07 %  13,42 %")
        outer.addWidget(self.published_text)

        self.published_line = QLabel("")
        self.published_line.setWordWrap(True)
        self.published_line.setStyleSheet("font-size:13px;")
        outer.addWidget(self.published_line)

        self.published_table = QTableWidget(0, 7)
        self.published_table.setHorizontalHeaderLabels(
            ["Fund", "Weight", "Fund", "Its benchmark", "Excess", "Fee", "After fee"])
        self.published_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.published_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.published_table.verticalHeader().setVisible(False)
        self._tips(self.published_table, {
            2: "The return your plan published for this fund, over the chosen horizon. "
               "Anything past a year is annualized on the sheet itself.",
            3: "The benchmark the fund itself names — often a blend, and always a "
               "better comparison than a stand-in ETF.",
            4: "Fund minus its benchmark, as published: before the fee you pay.",
            6: "The same excess after the plan's annual fee. A fund that beats its "
               "index by less than it charges did not beat it for you.",
        })
        outer.addWidget(self.published_table)
        return box

    def _build_flows_box(self) -> QGroupBox:
        box = QGroupBox("Contributions and withdrawals")
        outer = QVBoxLayout(box)
        outer.addWidget(_hint(
            "Only needed for 'Your return'. Money moved before your first statement is "
            "already inside that balance and should not be entered again."))
        row = QHBoxLayout()
        self.flow_date = QLineEdit(); self.flow_date.setPlaceholderText("YYYY-MM-DD")
        self.flow_date.setMaximumWidth(120)
        self.flow_amount = QLineEdit(); self.flow_amount.setPlaceholderText("2 500,00")
        self.flow_amount.setMaximumWidth(120)
        self.flow_kind = QComboBox()
        self.flow_kind.addItems(["Contribution (you)", "Employer", "Withdrawal"])
        self.flow_fund = QComboBox()
        add = QPushButton("Add"); add.clicked.connect(self._add_flow)
        remove = QPushButton("Remove selected"); remove.clicked.connect(self._remove_flow)
        for w in (QLabel("Date"), self.flow_date, QLabel("Amount"), self.flow_amount,
                  self.flow_kind, QLabel("into"), self.flow_fund, add, remove):
            row.addWidget(w)
        row.addStretch()
        outer.addLayout(row)

        self.flows_table = QTableWidget(0, 4)
        self.flows_table.setHorizontalHeaderLabels(["Date", "Fund", "Kind", "Amount"])
        self.flows_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.flows_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.flows_table.verticalHeader().setVisible(False)
        self.flows_table.setMaximumHeight(150)
        outer.addWidget(self.flows_table)
        return box

    @staticmethod
    def _tips(table, tips):
        for col, text in tips.items():
            item = table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(text)

    @staticmethod
    def _fit_table(table, max_rows: int = 14):
        """Grow a table to fit its rows instead of scrolling inside a stub.

        A QTableWidget defaults to a height that shows two or three rows, and
        the tab is already inside a scroll area — so a seven-fund plan ended up
        as a seven-row table you had to scroll a 60px window to read, inside a
        page that scrolls perfectly well itself. Capped so a long plan still
        can't push everything below it off the screen."""
        rows = min(table.rowCount(), max_rows)
        header = table.horizontalHeader().height()
        body = sum(table.rowHeight(r) for r in range(rows)) if rows else 0
        table.setMinimumHeight(header + body + (table.frameWidth() * 2) + 4)

    # --- plan selection ------------------------------------------------------

    def _reload_accounts(self, select_id: str = None):
        self._loading = True
        self.accounts.clear()
        for account in self.book.accounts:
            self.accounts.addItem(account.name, account.id)
        self._loading = False
        if select_id:
            index = self.accounts.findData(select_id)
            if index >= 0:
                self.accounts.setCurrentIndex(index)
        self.refresh()

    def current_account(self):
        account_id = self.accounts.currentData()
        return self.book.account(account_id) if account_id else None

    def _new_account(self):
        name, ok = QInputDialog.getText(self, "New plan", "Name",
                                        text="Group RRSP")
        if not ok or not name.strip():
            return
        from tradelab.core.retirement import Account
        account = self.book.add_account(Account(name=name.strip()))
        self._reload_accounts(account.id)

    def _rename_account(self):
        account = self.current_account()
        if account is None:
            return
        name, ok = QInputDialog.getText(self, "Rename plan", "Name", text=account.name)
        if not ok or not name.strip():
            return
        account.name = name.strip()
        self.book.save()
        self._reload_accounts(account.id)

    def _delete_account(self):
        account = self.current_account()
        if account is None:
            return
        confirm = QMessageBox.question(
            self, "Delete plan",
            f"Delete '{account.name}' and every statement recorded in it?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        self.book.remove_account(account.id)
        self._reload_accounts()

    def _ensure_account(self):
        """A first paste shouldn't be refused for want of a plan to put it in."""
        account = self.current_account()
        if account is not None:
            return account
        from tradelab.core.retirement import Account
        account = self.book.add_account(Account(name="Group RRSP"))
        self._reload_accounts(account.id)
        return self.current_account()

    # --- entering a statement -------------------------------------------------

    def _read_paste(self):
        from tradelab.core import retirement as rt
        text = self.paste.toPlainText().strip()
        if not text:
            self.preview.setText("Nothing pasted yet.")
            self.save_btn.setEnabled(False)
            return
        on = rt._parse_date(self.paste_date.text().strip())
        self._parsed = rt.parse_statement(text, on=on)
        rows = self._parsed["rows"]
        if not rows:
            self.preview.setText("No fund lines found — every line needs a name and "
                                 "at least one number.")
            self.save_btn.setEnabled(False)
            return
        self.paste_date.setText(self._parsed["date"])
        total = sum(r["value"] or 0 for r in rows)
        priced = sum(1 for r in rows if r["unit_value"])
        lines = [f"{len(rows)} funds dated {self._parsed['date']}, "
                 f"${total:,.2f} in total; {priced} with unit values."]
        for r in rows[:12]:
            if r["unit_value"]:
                lines.append(f"  {r['name']}: {r['units']:,.6f} × ${r['unit_value']:,.2f}"
                             f" = ${r['value']:,.2f}")
            else:
                lines.append(f"  {r['name']}: ${r['value']:,.2f}")
        if self._parsed["skipped"]:
            lines.append("Ignored: " + "; ".join(self._parsed["skipped"][:5]))
        self.preview.setText("\n".join(lines))
        self.save_btn.setEnabled(True)

    def _save_paste(self):
        if not self._parsed:
            return
        account = self._ensure_account()
        if account is None:
            return
        result = self.book.apply_statement(account, self._parsed["rows"])
        parts = []
        if result["added"]:
            parts.append(f"{len(result['added'])} funds added")
        if result["updated"]:
            parts.append(f"{len(result['updated'])} updated")
        self.status.setText(", ".join(parts) or "Nothing to save.")
        self.paste.clear()
        self.preview.setText("Saved.")
        self.save_btn.setEnabled(False)
        self._parsed = None
        self.refresh()

    # --- published returns ----------------------------------------------------

    def _read_published(self):
        from tradelab.core import retirement as rt
        account = self.current_account()
        if account is None:
            self.status.setText("Create a plan first.")
            return
        fund = account.fund(self.published_fund.currentData() or "")
        if fund is None:
            flag_problem(self.status, "Pick the fund this sheet belongs to.")
            return
        out = rt.parse_published(self.published_text.toPlainText())
        if not out["records"]:
            self.status.setText(out["reason"] or "Could not read that sheet.")
            return
        fund.set_published(out["records"])
        self.book.save()
        self.published_text.clear()
        self.status.setText(f"{len(out['records'])} published returns saved for "
                            f"{fund.name} ({out['as_of']}).")
        self.refresh()

    def _set_fee(self):
        from tradelab.core import retirement as rt
        account = self.current_account()
        if account is None:
            return
        text = self.fee_input.text().strip()
        fee = rt.parse_number(text) if text else None
        if fee == account.fee_pct:
            return
        account.fee_pct = fee
        self.book.save()
        self.refresh()

    def _render_published(self):
        from tradelab.core import retirement as rt
        if self._loading:
            return
        account = self.current_account()
        if account is None:
            self.published_table.setRowCount(0)
            self.published_line.setText("")
            return
        horizon = self.horizon.currentData() or "1y"
        rows = rt.published_rows(account, horizon)
        plan = rt.plan_published(account, horizon)
        self.published_line.setText(plan["text"])

        self.published_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            name = QTableWidgetItem(row["name"])
            if row["as_of"]:
                name.setToolTip(f"Published as at {row['as_of']}.")
            self.published_table.setItem(r, 0, name)
            weight = row["weight_pct"]
            self._cell(self.published_table, r, 1,
                       f"{weight:.1f}%" if weight is not None else "—")
            fund_pct = row["fund_pct"]
            if fund_pct is None:
                for col in (2, 3, 4, 5, 6):
                    item = self._cell(self.published_table, r, col, "—", theme.MUTED)
                    if col == 2:
                        item.setToolTip("No fund fact sheet on file for this fund.")
                continue
            self._cell(self.published_table, r, 2, f"{fund_pct:+.2f}%",
                       theme.pnl_color(fund_pct))
            index_pct = row["index_pct"]
            self._cell(self.published_table, r, 3,
                       f"{index_pct:+.2f}%" if index_pct is not None else "—")
            excess = row["excess_pct"]
            self._cell(self.published_table, r, 4,
                       f"{excess:+.2f} pp" if excess is not None else "—",
                       theme.pnl_color(excess) if excess is not None else None)
            fee = row["fee_pct"]
            self._cell(self.published_table, r, 5,
                       f"{fee:.2f}%" if fee is not None else "—", theme.MUTED)
            net = row["net_excess_pct"]
            if net is None:
                item = self._cell(self.published_table, r, 6, "—", theme.MUTED)
                item.setToolTip("Set the plan fee above — an annual fee is not "
                                "charged against a 3-month return."
                                if horizon == "3m" else "Set the plan fee above.")
            else:
                self._cell(self.published_table, r, 6, f"{net:+.2f} pp",
                           theme.pnl_color(net))
        self.published_table.resizeColumnsToContents()
        self._fit_table(self.published_table)

    def _render_fee_drag(self):
        from tradelab.core import retirement as rt
        account = self.current_account()
        drag = rt.fee_drag(account, self.low_fee.value(), self.gross_return.value()) \
            if account else None
        if drag is None:
            self.fee_drag_line.setText(
                "Set the plan fee above to see what it costs against a lower fee."
                if account and account.value else "")
            return
        if drag["fee_pct"] <= drag["low_fee_pct"]:
            self.fee_drag_line.setText(
                f"The plan's fee ({drag['fee_pct']:.2f}%) is no higher than {drag['low_fee_pct']:.2f}% "
                "- nothing to gain on fees.")
            return
        g10, g20 = drag["gaps"][10], drag["gaps"][20]
        self.fee_drag_line.setText(
            f"<b>Fees:</b> {drag['fee_pct']:.2f}% a year on ${drag['value']:,.0f} is about "
            f"${drag['per_year_now']:,.0f} a year more than at {drag['low_fee_pct']:.2f}%. Grown at "
            f"{drag['gross_pct']:.1f}% before fees with nothing added or taken out, the gap would be "
            f"about <b>${g10:,.0f} after 10 years</b> and <b>${g20:,.0f} after 20</b>. An "
            "illustration on these assumptions - moving a group plan can have conditions "
            "(employer contributions, transfer fees); ask before deciding. Not advice.")

    def _sync_published_controls(self, d):
        """Keep the fund and horizon pickers in step with what is on file,
        without letting a rebuild fire the signals that trigger another render."""
        from tradelab.core import retirement as rt
        account = self.current_account()
        self._loading = True
        current_fund = self.published_fund.currentData()
        self.published_fund.clear()
        for fund in (account.funds if account else []):
            self.published_fund.addItem(fund.name, fund.id)
        index = self.published_fund.findData(current_fund)
        if index >= 0:
            self.published_fund.setCurrentIndex(index)

        horizons = d.get("horizons") or ["1y"]
        current_horizon = self.horizon.currentData()
        self.horizon.clear()
        for horizon in horizons:
            self.horizon.addItem(rt.HORIZON_LABELS.get(horizon, horizon), horizon)
        index = self.horizon.findData(current_horizon)
        self.horizon.setCurrentIndex(index if index >= 0 else
                                     max(0, self.horizon.findData("1y")))
        fee = account.fee_pct if account else None
        self.fee_input.setText("" if fee is None else f"{fee:g}")
        self._loading = False
        self._render_fee_drag()

    # --- contributions --------------------------------------------------------

    def _add_flow(self):
        from tradelab.core import retirement as rt
        account = self.current_account()
        if account is None:
            self.status.setText("Create a plan first.")
            return
        fund = account.fund(self.flow_fund.currentData() or "")
        if fund is None:
            flag_problem(self.status, "Pick the fund the money went into.")
            return
        when = rt._parse_date(self.flow_date.text().strip())
        amount = rt.parse_number(self.flow_amount.text())
        if when is None or not amount:
            self.status.setText("A contribution needs a date (YYYY-MM-DD) and an amount.")
            return
        kind = {0: rt.CONTRIBUTION, 1: rt.EMPLOYER,
                2: rt.WITHDRAWAL}[self.flow_kind.currentIndex()]
        fund.add_flow(rt.Flow(date=when.isoformat(), amount=amount, kind=kind))
        self.book.save()
        self.flow_amount.clear()
        self.status.setText(f"Recorded ${amount:,.2f} in {fund.name}.")
        self.refresh()

    def _remove_flow(self):
        account = self.current_account()
        row = self.flows_table.currentRow()
        if account is None or row < 0:
            return
        item = self.flows_table.item(row, 0)
        key = item.data(Qt.UserRole) if item else None
        if not key:
            return
        fund_id, index = key
        fund = account.fund(fund_id)
        if fund is None or index >= len(fund.flows):
            return
        del fund.flows[index]
        self.book.save()
        self.refresh()

    # --- rendering ------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if self.table.rowCount() == 0 and self.book.accounts:
            self.refresh()

    def refresh(self):
        """Render from stored data immediately, then fetch the indices."""
        if self._loading:
            return
        self.note_refresh_started()
        from tradelab.core import retirement as rt
        account = self.current_account()
        if account is None:
            self._render_empty()
            return
        data = rt.summarize(account, benchmarks=self._benchmarks)
        self._render(data)
        symbols = {f.benchmark for f in account.funds if f.benchmark}
        missing = symbols - set(self._benchmarks)
        if missing and (self._worker is None or not self._worker.isRunning()):
            self.status.setText(f"Loading {len(missing)} index histories…")
            self._worker = _BenchmarkWorker(symbols)
            self._worker.done.connect(self._on_benchmarks)
            self._worker.start()

    def _on_benchmarks(self, histories, err):
        if err or histories is None:
            flag_problem(self.status, f"Could not load index histories: {err or 'no data'}")
            return
        from tradelab.data.market_data import is_synthetic
        # Never judge a real fund against fabricated prices — the same rule the
        # Analytics and Dividends tabs follow.
        self._benchmarks.update({s: df for s, df in histories.items()
                                 if df is not None and not is_synthetic(df)})
        self.status.setText("")
        self.refresh()

    def _render_empty(self):
        self._loading = True
        self.table.setRowCount(0)
        self._loading = False
        self.flows_table.setRowCount(0)
        self.flow_fund.clear()
        self.published_fund.clear()
        self.published_table.setRowCount(0)
        self.published_line.setText("")
        for key, _ in self._TILES:
            self.metrics[key].setText("—")
        self.headline.setText("Create a plan, then paste your statement below.")
        self.chart_widget.clear("No plan yet.")
        self.needs.setText("")

    def _cell(self, table, r, c, text, colour=None, align_right=True):
        item = QTableWidgetItem(text)
        if align_right:
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if colour:
            item.setForeground(QColor(colour))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        table.setItem(r, c, item)
        return item

    def _render(self, d):
        from tradelab.core import retirement as rt
        ccy = d["currency"]
        self.headline.setText(d["text"])

        self.metrics["value"].setText(f"${d['total_value']:,.2f} {ccy}"
                                      if d["total_value"] else "—")
        gain = d["gain"]
        self.metrics["gain"].setText(f"${gain:,.2f}" if gain is not None else "—")
        self.metrics["gain"].setStyleSheet(
            "font-size:18px; font-weight:bold;" + (
                f"color:{theme.pnl_color(gain)};" if gain is not None else ""))
        for key, row in (("best", d["best"]), ("worst", d["worst"])):
            if row is None:
                self.metrics[key].setText("—")
                self.metrics[key].setStyleSheet("font-size:18px; font-weight:bold;")
                continue
            pct = row["return"]["cumulative_pct"]
            self.metrics[key].setText(f"{row['name']}\n{pct:+.1f}%")
            self.metrics[key].setStyleSheet(
                f"font-size:14px; font-weight:bold; color:{theme.pnl_color(pct)};")
        self.metrics["funds"].setText(str(len(d["funds"])))

        self._loading = True
        rows = d["funds"]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            name = QTableWidgetItem(row["name"])
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, name)
            weight = row["weight_pct"]
            self._cell(self.table, r, 1, f"{weight:.1f}%" if weight is not None else "—")
            units = row["units"]
            self._cell(self.table, r, 2, f"{units:,.6f}" if units is not None else "—")
            uv = row["unit_value"]
            self._cell(self.table, r, 3, f"${uv:,.2f}" if uv is not None else "—")
            value = row["value"]
            self._cell(self.table, r, 4, f"${value:,.2f}" if value is not None else "—")

            perf = row["return"]
            if perf["usable"]:
                pct = perf["cumulative_pct"]
                text = f"{pct:+.2f}%"
                if perf["annualized_pct"] is not None:
                    text += f"  ({perf['annualized_pct']:+.1f}%/yr)"
                item = self._cell(self.table, r, 5, text, theme.pnl_color(pct))
                if perf["method"] == rt.BY_DIETZ:
                    item.setToolTip("Corrected for your contributions from dollar "
                                    "balances — no unit values on file for this fund.")
                self._cell(self.table, r, 6, f"{perf['days']}d")
            else:
                item = self._cell(self.table, r, 5, "—", theme.MUTED)
                item.setToolTip(perf["reason"])
                self._cell(self.table, r, 6, "—", theme.MUTED)

            mine = row["personal"]
            if mine["usable"]:
                self._cell(self.table, r, 7, f"{mine['rate_pct']:+.2f}%/yr",
                           theme.pnl_color(mine["rate_pct"]))
            else:
                item = self._cell(self.table, r, 7, "—", theme.MUTED)
                item.setToolTip(mine["reason"])

            bench = QTableWidgetItem(row["benchmark"] or "")
            bench.setTextAlignment(Qt.AlignCenter)
            bench.setFlags(bench.flags() | Qt.ItemIsEditable)
            bench.setData(Qt.UserRole, row["id"])
            self.table.setItem(r, self.BENCH_COL, bench)

            excess = row["excess_pct"]
            if excess is None:
                item = self._cell(self.table, r, 9, "—", theme.MUTED)
                if row["benchmark"] and perf["usable"]:
                    item.setToolTip("No price history for this index over that window.")
            else:
                self._cell(self.table, r, 9,
                           f"{excess:+.2f} pp", theme.pnl_color(excess))
        self.table.resizeColumnsToContents()
        self._fit_table(self.table)
        self._loading = False

        self._render_flows(d)
        self._sync_published_controls(d)
        self._render_published()
        footnote = ("Rebased from each fund's first statement. Unit values only — a "
                    "dollar balance rises when you contribute, which is not performance.")
        self.chart_widget.show_funds(rt.rebased(self.current_account()),
                                     footnote=footnote)
        self.needs.setText("\n".join("• " + n for n in d["needs"]))

    def _render_flows(self, d):
        from tradelab.core import retirement as rt
        account = self.current_account()
        self.flow_fund.clear()
        entries = []
        for fund in (account.funds if account else []):
            self.flow_fund.addItem(fund.name, fund.id)
            for i, flow in enumerate(fund.flows):
                entries.append((flow.date, fund, i, flow))
        entries.sort(key=lambda e: e[0], reverse=True)
        labels = {rt.CONTRIBUTION: "Contribution", rt.EMPLOYER: "Employer",
                  rt.WITHDRAWAL: "Withdrawal"}
        self.flows_table.setRowCount(len(entries))
        for r, (when, fund, index, flow) in enumerate(entries):
            item = QTableWidgetItem(when)
            item.setData(Qt.UserRole, (fund.id, index))
            self.flows_table.setItem(r, 0, item)
            self.flows_table.setItem(r, 1, QTableWidgetItem(fund.name))
            self.flows_table.setItem(r, 2, QTableWidgetItem(labels.get(flow.kind, flow.kind)))
            amount = QTableWidgetItem(f"${flow.amount:,.2f}")
            amount.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if flow.kind == rt.WITHDRAWAL:
                amount.setForeground(QColor(theme.DOWN))
            self.flows_table.setItem(r, 3, amount)
        self.flows_table.resizeColumnsToContents()

    def _on_item_changed(self, item):
        """The index column is the one editable cell; everything else is output."""
        if self._loading or item.column() != self.BENCH_COL:
            return
        account = self.current_account()
        if account is None:
            return
        fund = account.fund(item.data(Qt.UserRole) or "")
        if fund is None:
            return
        symbol = item.text().strip().upper()
        if symbol == fund.benchmark:
            return
        fund.benchmark = symbol
        self.book.save()
        self.refresh()

    def shutdown(self):
        worker = getattr(self, "_worker", None)
        if worker is not None:
            try:
                worker.done.disconnect()
            except (RuntimeError, TypeError):
                pass
            worker.wait(3000)
            self._worker = None
