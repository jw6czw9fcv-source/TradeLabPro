"""UI-level smoke tests for the Phase 3 MarketPanel.

get_history is monkeypatched so the dashboard refresh runs deterministically
offline - see tests/test_market.py for the underlying logic tests.
"""
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


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

    us = panel.read_cards["US"]
    assert "Favorable" in us.headline.text()
    assert "/100" in us.headline.text()
    assert us.reasons.text()   # transparent reasons populated
    assert us.summary.text()   # plain-English summary populated
    # Canada is scored on the same refresh, without touching the dropdown.
    assert "/100" in panel.read_cards["Canada"].headline.text()
    # Sector table "vs 50-day" column (index 4 now that rank/# is column 0)
    # filled in (rising series -> Above).
    assert panel.sector_table.item(0, 4).text() == "Above"
    assert "sectors up today" in panel.status.text()
    # Global indices table populated with a per-market read.
    from tradelab.core.market import GLOBAL_INDICES
    assert panel.global_table.rowCount() == len(GLOBAL_INDICES)
    assert panel.global_table.item(0, 6).text() in ("Favorable", "Neutral", "Caution")


def test_sector_region_dropdown_switches_us_to_canada(qapp, monkeypatch):
    import tradelab.ui.app as app
    from tradelab.core.market import SECTOR_ETFS, CANADA_SECTOR_ETFS

    requested = []

    def fake_history(symbol, period, interval):
        requested.append(symbol)
        if symbol == "^VIX":
            return pd.DataFrame({"Close": [14.0] * 250, "Open": [14.0]*250,
                                 "High": [14.0]*250, "Low": [14.0]*250, "Volume": [0]*250})
        return _rising()

    monkeypatch.setattr(app, "get_history", fake_history)
    panel = app.MarketPanel()

    # Defaults to the US SPDR sectors, benchmarked against SPY.
    assert panel.current_region() == "US"
    assert panel.sector_table.rowCount() == len(SECTOR_ETFS)
    assert panel.sector_table.horizontalHeaderItem(6).text() == "RS vs SPY"

    _refresh(panel, qapp)
    # One refresh scores BOTH markets, fetching each benchmark and sector set.
    assert "XIC.TO" in requested          # Canadian benchmark
    assert "XEG.TO" in requested          # Canadian sectors
    assert panel.read_cards["US"].headline.text()
    assert panel.read_cards["Canada"].headline.text()

    # Switching to Canada re-ranks the TSX sector ETFs against the TSX, and is
    # a pure re-render from cache - no further downloads.
    requested.clear()
    panel.region_combo.setCurrentText("Canada")
    assert panel.current_region() == "Canada"
    assert requested == [], "switching market must not refetch"
    assert panel.sector_table.rowCount() == len(CANADA_SECTOR_ETFS)
    assert panel.sector_table.horizontalHeaderItem(6).text() == "RS vs TSX"
    etfs = {panel.sector_table.item(r, 2).text() for r in range(panel.sector_table.rowCount())}
    assert etfs == {t for _, t in CANADA_SECTOR_ETFS}
    assert "Canada breadth" in panel.status.text()


def test_region_switch_before_refresh_does_not_fetch(qapp, monkeypatch):
    """Opening the tab and flipping the dropdown must not trigger downloads."""
    import tradelab.ui.app as app
    from tradelab.core.market import CANADA_SECTOR_ETFS

    calls = []
    monkeypatch.setattr(app, "get_history",
                        lambda s, p, i: calls.append(s) or _rising())
    panel = app.MarketPanel()
    panel.region_combo.setCurrentText("Canada")

    assert calls == []  # nothing fetched until the user refreshes
    assert panel.sector_table.rowCount() == len(CANADA_SECTOR_ETFS)


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


def _refresh(panel, qapp):
    """Run a dashboard refresh and wait for the background batch to land."""
    panel.refresh_market()
    worker = panel._refresh_worker
    if worker is not None:
        worker.wait(15000)
    qapp.processEvents()


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
    """SPY is both a regime row and the US benchmark - fetch it a single time."""
    import tradelab.ui.app as app

    calls = []
    monkeypatch.setattr(app, "get_history",
                        lambda s, p, i: calls.append(s) or _rising())
    panel = app.MarketPanel()
    symbols = panel.required_symbols()
    assert len(symbols) == len(set(symbols)), "required symbols must be de-duplicated"
    assert "SPY" in symbols and "XIC.TO" in symbols

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
    assert "/100" in panel.read_cards["US"].headline.text()


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
    panel.region_combo.setCurrentText("Canada")

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
    assert "/100" in panel.read_cards["US"].headline.text()
