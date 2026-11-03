"""The Plan tab: your investing plan, checked - the mixes, the trading cap and
the review rhythm you set, measured against what the accounts hold now."""
import datetime as dt
import json
import time

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDoubleSpinBox,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from tradelab.core import allocation_plan as ap
from tradelab.core import room
from tradelab.core.logging_config import get_logger
from tradelab.i18n import tr
from tradelab.data.database import Database
from tradelab.settings import app_settings
from tradelab.ui import theme
from tradelab.ui.common import StatusLabel, _hint, flag_problem, notify

log = get_logger(__name__)

TRADING_KEY = "Plan/tradingPortfolio"
CAP_KEY = "Plan/tradingCapPct"
REVIEW_KEY = "Plan/lastReview"
BUDGET_KEY = "RetirementSim/last_budget"
NOTIFIED_KEY = "Plan/lastNotified"
CLASS_CHOICES = ["auto", "stocks", "bonds", "cash", "other", ap.TRADING]


def return_text(mine, theirs, level_name, start, end) -> str:
    """The book's return, deposits left out, beside the level's over the same
    days - per year from a year on, as it was before that."""
    days = (end - start).days
    if mine is None:
        return tr("Your return: not enough recorded to measure yet.")
    since = tr("Since {date} ({days} days)").format(date=f"{start:%Y-%m-%d}", days=days)
    level = tr(level_name)
    if days >= 365:
        text = tr("{since}: your book did {mine} a year, your deposits left out").format(
            since=since, mine=f"{room.annualized(mine, days):+.1%}")
        if theirs is not None:
            text += tr("; {level} did {theirs} a year.").format(
                level=level, theirs=f"{room.annualized(theirs, days):+.1%}")
        return text + tr(" The past is no promise.")
    text = tr("{since}: your book {mine}, your deposits left out").format(
        since=since, mine=f"{mine:+.1%}")
    if theirs is not None:
        text += tr("; {level} {theirs} over the same days").format(level=level,
                                                                   theirs=f"{theirs:+.1%}")
    return text + tr(". Too short to judge - compare after a year.")


class _ReturnWorker(QThread):
    """The level's index funds over the recorded stretch, off the UI thread."""
    done = Signal(object)   # {symbol: prices} | None

    def __init__(self, period):
        super().__init__()
        self.period = period

    def run(self):
        out = None
        try:
            from tradelab.core import guide as g
            from tradelab.core.etf_metrics import get_prices
            out = {s: get_prices(s, self.period) for s in g.PROXIES}
        except Exception:
            log.debug("Return comparison prices failed", exc_info=True)
        try:
            self.done.emit(out)
        except RuntimeError:
            pass


class _PlanWorker(QThread):
    """Prices, FX and what each holding is, off the UI thread."""
    done = Signal(object, object, str)   # histories, metas, error

    def __init__(self, symbols, fx_symbols):
        super().__init__()
        self.symbols, self.fx_symbols = list(symbols), list(fx_symbols)

    def run(self):
        try:
            from tradelab.data.market_data import get_histories, get_quote_meta, with_latest_prices
            hist = get_histories(sorted(set(self.symbols) | set(self.fx_symbols)), "1mo", "1d")
            hist = with_latest_prices(hist, self.symbols)
            metas = {s: get_quote_meta(s) for s in self.symbols}
            self.done.emit(hist, metas, "")
        except Exception as exc:
            self.done.emit(None, None, str(exc) or type(exc).__name__)


class _CandidateWorker(QThread):
    """Everything the candidate check needs about one symbol, off the UI
    thread: ten years of prices, what it is, its dividends, what it holds -
    and what the funds you already own hold, for the overlap."""
    done = Signal(object, str)   # facts dict | None, error

    def __init__(self, symbol, owned_funds):
        super().__init__()
        self.symbol, self.owned_funds = symbol, list(owned_funds)

    def run(self):
        try:
            from tradelab.core.etf_metrics import dividend_yield, get_prices
            from tradelab.data.market_data import (get_dividends, get_fund_composition,
                                                   get_quote_meta)
            prices = get_prices(self.symbol, "11y")
            meta = get_quote_meta(self.symbol)
            divs = get_dividends(self.symbol)
            last = float(prices.iloc[-1]) if prices is not None and len(prices) else None
            comp = get_fund_composition(self.symbol) or {}
            owned_comps = {s: (get_fund_composition(s) or {}).get("top_holdings") or {}
                           for s in self.owned_funds}
            self.done.emit({"prices": prices, "meta": meta,
                            "yield": dividend_yield(divs, last) if last else None,
                            "holdings": comp.get("top_holdings") or {},
                            "owned_comps": owned_comps}, "")
        except Exception as exc:
            self.done.emit(None, str(exc) or type(exc).__name__)


