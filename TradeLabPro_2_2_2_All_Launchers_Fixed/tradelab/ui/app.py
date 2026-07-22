import sys
import json
import traceback
import time
from pathlib import Path
import pandas as pd
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTimer, QUrl, QSize, QRect, QPoint
from PySide6.QtGui import QAction, QImage, QTextCursor, QColor, QIcon, QPainter, QFont, QPen, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QSpinBox, QDoubleSpinBox, QComboBox,
    QListWidget, QLineEdit, QMessageBox, QSplitter, QFormLayout, QGroupBox, QCheckBox,
    QAbstractItemView, QTextEdit, QFileDialog, QProgressBar, QScrollArea, QHeaderView,
    QMenu, QToolButton, QSizePolicy, QDialog, QTextBrowser, QSystemTrayIcon, QStyle,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsSimpleTextItem, QFrame,
    QInputDialog, QSlider, QGraphicsItem, QLayout, QStackedWidget, QButtonGroup
)

from tradelab.core.config import APP_NAME, APP_VERSION, ScannerConfig, DATA_DIR, ROOT_DIR
from tradelab.data.database import Database
from tradelab.data.universe import list_symbols, available_universes, refresh_exchange_cache, import_universe_file, universe_metadata
from tradelab.data.market_data import get_history
from tradelab.core.scanner import scan_symbols
from tradelab.core.alerts import Alert, AlertStore
from tradelab.core.filters import FilterCondition
from tradelab.core.journal import Journal, JournalEntry, summarize, group_stats
from tradelab.core.risk import size_position, r_targets
from tradelab.core.links import Link, LinkStore
from tradelab.core.notes import load_notes, save_notes
from tradelab.core import heatmap as hm
from tradelab.data.universe import US_NASDAQ, US_NYSE, US_AMEX, CAN_TSX, CAN_TSX_EXPANDED
from tradelab.strategies import strategy_choices
from tradelab.ui.chart_widget import ChartWorkspace, ChartWidget
from tradelab.ui import colors
from tradelab.core.backtester import backtest_ema_macd
from tradelab.core.ai_ranker import explain_symbol


