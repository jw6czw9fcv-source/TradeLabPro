"""Headless smoke tests for the Settings panel (data-source selector)."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tradelab.data import providers
import tradelab.data.market_data as market_data


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_provider():
    providers.set_active(providers.DEFAULT)
    yield
    providers.set_active(providers.DEFAULT)
    market_data._quote_meta_cache.clear()


def _panel(qapp, tmp_path):
    from tradelab.ui.app import SettingsPanel
    from tradelab.data.database import Database
    from PySide6.QtCore import QSettings
    # Isolated settings file so the test never touches the real registry.
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    return SettingsPanel(Database(tmp_path / "s.db"), settings=settings)


def test_lists_providers_and_shows_active(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    items = [panel.source.itemText(i) for i in range(panel.source.count())]
    assert "Yahoo Finance" in items and "Offline (synthetic)" in items
    assert panel.source.currentText() == "Yahoo Finance"


def test_changing_source_switches_active_provider(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.source.setCurrentText("Offline (synthetic)")
    assert providers.active_name() == "Offline (synthetic)"
    # And it drives actual fetches now.
    m = market_data.get_quote_meta("ZZZZ")
    assert m["sector"] == "Unknown"


def test_description_updates_with_selection(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.source.setCurrentText("Offline (synthetic)")
    assert "no network" in panel.source_desc.text().lower()
