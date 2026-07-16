import sys
import json
import traceback
import time
from pathlib import Path
import pandas as pd
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QSpinBox, QDoubleSpinBox, QComboBox,
    QListWidget, QLineEdit, QMessageBox, QSplitter, QFormLayout, QGroupBox, QCheckBox,
    QAbstractItemView, QTextEdit, QFileDialog, QProgressBar, QScrollArea, QHeaderView,
    QMenu, QToolButton, QSizePolicy
)

from tradelab.core.config import APP_NAME, APP_VERSION, ScannerConfig, DATA_DIR
from tradelab.data.database import Database
from tradelab.data.universe import list_symbols, available_universes, refresh_exchange_cache, import_universe_file, universe_metadata
from tradelab.data.market_data import get_history
from tradelab.core.scanner import scan_symbols
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
    def __init__(self, db: Database, chart: ChartWidget, on_watchlist_changed=None, on_portfolio_changed=None):
        super().__init__()
        self.db = db
        self.chart = chart
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
        row.addWidget(self.add_watch); row.addWidget(self.add_port); row.addWidget(self.load_chart); row.addWidget(export_btn)
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


def _build_condition_row(condition, on_change, on_remove):
    """Build one condition-editing row: field + (tunable) period + operator +
    value(s) OR a second field + its period. Shared by the Scanner's custom
    filters and the Strategy Builder so the two stay identical. Returns
    (row_widget, widgets_dict)."""
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

    rm = QToolButton(); rm.setText("×"); rm.setMaximumWidth(24); rm.clicked.connect(lambda: on_remove(row))
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
    def __init__(self, chart: ChartWidget):
        super().__init__(); self.chart=chart; self.data=None; self.index=80; self.symbol_text="AAPL"; self.cfg=ScannerConfig()
        layout=QVBoxLayout(self)
        row=QHBoxLayout(); self.symbol=QLineEdit("AAPL"); self.period=QComboBox(); self.period.addItems(["1y","2y","5y","10y"]); self.period.setCurrentText("2y")
        load=QPushButton("Load replay"); load.clicked.connect(self.load_replay); step=QPushButton("Next candle"); step.clicked.connect(self.next_candle)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.symbol); row.addWidget(QLabel("Period")); row.addWidget(self.period); row.addWidget(load); row.addWidget(step); row.addStretch(); layout.addLayout(row)
        self.status=QLabel("Replay mode hides future candles. Load a symbol, then step candle by candle."); self.status.setWordWrap(True); layout.addWidget(self.status); layout.addStretch()
    def load_replay(self):
        self.symbol_text=self.symbol.text().strip().upper(); self.cfg.period=self.period.currentText(); self.cfg.interval="1d"; self.data=get_history(self.symbol_text,self.cfg.period,self.cfg.interval); self.index=min(80,len(self.data)); self._plot()
    def next_candle(self):
        if self.data is None: self.load_replay(); return
        self.index=min(len(self.data),self.index+1); self._plot()
    def _plot(self):
        if self.data is None or self.data.empty: return
        view=self.data.iloc[:self.index]
        self.chart.plot(self.symbol_text,view,self.cfg)
        self.status.setText(f"Replay: {self.symbol_text} candle {self.index}/{len(self.data)} date {str(view.index[-1])[:10]}")


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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - {APP_VERSION}")
        self.resize(1600, 950)
        self._settings = QSettings("TradeLabPro", "TradeLabPro")
        self.db = Database()
        self.cfg = ScannerConfig()
        # Discover indicator plugins before building panels, so their field
        # dropdowns include any plugin-provided indicators.
        from tradelab.core import plugins
        plugins.discover_plugins()
        splitter = QSplitter(Qt.Horizontal)
        tabs = QTabWidget()
        self.chart = ChartWorkspace()
        self.watch_panel = WatchlistPanel(self.db, self.chart, self.cfg)
        self.portfolio_panel = PortfolioPanel(self.db)
        self.scanner_panel = ScannerPanel(self.db, self.chart, self.watch_panel.refresh, self.portfolio_panel.refresh)
        tabs.addTab(self.scanner_panel, "Scanner")
        tabs.addTab(self.watch_panel, "Watchlists")
        tabs.addTab(self.portfolio_panel, "Portfolio")
        tabs.addTab(MarketPanel(), "Market")
        self.backtest_panel = BacktestPanel(self.chart, self.cfg)
        tabs.addTab(self.backtest_panel, "Backtest")
        # When a custom strategy is saved/deleted in the builder, refresh the
        # Scanner and Backtest strategy dropdowns so it appears immediately.
        tabs.addTab(StrategyBuilderPanel(on_strategies_changed=self._on_strategies_changed), "Strategies")
        tabs.addTab(PluginPanel(on_plugins_changed=self._on_plugins_changed), "Plugins")
        tabs.addTab(PaperTradingPanel(), "Paper Trading")
        tabs.addTab(AIAssistantPanel(), "AI Assist")
        settings_text = QTextEdit(); settings_text.setReadOnly(True)
        settings_text.setText(f"Database: {self.db.path}\nData folder: {DATA_DIR}\nScan history rows: {self.db.scan_history_count()}\nScan result rows: {self.db.scan_result_count()}\n\nPhase 2.3 adds scanner setup save/load, scan export, watchlist import/export, portfolio export and scan history storage.")
        tabs.addTab(settings_text, "Settings")
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
        splitter.setSizes([520, 1080])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage(f"{APP_NAME} {APP_VERSION} ready")
        self.restore_window_state()

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
