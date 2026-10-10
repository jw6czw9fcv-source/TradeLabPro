"""Valuing a book at the latest trade when Yahoo is late with the day's bar.

On 9 October 2026 at 21:25 Eastern, Yahoo's daily bars still ended on the 8th.
TradeLab valued the book at Thursday's closes and would have reported
Thursday's drop as "today". These tests pin the fix: a trade from a later
session is added as one more bar, a trade from the same session changes
nothing, and a failure never costs the valuation.
"""
import pandas as pd
import pytest

import tradelab.data.market_data as market_data
from tradelab.core import home
from tradelab.core import portfolio_analytics as pa

NY = "America/New_York"


def _daily(last_day, closes):
    idx = pd.date_range(end=last_day, periods=len(closes), freq="B")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                         "Adj Close": closes, "Volume": [1000] * len(closes)}, index=idx)


def _trade(price, when="2026-10-09 15:55", tz=NY):
    return {"price": price, "time": pd.Timestamp(when, tz=tz)}


# --- adding the missing session ----------------------------------------------

def test_a_later_session_is_added_as_one_more_bar():
    hist = {"NVDA": _daily("2026-10-08", [237.47, 230.48])}
    out = pa.apply_latest_prices(hist, {"NVDA": _trade(229.28)})
    frame = out["NVDA"]
    assert frame.index[-1] == pd.Timestamp("2026-10-09")
    assert frame["Close"].iloc[-1] == pytest.approx(229.28)
    assert frame["Adj Close"].iloc[-1] == pytest.approx(229.28)
    assert pd.isna(frame["Volume"].iloc[-1])             # no volume is invented
    assert len(hist["NVDA"]) == 2                         # the input is left as it was
    assert not market_data.is_synthetic(frame)            # still real data


def test_a_trade_from_the_session_already_there_changes_nothing():
    hist = {"NVDA": _daily("2026-10-09", [230.48, 229.28])}
    out = pa.apply_latest_prices(hist, {"NVDA": _trade(229.31)})
    assert out["NVDA"] is hist["NVDA"]


def test_the_session_is_read_in_the_market_s_own_time_zone():
    # Late afternoon in New York is already the next day in UTC: read in UTC, a
    # Friday trade would become a Saturday bar.
    hist = {"NVDA": _daily("2026-10-08", [237.47, 230.48])}
    out = pa.apply_latest_prices(hist, {"NVDA": _trade(229.28, "2026-10-10 01:30", "UTC")})
    assert out["NVDA"].index[-1] == pd.Timestamp("2026-10-09")


@pytest.mark.parametrize("symbol,tz", [
    ("NVDA", "America/New_York"), ("RY.TO", "America/Toronto"),
    ("XYZ.T", "Asia/Tokyo"), ("VOD.L", "Europe/London")])
def test_each_listing_trades_in_its_own_time_zone(symbol, tz):
    assert pa.exchange_timezone(symbol) == tz


@pytest.mark.parametrize("bad", [None, float("nan"), 0, -5, "n/a"])
def test_a_nonsense_price_is_ignored(bad):
    hist = {"A": _daily("2026-10-08", [10.0, 11.0])}
    out = pa.apply_latest_prices(hist, {"A": _trade(bad)})
    assert out["A"].index[-1] == pd.Timestamp("2026-10-08")


def test_a_trade_with_no_time_or_no_history_is_ignored():
    hist = {"A": _daily("2026-10-08", [10.0, 11.0])}
    assert len(pa.apply_latest_prices(hist, {"A": {"price": 12.0, "time": None}})["A"]) == 2
    assert "MISSING" not in pa.apply_latest_prices(hist, {"MISSING": _trade(12.0)})


def test_the_book_is_valued_at_the_latest_trade_and_today_means_today():
    positions = [{"symbol": "NVDA", "shares": 10, "entry_price": 240.0}]
    hist = pa.apply_latest_prices({"NVDA": _daily("2026-10-08", [237.47, 230.48])},
                                  {"NVDA": _trade(229.28)})
    summary = pa.summarize(positions, hist)
    assert summary["holdings"][0]["last"] == pytest.approx(229.28)
    assert summary["prices_as_of"] == "2026-10-09"
    # Friday's move, not Thursday's -$70.
    assert home.movers(positions, hist)[0]["change_value"] == pytest.approx(-12.0)


