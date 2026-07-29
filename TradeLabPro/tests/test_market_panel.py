"""UI-level smoke tests for the Phase 3 MarketPanel.

get_history is monkeypatched so the dashboard refresh runs deterministically
offline - see tests/test_market.py for the underlying logic tests.
"""
import time

import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _batch_via_get_history(monkeypatch):
    """The refresh worker fetches in batches via get_histories (one multi-ticker
    request instead of a serial per-symbol loop, which used to trip Yahoo's rate
    limit). Route that batch through the per-symbol get_history each test
    patches, read at call time, so every existing monkeypatch keeps controlling
    the data - and a symbol whose fake raises still becomes a None entry, just as
    the real batch backfills a symbol the feed couldn't fill."""
    import tradelab.ui.app as app

    def get_histories(symbols, period="1y", interval="1d"):
        out = {}
        for s in dict.fromkeys(symbols):
            try:
                out[s] = app.get_history(s, period, interval)
            except Exception:
                out[s] = None
        return out

    monkeypatch.setattr(app, "get_histories", get_histories, raising=False)


def _rising(n=250, start=100.0):
    return pd.DataFrame({
        "Open": [start + i for i in range(n)],
        "High": [start + i + 1 for i in range(n)],
        "Low": [start + i - 1 for i in range(n)],
        "Close": [start + i for i in range(n)],
        "Volume": [1_000_000] * n,
    })


def test_market_panel_constructs_with_regime_and_sector_rows(qapp):
    import tradelab.ui.app as app
    from tradelab.core.market import SECTOR_ETFS

    panel = app.MarketPanel()
    assert panel.table.rowCount() == len(panel.rows)
    assert panel.sector_table.rowCount() == len(SECTOR_ETFS)


def test_refresh_market_populates_read_and_breadth(qapp, monkeypatch):
    import tradelab.ui.app as app

    # Rising series for everything except a low VIX -> should read Favorable.
    def fake_history(symbol, period, interval):
        if symbol == "^VIX":
            return pd.DataFrame({"Close": [14.0] * 250, "Open": [14.0]*250, "High": [14.0]*250, "Low": [14.0]*250, "Volume": [0]*250})
        return _rising()

    monkeypatch.setattr(app, "get_history", fake_history)
    panel = app.MarketPanel()
    _refresh(panel, qapp)

    card = panel.read_card
    assert "Favorable" in card.headline.text()
    assert "/100" in card.headline.text()
    assert card.reasons.text()   # transparent reasons populated
    assert card.summary.text()   # plain-English summary populated
    # Sector table "vs 50-day" column (index 4 now that rank/# is column 0)
    # filled in (rising series -> Above).
    assert panel.sector_table.item(0, 4).text() == "Above"
    assert "sectors up today" in panel.status.text()
    # Global indices table populated with a per-market read.
    from tradelab.core.market import GLOBAL_INDICES
    assert panel.global_table.rowCount() == len(GLOBAL_INDICES)
    assert panel.global_table.item(0, 6).text() in ("Favorable", "Neutral", "Caution")


def _fake_history(symbol, period, interval):
    if symbol == "^VIX":
        return pd.DataFrame({"Close": [14.0] * 250, "Open": [14.0]*250,
                             "High": [14.0]*250, "Low": [14.0]*250, "Volume": [0]*250})
    return _rising()


def test_the_whole_tab_follows_the_country_selector(qapp, monkeypatch):
    """One selector at the top drives the read, the regime rows and the
    sectors - nothing on screen may mix the two markets."""
    import tradelab.ui.app as app
    from tradelab.core.market import regime_rows, sector_instruments

    monkeypatch.setattr(app, "get_history", _fake_history)
    panel = app.MarketPanel()

    assert panel.current_region() == "US"
    assert panel.sector_table.rowCount() == 11
    assert panel.sector_table.horizontalHeaderItem(6).text() == "RS vs SPY"
    assert [r[1] for r in panel.rows] == [r[1] for r in regime_rows("US")]
    _refresh(panel, qapp)
    assert "US" in panel.read_box.title()

    panel.country_combo.setCurrentText("Canada")
    _refresh(panel, qapp)
    assert panel.current_region() == "Canada"
    # Regime rows swapped to the Canadian set (loonie, banks, TSX).
    symbols = [r[1] for r in panel.rows]
    assert symbols == [r[1] for r in regime_rows("Canada")]
    assert "CAD=X" in symbols and "QQQ" not in symbols
    # Canada now shows all 11 sectors, same names as the US and the Scanner.
    assert panel.sector_table.rowCount() == 11
    assert panel.sector_table.horizontalHeaderItem(6).text() == "RS vs TSX"
    assert "Canada" in panel.read_box.title()
    assert "Canada breadth" in panel.status.text()
    names = {panel.sector_table.item(r, 1).text() for r in range(11)}
    assert names == {s["name"] for s in sector_instruments("Canada")}