def fmt_large(v):
    try:
        v=float(v)
        if abs(v)>=1_000_000_000: return f"{v/1_000_000_000:.2f}B"
        if abs(v)>=1_000_000: return f"{v/1_000_000:.1f}M"
        if abs(v)>=1_000: return f"{v/1_000:.1f}K"
        return f"{v:,.0f}"
    except Exception:
        return str(v)


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem with safe numeric sorting.

    BUG-007: The previous implementation called ``super().__lt__`` as a
    fallback. In PySide this can re-enter the Python override during table
    sorting and produce a RecursionError / stack overflow. This version never
    calls the Qt base comparator; it compares stored numeric keys when both
    exist, otherwise compares display text directly in Python.
    """

    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        other_sort_value = getattr(other, "sort_value", None)
        if self.sort_value is not None and other_sort_value is not None:
            try:
                return float(self.sort_value) < float(other_sort_value)
            except Exception:
                pass

        # Safe non-recursive fallback for text columns and invalid numbers.
        try:
            return self.text().casefold() < other.text().casefold()
        except Exception:
            return str(self.text()).casefold() < str(other).casefold()


def table_item(value, numeric=False, display=None):
    text = str(value if display is None else display)
    if numeric:
        try:
            return SortableTableWidgetItem(text, float(value))
        except Exception:
            return SortableTableWidgetItem(text, None)
    return SortableTableWidgetItem(text, None)


class ScanWorker(QThread):
    progress = Signal(int, int, str, int)
    scan_finished = Signal(object, bool, str)

    def __init__(self, symbols, cfg):
        super().__init__()
        self.symbols = symbols
        self.cfg = cfg
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        def safe_progress(i, t, symbol, shown):
            try:
                self.progress.emit(int(i), int(t), str(symbol), int(shown))
            except RuntimeError:
                # UI was closed while the worker was still active. Stop cleanly.
                self._stop = True

        try:
            df = scan_symbols(
                self.symbols,
                self.cfg,
                progress_callback=safe_progress,
                should_stop=lambda: self._stop,
            )
            self.scan_finished.emit(df, self._stop, "")
        except BaseException:
            # Never let a worker exception terminate the Qt application.
            self.scan_finished.emit(pd.DataFrame(), True, traceback.format_exc())


class UniverseRefreshWorker(QThread):
    finished = Signal(bool, str)
    def run(self):
        try:
            meta = refresh_exchange_cache()
            messages = "\n".join(meta.get("messages", []))
            self.finished.emit(True, messages or "Universe refreshed.")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class ScannerPanel(QWidget):
    def __init__(self, db: Database, chart: ChartWidget, on_watchlist_changed=None,
                 on_portfolio_changed=None, on_show_heatmap=None):
        super().__init__()
        self.db = db
        self.chart = chart
        self.on_show_heatmap = on_show_heatmap
        self.on_watchlist_changed = on_watchlist_changed
        self.on_portfolio_changed = on_portfolio_changed
        self.cfg = ScannerConfig()
        self.results = pd.DataFrame()
        self.scan_start_time = None
        self.scan_total_symbols = 0
        self.scan_done_symbols = 0
        self.scan_matches = 0
        self.scan_worker = None
        self.refresh_worker = None
        layout = QVBoxLayout(self)

        controls = QGroupBox("Scanner Parameters")
        controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(6)
        self.parameter_scroll = QScrollArea()
        self.parameter_scroll.setWidgetResizable(True)
        self.parameter_scroll.setMinimumHeight(220)
        self.parameter_scroll.setMaximumHeight(300)
        self.parameter_inner = QWidget()
        self.parameter_layout = QVBoxLayout(self.parameter_inner)
        self.parameter_layout.setContentsMargins(4, 4, 4, 4)
        self.parameter_layout.setSpacing(8)
        self.parameter_scroll.setWidget(self.parameter_inner)
        controls_layout.addWidget(self.parameter_scroll)
        self.scan_name = QLineEdit("My Scan")
        self.country = QComboBox(); self.country.addItems(["All Exchanges", "All USA", "All Canada", "My Lists"])
        self.strategy = QComboBox()
        for key, name in strategy_choices():
            self.strategy.addItem(name, key)
        self.strategy.setToolTip("Which strategy scores/signals each symbol (includes your no-code custom strategies).")
        self.min_price = QDoubleSpinBox(); self.min_price.setRange(0, 100000); self.min_price.setValue(5.0); self.min_price.setPrefix("$")
        self.max_price = QDoubleSpinBox(); self.max_price.setRange(0, 100000); self.max_price.setValue(10000.0); self.max_price.setPrefix("$")
        self.min_volume = QSpinBox(); self.min_volume.setRange(0, 100000000); self.min_volume.setValue(500000); self.min_volume.setSingleStep(100000)
        self.min_cap = QDoubleSpinBox(); self.min_cap.setRange(0, 1000000); self.min_cap.setValue(2.0); self.min_cap.setSuffix(" B")
        self.max_symbols = QSpinBox(); self.max_symbols.setRange(0, 50000); self.max_symbols.setValue(0)
        self.max_symbols.setToolTip("0 = scan all selected symbols. Use 50/100 for a fast test.")
        self.min_score = QSpinBox(); self.min_score.setRange(0, 100); self.min_score.setValue(60)
        self.min_rel_volume = QDoubleSpinBox(); self.min_rel_volume.setRange(0, 100); self.min_rel_volume.setDecimals(2); self.min_rel_volume.setValue(0.0); self.min_rel_volume.setSingleStep(0.25); self.min_rel_volume.setToolTip("Relative volume = current volume / 20-period average volume. 0 disables this filter.")
        self.min_rsi = QDoubleSpinBox(); self.min_rsi.setRange(0, 100); self.min_rsi.setDecimals(1); self.min_rsi.setValue(0.0)
        self.max_rsi = QDoubleSpinBox(); self.max_rsi.setRange(0, 100); self.max_rsi.setDecimals(1); self.max_rsi.setValue(100.0)
        self.min_atr_percent = QDoubleSpinBox(); self.min_atr_percent.setRange(0, 100); self.min_atr_percent.setDecimals(2); self.min_atr_percent.setValue(0.0); self.min_atr_percent.setSuffix(" %")
        self.max_atr_percent = QDoubleSpinBox(); self.max_atr_percent.setRange(0, 100); self.max_atr_percent.setDecimals(2); self.max_atr_percent.setValue(100.0); self.max_atr_percent.setSuffix(" %")
        self.require_ema_trend = QCheckBox("EMA fast above EMA slow")
        self.require_positive_macd = QCheckBox("MACD above signal")
        self.interval = QComboBox(); self.interval.addItems(["1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo"]); self.interval.setCurrentText("1d")
        self.period = QComboBox(); self.period.addItems(["1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","max"]); self.period.setCurrentText("1y")
        for widget in [
            self.scan_name, self.country, self.strategy, self.min_price, self.max_price, self.min_volume, self.min_cap,
            self.max_symbols, self.min_score, self.min_rel_volume, self.min_rsi, self.max_rsi,
            self.min_atr_percent, self.max_atr_percent, self.interval, self.period,
            self.require_ema_trend, self.require_positive_macd,
        ]:
            try:
                widget.setMinimumHeight(24)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            except Exception:
                pass

        self.min_price.setToolTip("Minimum last price. Example default: $5.00.")
        self.max_price.setToolTip("Maximum last price. Leave high to avoid limiting expensive stocks.")
        self.min_volume.setToolTip("Minimum current period volume. Use 500,000+ to avoid illiquid stocks.")
        self.min_cap.setToolTip("Minimum market capitalization in billions. Example: 2 = $2B.")
        self.min_score.setToolTip("Minimum scanner score from 0 to 100. Higher scores are stricter.")
        self.min_rsi.setToolTip("Minimum RSI14. 0 disables the lower bound.")
        self.max_rsi.setToolTip("Maximum RSI14. 100 disables the upper bound.")
        self.min_atr_percent.setToolTip("Minimum ATR as percent of price. 0 disables this filter.")
        self.max_atr_percent.setToolTip("Maximum ATR as percent of price. 100 disables this filter.")
        self.country.currentTextChanged.connect(self.on_market_changed)


        def add_parameter_section(title, rows):
            section = QGroupBox(title)
            section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            section_form = QFormLayout(section)
            section_form.setContentsMargins(10, 10, 10, 10)
            section_form.setSpacing(7)
            section_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            section_form.setFormAlignment(Qt.AlignTop)
            section_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for label, widget in rows:
                section_form.addRow(label, widget)
            self.parameter_layout.addWidget(section)
            return section

        add_parameter_section("General", [
            ("Scan name", self.scan_name),
            ("Exchange preset", self.country),
            ("Strategy", self.strategy),
            ("Interval", self.interval),
            ("Period", self.period),
            ("Maximum symbols (0 = all)", self.max_symbols),
        ])
        add_parameter_section("Price / Volume", [
            ("Minimum price", self.min_price),
            ("Maximum price", self.max_price),
            ("Minimum volume", self.min_volume),
            ("Minimum market cap", self.min_cap),
            ("Minimum relative volume", self.min_rel_volume),
        ])
        add_parameter_section("Technical", [
            ("Minimum RSI", self.min_rsi),
            ("Maximum RSI", self.max_rsi),
            ("Minimum ATR %", self.min_atr_percent),
            ("Maximum ATR %", self.max_atr_percent),
        ])
        add_parameter_section("Signal / Score", [
            ("Minimum score", self.min_score),
            ("Require EMA trend", self.require_ema_trend),
            ("Require MACD bullish", self.require_positive_macd),
        ])

        # SCN-026: IBKR-style custom filter builder. Complements the fixed
        # sections above (ANDed with them) rather than replacing them -
        # arbitrary conditions on any field in tradelab.core.filters.FILTER_FIELDS.
        custom_filters_box = QGroupBox("Custom Filters")
        custom_filters_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        cf_layout = QVBoxLayout(custom_filters_box)
        cf_layout.setContentsMargins(10, 10, 10, 10)
        cf_layout.setSpacing(6)
        self.custom_filter_rows_layout = QVBoxLayout()
        self.custom_filter_rows_layout.setSpacing(4)
        self._custom_filter_widgets = []
        cf_layout.addLayout(self.custom_filter_rows_layout)
        add_filter_btn = QPushButton("+ Add Filter")
        add_filter_btn.setToolTip("Add a condition on any technical field (price, RSI, MACD, EMA, ADX, Bollinger, etc.)")
        add_filter_btn.clicked.connect(lambda: self.add_filter_row())
        cf_layout.addWidget(add_filter_btn)
        self.parameter_layout.addWidget(custom_filters_box)

        self.parameter_layout.addStretch()
        self.filters_visible = True
        self.setup_container = QWidget()
        setup_row = QHBoxLayout(self.setup_container)
        setup_row.setContentsMargins(0, 0, 0, 0)
        # SCN-029: editable combo instead of a plain text field - lets you
        # pick an existing preset to switch to it instantly (no Open file
        # dialog needed for the common case), or type a new name to Save/
        # Save As under. refresh_preset_list() keeps the dropdown list
        # in sync with what's actually on disk.
        self.setup_name = QComboBox()
        self.setup_name.setEditable(True)
        self.setup_name.setInsertPolicy(QComboBox.NoInsert)
        self.setup_name.setEditText("Default Setup")
        self.setup_name.activated.connect(self.on_preset_picked)
        new_setup = QPushButton("New")
        new_setup.setToolTip("Create a new scanner setup from default values")
        new_setup.clicked.connect(self.new_setup)
        save_setup = QPushButton("Save")
        save_setup.setToolTip("Save the current scanner setup")
        save_setup.clicked.connect(self.save_setup)
        save_as_setup = QPushButton("Save As")
        save_as_setup.setToolTip("Save the current scanner setup to a chosen file")
        save_as_setup.clicked.connect(self.save_setup_as)
        load_setup = QPushButton("Open")
        load_setup.setToolTip("Open a setup file from elsewhere on disk. To switch between your saved presets, use the Preset dropdown instead.")
        load_setup.clicked.connect(self.load_setup)
        duplicate_setup = QPushButton("Duplicate")
        duplicate_setup.setToolTip("Duplicate this setup name so you can save a variation")
        duplicate_setup.clicked.connect(self.duplicate_setup)
        delete_setup = QPushButton("Delete")
        delete_setup.setToolTip("Delete the setup file with the current setup name")
        delete_setup.clicked.connect(self.delete_setup)
        default_setup = QPushButton("Reset")
        default_setup.setToolTip("Reset controls to the default professional swing setup")
        default_setup.clicked.connect(self.default_setup)
        self.toggle_filters_btn = QPushButton("Hide filters")
        self.toggle_filters_btn.clicked.connect(self.toggle_filters)
        # UI-006/UI-007: compact preset toolbar with always-visible setup name.
        # Buttons keep only the width they need; the setup name takes the remaining space.
        setup_buttons = [new_setup, load_setup, save_setup, save_as_setup, duplicate_setup, delete_setup, default_setup, self.toggle_filters_btn]
        for btn in setup_buttons:
            btn.setMinimumWidth(0)
            btn.setMaximumWidth(max(48, btn.sizeHint().width() + 8))
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        setup_label = QLabel("Preset:")
        setup_label.setToolTip("Pick a saved preset to switch instantly, or type a new name to Save/Save As under it.")
        setup_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setup_name.setMinimumWidth(360)
        self.setup_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for btn in setup_buttons:
            setup_row.addWidget(btn)
        setup_row.addWidget(setup_label)
        setup_row.addWidget(self.setup_name, stretch=1)
        layout.addWidget(self.setup_container)
        self.controls_box = controls
        layout.addWidget(self.controls_box)

        self.universe_box = QGroupBox("Exchanges / My Lists")
        universe_box = self.universe_box
        u_layout = QVBoxLayout(universe_box)
        self.universe_checks = []
        self.universe_scroll = QScrollArea(); self.universe_scroll.setWidgetResizable(True); self.universe_scroll.setMaximumHeight(120)
        self.universe_inner = QWidget(); self.universe_checks_layout = QVBoxLayout(self.universe_inner)
        self.universe_scroll.setWidget(self.universe_inner)
        u_layout.addWidget(self.universe_scroll)
        self.rebuild_universe_checks()
        rowu = QHBoxLayout()
        self.refresh_univ_btn = QPushButton("Refresh exchanges")
        self.refresh_univ_btn.clicked.connect(self.refresh_universe)
        paste_univ = QPushButton("Create My List")
        paste_univ.clicked.connect(self.create_custom_universe)
        usa_btn = QPushButton("USA")
        usa_btn.setToolTip("Select NYSE + NASDAQ + AMEX")
        usa_btn.clicked.connect(lambda: self.select_exchange_shortcut("USA"))
        canada_btn = QPushButton("Canada")
        canada_btn.setToolTip("Select TSX + TSXV + CSE")
        canada_btn.clicked.connect(lambda: self.select_exchange_shortcut("Canada"))
        select_all = QPushButton("All")
        select_all.setToolTip("Select all exchanges and lists shown")
        select_all.clicked.connect(lambda: self.select_exchange_shortcut("All"))
        select_none = QPushButton("None")
        select_none.setToolTip("Clear all exchange/list selections")
        select_none.clicked.connect(lambda: self.select_exchange_shortcut("None"))
        rowu.addWidget(self.refresh_univ_btn)
        rowu.addWidget(paste_univ)
        rowu.addWidget(usa_btn)
        rowu.addWidget(canada_btn)
        rowu.addWidget(select_all)
        rowu.addWidget(select_none)
        rowu.addStretch()
        u_layout.addLayout(rowu)
        self.universe_status = QLabel(self.universe_status_text())
        self.universe_status.setWordWrap(True)
        self.universe_status.setMinimumWidth(160)
        u_layout.addWidget(self.universe_status)
        layout.addWidget(universe_box)

        scan_row = QHBoxLayout()
        self.scan_btn = QPushButton("START SCAN")
        self.scan_btn.clicked.connect(self.scan)
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scan)
        scan_row.addWidget(self.scan_btn)
        scan_row.addWidget(self.stop_btn)
        layout.addLayout(scan_row)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("Ready. Exchange lists auto-refresh when the cache is old or after a refresh button press.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.scan_stats_box = QGroupBox("Scan Status")
        self.scan_stats_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        stats_layout = QFormLayout(self.scan_stats_box)
        stats_layout.setContentsMargins(8, 8, 8, 8)
        stats_layout.setSpacing(4)
        self.stat_current = QLabel("-")
        self.stat_progress = QLabel("0 / 0")
        self.stat_matches = QLabel("0")
        self.stat_elapsed = QLabel("00:00")
        self.stat_eta = QLabel("--:--")
        for lbl in [self.stat_current, self.stat_progress, self.stat_matches, self.stat_elapsed, self.stat_eta]:
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        stats_layout.addRow("Current", self.stat_current)
        stats_layout.addRow("Scanned", self.stat_progress)
        stats_layout.addRow("Matches", self.stat_matches)
        stats_layout.addRow("Elapsed", self.stat_elapsed)
        stats_layout.addRow("ETA", self.stat_eta)
        layout.addWidget(self.scan_stats_box)

        self.table = QTableWidget(0, 15)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setHorizontalHeaderLabels(["Symbol", "Signal", "Score", "Conf%", "Sample", "Price", "Volume", "RelVol", "Market Cap", "Cap", "Sector", "RSI", "ATR%", "EMA", "MACD"])
        self.table.setSortingEnabled(True)
        self.table.setMinimumHeight(520)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.cellDoubleClicked.connect(self.load_chart_from_row)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_results_context_menu)
        self.table.horizontalHeader().sectionResized.connect(lambda *_: self.save_scanner_layout())
        self.table.horizontalHeader().sortIndicatorChanged.connect(lambda *_: self.save_scanner_layout())
        self.restore_scanner_layout()
        layout.addWidget(self.table, stretch=1)
        self.result_status = QLabel("Results: 0")
        self.result_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.result_status)
        row = QHBoxLayout()
        self.add_watch = QPushButton("Add selected to Watchlist")
        self.add_watch.clicked.connect(self.add_selected_watch)
        self.add_port = QPushButton("Add selected to Portfolio")
        self.add_port.clicked.connect(self.add_selected_portfolio)
        self.load_chart = QPushButton("Load selected chart")
        self.load_chart.clicked.connect(self.load_selected_chart)
        export_btn = QPushButton("Export results CSV")
        export_btn.clicked.connect(self.export_results)
        self.heatmap_btn = QPushButton("🗺 Map results")
        self.heatmap_btn.setToolTip("Show the scan results as a heatmap (sized by cap, coloured by % change).")
        self.heatmap_btn.clicked.connect(self.show_results_in_heatmap)
        row.addWidget(self.add_watch); row.addWidget(self.add_port); row.addWidget(self.load_chart)
        row.addWidget(self.heatmap_btn); row.addWidget(export_btn)
        layout.addLayout(row)

        self.refresh_preset_list()

    def _format_seconds(self, seconds):
        try:
            seconds = max(0, int(seconds))
            return f"{seconds//60:02d}:{seconds%60:02d}"
        except Exception:
            return "--:--"

    def _update_scan_stats(self, done=None, total=None, symbol=None, matches=None):
        if total is not None:
            self.scan_total_symbols = int(total)
        if done is not None:
            self.scan_done_symbols = int(done)
        if matches is not None:
            self.scan_matches = int(matches)
        if symbol is not None:
            self.stat_current.setText(str(symbol) if symbol else "-")
        self.stat_progress.setText(f"{self.scan_done_symbols} / {self.scan_total_symbols}")
        self.stat_matches.setText(str(self.scan_matches))
        if self.scan_start_time:
            elapsed = time.time() - self.scan_start_time
            self.stat_elapsed.setText(self._format_seconds(elapsed))
            if self.scan_done_symbols > 0 and self.scan_total_symbols > self.scan_done_symbols:
                rate = elapsed / max(self.scan_done_symbols, 1)
                eta = rate * (self.scan_total_symbols - self.scan_done_symbols)
                self.stat_eta.setText(self._format_seconds(eta))
            else:
                self.stat_eta.setText("00:00" if self.scan_done_symbols else "--:--")

    def _parse_large_number(self, text: str, default=0.0):
        try:
            s = str(text).strip().upper().replace(',', '').replace('$', '')
            mult = 1.0
            if s.endswith('T'):
                mult, s = 1_000_000_000_000.0, s[:-1]
            elif s.endswith('B'):
                mult, s = 1_000_000_000.0, s[:-1]
            elif s.endswith('M'):
                mult, s = 1_000_000.0, s[:-1]
            elif s.endswith('K'):
                mult, s = 1_000.0, s[:-1]
            return float(s) * mult
        except Exception:
            return default


    def setup_path(self):
        d = DATA_DIR / "setups"
        d.mkdir(exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in self.setup_name.currentText().strip() or "Default Setup").strip()
        return d / f"{safe}.json"

    def refresh_preset_list(self):
        """Keep the Preset dropdown in sync with what's actually saved in
        DATA_DIR/setups, so switching presets is a pick from the list
        instead of an Open file dialog every time.
        """
        d = DATA_DIR / "setups"
        names = sorted(p.stem for p in d.glob("*.json")) if d.exists() else []
        current_text = self.setup_name.currentText()
        self.setup_name.blockSignals(True)
        self.setup_name.clear()
        self.setup_name.addItems(names)
        self.setup_name.setEditText(current_text)
        self.setup_name.blockSignals(False)

    def on_preset_picked(self, index: int):
        name = self.setup_name.itemText(index)
        if name:
            self.load_setup_by_name(name)

    def new_setup(self):
        # default_setup() also resets the name to "Default Setup" - call it
        # first so "New Setup" isn't immediately clobbered afterward.
        self.default_setup()
        self.setup_name.setEditText("New Setup")
        self.status.setText("New setup started. Adjust filters, then Save or Save As.")

    def save_setup_as(self):
        d = DATA_DIR / "setups"
        d.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save scanner setup as", str(d / f"{self.setup_name.currentText().strip() or 'Scanner Setup'}.json"), "JSON files (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.current_setup_dict(), indent=2), encoding="utf-8")
        self.setup_name.setEditText(Path(path).stem)
        self.refresh_preset_list()
        self.status.setText(f"Setup saved as: {Path(path).name}")

    def duplicate_setup(self):
        base = self.setup_name.currentText().strip() or "Default Setup"
        self.setup_name.setEditText(base + " Copy")
        self.status.setText("Setup duplicated. Use Save to create the copied setup file.")

    def delete_setup(self):
        path = self.setup_path()
        if not path.exists():
            QMessageBox.information(self, "Delete setup", f"No setup file exists for:\n{path.name}")
            return
        if QMessageBox.question(self, "Delete setup", f"Delete setup file?\n\n{path}") == QMessageBox.Yes:
            path.unlink()
            self.refresh_preset_list()
            self.status.setText(f"Deleted setup: {path.name}")


    def add_filter_row(self, condition=None):
        from tradelab.core.filters import FIELD_SPECS, FilterCondition
        condition = condition or FilterCondition(field=next(iter(FIELD_SPECS)))
        row, widgets = _build_condition_row(condition, None, self.remove_filter_row)
        self.custom_filter_rows_layout.addWidget(row)
        self._custom_filter_widgets.append(widgets)

    def remove_filter_row(self, row_widget):
        self._custom_filter_widgets = [w for w in self._custom_filter_widgets if w["row"] is not row_widget]
        self.custom_filter_rows_layout.removeWidget(row_widget)
        row_widget.deleteLater()

    def get_custom_filters(self) -> list:
        return [_row_to_condition(w).to_dict() for w in self._custom_filter_widgets]

    def set_custom_filters(self, filters: list):
        from tradelab.core.filters import FilterCondition
        for w in list(self._custom_filter_widgets):
            self.remove_filter_row(w["row"])
        for d in filters or []:
            self.add_filter_row(FilterCondition.from_dict(d))

    def current_setup_dict(self):
        return {
            "scan_name": self.scan_name.text(),
            "exchange_preset": self.country.currentText(),
            "market": self.country.currentText(),  # backward compatibility
            "country": self.country.currentText(),  # backward compatibility
            "min_price": self.min_price.value(),
            "max_price": self.max_price.value(),
            "min_volume": self.min_volume.value(),
            "min_cap_b": self.min_cap.value(),
            "max_symbols": self.max_symbols.value(),
            "min_score": self.min_score.value(),
            "min_rel_volume": self.min_rel_volume.value(),
            "min_rsi": self.min_rsi.value(),
            "max_rsi": self.max_rsi.value(),
            "min_atr_percent": self.min_atr_percent.value(),
            "max_atr_percent": self.max_atr_percent.value(),
            "require_ema_trend": self.require_ema_trend.isChecked(),
            "require_positive_macd": self.require_positive_macd.isChecked(),
            "interval": self.interval.currentText(),
            "period": self.period.currentText(),
            "strategy": self.strategy.currentData(),
            "universes": [cb.property('universe_name') for cb in self.universe_checks if cb.isChecked()],
            "custom_filters": self.get_custom_filters(),
        }

    def save_setup(self):
        path = self.setup_path()
        path.write_text(json.dumps(self.current_setup_dict(), indent=2), encoding="utf-8")
        self.refresh_preset_list()
        self.status.setText(f"Setup saved: {path.name}")

    def load_setup(self):
        d = DATA_DIR / "setups"
        d.mkdir(exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "Load setup", str(d), "JSON files (*.json)")
        if not path:
            return
        self._apply_setup_data(json.loads(Path(path).read_text(encoding="utf-8")), Path(path).stem)
        self.status.setText(f"Setup loaded: {Path(path).name}")

    def load_setup_by_name(self, name: str):
        path = DATA_DIR / "setups" / f"{name}.json"
        if not path.exists():
            self.status.setText(f"No setup file found for preset: {name}")
            return
        self._apply_setup_data(json.loads(path.read_text(encoding="utf-8")), name)
        self.status.setText(f"Preset loaded: {name}")

    def set_strategy(self, key: str):
        idx = self.strategy.findData(key)
        self.strategy.setCurrentIndex(idx if idx >= 0 else 0)

    def refresh_strategies(self):
        """Repopulate the strategy dropdown from the registry (e.g. after a
        custom strategy is saved/deleted in the Strategy Builder), keeping
        the current selection if it still exists."""
        current = self.strategy.currentData()
        self.strategy.blockSignals(True)
        self.strategy.clear()
        for key, name in strategy_choices():
            self.strategy.addItem(name, key)
        idx = self.strategy.findData(current)
        self.strategy.setCurrentIndex(idx if idx >= 0 else 0)
        self.strategy.blockSignals(False)

    def _apply_setup_data(self, data: dict, name: str):
        self.setup_name.setEditText(name)
        self.scan_name.setText(data.get("scan_name", "My Scan"))
        preset = data.get("exchange_preset", data.get("market", data.get("country", "All Exchanges")))
        # 2.1.11 migration: ETF is now under My Lists; Custom Selection was removed.
        if preset in {"ETFs", "Custom Selection"}:
            preset = "My Lists" if preset == "ETFs" else "All Exchanges"
        self.country.setCurrentText(preset)
        self.min_price.setValue(float(data.get("min_price", 5)))
        self.max_price.setValue(float(data.get("max_price", 10000)))
        self.min_volume.setValue(int(data.get("min_volume", 500000)))
        self.min_cap.setValue(float(data.get("min_cap_b", 2)))
        self.max_symbols.setValue(int(data.get("max_symbols", 0)))
        self.min_score.setValue(int(data.get("min_score", 60)))
        self.min_rel_volume.setValue(float(data.get("min_rel_volume", 0)))
        self.min_rsi.setValue(float(data.get("min_rsi", 0)))
        self.max_rsi.setValue(float(data.get("max_rsi", 100)))
        self.min_atr_percent.setValue(float(data.get("min_atr_percent", 0)))
        self.max_atr_percent.setValue(float(data.get("max_atr_percent", 100)))
        self.require_ema_trend.setChecked(bool(data.get("require_ema_trend", False)))
        self.require_positive_macd.setChecked(bool(data.get("require_positive_macd", False)))
        self.interval.setCurrentText(data.get("interval", "1d"))
        self.period.setCurrentText(data.get("period", "1y"))
        self.set_strategy(data.get("strategy", "ema_macd"))
        self.rebuild_universe_checks()
        selected = set(data.get("universes", []))
        for cb in self.universe_checks:
            cb.setChecked(bool(set(cb.property('universe_names') or []) & selected) or cb.property('universe_name') in selected)
        self.set_custom_filters(data.get("custom_filters", []))

    def default_setup(self):
        self.country.setCurrentText("All Exchanges")
        self.rebuild_universe_checks()
        self.min_price.setValue(5)
        self.max_price.setValue(10000)
        self.min_volume.setValue(500000)
        self.min_cap.setValue(2)
        self.max_symbols.setValue(0)
        self.min_score.setValue(60)
        self.min_rel_volume.setValue(0)
        self.min_rsi.setValue(0)
        self.max_rsi.setValue(100)
        self.min_atr_percent.setValue(0)
        self.max_atr_percent.setValue(100)
        self.require_ema_trend.setChecked(False)
        self.require_positive_macd.setChecked(False)
        self.interval.setCurrentText("1d")
        self.period.setCurrentText("1y")
        self.set_strategy("ema_macd")
        for cb in self.universe_checks:
            name = cb.property('universe_name')
            cb.setChecked(bool(cb.property("universe_names")))
        self.set_custom_filters([])
        self.setup_name.setEditText("Default Setup")
        self.status.setText("Default professional swing setup restored.")

    def create_custom_universe(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self); dlg.setWindowTitle("Create My List")
        lay = QVBoxLayout(dlg)
        name_edit = QLineEdit("My List")
        txt = QTextEdit(); txt.setPlaceholderText("Paste tickers separated by comma, space, semicolon or new line. Example: AAPL, MSFT, RY.TO, SHOP.TO")
        lay.addWidget(QLabel("List name")); lay.addWidget(name_edit); lay.addWidget(QLabel("Tickers")); lay.addWidget(txt)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); lay.addWidget(buttons)
        buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.Accepted:
            return
        import re
        syms = [x.strip().upper() for x in re.split(r"[\s,;]+", txt.toPlainText()) if x.strip()]
        syms = sorted(dict.fromkeys(syms))
        if not syms:
            return
        cache_path = DATA_DIR / "custom_universes.json"
        try:
            custom = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            custom = {}
        custom[name_edit.text().strip() or "My List"] = syms
        cache_path.write_text(json.dumps(custom, indent=2), encoding="utf-8")
        self.country.setCurrentText("My Lists")
        self.rebuild_universe_checks()
        self.status.setText(f"My List saved with {len(syms)} symbols. Select My Lists to scan it.")

    def _symbols_for_universe_names(self, universes, names):
        seen = set()
        for name in names:
            for sym in universes.get(name, []):
                if sym not in seen:
                    seen.add(sym)
        return seen

    def _exchange_group_for_universe_name(self, name: str) -> str:
        """Return a user-facing exchange/list group for an available universe name.

        2.1.10: avoid showing aggregate "NYSE / NASDAQ / AMEX" choices in
        the Exchange selector.  The main UI should show individual exchange
        choices where possible, and ETF must be a separate ETF-only group.
        """
        n = str(name or "")
        u = n.upper()
        if u.startswith("MY LIST") or u.startswith("CUSTOM"):
            return "My Lists"
        if "ALL US LISTED" in u:
            return "US Aggregate"  # internal only; do not show as a checkbox
        if "ALL CANADA" in u:
            return "Canada Aggregate"  # internal only; do not show as a checkbox
        if "ETF" in u:
            return "ETFs"  # Category/list, not an exchange.
        if "TSXV" in u or "VENTURE" in u or u.endswith(".V"):
            return "TSXV"
        if "CSE" in u:
            return "CSE"
        if "CANADA" in u or " TSX" in u or u.startswith("TSX"):
            return "TSX"
        if "NASDAQ" in u:
            return "NASDAQ"
        if "NYSE" in u and "AMEX" not in u and "OTHER" not in u:
            return "NYSE"
        if "AMEX" in u:
            return "AMEX"
        if "OTHER LISTED" in u or "NYSE/AMEX" in u or "NYSE/AMEX/OTHER" in u:
            return "NYSE / AMEX"
        return "Other"

    def _country_for_universe_name(self, name: str) -> str:
        group = self._exchange_group_for_universe_name(name)
        if group in {"NYSE", "NASDAQ", "AMEX", "NYSE / AMEX", "US Aggregate"}:
            return "US"
        if group in {"TSX", "TSXV", "CSE"}:
            return "Canada"
        if group in {"My Lists", "ETFs"}:
            return "List"
        return "Other"

    def _market_choices(self):
        universes = available_universes(refresh=False)
        preset = self.country.currentText() if hasattr(self, 'country') else 'All Exchanges'

        grouped: dict[str, list[str]] = {}
        for name in universes.keys():
            group = self._exchange_group_for_universe_name(name)
            grouped.setdefault(group, []).append(name)

        choices = []

        def add(display, source_names, checked=True):
            source_names = [n for n in source_names if n in universes]
            if not source_names:
                return
            count = len(self._symbols_for_universe_names(universes, source_names))
            choices.append((display, source_names, count, checked))

        def add_group(group_name, checked=True):
            if group_name in grouped:
                add(group_name, grouped[group_name], checked)

        usa_groups = ["NASDAQ", "NYSE", "AMEX", "NYSE / AMEX"]
        canada_groups = ["TSX", "TSXV", "CSE"]

        def add_list_items(checked=False):
            # SCN-035: ETFs are a list/category, not an exchange. They are
            # shown under My Lists along with user-created lists.
            add_group("ETFs", checked)
            for name in grouped.get("My Lists", []):
                display = name.replace('Custom - ', 'My List - ')
                add(display, [name], checked)

        if preset == 'All USA':
            for g in usa_groups:
                add_group(g, True)
            add_list_items(False)
        elif preset == 'All Canada':
            for g in canada_groups:
                add_group(g, True)
            add_list_items(False)
        elif preset == 'My Lists':
            add_list_items(True)
        else:  # All Exchanges
            for g in usa_groups + canada_groups:
                add_group(g, True)
            add_list_items(False)
        return choices

    def on_market_changed(self, _text=None):
        self.rebuild_universe_checks()
        try:
            self.universe_status.setText(self.universe_status_text())
        except Exception:
            pass

    def clear_universe_checks(self):
        while self.universe_checks_layout.count():
            item = self.universe_checks_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.universe_checks = []

    def rebuild_universe_checks(self):
        self.clear_universe_checks()
        for display, names, count, checked in self._market_choices():
            cb=QCheckBox(f"{display} ({count} symbols)")
            cb.setProperty('universe_name', display)
            cb.setProperty('universe_names', names)
            cb.setChecked(checked)
            self.universe_checks.append(cb)
            self.universe_checks_layout.addWidget(cb)
        self.universe_checks_layout.addStretch()

    def refresh_universe(self):
        self.refresh_univ_btn.setEnabled(False)
        self.status.setText("Refreshing US + Canadian exchange lists. This may take a minute...")
        self.refresh_worker = UniverseRefreshWorker()
        self.refresh_worker.finished.connect(self.on_universe_refreshed)
        self.refresh_worker.start()

    def on_universe_refreshed(self, ok, message):
        self.refresh_univ_btn.setEnabled(True)
        self.rebuild_universe_checks()
        self.universe_status.setText(self.universe_status_text())
        self.status.setText("Universe refresh complete." if ok else "Universe refresh failed; using cache/fallback.")
        box = QMessageBox(self)
        box.setWindowTitle("Universe refresh")
        box.setIcon(QMessageBox.Information if ok else QMessageBox.Warning)
        box.setText("Universe refresh complete." if ok else "Refresh failed. Cache/fallback is still usable.")
        box.setDetailedText(message)
        box.exec()

    def universe_status_text(self):
        try:
            universes = available_universes(refresh=False)
            total = sum(len(v) for v in universes.values())
            meta = universe_metadata()
            messages = [m for m in meta.get("messages", []) if not str(m).startswith("Canada warning:")][-4:]
            msg = "\n".join(messages)
            return f"Exchange/List sources: {len(universes)} | Raw symbols: {total}\n{msg}"
        except Exception as exc:
            return f"Market/List status unavailable: {exc}"

    def import_universe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import ticker list", "", "Ticker files (*.csv *.txt *.xlsx *.xls);;All files (*.*)")
        if not path:
            return
        try:
            country = "Canada" if "tsx" in path.lower() or "can" in path.lower() else "US"
            exchange = "TSXV" if "tsxv" in path.lower() or "venture" in path.lower() else ("TSX" if country == "Canada" else "NASDAQ")
            count = import_universe_file(path, country=country, exchange=exchange)
            self.rebuild_universe_checks()
            self.status.setText(f"Imported {count} symbols from {path}.")
            self.universe_status.setText(self.universe_status_text())
            QMessageBox.information(self, "Universe import", f"Imported {count} symbols and reloaded universe choices.")
        except Exception as exc:
            QMessageBox.warning(self, "Universe import", f"Import failed:\n{exc}")

    def select_exchange_shortcut(self, mode: str):
        """UI-008: compact shortcut selection for exchanges/lists."""
        mode = (mode or "").lower()
        for cb in self.universe_checks:
            label = str(cb.property('universe_name') or "")
            names = cb.property('universe_names') or []
            group = self._exchange_group_for_universe_name(label)
            if mode == "usa":
                cb.setChecked(group in {"NYSE", "NASDAQ", "AMEX", "NYSE / AMEX"})
            elif mode == "canada":
                cb.setChecked(group in {"TSX", "TSXV", "CSE"})
            elif mode == "all":
                cb.setChecked(True)
            elif mode == "none":
                cb.setChecked(False)
        try:
            self.status.setText(f"Selection shortcut applied: {mode.title()}")
        except Exception:
            pass

    def selected_universes(self):
        selected = []
        for cb in self.universe_checks:
            names = cb.property('universe_names') or []
            if cb.isChecked():
                selected.extend(list(names))
        # Deduplicate while preserving order.
        return list(dict.fromkeys(selected))

    def save_scanner_layout(self):
        try:
            settings = QSettings("TradeLabPro", "TradeLabPro")
            settings.beginGroup("ScannerTable")
            widths = [self.table.columnWidth(i) for i in range(self.table.columnCount())]
            hidden = [self.table.isColumnHidden(i) for i in range(self.table.columnCount())]
            settings.setValue("widths", json.dumps(widths))
            settings.setValue("hidden", json.dumps(hidden))
            settings.setValue("sortColumn", self.table.horizontalHeader().sortIndicatorSection())
            settings.setValue("sortOrder", int(getattr(self.table.horizontalHeader().sortIndicatorOrder(), "value", self.table.horizontalHeader().sortIndicatorOrder())))
            settings.endGroup()
        except Exception:
            pass

    def restore_scanner_layout(self):
        try:
            settings = QSettings("TradeLabPro", "TradeLabPro")
            settings.beginGroup("ScannerTable")
            widths = json.loads(settings.value("widths", "[]"))
            hidden = json.loads(settings.value("hidden", "[]"))
            sort_col = int(settings.value("sortColumn", 2))
            sort_order = Qt.SortOrder(int(settings.value("sortOrder", int(getattr(Qt.DescendingOrder, "value", 1)))))
            settings.endGroup()
            for i, w in enumerate(widths[:self.table.columnCount()]):
                if int(w) > 20:
                    self.table.setColumnWidth(i, int(w))
            for i, h in enumerate(hidden[:self.table.columnCount()]):
                self.table.setColumnHidden(i, bool(h))
            if 0 <= sort_col < self.table.columnCount():
                self.table.sortByColumn(sort_col, sort_order)
        except Exception:
            pass

    def toggle_filters(self):
        self.filters_visible = not getattr(self, "filters_visible", True)
        self.controls_box.setVisible(self.filters_visible)
        self.universe_box.setVisible(self.filters_visible)
        self.toggle_filters_btn.setText("Hide filters" if self.filters_visible else "Show filters")
        if not self.filters_visible:
            self.table.setMinimumHeight(650)
        else:
            self.table.setMinimumHeight(520)

    def show_results_context_menu(self, pos):
        menu = QMenu(self)
        open_chart = menu.addAction("Open chart")
        open_new = menu.addAction("Open chart in new tab")
        menu.addSeparator()
        add_watch = menu.addAction("Add selected to Watchlist")
        add_port = menu.addAction("Add selected to Portfolio")
        copy_symbols = menu.addAction("Copy selected symbols")
        export_selected = menu.addAction("Export selected rows CSV")
        menu.addSeparator()
        columns_action = menu.addAction("Column chooser")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == open_chart:
            self.load_selected_chart()
        elif action == open_new:
            sym = self.selected_symbol()
            if sym:
                if hasattr(self.chart, "add_chart"):
                    try:
                        self.chart.add_chart(sym)
                    except Exception:
                        self.plot_symbol(sym)
                else:
                    self.plot_symbol(sym)
        elif action == add_watch:
            self.add_selected_watch()
        elif action == add_port:
            self.add_selected_portfolio()
        elif action == copy_symbols:
            QApplication.clipboard().setText("\n".join(self.selected_symbols()))
            self.status.setText(f"Copied {len(self.selected_symbols())} symbol(s).")
        elif action == export_selected:
            self.export_selected_results()
        elif action == columns_action:
            self.column_chooser()

    def column_chooser(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self); dlg.setWindowTitle("Scanner Column Chooser")
        lay = QVBoxLayout(dlg)
        checks = []
        for col in range(self.table.columnCount()):
            text = self.table.horizontalHeaderItem(col).text() if self.table.horizontalHeaderItem(col) else f"Column {col}"
            cb = QCheckBox(text); cb.setChecked(not self.table.isColumnHidden(col)); cb.setProperty("col", col)
            checks.append(cb); lay.addWidget(cb)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); lay.addWidget(buttons)
        buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject)
        if dlg.exec() == QDialog.Accepted:
            for cb in checks:
                self.table.setColumnHidden(int(cb.property("col")), not cb.isChecked())
            self.status.setText("Scanner columns updated.")

    def export_selected_results(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if not rows:
            QMessageBox.information(self, "Export selected", "Select one or more result rows first.")
            return
        if self.results.empty:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export selected scan results", "selected_scan_results.csv", "CSV files (*.csv)")
        if not path:
            return
        self.results.iloc[rows].to_csv(path, index=False)
        self.status.setText(f"Exported {len(rows)} selected row(s) to {path}")

    def current_symbols(self):
        preset = self.country.currentText()
        selected = self.selected_universes()
        countries = None
        if preset == "All USA":
            countries = ["US"]
        elif preset == "All Canada":
            countries = ["Canada"]
        # BUG-013/SCN-035: an empty selection must mean scan nothing, not all symbols.
        # This prevents ETFs/My Lists from scanning the whole market when no
        # list checkbox is available or selected.
        if not selected:
            return []
        return [s.symbol for s in list_symbols(exchanges=selected, countries=countries)]

    def current_config(self):
        cfg = ScannerConfig()
        cfg.min_price = self.min_price.value()
        cfg.max_price = self.max_price.value()
        cfg.min_volume = self.min_volume.value()
        cfg.min_market_cap = self.min_cap.value() * 1_000_000_000
        cfg.max_symbols = self.max_symbols.value()
        cfg.min_score = self.min_score.value()
        cfg.min_rel_volume = self.min_rel_volume.value()
        cfg.min_rsi = self.min_rsi.value()
        cfg.max_rsi = self.max_rsi.value()
        cfg.min_atr_percent = self.min_atr_percent.value()
        cfg.max_atr_percent = self.max_atr_percent.value()
        cfg.require_ema_trend = self.require_ema_trend.isChecked()
        cfg.require_positive_macd = self.require_positive_macd.isChecked()
        cfg.interval = self.interval.currentText()
        cfg.period = self.period.currentText()
        cfg.strategy = self.strategy.currentData()
        cfg.custom_filters = self.get_custom_filters()
        return cfg

    def scanner_error_popup(self, title: str, details: str):
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "scanner_error.log"
        log_path.write_text(str(details), encoding="utf-8")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle(title)
        msg.setText(title)
        msg.setInformativeText(f"The scanner was stopped safely. The application is still open.\n\nLog: {log_path}")
        msg.setDetailedText(str(details))
        msg.exec()

    def scan(self):
        if self.scan_worker and self.scan_worker.isRunning():
            return
        try:
            self.cfg = self.current_config()
            symbols = self.current_symbols()
            # Remove duplicates while preserving order.
            symbols = list(dict.fromkeys([str(s).strip().upper() for s in symbols if str(s).strip()]))
            n = len(symbols) if self.cfg.max_symbols <= 0 else min(len(symbols), self.cfg.max_symbols)
        except Exception:
            self.scanner_error_popup("Scanner setup error", traceback.format_exc())
            return
        if not symbols:
            QMessageBox.warning(self, "Scanner", "No symbols selected. Select at least one Exchange/List.")
            return
        self.table.setRowCount(0)
        self.result_status.setText("Results: 0")
        self.progress.setValue(0)
        self.scan_start_time = time.time()
        self.scan_total_symbols = n
        self.scan_done_symbols = 0
        self.scan_matches = 0
        self._update_scan_stats(done=0, total=n, symbol="-", matches=0)
        self.status.setText(f"Scanning {n} symbols from {len(symbols)} available...")
        self.scan_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.scan_worker = ScanWorker(symbols, self.cfg)
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.scan_finished.connect(self.on_scan_finished)
        # BUG-005E: do not delete or clear the QThread from scan_finished.
        # scan_finished is emitted from inside run(), before the native thread is fully stopped.
        # Cleanup only after QThread.finished to avoid application crashes when Stop is clicked.
        self.scan_worker.finished.connect(self.on_scan_worker_finished)
        self.scan_worker.start()

    def stop_scan(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.request_stop()
            self.status.setText("Stop requested. Waiting for current symbol to finish...")
            self.stop_btn.setEnabled(False)
            self.scan_btn.setEnabled(False)

    def on_scan_progress(self, done, total, symbol, shown):
        pct = int(done * 100 / max(total, 1))
        self.progress.setValue(pct)
        self._update_scan_stats(done=done, total=total, symbol=symbol, matches=shown)
        self.status.setText(f"Scanning {done}/{total}: {symbol} | rows found: {shown}")

    def on_scan_finished(self, df, stopped, error):
        self.scan_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        if error:
            self.scanner_error_popup("Scanner worker error", error)
        try:
            self.results = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
            self.populate_table()
            if not self.results.empty:
                try:
                    self.db.save_scan(self.scan_name.text().strip() or "Scan", json.dumps(self.current_setup_dict()), self.results.to_dict("records"))
                except Exception:
                    self.scanner_error_popup("Scan completed but save failed", traceback.format_exc())
            self.progress.setValue(100 if not stopped else self.progress.value())
            self._update_scan_stats(done=self.scan_done_symbols, total=self.scan_total_symbols, symbol="Stopped" if stopped else "Complete", matches=len(self.results))
            status = "Scan stopped by user" if stopped else "Scan complete"
            self.status.setText(f"{status}: {len(self.results)} rows shown.")
            self.result_status.setText(f"Results: {len(self.results)}")
        except Exception:
            self.scanner_error_popup("Scanner result display error", traceback.format_exc())
            self.status.setText("Scanner stopped safely after a result display error.")

    def on_scan_worker_finished(self):
        # BUG-005E: safe scanner thread cleanup after the worker is fully stopped.
        worker = self.scan_worker
        self.scan_worker = None
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if worker is not None:
            try:
                worker.deleteLater()
            except RuntimeError:
                pass

    def populate_table(self):
        df = self.results
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(df))
        for r, (_, row) in enumerate(df.iterrows()):
            symbol = row.get("Symbol", "")
            signal = row.get("Signal", "")
            score = row.get("Score", 0)
            confidence = row.get("Confidence %")
            sample_n = row.get("Sample N", 0)
            price = row.get("Price", 0)
            volume = row.get("Volume", 0)
            rel_vol = row.get("RelVol", 0)
            market_cap = row.get("Market Cap", 0)
            cap_bucket = row.get("Cap", "")
            sector = row.get("Sector", "")
            rsi14 = row.get("RSI14", 0)
            atr_pct = row.get("ATR%", 0)
            ema_trend = row.get("EMA Trend", "")
            macd_state = row.get("MACD", "")
            self.table.setItem(r, 0, table_item(symbol))
            self.table.setItem(r, 1, table_item(signal))
            self.table.setItem(r, 2, table_item(score, numeric=True, display=f"{float(score or 0):.0f}" if str(score) != "" else ""))
            has_confidence = pd.notna(confidence)
            self.table.setItem(r, 3, table_item(confidence if has_confidence else "", numeric=True, display=f"{float(confidence):.0f}%" if has_confidence else "—"))
            self.table.setItem(r, 4, table_item(sample_n, numeric=True, display=str(int(sample_n or 0))))
            self.table.setItem(r, 5, table_item(price, numeric=True, display=f"{float(price or 0):.2f}" if str(price) != "" else ""))
            self.table.setItem(r, 6, table_item(volume, numeric=True, display=fmt_large(volume)))
            self.table.setItem(r, 7, table_item(rel_vol, numeric=True, display=f"{float(rel_vol or 0):.2f}" if str(rel_vol) != "" else ""))
            self.table.setItem(r, 8, table_item(market_cap, numeric=True, display=fmt_large(market_cap)))
            self.table.setItem(r, 9, table_item(cap_bucket))
            self.table.setItem(r, 10, table_item(sector))
            self.table.setItem(r, 11, table_item(rsi14, numeric=True, display=f"{float(rsi14 or 0):.1f}" if str(rsi14) != "" else ""))
            self.table.setItem(r, 12, table_item(atr_pct, numeric=True, display=f"{float(atr_pct or 0):.2f}%" if str(atr_pct) != "" else ""))
            self.table.setItem(r, 13, table_item(ema_trend))
            self.table.setItem(r, 14, table_item(macd_state))

            is_error = str(signal).upper() == "ERROR"
            if is_error:
                error_text = row.get("Error", "")
                item = self.table.item(r, 0)
                if item and error_text:
                    item.setToolTip(str(error_text))

            try:
                score_f = float(score or 0)
                bg = colors.score_row_color(score_f, is_error=is_error)
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    if it:
                        it.setBackground(bg)
            except Exception:
                pass

            for col, color in (
                (1, colors.signal_color(signal)),
                (11, colors.rsi_zone_color(rsi14)),
                (13, colors.trend_color(ema_trend)),
                (14, colors.trend_color(macd_state)),
            ):
                if color is None:
                    continue
                it = self.table.item(r, col)
                if it:
                    it.setForeground(color)
        self.table.setSortingEnabled(True)
        self.result_status.setText(f"Results: {len(df)}{self._sector_breakdown_text(df)}")
        if len(df) <= 200:
            self.table.resizeColumnsToContents()

    def _sector_breakdown_text(self, df: pd.DataFrame) -> str:
        if df.empty or "Sector" not in df.columns:
            return ""
        counts = df.loc[df["Sector"].astype(bool), "Sector"].value_counts()
        if counts.empty:
            return ""
        top = "  |  ".join(f"{sector}: {count}" for sector, count in counts.head(5).items())
        more = len(counts) - 5
        if more > 0:
            top += f"  |  +{more} more sector{'s' if more != 1 else ''}"
        return f"   —   {top}"

    def result_symbols(self) -> list:
        """Valid (non-error) symbols from the current results, best score first."""
        if self.results is None or self.results.empty or "Symbol" not in self.results.columns:
            return []
        out = []
        for _, row in self.results.iterrows():
            if str(row.get("Signal", "")) == "ERROR":
                continue
            sym = str(row.get("Symbol", "")).strip().upper()
            if sym:
                out.append(sym)
        return out

    def show_results_in_heatmap(self):
        syms = self.result_symbols()
        if not syms:
            self.status.setText("Run a scan first — no results to map.")
            return
        if self.on_show_heatmap:
            self.on_show_heatmap(syms)
        else:
            self.status.setText("Heatmap is not available.")

    def export_results(self):
        if self.results.empty:
            QMessageBox.information(self, "Export", "No scan results to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export scan results", f"{self.scan_name.text().strip() or 'scan_results'}.csv", "CSV files (*.csv)")
        if path:
            self.results.to_csv(path, index=False)
            self.status.setText(f"Exported {len(self.results)} rows to {path}")

    def selected_symbol(self):
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.text() if item else None

    def selected_symbols(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        symbols = []
        for row in rows:
            item = self.table.item(row, 0)
            if item and item.text() not in symbols:
                symbols.append(item.text())
        return symbols

    def selected_price_for_row(self, row):
        item = self.table.item(row, 5)
        try: return float(item.text()) if item else 0.0
        except Exception: return 0.0

    def selected_price(self):
        row = self.table.currentRow()
        if row < 0: return 0.0
        item = self.table.item(row, 5)
        try: return float(item.text()) if item else 0.0
        except Exception: return 0.0

    def load_chart_from_row(self, row, _col):
        item = self.table.item(row, 0)
        if item: self.plot_symbol(item.text())

    def load_selected_chart(self):
        sym=self.selected_symbol()
        if sym: self.plot_symbol(sym)

    def plot_symbol(self, symbol):
        df = get_history(symbol, self.cfg.period, self.cfg.interval)
        self.chart.plot(symbol, df, self.cfg)

    def add_selected_watch(self):
        symbols = self.selected_symbols()
        if not symbols:
            QMessageBox.information(self, "Watchlist", "Select one or more rows first.")
            return
        for symbol in symbols:
            self.db.add_watch_symbol(symbol)
        if self.on_watchlist_changed:
            self.on_watchlist_changed()
        self.status.setText(f"Added {len(symbols)} symbol(s) to Watchlist.")
        QMessageBox.information(self, "Watchlist", f"Added {len(symbols)} symbol(s) to Watchlist.")

    def add_selected_portfolio(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        if not rows:
            QMessageBox.information(self, "Portfolio", "Select one or more rows first.")
            return
        count = 0
        for row in rows:
            item = self.table.item(row, 0)
            if not item:
                continue
            symbol = item.text()
            price = self.selected_price_for_row(row)
            self.db.add_position(symbol, 0, price)
            count += 1
        if self.on_portfolio_changed:
            self.on_portfolio_changed()
        self.status.setText(f"Added {count} symbol(s) to Portfolio.")
        QMessageBox.information(self, "Portfolio", f"Added {count} symbol(s) to Portfolio.")


class WatchlistPanel(QWidget):
    def __init__(self, db: Database, chart: ChartWidget, cfg: ScannerConfig):
        super().__init__()
        self.db = db; self.chart = chart; self.cfg = cfg
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.symbol_edit = QLineEdit(); self.symbol_edit.setPlaceholderText("AAPL or RY.TO")
        add = QPushButton("Add"); add.clicked.connect(self.add)
        remove = QPushButton("Remove selected"); remove.clicked.connect(self.remove)
        import_btn = QPushButton("Import") ; import_btn.clicked.connect(self.import_watchlist)
        export_btn = QPushButton("Export") ; export_btn.clicked.connect(self.export_watchlist)
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        row.addWidget(self.symbol_edit); row.addWidget(add); row.addWidget(remove); row.addWidget(import_btn); row.addWidget(export_btn); row.addWidget(refresh)
        layout.addLayout(row)
        self.list = QListWidget(); self.list.setSelectionMode(QAbstractItemView.ExtendedSelection); self.list.itemDoubleClicked.connect(self.plot)
        layout.addWidget(self.list)
        self.status=QLabel("Double-click a symbol to load chart.")
        layout.addWidget(self.status)
        self.refresh()
    def refresh(self):
        self.list.clear(); syms=self.db.watch_symbols(); self.list.addItems(syms); self.status.setText(f"Watchlist: {len(syms)} symbols")
    def add(self):
        sym = self.symbol_edit.text().strip().upper()
        if sym:
            self.db.add_watch_symbol(sym); self.symbol_edit.clear(); self.refresh()
    def remove(self):
        items = self.list.selectedItems()
        for item in items:
            self.db.remove_watch_symbol(item.text())
        self.refresh()

    def import_watchlist(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import watchlist", "", "Text/CSV files (*.txt *.csv);;All files (*)")
        if not path:
            return
        import re
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        syms = [x.strip().upper() for x in re.split(r"[\s,;]+", text) if x.strip()]
        for sym in syms:
            self.db.add_watch_symbol(sym)
        self.refresh()

    def export_watchlist(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export watchlist", "watchlist.txt", "Text files (*.txt)")
        if path:
            Path(path).write_text("\n".join(self.db.watch_symbols()), encoding="utf-8")

    def plot(self, item):
        sym = item.text(); self.chart.plot(sym, get_history(sym, self.cfg.period, self.cfg.interval), self.cfg)


class PortfolioPanel(QWidget):
    def __init__(self, db: Database):
        super().__init__(); self.db = db
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.sym = QLineEdit(); self.sym.setPlaceholderText("Symbol")
        self.shares = QDoubleSpinBox(); self.shares.setRange(0, 1_000_000); self.shares.setValue(100)
        self.entry = QDoubleSpinBox(); self.entry.setRange(0, 1_000_000); self.entry.setPrefix("$")
        add = QPushButton("Add Position"); add.clicked.connect(self.add)
        delete = QPushButton("Delete selected"); delete.clicked.connect(self.delete)
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        row.addWidget(self.sym); row.addWidget(QLabel("Shares")); row.addWidget(self.shares); row.addWidget(QLabel("Entry")); row.addWidget(self.entry); row.addWidget(add); row.addWidget(delete); row.addWidget(refresh)
        layout.addLayout(row)
        export_btn = QPushButton("Export Portfolio"); export_btn.clicked.connect(self.export_portfolio); row.addWidget(export_btn)
        self.table = QTableWidget(0, 5); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table.setHorizontalHeaderLabels(["ID","Portfolio","Symbol","Shares","Entry"])
        layout.addWidget(self.table)
        self.status=QLabel("")
        layout.addWidget(self.status)
        self.refresh()
    def refresh(self):
        pos = self.db.positions(); self.table.setRowCount(len(pos))
        for r, p in enumerate(pos):
            for c, key in enumerate(["id","portfolio","symbol","shares","entry_price"]):
                self.table.setItem(r,c,QTableWidgetItem(str(p.get(key,""))))
        self.table.resizeColumnsToContents(); self.status.setText(f"Portfolio positions: {len(pos)}")
    def add(self):
        sym = self.sym.text().strip().upper()
        if sym:
            self.db.add_position(sym, self.shares.value(), self.entry.value()); self.sym.clear(); self.refresh()
    def delete(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            item = self.table.item(row,0)
            if item:
                self.db.delete_position(int(item.text()))
        self.refresh()

    def export_portfolio(self):
        import pandas as pd
        path, _ = QFileDialog.getSaveFileName(self, "Export portfolio", "portfolio.csv", "CSV files (*.csv)")
        if path:
            pd.DataFrame(self.db.positions()).to_csv(path, index=False)



class MarketPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout=QVBoxLayout(self)
        top=QHBoxLayout()
        self.refresh_btn=QPushButton("Refresh market dashboard")
        self.refresh_btn.clicked.connect(self.refresh_market)
        top.addWidget(QLabel("Market Dashboard")); top.addStretch(); top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        # Phase 3: "is it a good day to trade" macro read - a big, plain
        # headline plus the transparent reasons that produced it.
        self.read_box=QGroupBox("Is it a good day to trade?")
        read_layout=QVBoxLayout(self.read_box)
        self.read_headline=QLabel("Refresh to compute the market read.")
        self.read_headline.setStyleSheet("font-size:16px; font-weight:bold;")
        self.read_reasons=QLabel("")
        self.read_reasons.setWordWrap(True)
        self.read_reasons.setStyleSheet("color:#b8b8b8;")
        read_layout.addWidget(self.read_headline)
        read_layout.addWidget(self.read_reasons)
        layout.addWidget(self.read_box)

        layout.addWidget(QLabel("Regime symbols"))
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(["Item","Symbol","Last","Change %","Purpose"])
        layout.addWidget(self.table)

        layout.addWidget(QLabel("Sector breadth (SPDR sector ETFs)"))
        self.sector_table=QTableWidget(0,4); self.sector_table.setHorizontalHeaderLabels(["Sector","ETF","Change %","vs 50-day"])
        layout.addWidget(self.sector_table)

        self.status=QLabel("Refresh to update the dashboard. Data uses yfinance when available.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.rows=[('VIX','^VIX','Market fear / volatility'),('S&P 500','SPY','US market regime'),('NASDAQ 100','QQQ','Growth/technology regime'),('Russell 2000','IWM','Small-cap risk appetite'),('TSX','^GSPTSE','Canada market regime'),('USD/CAD','CAD=X','Currency for Canada exposure'),('Gold','GC=F','Risk/inflation proxy'),('Oil','CL=F','Energy/cyclical proxy'),('US 10Y','^TNX','Rates pressure')]
        self.populate_static()
    def populate_static(self):
        self.table.setRowCount(len(self.rows))
        for r,(name,sym,purpose) in enumerate(self.rows):
            vals=[name,sym,"","",purpose]
            for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()
        from tradelab.core.market import SECTOR_ETFS
        self.sector_table.setRowCount(len(SECTOR_ETFS))
        for r,(name,sym) in enumerate(SECTOR_ETFS):
            for c,v in enumerate([name,sym,"",""]): self.sector_table.setItem(r,c,QTableWidgetItem(str(v)))
        self.sector_table.resizeColumnsToContents()
    def refresh_market(self):
        from tradelab.core.market import SECTOR_ETFS, analyze_trend, sector_breadth, market_condition
        self.refresh_btn.setEnabled(False)
        regime_trends={}
        for r,(name,sym,purpose) in enumerate(self.rows):
            try:
                df=get_history(sym,"1y","1d")
                trend=analyze_trend(df)
                regime_trends[sym]=trend
                last=trend["last"]; ch=trend["change_pct"]
                self.table.setItem(r,2,QTableWidgetItem(f"{last:.2f}" if last is not None else "—"))
                self.table.setItem(r,3,QTableWidgetItem(f"{ch:+.2f}%" if ch is not None else "—"))
            except Exception as exc:
                self.table.setItem(r,2,QTableWidgetItem("ERR"))
                self.table.setItem(r,3,QTableWidgetItem(str(exc)[:40]))
        self.table.resizeColumnsToContents()

        sector_trends={}
        for r,(name,sym) in enumerate(SECTOR_ETFS):
            try:
                trend=analyze_trend(get_history(sym,"1y","1d"))
                sector_trends[name]=trend
                ch=trend["change_pct"]
                self.sector_table.setItem(r,2,QTableWidgetItem(f"{ch:+.2f}%" if ch is not None else "—"))
                above=trend["above_sma50"]
                self.sector_table.setItem(r,3,QTableWidgetItem("Above" if above else ("Below" if above is False else "—")))
            except Exception as exc:
                self.sector_table.setItem(r,2,QTableWidgetItem("ERR"))
                self.sector_table.setItem(r,3,QTableWidgetItem(str(exc)[:20]))
        self.sector_table.resizeColumnsToContents()

        breadth=sector_breadth(sector_trends)
        spy_trend=regime_trends.get("SPY",{})
        vix_last=(regime_trends.get("^VIX") or {}).get("last")
        read=market_condition(spy_trend, vix_last, breadth)
        colour={"Favorable":"#3fb950","Neutral / mixed":"#e3b341","Caution":"#e5534b"}.get(read["label"],"#c7d0d8")
        self.read_headline.setText(f"{read['label']}  ·  {read['score']}/100")
        self.read_headline.setStyleSheet(f"font-size:16px; font-weight:bold; color:{colour};")
        self.read_reasons.setText("  •  ".join(read["reasons"]) if read["reasons"] else "Not enough data for a confident read.")
        self.status.setText(f"Dashboard refreshed. Breadth: {breadth['advancing']}/{breadth['total']} sectors up today, {breadth['above_sma50']}/{breadth['measured_sma50']} above their 50-day average.")
        self.refresh_btn.setEnabled(True)


def _build_condition_row(condition, on_change, on_remove, removable=True):
    """Build one condition-editing row: field + (tunable) period + operator +
    value(s) OR a second field + its period. Shared by the Scanner's custom
    filters, the Strategy Builder, and the Alerts builder so they stay
    identical. Pass removable=False for a single fixed row (Alerts) with no
    × delete button. Returns (row_widget, widgets_dict)."""
    from tradelab.core.filters import (field_choices, field_has_period,
                                       field_default_period, OPERATORS, FIELD_OPERATORS)
    row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
    field = QComboBox()
    for key, label in field_choices():
        field.addItem(label, key)
    fi = field.findData(condition.field); field.setCurrentIndex(fi if fi >= 0 else 0)
    period = QSpinBox(); period.setRange(1, 500); period.setMaximumWidth(60)
    period.setValue(int(condition.period or field_default_period(condition.field) or 14))
    op = QComboBox(); op.addItems(OPERATORS); op.setCurrentText(condition.operator)
    v1 = QDoubleSpinBox(); v1.setRange(-1e9, 1e9); v1.setDecimals(2); v1.setValue(condition.value1)
    v2 = QDoubleSpinBox(); v2.setRange(-1e9, 1e9); v2.setDecimals(2)
    v2.setValue(condition.value2 if condition.value2 is not None else condition.value1)
    field2 = QComboBox()
    for key, label in field_choices():
        field2.addItem(label, key)
    f2 = field2.findData(condition.field2); field2.setCurrentIndex(f2 if f2 >= 0 else 0)
    period2 = QSpinBox(); period2.setRange(1, 500); period2.setMaximumWidth(60)
    period2.setValue(int(condition.period2 or field_default_period(field2.currentData()) or 14))

    def sync():
        is_field = op.currentText() in FIELD_OPERATORS
        period.setVisible(field_has_period(field.currentData()))
        v1.setVisible(not is_field)
        v2.setVisible(op.currentText() == "Between")
        field2.setVisible(is_field)
        period2.setVisible(is_field and field_has_period(field2.currentData()))

    def on_field_change():
        p = field_default_period(field.currentData())
        if p:
            period.setValue(p)  # pick a new indicator -> pre-fill its default period
        sync()

    def on_field2_change():
        p = field_default_period(field2.currentData())
        if p:
            period2.setValue(p)
        sync()

    field.currentTextChanged.connect(on_field_change)
    field2.currentTextChanged.connect(on_field2_change)
    op.currentTextChanged.connect(sync)
    sync()

    widgets = {"row": row, "field": field, "period": period, "op": op,
               "v1": v1, "v2": v2, "field2": field2, "period2": period2}
    if on_change:
        for w in (field, period, op, v1, v2, field2, period2):
            try: w.currentTextChanged.connect(lambda *_: on_change())
            except Exception: pass
            try: w.valueChanged.connect(lambda *_: on_change())
            except Exception: pass
    h.addWidget(field, 2); h.addWidget(period); h.addWidget(op, 1)
    h.addWidget(v1, 1); h.addWidget(v2, 1); h.addWidget(field2, 2); h.addWidget(period2)
    if removable:
        rm = QToolButton(); rm.setText("×"); rm.setMaximumWidth(24); rm.clicked.connect(lambda: on_remove(row))
        h.addWidget(rm)
    return row, widgets


def _row_to_condition(w):
    from tradelab.core.filters import FilterCondition, FIELD_OPERATORS, field_has_period
    op = w["op"].currentText()
    is_field = op in FIELD_OPERATORS
    return FilterCondition(
        field=w["field"].currentData(),
        period=(w["period"].value() if field_has_period(w["field"].currentData()) else None),
        operator=op,
        value1=w["v1"].value(),
        value2=(w["v2"].value() if op == "Between" else None),
        field2=(w["field2"].currentData() if is_field else None),
        period2=(w["period2"].value() if is_field and field_has_period(w["field2"].currentData()) else None),
    )


class ConditionListWidget(QWidget):
    """A reusable list of add/remove filter-condition rows (field + operator
    + value[s]), shared by the Strategy Builder's BUY and SELL blocks. Each
    row edits one FilterCondition (the same type the Scanner filter builder
    and custom strategies use)."""
    def __init__(self, on_change=None):
        super().__init__()
        self._on_change = on_change
        self._rows = []
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0)
        self._rows_layout = QVBoxLayout(); self._rows_layout.setSpacing(4)
        v.addLayout(self._rows_layout)
        add = QPushButton("+ Add condition"); add.clicked.connect(lambda: self.add_row())
        v.addWidget(add)

    def add_row(self, condition=None):
        from tradelab.core.filters import FIELD_SPECS, FilterCondition
        condition = condition or FilterCondition(field=next(iter(FIELD_SPECS)))
        row, widgets = _build_condition_row(condition, self._on_change, self.remove_row)
        self._rows_layout.addWidget(row)
        self._rows.append(widgets)
        if self._on_change: self._on_change()

    def remove_row(self, row):
        self._rows = [r for r in self._rows if r["row"] is not row]
        self._rows_layout.removeWidget(row); row.deleteLater()
        if self._on_change: self._on_change()

    def get_conditions(self):
        return [_row_to_condition(r) for r in self._rows]

    def set_conditions(self, conditions):
        for r in list(self._rows):
            self.remove_row(r["row"])
        for c in conditions:
            self.add_row(c)


class StrategyBuilderPanel(QWidget):
    """Phase 5 no-code Strategy Builder. Build a strategy from BUY/SELL
    condition blocks, save/load/delete it, and it becomes a real runnable
    strategy in the Scanner and Backtest dropdowns via the registry.
    """
    def __init__(self, on_strategies_changed=None):
        super().__init__()
        self._on_strategies_changed = on_strategies_changed
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("Build your own strategy with no code: pick conditions for when to BUY and when to SELL. Saved strategies appear in the Scanner and Backtest strategy dropdowns and run just like the built-in ones."))

        top = QHBoxLayout()
        self.name = QComboBox(); self.name.setEditable(True); self.name.setInsertPolicy(QComboBox.NoInsert)
        self.name.setEditText("My Strategy")
        self.name.activated.connect(self._on_name_picked)
        new_btn = QPushButton("New"); new_btn.clicked.connect(self.new_strategy)
        save_btn = QPushButton("Save"); save_btn.clicked.connect(self.save_strategy)
        delete_btn = QPushButton("Delete"); delete_btn.clicked.connect(self.delete_strategy)
        top.addWidget(QLabel("Name")); top.addWidget(self.name, 1)
        top.addWidget(new_btn); top.addWidget(save_btn); top.addWidget(delete_btn)
        layout.addLayout(top)

        layout.addWidget(QLabel("BUY when ALL of these are true:"))
        self.buy_conditions = ConditionListWidget(on_change=self.update_preview)
        layout.addWidget(self.buy_conditions)
        layout.addWidget(QLabel("SELL when ALL of these are true:"))
        self.sell_conditions = ConditionListWidget(on_change=self.update_preview)
        layout.addWidget(self.sell_conditions)

        self.preview = QTextEdit(); self.preview.setReadOnly(True); self.preview.setMaximumHeight(120)
        layout.addWidget(QLabel("Plain-English preview:")); layout.addWidget(self.preview)
        self.status = QLabel(""); self.status.setWordWrap(True); layout.addWidget(self.status)
        layout.addStretch()

        # Start with a sensible example so the panel isn't blank.
        from tradelab.core.filters import FilterCondition
        self.buy_conditions.set_conditions([FilterCondition(field="rsi14", operator="Below", value1=35)])
        self.sell_conditions.set_conditions([FilterCondition(field="rsi14", operator="Above", value1=65)])
        self.refresh_saved_list()
        self.update_preview()

    def refresh_saved_list(self):
        from tradelab.strategies.custom import list_custom_strategies
        current = self.name.currentText()
        self.name.blockSignals(True)
        self.name.clear(); self.name.addItems(list_custom_strategies())
        self.name.setEditText(current)
        self.name.blockSignals(False)

    def _on_name_picked(self, index):
        name = self.name.itemText(index)
        if name:
            self.load_strategy(name)

    def _current_strategy(self):
        from tradelab.strategies.custom import CustomStrategy
        return CustomStrategy(self.name.currentText().strip() or "My Strategy",
                              self.buy_conditions.get_conditions(),
                              self.sell_conditions.get_conditions())

    def update_preview(self):
        strat = self._current_strategy()
        lines = []
        if strat.buy_conditions:
            lines.append("BUY when ALL of:")
            lines += [f"   • {c.label()}" for c in strat.buy_conditions]
        else:
            lines.append("BUY: (no conditions — this strategy will never buy)")
        lines.append("")
        if strat.sell_conditions:
            lines.append("SELL when ALL of:")
            lines += [f"   • {c.label()}" for c in strat.sell_conditions]
        else:
            lines.append("SELL: (no conditions — position stays open until the data ends)")
        self.preview.setText("\n".join(lines))

    def new_strategy(self):
        from tradelab.core.filters import FilterCondition
        self.name.setEditText("My Strategy")
        self.buy_conditions.set_conditions([FilterCondition(field="rsi14", operator="Below", value1=35)])
        self.sell_conditions.set_conditions([FilterCondition(field="rsi14", operator="Above", value1=65)])
        self.update_preview()
        self.status.setText("New strategy started. Add conditions, then Save.")

    def save_strategy(self):
        strat = self._current_strategy()
        if not strat.buy_conditions:
            QMessageBox.warning(self, "Strategy", "Add at least one BUY condition before saving.")
            return
        path = strat.save()
        self.refresh_saved_list()
        self.status.setText(f"Saved strategy: {path.name}. It's now in the Scanner and Backtest strategy lists.")
        if self._on_strategies_changed:
            self._on_strategies_changed()

    def load_strategy(self, name):
        from tradelab.strategies.custom import load_custom_strategy
        strat = load_custom_strategy(name)
        if strat is None:
            self.status.setText(f"Could not load strategy: {name}"); return
        self.name.setEditText(strat.name)
        self.buy_conditions.set_conditions(strat.buy_conditions)
        self.sell_conditions.set_conditions(strat.sell_conditions)
        self.update_preview()
        self.status.setText(f"Loaded strategy: {name}")

    def delete_strategy(self):
        from tradelab.strategies.custom import delete_custom_strategy
        name = self.name.currentText().strip()
        if delete_custom_strategy(name):
            self.refresh_saved_list()
            self.status.setText(f"Deleted strategy: {name}")
            if self._on_strategies_changed:
                self._on_strategies_changed()
        else:
            self.status.setText(f"No saved strategy named '{name}' to delete.")


def _fill_table(table, columns, rows):
    """Populate a QTableWidget from a list of dicts (or (k,v) pairs)."""
    table.clear()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, key in enumerate(columns):
            val = row.get(key, "") if isinstance(row, dict) else row[c]
            table.setItem(r, c, QTableWidgetItem(str(val)))
    table.resizeColumnsToContents()


def _hint(text):
    """A muted, wrapped one-line explanation shown above a control, so the
    Backtest tab explains itself in plain language rather than assuming the
    user already knows what a walk-forward or profit factor is."""
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color:#8b98a5; font-style:italic;")
    return lbl


def _scroll_tab(widget):
    """Wrap a tab page in a widget-resizable scroll area so it can shrink.

    A QStackedWidget (what QTabWidget uses) adopts its TALLEST page as the
    whole stack's minimum height. Without this, one tall tab - the Scanner
    needs ~1330px for its parameters + results table - forces the entire
    window taller than a 1080p screen, so the bottom of every tab (and the
    charts) gets clipped and can't be reached. A scroll area lets each page
    still fill a tall pane, but scroll internally instead of overflowing a
    short one, so the window can always fit on screen.
    """
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setWidget(widget)
    return sa


class FlowLayout(QLayout):
    """A layout that lays its items left-to-right and wraps to new rows as
    width runs out (the classic Qt flow-layout). Used for the tab bar so every
    tab button stays visible across two (or more) rows instead of overflowing
    into a scroll arrow."""

    def __init__(self, parent=None, margin=0, hspacing=3, vspacing=3):
        super().__init__(parent)
        self._hspace = hspacing
        self._vspace = vspacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._hspace
            if next_x - self._hspace > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self._vspace
                next_x = x + hint.width() + self._hspace
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class MultiRowTabs(QWidget):
    """A drop-in-ish replacement for QTabWidget whose tab bar **wraps to
    multiple rows** (via FlowLayout), so all tabs stay visible with no overflow
    arrows. Implements the subset of the QTabWidget API this app uses."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        self._bar = QWidget()
        sp = self._bar.sizePolicy(); sp.setHeightForWidth(True); self._bar.setSizePolicy(sp)
        # Compact buttons (small font/padding = more per row = fewer rows) with
        # a clear "current tab" highlight (works light/dark).
        self._bar.setStyleSheet(
            "QToolButton{padding:2px 6px; font-size:11px; border:1px solid palette(mid); border-radius:3px;}"
            "QToolButton:hover{border-color:#2d5aa0;}"
            "QToolButton:checked{background:#2d5aa0; color:white; border:1px solid #2d5aa0;}")
        self._flow = FlowLayout(self._bar, hspacing=2, vspacing=2)
        outer.addWidget(self._bar)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)
        self._buttons = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

    def addTab(self, widget, label):
        index = self._stack.count()
        self._stack.addWidget(widget)
        btn = QToolButton()
        btn.setText(label)
        btn.setCheckable(True)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, i=index: self.setCurrentIndex(i))
        self._group.addButton(btn, index)
        self._flow.addWidget(btn)
        self._buttons.append(btn)
        if index == 0:
            btn.setChecked(True)
            self._stack.setCurrentIndex(0)
        return index

    # --- QTabWidget-compatible surface used by the app/tests ---
    def setCurrentIndex(self, index):
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
            self._buttons[index].setChecked(True)

    def currentIndex(self):
        return self._stack.currentIndex()

    def currentWidget(self):
        return self._stack.currentWidget()

    def setCurrentWidget(self, widget):
        i = self._stack.indexOf(widget)
        if i >= 0:
            self.setCurrentIndex(i)

    def count(self):
        return self._stack.count()

    def widget(self, index):
        return self._stack.widget(index)

    def tabText(self, index):
        return self._buttons[index].text() if 0 <= index < len(self._buttons) else ""


