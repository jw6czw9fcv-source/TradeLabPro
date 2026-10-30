"""The Guide tab: a beginner's path, one step at a time. Step 1 asks about the
person, step 2 shows the levels with what they returned and what they lost -
the one chosen becomes the Plan tab's target mix - and step 3 checks the ETFs
that could hold it, side by side."""
import datetime as dt
import json
import re

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from tradelab.core import guide as g
from tradelab.core.candidate import is_us_listed
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


class _FundsWorker(QThread):
    """The candidate check's data for each fund, off the UI thread."""
    done = Signal(object, object)   # {symbol: gathered}, [errors]

    def __init__(self, symbols):
        super().__init__()
        self.symbols = list(symbols)

    def run(self):
        from tradelab.core.candidate import gather
        out, errors = {}, []
        for symbol in self.symbols:
            try:
                info = gather(symbol)
                if info.get("prices") is None and not (info.get("meta") or {}).get("quote_type"):
                    errors.append(f"{symbol}: no data (a Canadian listing ends in .TO)")
                    continue
                out[symbol] = info
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
        try:
            self.done.emit(out, errors)
        except RuntimeError:
            pass


class _PriceWorker(QThread):
    """The last close of each fund, and USD/CAD when a US listing needs it."""
    done = Signal(object, object, object)   # {symbol: price}, fx | None, [errors]

    def __init__(self, symbols, need_fx):
        super().__init__()
        self.symbols, self.need_fx = list(symbols), bool(need_fx)

    def run(self):
        from tradelab.core.etf_metrics import get_prices
        prices, errors, fx = {}, [], None
        for symbol in self.symbols + ([g.FX] if self.need_fx else []):
            try:
                series = get_prices(symbol, "1mo")
                if series is None or not len(series):
                    raise ValueError("no price")
                if symbol == g.FX:
                    fx = float(series.iloc[-1])
                else:
                    prices[symbol] = float(series.iloc[-1])
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
        try:
            self.done.emit(prices, fx, errors)
        except RuntimeError:
            pass


def _money(v):
    return f"${v:,.0f}"


