"""The Heatmap tab: a market as a treemap."""
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

        self.status = StatusLabel("Pick a market and click Load map.")
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
                flag_problem(self.status, f"Could not add {symbol}: {exc}")

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
            flag_problem(self.status, f"No symbols for {src} (add some in that tab first).")
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
            flag_problem(self.status, f"Could not chart {symbol}: {exc}")

    def shutdown(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