class BacktestPanel(QWidget):
    """Backtesting Lab (Phase 4): single-symbol, multi-symbol, parameter
    optimization, and walk-forward - all strategy-agnostic via the engine
    in tradelab/core/backtest.py.
    """
    def __init__(self, chart: ChartWidget, cfg: ScannerConfig):
        super().__init__(); self.chart=chart; self.cfg=cfg
        layout=QVBoxLayout(self)

        common=QHBoxLayout()
        self.strategy=QComboBox()
        for key, name in strategy_choices():
            self.strategy.addItem(name, key)
        self.period=QComboBox(); self.period.addItems(["6mo","1y","2y","5y","10y","max"]); self.period.setCurrentText("5y")
        self.interval=QComboBox(); self.interval.addItems(["1d","1wk","1mo"]); self.interval.setCurrentText("1d")
        common.addWidget(QLabel("Strategy")); common.addWidget(self.strategy)
        common.addWidget(QLabel("Period")); common.addWidget(self.period)
        common.addWidget(QLabel("Interval")); common.addWidget(self.interval); common.addStretch()
        layout.addLayout(common)
        layout.addWidget(_hint("Backtesting replays past prices and pretends to follow the strategy's buy/sell signals, to check whether it would have made money. Nothing here places real trades."))

        self.tabs=QTabWidget()
        self.tabs.addTab(self._build_single(), "Single")
        self.tabs.addTab(self._build_multi(), "Multi-Symbol")
        self.tabs.addTab(self._build_optimize(), "Optimize")
        self.tabs.addTab(self._build_walk_forward(), "Walk-Forward")
        layout.addWidget(self.tabs)

        self.status=QLabel("Research only, not financial advice."); self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def _base_cfg(self):
        cfg=ScannerConfig()
        cfg.period=self.period.currentText(); cfg.interval=self.interval.currentText()
        cfg.strategy=self.strategy.currentData()
        return cfg

    def refresh_strategies(self):
        current=self.strategy.currentData()
        self.strategy.blockSignals(True); self.strategy.clear()
        for key, name in strategy_choices():
            self.strategy.addItem(name, key)
        idx=self.strategy.findData(current)
        self.strategy.setCurrentIndex(idx if idx>=0 else 0)
        self.strategy.blockSignals(False)

    # -- Single --------------------------------------------------------
    def _build_single(self):
        w=QWidget(); v=QVBoxLayout(w)
        v.addWidget(_hint("Tests the strategy on ONE stock. The plain-English verdict below the table tells you if it would have made money and how bumpy the ride was."))
        row=QHBoxLayout()
        self.single_symbol=QLineEdit("AAPL")
        run=QPushButton("Run backtest"); run.clicked.connect(self.run_single)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.single_symbol); row.addWidget(run); row.addStretch()
        v.addLayout(row)
        self.single_verdict=QLabel(""); self.single_verdict.setWordWrap(True); self.single_verdict.setStyleSheet("font-weight:bold;")
        v.addWidget(self.single_verdict)
        self.metrics=QTableWidget(0,2); self.metrics.setHorizontalHeaderLabels(["Metric","Value"]); v.addWidget(self.metrics)
        self.trades=QTableWidget(0,5); self.trades.setHorizontalHeaderLabels(["Entry Date","Exit Date","Entry","Exit","Return %"]); v.addWidget(self.trades)
        return w

    def run_single(self):
        from tradelab.core.backtest import backtest_symbol
        cfg=self._base_cfg(); sym=self.single_symbol.text().strip().upper()
        self.status.setText(f"Backtesting {sym}...")
        res=backtest_symbol(sym, cfg)
        _fill_table(self.metrics, ["Metric","Value"], [{"Metric":k,"Value":v} for k,v in res.metrics.items()])
        _fill_table(self.trades, ["Entry Date","Exit Date","Entry","Exit","Return %"],
                    res.trades.to_dict("records") if not res.trades.empty else [])
        self._set_single_verdict(sym, res.metrics)
        try:
            self.chart.plot(sym, get_history(sym, cfg.period, cfg.interval), cfg)
        except Exception: pass
        self.status.setText(f"Backtest complete: {len(res.trades)} trade rows.")

    def _set_single_verdict(self, sym, m):
        if m.get("Error") or not m.get("Closed trades"):
            self.single_verdict.setText(f"{sym}: not enough completed trades to judge over this period.")
            self.single_verdict.setStyleSheet("font-weight:bold; color:#8b98a5;")
            return
        total=m.get("Total return %",0); win=m.get("Win rate %",0); dd=m.get("Max drawdown %",0); n=m.get("Closed trades",0)
        if total>0:
            word, colour = ("made money", "#3fb950")
        else:
            word, colour = ("lost money", "#e5534b")
        self.single_verdict.setText(
            f"{sym}: this strategy would have {word} ({total:+.1f}%) over the period, "
            f"winning {win:.0f}% of its {n} trades. Worst dip along the way: -{dd:.1f}%.")
        self.single_verdict.setStyleSheet(f"font-weight:bold; color:{colour};")

    # -- Multi-symbol --------------------------------------------------
    def _build_multi(self):
        w=QWidget(); v=QVBoxLayout(w)
        v.addWidget(_hint("Tests the strategy on MANY stocks at once. If it only works on one lucky name it isn't reliable — look at the overall verdict to see if it works in general."))
        row=QHBoxLayout()
        self.multi_symbols=QLineEdit("AAPL, MSFT, GOOG, AMZN, NVDA")
        run=QPushButton("Run"); run.clicked.connect(self.run_multi)
        row.addWidget(QLabel("Symbols")); row.addWidget(self.multi_symbols, 1); row.addWidget(run)
        v.addLayout(row)
        self.multi_verdict=QLabel(""); self.multi_verdict.setWordWrap(True); self.multi_verdict.setStyleSheet("font-weight:bold;")
        v.addWidget(self.multi_verdict)
        self.multi_table=QTableWidget(0,6); self.multi_table.setHorizontalHeaderLabels(["Symbol","Trades","Win rate %","Total return %","Profit factor","Max drawdown %"]); v.addWidget(self.multi_table, 1)
        self.multi_agg=QLabel(""); self.multi_agg.setWordWrap(True); self.multi_agg.setStyleSheet("color:#8b98a5;"); v.addWidget(self.multi_agg)
        return w

    def run_multi(self):
        from tradelab.core.backtest import backtest_multi
        cfg=self._base_cfg()
        syms=[s.strip().upper() for s in self.multi_symbols.text().replace(";",",").split(",") if s.strip()]
        if not syms:
            self.status.setText("Enter at least one symbol."); return
        self.status.setText(f"Backtesting {len(syms)} symbols...")
        result=backtest_multi(syms, cfg)
        _fill_table(self.multi_table, ["Symbol","Trades","Win rate %","Total return %","Profit factor","Max drawdown %"],
                    result["per_symbol"].to_dict("records"))
        agg=result["aggregate"]
        self.multi_agg.setText("Details:  "+"   |   ".join(f"{k}: {v}" for k,v in agg.items()))
        self._set_multi_verdict(agg)
        self.status.setText(f"Multi-symbol backtest complete: {agg['Symbols tested']} symbols.")

    def _set_multi_verdict(self, agg):
        n=agg.get("Total closed trades",0); win=agg.get("Overall win rate %",0); avg=agg.get("Avg trade return %",0)
        if not n:
            self.multi_verdict.setText("No completed trades across these symbols in this period.");
            self.multi_verdict.setStyleSheet("font-weight:bold; color:#8b98a5;"); return
        if win>=55 and avg>0:
            verdict, colour = ("looks solid across the board", "#3fb950")
        elif win>=45 and avg>0:
            verdict, colour = ("is mixed but slightly positive", "#e3b341")
        else:
            verdict, colour = ("does not hold up across these names", "#e5534b")
        self.multi_verdict.setText(
            f"Across {agg.get('Symbols tested',0)} stocks, this strategy {verdict}: "
            f"it won {win:.0f}% of {n} trades, averaging {avg:+.2f}% per trade.")
        self.multi_verdict.setStyleSheet(f"font-weight:bold; color:{colour};")

    # -- Optimize ------------------------------------------------------
    def _build_optimize(self):
        w=QWidget(); v=QVBoxLayout(w)
        v.addWidget(_hint("Tries different values for ONE setting and ranks them best-first. The top row is the value that performed best — but a single standout spike is often luck; prefer a value whose neighbours also did well."))
        row=QHBoxLayout()
        self.opt_symbol=QLineEdit("AAPL")
        self.opt_param=QComboBox(); self.opt_param.addItems(["ema_slow","ema_fast","min_score","macd_slow"])
        self.opt_values=QLineEdit("20, 30, 40, 50")
        run=QPushButton("Optimize"); run.clicked.connect(self.run_optimize)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.opt_symbol)
        row.addWidget(QLabel("Parameter")); row.addWidget(self.opt_param)
        row.addWidget(QLabel("Values")); row.addWidget(self.opt_values, 1); row.addWidget(run)
        v.addLayout(row)
        self.opt_verdict=QLabel(""); self.opt_verdict.setWordWrap(True); self.opt_verdict.setStyleSheet("font-weight:bold;")
        v.addWidget(self.opt_verdict)
        self.opt_table=QTableWidget(0,6); v.addWidget(self.opt_table, 1)
        return w

    def run_optimize(self):
        from tradelab.core.backtest import optimize
        cfg=self._base_cfg(); sym=self.opt_symbol.text().strip().upper()
        param=self.opt_param.currentText()
        raw=[x.strip() for x in self.opt_values.text().replace(";",",").split(",") if x.strip()]
        try:
            values=[int(x) if x.lstrip("-").isdigit() else float(x) for x in raw]
        except ValueError:
            self.status.setText("Values must be numbers."); return
        if not values:
            self.status.setText("Enter at least one value to test."); return
        self.status.setText(f"Optimizing {param} over {len(values)} values...")
        df=optimize(sym, cfg, param, values)
        cols=list(df.columns) if not df.empty else [param]
        _fill_table(self.opt_table, cols, df.to_dict("records") if not df.empty else [])
        if df.empty:
            self.opt_verdict.setText("Not enough data to test these values.")
            self.opt_verdict.setStyleSheet("font-weight:bold; color:#8b98a5;")
        else:
            best=df.iloc[0]
            self.opt_verdict.setText(
                f"Best {param} = {best[param]} (total return {best.get('Total return %',0):+.1f}%, "
                f"win rate {best.get('Win rate %',0):.0f}%). It's at the top of the table.")
            self.opt_verdict.setStyleSheet("font-weight:bold; color:#3fb950;")
        self.status.setText("Optimization complete.")

    # -- Walk-forward --------------------------------------------------
    def _build_walk_forward(self):
        w=QWidget(); v=QVBoxLayout(w)
        v.addWidget(_hint("Splits the history into separate time periods and tests each one. This is the honesty check: a strategy that only worked in one lucky period is probably overfit. High consistency = trustworthy."))
        row=QHBoxLayout()
        self.wf_symbol=QLineEdit("AAPL")
        self.wf_splits=QSpinBox(); self.wf_splits.setRange(2,10); self.wf_splits.setValue(4)
        run=QPushButton("Run walk-forward"); run.clicked.connect(self.run_walk_forward)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.wf_symbol)
        row.addWidget(QLabel("Windows")); row.addWidget(self.wf_splits); row.addWidget(run); row.addStretch()
        v.addLayout(row)
        self.wf_verdict=QLabel(""); self.wf_verdict.setWordWrap(True); self.wf_verdict.setStyleSheet("font-weight:bold;")
        v.addWidget(self.wf_verdict)
        self.wf_table=QTableWidget(0,6); self.wf_table.setHorizontalHeaderLabels(["Window","From","To","Trades","Win rate %","Total return %"]); v.addWidget(self.wf_table, 1)
        self.wf_summary=QLabel(""); self.wf_summary.setWordWrap(True); self.wf_summary.setStyleSheet("color:#8b98a5;"); v.addWidget(self.wf_summary)
        return w

    def run_walk_forward(self):
        from tradelab.core.backtest import walk_forward
        cfg=self._base_cfg(); sym=self.wf_symbol.text().strip().upper()
        self.status.setText(f"Running walk-forward on {sym}...")
        result=walk_forward(sym, cfg, n_splits=self.wf_splits.value())
        wins=result["windows"]
        _fill_table(self.wf_table, ["Window","From","To","Trades","Win rate %","Total return %"],
                    wins.to_dict("records") if not wins.empty else [])
        if wins.empty:
            self.wf_verdict.setText("Not enough data for the requested number of windows — try fewer windows or a longer period.")
            self.wf_verdict.setStyleSheet("font-weight:bold; color:#8b98a5;")
            self.wf_summary.setText("")
        else:
            n=len(wins); profitable=int(round(result['consistency']/100*n)); c=result['consistency']
            if c>=75:
                word, colour = ("reliable", "#3fb950")
            elif c>=50:
                word, colour = ("somewhat reliable", "#e3b341")
            else:
                word, colour = ("unreliable (likely overfit)", "#e5534b")
            self.wf_verdict.setText(f"This strategy made money in {profitable} of {n} time periods ({c:.0f}%) — {word}.")
            self.wf_verdict.setStyleSheet(f"font-weight:bold; color:{colour};")
            self.wf_summary.setText("A robust strategy is profitable across most windows, not just one.")
        self.status.setText("Walk-forward complete.")


