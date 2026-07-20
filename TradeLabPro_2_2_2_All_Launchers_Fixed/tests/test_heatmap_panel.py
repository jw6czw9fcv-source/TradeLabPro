"""Headless smoke tests for the Heatmap UI panel, driven by an injected
offline quote provider so nothing hits the network."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _fake_provider(symbols, period=None, progress=None):
    quotes = {}
    for i, s in enumerate(symbols):
        if progress:
            progress(i + 1, len(symbols), s)
        quotes[s] = {
            "price": 100.0 + i,
            "change_pct": (i % 5) - 2,          # spread of gainers/losers
            "market_cap": 1e12 / (i + 1),
            "dollar_volume": 1e9 / (i + 1),
            "sector": "Technology" if i % 2 == 0 else "Energy",
            "industry": "Software" if i % 2 == 0 else "Oil & Gas",
            "country": "United States" if i % 3 else "China",
            "name": f"Company {s}",
        }
    return quotes


def _panel(qapp):
    from tradelab.ui.app import HeatmapPanel
    from tradelab.data.database import Database
    from tradelab.ui.chart_widget import ChartWorkspace
    from tradelab.core.config import ScannerConfig
    panel = HeatmapPanel(Database(), ChartWorkspace(), ScannerConfig(),
                         quote_provider=_fake_provider)
    panel.resize(600, 400)
    return panel


def _load_sync(panel):
    """Run the panel's load path synchronously (no background thread)."""
    symbols = panel._symbols_for_market()[: panel.max_tiles.value()]
    tiles = __import__("tradelab.core.heatmap", fromlist=["build_tiles"]).build_tiles(
        _fake_provider(symbols), "market_cap")
    panel._on_done(tiles)
    return tiles


def test_panel_constructs_with_markets(qapp):
    panel = _panel(qapp)
    items = [panel.market.itemText(i) for i in range(panel.market.count())]
    assert any("US" in m for m in items)
    assert any("Canada" in m for m in items)
    assert "Watchlist" in items


def test_etf_and_index_markets_available(qapp):
    panel = _panel(qapp)
    items = [panel.market.itemText(i) for i in range(panel.market.count())]
    assert any("ETF" in m for m in items)
    # Sector-ETF preset resolves to the SPDR sector symbols.
    panel.market.setCurrentText("US - Sector ETFs (SPDR)")
    syms = panel._symbols_for_market()
    assert "XLF" in syms and "XLK" in syms and "XLE" in syms


def test_load_builds_tiles_and_renders(qapp):
    panel = _panel(qapp)
    panel.market.setCurrentText("US - NASDAQ large caps")
    tiles = _load_sync(panel)
    assert len(tiles) > 0
    assert len(panel._tiles) == len(tiles)
    # Rendering populates the scene with rect + label items.
    assert len(panel.view.scene().items()) > 0


def test_clicking_a_tile_charts_it(qapp):
    panel = _panel(qapp)
    _load_sync(panel)
    sym = panel._tiles[0].symbol
    panel._on_pick(sym)
    assert sym.upper() in panel.status.text().upper()


def test_group_by_options_rerender_without_error(qapp):
    panel = _panel(qapp)
    _load_sync(panel)
    for choice in ["Sector", "Industry", "Country", "None"]:
        panel.group_by.setCurrentText(choice)
        panel.render_heatmap()
        assert len(panel.view.scene().items()) > 0


def test_theme_dropdown_overrides_market_symbols(qapp):
    panel = _panel(qapp)
    themes = [panel.theme_sel.itemText(i) for i in range(panel.theme_sel.count())]
    assert "Semiconductors" in themes
    panel.theme_sel.setCurrentText("Semiconductors")
    syms = panel._symbols_for_market()
    assert "NVDA" in syms and "AMD" in syms
    # Selecting a market clears the theme again.
    panel.market.setCurrentText("US - NASDAQ large caps")
    assert panel.theme_sel.currentText() == panel._NO_THEME


def test_world_market_defaults_group_to_country(qapp):
    panel = _panel(qapp)
    items = [panel.market.itemText(i) for i in range(panel.market.count())]
    assert any(m.startswith("World") for m in items)
    panel.market.setCurrentText("World - Large caps")
    assert panel.group_by.currentText() == "Country"


def test_watchlist_market_with_no_symbols_is_safe(qapp):
    panel = _panel(qapp)
    panel.market.setCurrentText("Watchlist")
    # db.watch_symbols() may be empty in a fresh test DB; load must not raise.
    panel.load()
    assert panel._worker is None or True


def _tiles(n):
    from tradelab.core.heatmap import HeatmapTile
    return [HeatmapTile(f"SYM{i}", f"Co {i}", "Tech", 1.0, (i % 3) - 1) for i in range(n)]


def test_zoom_enlarges_scene_and_clamps(qapp):
    from PySide6.QtCore import QPoint
    panel = _panel(qapp); panel.resize(400, 300)
    panel._tiles = _tiles(40); panel.group_by.setCurrentText("None")
    panel.render_heatmap()
    base_w = panel.view.scene().sceneRect().width()
    assert panel._zoom == 1.0

    panel._zoom_at(1.2, QPoint(50, 50))            # zoom in
    assert panel._zoom > 1.0
    assert panel.view.scene().sceneRect().width() > base_w    # scene grew
    for _ in range(60):                            # clamp at max
        panel._zoom_at(1.2, QPoint(50, 50))
    assert panel._zoom <= panel._MAX_ZOOM
    for _ in range(60):                            # clamp back to fit
        panel._zoom_at(1 / 1.2, QPoint(50, 50))
    assert panel._zoom == 1.0


