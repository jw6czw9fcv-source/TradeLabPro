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
            self.scan_name, self.country, self.min_price, self.max_price, self.min_volume, self.min_cap,
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

        self.table = QTableWidget(0, 11)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setHorizontalHeaderLabels(["Symbol", "Signal", "Score", "Price", "Volume", "RelVol", "Market Cap", "RSI", "ATR%", "EMA", "MACD"])
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
            "universes": [cb.property('universe_name') for cb in self.universe_checks if cb.isChecked()],
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
        self.rebuild_universe_checks()
        selected = set(data.get("universes", []))
        for cb in self.universe_checks:
            cb.setChecked(bool(set(cb.property('universe_names') or []) & selected) or cb.property('universe_name') in selected)

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
        for cb in self.universe_checks:
            name = cb.property('universe_name')
            cb.setChecked(bool(cb.property("universe_names")))
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
            price = row.get("Price", 0)
            volume = row.get("Volume", 0)
            rel_vol = row.get("RelVol", 0)
            market_cap = row.get("Market Cap", 0)
            rsi14 = row.get("RSI14", 0)
            atr_pct = row.get("ATR%", 0)
            ema_trend = row.get("EMA Trend", "")
            macd_state = row.get("MACD", "")
            self.table.setItem(r, 0, table_item(symbol))
            self.table.setItem(r, 1, table_item(signal))
            self.table.setItem(r, 2, table_item(score, numeric=True, display=f"{float(score or 0):.0f}" if str(score) != "" else ""))
            self.table.setItem(r, 3, table_item(price, numeric=True, display=f"{float(price or 0):.2f}" if str(price) != "" else ""))
            self.table.setItem(r, 4, table_item(volume, numeric=True, display=fmt_large(volume)))
            self.table.setItem(r, 5, table_item(rel_vol, numeric=True, display=f"{float(rel_vol or 0):.2f}" if str(rel_vol) != "" else ""))
            self.table.setItem(r, 6, table_item(market_cap, numeric=True, display=fmt_large(market_cap)))
            self.table.setItem(r, 7, table_item(rsi14, numeric=True, display=f"{float(rsi14 or 0):.1f}" if str(rsi14) != "" else ""))
            self.table.setItem(r, 8, table_item(atr_pct, numeric=True, display=f"{float(atr_pct or 0):.2f}%" if str(atr_pct) != "" else ""))
            self.table.setItem(r, 9, table_item(ema_trend))
            self.table.setItem(r, 10, table_item(macd_state))

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
                (7, colors.rsi_zone_color(rsi14)),
                (9, colors.trend_color(ema_trend)),
                (10, colors.trend_color(macd_state)),
            ):
                if color is None:
                    continue
                it = self.table.item(r, col)
                if it:
                    it.setForeground(color)
        self.table.setSortingEnabled(True)
        self.result_status.setText(f"Results: {len(df)}")
        if len(df) <= 200:
            self.table.resizeColumnsToContents()

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
        item = self.table.item(row, 3)
        try: return float(item.text()) if item else 0.0
        except Exception: return 0.0

    def selected_price(self):
        row = self.table.currentRow()
        if row < 0: return 0.0
        item = self.table.item(row, 3)
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
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(["Item","Symbol","Last","Change %","Purpose"])
        layout.addWidget(self.table)
        self.status=QLabel("Refresh to update market regime symbols. Data uses yfinance when available.")
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
    def refresh_market(self):
        self.refresh_btn.setEnabled(False)
        for r,(name,sym,purpose) in enumerate(self.rows):
            try:
                df=get_history(sym,"5d","1d")
                last=float(df["Close"].iloc[-1])
                prev=float(df["Close"].iloc[-2]) if len(df)>1 else last
                ch=(last-prev)/prev*100 if prev else 0
                self.table.setItem(r,2,QTableWidgetItem(f"{last:.2f}"))
                self.table.setItem(r,3,QTableWidgetItem(f"{ch:+.2f}%"))
            except Exception as exc:
                self.table.setItem(r,2,QTableWidgetItem("ERR"))
                self.table.setItem(r,3,QTableWidgetItem(str(exc)[:40]))
        self.table.resizeColumnsToContents()
        self.status.setText("Market dashboard refreshed. Economic calendar and breadth are planned in the next phase.")
        self.refresh_btn.setEnabled(True)


