"""Headless smoke tests for the Paper Trading UI panel. Prices are injected on
the panel's broker, so nothing hits the network."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(qapp, **prices):
    from tradelab.ui.app import PaperTradingPanel
    panel = PaperTradingPanel()
    panel.broker._price_fn = lambda s: prices[s]
    panel.broker._persist_path = None  # don't touch disk in tests
    panel.broker.reset()
    return panel


def test_panel_constructs_with_paper_warning(qapp):
    from PySide6.QtWidgets import QLabel
    panel = _panel(qapp, AAPL=100.0)
    texts = " ".join(lbl.text() for lbl in panel.findChildren(QLabel))
    assert "PAPER TRADING" in texts
    assert "no live orders" in texts.lower() or "no real money" in texts.lower()


def test_placing_a_market_order_updates_positions_table(qapp):
    panel = _panel(qapp, AAPL=100.0)
    panel.o_symbol.setText("AAPL")
    panel.o_side.setCurrentText(panel._BUY)
    panel.o_qty.setValue(5)
    panel.o_type.setCurrentText(panel._MARKET)
    panel._place()
    assert panel.pos_table.rowCount() == 1
    assert panel.pos_table.item(0, 0).text() == "AAPL"
    assert panel.pos_table.item(0, 1).text() == "5"
    assert panel.ord_table.rowCount() == 1
    assert panel.ord_table.item(0, 6).text() == "FILLED"


def test_limit_field_enables_only_for_limit_orders(qapp):
    panel = _panel(qapp, AAPL=100.0)
    panel.o_type.setCurrentText(panel._MARKET)
    assert panel.o_limit.isEnabled() is False
    panel.o_type.setCurrentText(panel._LIMIT)
    assert panel.o_limit.isEnabled() is True


def test_summary_shows_pnl_after_a_round_trip(qapp):
    panel = _panel(qapp, AAPL=100.0)
    panel.o_qty.setValue(10)
    panel._place()                       # buy 10 @ 100
    panel.broker._price_fn = lambda s: 120.0
    panel.o_side.setCurrentText(panel._SELL)
    panel._place()                       # sell 10 @ 120 -> +200 realized
    panel.refresh()
    assert "200" in panel._summary.text()