def test_both_markets_show_the_same_eleven_sector_names(qapp):
    """The Market tab's sectors must match the Scanner's taxonomy."""
    from tradelab.core.market import sector_instruments
    from tradelab.core.sectors import region_baskets
    for region in ("US", "Canada"):
        market = [s["name"] for s in sector_instruments(region)]
        scanner = list(region_baskets(region))[:11]
        assert market == scanner


def test_canada_sectors_without_an_etf_use_a_stock_basket(qapp):
    from tradelab.core.market import sector_instruments
    by_name = {s["name"]: s for s in sector_instruments("Canada")}
    # Seven track an iShares capped-sector fund...
    assert by_name["Energy"]["etf"] == "XEG.TO"
    assert by_name["Energy"]["label"] == "XEG.TO"
    # ...the other four have no liquid TSX fund and are equal-weighted.
    for name in ("Industrials", "Consumer Discretionary",
                 "Communication Services", "Health Care"):
        spec = by_name[name]
        assert spec["etf"] is None
        assert len(spec["symbols"]) > 1
        assert "stocks" in spec["label"]
    # The US has a fund for every sector.
    assert all(s["etf"] for s in sector_instruments("US"))


def test_region_switch_before_refresh_does_not_fetch(qapp, monkeypatch):
    """Opening the tab and flipping the selector must not trigger downloads."""
    import tradelab.ui.app as app

    calls = []
    monkeypatch.setattr(app, "get_history",
                        lambda s, p, i: calls.append(s) or _rising())
    panel = app.MarketPanel()
    panel.country_combo.setCurrentText("Canada")

    assert calls == []  # nothing fetched until the user refreshes
    assert panel.sector_table.rowCount() == 11


class _FakeChart:
    """Records what got plotted, standing in for the real ChartWorkspace."""
    def __init__(self):
        self.plotted = []

    def plot(self, symbol, df, cfg):
        self.plotted.append(symbol)


class _FakeCfg:
    period = "1y"
    interval = "1d"


def _settle(panel, qapp):
    """Wait for the background chart fetch and deliver its queued signal."""
    worker = panel._chart_worker
    if worker is not None:
        worker.wait(5000)
    qapp.processEvents()