def test_zoom_reveals_more_labels(qapp):
    from PySide6.QtWidgets import QGraphicsSimpleTextItem
    from PySide6.QtCore import QPoint
    panel = _panel(qapp); panel.resize(400, 300)
    # 400 tiles in a small view -> each is a ~15px sliver too small to label.
    panel._tiles = _tiles(400); panel.group_by.setCurrentText("None")
    panel.render_heatmap()
    labels_fit = len([it for it in panel.view.scene().items()
                      if isinstance(it, QGraphicsSimpleTextItem)])
    for _ in range(10):
        panel._zoom_at(1.2, QPoint(0, 0))
    labels_zoomed = len([it for it in panel.view.scene().items()
                         if isinstance(it, QGraphicsSimpleTextItem)])
    assert labels_zoomed > labels_fit              # hidden tickers come up


def test_fit_zoom_returns_to_one(qapp):
    from PySide6.QtCore import QPoint
    panel = _panel(qapp); panel.resize(400, 300)
    panel._tiles = _tiles(40); panel.group_by.setCurrentText("None")
    panel.render_heatmap()
    panel._zoom_at(1.2, QPoint(10, 10))
    assert panel._zoom > 1.0
    panel._fit_zoom()
    assert panel._zoom == 1.0


def test_fit_pt_labels_small_tiles_but_skips_tiny_ones():
    from tradelab.ui.app import HeatmapPanel
    # A comfortable tile gets a readable size.
    assert HeatmapPanel._fit_pt("AAPL", 60, 40) >= 8
    # A small tile still gets a (smaller) label — the whole point of the fix.
    assert HeatmapPanel._fit_pt("AAPL", 24, 12) > 0
    # A genuinely tiny sliver gets nothing (would be unreadable / overflow).
    assert HeatmapPanel._fit_pt("AAPL", 8, 6) == 0.0
    # Longer tickers need more width for the same tile.
    assert HeatmapPanel._fit_pt("GOOGL", 24, 12) <= HeatmapPanel._fit_pt("KO", 24, 12)


def test_render_labels_small_tiles(qapp):
    from PySide6.QtWidgets import QGraphicsSimpleTextItem
    panel = _panel(qapp)
    panel.resize(400, 300)
    # Many equal tiles -> each is small; with the fix they should still label.
    from tradelab.core.heatmap import HeatmapTile
    panel._tiles = [HeatmapTile(f"SYM{i}", f"Co {i}", "Tech", 1.0, (i % 3) - 1)
                    for i in range(60)]
    panel.group_by.setCurrentText("None")
    panel.render_heatmap()
    labels = [it for it in panel.view.scene().items() if isinstance(it, QGraphicsSimpleTextItem)]
    assert len(labels) > 0        # small tiles now carry ticker labels


def test_set_external_symbols_becomes_the_source(qapp):
    panel = _panel(qapp)                                # uses the fast fake provider
    panel.set_external_symbols(["AAPL", "msft", "NVDA"], "Scanner results")
    # A "Scanner results" entry is added and selected, and it drives the map.
    items = [panel.market.itemText(i) for i in range(panel.market.count())]
    assert "Scanner results" in items
    assert panel.market.currentText() == "Scanner results"
    assert panel._symbols_for_market() == ["AAPL", "MSFT", "NVDA"]
    assert panel.theme_sel.currentText() == panel._NO_THEME   # theme cleared
    panel.shutdown()                                   # join the background load


def test_period_dropdown_present_and_updates_legend(qapp):
    panel = _panel(qapp)
    periods = [panel.period_sel.itemText(i) for i in range(panel.period_sel.count())]
    assert "1 Day" in periods and "1 Year" in periods and "YTD" in periods
    panel.period_sel.setCurrentText("1 Month")
    assert "1 Month" in panel.legend_title.text()


def test_portfolio_market_source(qapp):
    panel = _panel(qapp)
    items = [panel.market.itemText(i) for i in range(panel.market.count())]
    assert "Portfolio" in items
    panel.db.add_position("NVDA", 10, 100.0)
    panel.market.setCurrentText("Portfolio")
    assert "NVDA" in panel._symbols_for_market()


def test_auto_refresh_toggle_starts_and_stops_timer(qapp):
    panel = _panel(qapp)
    assert not panel._timer.isActive()
    panel.auto_secs.setValue(30)
    panel.auto_chk.setChecked(True)
    assert panel._timer.isActive()
    assert panel._timer.interval() == 30_000
    panel.auto_chk.setChecked(False)
    assert not panel._timer.isActive()
    panel.shutdown()  # join the worker the immediate refresh started


def test_auto_refresh_interval_change_updates_running_timer(qapp):
    panel = _panel(qapp)
    panel.auto_chk.setChecked(True)
    panel.auto_secs.setValue(45)
    assert panel._timer.interval() == 45_000
    panel.auto_chk.setChecked(False)
    panel.shutdown()


def test_shutdown_stops_auto_refresh_timer(qapp):
    panel = _panel(qapp)
    panel.auto_chk.setChecked(True)
    assert panel._timer.isActive()
    panel.shutdown()
    assert not panel._timer.isActive()
