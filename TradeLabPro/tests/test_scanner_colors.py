"""Regression tests for the Scanner result color standard (SCN-027)."""
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from tradelab.ui import colors


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def scanner_panel(qapp, tmp_db_path):
    from tradelab.data.database import Database
    from tradelab.ui.chart_widget import ChartWidget
    from tradelab.ui.app import ScannerPanel

    db = Database(tmp_db_path)
    chart = ChartWidget()
    panel = ScannerPanel(db, chart)
    yield panel
    db.conn.close()


def test_score_row_color_tiers_are_distinct():
    strong = colors.score_row_color(90)
    good = colors.score_row_color(75)
    weak = colors.score_row_color(60)
    poor = colors.score_row_color(40)
    assert len({strong.name(), good.name(), weak.name(), poor.name()}) == 4


def test_score_row_color_boundaries():
    assert colors.score_row_color(85).name() == colors.score_row_color(100).name()
    assert colors.score_row_color(70).name() == colors.score_row_color(84.9).name()
    assert colors.score_row_color(55).name() == colors.score_row_color(69.9).name()
    assert colors.score_row_color(0).name() == colors.score_row_color(54.9).name()


def test_error_row_never_reads_as_poor_score():
    # A score-0 error row must not be visually indistinguishable from a
    # genuinely weak (but valid) low-score result.
    assert colors.score_row_color(0, is_error=True).name() != colors.score_row_color(0, is_error=False).name()


@pytest.mark.parametrize("signal,expected", [
    ("BUY", colors.BULLISH),
    ("buy", colors.BULLISH),
    ("SELL", colors.BEARISH),
    ("WATCH", colors.NEUTRAL),
    ("ERROR", colors.ERROR_GRAY),
])
def test_signal_color_known_states(signal, expected):
    assert colors.signal_color(signal).name() == expected.name()


def test_signal_color_hold_and_unknown_are_unstyled():
    assert colors.signal_color("HOLD") is None
    assert colors.signal_color("") is None
    assert colors.signal_color(None) is None


@pytest.mark.parametrize("state,expected", [
    ("Bull", colors.BULLISH),
    ("BEAR", colors.BEARISH),
])
def test_trend_color(state, expected):
    assert colors.trend_color(state).name() == expected.name()


def test_trend_color_unknown_is_unstyled():
    assert colors.trend_color("") is None
    assert colors.trend_color("flat") is None


def test_rsi_zone_color_overbought_and_oversold():
    assert colors.rsi_zone_color(75).name() == colors.BEARISH.name()
    assert colors.rsi_zone_color(25).name() == colors.BULLISH.name()


def test_rsi_zone_color_neutral_band_is_unstyled():
    assert colors.rsi_zone_color(50) is None
    assert colors.rsi_zone_color(colors.RSI_OVERBOUGHT - 0.01) is None
    assert colors.rsi_zone_color(colors.RSI_OVERSOLD + 0.01) is None


def test_rsi_zone_color_handles_bad_input():
    assert colors.rsi_zone_color("not-a-number") is None
    assert colors.rsi_zone_color(None) is None