class GuidePanel(QWidget):
    """Step by step: about you, then your level. It explains and measures;
    the person chooses."""

    _measured_cache = None   # one download a session is enough
    _facts_cache = {}        # the funds checked this session

    def __init__(self, db=None, settings=None, on_plan_changed=None):
        super().__init__()
        self.db = db
        self._settings = settings or app_settings()
        self.on_plan_changed = on_plan_changed
        self._worker = None
        self.measured = GuidePanel._measured_cache
        self.recommended = None
        self._user_picked = False   # a level clicked stays picked when the records arrive
        self._funds_worker = None
        self._funds_pending = False
        self._fund_facts = GuidePanel._facts_cache   # {symbol: candidate facts row}
        self._fund_symbols = []
        self.picks = []              # [[symbol, class]] - My funds
        self.weights_pct = {}        # {symbol: %} set by hand in step 4
        self._prices, self._fx = {}, None
        self._price_worker = None
        self._buy_touched = False
        self._saved_level = None
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
        self.pages.addWidget(self._funds_page())
        self.pages.addWidget(self._purchases_page())
        layout.addWidget(self.pages, 1)
        self._load_profile()

    # -- step 1 --
    def _about_you_page(self):
        page = QWidget(); v = QVBoxLayout(page)
        title = QLabel("Step 1 of 4 - About you"); title.setFont(QFont(title.font().family(), 13, QFont.Bold))
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
        title = QLabel("Step 2 of 4 - Your level"); title.setFont(QFont(title.font().family(), 13, QFont.Bold))
        v.addWidget(title)
        self.why = QLabel(""); self.why.setWordWrap(True)
        self.why.setStyleSheet("font-weight:bold;")
        v.addWidget(self.why)
        self.steps = QLabel(""); self.steps.setWordWrap(True)
        self.steps.setStyleSheet("color:#c9a227;")
        v.addWidget(self.steps)
        self.status = StatusLabel(); self.status.setStyleSheet("color:#8a9099;")
        v.addWidget(self.status)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Period"))
        self.basis = QComboBox(); self.basis.addItems(g.BASES)
        self.basis.currentIndexChanged.connect(lambda _i: self._show())
        brow.addWidget(self.basis)
        self.period_note = QLabel(""); self.period_note.setWordWrap(True)
        brow.addWidget(self.period_note, 1)
        v.addLayout(brow)
        self.table = QTableWidget(len(g.LEVELS), 8)
        self.table.setHorizontalHeaderLabels(
            ["Level", "Stocks / bonds / cash", "Did a year", "Guidelines, a year*",
             "Your money in … years", "Worst fall (when)", "Worst 12 months",
             "Worst 5 years, a year"])
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
            "What each level really did, in CAD, over the period you pick: "
            "index funds in a typical global mix (Canada 30%, US 45%, international 20%, "
            "emerging 5% - XIU, SPY, EFA, EEM, the US-listed ones at each month's exchange rate, "
            "unhedged as an all-in-one ETF holds them), bonds XBB, cash at a steady 2.4%, "
            "rebalanced monthly. They stand in for stocks and bonds and are not picks. "
            f"* The {g.GUIDELINES} are what financial planners are told to assume - deliberately "
            f"cautious, less a {g.INDEX_FEE:.2%} fee. The last 10 years were unusually strong "
            "for US stocks, and a short period can miss a crash entirely: the level marked ★ is "
            "always judged on the worst fall since 2003, 2008 included, because one like it can "
            "come again. The past is no promise. " + theme.NOT_ADVICE))
        row = QHBoxLayout()
        back = QPushButton("←  Back"); back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        row.addWidget(back); row.addStretch()
        nxt = QPushButton("Next: your funds  →"); nxt.clicked.connect(self.show_funds)
        row.addWidget(nxt)
        v.addLayout(row)
        return page

    # -- step 3 --
    def _funds_page(self):
        from tradelab.core.candidate import SORTS
        page = QWidget(); v = QVBoxLayout(page)
        title = QLabel("Step 3 of 4 - Your funds"); title.setFont(QFont(title.font().family(), 13, QFont.Bold))
        v.addWidget(title)
        self.funds_intro = QLabel(""); self.funds_intro.setWordWrap(True)
        self.funds_intro.setStyleSheet("font-weight:bold;")
        v.addWidget(self.funds_intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show"))
        self.fund_set = QComboBox(); self.fund_set.setMinimumWidth(240)
        self.fund_set.currentIndexChanged.connect(lambda _i: self.check_funds())
        row.addWidget(self.fund_set)
        row.addWidget(QLabel("Also check"))
        self.fund_extra = QLineEdit(); self.fund_extra.setPlaceholderText("other symbols, e.g. VDY.TO")
        self.fund_extra.returnPressed.connect(self.check_funds)
        row.addWidget(self.fund_extra, 1)
        row.addWidget(QLabel("Order by"))
        self.fund_sort = QComboBox(); self.fund_sort.addItems([s[0] for s in SORTS])
        self.fund_sort.currentIndexChanged.connect(lambda _i: self._show_funds())
        row.addWidget(self.fund_sort)
        check = QPushButton("Check"); check.clicked.connect(self.check_funds)
        row.addWidget(check)
        v.addLayout(row)
        self.fund_note = QLabel(""); self.fund_note.setWordWrap(True)
        v.addWidget(self.fund_note)
        self.fund_status = StatusLabel(); self.fund_status.setStyleSheet("color:#8a9099;")
        v.addWidget(self.fund_status)
        self.fund_table = QTableWidget(0, 10)
        self.fund_table.setHorizontalHeaderLabels(
            ["Symbol", "Name", "Fees/yr", "Risk (CSA)", "Worst fall (when)", "1 yr", "5 yr, a year",
             "10 yr, a year", "Account", "Morningstar"])
        self.fund_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fund_table.verticalHeader().setVisible(False)
        self.fund_table.setMinimumHeight(170)
        self.fund_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fund_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.fund_table)
        prow = QHBoxLayout()
        pick = QPushButton("Add selected to my funds  ↓"); pick.clicked.connect(self.pick_funds)
        unpick = QPushButton("Remove from my funds"); unpick.clicked.connect(self.unpick_funds)
        prow.addWidget(pick); prow.addWidget(unpick); prow.addStretch()
        v.addLayout(prow)
        v.addWidget(QLabel("My funds - what step 4 buys"))
        self.picks_list = QListWidget(); self.picks_list.setMaximumHeight(110)
        self.picks_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.picks_list)
        v.addWidget(_hint(
            "One fund for your level holds stocks and bonds in that mix and rebalances itself - "
            "the least work, and the fewest ways to go wrong. Building blocks are one fund per "
            "part (cash, bonds, Canadian, US, international stocks): more control, and you "
            "rebalance them yourself - the Plan tab shows when. The candidates are broad index "
            "ETFs from three providers, side by side; returns include dividends, in CAD. "
            "Account: \"REER\" when a US-listed fund's dividends would lose 15% to US tax in a "
            "CELI. TradeLab orders them by what you choose and never picks. " + theme.NOT_ADVICE))
        row = QHBoxLayout()
        back = QPushButton("←  Back"); back.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        row.addWidget(back); row.addStretch()
        nxt = QPushButton("Next: your purchases  →"); nxt.clicked.connect(self.show_purchases)
        row.addWidget(nxt)
        v.addLayout(row)
        return page

    def pick_funds(self):
        i = self.fund_set.currentIndex()
        cls = g.ALL if i <= 0 else g.BLOCKS[i - 1][1]
        rows = sorted({idx.row() for idx in self.fund_table.selectionModel().selectedRows()})
        symbols = [self.fund_table.item(r, 0).text() for r in rows if self.fund_table.item(r, 0)]
        if not symbols:
            flag_problem(self.fund_status, "Select one or more funds in the table first.")
            return
        have = {s for s, _c in self.picks}
        self.picks += [[s, cls] for s in symbols if s not in have]
        self._picks_changed()

    def unpick_funds(self):
        gone = {self.picks_list.item(i.row()).data(Qt.UserRole)
                for i in self.picks_list.selectedIndexes()}
        if not gone:
            flag_problem(self.fund_status, "Select funds in My funds to remove.")
            return
        self.picks = [p for p in self.picks if p[0] not in gone]
        self._picks_changed()

    def _picks_changed(self):
        self.weights_pct = {}          # back to the level's shares
        self._show_picks()
        self._save_funds()

    def _show_picks(self):
        kinds = {g.ALL: "the whole level", "stocks": "stocks", "bonds": "bonds", "cash": "cash"}
        self.picks_list.clear()
        for symbol, cls in self.picks:
            item = QListWidgetItem(f"{symbol}  -  {kinds.get(cls, cls)}")
            item.setData(Qt.UserRole, symbol)
            self.picks_list.addItem(item)

    # -- step 4 --
    def _purchases_page(self):
        page = QWidget(); v = QVBoxLayout(page)
        title = QLabel("Step 4 of 4 - Your purchases"); title.setFont(QFont(title.font().family(), 13, QFont.Bold))
        v.addWidget(title)
        form = QHBoxLayout()
        self.buy_portfolio = QLabel("")
        form.addWidget(self.buy_portfolio)
        form.addWidget(QLabel("Invest now"))
        self.buy_now = QDoubleSpinBox(); self.buy_now.setRange(0, 100_000_000); self.buy_now.setDecimals(0)
        self.buy_now.setSingleStep(1000); self.buy_now.setPrefix("$ "); self.buy_now.setGroupSeparatorShown(True)
        form.addWidget(self.buy_now)
        use_cash = QPushButton("Use its recorded cash"); use_cash.clicked.connect(self.use_recorded_cash)
        form.addWidget(use_cash)
        form.addWidget(QLabel("then each month"))
        self.buy_monthly = QDoubleSpinBox(); self.buy_monthly.setRange(0, 1_000_000); self.buy_monthly.setDecimals(0)
        self.buy_monthly.setSingleStep(50); self.buy_monthly.setPrefix("$ "); self.buy_monthly.setGroupSeparatorShown(True)
        form.addWidget(self.buy_monthly)
        form.addStretch()
        v.addLayout(form)
        self.buy_now.valueChanged.connect(lambda _v: self._show_purchases())
        self.buy_monthly.valueChanged.connect(lambda _v: self._show_purchases())
        self.buy_note = QLabel(""); self.buy_note.setWordWrap(True); self.buy_note.setStyleSheet("color:#c9a227;")
        v.addWidget(self.buy_note)
        self.buy_status = StatusLabel(); self.buy_status.setStyleSheet("color:#8a9099;")
        v.addWidget(self.buy_status)
        self.buy_table = QTableWidget(0, 8)
        self.buy_table.setHorizontalHeaderLabels(
            ["Fund", "For", "Share %", "Price", "Held now", "Buy now", "Cost", "Then each month"])
        self.buy_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.buy_table.verticalHeader().setVisible(False)
        self.buy_table.setMinimumHeight(170)
        v.addWidget(self.buy_table)
        self.buy_summary = QLabel(""); self.buy_summary.setWordWrap(True)
        self.buy_summary.setStyleSheet("font-weight:bold;")
        v.addWidget(self.buy_summary)
        brow = QHBoxLayout()
        copy = QPushButton("Copy the list"); copy.clicked.connect(self.copy_purchases)
        brow.addWidget(copy); brow.addStretch()
        v.addLayout(brow)
        v.addWidget(_hint(
            "Whole shares only, at the last closing price - the price will have moved a little "
            "when you buy. Each fund below its share gets the money first, so nothing has to be "
            "sold; what is left stays as cash. Place the orders yourself at your broker (a limit "
            "order near the price shown keeps a surprise out); TradeLab never trades. The "
            "monthly line assumes today's purchase is made. A fund listed in the US is priced in "
            "CAD at today's exchange rate. " + theme.NOT_ADVICE))
        row = QHBoxLayout()
        back = QPushButton("←  Back"); back.clicked.connect(lambda: self.pages.setCurrentIndex(2))
        row.addWidget(back); row.addStretch()
        v.addLayout(row)
        return page

    def _target_portfolio(self) -> str:
        return self.portfolio.currentText().strip()

    def show_purchases(self):
        if not self.picks:
            flag_problem(self.fund_status, "Add at least one fund to My funds first (select it "
                                           "in the table, then Add selected to my funds).")
            return
        self.pages.setCurrentIndex(3)
        portfolio = self._target_portfolio()
        self.buy_portfolio.setText(f"For {portfolio}:" if portfolio else "For your account:")
        if not self.buy_now.value() and not self._buy_touched:
            self.buy_now.setValue(self.lump.value())
        if not self.buy_monthly.value() and not self._buy_touched:
            self.buy_monthly.setValue(self.monthly.value())
        self._buy_touched = True
        missing = [s for s, _c in self.picks if s not in self._prices]
        need_fx = any(is_us_listed(s) for s, _c in self.picks) and self._fx is None
        held = self._held_symbols()
        missing += [s for s in held if s not in self._prices and s not in missing]
        self._show_purchases()
        if (missing or need_fx) and (self._price_worker is None or not self._price_worker.isRunning()):
            self.buy_status.setText("Getting the last prices…")
            self._price_worker = _PriceWorker(missing, need_fx)
            self._price_worker.done.connect(self._on_prices)
            self._price_worker.start()

    def _on_prices(self, prices, fx, errors):
        self._prices.update(prices)
        if fx:
            self._fx = fx
        self._show_purchases()
        if errors:
            flag_problem(self.buy_status, "No price for: " + "; ".join(errors))
        else:
            self.buy_status.setText("Prices are the last close.")

    def _cad(self, symbol):
        p = self._prices.get(symbol)
        if p is None:
            return None
        if is_us_listed(symbol):
            return p * self._fx if self._fx else None
        return p

    def _held_symbols(self) -> dict:
        """{symbol: shares} the portfolio already holds."""
        portfolio = self._target_portfolio()
        if self.db is None or not portfolio:
            return {}
        out = {}
        for p in self.db.positions():
            if str(p.get("portfolio") or "").strip() == portfolio:
                s = str(p["symbol"]).upper()
                out[s] = out.get(s, 0.0) + float(p.get("shares") or 0)
        return out

    def use_recorded_cash(self):
        portfolio = self._target_portfolio()
        if self.db is None or not portfolio:
            flag_problem(self.buy_status, "Pick the portfolio in step 2 first.")
            return
        total = 0.0
        for c in self.db.cash():
            if c["portfolio"] == portfolio:
                if c["currency"] == "CAD":
                    total += float(c["amount"])
                elif c["currency"] == "USD" and self._fx:
                    total += float(c["amount"]) * self._fx
        if not total:
            flag_problem(self.buy_status, f"No cash recorded for {portfolio} (Portfolio tab).")
            return
        self.buy_now.setValue(max(0.0, total))

    def _weights(self) -> dict:
        d = g.default_weights(self._level(), [tuple(p) for p in self.picks])
        weights = {s: self.weights_pct.get(s, w * 100.0) / 100.0 for s, w in d["weights"].items()}
        return {"weights": weights, "uncovered": d["uncovered"]}

    def _show_purchases(self):
        if not hasattr(self, "buy_table"):
            return
        d = self._weights()
        weights = d["weights"]
        prices = {s: self._cad(s) for s in weights}
        priced = {s: p for s, p in prices.items() if p}
        held_shares = self._held_symbols()
        held = {s: held_shares.get(s, 0.0) * (self._cad(s) or 0.0) for s in weights}
        other = sum(sh * (self._cad(s) or 0.0) for s, sh in held_shares.items() if s not in weights)
        now = g.purchases(weights, priced, held, self.buy_now.value())
        after = {s: held[s] + next(r["cost"] for r in now["rows"] if r["symbol"] == s) for s in weights}
        month = g.purchases(weights, priced, after, self.buy_monthly.value()) \
            if self.buy_monthly.value() else None
        kinds = {g.ALL: "whole level", "stocks": "stocks", "bonds": "bonds", "cash": "cash"}
        cls_of = dict((s, c) for s, c in self.picks)
        self.buy_table.setRowCount(len(now["rows"]))
        for r, row in enumerate(now["rows"]):
            s = row["symbol"]
            self.buy_table.setItem(r, 0, QTableWidgetItem(s))
            self.buy_table.setItem(r, 1, QTableWidgetItem(kinds.get(cls_of.get(s), "")))
            spin = QDoubleSpinBox(); spin.setRange(0, 100); spin.setDecimals(1); spin.setSuffix(" %")
            spin.setValue(weights[s] * 100.0)
            spin.valueChanged.connect(lambda v, sym=s: self._set_weight(sym, v))
            self.buy_table.setCellWidget(r, 2, spin)
            price = prices.get(s)
            m = next((x for x in (month or {}).get("rows", []) if x["symbol"] == s), None)
            cells = {3: "…" if price is None else f"${price:,.2f}",
                     4: f"{held_shares.get(s, 0):g} sh" if held_shares.get(s) else "—",
                     5: f"{row['shares']} sh" if price else "…",
                     6: _money(row["cost"]) if price else "…",
                     7: (f"{m['shares']} sh ({_money(m['cost'])})" if m else "—")}
            for c, text in cells.items():
                self.buy_table.setItem(r, c, QTableWidgetItem(text))
        self.buy_table.resizeColumnsToContents()
        notes = []
        total_w = sum(weights.values())
        if abs(total_w - 1.0) > 0.005:
            notes.append(f"The shares add up to {total_w:.0%}: the other {max(0, 1 - total_w):.0%} "
                         f"stays as cash." if total_w < 1 else
                         f"The shares add up to {total_w:.0%} - more than the money.")
        if d["uncovered"]:
            notes.append("No fund picked yet for " + ", ".join(
                f"{c} ({v:.0%} of {g.LEVELS[self._level()][0]})" for c, v in d["uncovered"].items())
                         + " - add one in step 3, or that part stays as cash.")
        if other:
            notes.append(f"The portfolio also holds {_money(other)} in other holdings; they are "
                         "left alone here (the Plan tab weighs the whole account).")
        self.buy_note.setText(" ".join(notes))
        self.buy_note.setVisible(bool(notes))
        summary = (f"Now: buy for {_money(now['spent'])}, {_money(now['left'])} left as cash.")
        if month:
            summary += (f" Each month after: buy for {_money(month['spent'])}; "
                        f"{_money(month['left'])} carried to the next month.")
        self.buy_summary.setText(summary)
        self._last_purchase = (now, month)

    def _set_weight(self, symbol, pct):
        self.weights_pct[symbol] = pct
        self._save_funds()
        # Not from inside the spin box's own signal: redrawing replaces it.
        QTimer.singleShot(0, self._show_purchases)

    def purchase_text(self) -> str:
        now, month = getattr(self, "_last_purchase", (None, None))
        if not now:
            return ""
        portfolio = self._target_portfolio() or "your account"
        lines = [f"TradeLab Guide - purchases for {portfolio}, {dt.date.today():%Y-%m-%d}"]
        for r in now["rows"]:
            if r["shares"]:
                lines.append(f"  Buy {r['shares']} {r['symbol']} (about ${r['price']:,.2f} each, "
                             f"{_money(r['cost'])})")
        lines.append(f"  Left as cash: {_money(now['left'])}")
        if month:
            lines.append("Each month after:")
            lines += [f"  Buy {r['shares']} {r['symbol']}" for r in month["rows"] if r["shares"]]
        lines.append("Prices are the last close. Calculations, not advice - you place the orders.")
        return "\n".join(lines)

    def copy_purchases(self):
        text = self.purchase_text()
        if not text:
            flag_problem(self.buy_status, "Nothing to copy yet.")
            return
        QApplication.clipboard().setText(text)
        self.buy_status.setText("Copied - paste it in a note, or keep it beside your broker's "
                                "order screen.")

    def _save_funds(self):
        try:
            saved = json.loads(self._settings.value(PROFILE_KEY, "", type=str) or "{}")
        except (ValueError, TypeError):
            saved = {}
        saved["funds"] = [{"symbol": s, "cls": c, "weight": self.weights_pct.get(s)}
                          for s, c in self.picks]
        self._settings.setValue(PROFILE_KEY, json.dumps(saved))

    def _level(self) -> int:
        """The level picked in step 2 - or the one saved, before step 2 is shown."""
        if self.recommended is not None:
            return self._picked()
        return self._saved_level if self._saved_level is not None else 0

    def show_funds(self):
        level = self._level()
        name = g.LEVELS[level][0]
        amount = self.lump.value()
        parts = g.block_amounts(level, amount)
        split = ", ".join(f"{cls} {_money(v)}" for cls, v in parts.items() if v) if amount else \
            ", ".join(f"{cls} {share:.0%}" for cls, share in zip(("stocks", "bonds", "cash"),
                                                                g.LEVELS[level][1:]) if share)
        self.funds_intro.setText(f"{name}: {split}. Either one fund that does it all, or one "
                                 f"fund per part - compare them below.")
        self.fund_set.blockSignals(True)
        self.fund_set.clear()
        self.fund_set.addItem(f"One fund for {name}")
        for block in g.BLOCKS:
            self.fund_set.addItem(f"Building block: {block[0]}")
        self.fund_set.blockSignals(False)
        self.pages.setCurrentIndex(2)
        self.check_funds()

    def _fund_choice(self):
        """(symbols, note) of what the Show list says."""
        i = self.fund_set.currentIndex()
        if i <= 0:
            level = self._level()
            return list(g.ONE_FUND[level]), g.ONE_FUND_NOTE.get(
                level, f"All-in-one ETFs: {g.LEVELS[level][1]:.0%} stocks from around the world "
                       f"and {g.LEVELS[level][2]:.0%} bonds, rebalanced inside the fund.")
        _name, _cls, symbols, note = g.BLOCKS[i - 1]
        return list(symbols), note

    def check_funds(self):
        symbols, note = self._fund_choice()
        for s in re.split(r"[\s,;]+", self.fund_extra.text().upper()):
            if s and s not in symbols:
                symbols.append(s)
        self.fund_note.setText(note)
        self._fund_symbols = symbols
        missing = [s for s in symbols if s not in self._fund_facts]
        self._show_funds()
        if not missing:
            return
        if self._funds_worker is not None and self._funds_worker.isRunning():
            self._funds_pending = True
            return
        self.fund_status.setText(f"Checking {', '.join(missing)}…")
        self._funds_worker = _FundsWorker(missing)
        self._funds_worker.done.connect(self._on_funds)
        self._funds_worker.start()

    def _on_funds(self, gathered, errors):
        from tradelab.core.candidate import facts
        from tradelab.core.morningstar import by_symbol
        etfs = self.db.etf_list() if self.db is not None else []
        try:
            ms = by_symbol(json.loads(self._settings.value("Morningstar/export", "", type=str)
                                      or "{}").get("rows") or [])
        except (ValueError, TypeError):
            ms = {}
        for symbol, info in gathered.items():
            meta = info.get("meta") or {}
            m = ms.get(symbol) or {}
            screener = next((r for r in etfs if symbol in {str(r.get("ticker") or "").upper(),
                                                             str(r.get("yahoo") or "").upper()}), None)
            if screener and screener.get("mer") is not None:
                mer, source = screener["mer"], "ETF Screener"
            elif m.get("mer") is not None:
                mer, source = m["mer"], "Morningstar"
            elif meta.get("expense_ratio") is not None:
                mer, source = meta["expense_ratio"], "Yahoo"
            else:
                mer, source = None, ""
            row = facts(symbol, info.get("prices"), meta, mer=mer, mer_source=source,
                        dividend_yield=info.get("yield"))
            row.update({k: m.get(k) for k in ("stars", "medalist", "medal_rank")})
            self._fund_facts[symbol] = row
        self._show_funds()
        if errors:
            flag_problem(self.fund_status, "Could not check: " + "; ".join(errors))
        else:
            self.fund_status.setText("Facts from real prices, dividends included. Not advice.")
        if self._funds_pending:
            self._funds_pending = False
            self.check_funds()

    def _show_funds(self):
        from tradelab.core.candidate import morningstar_text, rank
        rows = rank([self._fund_facts[s] for s in self._fund_symbols if s in self._fund_facts],
                    self.fund_sort.currentText())

        def pct(v, d=1):
            return "—" if v is None else f"{v * 100:.{d}f}%"
        self.fund_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = [row["symbol"], str(row["name"]),
                     pct(row["mer"], 2) + (f" ({row['mer_source']})" if row["mer_source"] else ""),
                     f"{pct(row['stdev'])} {row['band'] or ''}".strip(),
                     f"{pct(row['worst_fall'], 0)} {row['worst_when']}".strip(),
                     pct(row["ret1"]), pct(row["ret5"]), pct(row["ret10"]),
                     row["suits"], morningstar_text(row) or "—"]
            for c, text in enumerate(cells):
                self.fund_table.setItem(r, c, QTableWidgetItem(text))
        self.fund_table.resizeColumnsToContents()

    def show_levels(self):
        self._user_picked = False
        self.pages.setCurrentIndex(1)
        self._fill_portfolios()
        self._show()
        if self.measured is None and (self._worker is None or not self._worker.isRunning()):
            self.status.setText("Measuring what each level really did since 2003…")
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
                "debt": self.debt.currentText(),
                "basis": self.basis.currentIndex() if hasattr(self, "basis") else 0}

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
        window = g.WINDOWS[a["basis"] if a["basis"] < len(g.WINDOWS) else 0][0]
        months = g.WINDOWS[a["basis"]][1] if a["basis"] < len(g.WINDOWS) else None
        if months is not None and months < 120:
            self.period_note.setText(f"{window.capitalize()} is too short to judge a level: it "
                                     "can miss a crash entirely, and a strong stretch does not "
                                     "repeat on demand.")
            self.period_note.setStyleSheet("color:#c9a227;")
        else:
            self.period_note.setText("The returns, the falls and your money below all follow it.")
            self.period_note.setStyleSheet("color:#8a9099;")
        for col, text in ((2, f"Did a year, {window}"), (4, f"Your money in {years} years"),
                          (5, f"Worst fall, {window} (when)"), (6, "Worst 12 months"),
                          (7, "Worst 5 years, a year")):
            self.table.setHorizontalHeaderItem(col, QTableWidgetItem(text))
        invested = a["lump"] + a["monthly"] * 12 * years

        def opt(v, fmt):
            return "—" if v is None else format(v, fmt)
        for r, (name, st, bo, ca) in enumerate(g.LEVELS):
            w = g.window_record(r, a["basis"], self.measured)
            rate = g.rate_for(r, a["basis"], self.measured)
            fv = g.future_value(a["lump"], a["monthly"], years, rate)
            cells = [("★ " if r == rec["level"] else "") + name,
                     f"{st:.0%} / {bo:.0%} / {ca:.0%}",
                     f"{w['cagr']:.1%}" if w else "…",
                     f"{g.expected_return(st, bo, ca):.1%}",
                     f"{_money(fv)} (put in {_money(invested)})" if invested else "—",
                     (f"{w['worst_fall']:.0%}" + (f" ({w['worst_when']})" if w["worst_when"] else ""))
                     if w else "…",
                     opt(w["worst_12m"], "+.0%") if w else "…",
                     opt(w["worst_5y"], "+.1%") if w else "…"]
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
                    + (f" In its worst stretch since {m['since']}, $10,000 became "
                       f"{_money(10_000 * (1 + m['worst_fall']))}."
                       if m else ""))
        self.choice.setText(text)

    def _fill_portfolios(self):
        names = self.db.portfolio_names() if self.db is not None else []
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
        self._save_funds()
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
        for combo, key in ((self.horizon, "horizon"), (self.drop, "drop"), (self.basis, "basis")):
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
        funds = [f for f in saved.get("funds") or [] if isinstance(f, dict) and f.get("symbol")]
        self.picks = [[f["symbol"], f.get("cls") or g.ALL] for f in funds]
        self.weights_pct = {f["symbol"]: float(f["weight"]) for f in funds
                            if isinstance(f.get("weight"), (int, float))}
        self._show_picks()
        level = saved.get("level")
        self._saved_level = level if isinstance(level, int) and 0 <= level < len(g.LEVELS) else None
        if isinstance(level, int) and 0 <= level < len(g.LEVELS):
            self.saved_line.setText(
                f"Your level: {g.LEVELS[level][0]} (chosen {saved.get('saved', '')}"
                + (f", for {saved['portfolio']}" if saved.get("portfolio") else "")
                + "). Go through the steps again any time.")
        else:
            self.saved_line.setText("")
        self.saved_line.setVisible(bool(self.saved_line.text()))

    def has_profile(self) -> bool:
        """A level has been chosen (funds picked alone do not count)."""
        try:
            saved = json.loads(self._settings.value(PROFILE_KEY, "", type=str) or "{}")
        except (ValueError, TypeError):
            return False
        return isinstance(saved.get("level"), int)

    def shutdown(self):
        for worker in (self._worker, self._funds_worker, self._price_worker):
            if worker is not None and worker.isRunning():
                try:
                    worker.done.disconnect()
                except (RuntimeError, TypeError):
                    pass
                worker.wait(5000)
