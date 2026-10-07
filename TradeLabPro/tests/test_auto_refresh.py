"""Opening a tab brings its data up to date, if it has gone stale.

Only the tabs showing market data take part, at two speeds: intraday ones
after the threshold in Settings (15 minutes), daily ones when the day turns.
The ETF Screener stays manual by decision, and anything you run yourself -
scans, backtests, projections - is never started by a click on a tab.
"""
import pathlib
import tempfile
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QScrollArea


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def win(qapp):
    from tradelab.ui.app import (AUTO_REFRESH_KEY, AUTO_REFRESH_MINUTES_KEY,
                                 MainWindow, app_settings)
    s = app_settings()
    s.setValue(AUTO_REFRESH_KEY, True)
    s.setValue(AUTO_REFRESH_MINUTES_KEY, 15)
    s.sync()
    w = MainWindow()
    yield w
    w.close()


def _open(win, panel):
    """Switch to the tab holding `panel`, the way a click would."""
    for i in range(win.tabs.count()):
        page = win.tabs.widget(i)
        inner = page.widget() if isinstance(page, QScrollArea) else page
        if inner is panel:
            win.tabs.setCurrentIndex(1 if i == 0 else 0)     # so that it is a change
            win.tabs.setCurrentIndex(i)
            return
    raise AssertionError(f"{type(panel).__name__} is not on any tab")


def _record_refreshes(monkeypatch, panel):
    calls = []

    def fake():
        calls.append(1)
        panel.note_refresh_started()      # what the real entry method does first

    monkeypatch.setattr(panel, panel.REFRESH_METHOD, fake)
    return calls


# -- who takes part ----------------------------------------------------------------

def test_exactly_the_market_data_tabs_refresh_themselves():
    import tradelab.ui.app as app
    auto = {name for name, cls in vars(app).items()
            if isinstance(cls, type) and issubclass(cls, app.AutoRefresh)
            and cls is not app.AutoRefresh}
    assert auto == {"HomePanel", "MarketPanel", "PortfolioAnalyticsPanel",
                    "DividendsPanel", "RiskPanel", "RetirementPanel"}


@pytest.mark.parametrize("name", [
    "EtfScreenerPanel", "ScannerPanel", "BacktestPanel", "SeasonalityPanel",
    "RetirementSimPanel", "PaperTradingPanel", "CoachPanel", "AIAssistantPanel",
    "JournalPanel", "PortfolioPanel", "WatchlistPanel"])
def test_these_never_start_on_their_own(name):
    """The ETF Screener is manual by decision; the rest are things you run, or
    hold no market data at all."""
    import tradelab.ui.app as app
    assert not issubclass(getattr(app, name), app.AutoRefresh)


def test_prices_move_intraday_and_the_rest_daily():
    import tradelab.ui.app as app
    from tradelab.core import freshness
    for name in ("HomePanel", "MarketPanel", "PortfolioAnalyticsPanel"):
        assert getattr(app, name).REFRESH_POLICY == freshness.INTRADAY
    for name in ("DividendsPanel", "RiskPanel", "RetirementPanel"):
        assert getattr(app, name).REFRESH_POLICY == freshness.DAILY


# -- what opening a tab does --------------------------------------------------------

def test_opening_a_stale_tab_refreshes_it(win, monkeypatch):
    panel = win.analytics_panel
    calls = _record_refreshes(monkeypatch, panel)
    panel._refresh_started_at = None
    _open(win, panel)
    assert calls == [1]


def test_opening_a_fresh_tab_does_not(win, monkeypatch):
    panel = win.analytics_panel
    calls = _record_refreshes(monkeypatch, panel)
    panel._refresh_started_at = time.time() - 5 * 60
    _open(win, panel)
    assert calls == []


def test_coming_back_quickly_does_not_fetch_twice(win, monkeypatch):
    panel = win.dividends_panel
    calls = _record_refreshes(monkeypatch, panel)
    panel._refresh_started_at = None
    _open(win, panel)
    _open(win, panel)
    assert calls == [1]


def test_a_refresh_already_running_is_not_started_again(win, monkeypatch):
    class Busy:
        def isRunning(self):
            return True

    panel = win.analytics_panel
    calls = _record_refreshes(monkeypatch, panel)
    panel._refresh_started_at = None
    panel._worker = Busy()
    _open(win, panel)
    panel._worker = None
    assert calls == []


def test_turned_off_in_settings_nothing_refreshes(win, monkeypatch):
    from tradelab.ui.app import AUTO_REFRESH_KEY, app_settings
    s = app_settings()
    s.setValue(AUTO_REFRESH_KEY, False)
    s.sync()
    panel = win.analytics_panel
    calls = _record_refreshes(monkeypatch, panel)
    panel._refresh_started_at = None
    _open(win, panel)
    assert calls == []


def test_the_threshold_from_settings_is_the_one_used(win, monkeypatch):
    from tradelab.ui.app import AUTO_REFRESH_MINUTES_KEY, app_settings
    s = app_settings()
    s.setValue(AUTO_REFRESH_MINUTES_KEY, 60)
    s.sync()
    panel = win.analytics_panel
    calls = _record_refreshes(monkeypatch, panel)
    panel._refresh_started_at = time.time() - 30 * 60      # stale at 15, fresh at 60
    _open(win, panel)
    assert calls == []


def test_the_refresh_button_counts_too(win):
    """A click on Refresh resets the clock, so opening the tab right after does
    not fetch everything again. With no holdings it returns before any fetch."""
    panel = win.analytics_panel
    panel._refresh_started_at = None
    panel.analyze()
    assert panel._refresh_started_at is not None


# -- saying how old it is --------------------------------------------------------------

def test_a_successful_load_stamps_the_tab(win):
    panel = win.risk_panel
    assert panel.freshness_label is not None
    panel.mark_refreshed()
    assert panel.freshness_label.text().startswith("updated ")


def test_the_stamp_ages_when_you_come_back(win, monkeypatch):
    panel = win.dividends_panel
    _record_refreshes(monkeypatch, panel)
    two_hours_ago = time.time() - 2 * 3600
    if time.localtime(two_hours_ago)[:3] != time.localtime()[:3]:
        pytest.skip("too close to midnight for a same-day check")
    panel._refreshed_at = two_hours_ago
    panel._refresh_started_at = two_hours_ago             # same day: fresh for a daily tab
    _open(win, panel)
    assert panel.freshness_label.text().startswith("as of ")


# -- the setting -------------------------------------------------------------------------

def test_the_setting_is_saved(qapp):
    from tradelab.data.database import Database
    from tradelab.ui.app import SettingsPanel, app_settings, auto_refresh_settings
    panel = SettingsPanel(Database(path=pathlib.Path(tempfile.mkdtemp()) / "s.db"))
    panel.auto_refresh_minutes.setValue(30)
    panel.auto_refresh.setChecked(False)
    assert auto_refresh_settings(app_settings()) == (False, 30)
    assert not panel.auto_refresh_minutes.isEnabled()
    panel.auto_refresh.setChecked(True)
    assert auto_refresh_settings(app_settings()) == (True, 30)