def test_populate_table_applies_color_standard(scanner_panel):
    scanner_panel.results = pd.DataFrame([
        {"Symbol": "AAA", "Signal": "BUY", "Score": 90, "Price": 10, "Volume": 1, "RelVol": 1,
         "Market Cap": 1, "RSI14": 80, "ATR%": 1, "EMA Trend": "Bull", "MACD": "Bull"},
        {"Symbol": "BBB", "Signal": "SELL", "Score": 40, "Price": 10, "Volume": 1, "RelVol": 1,
         "Market Cap": 1, "RSI14": 20, "ATR%": 1, "EMA Trend": "Bear", "MACD": "Bear"},
        {"Symbol": "CCC", "Signal": "ERROR", "Score": 0, "Price": 0, "Volume": 0, "RelVol": 0,
         "Market Cap": 0, "RSI14": 0, "ATR%": 0, "EMA Trend": "", "MACD": "", "Error": "boom"},
    ])
    scanner_panel.populate_table()
    table = scanner_panel.table

    assert table.rowCount() == 3

    # The table has sorting enabled and may restore a persisted sort order
    # (restore_scanner_layout reads QSettings), so row 0 isn't necessarily
    # AAA - look each row up by its Symbol cell instead of assuming order.
    # Columns are also looked up by header label rather than a hardcoded
    # index, since the scanner table gains new columns fairly often (Cap/
    # Sector/Confidence were all added after this test was first written)
    # and a positional index silently drifts every time that happens.
    col = {table.horizontalHeaderItem(c).text(): c for c in range(table.columnCount())}
    rows_by_symbol = {table.item(r, col["Symbol"]).text(): r for r in range(table.rowCount())}

    buy_row = rows_by_symbol["AAA"]
    buy_row_bg = table.item(buy_row, col["Symbol"]).background().color().name()
    assert buy_row_bg == colors.score_row_color(90).name()
    assert table.item(buy_row, col["Signal"]).foreground().color().name() == colors.BULLISH.name()  # Signal=BUY
    assert table.item(buy_row, col["RSI"]).foreground().color().name() == colors.BEARISH.name()  # RSI 80 overbought
    assert table.item(buy_row, col["EMA"]).foreground().color().name() == colors.BULLISH.name()  # EMA Trend=Bull

    sell_row = rows_by_symbol["BBB"]
    sell_row_bg = table.item(sell_row, col["Symbol"]).background().color().name()
    assert sell_row_bg == colors.score_row_color(40).name()
    assert table.item(sell_row, col["Signal"]).foreground().color().name() == colors.BEARISH.name()  # Signal=SELL
    assert table.item(sell_row, col["RSI"]).foreground().color().name() == colors.BULLISH.name()  # RSI 20 oversold

    error_row = rows_by_symbol["CCC"]
    error_row_bg = table.item(error_row, col["Symbol"]).background().color().name()
    assert error_row_bg == colors.score_row_color(0, is_error=True).name()
    assert error_row_bg != colors.score_row_color(0, is_error=False).name()
    assert table.item(error_row, col["Symbol"]).toolTip() == "boom"


def test_result_status_shows_sector_breakdown(scanner_panel):
    scanner_panel.results = pd.DataFrame([
        {"Symbol": "AAA", "Signal": "BUY", "Score": 90, "Sector": "Technology"},
        {"Symbol": "BBB", "Signal": "BUY", "Score": 80, "Sector": "Technology"},
        {"Symbol": "CCC", "Signal": "BUY", "Score": 70, "Sector": "Energy"},
        {"Symbol": "DDD", "Signal": "ERROR", "Score": 0, "Sector": ""},  # excluded, no real sector
    ])
    scanner_panel.populate_table()
    text = scanner_panel.result_status.text()
    assert text.startswith("Results: 4")
    assert "Technology: 2" in text
    assert "Energy: 1" in text


def test_result_status_omits_breakdown_when_no_sector_data(scanner_panel):
    scanner_panel.results = pd.DataFrame([{"Symbol": "AAA", "Signal": "BUY", "Score": 90}])
    scanner_panel.populate_table()
    assert scanner_panel.result_status.text() == "Results: 1"


def test_populate_table_shows_confidence_and_sample_columns(scanner_panel):
    scanner_panel.results = pd.DataFrame([
        {"Symbol": "AAA", "Signal": "BUY", "Score": 90, "Confidence %": 66.7, "Sample N": 3},
        {"Symbol": "BBB", "Signal": "BUY", "Score": 80, "Confidence %": None, "Sample N": 0},
    ])
    scanner_panel.populate_table()
    table = scanner_panel.table
    col = {table.horizontalHeaderItem(c).text(): c for c in range(table.columnCount())}
    rows_by_symbol = {table.item(r, col["Symbol"]).text(): r for r in range(table.rowCount())}

    aaa_row = rows_by_symbol["AAA"]
    assert table.item(aaa_row, col["Conf%"]).text() == "67%"
    assert table.item(aaa_row, col["Sample"]).text() == "3"

    bbb_row = rows_by_symbol["BBB"]
    assert table.item(bbb_row, col["Conf%"]).text() == "—"  # no historical BUY signals to measure
    assert table.item(bbb_row, col["Sample"]).text() == "0"