class ReplayPanel(QWidget):
    """Bar-by-bar chart replay: load history, hide the future, and step or
    auto-play forward one candle at a time to practice reading a chart as it
    develops. Indicators recompute only on the revealed bars, so there is no
    look-ahead."""

    # Label -> milliseconds between bars while playing.
    _SPEEDS = {"0.5×": 1600, "1×": 800, "2×": 400, "4×": 200, "8×": 100}

    def __init__(self, chart: ChartWidget, cfg: ScannerConfig):
        super().__init__()
        self.chart = chart
        self.cfg = ScannerConfig()
        self.cfg.interval = "1d"
        self.data = None
        self.symbol_text = ""
        self.index = 0
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Practice reading a chart with the future hidden. Load a symbol, pick where "
            "to start, then Play or step candle by candle. Indicators only use the "
            "revealed bars — no peeking ahead."))

        row = QHBoxLayout()
        self.symbol = QLineEdit("AAPL"); self.symbol.setMaximumWidth(110)
        self.period = QComboBox(); self.period.addItems(["1y", "2y", "5y", "10y", "max"]); self.period.setCurrentText("2y")
        self.start_bars = QSpinBox(); self.start_bars.setRange(2, 5000); self.start_bars.setValue(60)
        self.start_bars.setToolTip("How many bars to reveal before you start stepping.")
        load = QPushButton("Load replay"); load.clicked.connect(self.load_replay)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.symbol)
        row.addWidget(QLabel("Period")); row.addWidget(self.period)
        row.addWidget(QLabel("Start at bar")); row.addWidget(self.start_bars)
        row.addWidget(load); row.addStretch()
        layout.addLayout(row)

        controls = QHBoxLayout()
        self.reset_btn = QToolButton(); self.reset_btn.setText("⏮"); self.reset_btn.setToolTip("Back to the start bar"); self.reset_btn.clicked.connect(self.reset)
        self.back_btn = QToolButton(); self.back_btn.setText("◀"); self.back_btn.setToolTip("Step back one bar"); self.back_btn.clicked.connect(lambda: self.step(-1))
        self.play_btn = QToolButton(); self.play_btn.setText("▶ Play"); self.play_btn.clicked.connect(self.toggle_play)
        self.fwd_btn = QToolButton(); self.fwd_btn.setText("▶"); self.fwd_btn.setToolTip("Step forward one bar"); self.fwd_btn.clicked.connect(lambda: self.step(1))
        self.end_btn = QToolButton(); self.end_btn.setText("⏭"); self.end_btn.setToolTip("Reveal all bars"); self.end_btn.clicked.connect(self.to_end)
        self.speed = QComboBox(); self.speed.addItems(list(self._SPEEDS.keys())); self.speed.setCurrentText("1×")
        self.speed.currentTextChanged.connect(self._on_speed_changed)
        for w in (self.reset_btn, self.back_btn, self.play_btn, self.fwd_btn, self.end_btn):
            controls.addWidget(w)
        controls.addWidget(QLabel("Speed")); controls.addWidget(self.speed)
        controls.addStretch()
        layout.addLayout(controls)

        self.slider = QSlider(Qt.Horizontal); self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

        self.status = QLabel("Load a symbol to begin.")
        layout.addWidget(self.status)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._set_controls_enabled(False)

    # --- loading ----------------------------------------------------------
    def load_replay(self):
        self.symbol_text = self.symbol.text().strip().upper()
        if not self.symbol_text:
            self.status.setText("Enter a symbol first.")
            return
        self.cfg.period = self.period.currentText()
        self.cfg.interval = "1d"
        self.data = get_history(self.symbol_text, self.cfg.period, self.cfg.interval)
        if self.data is None or self.data.empty:
            self.status.setText(f"No data for {self.symbol_text}.")
            return
        n = len(self.data)
        self.index = max(2, min(self.start_bars.value(), n))
        self.slider.blockSignals(True)
        self.slider.setRange(2, n); self.slider.setValue(self.index); self.slider.setEnabled(True)
        self.slider.blockSignals(False)
        self._set_controls_enabled(True)
        self._plot()

    def set_data(self, symbol, df):
        """Test/programmatic hook: use a supplied DataFrame instead of fetching."""
        self.symbol_text = symbol.upper()
        self.data = df
        n = len(df)
        self.index = max(2, min(self.start_bars.value(), n))
        self.slider.blockSignals(True)
        self.slider.setRange(2, n); self.slider.setValue(self.index); self.slider.setEnabled(True)
        self.slider.blockSignals(False)
        self._set_controls_enabled(True)
        self._plot()

    # --- transport --------------------------------------------------------
    def reset(self):
        self.pause()
        self.index = max(2, min(self.start_bars.value(), self._len()))
        self._plot()

    def step(self, delta):
        if self.data is None:
            return
        self.index = max(2, min(self._len(), self.index + int(delta)))
        self._plot()
        if self.index >= self._len():
            self.pause()

    def to_end(self):
        self.pause()
        self.index = self._len()
        self._plot()

    def toggle_play(self):
        if self._timer.isActive():
            self.pause()
        else:
            self.play()

    def play(self):
        if self.data is None or self.index >= self._len():
            return
        self._timer.start(self._SPEEDS[self.speed.currentText()])
        self.play_btn.setText("⏸ Pause")

    def pause(self):
        self._timer.stop()
        self.play_btn.setText("▶ Play")

    def _advance(self):
        if self.index >= self._len():
            self.pause(); return
        self.step(1)

    def _on_speed_changed(self, _label):
        if self._timer.isActive():
            self._timer.start(self._SPEEDS[self.speed.currentText()])

    def _on_slider(self, value):
        if self.data is None:
            return
        self.pause()
        self.index = int(value)
        self._plot()

    # --- helpers ----------------------------------------------------------
    def _len(self):
        return len(self.data) if self.data is not None else 0

    def _set_controls_enabled(self, on):
        for w in (self.reset_btn, self.back_btn, self.play_btn, self.fwd_btn, self.end_btn, self.speed):
            w.setEnabled(on)

    def _plot(self):
        if self.data is None or self.data.empty:
            return
        view = self.data.iloc[:self.index]
        self.chart.plot(self.symbol_text, view, self.cfg)
        self.slider.blockSignals(True); self.slider.setValue(self.index); self.slider.blockSignals(False)
        try:
            last_date = str(view.index[-1])[:10]
        except Exception:
            last_date = "?"
        at_end = " (end)" if self.index >= self._len() else ""
        self.status.setText(f"{self.symbol_text}  ·  bar {self.index}/{self._len()}  ·  {last_date}{at_end}")

    def shutdown(self):
        self.pause()


