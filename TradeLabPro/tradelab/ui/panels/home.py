"""The Home tab: your book in one screen."""
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
from tradelab.ui.common import (AutoRefresh, StatusLabel, _HistoryWorker, _READ_COLORS, _prices_as_of, flag_problem)

log = get_logger(__name__)


class _HomeWorker(QThread):
    """Loads everything Home needs in one background pass: prices for the
    holdings and benchmark, the FX rates to convert them, each holding's
    dividend history, the composition of any holding that turns out to be a fund
    (so exposure can be read by company, not just by position), and the dates
    each one has scheduled."""
    # histories, dividends, compositions, calendars, error
    done = Signal(object, object, object, object, str)

    def __init__(self, symbols, fx_symbols, period="1y"):
        super().__init__()
        self.symbols = list(symbols)
        self.fx_symbols = list(fx_symbols)
        self.period = period

    def run(self):
        try:
            from tradelab.data.market_data import (get_histories, get_dividends,
                                                   get_fund_composition, get_calendar,
                                                   with_latest_prices)
            hist = get_histories(sorted(set(self.symbols) | set(self.fx_symbols)),
                                 self.period, "1d")
            # Without this, an evening when Yahoo is late with the day's bar
            # shows yesterday's close as the value and yesterday's move as
            # "today" - what happened on 9 October 2026.
            hist = with_latest_prices(hist, self.symbols)
            divs = {s: get_dividends(s) for s in self.symbols}
            # Both are cached per symbol in market_data, so the Analytics tab's
            # own look-through afterwards costs nothing.
            comps = {s: get_fund_composition(s) for s in self.symbols}
            cals = {s: get_calendar(s) for s in self.symbols}
            self.done.emit(hist, divs, comps, cals, "")
        except Exception as exc:
            self.done.emit(None, None, None, None, str(exc))


