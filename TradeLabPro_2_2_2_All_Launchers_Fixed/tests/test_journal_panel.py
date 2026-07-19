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


def test_breakdown_by_strategy(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    panel = _panel(qapp, tmp_path)
    for strat, exit_ in [("breakout", 120.0), ("fade", 90.0)]:
        panel.f_symbol.setText("AAPL"); panel.f_qty.setValue(10); panel.f_entry.setValue(100.0)
        panel.f_strategy.setText(strat); panel.add_trade()
        panel.table.selectRow(panel.table.rowCount() - 1)
        monkeypatch.setattr(appmod.QInputDialog, "getDouble", staticmethod(lambda *a, **k: (exit_, True)))
        panel.close_selected()
    panel.group_by.setCurrentText("Strategy")
    panel._refresh_breakdown()
    groups = [panel.breakdown.item(r, 0).text() for r in range(panel.breakdown.rowCount())]
    assert "breakout" in groups and "fade" in groups