class CoachPanel(QWidget):
    def __init__(self):
        super().__init__(); layout=QVBoxLayout(self)
        row=QHBoxLayout(); self.symbol=QLineEdit("AAPL"); self.period=QComboBox(); self.period.addItems(["6mo","1y","2y"]); self.period.setCurrentText("1y"); run=QPushButton("Analyze setup"); run.clicked.connect(self.analyze)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.symbol); row.addWidget(QLabel("Period")); row.addWidget(self.period); row.addWidget(run); layout.addLayout(row)
        self.text=QTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text)
    def analyze(self):
        sym=self.symbol.text().strip().upper(); cfg=ScannerConfig(); cfg.period=self.period.currentText(); cfg.interval="1d"; df=get_history(sym,cfg.period,cfg.interval); info=explain_symbol(sym,df,cfg)
        lines=[f"{sym} Trade Coach", "", f"Score: {info['score']}/100", f"Summary: {info['summary']}", "", "Score breakdown:"]
        for k,v in info.get('parts',{}).items(): lines.append(f"- {k}: {v}")
        lines += ["", "Coach note:", "This is a rules-based assistant. Confirm support/resistance, earnings date, sector strength and market regime before any real trade."]
        self.text.setText("\n".join(lines))


class _AIWorker(QThread):
    """Runs a blocking LLM call off the UI thread so the window never freezes
    while waiting on the network."""
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, messages, api_key, model, context):
        super().__init__()
        self._messages = messages
        self._api_key = api_key
        self._model = model
        self._context = context

    def run(self):
        from tradelab.core import ai_assistant
        try:
            reply = ai_assistant.ask(self._messages, self._api_key,
                                     model=self._model, context=self._context)
            self.done.emit(reply)
        except Exception as e:
            self.failed.emit(str(e))


class AIAssistantPanel(QWidget):
    """Phase 7 (option b): LLM-backed AI assistant. Chat-style panel that
    explains scans/charts/setups in plain language using the user's own
    Anthropic API key. Falls back to the offline Trade Coach with no key."""

    def __init__(self):
        super().__init__()
        self._settings = QSettings("TradeLabPro", "TradeLabPro")
        self._history = []          # [{"role","content"}] chat turns for the API
        self._context = None        # optional symbol indicator snapshot
        self._worker = None
        layout = QVBoxLayout(self)

        layout.addWidget(_hint(
            "Natural-language assistant. It explains indicators, scores and setups "
            "in plain English. Educational only - NOT financial advice. Uses your own "
            "Anthropic API key (per-use cost billed to you); with no key it falls back "
            "to the offline rules-based Trade Coach."))

        # Persistent data-scope disclaimer: the assistant reasons only over the
        # indicator snapshot this app computes plus the model's training
        # knowledge - it has no live market feed, prices, or news.
        disclaimer = QLabel(
            "⚠ No live market data. Answers are based on the indicators "
            "TradeLabPro computes for the loaded symbol plus the model's general "
            "knowledge (not real-time). It cannot give current prices, today's "
            "news, or earnings dates. Educational only — not financial advice.")
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet("color:#c9a227; font-size:11px;")
        layout.addWidget(disclaimer)

        # --- API key + model config ---
        from tradelab.core import ai_assistant
        cfg_row = QHBoxLayout()
        self.key_edit = QLineEdit(); self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Anthropic API key (sk-ant-...) - stored locally on this machine")
        saved_key = self._settings.value("AIAssistant/api_key", "", type=str)
        if saved_key:
            self.key_edit.setText(saved_key)
        self.model_combo = QComboBox(); self.model_combo.addItems(ai_assistant.MODELS)
        self.model_combo.setCurrentText(self._settings.value("AIAssistant/model", ai_assistant.DEFAULT_MODEL, type=str))
        save_btn = QPushButton("Save"); save_btn.clicked.connect(self._save_config)
        cfg_row.addWidget(QLabel("API key")); cfg_row.addWidget(self.key_edit, 1)
        cfg_row.addWidget(QLabel("Model")); cfg_row.addWidget(self.model_combo)
        cfg_row.addWidget(save_btn)
        layout.addLayout(cfg_row)
        self.status = QLabel(); self.status.setStyleSheet("color:#8a9099;")
        layout.addWidget(self.status)

        # --- symbol context loader ---
        ctx_row = QHBoxLayout()
        self.symbol = QLineEdit("AAPL"); self.symbol.setMaximumWidth(120)
        self.period = QComboBox(); self.period.addItems(["6mo", "1y", "2y"]); self.period.setCurrentText("1y")
        load_btn = QPushButton("Load symbol context"); load_btn.clicked.connect(self._load_context)
        ctx_row.addWidget(QLabel("Symbol")); ctx_row.addWidget(self.symbol)
        ctx_row.addWidget(QLabel("Period")); ctx_row.addWidget(self.period)
        ctx_row.addWidget(load_btn); ctx_row.addStretch()
        layout.addLayout(ctx_row)

        # --- conversation ---
        self.log = QTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log, 1)
        ask_row = QHBoxLayout()
        self.prompt = QLineEdit(); self.prompt.setPlaceholderText("Ask about a symbol, indicator or setup...")
        self.prompt.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send"); self.send_btn.clicked.connect(self._send)
        clear_btn = QPushButton("Clear"); clear_btn.clicked.connect(self._clear)
        ask_row.addWidget(self.prompt, 1); ask_row.addWidget(self.send_btn); ask_row.addWidget(clear_btn)
        layout.addLayout(ask_row)

        self._refresh_status()

    # -- config --
    def _current_key(self):
        from tradelab.core import ai_assistant
        return self.key_edit.text().strip() or ai_assistant.api_key_from_env()

    def _save_config(self):
        self._settings.setValue("AIAssistant/api_key", self.key_edit.text().strip())
        self._settings.setValue("AIAssistant/model", self.model_combo.currentText())
        self._refresh_status()
        self.status.setText(self.status.text() + "  (saved)")

    def _refresh_status(self):
        from tradelab.core import ai_assistant
        if ai_assistant.is_configured(self._current_key()):
            src = "settings" if self.key_edit.text().strip() else "ANTHROPIC_API_KEY"
            self.status.setText(f"AI mode: on ({self.model_combo.currentText()}, key from {src}).")
        else:
            self.status.setText("AI mode: off (no key) - answers use the offline Trade Coach.")

    # -- context --
    def _load_context(self):
        from tradelab.core import ai_assistant
        sym = self.symbol.text().strip().upper()
        if not sym:
            return
        cfg = ScannerConfig(); cfg.period = self.period.currentText(); cfg.interval = "1d"
        try:
            df = get_history(sym, cfg.period, cfg.interval)
            self._context = ai_assistant.build_symbol_context(sym, df, cfg)
            self._append("System", f"Loaded context for {sym}. Ask a question about it below.")
        except Exception as e:
            self._append("System", f"Could not load {sym}: {e}")

    # -- chat --
    def _append(self, who, text):
        self.log.append(f"<b>{who}:</b> {text.replace(chr(10), '<br>')}<br>")

    def _clear(self):
        self._history = []
        self.log.clear()

    def _send(self):
        q = self.prompt.text().strip()
        if not q:
            return
        self.prompt.clear()
        self._append("You", q)
        from tradelab.core import ai_assistant
        key = self._current_key()
        if not ai_assistant.is_configured(key):
            # Offline fallback: rules-based coach for the loaded symbol.
            sym = self.symbol.text().strip().upper()
            cfg = ScannerConfig(); cfg.period = self.period.currentText(); cfg.interval = "1d"
            try:
                df = get_history(sym, cfg.period, cfg.interval)
                self._append("Coach", ai_assistant.offline_answer(sym, df, cfg))
            except Exception as e:
                self._append("Coach", f"Offline coach could not load {sym}: {e}")
            return
        self._history.append({"role": "user", "content": q})
        self.send_btn.setEnabled(False); self.prompt.setEnabled(False)
        self.status.setText("Thinking...")
        self._worker = _AIWorker(list(self._history), key,
                                 self.model_combo.currentText(), self._context)
        self._worker.done.connect(self._on_reply)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_reply(self, reply):
        self._history.append({"role": "assistant", "content": reply})
        self._append("AI", reply)
        self.send_btn.setEnabled(True); self.prompt.setEnabled(True)
        self._refresh_status()

    def _on_error(self, msg):
        # Drop the failed user turn so history stays valid for the next try.
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()
        self._append("System", f"AI error: {msg}")
        self.send_btn.setEnabled(True); self.prompt.setEnabled(True)
        self._refresh_status()


class PaperTradingPanel(QWidget):
    """Phase 8: paper-trading desk. A fully simulated account (local ledger,
    no real money, no live order routing) with order entry, positions, and
    live P&L. Backed by tradelab.core.broker.PaperBroker."""

    def __init__(self):
        super().__init__()
        from tradelab.core.broker import PaperBroker, BUY, SELL, MARKET, LIMIT
        self._BUY, self._SELL = BUY, SELL
        self._MARKET, self._LIMIT = MARKET, LIMIT
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
        self.o_symbol = QLineEdit("AAPL"); self.o_symbol.setMaximumWidth(90)
        self.o_side = QComboBox(); self.o_side.addItems([BUY, SELL])
        self.o_qty = QSpinBox(); self.o_qty.setRange(1, 1_000_000); self.o_qty.setValue(10)
        self.o_type = QComboBox(); self.o_type.addItems([MARKET, LIMIT])
        self.o_limit = QDoubleSpinBox(); self.o_limit.setRange(0.0, 1_000_000.0)
        self.o_limit.setDecimals(2); self.o_limit.setMaximumWidth(100); self.o_limit.setEnabled(False)
        self.o_type.currentTextChanged.connect(
            lambda t: self.o_limit.setEnabled(t == self._LIMIT))
        place = QPushButton("Place paper order"); place.clicked.connect(self._place)
        for w in (QLabel("Symbol"), self.o_symbol, QLabel("Side"), self.o_side,
                  QLabel("Qty"), self.o_qty, QLabel("Type"), self.o_type,
                  QLabel("Limit"), self.o_limit, place):
            entry.addWidget(w)
        entry.addStretch()
        layout.addLayout(entry)

        # --- actions ---
        actions = QHBoxLayout()
        refresh = QPushButton("Refresh (mark-to-market + fill limits)")
        refresh.clicked.connect(self.refresh)
        reset = QPushButton("Reset account"); reset.clicked.connect(self._reset)
        actions.addWidget(refresh); actions.addWidget(reset); actions.addStretch()
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
        self.ord_table = QTableWidget(0, 8)
        self.ord_table.setHorizontalHeaderLabels(
            ["ID", "Symbol", "Side", "Qty", "Type", "Limit", "Status", "Fill price"])
        self.ord_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.ord_table)

        self.refresh()

    def _place(self):
        from tradelab.core.broker import BrokerError
        sym = self.o_symbol.text().strip().upper()
        limit = self.o_limit.value() if self.o_type.currentText() == self._LIMIT else None
        try:
            order = self.broker.place_order(sym, self.o_side.currentText(),
                                            self.o_qty.value(), self.o_type.currentText(),
                                            limit_price=limit)
        except BrokerError as e:
            QMessageBox.warning(self, "Order rejected", str(e)); return
        if order.status == "REJECTED":
            QMessageBox.warning(self, "Order rejected", order.note or "Could not fill.")
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
                     f"{o.limit_price:.2f}" if o.limit_price else "-", o.status,
                     f"{o.filled_price:.2f}" if o.filled_price else "-"]
            for c, val in enumerate(cells):
                self.ord_table.setItem(r, c, QTableWidgetItem(val))