class StrategyBuilderPanel(QWidget):
    def __init__(self):
        super().__init__(); layout=QVBoxLayout(self)
        layout.addWidget(QLabel("No-code Strategy Builder - Phase 2 foundation"))
        form=QFormLayout()
        self.name=QLineEdit("EMA 9/30 + MACD + Volume")
        self.fast=QSpinBox(); self.fast.setRange(1,200); self.fast.setValue(9)
        self.slow=QSpinBox(); self.slow.setRange(1,300); self.slow.setValue(30)
        self.require_macd=QCheckBox("MACD line above signal for BUY"); self.require_macd.setChecked(True)
        self.require_volume=QCheckBox("Volume above 20-day average"); self.require_volume.setChecked(False)
        self.rsi_min=QSpinBox(); self.rsi_min.setRange(0,100); self.rsi_min.setValue(45)
        self.rsi_max=QSpinBox(); self.rsi_max.setRange(0,100); self.rsi_max.setValue(70)
        for lbl,w in [("Strategy name",self.name),("Fast EMA",self.fast),("Slow EMA",self.slow),("MACD confirmation",self.require_macd),("Volume confirmation",self.require_volume),("RSI min",self.rsi_min),("RSI max",self.rsi_max)]:
            form.addRow(lbl,w)
        layout.addLayout(form)
        row=QHBoxLayout(); save=QPushButton("Save strategy preset"); save.clicked.connect(self.save_strategy); row.addWidget(save); row.addStretch(); layout.addLayout(row)
        self.preview=QTextEdit(); self.preview.setReadOnly(True); layout.addWidget(self.preview); self.update_preview()
        for w in [self.name,self.fast,self.slow,self.require_macd,self.require_volume,self.rsi_min,self.rsi_max]:
            try: w.valueChanged.connect(self.update_preview)
            except Exception:
                try: w.textChanged.connect(self.update_preview)
                except Exception: w.stateChanged.connect(self.update_preview)
    def strategy_dict(self):
        return {"name":self.name.text(),"ema_fast":self.fast.value(),"ema_slow":self.slow.value(),"require_macd":self.require_macd.isChecked(),"require_volume":self.require_volume.isChecked(),"rsi_min":self.rsi_min.value(),"rsi_max":self.rsi_max.value()}
    def update_preview(self):
        d=self.strategy_dict()
        txt=f"BUY when EMA{d['ema_fast']} crosses above EMA{d['ema_slow']}"
        if d['require_macd']: txt += "\nAND MACD > Signal"
        if d['require_volume']: txt += "\nAND Volume > Volume average 20"
        txt += f"\nAND RSI between {d['rsi_min']} and {d['rsi_max']}"
        txt += f"\n\nSELL when EMA{d['ema_fast']} crosses below EMA{d['ema_slow']} or strategy exit triggers."
        self.preview.setText(txt)
    def save_strategy(self):
        d=DATA_DIR/"strategies"; d.mkdir(exist_ok=True)
        safe="".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in self.name.text()).strip() or "strategy"
        path=d/f"{safe}.json"
        path.write_text(json.dumps(self.strategy_dict(),indent=2),encoding="utf-8")
        QMessageBox.information(self,"Strategy",f"Saved strategy preset:\n{path}")


class BacktestPanel(QWidget):
    def __init__(self, chart: ChartWidget, cfg: ScannerConfig):
        super().__init__(); self.chart=chart; self.cfg=cfg
        layout=QVBoxLayout(self)
        row=QHBoxLayout()
        self.symbol=QLineEdit("AAPL")
        self.period=QComboBox(); self.period.addItems(["6mo","1y","2y","5y","10y","max"]); self.period.setCurrentText("5y")
        self.interval=QComboBox(); self.interval.addItems(["1d","1wk","1mo"]); self.interval.setCurrentText("1d")
        run=QPushButton("Run backtest"); run.clicked.connect(self.run_backtest)
        row.addWidget(QLabel("Symbol")); row.addWidget(self.symbol); row.addWidget(QLabel("Period")); row.addWidget(self.period); row.addWidget(QLabel("Interval")); row.addWidget(self.interval); row.addWidget(run)
        layout.addLayout(row)
        self.metrics=QTableWidget(0,2); self.metrics.setHorizontalHeaderLabels(["Metric","Value"]); layout.addWidget(self.metrics)
        self.trades=QTableWidget(0,5); self.trades.setHorizontalHeaderLabels(["Entry Date","Exit Date","Entry","Exit","Return %"]); layout.addWidget(self.trades)
        self.status=QLabel("Backtest uses current EMA/MACD strategy. This is for research only, not financial advice."); self.status.setWordWrap(True); layout.addWidget(self.status)
    def run_backtest(self):
        cfg=ScannerConfig(); cfg.period=self.period.currentText(); cfg.interval=self.interval.currentText()
        res=backtest_ema_macd(self.symbol.text().strip().upper(), cfg)
        items=list(res.metrics.items())
        self.metrics.setRowCount(len(items))
        for r,(k,v) in enumerate(items):
            self.metrics.setItem(r,0,QTableWidgetItem(str(k))); self.metrics.setItem(r,1,QTableWidgetItem(str(v)))
        df=res.trades
        self.trades.setRowCount(len(df))
        for r,(_,row) in enumerate(df.iterrows()):
            for c,key in enumerate(["Entry Date","Exit Date","Entry","Exit","Return %"]): self.trades.setItem(r,c,QTableWidgetItem(str(row.get(key,""))))
        self.metrics.resizeColumnsToContents(); self.trades.resizeColumnsToContents()
        try:
            dfhist=get_history(self.symbol.text().strip().upper(), cfg.period, cfg.interval)
            self.chart.plot(self.symbol.text().strip().upper(), dfhist, cfg)
        except Exception: pass
        self.status.setText(f"Backtest complete: {len(df)} trade rows.")


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


class PluginPanel(QWidget):
    def __init__(self):
        super().__init__(); layout=QVBoxLayout(self)
        layout.addWidget(QLabel("Plugin System - Phase 3 foundation"))
        self.text=QTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text); self.refresh()
    def refresh(self):
        plug_dir=Path(__file__).resolve().parents[1]/"plugins"
        files=sorted([p.name for p in plug_dir.glob("*.py") if p.name != "__init__.py"])
        self.text.setText("Plugins folder:\n"+str(plug_dir)+"\n\nDetected plugins:\n"+"\n".join(files)+"\n\nFuture: custom indicators, custom strategies, custom scanners.")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - {APP_VERSION}")
        self.resize(1600, 950)
        self._settings = QSettings("TradeLabPro", "TradeLabPro")
        self.db = Database()
        self.cfg = ScannerConfig()
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
        tabs.addTab(StrategyBuilderPanel(), "Strategies")
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
