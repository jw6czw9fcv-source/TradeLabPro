"""The Retirement Sim tab: a household projected year by year."""
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
from tradelab.ui.common import (FlowLayout, StatusLabel, _hint, flag_problem, table_item)

log = get_logger(__name__)


class _BudgetWorker(QThread):
    """Finds the safe budget (retirement_plan.safe_budget) off the UI thread."""
    done = Signal(object, str)   # result dict | None, error

    def __init__(self, make_plan, mean, sd, share, paths, start):
        super().__init__()
        self.args = (make_plan, mean, sd, share, paths, start)

    def run(self):
        from tradelab.core.retirement_plan import safe_budget
        make_plan, mean, sd, share, paths, start = self.args
        try:
            result, err = safe_budget(make_plan, mean, sd, share=share, paths=paths,
                                      start=max(start, 1_000.0)), ""
        except Exception as exc:
            result, err = None, str(exc) or type(exc).__name__
        try:
            self.done.emit(result, err)
        except RuntimeError:
            pass


class RetirementSimPanel(QWidget):
    """How long the money lasts, given what you hold and what you assume.

    The Retirement tab beside this one *tracks* a plan — what it was worth,
    what it returned. This one projects: incomes, the forced RRIF minimum,
    real Québec + federal tax, and what has to come out of capital to cover
    the spending, year by year to the age you name.

    It computes and does not advise. Spending, return, the age each pension
    starts, how much pension income is split, the order accounts are drawn
    from — all of it is typed here by the person whose plan it is. Nothing in
    this panel picks a strategy or says whether a plan is good.
    """

    SETTING = "RetirementSim"
    SPECS = {
        "people": (["Name", "Age", "TFSA room", "Born"], ["name", "age", "tfsa_room", "born"]),
        "accounts": (["Account", "Kind", "Balance", "Owner"],
                     ["name", "kind", "balance", "owner"]),
        "incomes": (["Income", "Owner", "Per year", "Starts", "Ends", "Indexed"],
                    ["name", "owner", "annual", "starts_at_age", "ends_at_age",
                     "indexed"]),
    }

    # Typed in the Indexed column. Anything else is read as "yes", because an
    # income that keeps its value is by far the common case here - RRQ, PSV,
    # AOW - and a blank cell should not quietly halve a pension.
    NOT_INDEXED = {"no", "n", "non", "false", "0", "fixed", "fixe"}

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.rows = []
        # Set by MainWindow; the panel does not know about the right-hand pane.
        self.chart = None
        self._last_series = None
        # The last many-path run, kept so the Today's $ toggle can re-read it
        # rather than draw hundreds of paths again.
        self._paths_out = None
        layout = QVBoxLayout(self)

        bar = QWidget()
        policy = bar.sizePolicy(); policy.setHeightForWidth(True); bar.setSizePolicy(policy)
        controls = FlowLayout(bar, hspacing=6, vspacing=4)
        self.spending = QDoubleSpinBox()
        self.spending.setRange(0, 1_000_000); self.spending.setDecimals(0)
        self.spending.setPrefix("$"); self.spending.setSingleStep(1_000)
        self.spending.setToolTip("Household spending per year, in today's dollars — it "
                                 "grows with inflation from there. The input that moves "
                                 "the answer more than any other.")
        self.nominal_return = QDoubleSpinBox()
        self.nominal_return.setRange(-10, 20); self.nominal_return.setDecimals(1)
        self.nominal_return.setSuffix(" % return")
        self.nominal_return.setToolTip("The return as a fund reports it, with inflation "
                                       "still in it. 5 means five percent.")
        self.inflation = QDoubleSpinBox()
        self.inflation.setRange(0, 15); self.inflation.setDecimals(1)
        self.inflation.setSuffix(" % infl")
        self.inflation.setToolTip(
            "Projected explicitly rather than netted out of the return. It grows "
            "the indexed benefits (RRQ, PSV, AOW), the spending, and the tax "
            "brackets — which are indexed by law, so leaving them frozen would "
            "invent bracket creep that will not happen.")
        # The nominal return is the figure you can look up; the real one is what
        # actually decides whether the plan holds. Showing it live means the
        # difference between them is never invisible.
        self.real_hint = QLabel("")
        self.real_hint.setStyleSheet("color: " + theme.MUTED + "; font-size: 11px;")
        self.nominal_return.valueChanged.connect(self._update_real_hint)
        self.inflation.valueChanged.connect(self._update_real_hint)
        # A balance in 2055 nominal dollars is not a figure anyone can price,
        # so the reading view is a toggle rather than a second run: every row
        # carries its own deflator.
        self.todays_dollars = QCheckBox("Today's $")
        self.todays_dollars.setToolTip(
            "Show the results in today's purchasing power instead of the dollars "
            "of the year they happen. The projection itself is unchanged — this "
            "only divides each year by its inflation factor.")
        self.todays_dollars.toggled.connect(self._redraw_results)
        self.until_age = QSpinBox(); self.until_age.setRange(66, 110)
        self.until_age.setPrefix("to age ")
        self.splitting = QDoubleSpinBox()
        self.splitting.setRange(0, 50); self.splitting.setDecimals(0)
        self.splitting.setSuffix(" % split")
        self.splitting.setToolTip("How much eligible pension income to move to the lower "
                                  "earner. Only pension income can move — a wage cannot, "
                                  "and RRQ has its own separate mechanism.")
        self.volatility = QDoubleSpinBox()
        self.volatility.setRange(0, 40); self.volatility.setDecimals(0)
        self.volatility.setSuffix(" % vol")
        self.volatility.setToolTip("How much the return varies year to year. This is what "
                                   "turns one projection into a range - and what makes the "
                                   "order of the returns matter.")
        self.paths = QSpinBox(); self.paths.setRange(50, 5000); self.paths.setSingleStep(50)
        self.paths.setPrefix("paths ")
        run = QPushButton("Run projection"); run.clicked.connect(self.run)
        trajectories = QPushButton("Run many paths")
        trajectories.setToolTip("Run the same plan over hundreds of return orderings. One "
                                "average cannot show sequence risk; this can.")
        trajectories.clicked.connect(self.run_paths)
        ages = QPushButton("Compare start ages")
        ages.setToolTip("Run the plan with each RRQ and PSV started at every age from 65 "
                        "to 72 (RRQ) or 70 (PSV) and show what each leaves at the end.")
        ages.clicked.connect(self.compare_ages)
        dates = QPushButton("Key dates")
        dates.setToolTip("When to apply for the RRQ and the PSV, the RRSP deadline at 71 "
                         "and the TFSA's new room - dated from each person's Born month.")
        dates.clicked.connect(self.show_key_dates)
        budget = QPushButton("Safe budget")
        budget.setToolTip("The most this plan can spend a year to its last age: if every "
                          "year is average, and in 90% of simulated return orderings "
                          "(using the Return and % vol set here).")
        budget.clicked.connect(self.check_budget)
        orders = QPushButton("Withdrawal order")
        orders.setToolTip("Run the plan drawing from REER/FERR, CELI and non-registered accounts "
                          "in every order, and compare what is left, the tax paid and the OAS "
                          "clawback.")
        orders.clicked.connect(self.compare_orders)
        save = QPushButton("Save inputs"); save.clicked.connect(self.save)
        save_sim = QPushButton("Save sim")
        save_sim.setToolTip("Keep the current run on the chart as the line to compare "
                            "against. It stays there until you press this again — "
                            "including after the app is closed.")
        save_sim.clicked.connect(self.save_sim)
        clear_sim = QPushButton("Clear saved")
        clear_sim.clicked.connect(self.clear_saved_sim)
        for widget in (QLabel("Spending"), self.spending, QLabel("  Return"),
                       self.nominal_return, self.inflation, self.real_hint,
                       self.volatility, QLabel("  Project"),
                       self.until_age, QLabel("  Pension"), self.splitting,
                       self.todays_dollars,
                       self.paths, run, trajectories, ages, dates, budget, orders, save, save_sim,
                       clear_sim):
            controls.addWidget(widget)
        layout.addWidget(bar)

        self.tables = {}
        inputs = QHBoxLayout()
        for key, (headers, _fields) in self.SPECS.items():
            box = QGroupBox(key.capitalize())
            inner = QVBoxLayout(box)
            table = QTableWidget(0, len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setMinimumHeight(150)
            inner.addWidget(table)
            buttons = QHBoxLayout()
            add = QPushButton("Add")
            add.clicked.connect(lambda _c=False, k=key: self._add_row(k))
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda _c=False, k=key: self._remove_row(k))
            buttons.addWidget(add); buttons.addWidget(remove)
            inner.addLayout(buttons)
            self.tables[key] = table
            inputs.addWidget(box)
        layout.addLayout(inputs)
        deferral_tip = ("For the RRQ and the PSV, type the amount at 65 and the age it "
                        "starts: a later start adds the increase the law gives for waiting "
                        "- RRQ +0.7% a month up to 72, PSV +0.6% a month up to 70. An RRQ "
                        "started before 65 is used as typed.")
        for column in (2, 3):                       # Per year, Starts
            header = self.tables["incomes"].horizontalHeaderItem(column)
            if header is not None:
                header.setToolTip(deferral_tip)
        born_header = self.tables["people"].horizontalHeaderItem(3)
        if born_header is not None:
            born_header.setToolTip("Birth month, e.g. 1962-08 - dates the reminders under "
                                   "Key dates. Optional.")
        room_header = self.tables["people"].horizontalHeaderItem(2)
        if room_header is not None:
            room_header.setToolTip(
                "The TFSA contribution room this person has today - CRA's My Account "
                "shows it. Money the plan saves fills it before going where its growth "
                "is taxed. Blank counts as none.")

        # What the accounts TradeLab follows hold today, beside the plan's own
        # starting balances - shown, never copied in: the plan's lines can cover
        # accounts TradeLab cannot see.
        self.retirement_path = None
        self.tracked_line = QLabel("")
        self.tracked_line.setWordWrap(True)
        self.tracked_line.setStyleSheet("color: " + theme.MUTED + ";")
        layout.addWidget(self.tracked_line)

        # The safe-budget check: the most the plan can spend, against what it does.
        self.budget = None
        self._budget_worker = None
        self.budget_line = QLabel("")
        self.budget_line.setWordWrap(True)
        layout.addWidget(self.budget_line)

        self.status = StatusLabel("Fill in the tables, then Run projection.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.results = QTableWidget(0, len(self.RESULT_HEADERS))
        self.results.setHorizontalHeaderLabels(self.RESULT_HEADERS)
        self.results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results.setAlternatingRowColors(True)
        self.results.setMinimumHeight(260)
        layout.addWidget(self.results, 1)

        note = QLabel(
            "Every figure is in the dollars of the year it happens: the return is the "
            "nominal one a fund reports, and inflation is projected rather than netted "
            "out of it. So the RRQ, the PSV and the spending all rise year by year, and "
            "so do the tax brackets, which are indexed by law — if indexation ever "
            "stops, this is optimistic. An income you mark Indexed = No keeps paying the "
            "same cheque and quietly loses half its worth over thirty years. Tick "
            "Today's $ to read the whole table in today's purchasing power. "
            "A withdrawal from a registered account is income: covering a gap takes "
            "enough more to pay its own tax. Income left over after tax and spending - "
            "a RRIF minimum you did not need, a wage still coming in - is saved, drawn "
            "last: into the TFSA while there is room (each person's room today, in the "
            "People table, plus each year's new limit), the rest in a non-registered "
            "account whose growth is taxed every year as a capital gain. "
            "And a single return path says nothing about the order returns arrive in: a "
            "bad first few years of drawing down hurts far more than the same average "
            "later. " + theme.NOT_ADVICE)
        note.setWordWrap(True)
        note.setStyleSheet("color: " + theme.MUTED + "; font-size: 11px;")
        layout.addWidget(note)

        self.load()

    # -- the input tables ---------------------------------------------------
    def load(self):
        for key, (_headers, fields) in self.SPECS.items():
            rows = self.db.retirement_rows(key)
            table = self.tables[key]
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, field in enumerate(fields):
                    value = row.get(field)
                    # Stored as a flag, read back as a word: a column of 1s and
                    # 0s is not something you can check at a glance.
                    if field == "indexed":
                        value = "No" if str(value) in ("0", "False") else "Yes"
                    table.setItem(r, c, table_item("" if value is None else value))
            table.resizeColumnsToContents()
        settings = app_settings()
        settings.beginGroup(self.SETTING)
        self.spending.setValue(float(settings.value("spending", 50_000)))
        self.inflation.setValue(float(settings.value("inflation", 2.0)))
        # The panel used to ask for a real return. Someone who set 3% real meant
        # a plan, not a number, so the saved value is converted rather than
        # dropped - reading it as 3% nominal would silently make their plan
        # poorer overnight.
        from tradelab.core.retirement_plan import nominal_from_real
        saved_nominal = settings.value("nominal_return")
        if saved_nominal is None:
            old_real = settings.value("real_return")
            saved_nominal = (nominal_from_real(float(old_real) / 100.0,
                                               self.inflation.value() / 100.0) * 100
                             if old_real is not None else 5.0)
        self.nominal_return.setValue(float(saved_nominal))
        self.todays_dollars.setChecked(
            str(settings.value("todays_dollars", "false")).lower() in ("true", "1"))
        self.until_age.setValue(int(settings.value("until_age", 95)))
        self.splitting.setValue(float(settings.value("splitting", 0)))
        self.volatility.setValue(float(settings.value("volatility", 10)))
        self.paths.setValue(int(settings.value("paths", 500)))
        settings.endGroup()
        self._update_real_hint()
        self.show_tracked()

    def show_tracked(self):
        """One line: the portfolios' last recorded value and the plans in the
        Retirement tab, against the balances the plan starts from."""
        from tradelab.core.retirement import RetirementBook
        parts, total = [], 0.0
        try:
            rows = self.db.value_history("CAD")
        except Exception:
            rows = []
        if rows:
            parts.append(f"portfolios ${rows[-1]['value']:,.0f} ({rows[-1]['day']})")
            total += rows[-1]["value"]
        try:
            accounts = RetirementBook(self.retirement_path).accounts
        except Exception:
            accounts = []
        for account in accounts:
            if account.value and account.currency == "CAD":
                parts.append(f"{account.name} ${account.value:,.0f}")
                total += account.value
        if not parts:
            self.tracked_line.setText("")
            return
        plan = sum(r.get("balance") or 0.0 for r in self._read("accounts"))
        self.tracked_line.setText(
            "What TradeLab tracks today: " + " + ".join(parts) + f" = ${total:,.0f}. "
            f"The plan's accounts start at ${plan:,.0f} - update them here if they no "
            "longer match; the plan can include accounts TradeLab cannot see.")

    def save(self):
        written = 0
        for key in self.SPECS:
            written += self.db.set_retirement_rows(key, self._read(key))
        settings = app_settings()
        settings.beginGroup(self.SETTING)
        settings.setValue("spending", self.spending.value())
        settings.setValue("nominal_return", self.nominal_return.value())
        settings.setValue("inflation", self.inflation.value())
        settings.setValue("todays_dollars", self.todays_dollars.isChecked())
        settings.setValue("until_age", self.until_age.value())
        settings.setValue("splitting", self.splitting.value())
        settings.setValue("volatility", self.volatility.value())
        settings.setValue("paths", self.paths.value())
        settings.endGroup()
        settings.sync()
        self.status.setText("Saved " + str(written) + " rows.")

    def _read(self, key) -> list:
        _headers, fields = self.SPECS[key]
        table = self.tables[key]
        rows = []
        for r in range(table.rowCount()):
            row = {}
            for c, field in enumerate(fields):
                item = table.item(r, c)
                text = item.text().strip() if item else ""
                if field in ("age", "starts_at_age", "ends_at_age"):
                    row[field] = int(float(text)) if text else None
                elif field in ("balance", "annual"):
                    cleaned = text.replace(",", "").replace("$", "").replace(" ", "")
                    row[field] = float(cleaned) if cleaned else 0.0
                elif field == "tfsa_room":
                    # Blank stays blank: "none", the cautious reading, without
                    # pretending someone typed a zero.
                    cleaned = text.replace(",", "").replace("$", "").replace(" ", "")
                    row[field] = float(cleaned) if cleaned else None
                elif field == "indexed":
                    row[field] = 0 if text.lower() in self.NOT_INDEXED else 1
                else:
                    row[field] = text
            rows.append(row)
        return rows

    def _add_row(self, key):
        table = self.tables[key]
        table.insertRow(table.rowCount())

    def _remove_row(self, key):
        table = self.tables[key]
        rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True)
        if not rows and table.rowCount():
            rows = [table.rowCount() - 1]
        for row in rows:
            table.removeRow(row)

    def _update_real_hint(self):
        """Show what the nominal return leaves after inflation.

        The nominal figure is the one you can look up; the real one is what
        decides whether the plan holds. It is the Fisher relation rather than
        a subtraction — 5% with 2% inflation is 2.94% real, not 3%, and the
        subtraction is always the optimistic direction.
        """
        from tradelab.core.retirement_plan import real_from_nominal
        real = real_from_nominal(self.nominal_return.value() / 100.0,
                                 self.inflation.value() / 100.0)
        self.real_hint.setText("= {:.2f}% real".format(real * 100))

    # -- the projection -----------------------------------------------------
    def build_plan(self):
        from tradelab.core.retirement_plan import deferrals, plan_from_rows
        plan = plan_from_rows(
            self._read("people"), self._read("accounts"), self._read("incomes"),
            spending=self.spending.value(),
            nominal_return=self.nominal_return.value() / 100.0,
            inflation=self.inflation.value() / 100.0,
            until_age=self.until_age.value(),
            tax_fn=self.tax_fn())
        self._deferrals = deferrals(plan) if plan is not None else []
        return plan

    def tax_fn(self):
        """Real Quebec + federal tax, each person taxed as a person, pension
        split by the fraction set here. Built in core.tax_quebec, so the MCP
        server's projection taxes a plan exactly as this tab does."""
        from tradelab.core.tax_quebec import household_tax_fn
        return household_tax_fn(self.splitting.value() / 100.0,
                                self.inflation.value() / 100.0)

    def run(self):
        from tradelab.core.retirement_plan import project
        plan = self.build_plan()
        if plan is None:
            flag_problem(self.status, "Add at least one person and one account first.")
            self.results.setRowCount(0)
            return
        self.rows = project(plan)
        # A one-path run replaces a many-path one on screen, so the band is no
        # longer what is being shown.
        self._paths_out = None
        self._last_series = {
            "years": [row["calendar_year"] for row in self.rows],
            "balances": [row["closing"] for row in self.rows],
            # Kept with the series so the chart can switch to today's dollars
            # without re-running anything - including for a run saved months ago.
            "deflators": [row["closing_deflator"] for row in self.rows],
            "label": "{:,.0f}$/yr at {:.1f}% nominal".format(
                self.spending.value(), self.nominal_return.value()),
        }
        self.render_results()
        self._draw()

    # -- which dollars the results are read in --------------------------------
    #
    # The projection is always run in the dollars of the year each thing
    # happens; the toggle only changes how the finished rows are read, which is
    # why it re-renders instead of re-running.

    def _in_todays_dollars(self) -> bool:
        return self.todays_dollars.isChecked()

    def _view_rows(self):
        """The rows as they should be read right now."""
        from tradelab.core.retirement_plan import deflate
        if not self.rows:
            return []
        return deflate(self.rows) if self._in_todays_dollars() else self.rows

    def _dollars_note(self) -> str:
        return (" Figures are in today's dollars."
                if self._in_todays_dollars()
                else " Figures are in the dollars of each year, not today's.")

    def _deferral_note(self) -> str:
        """Which public pensions start after 65 and what the law added for it,
        so a larger cheque than the one typed is never a mystery."""
        items = getattr(self, "_deferrals", None) or []
        if not items:
            return ""
        return " Started after 65, with the increase for waiting: " + "; ".join(
            "{} ({}) at {}, +{:g}%".format(d["income"], d["owner"], d["starts_at_age"],
                                          d["increase_pct"]) for d in items) + "."

    def _status_notes(self) -> str:
        return self._dollars_note() + self._deferral_note()

    def _redraw_results(self):
        """Re-read what is already on screen, whichever view it is."""
        if getattr(self, "_paths_out", None):
            self.render_paths(self._paths_out)
        elif self.rows:
            self.render_results()
        self._draw(band=self._band())

    SAVED_KEY = "saved_sim"

    def saved_sim(self):
        """The kept run, or None. Lives in settings rather than memory so it
        survives closing the app — the point of a baseline is that it is still
        there tomorrow."""
        settings = app_settings()
        settings.beginGroup(self.SETTING)
        raw = settings.value(self.SAVED_KEY)
        settings.endGroup()
        try:
            saved = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            return None
        return saved if saved and saved.get("years") else None

    def save_sim(self):
        """Keep what is on screen as the line to compare against."""
        if not self._last_series:
            flag_problem(self.status, "Run a projection first — there is nothing to save yet.")
            return
        settings = app_settings()
        settings.beginGroup(self.SETTING)
        settings.setValue(self.SAVED_KEY, json.dumps(self._last_series))
        settings.endGroup()
        settings.sync()
        self._draw()
        self.status.setText(
            "Saved as the comparison line. It stays until you press Save sim again.")

    def clear_saved_sim(self):
        settings = app_settings()
        settings.beginGroup(self.SETTING)
        settings.remove(self.SAVED_KEY)
        settings.endGroup()
        settings.sync()
        self._draw()
        self.status.setText("Saved run removed from the chart.")

    def _as_read(self, series):
        """A saved or current series in whichever dollars are being shown.

        A series carries the deflator for every year it drew, so a run kept
        months ago can be read in today's dollars beside a fresh one. One saved
        before those deflators existed has none, and is left as it was rather
        than deflated with a guess.
        """
        if not series or not self._in_todays_dollars():
            return series
        factors = series.get("deflators")
        if not factors or len(factors) != len(series.get("balances", [])):
            return series
        out = dict(series)
        out["balances"] = [b / (f or 1.0) for b, f in zip(series["balances"], factors)]
        return out

    def _band(self):
        """The percentile band of the last many-path run, read the same way."""
        out = getattr(self, "_paths_out", None)
        if not out:
            return None
        low, high = out["percentiles"][10], out["percentiles"][90]
        if self._in_todays_dollars():
            factors = self._closing_deflators(len(low))
            low = [v / f for v, f in zip(low, factors)]
            high = [v / f for v, f in zip(high, factors)]
        return (low, high)

    def _closing_deflators(self, count):
        """One factor per year, for figures measured at the end of the year —
        a closing balance is a year further from today's prices than the
        cheques written during that year."""
        rate = self.inflation.value() / 100.0
        return [(1.0 + rate) ** (year + 1) for year in range(count)]

    def _draw(self, band=None):
        """Push the current run and the saved one at the chart."""
        if self.chart is None:
            return
        self.chart.show_saved(self._as_read(self.saved_sim()))
        series = self._as_read(self._last_series)
        if series:
            self.chart.show_projection(series["years"], series["balances"],
                                       series.get("label", "Current"),
                                       band=band)

    def show_key_dates(self):
        """The dated reminders around retirement for everyone in the plan."""
        from tradelab.core.retirement_dates import checklist
        people = [p for p in self._read("people") if str(p.get("name") or "").strip()]
        if not people:
            flag_problem(self.status, "Add the people in the plan first (People table).")
            return
        items = checklist(people, self._read("incomes"))
        self.key_dates = items
        dialog = QDialog(self)
        dialog.setWindowTitle("Retirement - key dates")
        dialog.resize(900, 460)
        v = QVBoxLayout(dialog)
        v.addWidget(_hint(
            "Worked out from each person's Born month and when the plan starts each pension. "
            "The rules were read on Retraite Québec's and canada.ca's own pages on "
            "2026-10-14 (hover a row for its source) - check them there before acting, they "
            "can change. Past dates are greyed."))
        table = QTableWidget(len(items), 3)
        table.setHorizontalHeaderLabels(["When", "Who", "What"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        for r, item in enumerate(items):
            when = item["date"].strftime("%Y-%m-%d") if item["date"] else "—"
            for c, text in enumerate((when, item["person"], item["what"])):
                cell = QTableWidgetItem(text)
                cell.setToolTip(item["source"])
                if item["past"]:
                    cell.setForeground(QColor(theme.MUTED))
                table.setItem(r, c, cell)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeRowsToContents()
        v.addWidget(table, 1)
        close = QPushButton("Close"); close.clicked.connect(dialog.accept)
        v.addWidget(close, 0, Qt.AlignRight)
        self.dates_dialog = dialog
        dialog.show()

    AGE_HEADERS = ["Pension", "Person", "Starts at", "Increase", "Left at the end (today's $)",
                   "Money runs out", ""]

    # -- the safe budget --------------------------------------------------------
    BUDGET_SHARE = 0.90
    BUDGET_PATHS = 300
    BUDGET_CLOSE = 0.90     # spending above 90% of the safe budget is "close"

    def check_budget(self):
        """Work out the safe budget off the UI thread - a few thousand
        projections - then compare it with the spending set here."""
        from tradelab.core.retirement_plan import plan_from_rows
        if self._budget_worker is not None and self._budget_worker.isRunning():
            return
        people, accounts, incomes = (self._read(k) for k in ("people", "accounts", "incomes"))
        kwargs = dict(nominal_return=self.nominal_return.value() / 100.0,
                      inflation=self.inflation.value() / 100.0,
                      until_age=self.until_age.value(), tax_fn=self.tax_fn())
        if plan_from_rows(people, accounts, incomes, spending=self.spending.value(),
                          **kwargs) is None:
            flag_problem(self.status, "Add at least one person and one account first.")
            return

        def make_plan(spending):
            return plan_from_rows(people, accounts, incomes, spending=spending, **kwargs)

        self.budget_line.setText("Working out the safe budget…")
        self._budget_worker = _BudgetWorker(make_plan, kwargs["nominal_return"],
                                            self.volatility.value() / 100.0,
                                            self.BUDGET_SHARE, self.BUDGET_PATHS,
                                            self.spending.value())
        self._budget_worker.done.connect(self._on_budget)
        self._budget_worker.start()

    def _on_budget(self, result, error):
        if error or not result:
            flag_problem(self.status, f"Could not work out the safe budget: {error or 'no result'}")
            self.budget_line.setText("")
            return
        self.budget = result
        spending = self.spending.value()
        # Kept for the Plan tab's checklist, with the spending it was compared to.
        try:
            settings = app_settings()
            settings.setValue(f"{self.SETTING}/last_budget", json.dumps(
                {"safe": result["safe"], "average": result["average"], "spending": spending,
                 "checked": time.strftime("%Y-%m-%d")}))
            settings.sync()
        except Exception:
            log.exception("Could not keep the safe budget for the Plan tab")
        safe, average = result["safe"], result["average"]
        head = (f"<b>Safe budget: ${safe:,.0f} a year</b> (holds in "
                f"{result['share']:.0%} of {result['paths']} simulated return orderings at "
                f"{result['mean']:.1%} with {result['sd']:.0%} vol, in today's dollars, to age "
                f"{self.until_age.value()}); ${average:,.0f} if every year is average. ")
        if spending > safe:
            colour = theme.DOWN
            verdict = (f"Your spending of ${spending:,.0f} is ${spending - safe:,.0f} above it: "
                       "the bad orderings run the plan short.")
        elif spending > safe * self.BUDGET_CLOSE:
            colour = theme.WARN
            verdict = (f"Your spending of ${spending:,.0f} is close to it - "
                       f"${safe - spending:,.0f} of margin.")
        else:
            colour = theme.UP
            verdict = (f"Your spending of ${spending:,.0f} leaves ${safe - spending:,.0f} a "
                       "year of margin.")
        self.budget_line.setText(head + f"<span style='color:{colour}'>{verdict}</span>"
                                 " Crashes deeper than the % vol implies would lower it - "
                                 "keep a margin. A calculation, not advice.")
        if spending > safe:
            flag_problem(self.status, f"Spending ${spending:,.0f} is above the safe budget of "
                                      f"${safe:,.0f} a year.")

    def shutdown(self):
        worker = self._budget_worker
        if worker is not None and worker.isRunning():
            worker.wait(30000)

    ORDER_HEADERS = ["Draw from (first → last)", "Left at the end (today's $)",
                     "Tax paid (today's $)", "of which OAS clawback", "Money runs out", ""]

    def compare_orders(self):
        """Every order of account kinds, side by side, in a window."""
        from tradelab.core.retirement_plan import compare_withdrawal_orders
        plan = self.build_plan()
        if plan is None:
            flag_problem(self.status, "Add at least one person and one account first.")
            return
        rows = compare_withdrawal_orders(plan)
        if len(rows) < 2:
            flag_problem(self.status, "The plan has only one kind of account - there is no order "
                                      "to compare. Add a CELI or a non-registered account.")
            return
        self.order_rows = rows
        dialog = QDialog(self)
        dialog.setWindowTitle("Withdrawal order compared")
        dialog.resize(900, 360)
        v = QVBoxLayout(dialog)
        v.addWidget(_hint(
            f"The same plan, drawing from each kind of account in a different order, projected "
            f"to age {self.until_age.value()}. The RRIF minimum is drawn whatever the order; only "
            "what is drawn beyond it follows the order. ★ leaves the most. It compares orders "
            "only - not strategies such as drawing more in a low-tax year. " + theme.NOT_ADVICE))
        table = QTableWidget(len(rows), len(self.ORDER_HEADERS))
        table.setHorizontalHeaderLabels(self.ORDER_HEADERS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for r, row in enumerate(rows):
            marks = " ".join(m for m, on in (("★ most left", row["best"]),
                                              ("(as entered)", row["current"])) if on)
            cells = [" → ".join(row["order"]), f"{row['capital_at_end']:,.0f} $",
                     f"{row['tax']:,.0f} $", f"{row['oas_recovery']:,.0f} $",
                     str(row["runs_out"]) if row["runs_out"] else "never", marks]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if row["best"]:
                    font = item.font(); font.setBold(True); item.setFont(font)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        v.addWidget(table, 1)
        close = QPushButton("Close"); close.clicked.connect(dialog.accept)
        v.addWidget(close, 0, Qt.AlignRight)
        self.order_dialog = dialog
        self.status.setText("Withdrawal orders compared - see the window.")
        dialog.show()

    def compare_ages(self):
        """Every start age of each RRQ and PSV, one at a time, in a window -
        the comparison that used to take one edit and one run per age."""
        from tradelab.core.retirement_plan import compare_start_ages
        plan = self.build_plan()
        if plan is None:
            flag_problem(self.status, "Add at least one person and one account first.")
            return
        options = compare_start_ages(plan)
        if not options:
            flag_problem(self.status, "There is no RRQ or PSV starting at 65 or later in the "
                                      "Incomes table to compare.")
            return
        self.age_options = options
        dialog = QDialog(self)
        dialog.setWindowTitle("RRQ and PSV - start ages compared")
        dialog.resize(820, 520)
        v = QVBoxLayout(dialog)
        v.addWidget(_hint(
            f"Each pension started at every age, the rest of the plan unchanged, projected "
            f"to age {self.until_age.value()}. ★ leaves the most at the end. A later start "
            "pays more each year but for fewer years: it comes out ahead only for a life "
            "long enough to pass the break-even age. Surviving spouses and health are not "
            "in it. " + theme.NOT_ADVICE))
        table = QTableWidget(len(options), len(self.AGE_HEADERS))
        table.setHorizontalHeaderLabels(self.AGE_HEADERS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for r, o in enumerate(options):
            marks = " ".join(m for m, on in (("★ most left", o["best"]),
                                              ("(your plan)", o["current"])) if on)
            cells = [o["income"], o["owner"], str(o["starts_at_age"]),
                     f"+{o['increase_pct']:g}%" if o["increase_pct"] else "-",
                     f"{o['capital_at_end']:,.0f} $",
                     str(o["runs_out"]) if o["runs_out"] else "never", marks]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if o["best"]:
                    font = item.font(); font.setBold(True); item.setFont(font)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        v.addWidget(table, 1)
        close = QPushButton("Close"); close.clicked.connect(dialog.accept)
        v.addWidget(close, 0, Qt.AlignRight)
        self.age_dialog = dialog
        self.status.setText("Start ages compared - see the window.")
        dialog.show()

    def run_paths(self):
        """The same plan over many return orderings.

        One average return hides the thing that decides a drawdown: losing
        20% in the first two years of withdrawing is not the same as losing
        it in the last two, because money taken out at the bottom never comes
        back. Only many orderings can show that.
        """
        from tradelab.core.retirement_plan import simulate
        plan = self.build_plan()
        if plan is None:
            flag_problem(self.status, "Add at least one person and one account first.")
            return
        out = simulate(plan, paths=self.paths.value(),
                       mean=self.nominal_return.value() / 100.0,
                       sd=self.volatility.value() / 100.0, seed=1)
        self._paths_out = out
        self._last_series = {
            "years": out["calendar_years"],
            "balances": out["percentiles"][50],
            "deflators": self._closing_deflators(len(out["calendar_years"])),
            "label": "{:,.0f}$/yr, {:,} paths (median)".format(
                self.spending.value(), out["paths"]),
        }
        self.render_paths(out)
        self._draw(band=self._band())

    def render_paths(self, out):
        self.results.setColumnCount(6)
        self.results.setHorizontalHeaderLabels(
            ["Year", "Ages", "Worst 10%", "Median", "Best 10%", "Still solvent"])
        years = out["calendar_years"]
        self.results.setRowCount(len(years))
        ages = [row["ages"] for row in self.rows] if self.rows else []
        # Balances are end-of-year figures, so they deflate by the end-of-year
        # factor. Whether it is applied at all is the toggle's only job here.
        factors = (self._closing_deflators(len(years)) if self._in_todays_dollars()
                   else [1.0] * len(years))
        for r, year in enumerate(years):
            age_text = ", ".join(str(a) for a in ages[r].values()) if r < len(ages) else ""
            low = out["percentiles"][10][r] / factors[r]
            solvent = sum(1 for a in out["depletion_ages"]
                          if a is None or (r < len(ages) and a > max(ages[r].values())))
            cells = [str(year), age_text,
                     "{:,.0f}".format(low),
                     "{:,.0f}".format(out["percentiles"][50][r] / factors[r]),
                     "{:,.0f}".format(out["percentiles"][90][r] / factors[r]),
                     "{:.0f}%".format(solvent / out["paths"] * 100)]
            for c, text in enumerate(cells):
                item = table_item(text)
                if c == 2 and low <= 0:
                    item.setForeground(QColor(theme.DOWN))
                self.results.setItem(r, c, item)
        self.results.resizeColumnsToContents()

        rate = out["success_rate"] * 100
        worst = out["worst_decile_age"]
        message = ("Of {:,} paths, the money lasted the whole way in {:.0f}%."
                   .format(out["paths"], rate))
        if worst is not None:
            message += (" In the worst tenth of the ones that failed it ran out by age "
                        "{:.0f}.".format(worst))
        message += (" That percentage is the share of *simulated* paths under assumptions "
                    "you chose, not a probability that a retirement works — move the "
                    "spending by five thousand and it shifts more than any market will. "
                    "Returns are drawn from a normal curve, which has fewer very bad "
                    "years than markets actually do.")
        self.status.setText(message + self._status_notes())

    RESULT_HEADERS = ["Year", "Ages", "Income", "RRIF minimum", "Tax", "OAS clawback",
                      "From capital", "Reinvested", "Into TFSA", "Unfunded", "Closing"]

    def render_results(self):
        self.results.setColumnCount(len(self.RESULT_HEADERS))
        self.results.setHorizontalHeaderLabels(self.RESULT_HEADERS)
        from tradelab.core.retirement_plan import depletion_year
        # Whether the plan holds is decided on the nominal rows; only the
        # reading of them changes. Both agree about *when* it fails, because
        # dividing every figure by a positive factor cannot change a sign.
        rows = self._view_rows()
        self.results.setRowCount(len(rows))
        for r, row in enumerate(rows):
            ages = ", ".join(str(a) for a in row["ages"].values())
            cells = [str(row["calendar_year"]), ages,
                     "{:,.0f}".format(row["income"]),
                     "{:,.0f}".format(row["forced_withdrawal"]),
                     "{:,.0f}".format(row["tax"]),
                     "{:,.0f}".format(row.get("oas_recovery", 0.0)),
                     "{:,.0f}".format(row["drawn_from_capital"]),
                     "{:,.0f}".format(row.get("surplus", 0.0)),
                     "{:,.0f}".format(row.get("surplus_tfsa", 0.0)),
                     "{:,.0f}".format(row["unfunded"]),
                     "{:,.0f}".format(row["closing"])]
            for c, text in enumerate(cells):
                item = table_item(text)
                if row["unfunded"] > 0.01:
                    item.setForeground(QColor(theme.DOWN))
                self.results.setItem(r, c, item)
        self.results.resizeColumnsToContents()

        failed = depletion_year(rows)
        last = rows[-1]
        oldest = max(last["ages"].values())
        if failed is None:
            self.status.setText(
                "The money lasts to age {} — {:,.0f}$ left at the end. That is this one "
                "return path, not a promise: the same average arriving in a worse order "
                "can end differently.".format(oldest, last["closing"])
                + self._status_notes())
        else:
            age = max(rows[failed]["ages"].values())
            self.status.setText(
                "Runs short at age {}, first year {:,.0f}$ under the spending. The years "
                "after it are still shown rather than cut off.".format(
                    age, rows[failed]["unfunded"]) + self._status_notes())