class PluginPanel(QWidget):
    """Phase 6 Plugin SDK panel: shows discovered indicator plugins (loaded
    OK or errored) and a Reload button. Loaded plugins become fields in the
    Scanner filters and Strategy Builder automatically."""
    def __init__(self, on_plugins_changed=None):
        super().__init__()
        self._on_plugins_changed = on_plugins_changed
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("Drop a .py file in the plugins/ folder that defines PLUGIN_NAME and compute(df) -> Series. It becomes usable as a field in Custom Filters and the Strategy Builder. See plugins/sample_hl_range.py for a template."))
        row = QHBoxLayout()
        reload_btn = QPushButton("Reload plugins"); reload_btn.clicked.connect(self.refresh)
        row.addWidget(reload_btn); row.addStretch()
        layout.addLayout(row)
        self.text = QTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text)
        self.refresh()

    def refresh(self):
        from tradelab.core import plugins
        result = plugins.discover_plugins()
        lines = [f"Plugins folder:  {plugins.PLUGINS_DIR}", ""]
        if result["loaded"]:
            lines.append("Loaded plugins (usable as indicator fields):")
            lines += [f"  ✓ {name}" for name in result["loaded"]]
        else:
            lines.append("No plugins loaded yet.")
        if result["errors"]:
            lines += ["", "Could not load (fix and Reload):"]
            lines += [f"  ✗ {f}: {msg}" for f, msg in result["errors"].items()]
        self.text.setText("\n".join(lines))
        if self._on_plugins_changed:
            self._on_plugins_changed()

def _scale_doc_images(doc, target_width, native_size_fn):
    """Set every image fragment in a QTextDocument to `target_width` wide,
    preserving aspect via native_size_fn(name) -> (native_w, native_h).
    Positions are collected first so editing doesn't invalidate the walk.
    Shared by the on-screen viewer and the PDF export."""
    positions = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                positions.append(frag.position())
            it += 1
        block = block.next()
    for pos in positions:
        cur = QTextCursor(doc)
        cur.setPosition(pos)
        cur.setPosition(pos + 1, QTextCursor.KeepAnchor)
        fmt = cur.charFormat()
        if not fmt.isImageFormat():
            continue
        imgfmt = fmt.toImageFormat()
        nw, nh = native_size_fn(imgfmt.name())
        if nw > 0 and nh > 0:
            imgfmt.setWidth(target_width)
            imgfmt.setHeight(target_width * nh / nw)
            cur.setCharFormat(imgfmt)


def _recolor_doc_links(doc, color="#000000"):
    """Render every link in a QTextDocument in `color` (default black) instead
    of Qt's default light-blue hyperlink colour. Shared by the on-screen viewer
    and the PDF export so both match."""
    positions = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isAnchor():
                positions.append((frag.position(), frag.length()))
            it += 1
        block = block.next()
    for pos, length in positions:
        cur = QTextCursor(doc)
        cur.setPosition(pos)
        cur.setPosition(pos + length, QTextCursor.KeepAnchor)
        fmt = cur.charFormat()
        fmt.setForeground(QColor(color))
        cur.setCharFormat(fmt)


class HeatmapView(QGraphicsView):
    """Scene view for the market map. Emits `picked` with a symbol when a tile
    is clicked and `resized` so the panel can re-lay out the treemap to the
    new size."""
    picked = Signal(str)
    resized = Signal()
    context_requested = Signal(str, object)   # symbol, global position
    zoom_requested = Signal(float, object)    # factor, view position (anchor)
    fit_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        # Scrollbars appear only when zoomed in (so you can pan the magnified map).
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor("#0b0e14"))
        self.setMinimumHeight(320)
        self._left_down = False
        self._dragging = False
        self._pan_last = None
        self._press_pos = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def _symbol_at(self, pos):
        item = self.itemAt(pos)
        while item is not None:
            sym = item.data(0)
            if sym:
                return str(sym)
            item = item.parentItem()
        return None

    # --- zoom (handled by the panel, which re-lays the map out bigger so the
    #     TILES grow but the label text stays a normal, readable size) --------
    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        try:
            pos = event.position().toPoint()
        except AttributeError:
            pos = event.pos()
        self.zoom_requested.emit(factor, pos)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # Double-click empty space (no tile) to fit the whole map again.
        if self._symbol_at(event.pos()) is None:
            self.fit_requested.emit()
        super().mouseDoubleClickEvent(event)

    # --- click / drag-to-pan ---------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._left_down = True
            self._dragging = False
            self._pan_last = event.pos()
            self._press_pos = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._left_down:
            delta = event.pos() - self._pan_last
            if not self._dragging and (abs(delta.x()) + abs(delta.y())) > 3:
                self._dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
                self._pan_last = event.pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._left_down:
            self._left_down = False
            self.setCursor(Qt.ArrowCursor)
            if not self._dragging:                     # a click, not a pan -> chart it
                sym = self._symbol_at(self._press_pos)
                if sym:
                    self.picked.emit(sym)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        sym = self._symbol_at(event.pos())
        if sym:
            self.context_requested.emit(sym, event.globalPos())


class HeatmapWorker(QThread):
    """Fetches heatmap quotes off the UI thread and builds the tiles."""
    progress = Signal(int, int, str)
    done = Signal(object)  # list[HeatmapTile]

    def __init__(self, symbols, size_by, period=hm.DEFAULT_PERIOD, quote_provider=None):
        super().__init__()
        self.symbols = symbols
        self.size_by = size_by
        self.period = period
        self._provider = quote_provider or hm.default_quote_provider

    def run(self):
        try:
            def prog(i, t, s):
                try:
                    self.progress.emit(int(i), int(t), str(s))
                except RuntimeError:
                    pass
            quotes = self._provider(self.symbols, period=self.period, progress=prog)
            tiles = hm.build_tiles(quotes, self.size_by)
        except BaseException:
            tiles = []
        try:
            self.done.emit(tiles)
        except RuntimeError:
            pass


class HeatmapPanel(QWidget):
    """Finviz-style market map: tiles sized by market cap (or dollar volume),
    coloured green->red by the day's % change, grouped into sector blocks.
    Click a tile to load its chart. US and Canadian presets built in."""

    _MARKETS = {
        "US - Mega/Large caps": sorted(set(US_NASDAQ + US_NYSE)),
        "US - NASDAQ large caps": list(US_NASDAQ),
        "US - NYSE large caps": list(US_NYSE),
        "Canada - TSX large caps": list(CAN_TSX),
        "Canada - TSX (expanded)": list(CAN_TSX_EXPANDED),
        # ETF / index maps. Funds have no market cap or sector; get_quote_meta
        # falls back to AUM (totalAssets) for size and fund `category` for the
        # group label, so these map cleanly too.
        "US - Sector ETFs (SPDR)": ["XLF", "XLK", "XLE", "XLY", "XLV", "XLI",
                                     "XLP", "XLU", "XLB", "XLRE", "XLC"],
        "US - Index & asset ETFs": ["SPY", "QQQ", "DIA", "IWM", "GLD", "SLV",
                                    "TLT", "HYG", "LQD", "ARKK"],
        "US - ETFs (all)": list(US_AMEX),
        "Canada - ETFs": ["XIU.TO", "XIC.TO", "XEI.TO", "XRE.TO", "XFN.TO",
                          "XEG.TO", "XIT.TO", "XSP.TO", "XQQ.TO", "ZSP.TO",
                          "ZCN.TO", "ZEB.TO", "VDY.TO", "VCN.TO", "VFV.TO"],
        # World map: major global companies (mostly US-listed ADRs so the data
        # resolves). Group by Country for the Finviz-style world view.
        "World - Large caps": [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM",
            "BABA", "PDD", "JD", "NIO", "BIDU", "TCEHY", "LI",
            "TSM", "TM", "SONY", "MUFG", "HMC",
            "AZN", "HSBC", "SHEL", "UL", "RIO", "BTI", "BP",
            "NVS", "NSRGY", "UBS", "LVMUY", "TTE", "SNY",
            "SAP", "DB", "ASML", "PHG",
            "INFY", "WIT", "HDB", "IBN",
            "VALE", "PBR", "ITUB", "NU",
            "SHOP.TO", "RY.TO", "TD.TO", "ENB.TO", "CNQ.TO",
            "BHP", "NVO", "MELI", "SAN", "TEF"],
    }

    def __init__(self, db: Database, chart: ChartWidget, cfg: ScannerConfig, quote_provider=None):
        super().__init__()
        self.db = db
        self.chart = chart
        self.cfg = cfg
        self._quote_provider = quote_provider
        self._tiles = []
        self._worker = None
        self._EXTERNAL_LABEL = "Scanner results"
        self._external_symbols = []
        self._zoom = 1.0
        self._MAX_ZOOM = 12.0

        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "A market map at a glance. Each tile is a stock/ETF, sized by market cap "
            "and coloured by its % change over the selected Period (green up, red down), "
            "grouped by Sector, Industry or Country. Map a preset, a Theme basket, the "
            "World, your Watchlist or Portfolio. Click a tile to chart it, right-click for "
            "more. Scroll to zoom in on small tiles, drag to pan, double-click to fit."))

        self._NO_THEME = "(no theme)"
        self._GROUP_ATTR = {"Sector": "sector", "Industry": "industry",
                            "Country": "country", "None": None}

        controls = QHBoxLayout()
        self.market = QComboBox(); self.market.addItems(list(self._MARKETS.keys()) + ["Watchlist", "Portfolio"])
        self.theme_sel = QComboBox(); self.theme_sel.addItems([self._NO_THEME] + hm.theme_choices())
        self.theme_sel.setToolTip("Map a thematic basket (AI, Semiconductors, EV, …). Overrides Market while set.")
        self.period_sel = QComboBox(); self.period_sel.addItems(hm.period_choices())
        self.period_sel.setToolTip("Performance window the tile colour represents (like Finviz): 1 Day, 1 Week … 10 Year, YTD.")
        self.size_by = QComboBox(); self.size_by.addItems(["Market cap", "Dollar volume"])
        self.size_by.setToolTip("Tile area = market cap (classic) or today's traded dollar volume (faster, no cap lookup).")
        self.group_by = QComboBox(); self.group_by.addItems(["Sector", "Industry", "Country", "None"])
        self.group_by.setToolTip("Group tiles into blocks by Sector, Industry, or Country (Country suits the World map).")
        self.group_by.currentTextChanged.connect(self.render_heatmap)
        self.max_tiles = QSpinBox(); self.max_tiles.setRange(10, 500); self.max_tiles.setValue(100)
        self.max_tiles.setToolTip("Cap the number of tiles (largest first) so the map stays fast and readable.")
        self.load_btn = QPushButton("Load map"); self.load_btn.clicked.connect(self.load)
        self.auto_chk = QCheckBox("Auto-refresh every")
        self.auto_chk.setToolTip("Reload the map on a timer so it tracks the market during the day.")
        self.auto_secs = QSpinBox(); self.auto_secs.setRange(15, 3600); self.auto_secs.setValue(60); self.auto_secs.setSuffix(" s")
        self.auto_chk.toggled.connect(self._on_auto_toggled)
        self.auto_secs.valueChanged.connect(self._on_auto_interval_changed)
        controls.addWidget(QLabel("Market")); controls.addWidget(self.market, 1)
        controls.addWidget(QLabel("Theme")); controls.addWidget(self.theme_sel)
        controls.addWidget(QLabel("Period")); controls.addWidget(self.period_sel)
        controls.addWidget(QLabel("Size by")); controls.addWidget(self.size_by)
        controls.addWidget(QLabel("Group")); controls.addWidget(self.group_by)
        controls.addWidget(QLabel("Max")); controls.addWidget(self.max_tiles)
        controls.addWidget(self.load_btn)
        controls.addWidget(self.auto_chk); controls.addWidget(self.auto_secs)
        layout.addLayout(controls)
        # Changing period/theme/market re-fetches, but only once a map has been
        # loaded (avoids a fetch during construction / before the first Load).
        self.period_sel.currentTextChanged.connect(self._on_period_changed)
        self.theme_sel.currentTextChanged.connect(self._on_theme_changed)
        self.market.currentTextChanged.connect(self._on_market_changed)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)

        self.progress = QProgressBar(); self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.view = HeatmapView()
        self.view.picked.connect(self._on_pick)
        self.view.resized.connect(self.render_heatmap)
        self.view.context_requested.connect(self._on_tile_menu)
        self.view.zoom_requested.connect(self._zoom_at)
        self.view.fit_requested.connect(self._fit_zoom)
        layout.addWidget(self.view, 1)

        legend = QHBoxLayout()
        self.legend_title = QLabel("1 Day change:")
        legend.addWidget(self.legend_title)
        for pct, text in [(-3, "-3%+"), (-1.5, "-1.5%"), (0, "0"), (1.5, "+1.5%"), (3, "+3%+")]:
            swatch = QLabel(f" {text} ")
            swatch.setStyleSheet(
                f"background:{hm.color_for_change(pct)}; color:#fff; padding:1px 6px; border-radius:2px;")
            legend.addWidget(swatch)
        legend.addStretch()
        layout.addLayout(legend)

        self.status = QLabel("Pick a market and click Load map.")
        layout.addWidget(self.status)

    # --- data -------------------------------------------------------------
    def _symbols_for_market(self):
        theme = self.theme_sel.currentText()
        if theme != self._NO_THEME:                 # a theme overrides the market
            return list(hm.THEMES.get(theme, []))
        name = self.market.currentText()
        if name == self._EXTERNAL_LABEL:            # symbols pushed in from the Scanner
            return list(self._external_symbols)
        if name == "Watchlist":
            return list(self.db.watch_symbols())
        if name == "Portfolio":
            seen, out = set(), []
            for pos in self.db.positions():
                sym = str(pos.get("symbol", "")).upper().strip()
                if sym and sym not in seen:
                    seen.add(sym); out.append(sym)
            return out
        return list(self._MARKETS.get(name, []))

    def set_external_symbols(self, symbols, label=None):
        """Map an ad-hoc symbol list (e.g. Scanner results). Adds/selects a
        source entry in the Market dropdown and loads it."""
        label = label or self._EXTERNAL_LABEL
        self._EXTERNAL_LABEL = label
        self._external_symbols = [str(s).upper() for s in symbols if str(s).strip()]
        if self.market.findText(label) < 0:
            self.market.blockSignals(True); self.market.addItem(label); self.market.blockSignals(False)
        # Clear any theme (it would override the market) and select this source.
        self.theme_sel.blockSignals(True); self.theme_sel.setCurrentText(self._NO_THEME); self.theme_sel.blockSignals(False)
        self.market.blockSignals(True); self.market.setCurrentText(label); self.market.blockSignals(False)
        self.load()

    def _on_tile_menu(self, symbol, global_pos):
        menu = QMenu(self)
        act_chart = menu.addAction(f"Open chart — {symbol}")
        act_watch = menu.addAction("Add to watchlist")
        chosen = menu.exec(global_pos)
        if chosen == act_chart:
            self._on_pick(symbol)
        elif chosen == act_watch:
            try:
                self.db.add_watch_symbol(symbol)
                self.status.setText(f"Added {symbol} to watchlist.")
            except Exception as exc:
                self.status.setText(f"Could not add {symbol}: {exc}")

    def _on_period_changed(self, _period):
        self.legend_title.setText(f"{self.period_sel.currentText()} change:")
        if self._tiles:   # already loaded once -> refresh with the new window
            self.load()

    def _on_theme_changed(self, _theme):
        if self._tiles:
            self.load()

    def _on_market_changed(self, name):
        # Picking a market clears any active theme so the market takes effect,
        # and the World map defaults to grouping by Country (Finviz-style).
        if self.theme_sel.currentText() != self._NO_THEME:
            self.theme_sel.blockSignals(True)
            self.theme_sel.setCurrentText(self._NO_THEME)
            self.theme_sel.blockSignals(False)
        if name.startswith("World"):
            self.group_by.blockSignals(True)
            self.group_by.setCurrentText("Country")
            self.group_by.blockSignals(False)
        if self._tiles:
            self.load()

    def load(self):
        if self._worker is not None and self._worker.isRunning():
            return
        symbols = self._symbols_for_market()[: self.max_tiles.value()]
        if not symbols:
            src = self.market.currentText().lower()
            self.status.setText(f"No symbols for {src} (add some in that tab first).")
            return
        size_by = "dollar_volume" if self.size_by.currentText() == "Dollar volume" else "market_cap"
        period = self.period_sel.currentText()
        self.legend_title.setText(f"{period} change:")
        self._zoom = 1.0            # a fresh map starts fitted, not zoomed
        self.load_btn.setEnabled(False)
        self.progress.setVisible(True); self.progress.setRange(0, len(symbols)); self.progress.setValue(0)
        self.status.setText(f"Loading {len(symbols)} symbols ({period})…")
        self._worker = HeatmapWorker(symbols, size_by, period, self._quote_provider)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    def _clear_worker(self):
        self._worker = None

    # --- auto-refresh -----------------------------------------------------
    def _on_auto_toggled(self, on):
        if on:
            self._timer.start(self.auto_secs.value() * 1000)
            self.load()  # refresh immediately so the timer's effect is visible
        else:
            self._timer.stop()

    def _on_auto_interval_changed(self, secs):
        if self._timer.isActive():
            self._timer.start(secs * 1000)

    def _auto_refresh(self):
        # load() no-ops if a fetch is still in flight, so a slow refresh never
        # stacks up behind the next tick.
        self.load()

    def _on_progress(self, i, total, sym):
        self.progress.setValue(i)
        self.status.setText(f"Loading {i}/{total}: {sym}")

    def _on_done(self, tiles):
        self._tiles = tiles
        self.progress.setVisible(False)
        self.load_btn.setEnabled(True)
        if not tiles:
            self.status.setText("No data returned for this market.")
            self.view.scene().clear()
            return
        gainers = sum(1 for t in tiles if t.change_pct > 0)
        stamp = time.strftime("%H:%M:%S")
        suffix = " · auto-refresh on" if self._timer.isActive() else ""
        self.status.setText(
            f"{len(tiles)} stocks — {gainers} up / {len(tiles) - gainers} down "
            f"(updated {stamp}{suffix}). Click a tile to chart it.")
        self.render_heatmap()

    # --- zoom -------------------------------------------------------------
    def _zoom_at(self, factor, view_pos):
        """Re-lay the map out `factor`× bigger/smaller, keeping the point under
        the cursor fixed. Tiles grow; label text stays a normal size and
        previously-hidden tickers appear once their tile is big enough."""
        old = self._zoom
        new = max(1.0, min(self._MAX_ZOOM, old * factor))
        if abs(new - old) < 1e-6:
            return
        before = self.view.mapToScene(view_pos)      # scene point under cursor now
        self._zoom = new
        self.render_heatmap()
        ratio = new / old
        # The same content point is now at before*ratio; scroll so it sits back
        # under the cursor.
        self.view.horizontalScrollBar().setValue(int(before.x() * ratio - view_pos.x()))
        self.view.verticalScrollBar().setValue(int(before.y() * ratio - view_pos.y()))

    def _fit_zoom(self):
        if self._zoom != 1.0:
            self._zoom = 1.0
            self.render_heatmap()

    # --- drawing ----------------------------------------------------------
    @staticmethod
    def _fit_pt(text, w, h, max_pt=11.0, min_pt=5.0):
        """Largest point size at which `text` fits a w×h tile (0 = too small to
        label). Lets tickers show on much smaller tiles than a fixed size would."""
        if not text or w < 13 or h < 9:
            return 0.0
        pt_w = (w - 3) / (len(text) * 0.66)     # ~0.66·pt per character
        pt_h = (h - 2) / 1.4                     # ~1.4·pt per line
        pt = min(max_pt, pt_w, pt_h)
        return pt if pt >= min_pt else 0.0

    def render_heatmap(self):
        scene = self.view.scene()
        scene.clear()
        vw = max(50, self.view.viewport().width() - 2)
        vh = max(50, self.view.viewport().height() - 2)
        # Zoom enlarges the SCENE (so tiles grow and more of them get a label at
        # a normal text size), and scrollbars pan it - the label text itself is
        # never scaled up.
        sw, sh = vw * self._zoom, vh * self._zoom
        scene.setSceneRect(0, 0, sw, sh)
        if not self._tiles:
            return
        group_attr = self._GROUP_ATTR.get(self.group_by.currentText(), "sector")
        cells = hm.layout_heatmap(self._tiles, sw, sh, header=16.0, group_by=group_attr)
        border = QColor("#0b0e14")
        for cell in cells:
            if cell.is_header:
                band = QGraphicsRectItem(cell.x, cell.y, cell.w, cell.h)
                band.setBrush(QColor("#0f1420")); band.setPen(QPen(border))
                scene.addItem(band)
                if cell.w > 44:
                    lbl = QGraphicsSimpleTextItem(cell.sector)
                    f = QFont(); f.setPointSize(8); f.setBold(True); lbl.setFont(f)
                    lbl.setBrush(QColor("#c7d0dd"))
                    lbl.setPos(cell.x + 4, cell.y + max(0.0, (cell.h - 12) / 2))
                    scene.addItem(lbl)
                continue
            t = cell.tile
            rw, rh = max(0.0, cell.w - 1), max(0.0, cell.h - 1)
            rect = QGraphicsRectItem(cell.x, cell.y, rw, rh)
            rect.setBrush(QColor(hm.color_for_change(t.change_pct)))
            rect.setPen(QPen(border))
            rect.setData(0, t.symbol)
            # Clip any label to the tile so a ticker never bleeds into neighbours.
            rect.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
            rect.setToolTip(
                f"{t.symbol} — {t.name}\nSector: {t.sector}\nIndustry: {t.industry}\n"
                f"Country: {t.country}\nPrice: {t.price:,.2f}\n"
                f"Change: {t.change_pct:+.2f}%\nSize: {fmt_large(t.size)}")
            scene.addItem(rect)
            # Auto-size the ticker to the tile so even small tiles are labelled.
            pt = self._fit_pt(t.symbol, rw, rh)
            if pt:
                sym = QGraphicsSimpleTextItem(t.symbol, rect)   # child -> clipped
                f = QFont(); f.setBold(True); f.setPointSizeF(pt); sym.setFont(f)
                sym.setBrush(QColor("#ffffff")); sym.setData(0, t.symbol)
                sym.setPos(cell.x + 2, cell.y + 1)
                line_h = pt * 1.4
                if rh >= line_h * 2 + 2 and rw >= 30:      # room for a second line
                    ppt = max(5.0, pt * 0.85)
                    pct = QGraphicsSimpleTextItem(f"{t.change_pct:+.2f}%", rect)
                    pf = QFont(); pf.setPointSizeF(ppt); pct.setFont(pf)
                    pct.setBrush(QColor("#eef1f5")); pct.setData(0, t.symbol)
                    pct.setPos(cell.x + 2, cell.y + 1 + line_h)

    def _on_pick(self, symbol):
        try:
            self.chart.plot(symbol, get_history(symbol, self.cfg.period, self.cfg.interval), self.cfg)
            self.status.setText(f"Charted {symbol}.")
        except Exception as exc:
            self.status.setText(f"Could not chart {symbol}: {exc}")

    def shutdown(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)


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
        self.status = QLabel("Ready.")
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
            self.status.setText("Enter a symbol first.")
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