def test_the_oldest_price_is_the_one_reported():
    positions = [{"symbol": "NVDA", "shares": 1, "entry_price": 1},
                 {"symbol": "RY.TO", "shares": 1, "entry_price": 1}]
    hist = {"NVDA": _daily("2026-10-09", [230.0, 229.0]),
            "RY.TO": _daily("2026-10-08", [150.0, 151.0])}
    assert pa.summarize(positions, hist)["prices_as_of"] == "2026-10-08"


# --- fetching it --------------------------------------------------------------

def test_only_real_histories_are_topped_up(monkeypatch):
    asked = []

    def latest(symbols):
        asked.append(list(symbols))
        return {"NVDA": _trade(229.28)}
    monkeypatch.setattr(market_data, "get_latest_prices", latest)
    hist = {"NVDA": _daily("2026-10-08", [237.47, 230.48]),
            "FAKE": market_data.synthetic_ohlcv("FAKE"), "GONE": None}
    out = market_data.with_latest_prices(hist, ["NVDA", "FAKE", "GONE"])
    assert asked == [["NVDA"]]
    assert out["NVDA"].index[-1] == pd.Timestamp("2026-10-09")
    assert out["FAKE"] is hist["FAKE"]


def test_a_failing_source_leaves_the_histories_as_they_were(monkeypatch):
    def boom(symbols):
        raise RuntimeError("no network")
    monkeypatch.setattr(market_data, "get_latest_prices", boom)
    hist = {"NVDA": _daily("2026-10-08", [237.47, 230.48])}
    assert market_data.with_latest_prices(hist, ["NVDA"]) is hist


def _five_minute_batch(calls):
    def download(tickers, **kwargs):
        tickers = list(tickers)
        calls.append((tickers, kwargs.get("period"), kwargs.get("interval")))
        idx = pd.date_range("2026-10-09 15:45", periods=3, freq="5min", tz=NY)
        data = {}
        for t in tickers:
            close = [1.0, 2.0, float("nan")] if t == "NVDA" else [float("nan")] * 3
            for field in ("Open", "High", "Low", "Close", "Volume"):
                data[(t, field)] = close
        frame = pd.DataFrame(data, index=idx)
        frame.columns = pd.MultiIndex.from_tuples(frame.columns)
        return frame
    return type("_yf", (), {"download": staticmethod(download)})


def test_yahoo_s_last_five_minute_trade_is_the_latest_price(monkeypatch):
    calls = []
    monkeypatch.setattr(market_data, "yf", _five_minute_batch(calls))
    out = market_data._yahoo_latest_prices(["NVDA", "BAD"])
    assert calls == [(["NVDA", "BAD"], "5d", "5m")]          # one batch request
    assert out["NVDA"]["price"] == 2.0
    assert out["NVDA"]["time"] == pd.Timestamp("2026-10-09 15:50", tz=NY)
    assert "BAD" not in out                                  # nothing usable, nothing guessed


def test_without_yfinance_there_is_no_latest_price(monkeypatch):
    monkeypatch.setattr(market_data, "yf", None)
    assert market_data._yahoo_latest_prices(["NVDA"]) == {}


def test_a_source_without_intraday_data_guesses_nothing():
    from tradelab.data import providers
    assert providers.SyntheticProvider().get_latest_prices(["NVDA"]) == {}


def test_the_analytics_download_tops_up_the_holdings_only(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import tradelab.ui.app as app
    monkeypatch.setattr(app, "get_histories", lambda chunk, period, interval: {
        s: _daily("2026-10-08", [10.0, 11.0]) for s in chunk})
    monkeypatch.setattr(market_data, "get_latest_prices",
                        lambda symbols: {s: _trade(12.0) for s in symbols})
    worker = app._MarketRefreshWorker(["NVDA", "USDCAD=X"], latest_for=["NVDA"])
    got = {}
    worker.done.connect(got.update)
    worker.run()
    assert got["NVDA"].index[-1] == pd.Timestamp("2026-10-09")
    assert got["USDCAD=X"].index[-1] == pd.Timestamp("2026-10-08")    # FX left alone
