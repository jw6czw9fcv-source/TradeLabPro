"""Dockable Chart Engine workspace (Phase 1).

Replaces the previous QTabWidget-based ChartWorkspace with real dockable,
resizable, floatable panels (QDockWidget hosted inside an internal
QMainWindow used purely as a dock area). Panels can be dragged into tabs,
split, floated to a second monitor, and the whole arrangement can be saved
and restored by name.

Public API kept compatible with the previous ChartWorkspace so app.py did
not need to change:
    - .add_chart(symbol="") -> panel with the same interface as before
    - .plot(symbol, df, cfg)
    - .current_chart() -> panel
"""
from __future__ import annotations

import base64
import json
from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QMainWindow, QDockWidget, QToolButton, QComboBox, QInputDialog, QMessageBox

from tradelab.core.config import ScannerConfig
from tradelab.data.database import Database
from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
from tradelab.core.logging_config import get_logger

log = get_logger(__name__)


class ChartWorkspace(QWidget):
    def __init__(self):
        super().__init__()
        self._db: Optional[Database] = None
        self._panels: list[PGChartWidget] = []
        self._docks: list[QDockWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        new_btn = QToolButton(); new_btn.setText("+ Chart"); new_btn.setToolTip("Add a new dockable chart panel")
        new_btn.clicked.connect(lambda: self.add_chart(""))
        toolbar.addWidget(new_btn)

        self.layout_combo = QComboBox()
        self.layout_combo.setMinimumWidth(140)
        toolbar.addWidget(self.layout_combo)
        self._refresh_layout_list()

        load_btn = QToolButton(); load_btn.setText("Load layout")
        load_btn.clicked.connect(self._load_selected_layout)
        toolbar.addWidget(load_btn)

        save_btn = QToolButton(); save_btn.setText("Save layout as…")
        save_btn.clicked.connect(self._save_layout_as)
        toolbar.addWidget(save_btn)

        toolbar.addStretch()
        outer.addLayout(toolbar)

        # QMainWindow used purely as an embedded dock-area host (not shown
        # as its own top-level window) - the standard way to get real
        # QDockWidget docking/floating/tabifying inside another widget.
        self._dock_host = QMainWindow()
        self._dock_host.setWindowFlags(Qt.Widget)
        self._dock_host.setDockNestingEnabled(True)
        outer.addWidget(self._dock_host)

        self.add_chart("AAPL")

    # ------------------------------------------------------------------
    def _get_db(self) -> Database:
        if self._db is None:
            self._db = Database()
        return self._db

    # ------------------------------------------------------------------
    def add_chart(self, symbol: str = "") -> PGChartWidget:
        panel = PGChartWidget()
        title = symbol.upper() if symbol else "Empty"
        dock = QDockWidget(title, self._dock_host)
        dock.setObjectName(f"chart_dock_{len(self._docks)}")
        dock.setWidget(panel)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )

        if not self._docks:
            self._dock_host.addDockWidget(Qt.TopDockWidgetArea, dock)
        else:
            # Tabify with the first dock by default; the user can freely
            # drag it out to split/float afterward - that's the point of
            # a real dockable workspace vs. fixed tabs.
            self._dock_host.tabifyDockWidget(self._docks[0], dock)

        dock.visibilityChanged.connect(lambda _v, d=dock: self._prune_closed(d))
        panel.symbolChanged.connect(lambda sym, d=dock: d.setWindowTitle(sym.upper() if sym else "Empty"))

        self._panels.append(panel)
        self._docks.append(dock)

        if symbol:
            try:
                cfg = ScannerConfig()
                df = panel._get_cached_history(symbol.upper(), cfg.period, cfg.interval)
                panel.plot(symbol.upper(), df, cfg)
            except Exception:
                log.exception("Failed to load initial history for %s", symbol)
        else:
            panel.symbol = ""
            panel.show_empty_placeholder()

        dock.raise_()
        return panel

    def _prune_closed(self, dock: QDockWidget):
        if dock.isVisible():
            return
        if dock in self._docks:
            idx = self._docks.index(dock)
            self._docks.pop(idx)
            self._panels.pop(idx)

    def current_chart(self) -> PGChartWidget:
        if not self._panels:
            return self.add_chart("AAPL")
        # "Current" = whichever dock is on top of its tab group; fall back
        # to the first panel if none report focus.
        for dock, panel in zip(self._docks, self._panels):
            if dock.isVisible() and not dock.visibleRegion().isEmpty():
                return panel
        return self._panels[0]

    def plot(self, symbol: str, df: pd.DataFrame, cfg: ScannerConfig):
        chart = self.current_chart()
        chart.plot(symbol, df, cfg)

    # ------------------------------------------------------------------
    # Layout persistence
    # ------------------------------------------------------------------
    def _refresh_layout_list(self):
        self.layout_combo.clear()
        try:
            names = self._get_db().list_chart_layouts()
        except Exception:
            names = []
        self.layout_combo.addItems(names or ["(no saved layouts)"])

    def _save_layout_as(self):
        name, ok = QInputDialog.getText(self, "Save chart layout", "Layout name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        state_b64 = base64.b64encode(bytes(self._dock_host.saveState())).decode("ascii")
        panels_meta = [
            {"symbol": p.symbol, "period": p.cfg.period, "chart_type": p.chart_type}
            for p in self._panels
        ]
        payload = json.dumps({"dock_state": state_b64, "panels": panels_meta})
        try:
            self._get_db().save_chart_layout(name, payload)
            self._refresh_layout_list()
            idx = self.layout_combo.findText(name)
            if idx >= 0:
                self.layout_combo.setCurrentIndex(idx)
        except Exception:
            log.exception("Failed to save chart layout %s", name)
            QMessageBox.warning(self, "Save layout", "Could not save this layout. Check logs for details.")

    def _load_selected_layout(self):
        name = self.layout_combo.currentText()
        if not name or name.startswith("("):
            return
        try:
            payload = self._get_db().load_chart_layout(name)
        except Exception:
            log.exception("Failed to load chart layout %s", name)
            return
        if not payload:
            return
        data = json.loads(payload)

        # Remove existing docks/panels, then recreate one per saved panel.
        for dock in list(self._docks):
            self._dock_host.removeDockWidget(dock)
            dock.deleteLater()
        self._docks = []
        self._panels = []

        for meta in data.get("panels", []) or [{}]:
            panel = self.add_chart(meta.get("symbol", ""))
            if meta.get("period"):
                panel.period_combo.setCurrentText(meta["period"])
            if meta.get("chart_type"):
                panel.chart_type_combo.setCurrentText(meta["chart_type"])

        state_b64 = data.get("dock_state")
        if state_b64:
            try:
                self._dock_host.restoreState(base64.b64decode(state_b64))
            except Exception:
                log.exception("Failed to restore dock geometry for layout %s", name)