class RiskPanel(QWidget):
    """Position-sizing calculator + R-multiple targets + portfolio sector
    exposure. Pure planning math - it never places orders."""

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
        exp.addWidget(QLabel("Portfolio sector exposure")); exp.addStretch(); exp.addWidget(load_btn)
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


class IbkrFlexWorker(QThread):
    """Fetches an IBKR Flex Query report off the UI thread and returns the
    parsed fills. Read-only network call; no orders, no funds."""
    done = Signal(object, str)   # fills, error_message

    def __init__(self, token, query_id):
        super().__init__()
        self.token = token
        self.query_id = query_id

    def run(self):
        try:
            from tradelab.core.journal import (fetch_ibkr_flex, parse_ibkr_flex_xml,
                                               parse_ibkr_trades_csv, flex_trade_row_count,
                                               flex_missing_fields)
            text = fetch_ibkr_flex(self.token, self.query_id)
            fills = parse_ibkr_flex_xml(text) or parse_ibkr_trades_csv(text)
            error = ""
            if not fills:
                # Distinguish "the query returned nothing" from "we couldn't read
                # it", and keep the raw report so the cause is inspectable.
                rows = flex_trade_row_count(text)
                saved = ""
                try:
                    out = ROOT_DIR / "logs" / "ibkr_flex_last.xml"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(text, encoding="utf-8")
                    saved = " Raw report saved to logs/ibkr_flex_last.xml."
                except Exception:
                    pass
                if rows:
                    missing = flex_missing_fields(text)
                    if missing:
                        error = (f"Your Flex Query returned {rows} trades but is missing the "
                                 f"field(s): {', '.join(missing)}. In IBKR → Flex Queries → "
                                 f"edit your query → Trades section, tick those (Trade Price "
                                 f"is required), save, then Fetch again.")
                    else:
                        error = (f"The report contains {rows} trade row(s) but none could be "
                                 f"read.{saved}")
                else:
                    error = ("The report came back with no trades. Check that the Flex "
                             "Query includes the Trades section, that its date period "
                             "covers your trades, and that it's an Activity Flex Query "
                             "(not Trade Confirmation)." + saved)
        except BaseException as exc:
            fills, error = [], str(exc)
        try:
            self.done.emit(fills, error)
        except RuntimeError:
            pass


class JournalPanel(QWidget):
    """Trade journal: log trades with a stop/strategy/tags, then review what
    works - win rate, average R-multiple, expectancy, and P&L by strategy or
    tag. Round-trips can be imported from the paper-trading account. Analysis
    and practice only; nothing here places orders."""

    _COLS = ["Symbol", "Side", "Qty", "Entry", "Entry date", "Stop", "Exit", "Exit date",
             "P&L", "P&L %", "R", "Days", "Status", "Strategy", "Tags"]

    def __init__(self, chart: ChartWidget, cfg: ScannerConfig):
        super().__init__()
        self.chart = chart
        self.cfg = cfg
        self.journal = Journal()
        self._flex_worker = None
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Log your trades, tag them, and review what works: win rate, average "
            "R-multiple, expectancy, and P&L by strategy/tag. Set a Stop to get "
            "R-multiples. Import round-trips from Paper Trading. Practice tool only."))

        # --- log-a-trade form ---------------------------------------------
        form = QGroupBox("Log a trade")
        fl = QHBoxLayout(form)
        self.f_symbol = QLineEdit(); self.f_symbol.setPlaceholderText("Symbol"); self.f_symbol.setMaximumWidth(90)
        self.f_side = QComboBox(); self.f_side.addItems(["Long", "Short"])
        self.f_qty = QDoubleSpinBox(); self.f_qty.setRange(0, 1e9); self.f_qty.setValue(100); self.f_qty.setMaximumWidth(90)
        self.f_entry = QDoubleSpinBox(); self.f_entry.setRange(0, 1e9); self.f_entry.setDecimals(2); self.f_entry.setPrefix("$"); self.f_entry.setMaximumWidth(110)
        self.f_stop = QDoubleSpinBox(); self.f_stop.setRange(0, 1e9); self.f_stop.setDecimals(2); self.f_stop.setPrefix("$"); self.f_stop.setSpecialValueText("— none"); self.f_stop.setMaximumWidth(110)
        self.f_stop.setToolTip("Protective stop (0 = none). Needed for R-multiples.")
        self.f_strategy = QLineEdit(); self.f_strategy.setPlaceholderText("Strategy"); self.f_strategy.setMaximumWidth(120)
        self.f_tags = QLineEdit(); self.f_tags.setPlaceholderText("tags, comma-separated"); self.f_tags.setMaximumWidth(150)
        add_btn = QPushButton("Add"); add_btn.clicked.connect(self.add_trade)
        for label, w in [("Symbol", self.f_symbol), ("Side", self.f_side), ("Qty", self.f_qty),
                         ("Entry", self.f_entry), ("Stop", self.f_stop),
                         ("Strategy", self.f_strategy), ("Tags", self.f_tags)]:
            fl.addWidget(QLabel(label)); fl.addWidget(w)
        fl.addWidget(add_btn)
        fl.addStretch()
        layout.addWidget(form)

        # --- stats summary ------------------------------------------------
        self.stats_label = QLabel("No trades yet."); self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("font-weight:bold;")
        layout.addWidget(self.stats_label)

        # --- trades table -------------------------------------------------
        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._chart_row)
        # Click any header to sort (numeric columns sort by value, not text).
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setToolTip("Click a column header to sort; click again to reverse.")
        self._default_sort_col = self._COLS.index("Entry date")
        self.table.sortItems(self._default_sort_col, Qt.DescendingOrder)
        layout.addWidget(self.table, 1)

        controls = QHBoxLayout()
        close_btn = QPushButton("Close selected…"); close_btn.clicked.connect(self.close_selected)
        edit_note_btn = QPushButton("Edit note…"); edit_note_btn.clicked.connect(self.edit_note)
        del_btn = QPushButton("Delete"); del_btn.clicked.connect(self.delete_selected)
        import_btn = QPushButton("Import from Paper Trading"); import_btn.clicked.connect(self.import_paper)
        ibkr_btn = QPushButton("Import from IBKR (CSV)…"); ibkr_btn.clicked.connect(self.import_ibkr)
        ibkr_btn.setToolTip("Import an IBKR trades CSV — a Flex Query 'Trades' export or an Activity Statement.")
        flex_btn = QPushButton("Import from IBKR (Flex)…"); flex_btn.clicked.connect(self.import_ibkr_flex)
        flex_btn.setToolTip("Fetch your Flex Query report directly over IBKR's Flex Web Service (read-only).")
        export_btn = QPushButton("Export CSV"); export_btn.clicked.connect(self.export_csv)
        controls.addWidget(close_btn); controls.addWidget(edit_note_btn); controls.addWidget(del_btn)
        controls.addStretch()
        controls.addWidget(import_btn); controls.addWidget(ibkr_btn); controls.addWidget(flex_btn); controls.addWidget(export_btn)
        layout.addLayout(controls)

        # --- breakdown ----------------------------------------------------
        bd = QHBoxLayout()
        bd.addWidget(QLabel("Breakdown by"))
        self.group_by = QComboBox(); self.group_by.addItems(["Strategy", "Tag", "Symbol"])
        self.group_by.currentTextChanged.connect(self._refresh_breakdown)
        bd.addWidget(self.group_by); bd.addStretch()
        layout.addLayout(bd)
        self.breakdown = QTableWidget(0, 5)
        self.breakdown.setHorizontalHeaderLabels(["Group", "Trades", "Win %", "Total P&L", "Avg R"])
        self.breakdown.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.breakdown.setSortingEnabled(True)
        self.breakdown.horizontalHeader().setToolTip("Click a column header to sort.")
        self.breakdown.setMaximumHeight(180)
        layout.addWidget(self.breakdown)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.refresh()

    # --- helpers ----------------------------------------------------------
    def _selected_ids(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), 0)
            if item:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _chart_row(self, row, _col):
        item = self.table.item(row, 0)
        if not item:
            return
        entry = self.journal.get(item.data(Qt.UserRole))
        if entry:
            try:
                self.chart.plot(entry.symbol, get_history(entry.symbol, self.cfg.period, self.cfg.interval), self.cfg)
            except Exception as exc:
                self.status.setText(f"Could not chart {entry.symbol}: {exc}")

    # --- actions ----------------------------------------------------------
    def add_trade(self):
        symbol = self.f_symbol.text().strip().upper()
        if not symbol:
            self.status.setText("Enter a symbol first.")
            return
        stop = self.f_stop.value() or None
        entry = JournalEntry(
            symbol=symbol, side=self.f_side.currentText(), qty=self.f_qty.value(),
            entry_price=self.f_entry.value(), stop=stop,
            strategy=self.f_strategy.text().strip(),
            tags=self.f_tags.text().strip())
        self.journal.add(entry)
        self.f_symbol.clear(); self.f_tags.clear()
        self.status.setText(f"Logged {entry.side} {entry.symbol}.")
        self.refresh()

    def close_selected(self):
        ids = self._selected_ids()
        open_ids = [i for i in ids if self.journal.get(i) and self.journal.get(i).is_open]
        if not open_ids:
            self.status.setText("Select an open trade to close.")
            return
        price, ok = QInputDialog.getDouble(self, "Close trade", "Exit price:", 0.0, 0.0, 1e9, 2)
        if not ok:
            return
        for i in open_ids:
            self.journal.close_trade(i, price)
        self.status.setText(f"Closed {len(open_ids)} trade(s) @ {price:g}.")
        self.refresh()

    def edit_note(self):
        ids = self._selected_ids()
        if not ids:
            self.status.setText("Select a trade to annotate.")
            return
        entry = self.journal.get(ids[0])
        text, ok = QInputDialog.getMultiLineText(self, "Edit note", f"Note for {entry.symbol}:", entry.notes)
        if ok:
            entry.notes = text
            self.journal.save()
            self.status.setText("Note saved.")

    def delete_selected(self):
        for i in self._selected_ids():
            self.journal.remove(i)
        self.refresh()

    def import_paper(self):
        path = DATA_DIR / "paper_account.json"
        if not path.exists():
            self.status.setText("No paper-trading account found yet — place some paper trades first.")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            added = self.journal.import_fills(data.get("orders", []))
        except Exception as exc:
            self.status.setText(f"Import failed: {exc}")
            return
        self.status.setText(f"Imported {added} new trade(s) from Paper Trading."
                            if added else "No new trades to import.")
        self.refresh()

    def import_ibkr(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import IBKR trades CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            added = self.journal.import_ibkr_csv(path)
        except Exception as exc:
            self.status.setText(f"IBKR import failed: {exc}")
            return
        if added:
            self.status.setText(f"Imported {added} new trade(s) from IBKR.")
        else:
            self.status.setText("No new trades found in that IBKR CSV "
                                "(already imported, or not a recognized Flex/Activity export).")
        self.refresh()

    # Custom dialog result for "Save without fetching".
    _FLEX_SAVE = 2

    @staticmethod
    def _flex_settings():
        return QSettings("TradeLabPro", "TradeLabPro")

    def _save_flex_credentials(self, token, query, settings=None):
        """Persist the Flex token + query id. QSettings lives in the OS store
        (Windows registry under TradeLabPro), independent of the app folder, so
        credentials survive app updates/reinstalls. Injectable for testing."""
        settings = settings or self._flex_settings()
        settings.setValue("ibkr/flex_token", token)
        settings.setValue("ibkr/flex_query", query)

    def _start_flex_fetch(self, token, query):
        self.status.setText("Fetching your Flex report from IBKR…")
        self._flex_worker = IbkrFlexWorker(token, query)
        self._flex_worker.done.connect(self._on_flex_done)
        self._flex_worker.start()

    def import_ibkr_flex(self):
        """Direct pull via IBKR's Flex Web Service. The user supplies their own
        read-only Flex token + query id, kept locally (token masked) and reused
        next time. 'Save' stores them without fetching (handy when the token
        changes); 'Fetch & import' stores and pulls. The fetch runs off the UI
        thread. Read-only: no login, no orders, no funds."""
        if self._flex_worker is not None and self._flex_worker.isRunning():
            self.status.setText("An IBKR Flex fetch is already running…")
            return
        settings = self._flex_settings()
        dlg = QDialog(self)
        dlg.setWindowTitle("IBKR Flex Web Service — token & query id")
        form = QFormLayout(dlg)
        info = QLabel(
            "Your read-only Flex token + Query ID (stored on this PC, kept across "
            "app updates — you only enter them once, and update here if the token "
            "changes).\nIn IBKR Client Portal: Performance & Reports → Flex Queries "
            "→ create a Trades query, then enable the Flex Web Service for a token.")
        info.setWordWrap(True)
        form.addRow(info)
        token_edit = QLineEdit(str(settings.value("ibkr/flex_token", "") or ""))
        token_edit.setEchoMode(QLineEdit.Password)
        token_edit.setPlaceholderText("Flex Web Service token")
        show = QCheckBox("Show token")
        show.toggled.connect(lambda on: token_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        query_edit = QLineEdit(str(settings.value("ibkr/flex_query", "") or ""))
        query_edit.setPlaceholderText("Flex Query ID")
        form.addRow("Flex token", token_edit)
        form.addRow("", show)
        form.addRow("Query id", query_edit)
        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(dlg.reject)
        save_btn = QPushButton("Save"); save_btn.clicked.connect(lambda: dlg.done(self._FLEX_SAVE))
        ok_btn = QPushButton("Fetch && import"); ok_btn.clicked.connect(dlg.accept)
        buttons.addStretch(); buttons.addWidget(cancel_btn); buttons.addWidget(save_btn); buttons.addWidget(ok_btn)
        form.addRow(buttons)

        result = dlg.exec()
        if result == QDialog.Rejected:
            return
        token, query = token_edit.text().strip(), query_edit.text().strip()
        if not token or not query:
            self.status.setText("Flex token and query id are both required.")
            return
        self._save_flex_credentials(token, query, settings)
        if result == QDialog.Accepted:          # Fetch & import
            self._start_flex_fetch(token, query)
        else:                                   # Save only
            self.status.setText("IBKR Flex token & query id saved — kept for next time.")

    def _on_flex_done(self, fills, error):
        if error and not fills:
            self.status.setText(f"IBKR Flex import failed: {error}")
            return
        added = self.journal.import_fills(fills)
        self.status.setText(f"Imported {added} new trade(s) from IBKR Flex."
                            if added else "No new trades to import from IBKR Flex.")
        self.refresh()

    def shutdown(self):
        if self._flex_worker is not None and self._flex_worker.isRunning():
            self._flex_worker.wait(3000)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export journal", "trade_journal.csv", "CSV files (*.csv)")
        if not path:
            return
        rows = []
        for e in self.journal.all():
            rows.append({
                "Symbol": e.symbol, "Side": e.side, "Qty": e.qty, "Entry": e.entry_price,
                "Stop": e.stop, "Exit": e.exit_price, "PnL": e.pnl, "PnL%": e.pnl_pct,
                "R": e.r_multiple, "EntryDate": e.entry_date, "ExitDate": e.exit_date,
                "Strategy": e.strategy, "Tags": ",".join(e.tags), "Notes": e.notes,
            })
        pd.DataFrame(rows).to_csv(path, index=False)
        self.status.setText(f"Exported {len(rows)} trades.")

    # --- rendering --------------------------------------------------------
    @staticmethod
    def _num(value, money=False, pct=False, suffix=""):
        item = SortableTableWidgetItem("", sort_value=(value if value is not None else -1e18))
        if value is None:
            item.setText("—")
            return item
        if money:
            item.setText(f"{value:,.2f}")
        elif pct:
            item.setText(f"{value:+.2f}%")
        else:
            item.setText(f"{value:g}{suffix}")
        if money or pct:
            item.setForeground(QColor("#3fb950") if value > 0 else QColor("#f0553a") if value < 0 else QColor("#8b98a5"))
        return item

    def refresh(self):
        # Newest trades first - after importing a year of IBKR history the
        # recent ones are what you want to see.
        entries = sorted(self.journal.all(),
                         key=lambda e: (e.entry_date or "", e.created_at), reverse=True)
        # Repopulating with sorting live would shuffle rows mid-insert, so turn
        # it off and restore the user's chosen column/direction afterwards.
        header = self.table.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        if sort_col < 0 or sort_col >= len(self._COLS):
            sort_col, sort_order = self._default_sort_col, Qt.DescendingOrder
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            cells = [
                QTableWidgetItem(e.symbol),
                QTableWidgetItem(e.side),
                self._num(e.qty),
                self._num(e.entry_price, money=True),
                QTableWidgetItem(e.entry_date or "—"),
                self._num(e.stop, money=True),
                self._num(e.exit_price, money=True),
                QTableWidgetItem(e.exit_date or "—"),
                self._num(e.pnl, money=True),
                self._num(e.pnl_pct, pct=True),
                self._num(e.r_multiple, suffix="R"),
                self._num(e.holding_days),
                QTableWidgetItem("Open" if e.is_open else "Closed"),
                QTableWidgetItem(e.strategy),
                QTableWidgetItem(", ".join(e.tags)),
            ]
            cells[0].setData(Qt.UserRole, e.id)
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(sort_col, sort_order)
        self.table.resizeColumnsToContents()
        self._refresh_stats(entries)
        self._refresh_breakdown()

    def _refresh_stats(self, entries):
        s = summarize(entries)
        if s["closed"] == 0:
            self.stats_label.setText(f"{s['open']} open trade(s), none closed yet — close trades to see stats.")
            return
        pf = s["profit_factor"]
        pf_txt = "∞" if pf == float("inf") else f"{pf:.2f}"
        avg_r = "—" if s["avg_r"] is None else f"{s['avg_r']:+.2f}R"
        self.stats_label.setText(
            f"Closed {s['closed']}  ·  Win rate {s['win_rate']:.0f}%  "
            f"({s['wins']}W / {s['losses']}L)  ·  Expectancy ${s['expectancy']:,.2f}/trade  ·  "
            f"Profit factor {pf_txt}  ·  Avg {avg_r}  ·  Total P&L ${s['total_pnl']:,.2f}  ·  "
            f"{s['open']} open")

    def _refresh_breakdown(self):
        key = {"Strategy": "strategy", "Tag": "tag", "Symbol": "symbol"}[self.group_by.currentText()]
        groups = group_stats(self.journal.all(), key)
        bh = self.breakdown.horizontalHeader()
        b_col, b_order = bh.sortIndicatorSection(), bh.sortIndicatorOrder()
        if b_col < 0 or b_col >= self.breakdown.columnCount():
            b_col, b_order = 3, Qt.DescendingOrder      # default: biggest P&L first
        self.breakdown.setSortingEnabled(False)
        self.breakdown.setRowCount(len(groups))
        for r, (label, s) in enumerate(groups):
            pnl_item = SortableTableWidgetItem(f"{s['total_pnl']:,.2f}", sort_value=s["total_pnl"])
            pnl_item.setForeground(QColor("#3fb950") if s["total_pnl"] > 0 else QColor("#f0553a") if s["total_pnl"] < 0 else QColor("#8b98a5"))
            avg_r = "—" if s["avg_r"] is None else f"{s['avg_r']:+.2f}"
            for c, item in enumerate([
                QTableWidgetItem(label or "—"),
                SortableTableWidgetItem(str(s["closed"]), sort_value=s["closed"]),
                SortableTableWidgetItem(f"{s['win_rate']:.0f}%", sort_value=s["win_rate"]),
                pnl_item,
                SortableTableWidgetItem(avg_r, sort_value=(s["avg_r"] if s["avg_r"] is not None else -1e18)),
            ]):
                self.breakdown.setItem(r, c, item)
        self.breakdown.setSortingEnabled(True)
        self.breakdown.sortItems(b_col, b_order)
        self.breakdown.resizeColumnsToContents()


class ManualBrowser(QTextBrowser):
    """User-manual viewer whose embedded screenshots scale with the window
    AND with Ctrl+wheel zoom, so images 'follow' both when you resize/maximize
    the window and when you zoom the text in or out (like a browser page zoom),
    instead of staying at their fixed native pixel size."""

    def __init__(self, base_dir):
        super().__init__()
        self.setOpenExternalLinks(True)
        self._base_dir = Path(base_dir)
        # Resolve the manual's relative image paths (images/*.png).
        self.setSearchPaths([str(self._base_dir)])
        self._native = {}  # src name -> (width, height) in native pixels
        self._base_pt = None  # font point size at zoom 1.0

    def load_markdown(self, md):
        self.setMarkdown(md)
        # Capture a baseline point size so the zoom factor is well-defined even
        # if the widget font was pixel-sized.
        if self.font().pointSizeF() <= 0:
            f = self.font(); f.setPointSizeF(11.0); self.setFont(f)
        self._base_pt = self.font().pointSizeF()
        # NOTE: links keep Qt's default (light-blue) colour in the on-screen
        # viewer. Only the PDF export recolours links to black.
        self._rescale_images()

    def wheelEvent(self, event):
        """Ctrl+wheel zooms text (works even though the viewer is read-only)
        and rescales images by the same factor so they zoom together."""
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoomIn(1)
            elif event.angleDelta().y() < 0:
                self.zoomOut(1)
            self._rescale_images()
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_images()

    def _zoom_factor(self):
        cur = self.font().pointSizeF()
        if self._base_pt and self._base_pt > 0 and cur > 0:
            return cur / self._base_pt
        return 1.0

    def _native_size(self, name):
        if name not in self._native:
            img = QImage(str(self._base_dir / name))
            self._native[name] = (img.width(), img.height()) if not img.isNull() else (0, 0)
        return self._native[name]

    def _rescale_images(self):
        """Size every embedded image to the content width scaled by the current
        zoom factor (aspect preserved)."""
        avail = self.viewport().width() - 24  # leave room for scrollbar/margins
        if avail < 50:
            return
        _scale_doc_images(self.document(), avail * self._zoom_factor(), self._native_size)


class NotesPanel(QWidget):
    """A free-form notes scratchpad, auto-saved to data/notes.txt."""

    def __init__(self, path=None):
        super().__init__()
        self._path = path
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(_hint(
            "A free-form scratchpad — your trading plan, ideas, reminders, rules. "
            "It saves automatically as you type (stored on this PC)."), 1)
        self.saved_label = QLabel(""); self.saved_label.setStyleSheet("color:#8b98a5;")
        top.addWidget(self.saved_label)
        layout.addLayout(top)

        self.editor = QTextEdit(); self.editor.setAcceptRichText(False)
        self.editor.setPlainText(load_notes(self._path))
        self.editor.textChanged.connect(self._on_changed)
        layout.addWidget(self.editor, 1)

        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.save)

    def _on_changed(self):
        self.saved_label.setText("Editing…")
        self._timer.start(800)          # debounce: save shortly after you stop typing

    def save(self):
        save_notes(self.editor.toPlainText(), self._path)
        self.saved_label.setText("Saved ✓")

    def shutdown(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        self.save()


class LinksPanel(QWidget):
    """A personal bookmark list: name + URL (+ optional group) for the research
    sites, broker pages, news and screeners you use. Double-click to open in
    your default browser. Stored locally; opens links only, sends nothing."""

    _COLS = ["Name", "URL", "Group"]

    def __init__(self, store=None):
        super().__init__()
        self.store = store or LinkStore()
        self._editing_id = None
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "Keep your go-to research sites, broker pages, news and screeners here. "
            "Enter a name and a URL (https:// is added if you omit it), then "
            "double-click a row to open it in your browser. Stored on your PC."))

        form = QGroupBox("Add / edit a link")
        fl = QHBoxLayout(form)
        self.f_name = QLineEdit(); self.f_name.setPlaceholderText("Name e.g. Finviz Map")
        self.f_url = QLineEdit(); self.f_url.setPlaceholderText("URL e.g. finviz.com/map.ashx")
        self.f_group = QLineEdit(); self.f_group.setPlaceholderText("Group (optional)"); self.f_group.setMaximumWidth(150)
        self.save_btn = QPushButton("Add"); self.save_btn.clicked.connect(self.save)
        new_btn = QPushButton("Clear"); new_btn.clicked.connect(self.clear_form)
        fl.addWidget(QLabel("Name")); fl.addWidget(self.f_name, 1)
        fl.addWidget(QLabel("URL")); fl.addWidget(self.f_url, 2)
        fl.addWidget(QLabel("Group")); fl.addWidget(self.f_group)
        fl.addWidget(self.save_btn); fl.addWidget(new_btn)
        layout.addWidget(form)

        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.table, 1)

        controls = QHBoxLayout()
        open_btn = QPushButton("Open selected"); open_btn.clicked.connect(self.open_selected)
        remove_btn = QPushButton("Remove"); remove_btn.clicked.connect(self.remove_selected)
        import_btn = QPushButton("Import CSV"); import_btn.clicked.connect(self.import_csv)
        export_btn = QPushButton("Export CSV"); export_btn.clicked.connect(self.export_csv)
        controls.addWidget(open_btn); controls.addWidget(remove_btn)
        controls.addStretch()
        controls.addWidget(import_btn); controls.addWidget(export_btn)
        layout.addLayout(controls)

        self.status = QLabel("Double-click a link to open it.")
        layout.addWidget(self.status)
        self.refresh()

    # --- helpers ----------------------------------------------------------
    def _selected_ids(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), 0)
            if item:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _open(self, url):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _open_row(self, row, _col):
        item = self.table.item(row, 0)
        link = self.store.get(item.data(Qt.UserRole)) if item else None
        if link:
            self._open(link.url)
            self.status.setText(f"Opened {link.name}.")

    # --- actions ----------------------------------------------------------
    def save(self):
        name, url = self.f_name.text().strip(), self.f_url.text().strip()
        if not name or not url:
            self.status.setText("Enter a name and a URL.")
            return
        if self._editing_id and self.store.get(self._editing_id):
            self.store.update(self._editing_id, name=name, url=url, group=self.f_group.text())
            self.status.setText(f"Updated {name}.")
        else:
            self.store.add(Link(name=name, url=url, group=self.f_group.text()))
            self.status.setText(f"Added {name}.")
        self.refresh()
        self.clear_form()

    def clear_form(self):
        self._editing_id = None
        self.f_name.clear(); self.f_url.clear(); self.f_group.clear()
        self.save_btn.setText("Add")
        self.table.clearSelection()

    def _on_selection(self):
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        link = self.store.get(ids[0])
        if link:
            self.f_name.setText(link.name); self.f_url.setText(link.url); self.f_group.setText(link.group)
            self._editing_id = link.id
            self.save_btn.setText("Save changes")

    def open_selected(self):
        for i in self._selected_ids():
            link = self.store.get(i)
            if link:
                self._open(link.url)

    def remove_selected(self):
        for i in self._selected_ids():
            self.store.remove(i)
        self.clear_form()
        self.refresh()

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export links", "links.csv", "CSV files (*.csv)")
        if not path:
            return
        rows = [{"name": l.name, "url": l.url, "group": l.group, "notes": l.notes}
                for l in self.store.all()]
        pd.DataFrame(rows).to_csv(path, index=False)
        self.status.setText(f"Exported {len(rows)} links.")

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import links", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            self.status.setText(f"Import failed: {exc}")
            return
        added = 0
        for _, row in df.iterrows():
            name = str(row.get("name", "") or "").strip()
            url = str(row.get("url", "") or "").strip()
            if name and url:
                self.store.add(Link(name=name, url=url, group=str(row.get("group", "") or "")))
                added += 1
        self.refresh()
        self.status.setText(f"Imported {added} links.")

    # --- rendering --------------------------------------------------------
    def refresh(self):
        links = sorted(self.store.all(), key=lambda l: (l.group.lower(), l.name.lower()))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(links))
        for r, link in enumerate(links):
            name_item = QTableWidgetItem(link.name)
            name_item.setData(Qt.UserRole, link.id)
            for c, item in enumerate([name_item, QTableWidgetItem(link.url), QTableWidgetItem(link.group)]):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()


