"""The Links tab: your bookmarks, opened in the browser."""
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
from tradelab.ui.common import (StatusLabel, _hint, flag_problem, open_external)

log = get_logger(__name__)


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

        self.status = StatusLabel("Double-click a link to open it.")
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

    def _open_link(self, link):
        """Open one saved link in the browser, brought to the front; True when
        it went. A refusal is a pop-up, with the address left on the clipboard
        to paste into the browser by hand."""
        reason = open_external(link.url)
        if reason is None:
            return True
        QApplication.clipboard().setText(link.url)
        flag_problem(self.status, f"Could not open {link.name}: {reason}",
                     f"Its address is on the clipboard - paste it into your browser:\n{link.url}")
        return False

    def _open_row(self, row, _col):
        item = self.table.item(row, 0)
        link = self.store.get(item.data(Qt.UserRole)) if item else None
        if link and self._open_link(link):
            self.status.setText(f"Opened {link.name} in your browser.")

    # --- actions ----------------------------------------------------------
    def save(self):
        name, url = self.f_name.text().strip(), self.f_url.text().strip()
        if not name or not url:
            flag_problem(self.status, "Enter a name and a URL.")
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
        links = [link for link in map(self.store.get, self._selected_ids()) if link]
        if not links:
            flag_problem(self.status, "Select a link in the list first, then click Open selected.")
            return
        opened = [link.name for link in links if self._open_link(link)]
        if opened:
            self.status.setText(f"Opened {', '.join(opened)} in your browser.")

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
            flag_problem(self.status, f"Import failed: {exc}")
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
