"""Chart dividend markers + header yield (restored on the PyQtGraph chart).

The markers existed on the old matplotlib chart and were lost when the chart
engine was rebuilt. These tests pin the restored behaviour. Dividends are
injected directly (no network) and the fetch worker is never started.
"""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from tradelab.core.config import ScannerConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _prices(n=200, start=40.0):
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="B")
    close = np.linspace(start, start * 1.15, n)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": [1000] * n}, index=idx)


def _chart(qapp, divs, df=None):
    """A chart with dividends pre-loaded, so no fetch is attempted."""
    from tradelab.ui.widgets.pg_chart_widget import PGChartWidget
    df = _prices() if df is None else df
    w = PGChartWidget()
    w.symbol = "XDIV.TO"
    w._dividend_symbol = "XDIV.TO"          # marks the cache as already filled
    w._dividends = divs
    w.df_raw = df
    w.cfg = ScannerConfig()
    w.replot()
    return w


def _quarterly_divs(df, amount=0.30, count=6):
    """Payments on real bar dates inside the plotted range."""
    dates = [df.index[i] for i in range(20, 20 + count * 25, 25)]
    return pd.Series([amount] * len(dates), index=pd.DatetimeIndex(dates))


def test_markers_drawn_for_each_payment_in_range(qapp):
    df = _prices()
    divs = _quarterly_divs(df)
    w = _chart(qapp, divs, df)
    spots = w.dividend_scatter.data
    assert len(spots) == len(divs)
    # Markers sit below the bar's low so they never cover a candle.
    lows = df["Low"].to_numpy()
    for spot in spots:
        assert spot["y"] < lows.max()


def test_marker_tooltip_carries_the_amount(qapp):
    df = _prices()
    divs = _quarterly_divs(df, amount=0.117, count=2)
    w = _chart(qapp, divs, df)
    tips = [str(s["data"]) for s in w.dividend_scatter.data]
    assert any("0.117" in t for t in tips)
    assert all("Dividend" in t for t in tips)


def test_payments_outside_the_window_are_ignored(qapp):
    df = _prices()
    old = pd.Series([0.25], index=pd.DatetimeIndex([df.index[0] - pd.Timedelta(days=400)]))
    w = _chart(qapp, old, df)
    assert len(w.dividend_scatter.data) == 0


def test_toggle_off_clears_the_markers(qapp):
    df = _prices()
    w = _chart(qapp, _quarterly_divs(df), df)
    assert len(w.dividend_scatter.data) > 0
    w._show_dividends = False
    w.replot()
    assert len(w.dividend_scatter.data) == 0


def test_non_payer_draws_nothing_and_shows_no_yield(qapp):
    w = _chart(qapp, pd.Series(dtype=float))
    assert len(w.dividend_scatter.data) == 0
    text, _ = w._price_line()
    assert "Yield" not in text


def test_header_shows_annual_yield(qapp):
    # Quarterly $0.35 -> $1.40/yr on the latest close.
    df = _prices(start=40.0)
    today = pd.Timestamp.today().normalize()
    dates = pd.DatetimeIndex([today - pd.DateOffset(months=m) for m in (1, 4, 7, 10)])
    w = _chart(qapp, pd.Series([0.35] * 4, index=dates), df)
    text, _ = w._price_line()
    assert "Yield" in text
    last = float(df["Close"].iloc[-1])
    expected = 1.40 / last * 100.0
    assert f"{expected:.2f}%" in text


def test_header_yield_matches_the_dividends_tab(qapp):
    # Regression: the header used a raw trailing-12-month SUM, so a quarterly
    # payer whose year boundary excluded one payment showed only 3 payments'
    # worth of yield — disagreeing with the Dividends tab for the same stock.
    # Both must use the forward run rate (latest payment x frequency).
    from tradelab.core.dividends import holding_income
    df = _prices(start=250.0)
    today = pd.Timestamp.today().normalize()
    # Five quarterly payments, rising, so a 12-month window catches only 3-4.
    dates = pd.DatetimeIndex([today - pd.DateOffset(months=m) for m in (2, 5, 8, 11, 14)])
    divs = pd.Series([1.64, 1.64, 1.54, 1.54, 1.48][::-1], index=dates[::-1])
    w = _chart(qapp, divs, df)

    last = float(df["Close"].iloc[-1])
    tab = holding_income({"symbol": "RY.TO", "shares": 1, "avg_entry": last},
                         divs, price=last)
    chart_yield = w._dividend_yield_pct()
    assert chart_yield == pytest.approx(tab["current_yield_pct"], abs=0.01)
    # And it reflects the latest payment annualized, not a short-changed window.
    assert chart_yield == pytest.approx(1.64 * 4 / last * 100.0, abs=0.01)


def test_yield_hidden_when_markers_are_toggled_off(qapp):
    df = _prices()
    today = pd.Timestamp.today().normalize()
    dates = pd.DatetimeIndex([today - pd.DateOffset(months=m) for m in (1, 4)])
    w = _chart(qapp, pd.Series([0.5] * 2, index=dates), df)
    assert "Yield" in w._price_line()[0]
    w._show_dividends = False
    assert "Yield" not in w._price_line()[0]


def test_timezone_aware_dividends_are_handled(qapp):
    # yfinance returns a tz-aware index; the chart must not raise comparing it
    # against the plot's naive dates.
    df = _prices()
    dates = pd.DatetimeIndex([df.index[50], df.index[100]]).tz_localize("America/New_York")
    w = _chart(qapp, pd.Series([0.2, 0.2], index=dates), df)
    assert len(w.dividend_scatter.data) == 2
