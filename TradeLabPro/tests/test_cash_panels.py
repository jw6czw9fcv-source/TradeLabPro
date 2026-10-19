"""Cash on screen: entered on the Portfolio tab, counted on Analytics and Home,
with the date of the prices beside the totals."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tradelab.data.database import Database


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "panels.db")
    d.set_portfolio_positions("RRSP", [{"symbol": "NVDA", "shares": 10, "entry_price": 240.0}])
    yield d
    d.conn.close()


def _hist(n=120, start=100.0, end="2026-10-09"):
    idx = pd.date_range(end=end, periods=n, freq="B")
    close = start * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, n)))
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close,
                         "Volume": [0] * n}, index=idx)


def test_the_portfolio_tab_sets_and_removes_cash(qapp, db):
    import tradelab.ui.app as app
    panel = app.PortfolioPanel(db)
    assert panel.cash_portfolio.currentText() == "RRSP"          # offered from the positions
    panel.cash_currency.setCurrentText("cad")
    panel.cash_amount.setValue(2500.25)
    panel.set_cash()
    assert [(c["portfolio"], c["currency"], c["amount"]) for c in db.cash()] == [
        ("RRSP", "CAD", 2500.25)]
    assert panel.cash_table.rowCount() == 1
    assert panel.cash_table.item(0, 2).text() == "2,500.25"
    panel.cash_table.selectRow(0)
    panel.delete_cash()
    assert db.cash() == [] and panel.cash_table.rowCount() == 0


def test_the_portfolio_tab_wants_a_currency_code(qapp, db):
    import tradelab.ui.app as app
    panel = app.PortfolioPanel(db)
    panel.cash_currency.setCurrentText("dollars")
    panel.cash_amount.setValue(100)
    panel.set_cash()
    assert db.cash() == []
    assert "three-letter" in panel.status.text()


def _answer_yes(monkeypatch, asked=None):
    import tradelab.ui.app as app

    def question(parent, title, text, *rest):
        if asked is not None:
            asked.append(text)
        return app.QMessageBox.Yes
    monkeypatch.setattr(app.QMessageBox, "question", staticmethod(question))


def test_an_ibkr_import_fills_the_chosen_portfolio_and_its_cash(qapp, db, monkeypatch):
    import tradelab.ui.app as app
    _answer_yes(monkeypatch)
    db.set_cash("RRSP", "USD", 99.0)                   # gone afterwards: the account holds none
    panel = app.PortfolioPanel(db)
    panel.import_portfolio.setCurrentText("RRSP")
    panel._apply_ibkr([{"symbol": "VTI", "shares": 10, "entry_price": 250.0}], "file",
                      {"CAD": 1200.25})
    assert [(p["portfolio"], p["symbol"]) for p in db.positions()] == [("RRSP", "VTI")]
    assert [(c["currency"], c["amount"]) for c in db.cash()] == [("CAD", 1200.25)]
    assert "and the cash into the 'RRSP' portfolio" in panel.status.text()


def test_a_report_without_cash_leaves_the_recorded_cash_alone(qapp, db, monkeypatch):
    import tradelab.ui.app as app
    asked = []
    _answer_yes(monkeypatch, asked)
    db.set_cash("RRSP", "CAD", 500.0)
    panel = app.PortfolioPanel(db)
    panel.import_portfolio.setCurrentText("RRSP")
    panel._apply_ibkr([{"symbol": "VTI", "shares": 10, "entry_price": 250.0}], "file", {})
    assert [(c["currency"], c["amount"]) for c in db.cash()] == [("CAD", 500.0)]
    assert "stays as it is" in asked[0]


def test_a_cash_section_that_cannot_be_read_says_so(qapp, db, monkeypatch):
    import tradelab.ui.app as app
    asked = []
    _answer_yes(monkeypatch, asked)
    db.set_cash("RRSP", "CAD", 500.0)
    panel = app.PortfolioPanel(db)
    panel.import_portfolio.setCurrentText("RRSP")
    panel._apply_ibkr([{"symbol": "VTI", "shares": 10, "entry_price": 250.0}], "file", {},
                      cash_section=True)
    assert [(c["currency"], c["amount"]) for c in db.cash()] == [("CAD", 500.0)]
    assert "could not read" in asked[0] and "ibkr_positions_last.xml" in asked[0]


def test_a_flex_fetch_keeps_the_raw_report_and_notes_the_cash_section(qapp, monkeypatch, tmp_path):
    import tradelab.core.journal as journal
    import tradelab.core.portfolio_import as pi
    import tradelab.ui.app as app
    report = ('<FlexQueryResponse><FlexStatements><FlexStatement>'
              '<OpenPositions><OpenPosition symbol="VTI" position="10" costBasisPrice="250" '
              'currency="USD" listingExchange="ARCA"/></OpenPositions>'
              '<CashReport><CashReportCurrency currency="CAD" endingCash="1200.25"/></CashReport>'
              '</FlexStatement></FlexStatements></FlexQueryResponse>')
    monkeypatch.setattr(journal, "fetch_ibkr_flex", lambda token, query, transport=None: report)
    monkeypatch.setattr(pi, "resolve_positions", lambda positions, probe=None: positions)
    monkeypatch.setenv("TRADELAB_LOG_DIR", str(tmp_path))
    out = []
    worker = app._IbkrPositionsWorker("token", "query")
    worker.done.connect(lambda holdings, err: out.append((holdings, err)))
    worker.run()                                         # in this thread, on purpose
    (positions, cash, section, pos_section), err = out[0]
    assert err == "" and section is True and pos_section is True
    assert cash == {"CAD": 1200.25} and positions[0]["symbol"] == "VTI"
    assert (tmp_path / "ibkr_positions_last.xml").read_text(encoding="utf-8") == report


def test_an_import_goes_to_the_ibkr_portfolio_unless_told_otherwise(qapp, tmp_path):
    import tradelab.ui.app as app
    empty = Database(path=tmp_path / "empty.db")
    panel = app.PortfolioPanel(empty)
    assert panel.import_portfolio.currentText() == "IBKR"
    empty.conn.close()


def test_analytics_shows_the_account_value_and_the_date_of_its_prices(qapp, db):
    import tradelab.ui.app as app
    db.set_cash("RRSP", "CAD", 2500.0)
    panel = app.PortfolioAnalyticsPanel(db)
    panel._positions = db.positions()
    panel._cash = db.cash()
    panel._bench_symbol = "SPY"
    panel._target = None
    panel._fx_pairs = {}
    panel._on_loaded({"NVDA": _hist(start=230.0), "SPY": _hist(start=600.0)})
    assert panel.metrics["value"].toolTip().startswith("Positions $")
    assert "cash $2,500" in panel.headline.text()
    assert "Prices as of Fri 09 Oct" in panel.conc.text()


def test_home_counts_the_cash_and_dates_its_prices(qapp, db):
    import tradelab.ui.app as app
    db.set_cash("RRSP", "CAD", 2500.0)
    panel = app.HomePanel(db)
    panel._positions = db.positions()
    panel._cash = db.cash()
    panel._target = None
    panel._bench = "SPY"
    panel._fx_pairs = {}
    panel._on_loaded({"NVDA": _hist(start=230.0), "SPY": _hist(start=600.0)}, {}, {}, {}, "")
    assert "of it in cash" in panel.headline.text()
    assert panel.metrics["value"].toolTip().startswith("Positions $")
    assert "prices as of Fri 09 Oct" in panel.status.text()


def test_a_report_with_an_empty_positions_section_empties_the_portfolio(qapp, db, monkeypatch):
    # Everything sold: IBKR sends the Open Positions section with nothing in it.
    import tradelab.ui.app as app
    asked = []
    _answer_yes(monkeypatch, asked)
    db.set_cash("RRSP", "CAD", 500.0)
    panel = app.PortfolioPanel(db)
    panel.import_portfolio.setCurrentText("RRSP")
    panel._apply_ibkr([], "Flex report", {}, positions_section=True)
    assert [p for p in db.positions() if p["portfolio"] == "RRSP"] == []
    assert "everything has been sold" in asked[0] and "1 position(s) removed" in asked[0]
    assert [(c["currency"], c["amount"]) for c in db.cash()] == [("CAD", 500.0)]
    assert "Emptied the 'RRSP' portfolio" in panel.status.text()


def test_a_report_without_a_positions_section_changes_nothing_and_says_so(qapp, db, monkeypatch):
    import tradelab.ui.app as app
    shown = []
    monkeypatch.setattr("tradelab.ui.common.show_problem", lambda text, parent=None: shown.append(text))
    monkeypatch.setattr(app.QMessageBox, "question", staticmethod(lambda *a, **k: pytest.fail("asked")))
    panel = app.PortfolioPanel(db)
    panel.import_portfolio.setCurrentText("RRSP")
    panel._apply_ibkr([], "Flex report", {})
    assert len([p for p in db.positions() if p["portfolio"] == "RRSP"]) == 1
    assert shown and "no Open Positions section" in shown[0]


class _FakeFlexWorker:
    """Stands in for the Flex fetch: hands back a prepared report at start()."""
    result = None

    def __init__(self, token, query):
        from PySide6.QtCore import QObject, Signal

        class _Sig(QObject):
            done = Signal(object, str)
        self._sig = _Sig()
        self.done = self._sig.done

    def isRunning(self):
        return False

    def start(self):
        holdings, err = _FakeFlexWorker.result
        self.done.emit(holdings, err)


@pytest.fixture
def sync_settings():
    from tradelab.settings import app_settings
    s = app_settings()
    for key, value in (("ibkr/sync_at_startup", True), ("ibkr/sync_portfolio", "RRSP"),
                       ("ibkr/flex_token", "t"), ("ibkr/flex_query", "q")):
        s.setValue(key, value)
    s.sync()
    yield s
    for key in ("ibkr/sync_at_startup", "ibkr/sync_portfolio", "ibkr/flex_token", "ibkr/flex_query"):
        s.remove(key)
    s.sync()


def test_the_startup_sync_replaces_the_portfolio_without_asking(qapp, db, monkeypatch, sync_settings):
    import tradelab.ui.app as app
    monkeypatch.setattr(app, "_IbkrPositionsWorker", _FakeFlexWorker)
    monkeypatch.setattr(app.QMessageBox, "question", staticmethod(lambda *a, **k: pytest.fail("asked")))
    _FakeFlexWorker.result = (([{"symbol": "VTI", "shares": 5, "entry_price": 250.0}],
                               {"CAD": 900.0}, True, True), "")
    panel = app.PortfolioPanel(db)
    seen = []
    panel.synced.connect(seen.append)
    assert panel.startup_sync() is True
    assert [(p["portfolio"], p["symbol"]) for p in db.positions()] == [("RRSP", "VTI")]
    assert [(c["currency"], c["amount"]) for c in db.cash()] == [("CAD", 900.0)]
    assert seen == ["RRSP"] and "IBKR synced" in panel.status.text()


def test_a_failed_startup_sync_changes_nothing_and_pops_up(qapp, db, monkeypatch, sync_settings):
    import tradelab.ui.app as app
    shown = []
    monkeypatch.setattr("tradelab.ui.common.show_problem", lambda text, parent=None: shown.append(text))
    monkeypatch.setattr(app, "_IbkrPositionsWorker", _FakeFlexWorker)
    _FakeFlexWorker.result = (None, "network down")
    panel = app.PortfolioPanel(db)
    panel.startup_sync()
    assert [p["symbol"] for p in db.positions()] == ["NVDA"]
    assert shown and "network down" in shown[0] and "unchanged" in shown[0]


def test_the_startup_sync_is_off_unless_switched_on(qapp, db, monkeypatch):
    import tradelab.ui.app as app
    monkeypatch.setattr(app, "_IbkrPositionsWorker", lambda *a: pytest.fail("fetched"))
    assert app.PortfolioPanel(db).startup_sync() is False
