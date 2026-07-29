"""Headless smoke tests for the News panel."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(qapp):
    from tradelab.ui.app import NewsPanel
    return NewsPanel()


def test_panel_constructs(qapp):
    panel = _panel(qapp)
    texts = " ".join(lbl.text() for lbl in panel.findChildren(QLabel))
    assert "macro" in texts.lower()


def test_source_modes_select_the_right_symbols(qapp):
    panel = _panel(qapp)
    panel.mode.setCurrentText("Symbol")
    panel.symbol.setText("NVDA")
    assert not panel.symbol.isHidden() and panel._symbols() == ["NVDA"]
    panel.mode.setCurrentText("Market")
    assert panel.symbol.isHidden() and "SPY" in panel._symbols()
    panel.mode.setCurrentText("Sectors")
    assert not panel.sector.isHidden()
    panel.sector.setCurrentText("Energy")
    assert panel._symbols() == ["XLE"]
    panel.mode.setCurrentText("Geopolitical")
    assert "USO" in panel._symbols()
    assert not panel.macro_only.isEnabled()      # geo is inherently filtered


def test_render_flags_macro_and_opens_url(qapp, monkeypatch):
    from tradelab.core.news import NewsItem
    from tradelab.ui import app as appmod
    opened = {}
    monkeypatch.setattr(appmod.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.update(u=url.toString()) or True))
    panel = _panel(qapp)
    items = [
        NewsItem(title="Fed raises rates", publisher="Reuters", url="http://x/1",
                 published=1700000000, tickers=["SPY"]),
        NewsItem(title="Apple ships new chip", publisher="Bloomberg", url="http://x/2",
                 published=1699990000, tickers=["AAPL"]),
    ]
    panel._on_done(items)
    assert panel.table.rowCount() == 2
    assert panel.table.item(0, 2).text().startswith("⚑")     # macro flagged
    assert not panel.table.item(1, 2).text().startswith("⚑")
    panel._open_row(0, 2)
    assert opened["u"] == "http://x/1"


def test_get_news_via_injected_fetcher(qapp):
    from tradelab.ui.app import NewsPanel
    feed = {"AAPL": [{"title": "Apple news", "link": "http://a", "providerPublishTime": 1}]}
    panel = NewsPanel(fetcher=lambda sym: feed.get(sym, []))
    panel.mode.setCurrentText("Symbol")
    panel.symbol.setText("AAPL")
    panel.get_news()
    panel._worker.wait(3000)          # let the background fetch finish
    qapp.processEvents()
    assert panel.table.rowCount() == 1
    assert "Apple news" in panel.table.item(0, 2).text()