def _pump(qapp, until, timeout=20.0):
    """Deliver queued Qt signals until `until()` holds, or time out.

    A single processEvents() is not enough: the worker's done signal is queued
    from another thread, and the handler it runs may itself start more work.
    Polling here is what keeps these tests from being flaky under load.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if until():
            qapp.processEvents()
            return True
        time.sleep(0.01)
    return False


def _refresh(panel, qapp):
    """Run a dashboard refresh and wait for the background batch to land."""
    panel.refresh_market()
    worker = panel._refresh_worker
    if worker is not None:
        worker.wait(15000)
    assert _pump(qapp, lambda: panel.current_region() in panel._region_data), \
        "refresh never delivered its results"


def test_clicking_a_row_charts_that_symbol(qapp, monkeypatch):
    import tradelab.ui.app as app

    monkeypatch.setattr(app, "get_history", lambda s, p, i: _rising())
    chart = _FakeChart()
    panel = app.MarketPanel(chart, _FakeCfg())

    # Global indices: symbol is column 1. Row 0 is the first market to open.
    panel._chart_row(panel.global_table, 0, 1)
    _settle(panel, qapp)
    assert chart.plotted == ["^N225"]

    # Regime symbols: symbol is column 1 (row 0 is the VIX).
    panel._chart_row(panel.table, 0, 1)
    _settle(panel, qapp)
    assert chart.plotted[-1] == "^VIX"

    # Sectors: the ETF is column 2.
    from tradelab.core.market import SECTOR_ETFS
    panel._chart_row(panel.sector_table, 0, 2)
    _settle(panel, qapp)
    assert chart.plotted[-1] in {t for _, t in SECTOR_ETFS}
    assert "Charted" in panel.status.text()


def test_refresh_never_fetches_on_the_ui_thread(qapp, monkeypatch):
    """Refresh downloads ~37 symbols; doing that inline froze the window."""
    import threading
    import tradelab.ui.app as app

    release = threading.Event()
    fetch_threads = set()

    def slow_history(symbol, period, interval):
        fetch_threads.add(threading.current_thread().name)
        release.wait(5)
        return _rising()

    monkeypatch.setattr(app, "get_history", slow_history)
    panel = app.MarketPanel()

    panel.refresh_market()                     # must return immediately
    assert "Refreshing" in panel.status.text()
    assert not panel.progress.isHidden()
    assert not panel.refresh_btn.isEnabled()   # no double-refresh while running
    release.set()

    panel._refresh_worker.wait(15000)
    qapp.processEvents()
    assert fetch_threads and threading.main_thread().name not in fetch_threads
    assert panel.refresh_btn.isEnabled()
    assert panel.progress.isHidden()


def test_refresh_fetches_each_symbol_once(qapp, monkeypatch):
    """SPY is both a regime row and the US benchmark - fetch it a single time.
    One refresh covers BOTH markets so switching country afterwards needs no
    download, so the Canadian symbols are in the batch too."""
    import tradelab.ui.app as app

    calls = []
    monkeypatch.setattr(app, "get_history",
                        lambda s, p, i: calls.append(s) or _rising())
    panel = app.MarketPanel()
    symbols = panel.required_symbols()
    assert len(symbols) == len(set(symbols)), "required symbols must be de-duplicated"
    # Both markets are downloaded in one refresh (US and Canada instruments).
    assert "SPY" in symbols and "XLK" in symbols
    assert "XIC.TO" in symbols and "XEG.TO" in symbols

    _refresh(panel, qapp)
    assert sorted(calls) == sorted(symbols)


def test_refresh_survives_a_dead_symbol_without_a_worker_crash(qapp, monkeypatch):
    import tradelab.ui.app as app

    def flaky(symbol, period, interval):
        if symbol == "^HSI":
            raise RuntimeError("network blip")
        return _rising()

    monkeypatch.setattr(app, "get_history", flaky)
    panel = app.MarketPanel()
    _refresh(panel, qapp)

    # The dead index shows no data, every other row still rendered.
    hsi = next(r for r in range(panel.global_table.rowCount())
               if panel.global_table.item(r, 1).text() == "^HSI")
    assert panel.global_table.item(hsi, 2).text() == "—"
    assert "/100" in panel.read_card.headline.text()


def test_clicking_never_fetches_on_the_ui_thread(qapp, monkeypatch):
    """The click handler must return before the (slow) download finishes -
    that blocking call is what froze the window and spun the cursor."""
    import threading
    import tradelab.ui.app as app

    release = threading.Event()
    fetch_threads = []

    def slow_history(symbol, period, interval):
        fetch_threads.append(threading.current_thread().name)
        release.wait(5)
        return _rising()

    monkeypatch.setattr(app, "get_history", slow_history)
    panel = app.MarketPanel(_FakeChart(), _FakeCfg())

    panel._chart_row(panel.global_table, 0, 1)   # returns immediately
    assert "Loading" in panel.status.text()
    release.set()
    _settle(panel, qapp)

    assert fetch_threads and all(n != threading.main_thread().name for n in fetch_threads)


def test_refresh_populates_the_cache_so_clicks_need_no_fetch(qapp, monkeypatch):
    import tradelab.ui.app as app

    calls = []

    def counted(symbol, period, interval):
        calls.append(symbol)
        if symbol == "^VIX":
            return pd.DataFrame({"Close": [14.0]*250, "Open": [14.0]*250,
                                 "High": [14.0]*250, "Low": [14.0]*250, "Volume": [0]*250})
        return _rising()

    monkeypatch.setattr(app, "get_history", counted)
    chart = _FakeChart()
    panel = app.MarketPanel(chart, _FakeCfg())
    _refresh(panel, qapp)

    calls.clear()
    panel._chart_row(panel.global_table, 0, 1)   # already downloaded by refresh
    assert chart.plotted[-1] == "^N225"
    assert calls == [], "clicking a refreshed row must not refetch"
    assert panel._chart_worker is None           # charted straight from cache


def test_a_newer_click_supersedes_an_older_one(qapp, monkeypatch):
    """Clicking several rows quickly must not plot a stale, late-arriving one."""
    import tradelab.ui.app as app

    monkeypatch.setattr(app, "get_history", lambda s, p, i: _rising())
    chart = _FakeChart()
    panel = app.MarketPanel(chart, _FakeCfg())

    panel._pending_symbol = "^HSI"               # pretend a later click happened
    panel._on_history_loaded("^N225", _rising(), "")
    assert chart.plotted == []                   # stale result dropped


def test_clicking_a_canadian_sector_charts_the_tsx_etf(qapp, monkeypatch):
    import tradelab.ui.app as app
    from tradelab.core.market import CANADA_SECTOR_ETFS

    monkeypatch.setattr(app, "get_history", lambda s, p, i: _rising())
    chart = _FakeChart()
    panel = app.MarketPanel(chart, _FakeCfg())
    panel.country_combo.setCurrentText("Canada")

    panel._chart_row(panel.sector_table, 0, 2)
    _settle(panel, qapp)
    assert chart.plotted[-1] in {t for _, t in CANADA_SECTOR_ETFS}
    assert chart.plotted[-1].endswith(".TO")


def test_chart_click_reports_failure_without_raising(qapp, monkeypatch):
    import tradelab.ui.app as app

    def boom(symbol, period, interval):
        raise RuntimeError("no data")

    monkeypatch.setattr(app, "get_history", boom)
    panel = app.MarketPanel(_FakeChart(), _FakeCfg())
    panel._chart_row(panel.global_table, 0, 1)  # must not raise
    _settle(panel, qapp)
    assert "Could not chart" in panel.status.text()


def test_chart_click_is_inert_without_a_chart(qapp, monkeypatch):
    """The panel stays constructible (and clickable) with no chart wired."""
    import tradelab.ui.app as app

    monkeypatch.setattr(app, "get_history", lambda s, p, i: _rising())
    panel = app.MarketPanel()
    panel._chart_row(panel.global_table, 0, 1)  # must not raise


def test_refresh_market_survives_a_failing_symbol(qapp, monkeypatch):
    import tradelab.ui.app as app

    def flaky_history(symbol, period, interval):
        if symbol == "XLK":
            raise RuntimeError("network blip")
        return _rising()

    monkeypatch.setattr(app, "get_history", flaky_history)
    panel = app.MarketPanel()
    _refresh(panel, qapp)  # must not raise

    # The failing sector (Technology / XLK) falls back to a neutral, no-data
    # row instead of breaking the refresh, and the panel still produces a read.
    from tradelab.core.market import SECTOR_ETFS
    assert panel.sector_table.rowCount() == len(SECTOR_ETFS)
    tech_row = next(r for r in range(panel.sector_table.rowCount())
                    if panel.sector_table.item(r, 2).text() == "XLK")
    assert panel.sector_table.item(tech_row, 3).text() == "—"  # no change data
    assert "/100" in panel.read_card.headline.text()


def test_clicking_a_basket_sector_charts_a_real_symbol(qapp, monkeypatch):
    """A sector with no ETF shows "6 stocks" in the instrument column - that
    is a description, not something you can chart, so the cell carries its
    lead constituent instead."""
    import tradelab.ui.app as app
    from tradelab.core.market import sector_instruments

    monkeypatch.setattr(app, "get_history", _fake_history)
    chart = _FakeChart()
    panel = app.MarketPanel(chart, _FakeCfg())
    panel.country_combo.setCurrentText("Canada")

    basket = next(s for s in sector_instruments("Canada") if s["etf"] is None)
    row = next(r for r in range(panel.sector_table.rowCount())
               if panel.sector_table.item(r, 1).text() == basket["name"])
    assert "stocks" in panel.sector_table.item(row, 2).text()

    panel._chart_row(panel.sector_table, row, 2)
    _settle(panel, qapp)
    assert chart.plotted == [basket["symbols"][0]]
    assert chart.plotted[0].endswith(".TO")


def test_refresh_caches_both_markets(qapp, monkeypatch):
    """A single refresh downloads and scores BOTH markets, so switching country
    afterwards is an instant re-render with no second download."""
    import tradelab.ui.app as app

    monkeypatch.setattr(app, "get_history", _fake_history)
    panel = app.MarketPanel()
    _refresh(panel, qapp)
    assert set(panel._region_data) == {"US", "Canada"}


def test_switching_country_after_a_refresh_fetches_nothing(qapp, monkeypatch):
    """The whole point: both markets stay in memory, so the switch is a pure
    re-render with no downloads."""
    import tradelab.ui.app as app

    calls = []

    def counted(symbol, period, interval):
        calls.append(symbol)
        return _fake_history(symbol, period, interval)

    monkeypatch.setattr(app, "get_history", counted)
    panel = app.MarketPanel()
    _refresh(panel, qapp)

    calls.clear()
    panel.country_combo.setCurrentText("Canada")
    assert calls == [], "switching to a cached market must not refetch"
    assert panel.sector_table.item(0, 7).text()          # sectors already scored
    assert "/100" in panel.read_card.headline.text()     # read already scored
    assert panel.table.item(0, 3).text() != "—"          # regime rows filled in

    calls.clear()
    panel.country_combo.setCurrentText("US")
    assert calls == [], "switching back must not refetch either"
    assert "/100" in panel.read_card.headline.text()


def test_switching_country_shows_that_markets_regime_values(qapp, monkeypatch):
    """Each market's cached regime rows come back with it, not the other's."""
    import tradelab.ui.app as app
    from tradelab.core.market import regime_rows

    monkeypatch.setattr(app, "get_history", _fake_history)
    panel = app.MarketPanel()
    _refresh(panel, qapp)

    panel.country_combo.setCurrentText("Canada")
    shown = [panel.table.item(r, 1).text() for r in range(panel.table.rowCount())]
    assert shown == [sym for _, sym, _ in regime_rows("Canada")]
    assert all(panel.table.item(r, 2).text() != "—" for r in range(panel.table.rowCount()))


def test_global_indices_survive_a_country_switch(qapp, monkeypatch):
    """Regression: the global-indices table is region-independent and must keep
    its values when the country selector flips. It used to be blanked by the
    switch (populate_static rebuilt it empty) and never refilled, since the
    switch path only redraws the region-specific tables."""
    import tradelab.ui.app as app
    from tradelab.core.market import GLOBAL_INDICES

    monkeypatch.setattr(app, "get_history", _fake_history)
    panel = app.MarketPanel()
    _refresh(panel, qapp)

    def globals_filled():
        # Every global index shows a Last price (col 2), not the empty scaffold.
        return all(panel.global_table.item(r, 2).text() not in ("", "—")
                   for r in range(len(GLOBAL_INDICES)))

    assert globals_filled(), "globals should fill on refresh"
    panel.country_combo.setCurrentText("Canada")
    assert globals_filled(), "globals must not blank when switching to Canada"
    panel.country_combo.setCurrentText("US")
    assert globals_filled(), "globals must not blank when switching back to US"


def test_breadth_card_populates_and_highlights_pct_above_200(qapp, monkeypatch):
    """The advance/decline breadth card fills in on refresh, with the
    % above the 200-day average as its headline number."""
    import tradelab.ui.app as app

    monkeypatch.setattr(app, "get_history", _fake_history)  # all rising -> broad
    panel = app.MarketPanel()
    _refresh(panel, qapp)

    # Rising series for every constituent -> ~100% above the 200-day.
    assert panel.breadth_card.pct200.text() == "100%"
    assert "advancing" in panel.breadth_card.ad.text()
    assert "50-day" in panel.breadth_card.pct50.text()
    assert "large-cap stocks" in panel.breadth_card.sample.text()
    # Broad breadth is named in the read reasons.
    assert any("200-day avg" in r for r in panel._region_data["US"]["read"]["reasons"])


def test_breadth_follows_the_country_selector(qapp, monkeypatch):
    import tradelab.ui.app as app

    monkeypatch.setattr(app, "get_history", _fake_history)
    panel = app.MarketPanel()
    _refresh(panel, qapp)

    us_sample = panel.breadth_card.sample.text()
    panel.country_combo.setCurrentText("Canada")
    assert panel.breadth_card.sample.text()           # repopulated from cache
    # Canada's breadth is scored on Canadian names, cached separately.
    assert "Canada" in panel.read_box.title()
    assert panel._region_data["Canada"]["stock_breadth"]["total"] > 0


def test_refresh_includes_breadth_constituents(qapp, monkeypatch):
    import tradelab.ui.app as app
    from tradelab.core.market import breadth_universe

    monkeypatch.setattr(app, "get_history", _fake_history)
    panel = app.MarketPanel()
    symbols = set(panel.required_symbols())
    for name in breadth_universe("US")[:5]:
        assert name in symbols
