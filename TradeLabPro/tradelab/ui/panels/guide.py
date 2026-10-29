"""The Guide tab: a beginner's path, one step at a time. Step 1 asks about the
person, step 2 shows the levels with what they may return and what they
really did, and the one chosen becomes the Plan tab's target mix."""
import datetime as dt
import json

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from tradelab.core import guide as g
from tradelab.core.logging_config import get_logger
from tradelab.settings import app_settings
from tradelab.ui import theme
from tradelab.ui.common import StatusLabel, _hint, flag_problem

log = get_logger(__name__)

PROFILE_KEY = "Guide/profile"


class _GuideWorker(QThread):
    """The index funds' full price history, off the UI thread."""
    done = Signal(object, str)   # measured levels | None, error

    def run(self):
        try:
            from tradelab.core.etf_metrics import get_prices
            measured = g.measure({s: get_prices(s, "max") for s in g.PROXIES})
            self.done.emit(measured, "" if measured else "no price history came back")
        except Exception as exc:
            self.done.emit(None, str(exc) or type(exc).__name__)


def _money(v):
    return f"${v:,.0f}"


class GuidePanel(QWidget):
    """Step by step: about you, then your level. It explains and measures;
    the person chooses."""

    _measured_cache = None   # one download a session is enough

    def __init__(self, db=None, settings=None, on_plan_changed=None):
        super().__init__()
        self.db = db
        self._settings = settings or app_settings()
        self.on_plan_changed = on_plan_changed
        self._worker = None
        self.measured = GuidePanel._measured_cache
        self.recommended = None
        self._user_picked = False   # a level clicked stays picked when the records arrive
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "New to investing? This guide takes you through it one step at a time: a few "
            "questions about you, then the level of risk that fits your answers - with what it "
            "may return and what it really did in bad years. You choose; TradeLab never picks "
            "for you. " + theme.NOT_ADVICE))
        self.saved_line = QLabel(""); self.saved_line.setWordWrap(True)
        layout.addWidget(self.saved_line)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._about_you_page())
        self.pages.addWidget(self._level_page())
        layout.addWidget(self.pages, 1)
        self._load_profile()

    # -- step 1 --
    def _about_you_page(self):
        page = QWidget(); v = QVBoxLayout(page)
        title = QLabel("Step 1 of 2 - About you"); title.setFont(QFont(title.font().family(), 13, QFont.Bold))
        v.addWidget(title)
        form = QFormLayout()
        self.horizon = QComboBox(); self.horizon.addItems([h[0] for h in g.HORIZONS])
        self.horizon.setCurrentIndex(4)
        self.drop = QComboBox(); self.drop.addItems([d[0] for d in g.DROPS])
        self.drop.setCurrentIndex(3)
        self.accounts = QComboBox(); self.accounts.addItems(g.ACCOUNTS)
        self.lump = QDoubleSpinBox(); self.lump.setRange(0, 100_000_000); self.lump.setDecimals(0)
        self.lump.setSingleStep(1000); self.lump.setPrefix("$ "); self.lump.setGroupSeparatorShown(True)
        self.monthly = QDoubleSpinBox(); self.monthly.setRange(0, 1_000_000); self.monthly.setDecimals(0)
        self.monthly.setSingleStep(50); self.monthly.setPrefix("$ "); self.monthly.setGroupSeparatorShown(True)
        self.emergency = QComboBox(); self.emergency.addItems(g.YES_NO)
        self.debt = QComboBox(); self.debt.addItems(g.YES_NO); self.debt.setCurrentIndex(1)
        form.addRow("When will you need this money?", self.horizon)
        form.addRow("How big a drop could you live through without selling?", self.drop)
        form.addRow("", _hint("A 20% drop turns $10,000 into $8,000 for a while - months, "
                              "sometimes years. Selling then makes the loss permanent."))
        form.addRow("Which accounts do you have?", self.accounts)
        form.addRow("Amount to invest now", self.lump)
        form.addRow("Amount you can add each month", self.monthly)
        form.addRow("Do you have a few months of expenses set aside?", self.emergency)
        form.addRow("Do you owe on a credit card or loan at a high rate?", self.debt)
        v.addLayout(form)
        row = QHBoxLayout(); row.addStretch()
        nxt = QPushButton("Next: your level  →"); nxt.clicked.connect(self.show_levels)
        row.addWidget(nxt)
        v.addLayout(row)
        v.addStretch()
        return page

    # -- step 2 --
    def _level_page(self):
        page = QWidget(); v = QVBoxLayout(page)
        title = QLabel("Step 2 of 2 - Your level"); title.setFont(QFont(title.font().family(), 13, QFont.Bold))
        v.addWidget(title)
        self.why = QLabel(""); self.why.setWordWrap(True)
        self.why.setStyleSheet("font-weight:bold;")
        v.addWidget(self.why)
        self.steps = QLabel(""); self.steps.setWordWrap(True)
        self.steps.setStyleSheet("color:#c9a227;")
        v.addWidget(self.steps)
        self.status = StatusLabel(); self.status.setStyleSheet("color:#8a9099;")
        v.addWidget(self.status)
        self.table = QTableWidget(len(g.LEVELS), 7)
        self.table.setHorizontalHeaderLabels(
            ["Level", "Stocks / bonds / cash", "May return a year*", "Your money in … years*",
             "Worst fall (when)", "Worst 12 months", "Worst 5 years, a year"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(230)
        self.table.itemSelectionChanged.connect(self._on_pick)
        self.table.clicked.connect(lambda _i: setattr(self, "_user_picked", True))
        v.addWidget(self.table)
        self.choice = QLabel(""); self.choice.setWordWrap(True)
        v.addWidget(self.choice)
        box = QGroupBox("Make it your plan"); bv = QHBoxLayout(box)
        bv.addWidget(QLabel("For portfolio"))
        self.portfolio = QComboBox(); self.portfolio.setEditable(True); self.portfolio.setMinimumWidth(180)
        bv.addWidget(self.portfolio)
        use = QPushButton("Use this level"); use.clicked.connect(self.use_level)
        bv.addWidget(use); bv.addStretch()
        v.addWidget(box)
        v.addWidget(_hint(
            f"* From the {g.GUIDELINES} - a typical global index mix, less a "
            f"{g.INDEX_FEE:.2%} index-fund fee - from today's amounts. The guidelines are for 10 "
            f"years or more; over a shorter time a GIC's actual rate tells more. The worst "
            f"falls are what really happened, measured on Canadian-listed index funds "
            f"({', '.join(g.PROXIES)}) since 2002, rebalanced monthly: they stand in for "
            f"stocks and bonds and are not picks. The past is no promise. " + theme.NOT_ADVICE))
        row = QHBoxLayout()
        back = QPushButton("←  Back"); back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        row.addWidget(back); row.addStretch()
        v.addLayout(row)
        return page

    def show_levels(self):
        self._user_picked = False
        self.pages.setCurrentIndex(1)
        self._fill_portfolios()
        self._show()
        if self.measured is None and (self._worker is None or not self._worker.isRunning()):
            self.status.setText("Measuring what each level really did since 2002…")
            self._worker = _GuideWorker()
            self._worker.done.connect(self._on_measured)
            self._worker.start()

    def _on_measured(self, measured, error):
        if measured is None:
            flag_problem(self.status, f"Could not measure the levels' history ({error}). "
                                      "The returns from the guidelines are still shown.")
            return
        self.measured = GuidePanel._measured_cache = measured
        self.status.setText(f"Measured on real prices since {measured[0]['since']}.")
        self._show()

    def answers(self) -> dict:
        return {"horizon": self.horizon.currentIndex(), "drop": self.drop.currentIndex(),
                "accounts": self.accounts.currentText(), "lump": self.lump.value(),
                "monthly": self.monthly.value(), "emergency": self.emergency.currentText(),
                "debt": self.debt.currentText()}

    def _show(self):
        a = self.answers()
        rec = g.recommend(a["horizon"], a["drop"], self.measured)
        self.recommended = rec["level"]
        self.why.setText(f"Your answers point to {g.LEVELS[rec['level']][0]}. {rec['why']}"
                         + (f" {rec['note']}" if rec["note"] else ""))
        steps = g.first_steps(a["emergency"], a["debt"], a["accounts"])
        self.steps.setText("Before you start: " + " ".join(steps) if steps else "")
        self.steps.setVisible(bool(steps))
        years = g.HORIZONS[a["horizon"]][1]
        self.table.setHorizontalHeaderItem(3, QTableWidgetItem(f"Your money in {years} years*"))
        invested = a["lump"] + a["monthly"] * 12 * years
        for r, (name, st, bo, ca) in enumerate(g.LEVELS):
            m = self.measured[r] if self.measured else None
            rate = g.expected_return(st, bo, ca)
            fv = g.future_value(a["lump"], a["monthly"], years, rate)
            cells = [("★ " if r == rec["level"] else "") + name,
                     f"{st:.0%} / {bo:.0%} / {ca:.0%}", f"{rate:.1%}",
                     f"{_money(fv)} (put in {_money(invested)})" if invested else "—",
                     f"{m['worst_fall']:.0%} ({m['worst_when']})" if m else "…",
                     f"{m['worst_12m']:+.0%}" if m else "…",
                     f"{m['worst_5y']:+.1%}" if m else "…"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if r == rec["level"]:
                    item.setBackground(QColor("#1f4f8a"))
                    item.setForeground(QColor("#ffffff"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        if not self._user_picked:
            self.table.selectRow(rec["level"])
        self._on_pick()

    def _picked(self) -> int:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else (self.recommended or 0)

    def _on_pick(self):
        if self.recommended is None:
            return
        level = self._picked()
        name, st, bo, ca = g.LEVELS[level]
        text = g.check_choice(level, self.recommended, self.measured)
        if not text:
            m = self.measured[level] if self.measured else None
            text = (f"{name}: {st:.0%} stocks, {bo:.0%} bonds, {ca:.0%} cash."
                    + (f" In its worst stretch, $10,000 became {_money(10_000 * (1 + m['worst_fall']))}."
                       if m else ""))
        self.choice.setText(text)

    def _fill_portfolios(self):
        names = []
        if self.db is not None:
            found = {str(p.get("portfolio") or "").strip() for p in self.db.positions()}
            found |= {str(c.get("portfolio") or "").strip() for c in self.db.cash()}
            found |= set(self.db.plan_targets())
            names = sorted(n for n in found if n)
        current = self.portfolio.currentText()
        self.portfolio.clear(); self.portfolio.addItems(names)
        if current:
            self.portfolio.setCurrentText(current)

    def use_level(self):
        level = self._picked()
        name, st, bo, ca = g.LEVELS[level]
        portfolio = self.portfolio.currentText().strip()
        if self.db is not None and portfolio:
            self.db.set_plan_target(portfolio, st * 100, bo * 100, ca * 100)
            if self.on_plan_changed:
                self.on_plan_changed()
        self._settings.setValue(PROFILE_KEY, json.dumps(
            {"answers": self.answers(), "level": level, "portfolio": portfolio,
             "saved": dt.date.today().isoformat()}))
        self._load_profile()
        where = (f" It is now {portfolio}'s target mix in the Plan tab, which shows what it "
                 f"would take to get there." if portfolio and self.db is not None else
                 " Pick a portfolio to make it that portfolio's target mix in the Plan tab.")
        self.status.setText(f"Saved: {name}.{where}")

    def _load_profile(self):
        try:
            saved = json.loads(self._settings.value(PROFILE_KEY, "", type=str) or "{}")
        except (ValueError, TypeError):
            saved = {}
        a = saved.get("answers") or {}
        for combo, key in ((self.horizon, "horizon"), (self.drop, "drop")):
            if isinstance(a.get(key), int):
                combo.setCurrentIndex(a[key])
        for combo, key in ((self.accounts, "accounts"), (self.emergency, "emergency"),
                           (self.debt, "debt")):
            if a.get(key):
                combo.setCurrentText(a[key])
        self.lump.setValue(float(a.get("lump") or 0))
        self.monthly.setValue(float(a.get("monthly") or 0))
        if saved.get("portfolio"):
            self.portfolio.setCurrentText(saved["portfolio"])
        level = saved.get("level")
        if isinstance(level, int) and 0 <= level < len(g.LEVELS):
            self.saved_line.setText(
                f"Your level: {g.LEVELS[level][0]} (chosen {saved.get('saved', '')}"
                + (f", for {saved['portfolio']}" if saved.get("portfolio") else "")
                + "). Go through the steps again any time.")
        else:
            self.saved_line.setText("")
        self.saved_line.setVisible(bool(self.saved_line.text()))

    def has_profile(self) -> bool:
        return bool(self._settings.value(PROFILE_KEY, "", type=str))

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.done.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._worker.wait(5000)