class SettingsPanel(QWidget):
    """App settings — currently the data-source (provider) selector plus
    database/info. The provider abstraction lets the app swap where prices &
    fundamentals come from without touching any other tab."""

    def __init__(self, db: Database, settings=None):
        super().__init__()
        self.db = db
        self._settings = settings or QSettings("TradeLabPro", "TradeLabPro")
        from tradelab.data import providers
        layout = QVBoxLayout(self)

        box = QGroupBox("Data source")
        v = QVBoxLayout(box)
        v.addWidget(_hint(
            "Where the app gets prices and fundamentals. Switch to Offline (synthetic) "
            "to run with no network (demos/testing) — new data loads use the selected "
            "source. The architecture supports adding more sources (Alpaca, Polygon, "
            "IBKR feed) later."))
        row = QHBoxLayout()
        self.source = QComboBox(); self.source.addItems(providers.provider_names())
        self.source.setCurrentText(providers.active_name())
        self.source.currentTextChanged.connect(self._on_source_changed)
        row.addWidget(QLabel("Provider")); row.addWidget(self.source, 1)
        v.addLayout(row)
        self.source_desc = QLabel(); self.source_desc.setWordWrap(True)
        self.source_desc.setStyleSheet("color:#8b98a5;")
        v.addWidget(self.source_desc)
        layout.addWidget(box)

        self.info = QTextEdit(); self.info.setReadOnly(True)
        layout.addWidget(self.info, 1)
        self._refresh_info()
        self._update_desc()

    def _on_source_changed(self, name):
        from tradelab.data import providers
        if providers.set_active(name):
            self._settings.setValue("data/provider", name)
        self._update_desc()

    def _update_desc(self):
        from tradelab.data import providers
        p = providers.get(self.source.currentText())
        text = p.description if p else ""
        if p and p.requires_network and not p.available():
            text += "  ⚠ yfinance is not installed — this source falls back to synthetic data."
        self.source_desc.setText(text)

    def _refresh_info(self):
        self.info.setText(
            f"Database: {self.db.path}\nData folder: {DATA_DIR}\n"
            f"Scan history rows: {self.db.scan_history_count()}\n"
            f"Scan result rows: {self.db.scan_result_count()}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - {APP_VERSION}")
        self.resize(1600, 950)
        self._settings = QSettings("TradeLabPro", "TradeLabPro")
        self.db = Database()
        self.cfg = ScannerConfig()
        # Apply the saved data source before any panel fetches data.
        saved_provider = self._settings.value("data/provider")
        if saved_provider:
            from tradelab.data import providers
            providers.set_active(str(saved_provider))
        # Discover indicator plugins before building panels, so their field
        # dropdowns include any plugin-provided indicators.
        from tradelab.core import plugins
        plugins.discover_plugins()
        splitter = QSplitter(Qt.Horizontal)
        self.splitter = splitter
        # Multi-row tab bar: every tab stays visible (wraps to 2+ rows) instead
        # of overflowing into a scroll arrow.
        tabs = MultiRowTabs()
        self.tabs = tabs
        self.chart = ChartWorkspace()
        self.chart.fullscreenRequested.connect(self.toggle_chart_fullscreen)
        self.watch_panel = WatchlistPanel(self.db, self.chart, self.cfg)
        self.portfolio_panel = PortfolioPanel(self.db)
        self.scanner_panel = ScannerPanel(self.db, self.chart, self.watch_panel.refresh,
                                          self.portfolio_panel.refresh,
                                          on_show_heatmap=self._show_scan_in_heatmap)
        # Each tab page is wrapped in a scroll area (see _scroll_tab) so no
        # single tall tab can force the whole window past the screen height
        # and clip the bottom.
        tabs.addTab(_scroll_tab(self.scanner_panel), "Scanner")
        tabs.addTab(_scroll_tab(self.watch_panel), "Watchlists")
        tabs.addTab(_scroll_tab(self.portfolio_panel), "Portfolio")
        self.alerts_panel = AlertsPanel(symbol_provider=self.db.watch_symbols)
        tabs.addTab(_scroll_tab(self.alerts_panel), "Alerts")
        self.heatmap_panel = HeatmapPanel(self.db, self.chart, self.cfg)
        self._heatmap_page = _scroll_tab(self.heatmap_panel)
        tabs.addTab(self._heatmap_page, "Heatmap")
        tabs.addTab(_scroll_tab(MarketPanel()), "Market")
        self.backtest_panel = BacktestPanel(self.chart, self.cfg)
        tabs.addTab(_scroll_tab(self.backtest_panel), "Backtest")
        self.replay_panel = ReplayPanel(self.chart, self.cfg)
        tabs.addTab(_scroll_tab(self.replay_panel), "Replay")
        # When a custom strategy is saved/deleted in the builder, refresh the
        # Scanner and Backtest strategy dropdowns so it appears immediately.
        tabs.addTab(_scroll_tab(StrategyBuilderPanel(on_strategies_changed=self._on_strategies_changed)), "Strategies")
        tabs.addTab(_scroll_tab(PluginPanel(on_plugins_changed=self._on_plugins_changed)), "Plugins")
        tabs.addTab(_scroll_tab(PaperTradingPanel()), "Paper Trading")
        self.journal_panel = JournalPanel(self.chart, self.cfg)
        tabs.addTab(_scroll_tab(self.journal_panel), "Journal")
        self.risk_panel = RiskPanel(self.db)
        tabs.addTab(_scroll_tab(self.risk_panel), "Risk")
        tabs.addTab(_scroll_tab(AIAssistantPanel()), "AI Assist")
        self.notes_panel = NotesPanel()
        tabs.addTab(_scroll_tab(self.notes_panel), "Notes")
        tabs.addTab(_scroll_tab(LinksPanel()), "Links")
        tabs.addTab(_scroll_tab(SettingsPanel(self.db)), "Settings")
        # UI-001: keep the left control area usable.  The splitter may still
        # be resized, but the scanner/watchlist/settings column will not
        # collapse to an unreadable width.
        tabs.setMinimumWidth(420)
        self.scanner_panel.setMinimumWidth(400)
        splitter.addWidget(tabs)
        splitter.addWidget(self.chart)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # Give the left control column more room by default so its tab bar packs
        # into fewer rows and panel content isn't squeezed. Use the chart's
        # ⛶ Full screen button when you want the chart to fill the monitor.
        splitter.setSizes([640, 1000])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage(f"{APP_NAME} {APP_VERSION} ready")
        self._build_menus()
        self.restore_window_state()

    def _build_menus(self):
        """Menu bar with a Help section: an in-app User Manual viewer and a
        Version / About dialog. References are held on self so PySide6 doesn't
        garbage-collect the underlying C++ menu/actions."""
        self.help_menu = self.menuBar().addMenu("&Help")

        self.manual_action = QAction("User Manual", self)
        self.manual_action.setShortcut("F1")
        self.manual_action.triggered.connect(self.show_user_manual)
        self.help_menu.addAction(self.manual_action)

        self.help_menu.addSeparator()

        self.version_action = QAction("Version", self)
        self.version_action.triggered.connect(self.show_version)
        self.help_menu.addAction(self.version_action)

    def show_user_manual(self):
        """Open the bundled docs/USER_MANUAL.md in a scrollable in-app viewer
        (rendered from Markdown), so users never leave the app to read it."""
        manual_path = ROOT_DIR / "docs" / "USER_MANUAL.md"
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{APP_NAME} - User Manual")
        # Standard window title-bar controls: minimize and maximize/restore
        # next to the close [X], like any normal window.
        dlg.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint
                           | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        dlg.resize(900, 720)
        layout = QVBoxLayout(dlg)

        # Top shortcut row: open the manual as a PDF in the system viewer.
        toolbar = QHBoxLayout()
        pdf_btn = QPushButton("📄  Open as PDF")
        pdf_btn.setToolTip("Export the manual to a PDF and open it in your default viewer")
        pdf_btn.clicked.connect(lambda: self._export_manual_pdf(manual_path))
        toolbar.addWidget(pdf_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        viewer = ManualBrowser(manual_path.parent)
        try:
            viewer.load_markdown(manual_path.read_text(encoding="utf-8"))
        except Exception as e:
            viewer.setPlainText(
                f"Could not load the user manual from:\n{manual_path}\n\n{e}")
        layout.addWidget(viewer)
        dlg.exec()

    def _export_manual_pdf(self, manual_path):
        """Render the manual (text + screenshots) to a PDF and open it in the
        system's default viewer. Images are pre-loaded as document resources so
        they embed reliably, and sized to the printable page width."""
        import tempfile, os
        from PySide6.QtCore import QUrl, QSizeF
        from PySide6.QtGui import QTextDocument, QDesktopServices, QPageSize
        try:
            from PySide6.QtPrintSupport import QPrinter
        except Exception:
            QMessageBox.warning(self, "PDF export unavailable",
                                "Qt print support is not installed in this environment.")
            return
        try:
            out = os.path.join(tempfile.gettempdir(), "TradeLab_Pro_User_Manual.pdf")
            printer = QPrinter()
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(out)
            printer.setPageSize(QPageSize(QPageSize.A4))

            doc = QTextDocument()
            base = manual_path.parent
            doc.setBaseUrl(QUrl.fromLocalFile(str(base).replace("\\", "/") + "/"))
            # Embed each screenshot as a document resource keyed by its markdown
            # path so it renders even without a live search-path resolver.
            img_dir = base / "images"
            if img_dir.is_dir():
                for p in img_dir.glob("*.png"):
                    doc.addResource(QTextDocument.ImageResource,
                                    QUrl("images/" + p.name), QImage(str(p)))
            doc.setMarkdown(manual_path.read_text(encoding="utf-8"))
            _recolor_doc_links(doc)  # black links (incl. the TOC) in the PDF too

            cache = {}
            def native(name):
                if name not in cache:
                    im = QImage(str(base / name))
                    cache[name] = (im.width(), im.height()) if not im.isNull() else (0, 0)
                return cache[name]

            page = printer.pageRect(QPrinter.Point)
            _scale_doc_images(doc, page.width(), native)
            doc.setPageSize(QSizeF(page.width(), page.height()))
            doc.print_(printer)

            QDesktopServices.openUrl(QUrl.fromLocalFile(out))
        except Exception as e:
            QMessageBox.warning(self, "PDF export failed", str(e))

    def show_version(self):
        """Version / About dialog."""
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p><b>Version:</b> {APP_VERSION}</p>"
            "<p>A desktop trading workstation for scanning, charting, watchlists, "
            "portfolios, alerts, market heatmaps, backtesting, strategy building, "
            "and simulated paper trading.</p>"
            "<p><i>Analysis and practice tool only. It does not place real orders or "
            "provide financial advice.</i></p>")

    def _show_scan_in_heatmap(self, symbols):
        """Scanner → Heatmap: map the scan results and switch to the Heatmap tab."""
        self.heatmap_panel.set_external_symbols(symbols, "Scanner results")
        self.tabs.setCurrentWidget(self._heatmap_page)

    def toggle_chart_fullscreen(self):
        """Expand the chart to fill the whole monitor (hiding the left tab
        panel and window chrome), or retract back to the normal layout."""
        if not getattr(self, "_chart_full", False):
            self._chart_full = True
            self._saved_split_sizes = self.splitter.sizes()
            self._was_maximized = self.isMaximized()
            self.tabs.hide()
            self.chart.set_fullscreen_label(True)
            self.showFullScreen()
        else:
            self._chart_full = False
            self.tabs.show()
            self.chart.set_fullscreen_label(False)
            try:
                self.splitter.setSizes(self._saved_split_sizes)
            except Exception:
                pass
            self.showMaximized()

    def keyPressEvent(self, event):
        # Esc also exits chart full-screen.
        if event.key() == Qt.Key_Escape and getattr(self, "_chart_full", False):
            self.toggle_chart_fullscreen()
            return
        super().keyPressEvent(event)

    def _on_strategies_changed(self):
        self.scanner_panel.refresh_strategies()
        self.backtest_panel.refresh_strategies()

    def _on_plugins_changed(self):
        # Plugin indicators became new condition fields - rebuild the custom
        # filter rows so the field dropdowns pick them up.
        try:
            self.scanner_panel.set_custom_filters(self.scanner_panel.get_custom_filters())
        except Exception:
            pass

    def restore_window_state(self):
        try:
            geom = self._settings.value("MainWindow/geometry")
            if geom:
                self.restoreGeometry(geom)
            state = self._settings.value("MainWindow/windowState")
            if state:
                self.restoreState(state)
            maximized = self._settings.value("MainWindow/maximized", "true")
            if str(maximized).lower() in {"true", "1", "yes"}:
                QTimer.singleShot(0, self.showMaximized)
        except Exception:
            QTimer.singleShot(0, self.showMaximized)

    def closeEvent(self, event):
        try:
            self._settings.setValue("MainWindow/geometry", self.saveGeometry())
            self._settings.setValue("MainWindow/windowState", self.saveState())
            self._settings.setValue("MainWindow/maximized", self.isMaximized())
        except Exception:
            pass
        try:
            self.alerts_panel.shutdown()  # stop poller + worker cleanly
        except Exception:
            pass
        try:
            self.heatmap_panel.shutdown()
        except Exception:
            pass
        try:
            self.journal_panel.shutdown()
        except Exception:
            pass
        try:
            self.risk_panel.shutdown()
        except Exception:
            pass
        try:
            self.replay_panel.shutdown()
        except Exception:
            pass
        try:
            self.notes_panel.shutdown()   # flush unsaved notes
        except Exception:
            pass
        super().closeEvent(event)


def run_app():
    from tradelab.core.logging_config import configure_logging, get_logger
    configure_logging()
    log = get_logger(__name__)
    log.info("TradeLab Pro starting (version %s)", APP_VERSION)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    def show_exception(exc_type, exc_value, exc_traceback):
        import traceback
        from tradelab.core.config import DATA_DIR
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log.error("Uncaught exception:\n%s", msg)
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "last_error.log"
        log_path.write_text(msg, encoding="utf-8")
        parent = QApplication.activeWindow()
        QMessageBox.critical(parent, "TradeLab Pro Error", f"An error occurred.\n\n{str(exc_value)}\n\nFull log:\n{log_path}")

    sys.excepthook = show_exception
    win = MainWindow()
    win.showMaximized()
    win.raise_()
    win.activateWindow()
    QTimer.singleShot(250, win.raise_)
    QTimer.singleShot(300, win.activateWindow)
    sys.exit(app.exec())
