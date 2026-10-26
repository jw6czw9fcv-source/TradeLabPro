"""The Plugins tab: strategies and indicators added from files."""
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
