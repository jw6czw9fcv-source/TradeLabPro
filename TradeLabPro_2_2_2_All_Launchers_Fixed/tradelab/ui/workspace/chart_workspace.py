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
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QMainWindow, QDockWidget, QToolButton, QComboBox, QInputDialog, QMessageBox

from tradelab.core.config import ScannerConfig
from tradelab.data.database import Database
from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
from tradelab.core.logging_config import get_logger

log = get_logger(__name__)


class _ChartDock(QDockWidget):
    """QDockWidget.visibilityChanged fires both when the user actually
    closes a dock AND when it's merely hidden because it isn't the active
    tab in a tabified group - the latter happens to every dock the instant
    a second one is tabified onto it. Using that signal to detect "closed"
    (as a naive implementation would) means opening a second chart tab
    immediately makes the workspace forget the first one ever existed, even
    though it's still open, just not the frontmost tab. closeEvent is the
    signal that only fires on an actual close.
    """
    closed = Signal(object)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.closed.emit(self)


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

        reset_btn = QToolButton(); reset_btn.setText("Reset charts")
        reset_btn.setToolTip("Close every chart tab and start over with a single empty chart")
        reset_btn.clicked.connect(self.reset_charts)
        toolbar.addWidget(reset_btn)

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

        # The native QDockWidget tab bar (from tabifyDockWidget) is easy to
        # miss - it's a thin strip that can end up visually competing with
        # each dock's own title bar. This row is an explicit, always-visible
        # "which chart is open" switcher: click a symbol to bring that
        # chart to front, no hunting for the native tab strip required. Own
        # row, below the button toolbar, so it doesn't get lost among them.
        chart_tabs_row = QHBoxLayout()
        chart_tabs_row.setContentsMargins(4, 0, 4, 2)
        self._chart_tabs_layout = QHBoxLayout()
        self._chart_tabs_layout.setSpacing(2)
        chart_tabs_row.addLayout(self._chart_tabs_layout)
        chart_tabs_row.addStretch()
        outer.addLayout(chart_tabs_row)

        # QMainWindow used purely as an embedded dock-area host (not shown
        # as its own top-level window) - the standard way to get real
        # QDockWidget docking/floating/tabifying inside another widget.
        self._dock_host = QMainWindow()
        self._dock_host.setWindowFlags(Qt.Widget)
        self._dock_host.setDockNestingEnabled(True)
        outer.addWidget(self._dock_host)

        self.add_chart("AAPL")
        self._rebuild_chart_tabs()

    # ------------------------------------------------------------------
    def _get_db(self) -> Database:
        if self._db is None:
            self._db = Database()
        return self._db

    # ------------------------------------------------------------------
    def add_chart(self, symbol: str = "") -> PGChartWidget:
        panel = PGChartWidget()
        title = symbol.upper() if symbol else "Empty"
        dock = _ChartDock(title, self._dock_host)
        dock.setObjectName(f"chart_dock_{len(self._docks)}")
        dock.setWidget(panel)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        # The dock's native title bar just repeats the symbol the switcher
        # row (below the toolbar) and the chart's own search box already
        # show, right above each other. Hiding it costs the drag-by-title-
        # bar gesture for floating/splitting a dock, but the switcher row
        # and Reset charts button cover the everyday cases.
        dock.setTitleBarWidget(QWidget())

        if not self._docks:
            self._dock_host.addDockWidget(Qt.TopDockWidgetArea, dock)
        else:
            # Tabify with the first dock by default; the user can freely
            # drag it out to split/float afterward - that's the point of
            # a real dockable workspace vs. fixed tabs.
            self._dock_host.tabifyDockWidget(self._docks[0], dock)

        dock.closed.connect(self._prune_closed)
        panel.symbolChanged.connect(lambda sym, d=dock: (d.setWindowTitle(sym.upper() if sym else "Empty"), self._rebuild_chart_tabs()))

        self._panels.append(panel)
        self._docks.append(dock)
        self._rebuild_chart_tabs()

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

        # tabifyDockWidget() needs the event loop to run before the tab bar
        # actually registers the new tab - raising synchronously here is a
        # no-op, silently leaving the new chart open but hidden behind
        # whichever tab was already active.
        QTimer.singleShot(0, lambda: (dock.raise_(), self._rebuild_chart_tabs()))
        return panel

    def _prune_closed(self, dock: QDockWidget):
        # dock.closed only fires on an actual user close (see _ChartDock),
        # not on the tab-switch hide that every non-active tabified dock
        # goes through - no isVisible() guard needed here anymore.
        if dock in self._docks:
            idx = self._docks.index(dock)
            self._docks.pop(idx)
            self._panels.pop(idx)
        self._rebuild_chart_tabs()

    def _activate_dock(self, dock: QDockWidget):
        dock.raise_()
        self._rebuild_chart_tabs()

    def _rebuild_chart_tabs(self):
        """Explicit "which chart is open" switcher row - see the comment
        where self._chart_tabs_layout is built for why this exists
        alongside (not instead of) the native dock tab bar.
        """
        while self._chart_tabs_layout.count():
            item = self._chart_tabs_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        active = self.current_chart() if self._panels else None
        for dock, panel in zip(self._docks, self._panels):
            btn = QToolButton()
            btn.setText(dock.windowTitle() or "Empty")
            btn.setCheckable(True)
            btn.setChecked(panel is active)
            btn.clicked.connect(lambda _checked=False, d=dock: self._activate_dock(d))
            self._chart_tabs_layout.addWidget(btn)

            if len(self._docks) > 1:
                # Hiding the dock's native title bar (see add_chart) also
                # hid its close (x) button - this replaces it, but only
                # once there's more than one chart open, same as the old
                # QTabWidget-based workspace never let you close its last tab.
                close_btn = QToolButton()
                close_btn.setText("×")
                close_btn.setToolTip(f"Close {dock.windowTitle() or 'Empty'}")
                close_btn.setMaximumWidth(18)
                close_btn.clicked.connect(lambda _checked=False, d=dock: d.close())
                self._chart_tabs_layout.addWidget(close_btn)

    def reset_charts(self):
        for dock in list(self._docks):
            self._dock_host.removeDockWidget(dock)
            dock.deleteLater()
        self._docks = []
        self._panels = []
        self.add_chart("AAPL")
        self._rebuild_chart_tabs()

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
