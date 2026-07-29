"""Headless smoke tests for the Trade Journal UI panel."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(qapp, tmp_path):
    from tradelab.ui.app import JournalPanel
    from tradelab.ui.chart_widget import ChartWorkspace
    from tradelab.core.config import ScannerConfig
    from tradelab.core.journal import Journal
    panel = JournalPanel(ChartWorkspace(), ScannerConfig())
    panel.journal = Journal(tmp_path / "journal.json")   # isolate from real data
    panel.refresh()
    return panel


def test_panel_constructs_with_disclaimer(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    texts = " ".join(lbl.text() for lbl in panel.findChildren(QLabel))
    assert "practice tool only" in texts.lower()


def test_add_trade_populates_table(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.f_symbol.setText("aapl")
    panel.f_side.setCurrentText("Long")
    panel.f_qty.setValue(10)
    panel.f_entry.setValue(100.0)
    panel.f_stop.setValue(90.0)
    panel.f_strategy.setText("breakout")
    panel.add_trade()
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 0).text() == "AAPL"
    assert len(panel.journal.all()) == 1


def test_add_trade_requires_symbol(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.f_symbol.setText("")
    panel.add_trade()
    assert panel.table.rowCount() == 0


def test_close_updates_stats(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    panel = _panel(qapp, tmp_path)
    panel.f_symbol.setText("AAPL"); panel.f_qty.setValue(10); panel.f_entry.setValue(100.0)
    panel.add_trade()
    panel.table.selectRow(0)
    # Stub the exit-price dialog.
    monkeypatch.setattr(appmod.QInputDialog, "getDouble", staticmethod(lambda *a, **k: (120.0, True)))
    panel.close_selected()
    entry = panel.journal.all()[0]
    assert entry.exit_price == 120.0 and entry.pnl == 200.0
    assert "Win rate" in panel.stats_label.text()


def test_import_from_paper_trading(qapp, tmp_path, monkeypatch):
    import json
    from tradelab.ui import app as appmod
    # Point DATA_DIR's paper_account.json at a temp file with two round trips.
    paper = tmp_path / "paper_account.json"
    paper.write_text(json.dumps({"orders": [
        {"symbol": "AAPL", "side": "BUY", "filled_qty": 10, "filled_price": 100.0, "filled_at": 1, "status": "FILLED"},
        {"symbol": "AAPL", "side": "SELL", "filled_qty": 10, "filled_price": 120.0, "filled_at": 2, "status": "FILLED"},
    ]}))
    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path)
    panel = _panel(qapp, tmp_path)
    panel.import_paper()
    assert panel.table.rowCount() == 1
    assert panel.journal.all()[0].pnl == 200.0


def test_import_from_ibkr_csv(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    csv_path = tmp_path / "ibkr.csv"
    csv_path.write_text(
        "Symbol,DateTime,Quantity,TradePrice,Buy/Sell\n"
        "AAPL,2024-01-02,10,100.0,BUY\n"
        "AAPL,2024-01-05,10,120.0,SELL\n", encoding="utf-8")
    panel = _panel(qapp, tmp_path)
    monkeypatch.setattr(appmod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(csv_path), "")))
    panel.import_ibkr()
    assert panel.table.rowCount() == 1
    assert panel.journal.all()[0].pnl == 200.0


def test_table_shows_entry_and_exit_dates(qapp, tmp_path):
    # Regression: imported trades carried dates but the table had no date
    # columns, so they looked like they had none.
    from tradelab.core.journal import JournalEntry
    panel = _panel(qapp, tmp_path)
    e = JournalEntry(symbol="AAPL", qty=10, entry_price=100.0, entry_date="2026-01-26")
    e.close(120.0, "2026-02-05")
    panel.journal.add(e)
    panel.refresh()
    headers = [panel.table.horizontalHeaderItem(i).text() for i in range(panel.table.columnCount())]
    assert "Entry date" in headers and "Exit date" in headers and "Days" in headers
    row = {h: panel.table.item(0, i).text() for i, h in enumerate(headers)}
    assert row["Entry date"] == "2026-01-26"
    assert row["Exit date"] == "2026-02-05"
    assert row["Days"] == "10"


def test_table_sorts_newest_first(qapp, tmp_path):
    from tradelab.core.journal import JournalEntry
    panel = _panel(qapp, tmp_path)
    panel.journal.add(JournalEntry(symbol="OLD", qty=1, entry_price=1, entry_date="2025-01-01"))
    panel.journal.add(JournalEntry(symbol="NEW", qty=1, entry_price=1, entry_date="2026-06-01"))
    panel.refresh()
    assert panel.table.item(0, 0).text() == "NEW"


def test_clicking_header_sorts_by_value_not_text(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from tradelab.core.journal import JournalEntry
    panel = _panel(qapp, tmp_path)
    # Quantities 2 / 10 / 100 sort wrong lexicographically ("10" < "2").
    for sym, qty in [("A", 2), ("B", 10), ("C", 100)]:
        panel.journal.add(JournalEntry(symbol=sym, qty=qty, entry_price=1.0))
    panel.refresh()
    headers = [panel.table.horizontalHeaderItem(i).text() for i in range(panel.table.columnCount())]
    qty_col = headers.index("Qty")
    panel.table.sortItems(qty_col, Qt.AscendingOrder)
    order = [panel.table.item(r, 0).text() for r in range(panel.table.rowCount())]
    assert order == ["A", "B", "C"]
    panel.table.sortItems(qty_col, Qt.DescendingOrder)
    order = [panel.table.item(r, 0).text() for r in range(panel.table.rowCount())]
    assert order == ["C", "B", "A"]


def test_refresh_keeps_the_users_chosen_sort(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from tradelab.core.journal import JournalEntry
    panel = _panel(qapp, tmp_path)
    for sym, qty in [("A", 2), ("B", 10)]:
        panel.journal.add(JournalEntry(symbol=sym, qty=qty, entry_price=1.0))
    panel.refresh()
    headers = [panel.table.horizontalHeaderItem(i).text() for i in range(panel.table.columnCount())]
    qty_col = headers.index("Qty")
    panel.table.sortItems(qty_col, Qt.DescendingOrder)
    panel.refresh()                       # e.g. after an import
    h = panel.table.horizontalHeader()
    assert h.sortIndicatorSection() == qty_col
    assert h.sortIndicatorOrder() == Qt.DescendingOrder
    assert panel.table.item(0, 0).text() == "B"      # still biggest-qty first


def test_flex_import_done_handler_adds_trades(qapp, tmp_path):
    # Drive the worker's completion path directly with parsed fills (no network).
    panel = _panel(qapp, tmp_path)
    fills = [
        {"symbol": "AAPL", "side": "BUY", "filled_qty": 10, "filled_price": 100.0, "filled_at": 1, "status": "FILLED"},
        {"symbol": "AAPL", "side": "SELL", "filled_qty": 10, "filled_price": 120.0, "filled_at": 2, "status": "FILLED"},
    ]
    panel._on_flex_done(fills, "")
    assert panel.table.rowCount() == 1
    assert panel.journal.all()[0].pnl == 200.0


def test_flex_import_done_handler_reports_error(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel._on_flex_done([], "IBKR Flex error 1015: Token has expired")
    assert panel.table.rowCount() == 0
    assert "1015" in panel.status.text()


def test_flex_credentials_persist_via_injected_settings(qapp, tmp_path):
    # The Save path writes token + query id to a settings store (injected here
    # so the real QSettings / user's saved token is never touched).
    class _FakeSettings:
        def __init__(self): self.store = {}
        def setValue(self, k, v): self.store[k] = v
        def value(self, k, default=None): return self.store.get(k, default)

    panel = _panel(qapp, tmp_path)
    fake = _FakeSettings()
    panel._save_flex_credentials("TOKEN123", "999", settings=fake)
    assert fake.store["ibkr/flex_token"] == "TOKEN123"
    assert fake.store["ibkr/flex_query"] == "999"


def test_breakdown_by_strategy(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    panel = _panel(qapp, tmp_path)
    for strat, exit_ in [("breakout", 120.0), ("fade", 90.0)]:
        panel.f_symbol.setText("AAPL"); panel.f_qty.setValue(10); panel.f_entry.setValue(100.0)
        panel.f_strategy.setText(strat); panel.add_trade()
        panel.table.selectRow(0)   # newest trade sorts first
        monkeypatch.setattr(appmod.QInputDialog, "getDouble", staticmethod(lambda *a, **k: (exit_, True)))
        panel.close_selected()
    panel.group_by.setCurrentText("Strategy")
    panel._refresh_breakdown()
    groups = [panel.breakdown.item(r, 0).text() for r in range(panel.breakdown.rowCount())]
    assert "breakout" in groups and "fade" in groups