class HomePanel(AutoRefresh, QWidget):
    """The first thing you see: your book in one screen.

    Deliberately assembles rather than calculates — every figure comes from the
    same engines behind the Analytics and Dividends tabs, so Home can never
    disagree with them. Refreshes itself once at startup so the numbers are
    already there when you arrive.
    """

    # Brought up to date when the tab is opened, if stale - see AutoRefresh.
    REFRESH_METHOD = "refresh"
    REFRESH_WORKERS = ("_worker",)
    REFRESH_POLICY = freshness.INTRADAY

    _TILES = [("value", "Book value"), ("today", "Today"),
              ("unreal", "Unrealized P&L"), ("income", "Annual income"),
              ("worth", "Net worth")]
    CHART_MODES = ["This year (estimated)", "Recorded history"]

    def __init__(self, db: Database, chart=None, cfg=None, market_source=None):
        super().__init__()
        self.db = db
        self.chart = chart
        self.cfg = cfg
        # Callable returning the Market tab's own read (see
        # MarketPanel.market_summary). Home never recomputes the market itself:
        # showing a second, cheaper calculation would let the two screens
        # disagree about the same day.
        self.market_source = market_source
        self._worker = None
        self._chart_worker = None
        self._loaded_once = False
        self._cash = []
        self._ytd = None
        self.retirement_path = None      # retirement.json; None = the data folder's
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        title = QLabel("Your portfolio at a glance")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch()
        self.currency = QComboBox(); self.currency.addItems(["CAD", "USD", "Native (mixed)"])
        self.chart_mode = QComboBox(); self.chart_mode.addItems(self.CHART_MODES)
        self.chart_mode.setToolTip(
            "Estimated: today's share counts valued back through the year. Recorded: what "
            "the account was really worth each day TradeLab priced it - deposits, trades "
            "and dividends included as they happened.")
        self.chart_mode.currentIndexChanged.connect(lambda _i: self._draw_chart())
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        top.addWidget(QLabel("Chart")); top.addWidget(self.chart_mode)
        top.addWidget(QLabel("Currency")); top.addWidget(self.currency); top.addWidget(refresh)
        layout.addLayout(top)

        self.status = StatusLabel(); self.status.setStyleSheet(f"color:{theme.MUTED};")
        layout.addWidget(self.status)

        self.headline = QLabel("Loading your portfolio…")
        self.headline.setWordWrap(True)
        self.headline.setStyleSheet("font-size:14px;")
        layout.addWidget(self.headline)

        tiles = QHBoxLayout()
        self.metrics = {}
        for key, label in self._TILES:
            box = QVBoxLayout()
            cap = QLabel(label); cap.setStyleSheet(f"color:{theme.MUTED}; font-size:12px;")
            val = QLabel("—"); val.setStyleSheet("font-size:20px; font-weight:bold;")
            box.addWidget(cap); box.addWidget(val)
            holder = QWidget(); holder.setLayout(box)
            tiles.addWidget(holder)
            self.metrics[key] = val
        layout.addLayout(tiles)

        # The year so far. Drawn from the same equity curve Analytics measures
        # drawdown on, so the chart and the numbers above it are one thing seen
        # two ways.
        self.ytd_chart = EquityCurveWidget()
        self.ytd_chart.clear_curve("Loading…")
        layout.addWidget(self.ytd_chart)

        # Anything that wants attention, and the day's biggest moves. Each
        # column keeps its heading tight against its own widget: without the
        # explicit spacing/margins (and the trailing stretch) the layout hands
        # the leftover height to the gap between them, so the labels drift far
        # above the boxes they name.
        split = QHBoxLayout()

        left = QVBoxLayout()
        left.setSpacing(4)
        left.setContentsMargins(0, 0, 0, 0)
        attention_label = QLabel("Needs attention")
        attention_label.setStyleSheet("font-weight:bold;")
        left.addWidget(attention_label)
        self.attention = QListWidget()
        self.attention.setMaximumHeight(120)
        left.addWidget(self.attention)
        split.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        right.setContentsMargins(0, 0, 0, 0)
        movers_label = QLabel("Today's movers")
        movers_label.setStyleSheet("font-weight:bold;")
        right.addWidget(movers_label)
        self.movers = QTableWidget(0, 3)
        self.movers.setHorizontalHeaderLabels(["Symbol", "Change %", "Value"])
        self.movers.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.movers.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.movers.verticalHeader().setVisible(False)
        self.movers.setMaximumHeight(120)
        self.movers.setToolTip("Click a holding to chart it.")
        self.movers.cellClicked.connect(self._chart_row)
        right.addWidget(self.movers)
        split.addLayout(right, 1)
        # Hold the two columns in a height-capped container. Left to itself the
        # section would absorb the panel's spare height - which either pushed
        # the headings away from their boxes or, once the columns were pinned,
        # stranded the income/market lines at the very bottom of the tab.
        split_box = QWidget()
        split_box.setLayout(split)
        split_box.setMaximumHeight(150)
        layout.addWidget(split_box)

        # Income + market context, the two "what's next" lines.
        self.income_line = QLabel("")
        self.income_line.setWordWrap(True)
        layout.addWidget(self.income_line)

        # Dates your holdings have scheduled — earnings and ex-dividend only.
        self.upcoming_line = QLabel("")
        self.upcoming_line.setWordWrap(True)
        layout.addWidget(self.upcoming_line)

        self.market_line = QLabel("")
        self.market_line.setWordWrap(True)
        layout.addWidget(self.market_line)

        # The world board and the macro row that moves a Canadian book. Both are
        # rendered from the Market tab's existing download, so they cost nothing
        # beyond the refresh that already happened.
        self.world_line = QLabel("")
        self.world_line.setWordWrap(True)
        layout.addWidget(self.world_line)

        self.macro_line = QLabel("")
        self.macro_line.setWordWrap(True)
        layout.addWidget(self.macro_line)

        layout.addStretch()
        hint = QLabel("Figures come from the Analytics and Dividends tabs — open those for the "
                      "full breakdown. " + theme.ANALYSIS_ONLY)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(hint)

    def showEvent(self, event):
        super().showEvent(event)
        # Populate on first view; the startup prefetch usually beats the user here.
        if not self._loaded_once and self.db.positions():
            self.refresh()

    def refresh(self):
        from tradelab.core.portfolio_analytics import currency_of, fx_pair_symbol
        if self._worker is not None and self._worker.isRunning():
            return
        self.note_refresh_started()
        positions = self.db.positions()
        if not positions:
            self.headline.setText("No holdings yet — add positions in the Portfolio tab, "
                                  "or import them from IBKR.")
            self.status.setText("")
            self.ytd_chart.clear_curve("No holdings to chart yet.")
            self._loaded_once = True
            return
        self._positions = positions
        self._cash = self.db.cash()
        choice = self.currency.currentText()
        self._target = None if choice.startswith("Native") else choice
        self._bench = "SPY"
        symbols = sorted({str(p["symbol"]).upper() for p in positions})
        self._fx_pairs = {}
        if self._target:
            for ccy in ({currency_of(s) for s in symbols} | {currency_of(self._bench)}
                        | {str(c["currency"]).upper() for c in self._cash}):
                if ccy != self._target:
                    self._fx_pairs[ccy] = fx_pair_symbol(ccy, self._target)
        self.status.setText("Refreshing…")
        self._worker = _HomeWorker(symbols + [self._bench], self._fx_pairs.values())
        self._worker.done.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, history, divs, comps, cals, err):
        from tradelab.core import home as hm_core
        from tradelab.data.market_data import is_synthetic
        self._loaded_once = True
        if err or history is None:
            flag_problem(self.status, f"Could not refresh: {err or 'no data'}")
            return
        # Real money: never show fabricated prices (same rule as Analytics).
        history = {s: df for s, df in history.items()
                   if df is not None and not is_synthetic(df)}
        fx = ({ccy: history.get(sym) for ccy, sym in self._fx_pairs.items()}
              if self._target else None)
        data = hm_core.summarize(
            self._positions, history, divs or {},
            benchmark_df=history.get(self._bench), benchmark_symbol=self._bench,
            target_currency=self._target, fx=fx, compositions=comps,
            calendars=cals, cash=self._cash)
        as_of = _prices_as_of((data.get("analytics") or {}).get("prices_as_of"))
        self.status.setText(f"Updated {time.strftime('%H:%M')}"
                            + (f" · {as_of}" if as_of else ""))
        self._render(data)

    def _set_tile(self, key, text, colour=None):
        lbl = self.metrics[key]
        lbl.setText(text)
        lbl.setStyleSheet("font-size:20px; font-weight:bold;"
                          + (f" color:{colour};" if colour else ""))

    def _render(self, d):
        cur = d.get("currency")
        suf = f" {cur}" if cur else ""
        self.headline.setText(d["text"])
        if not d["has_positions"]:
            for key, _ in self._TILES:
                self._set_tile(key, "—")
            self.ytd_chart.clear_curve("No holdings to chart yet.")
            return

        a = d["analytics"] or {}
        from tradelab.core.home import book_value
        value = book_value(a)
        self._set_tile("value", f"${value:,.0f}{suf}" if value else "—")
        self.metrics["value"].setToolTip(
            f"Positions ${a['total_value']:,.0f} + cash ${a['cash_value']:,.0f}{suf}"
            if value and a.get("cash") else "")

        day = d.get("day_change")
        self._set_tile("today", f"{day:+,.0f}{suf}" if day is not None else "—",
                       theme.pnl_color(day) if day is not None else None)

        unreal, pct = a.get("total_unrealized"), a.get("total_unrealized_pct")
        if unreal is None:
            txt = "—"
        else:
            txt = f"{unreal:+,.0f}" + (f" ({pct:+.1f}%)" if pct is not None else "")
        self._set_tile("unreal", txt,
                       theme.pnl_color(unreal) if unreal is not None else None)

        income = (d.get("income") or {}).get("total_annual_income")
        self._set_tile("income", f"${income:,.0f}{suf}" if income else "—",
                       theme.UP if income else None)

        self._record_value(a)
        self._render_net_worth(value, cur)
        self._ytd = d.get("ytd")
        self._draw_chart()

        self.attention.clear()
        items = d.get("attention") or []
        if not items:
            entry = QListWidgetItem("Nothing needs attention.")
            entry.setForeground(QColor(theme.MUTED))
            self.attention.addItem(entry)
        for item in items:
            entry = QListWidgetItem(("⚠  " if item["kind"] == "warn" else "•  ") + item["text"])
            entry.setForeground(QColor(theme.DOWN if item["kind"] == "warn" else theme.TEXT))
            self.attention.addItem(entry)

        rows = (d.get("movers") or [])[:5]
        self.movers.setRowCount(len(rows))
        for r, m in enumerate(rows):
            self.movers.setItem(r, 0, QTableWidgetItem(m["symbol"]))
            for col, text in ((1, f"{m['change_pct']:+.2f}%"),
                              (2, f"{m['change_value']:+,.0f}")):
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setForeground(QColor(theme.pnl_color(m["change_pct"])))
                self.movers.setItem(r, col, cell)
        self.movers.resizeColumnsToContents()

        nxt = d.get("next_payment")
        inc = d.get("income") or {}
        if nxt:
            self.income_line.setText(
                f"<b>Income:</b> about ${inc.get('monthly_average', 0):,.0f}{suf} a month · "
                f"next payment {nxt['symbol']} in {nxt['name']} "
                f"(~${nxt['amount']:,.0f}{suf})")
        elif inc.get("total_annual_income"):
            self.income_line.setText(
                f"<b>Income:</b> about ${inc['monthly_average']:,.0f}{suf} a month.")
        else:
            self.income_line.setText("<b>Income:</b> none of your holdings pay a dividend.")

        self._render_upcoming(d.get("events"))
        self.refresh_market_line()

    def _record_value(self, analytics):
        """Keep today's account value for the recorded history - only when every
        holding was priced and converted (core.home.snapshot_of)."""
        from tradelab.core.home import snapshot_of
        snap = snapshot_of(analytics)
        if snap is None:
            return
        try:
            self.db.record_value(snap)
        except Exception:
            log.exception("Could not record today's account value")

    def _render_net_worth(self, book, currency):
        """Portfolios plus the plans followed in the Retirement tab."""
        from tradelab.core.home import net_worth
        from tradelab.core.retirement import RetirementBook
        try:
            accounts = RetirementBook(self.retirement_path).accounts
        except Exception:
            log.exception("Could not read the Retirement tab's accounts")
            accounts = []
        worth = net_worth(book, currency, accounts)
        self.net_worth = worth
        suf = f" {currency}" if currency else ""
        if worth["total"] is None:
            self._set_tile("worth", "—")
            self.metrics["worth"].setToolTip("")
            return
        self._set_tile("worth", f"${worth['total']:,.0f}{suf}")
        lines = [f"{p['name']}: ${p['value']:,.0f}{suf}"
                 + (f" (statement {p['as_of']})" if p.get("as_of") else "")
                 for p in worth["parts"]]
        lines += [f"{p['name']}: {p['value']:,.0f} {p['currency']} - not added, another currency"
                  for p in worth["apart"]]
        if len(worth["parts"]) == 1 and not worth["apart"]:
            lines.append("Add the plans you can't import (a group RRSP, a pension) in the "
                         "Retirement tab and they count here too.")
        self.metrics["worth"].setToolTip("\n".join(lines))

    def _draw_chart(self):
        """The year as estimated, or the history as recorded - whichever the
        Chart box asks for."""
        if self.chart_mode.currentIndex() == 1:
            self._render_recorded()
        else:
            self._render_ytd(self._ytd)

    def _render_recorded(self):
        from tradelab.core.home import recorded_curve
        currency = getattr(self, "_target", None)
        if not currency:
            self.ytd_chart.clear_curve("Pick CAD or USD: the history is recorded in one currency.")
            return
        rows = self.db.value_history(currency)
        curve = recorded_curve(rows, currency)
        if curve is None:
            first = f" since {rows[0]['day']}" if rows else ""
            self.ytd_chart.clear_curve(
                f"Recording your account's value each day{first} - the chart starts once "
                "two days are recorded.")
            return
        self.ytd_chart.show_curve(
            curve, title=f"Recorded value ({currency})",
            footnote="What the account was worth each day TradeLab priced it, cash "
                     "included. Deposits and withdrawals show as moves - this is the "
                     "account, not its performance.")

    def _render_ytd(self, ytd):
        """The account curve for the year, plus the caveat that belongs with it.

        The line is a mark-to-market of the shares you hold *today* — the only
        thing an imported IBKR position supports, since it carries a share count
        and an average price but no trade date. Saying so under the chart is not
        optional: a curve that looks like an account statement, but silently
        values a March purchase back to January, would be the most misleading
        thing on the screen.
        """
        if not ytd:
            self.ytd_chart.clear_curve(
                "Not enough of this year priced yet to draw a curve.")
            return
        ccy = f" ({ytd['currency']})" if ytd.get("currency") else ""
        note = ("Today's share counts valued at each day's close — not an account "
                "statement: contributions, withdrawals, trades during the year and "
                "dividends received are not in it.")
        if ytd.get("limited_by"):
            note += (f" Starts {ytd['start_date']:%d %b} — {ytd['limited_by']} has no "
                     "price history before then, and the book is only valued on days "
                     "every holding traded.")
        elif not ytd.get("from_last_year"):
            note += " Measured from its first session of the year."
        self.ytd_chart.show_curve(ytd, title=f"This year{ccy}", footnote=note)

    def _render_upcoming(self, schedule):
        """Scheduled dates for your holdings — earnings and ex-dividend.

        A quiet line is normal rather than a failure: ETFs have no earnings and
        publish no calendar, so a book held mostly in funds genuinely has little
        to show. The line says which holdings had nothing rather than leaving
        you to wonder whether the lookup broke.
        """
        if not schedule:
            self.upcoming_line.setText("")
            return
        events = schedule.get("events") or []
        if events:
            soonest = events[0]["days_away"]
            colour = theme.WARN if soonest <= 3 else theme.TEXT
            text = (f"<b>Coming up:</b> <span style='color:{colour}'>"
                    f"{schedule['text']}</span>")
        else:
            text = (f"<b>Coming up:</b> <span style='color:{theme.MUTED}'>"
                    f"nothing scheduled in the next {schedule['horizon_days']} days"
                    "</span>")
        missing = schedule.get("no_data") or []
        if missing:
            text += (f"<br><span style='color:{theme.MUTED}'>No calendar published for "
                     + ", ".join(missing) + " — funds rarely have one.</span>")
        self.upcoming_line.setText(text)

    def refresh_market_line(self):
        """Show the Market tab's read for every market it has scored.

        Called both after a Home refresh and whenever the Market tab finishes
        its own, so the line fills in on its own once the background warm-up
        completes.
        """
        summary = None
        if self.market_source is not None:
            try:
                summary = self.market_source()
            except Exception:
                summary = None
        if not summary or not summary.get("reads"):
            self.market_line.setText(
                f"<b>Market:</b> <span style='color:{theme.MUTED}'>reading the market…"
                "</span>  (or open the Market tab)")
            self.world_line.setText("")
            self.macro_line.setText("")
            return

        parts = []
        for region, read in summary["reads"].items():
            colour = _READ_COLORS.get(read.get("label"), theme.TEXT)
            seg = (f"{region} <span style='color:{colour}'><b>{read.get('label')}</b>"
                   f" · {read.get('score')}/100</span>")
            parts.append(seg)
        line = "<b>Market:</b> " + "   ·   ".join(parts)

        # A little context from whichever market was scored first, plus the age
        # of the reading so an old number is never presented as current.
        first = next(iter(summary["reads"].values()))
        extras = []
        if first.get("pct_above_200") is not None:
            extras.append(f"{first['pct_above_200']:.0f}% above 200-day")
        if first.get("vix") is not None:
            extras.append(f"VIX {first['vix']:.1f}")
        if first.get("strongest"):
            extras.append(f"strongest {first['strongest']}")
        if first.get("weakest"):
            extras.append(f"weakest {first['weakest']}")
        as_of = summary.get("as_of")
        if as_of:
            extras.append(freshness.stamp(as_of, time.time()))
        if extras:
            line += (f"<br><span style='color:{theme.MUTED}'>"
                     + "  ·  ".join(extras) + "</span>")
        self.market_line.setText(line)
        self._render_context_lines(summary)

    def _render_context_lines(self, summary):
        """The world board and the macro row, formatted by core.home from the
        Market tab's own download — no second fetch, no second calculation."""
        from tradelab.core import home as hm_core

        def coloured(items):
            out = []
            for it in items:
                pct = it.get("change_pct")
                colour = (theme.pnl_color(pct)
                          if it.get("directional") and pct is not None else theme.TEXT)
                out.append(f"<span style='color:{colour}'>{it['text']}</span>")
            return "  ·  ".join(out)

        strip = hm_core.index_strip(summary.get("indices"))
        self.world_line.setText(("<b>World:</b> " + coloured(strip)) if strip else "")
        macro = hm_core.macro_row(summary.get("macro"))
        self.macro_line.setText(("<b>Macro:</b> " + coloured(macro)) if macro else "")

    def _chart_row(self, row, _col):
        if self.chart is None or self.cfg is None or row < 0:
            return
        item = self.movers.item(row, 0)
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