class PlanPanel(QWidget):
    """The checklist: each account against the mix you chose, the trading side
    against its cap, the spending against the safe budget, the next review.
    It measures and shows; every choice in it is yours."""

    # The checklist just computed - Home shows it as one light.
    checked = Signal(object)

    def __init__(self, db: Database, settings=None):
        super().__init__()
        self.db = db
        self._settings = settings or app_settings()
        self._worker = None
        self._loaded_once = False
        self.holdings = []        # [{portfolio, symbol, value, split, auto}]
        self.cash_by_portfolio = {}
        self._metas = {}
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Your plan, checked. You set the mix each portfolio should hold, which portfolio "
            "is for trading and how big it may get; TradeLab shows how far each one is from "
            "it and what moving back would take in dollars. It never chooses a mix or a "
            "security - the moves shown are what it would take, not what to do."))

        top = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh"); self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn); top.addStretch()
        layout.addLayout(top)

        self.checklist = QListWidget(); self.checklist.setMaximumHeight(150)
        box = QGroupBox("Checklist"); v = QVBoxLayout(box); v.addWidget(self.checklist)
        # What the book really did, your deposits left out, beside your level.
        self.return_line = QLabel(""); self.return_line.setWordWrap(True)
        v.addWidget(self.return_line)
        layout.addWidget(box)

        targets = QGroupBox("Target mix per portfolio (your choice, %)")
        tv = QVBoxLayout(targets)
        self.targets = QTableWidget(0, 4)
        self.targets.setHorizontalHeaderLabels(["Portfolio", "Stocks %", "Bonds %", "Cash %"])
        self.targets.verticalHeader().setVisible(False)
        self.targets.setMaximumHeight(140)
        tv.addWidget(self.targets)
        row = QHBoxLayout()
        save = QPushButton("Save targets"); save.clicked.connect(self.save_targets)
        row.addWidget(save); row.addStretch()
        row.addWidget(QLabel("Trading portfolio"))
        self.trading = QComboBox()
        row.addWidget(self.trading)
        row.addWidget(QLabel("may be at most"))
        self.cap = QDoubleSpinBox(); self.cap.setRange(0, 100); self.cap.setDecimals(0)
        self.cap.setSuffix(" %")
        self.cap.setValue(float(self._settings.value(CAP_KEY, 10)))
        self.cap.setToolTip("A trading portfolio: at most this share of everything. Holdings set "
                            "to \"trading\" inside a portfolio: at most this share of that portfolio.")
        row.addWidget(self.cap)
        row.addWidget(QLabel("of everything - or of each portfolio, for holdings set to \"trading\""))
        self.trading.currentIndexChanged.connect(lambda _i: self._save_trading())
        self.cap.valueChanged.connect(lambda _v: self._save_trading())
        tv.addLayout(row)
        layout.addWidget(targets)

        rev = QHBoxLayout()
        self.review_line = QLabel("")
        reviewed = QPushButton("Mark reviewed today"); reviewed.clicked.connect(self.mark_reviewed)
        rev.addWidget(self.review_line, 1); rev.addWidget(reviewed)
        layout.addLayout(rev)

        layout.addWidget(self._room_box())

        layout.addWidget(QLabel("What each portfolio holds, by class (set a class by hand if "
                                "the automatic one is wrong, or \"trading\" for a swing trade - "
                                "it then stays out of the mix and counts against the trading cap)"))
        self.hold_table = QTableWidget(0, 4)
        self.hold_table.setHorizontalHeaderLabels(["Portfolio", "Symbol", "Value (CAD)", "Class"])
        self.hold_table.verticalHeader().setVisible(False)
        self.hold_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hold_table.setMaximumHeight(170)
        layout.addWidget(self.hold_table)

        layout.addWidget(QLabel("Against the target"))
        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(
            ["Portfolio", "Class", "Held (CAD)", "Held %", "Target %", "To get back"])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.result_table, 1)

        cand = QGroupBox("Candidate check - the facts before you buy")
        cv = QVBoxLayout(cand)
        crow = QHBoxLayout()
        self.cand_symbol = QLineEdit(); self.cand_symbol.setPlaceholderText("Symbol, e.g. XBB.TO")
        self.cand_symbol.setMaximumWidth(160)
        self.cand_symbol.returnPressed.connect(self.check_candidate)
        self.cand_account = QComboBox()
        check = QPushButton("Check"); check.clicked.connect(self.check_candidate)
        crow.addWidget(QLabel("Symbol")); crow.addWidget(self.cand_symbol)
        crow.addWidget(QLabel("for")); crow.addWidget(self.cand_account)
        crow.addWidget(check); crow.addStretch()
        cv.addLayout(crow)
        self.cand_list = QListWidget(); self.cand_list.setWordWrap(True)
        self.cand_list.setMinimumHeight(170)
        cv.addWidget(self.cand_list)
        cv.addWidget(_hint("Fees, risk band, worst fall, returns, overlap with what you own, the part "
                           "of your plan it adds to, and which account suits it - facts with their "
                           "basis, not a verdict. ⚠ marks something worth a second look."))
        layout.addWidget(cand)
        self._cand_worker = None
        self._return_worker = None
        self._return_args = None

        self.status = StatusLabel("Click Refresh to price your portfolios.")
        layout.addWidget(self.status)
        layout.addWidget(_hint(theme.NOT_ADVICE))
        self._load_targets()
        self._show_review()
        self._load_room()

    # --- CELI / REER room ----------------------------------------------------
    def _room_box(self):
        box = QGroupBox("Contribution room - CELI and REER")
        v = QVBoxLayout(box)
        v.addWidget(_hint(
            "Type the room CRA shows (My Account; for the REER, the deduction limit on your "
            "latest Notice of Assessment) and its date, then record each deposit and withdrawal "
            "you make - in every CELI or REER you have, group plans included. A CELI withdrawal "
            "comes back as room on January 1; the 2026 CELI limit of $7,000 is added on its "
            "January 1. An excess is taxed 1% a month (for the REER, beyond a $2,000 "
            "allowance) - canada.ca. The deposits also let the return above leave your own "
            "money out."))
        self.room_edits = {}
        for account in room.ACCOUNTS:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{account} room"))
            amount = QDoubleSpinBox(); amount.setRange(0, 10_000_000); amount.setDecimals(0)
            amount.setPrefix("$ "); amount.setGroupSeparatorShown(True)
            day = QDateEdit(); day.setCalendarPopup(True); day.setDisplayFormat("yyyy-MM-dd")
            day.setDate(QDate.currentDate())
            save = QPushButton("Save"); save.clicked.connect(lambda _c=False, a=account: self.save_room(a))
            row.addWidget(amount); row.addWidget(QLabel("as of")); row.addWidget(day)
            row.addWidget(save); row.addStretch()
            v.addLayout(row)
            self.room_edits[account] = (amount, day)
        row = QHBoxLayout()
        self.flow_day = QDateEdit(); self.flow_day.setCalendarPopup(True)
        self.flow_day.setDisplayFormat("yyyy-MM-dd"); self.flow_day.setDate(QDate.currentDate())
        self.flow_account = QComboBox(); self.flow_account.addItems(room.ACCOUNTS)
        self.flow_kind = QComboBox(); self.flow_kind.addItems(["Deposit", "Withdrawal"])
        self.flow_kind.setProperty("i18n", True)         # read by position
        self.flow_amount = QDoubleSpinBox(); self.flow_amount.setRange(0, 10_000_000)
        self.flow_amount.setDecimals(2); self.flow_amount.setPrefix("$ ")
        self.flow_amount.setGroupSeparatorShown(True)
        self.flow_note = QLineEdit(); self.flow_note.setPlaceholderText("note (optional)")
        record = QPushButton("Record"); record.clicked.connect(lambda: self.record_flow())
        for w in (self.flow_day, self.flow_account, self.flow_kind, self.flow_amount):
            row.addWidget(w)
        row.addWidget(self.flow_note, 1); row.addWidget(record)
        v.addLayout(row)
        self.flow_table = QTableWidget(0, 5)
        self.flow_table.setHorizontalHeaderLabels(["Date", "Account", "Kind", "Amount", "Note"])
        self.flow_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.flow_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.flow_table.verticalHeader().setVisible(False)
        self.flow_table.setMaximumHeight(130)
        v.addWidget(self.flow_table)
        row = QHBoxLayout()
        remove = QPushButton("Remove selected"); remove.clicked.connect(self.remove_flows)
        self.room_line = QLabel(""); self.room_line.setWordWrap(True)
        row.addWidget(self.room_line, 1); row.addWidget(remove)
        v.addLayout(row)
        return box

    def room_statuses(self, today=None):
        rooms = self.db.contribution_room()
        flows = self.db.contributions()
        return [room.status(a, rooms[a]["room"], rooms[a]["as_of"], flows, today)
                for a in room.ACCOUNTS if a in rooms]

    def _load_room(self):
        rooms = self.db.contribution_room()
        for account, (amount, day) in self.room_edits.items():
            if account in rooms:
                amount.setValue(float(rooms[account]["room"]))
                day.setDate(QDate.fromString(rooms[account]["as_of"], "yyyy-MM-dd"))
        flows = self.db.contributions()
        self.flow_table.setRowCount(len(flows))
        for r, f in enumerate(flows):
            cells = [f["day"], f["account"], "Deposit" if f["amount"] > 0 else "Withdrawal",
                     f"{abs(f['amount']):,.2f}", f.get("note") or ""]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, f["id"])
                self.flow_table.setItem(r, c, item)
        self.flow_table.resizeColumnsToContents()
        lines = [t for _k, t in room.check_items(self.room_statuses())]
        self.room_line.setText("  ".join(lines) if lines else tr("No room typed yet."))

    def save_room(self, account):
        amount, day = self.room_edits[account]
        self.db.set_contribution_room(account, amount.value(), day.date().toString("yyyy-MM-dd"))
        self._load_room()
        self.recompute()

    def record_flow(self, confirm=True):
        account = self.flow_account.currentText()
        amount = self.flow_amount.value()
        if amount <= 0:
            flag_problem(self.status, "Type the amount of the deposit or withdrawal.")
            return False
        deposit = self.flow_kind.currentIndex() == 0      # Deposit, Withdrawal
        day = self.flow_day.date().toString("yyyy-MM-dd")
        if deposit:
            current = next((s for s in self.room_statuses() if s["account"] == account), None)
            over = room.would_exceed(current, amount) if current else 0.0
            if over and confirm:
                taxed = ("taxed 1% a month while it stays" if account == room.CELI else
                         "taxed 1% a month on whatever is beyond the $2,000 allowance")
                answer = QMessageBox.question(
                    self, "Over your room",
                    f"This deposit goes ${over:,.0f} past your {account} room - {taxed}. "
                    f"Record it anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    return False
        self.db.add_contribution(account, day, amount if deposit else -amount,
                                 self.flow_note.text().strip())
        self.flow_amount.setValue(0); self.flow_note.clear()
        self._load_room()
        self.recompute()
        return True

    def remove_flows(self):
        rows = {i.row() for i in self.flow_table.selectionModel().selectedRows()}
        if not rows:
            flag_problem(self.status, "Select the deposits or withdrawals to remove.")
            return
        for r in rows:
            self.db.delete_contribution(self.flow_table.item(r, 0).data(Qt.UserRole))
        self._load_room()
        self.recompute()

    # --- your return against your level ---------------------------------------
    def _guide_level(self):
        from tradelab.ui.panels.guide import PROFILE_KEY
        try:
            level = json.loads(self._settings.value(PROFILE_KEY, "", type=str) or "{}").get("level")
        except (ValueError, TypeError):
            return None
        return level if isinstance(level, int) else None

    def compare_return(self):
        """Start the comparison: the recorded book against the Guide's level."""
        history = [h for h in self.db.value_history("CAD") if h.get("value")]
        level = self._guide_level()
        if len(history) < 2:
            self.return_line.setText(tr("Your return: TradeLab needs a few days of recorded values "
                                        "first (Home records one each day it prices your book)."))
            return
        if level is None:
            self.return_line.setText(tr("Your return: choose a level in the Guide to compare it with."))
            return
        if self._return_worker is not None and self._return_worker.isRunning():
            return
        start, end = history[0]["day"], history[-1]["day"]
        self._return_args = (history[0], history[-1], level)
        days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
        self._return_worker = _ReturnWorker("2y" if days < 700 else "max")
        self._return_worker.done.connect(self._on_return)
        self._return_worker.start()

    def _on_return(self, prices):
        from tradelab.core import guide as g
        first, last, level = self._return_args
        start, end = dt.date.fromisoformat(first["day"]), dt.date.fromisoformat(last["day"])
        flows = [(f["day"], f["amount"]) for f in self.db.contributions()]
        mine = room.modified_dietz(first["value"], last["value"], flows, start, end)
        theirs = g.level_growth(prices or {}, level, start, end) if prices else None
        self.return_line.setText(return_text(mine, theirs, g.LEVELS[level][0], start, end))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded_once and self.db.positions():
            self.refresh()

    # --- inputs --------------------------------------------------------------
    def portfolios(self) -> list:
        return self.db.portfolio_names()

    def _load_targets(self):
        saved = self.db.plan_targets()
        names = self.portfolios()
        self.targets.setRowCount(len(names))
        for r, name in enumerate(names):
            item = QTableWidgetItem(name); item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.targets.setItem(r, 0, item)
            t = saved.get(name) or {}
            for c, cls in enumerate(ap.TARGET_CLASSES, start=1):
                value = t.get(cls)
                self.targets.setItem(r, c, QTableWidgetItem("" if value is None else f"{value:g}"))
        self.targets.resizeColumnsToContents()
        chosen = self.cand_account.currentText() if hasattr(self, "cand_account") else ""
        if hasattr(self, "cand_account"):
            self.cand_account.clear(); self.cand_account.addItems(names or ["(no portfolio)"])
            if chosen in names:
                self.cand_account.setCurrentText(chosen)
        current = str(self._settings.value(TRADING_KEY, "") or "")
        self.trading.blockSignals(True)
        self.trading.clear(); self.trading.addItems(["(none)"] + names)
        self.trading.setCurrentText(current if current in names else "(none)")
        self.trading.blockSignals(False)

    def save_targets(self):
        problems = []
        for r in range(self.targets.rowCount()):
            name = self.targets.item(r, 0).text()
            texts = [(self.targets.item(r, c).text().strip() if self.targets.item(r, c) else "")
                     for c in (1, 2, 3)]
            if not any(texts):
                self.db.delete_plan_target(name)
                continue
            try:
                values = [float(t.replace("%", "").replace(",", ".") or 0) for t in texts]
            except ValueError:
                problems.append(f"{name}: not a number")
                continue
            target = dict(zip(ap.TARGET_CLASSES, values))
            why = ap.check_target(target)
            if why:
                problems.append(f"{name}: {why}")
                continue
            self.db.set_plan_target(name, *values)
        if problems:
            flag_problem(self.status, "Some targets were not saved: " + "; ".join(problems))
        else:
            self.status.setText(tr("Targets saved."))
        self.recompute()

    def _save_trading(self):
        name = self.trading.currentText()
        self._settings.setValue(TRADING_KEY, "" if name == "(none)" else name)
        self._settings.setValue(CAP_KEY, self.cap.value())
        self._settings.sync()
        self.recompute()

    def mark_reviewed(self):
        self._settings.setValue(REVIEW_KEY, dt.date.today().isoformat())
        self._settings.sync()
        self._show_review()
        self.recompute()

    def _last_review(self):
        try:
            return dt.date.fromisoformat(str(self._settings.value(REVIEW_KEY, "") or ""))
        except ValueError:
            return None

    def _show_review(self):
        due = ap.review_due(self._last_review())
        if due["last"] is None:
            self.review_line.setText(tr("No review recorded yet."))
        else:
            self.review_line.setText(tr("Last review {last}; next around {next} (about every "
                                        "quarter).").format(last=f"{due['last']:%Y-%m-%d}",
                                                            next=f"{due['next']:%Y-%m-%d}"))

    # --- prices --------------------------------------------------------------
    def refresh(self):
        from tradelab.core.portfolio_analytics import currency_of, fx_pair_symbol
        if self._worker is not None and self._worker.isRunning():
            return
        self._loaded_once = True
        self._load_targets()
        positions = self.db.positions()
        symbols = sorted({str(p["symbol"]).upper() for p in positions})
        ccys = {currency_of(s) for s in symbols} | {str(c["currency"]).upper() for c in self.db.cash()}
        self._fx_pairs = {c: fx_pair_symbol(c, "CAD") for c in ccys if c != "CAD"}
        if not symbols and not self.db.cash():
            self.status.setText(tr("No portfolios yet - add positions in the Portfolio tab."))
            self.recompute()
            return
        if not symbols and not self._fx_pairs:
            self._on_priced({}, {}, "")          # cash only, in CAD: nothing to price
            return
        self.status.setText(tr("Pricing your portfolios…"))
        self._worker = _PlanWorker(symbols, self._fx_pairs.values())
        self._worker.done.connect(self._on_priced)
        self._worker.start()

    def _on_priced(self, histories, metas, err):
        from tradelab.core import portfolio_analytics as pa
        from tradelab.data.market_data import is_synthetic
        if err or histories is None:
            flag_problem(self.status, f"Could not price the portfolios: {err or 'no data'}")
            return
        self._metas = metas or {}
        histories = {s: df for s, df in histories.items() if df is not None and not is_synthetic(df)}
        fx = {c: histories.get(sym) for c, sym in self._fx_pairs.items()}
        etfs = self.db.etf_list()
        overrides = self.db.asset_class_overrides()
        self.holdings, missing = [], []
        by_portfolio = {}
        for p in self.db.positions():
            by_portfolio.setdefault(str(p.get("portfolio") or ""), []).append(p)
        for name, positions in by_portfolio.items():
            rows, _total = pa.holdings(positions, histories, "CAD", fx)
            for h in rows:
                if h.get("market_value") is None or not h.get("converted"):
                    missing.append(h["symbol"])
                    continue
                sym = h["symbol"]
                self.holdings.append({
                    "portfolio": name, "symbol": sym, "value": float(h["market_value"]),
                    "split": ap.split_of(sym, etfs, overrides.get(sym), (metas or {}).get(sym)),
                    "auto": sym not in overrides})
        cash_rows, _ = pa.cash_rows(self.db.cash(), "CAD", fx)
        self.cash_by_portfolio = {}
        for c in cash_rows:
            self.cash_by_portfolio[c["portfolio"]] = self.cash_by_portfolio.get(c["portfolio"], 0.0) + c["value"]
        self.status.setText(f"Priced {time.strftime('%H:%M')}."
                            + (f" Left out, no price: {', '.join(sorted(set(missing)))}." if missing else ""))
        if missing:
            flag_problem(self.status, "These holdings could not be priced and are left out of the "
                                      "plan check: " + ", ".join(sorted(set(missing))))
        self._fill_holdings()
        self.recompute()
        self.compare_return()

    def _fill_holdings(self):
        self.hold_table.setRowCount(len(self.holdings))
        for r, h in enumerate(self.holdings):
            for c, text in enumerate((h["portfolio"], h["symbol"], f"{h['value']:,.0f}")):
                self.hold_table.setItem(r, c, QTableWidgetItem(text))
            combo = QComboBox(); combo.addItems(CLASS_CHOICES)
            split = h["split"]
            label = (" / ".join(f"{k} {v:.0%}" for k, v in split.items()) if len(split) > 1
                     else next(iter(split)))
            combo.setItemText(0, f"auto ({label})" if h["auto"] else "auto")
            combo.setCurrentIndex(0 if h["auto"] else CLASS_CHOICES.index(next(iter(split))))
            combo.currentIndexChanged.connect(lambda i, sym=h["symbol"]: self._set_class(sym, i))
            self.hold_table.setCellWidget(r, 3, combo)
        self.hold_table.resizeColumnsToContents()

    def _set_class(self, symbol, index):
        self.db.set_asset_class(symbol, None if index == 0 else CLASS_CHOICES[index])
        etfs, overrides = self.db.etf_list(), self.db.asset_class_overrides()
        for h in self.holdings:
            if h["symbol"] == symbol:
                if index == 0:
                    h["split"] = ap.split_of(symbol, etfs, None, self._metas.get(symbol))
                    h["auto"] = True
                else:
                    h["split"] = {CLASS_CHOICES[index]: 1.0}
                    h["auto"] = False
        self.recompute()

    # --- the check -----------------------------------------------------------
    def recompute(self):
        targets = self.db.plan_targets()
        names = sorted({h["portfolio"] for h in self.holdings} | set(self.cash_by_portfolio)
                       | set(targets))
        items, table_rows = [], []
        totals, trades = {}, {}
        for name in names:
            held = [h for h in self.holdings if h["portfolio"] == name]
            mix = ap.current_mix(held, self.cash_by_portfolio.get(name, 0.0))
            trades[name] = ap.trading_in(held)
            totals[name] = sum(mix.values()) + trades[name]
            if trades[name]:
                t = ap.trading_check(trades[name], totals[name], self.cap.value())
                fields = {"cap": f"{t['cap_pct']:.0f}%", "room": f"${abs(t['room']):,.0f}"}
                verdict = (tr("above its {cap} cap by {room}") if t["over"]
                           else tr("inside its {cap} cap ({room} of room)")).format(**fields)
                items.append(("warn" if t["over"] else "ok",
                              tr("{name}: swing trades {amount} are {share} of the portfolio, "
                                 "{verdict}.").format(name=name, amount=f"${trades[name]:,.0f}",
                                                      share=f"{t['share_pct']:.1f}%",
                                                      verdict=verdict)))
            target = targets.get(name)
            if not target:
                if totals[name]:
                    items.append(("info", tr("{name}: no target mix set - type one above.")
                                  .format(name=name)))
                continue
            if not sum(mix.values()):
                # Nothing in it yet: nothing is off target, and there is nothing to move.
                items.append(("info", tr("{name}: empty - its target mix applies once money is "
                                         "in it.").format(name=name)))
                continue
            result = ap.rebalance(mix, target)
            deploy = ap.deploy_cash(mix, target)
            if deploy["investable"] >= max(500.0, totals[name] * 0.01):
                parts = [f"${v:,.0f} {tr(c)}" for c, v in deploy["buys"].items() if v >= 1]
                items.append(("info", tr("{name}: {amount} of cash beyond your target cash share - "
                                         "by your target mix, putting it to work without selling "
                                         "anything would mean {parts}. Pick the funds with the "
                                         "candidate check below.").format(
                    name=name, amount=f"${deploy['investable']:,.0f}", parts=", ".join(parts))))
            for row in result["rows"]:
                if row["value"] or row["target_pct"]:
                    table_rows.append((name, row))
            if result["drifted"]:
                moves = [(tr("buy") if r["change"] > 0 else tr("sell"))
                         + f" ${abs(r['change']):,.0f} {tr(r['class'])}"
                         for r in result["rows"] if abs(r["change"]) >= 1
                         and r["class"] in result["drifted"]]
                gaps = ", ".join(f"{tr(r['class'])} {r['pct']:.0f}% vs {r['target_pct']:.0f}%"
                                 for r in result["rows"] if r["class"] in result["drifted"])
                items.append(("warn", tr("{name}: off its target ({gaps}) - getting back would "
                                         "take: {moves}.").format(name=name, gaps=gaps,
                                                                  moves="; ".join(moves))))
            else:
                worst = max(abs(r["drift_pp"]) for r in result["rows"])
                items.append(("ok", tr("{name}: on target (largest gap {gap} points).")
                              .format(name=name, gap=f"{worst:.0f}")))
        trading = str(self._settings.value(TRADING_KEY, "") or "")
        whole = sum(totals.values())
        if trading and whole:
            t = ap.trading_check(totals.get(trading, 0.0), whole, self.cap.value())
            fields = {"name": trading, "share": f"{t['share_pct']:.1f}%", "cap": f"{t['cap_pct']:.0f}%",
                      "room": f"${abs(t['room']):,.0f}"}
            if t["over"]:
                items.append(("warn", tr("Trading ({name}) is {share} of everything, above its "
                                         "{cap} cap by {room}.").format(**fields)))
            else:
                items.append(("ok", tr("Trading ({name}) is {share} of everything, inside its "
                                       "{cap} cap ({room} of room).").format(**fields)))
        elif whole and not any(trades.values()):
            items.append(("info", tr("No trading portfolio chosen and no holding set to "
                                     "\"trading\" - do one or the other to keep trading capped.")))
        try:
            items += room.check_items(self.room_statuses())
        except Exception:
            log.exception("The contribution room could not be checked")
        items.append(self._budget_item())
        due = ap.review_due(self._last_review())
        items.append(("warn", tr("Review due: go through this list, then Mark reviewed today."))
                     if due["due"] else
                     ("ok", tr("Next review around {date} ({days} days).").format(
                         date=f"{due['next']:%Y-%m-%d}", days=due["days_left"])))
        self._show(items, table_rows)

    def _budget_item(self):
        try:
            b = json.loads(self._settings.value(BUDGET_KEY, "") or "null")
        except (TypeError, ValueError):
            b = None
        if not b:
            return ("info", tr("Safe budget not checked yet - Retirement Sim → Safe budget."))
        fields = {"spending": f"${b['spending']:,.0f}", "safe": f"${b['safe']:,.0f}",
                  "checked": b["checked"]}
        if b["spending"] > b["safe"]:
            # "alert": a warning serious enough to turn Home's light red.
            return ("alert", tr("Spending {spending} is above the safe budget of {safe} a year "
                                "(checked {checked}).").format(**fields))
        return ("ok", tr("Spending {spending} is under the safe budget of {safe} a year "
                         "(checked {checked}).").format(**fields))

    def startup_check(self):
        """At launch: check the plan, and if anything wants a look, say so in a
        Windows notification - at most once a day."""
        self._notify_when_done = True
        self.refresh()

    def _maybe_notify(self, items):
        if not getattr(self, "_notify_when_done", False):
            return
        self._notify_when_done = False
        warns = [text for kind, text in items if kind in ("warn", "alert")]
        today = dt.date.today().isoformat()
        if not warns or str(self._settings.value(NOTIFIED_KEY, "")) == today:
            return
        title = tr("TradeLab - {n} thing(s) to look at in your plan").format(n=len(warns))
        if notify(title, warns[0] + (tr(" (and more in the Plan tab)") if len(warns) > 1 else "")):
            self._settings.setValue(NOTIFIED_KEY, today)
            self._settings.sync()

    def _show(self, items, table_rows):
        self._maybe_notify(items)
        self.check_items = items
        self.checked.emit(list(items))
        self.checklist.clear()
        marks = {"ok": ("✓", theme.UP), "warn": ("⚠", theme.WARN), "alert": ("⚠", theme.DOWN),
                 "info": ("•", theme.MUTED)}
        for kind, text in items:
            mark, colour = marks[kind]
            entry = QListWidgetItem(f"{mark}  {text}")
            entry.setForeground(QColor(colour))
            self.checklist.addItem(entry)
        self.result_table.setRowCount(len(table_rows))
        for r, (name, row) in enumerate(table_rows):
            change = row["change"]
            cells = [name, row["class"], f"{row['value']:,.0f}", f"{row['pct']:.1f}%",
                     f"{row['target_pct']:.0f}%",
                     "-" if abs(change) < 1 else f"{'buy' if change > 0 else 'sell'} ${abs(change):,.0f}"]
            for c, text in enumerate(cells):
                self.result_table.setItem(r, c, QTableWidgetItem(text))
        self.result_table.resizeColumnsToContents()

    # --- the candidate check -------------------------------------------------------
    def check_candidate(self):
        symbol = self.cand_symbol.text().strip().upper()
        if not symbol:
            flag_problem(self.status, "Type a symbol to check (e.g. XBB.TO).")
            return
        if self._cand_worker is not None and self._cand_worker.isRunning():
            return
        owned_funds = sorted({str(p["symbol"]).upper() for p in self.db.positions()})
        self.cand_list.clear()
        self.cand_list.addItem(f"Checking {symbol}…")
        self._cand_symbol = symbol
        self._cand_worker = _CandidateWorker(symbol, owned_funds)
        self._cand_worker.done.connect(self._on_candidate)
        self._cand_worker.start()

    def owned_map(self, owned_comps: dict) -> dict:
        """{company symbol: where you own it} - directly, or inside a fund."""
        owned = {}
        for p in self.db.positions():
            sym = str(p["symbol"]).upper()
            owned.setdefault(sym, f"{p.get('portfolio')}")
        for fund, top in (owned_comps or {}).items():
            for sym in top:
                owned.setdefault(str(sym).upper(), f"inside {fund}")
        return owned

    def _on_candidate(self, facts, err):
        from tradelab.core.candidate import assess
        symbol = getattr(self, "_cand_symbol", "")
        if err or not facts:
            self.cand_list.clear()
            flag_problem(self.status, f"Could not check {symbol}: {err or 'no data'}")
            return
        prices = facts.get("prices")
        if prices is None and not (facts.get("meta") or {}).get("quote_type"):
            self.cand_list.clear()
            flag_problem(self.status, f"{symbol}: no data found - check the symbol (a Canadian "
                                      "listing ends in .TO).")
            return
        etfs = self.db.etf_list()
        screener = next((r for r in etfs if symbol in {str(r.get("ticker") or "").upper(),
                                                         str(r.get("yahoo") or "").upper()}), None)
        meta = facts.get("meta") or {}
        mer = screener.get("mer") if screener else None
        mer_source = "ETF Screener" if mer is not None else ""
        if mer is None and meta.get("expense_ratio") is not None:
            mer, mer_source = meta["expense_ratio"], "Yahoo"
        split = ap.split_of(symbol, etfs, self.db.asset_class_overrides().get(symbol), meta)
        account = self.cand_account.currentText()
        if account == "(no portfolio)":
            account = None
        account_rows = None
        target = self.db.plan_targets().get(account) if account else None
        if account and target:
            mix = ap.current_mix([h for h in self.holdings if h["portfolio"] == account],
                                 self.cash_by_portfolio.get(account, 0.0))
            if sum(mix.values()):
                account_rows = ap.rebalance(mix, target)["rows"]
        holdings = facts.get("holdings") or ({symbol: 1.0} if meta.get("quote_type") == "EQUITY" else {})
        items = assess(symbol, prices, meta, mer=mer, mer_source=mer_source,
                       dividend_yield=facts.get("yield"),
                       holdings=holdings, owned=self.owned_map(facts.get("owned_comps")),
                       split=split, account=account, account_rows=account_rows)
        self.candidate_items = items
        self.cand_list.clear()
        marks = {"ok": ("✓", theme.UP), "warn": ("⚠", theme.WARN), "info": ("•", theme.TEXT)}
        for kind, label, text in items:
            mark, colour = marks[kind]
            entry = QListWidgetItem(f"{mark}  {label}: {text}")
            entry.setForeground(QColor(colour))
            self.cand_list.addItem(entry)
        self.status.setText(f"Checked {symbol} at {time.strftime('%H:%M')}. Facts, not advice.")

    def shutdown(self):
        for worker in (self._worker, self._cand_worker, self._return_worker):
            if worker is not None and worker.isRunning():
                worker.wait(5000)
