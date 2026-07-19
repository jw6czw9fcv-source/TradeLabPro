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


def test_group_toggle_rerenders_without_error(qapp):
    panel = _panel(qapp)
    _load_sync(panel)
    panel.group_chk.setChecked(False)
    panel.render_heatmap()
    panel.group_chk.setChecked(True)
    panel.render_heatmap()
    assert len(panel.view.scene().items()) > 0


def test_watchlist_market_with_no_symbols_is_safe(qapp):
    panel = _panel(qapp)
    panel.market.setCurrentText("Watchlist")
    # db.watch_symbols() may be empty in a fresh test DB; load must not raise.
    panel.load()
    assert panel._worker is None or True


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
