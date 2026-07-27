"""UI smoke tests for the Home tab (HomePanel) and the startup refresh.

Data is fed straight into the render path (no network), with a fake DB
supplying positions.
"""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeDB:
    def __init__(self, positions):
        self._p = positions

    def positions(self):
        return list(self._p)


def _hist(start, end, n=120):
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="B")
    close = np.linspace(start, end, n)
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": [0] * n}, index=idx)


def _panel(qapp, positions):
    import tradelab.ui.app as app
    p = app.HomePanel(_FakeDB(positions))
    p._positions = positions
    p._target = "CAD"
    p._bench = "SPY"
    p._fx_pairs = {"USD": "USDCAD=X"}
    return p


def test_home_populates_tiles_and_movers(qapp):
    positions = [{"symbol": "XDIV.TO", "shares": 300, "entry_price": 43.26},
                 {"symbol": "RY.TO", "shares": 30, "entry_price": 264.45}]
    p = _panel(qapp, positions)
    hist = {"XDIV.TO": _hist(43.0, 46.42), "RY.TO": _hist(280.0, 295.01),
            "SPY": _hist(600.0, 640.0), "USDCAD=X": _hist(1.40, 1.41)}
    p._on_loaded(hist, {}, {}, "")

    assert p.metrics["value"].text().startswith("$")
    assert "CAD" in p.metrics["value"].text()
    assert p.metrics["unreal"].text() != "—"
    assert p.movers.rowCount() == 2
    assert "worth" in p.headline.text()


def test_home_empty_book_is_graceful(qapp):
    import tradelab.ui.app as app
    p = app.HomePanel(_FakeDB([]))
    p.refresh()
    assert "No holdings yet" in p.headline.text()
    assert p.movers.rowCount() == 0


def test_home_reports_fetch_failure(qapp):
    p = _panel(qapp, [{"symbol": "A", "shares": 1, "entry_price": 1}])
    p._on_loaded(None, None, None, "network down")
    assert "network down" in p.status.text()


def test_home_refuses_synthetic_prices(qapp):
    # Same rule as Analytics: a failed download must not become a fake balance.
    from tradelab.data.market_data import synthetic_ohlcv
    p = _panel(qapp, [{"symbol": "FAKE", "shares": 100, "entry_price": 10.0}])
    p._on_loaded({"FAKE": synthetic_ohlcv("FAKE")}, {}, {}, "")
    assert p.metrics["value"].text() == "—"       # no fabricated book value


def test_home_attention_lists_a_big_drop(qapp):
    positions = [{"symbol": "CRASH", "shares": 10, "entry_price": 100.0}]
    p = _panel(qapp, positions)
    df = _hist(100.0, 100.0)
    df.iloc[-1, df.columns.get_loc("Close")] = 90.0     # -10% on the last bar
    p._on_loaded({"CRASH": df}, {}, {}, "")
    texts = [p.attention.item(i).text() for i in range(p.attention.count())]
    assert any("CRASH" in t and "down" in t for t in texts)


def test_market_line_shows_every_market_read(qapp):
    # Home displays the Market tab's own numbers rather than recomputing them.
    p = _panel(qapp, [{"symbol": "A", "shares": 1, "entry_price": 1}])
    import time as _t
    p.market_source = lambda: {
        "reads": {
            "Canada": {"label": "Favorable", "score": 74, "summary": "TSX trending up.",
                       "pct_above_200": 62.0, "vix": 18.7,
                       "strongest": "Financials", "weakest": "Utilities"},
            "US": {"label": "Neutral / mixed", "score": 58, "summary": "Mixed.",
                   "pct_above_200": 51.0, "vix": 18.7,
                   "strongest": "Technology", "weakest": "Energy"},
        },
        "as_of": _t.time(),
    }
    p.refresh_market_line()
    text = p.market_line.text()
    assert "Canada" in text and "74/100" in text
    assert "US" in text and "58/100" in text
    assert "62% above 200-day" in text and "VIX 18.7" in text
    assert "Financials" in text and "Utilities" in text
    assert "updated" in text            # fresh reading is labelled as such


def test_home_shows_the_world_board_and_macro_row(qapp):
    import time as _t
    p = _panel(qapp, [{"symbol": "A", "shares": 1, "entry_price": 1}])
    p.market_source = lambda: {
        "reads": {"Canada": {"label": "Favorable", "score": 74, "summary": "",
                             "pct_above_200": 62.0, "vix": None,
                             "strongest": None, "weakest": None}},
        "as_of": _t.time(),
        "indices": {"TSX Composite": {"last": 35568.0, "change_pct": 0.56},
                    "S&P 500": {"last": 7100.0, "change_pct": -0.24}},
        "macro": {"CAD=X": {"last": 1.4125, "change_pct": 0.28},
                  "^TNX": {"last": 4.641, "change_pct": -0.812}},
    }
    p.refresh_market_line()
    world, macro = p.world_line.text(), p.macro_line.text()
    assert "TSX +0.6%" in world and "S&P 500 -0.2%" in world
    assert "USD/CAD 1.4125 +0.3%" in macro and "US 10Y 4.64% -4 bp" in macro
    # Direction is coloured for prices; the yield stays neutral on purpose.
    from tradelab.ui import theme
    assert theme.UP in world and theme.DOWN in world
    assert theme.UP not in macro.split("US 10Y")[1]


def test_home_context_lines_clear_when_the_market_is_unread(qapp):
    p = _panel(qapp, [{"symbol": "A", "shares": 1, "entry_price": 1}])
    p.market_source = lambda: {
        "reads": {"Canada": {"label": "Favorable", "score": 74, "summary": "",
                             "pct_above_200": None, "vix": None,
                             "strongest": None, "weakest": None}},
        "indices": {"TSX Composite": {"last": 1.0, "change_pct": 1.0}},
        "macro": {},
    }
    p.refresh_market_line()
    assert p.world_line.text() and not p.macro_line.text()   # no macro, no line
    p.market_source = lambda: None
    p.refresh_market_line()
    assert p.world_line.text() == "" and p.macro_line.text() == ""


def test_market_panel_exposes_indices_and_macro(qapp):
    import tradelab.ui.app as app
    panel = app.MarketPanel()
    panel._global_indices = {"TSX Composite": {"last": 35568.0, "change_pct": 0.56}}
    panel._region_data = {"Canada": {
        "read": {"label": "Favorable", "score": 74, "summary": ""},
        "stock_breadth": {}, "ranked": [],
        "regime": {"CAD=X": {"last": 1.4125, "change_pct": 0.28},
                   "CL=F": {"last": 81.9, "change_pct": -8.3}},
    }}
    summary = panel.market_summary()
    assert summary["indices"]["TSX Composite"]["change_pct"] == 0.56
    assert summary["macro"]["CAD=X"]["last"] == 1.4125
    assert summary["macro"]["CL=F"]["change_pct"] == -8.3


def test_market_line_flags_a_stale_reading(qapp):
    import time as _t
    p = _panel(qapp, [{"symbol": "A", "shares": 1, "entry_price": 1}])
    p.market_source = lambda: {
        "reads": {"Canada": {"label": "Caution", "score": 30, "summary": "",
                             "pct_above_200": None, "vix": None,
                             "strongest": None, "weakest": None}},
        "as_of": _t.time() - 7200,       # two hours old
    }
    p.refresh_market_line()
    assert "as of" in p.market_line.text()   # not presented as current


def test_market_line_waits_when_no_read_yet(qapp):
    p = _panel(qapp, [{"symbol": "A", "shares": 1, "entry_price": 1}])
    p.market_source = lambda: None
    p.refresh_market_line()
    assert "reading the market" in p.market_line.text()
    # A market source that raises must not break the panel.
    def boom():
        raise RuntimeError("market unavailable")
    p.market_source = boom
    p.refresh_market_line()
    assert "reading the market" in p.market_line.text()


def test_market_panel_exposes_its_read(qapp):
    import tradelab.ui.app as app
    panel = app.MarketPanel()
    assert panel.market_summary() is None          # nothing computed yet
    panel._region_data = {"Canada": {
        "read": {"label": "Favorable", "score": 74, "summary": "TSX up."},
        "stock_breadth": {"pct_above_200": 62.0},
        "ranked": [{"name": "Financials"}, {"name": "Utilities"}],
        "regime": {"^VIX": {"last": 18.7}},
    }}
    summary = panel.market_summary()
    read = summary["reads"]["Canada"]
    assert read["score"] == 74 and read["label"] == "Favorable"
    assert read["strongest"] == "Financials" and read["weakest"] == "Utilities"
    assert read["vix"] == 18.7


def test_startup_refresh_is_safe_without_positions(qapp, monkeypatch):
    # MainWindow.refresh_on_startup must never raise, even with an empty book.
    import tradelab.ui.app as app
    called = []

    warmed = []

    class _Win:
        db = _FakeDB([])
        home_panel = type("P", (), {"refresh": lambda self: called.append(1)})()
        market_panel = type(
            "M", (), {"refresh_market": lambda self: warmed.append(1)})()

        def _warm_market(self):
            self.market_panel.refresh_market()

    app.MainWindow.refresh_on_startup(_Win())
    assert called == []          # nothing to refresh, and no exception


def test_startup_refresh_survives_a_broken_panel(qapp):
    # Startup must never be taken down by a refresh failure.
    import tradelab.ui.app as app

    class _Win:
        db = _FakeDB([{"symbol": "A", "shares": 1, "entry_price": 1}])
        home_panel = type("P", (), {
            "refresh": lambda self: (_ for _ in ()).throw(RuntimeError("boom"))})()

        def _warm_market(self):
            pass

    app.MainWindow.refresh_on_startup(_Win())      # must not raise


def test_home_flags_look_through_concentration(qapp):
    # A name held directly *and* inside a fund is one exposure, not two. Home
    # must say so when the combined figure crosses the concentration threshold.
    positions = [{"symbol": "RY.TO", "shares": 30, "entry_price": 264.45},
                 {"symbol": "XDIV.TO", "shares": 300, "entry_price": 43.26}]
    p = _panel(qapp, positions)
    hist = {"RY.TO": _hist(295.0, 295.0), "XDIV.TO": _hist(46.42, 46.42),
            "SPY": _hist(600.0, 640.0), "USDCAD=X": _hist(1.40, 1.41)}
    comps = {"XDIV.TO": {"top_holdings": {"RY.TO": 0.10, "TD.TO": 0.09}},
             "RY.TO": {"top_holdings": {}}}
    p._on_loaded(hist, {}, comps, "")
    texts = [p.attention.item(i).text() for i in range(p.attention.count())]
    assert any("RY.TO" in t and "opened up" in t for t in texts)


def test_home_without_compositions_says_nothing_about_look_through(qapp):
    p = _panel(qapp, [{"symbol": "RY.TO", "shares": 30, "entry_price": 264.45}])
    p._on_loaded({"RY.TO": _hist(295.0, 295.0)}, {}, {}, "")
    texts = [p.attention.item(i).text() for i in range(p.attention.count())]
    assert not any("opened up" in t for t in texts)
