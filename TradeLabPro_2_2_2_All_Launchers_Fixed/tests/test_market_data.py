import pandas as pd
import pytest

import tradelab.data.market_data as market_data
from tradelab.data.market_data import (synthetic_ohlcv, get_history, get_quote_meta,
                                       market_cap_bucket, _company_name_from_info,
                                       _name_from_summary, _yahoo_histories)


def test_synthetic_ohlcv_returns_expected_columns():
    df = synthetic_ohlcv("AAPL")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        assert col in df.columns


def test_synthetic_ohlcv_index_length_matches_data_length():
    # Regression test: date_range(periods=N, freq="B") is not guaranteed to
    # return exactly N rows on every pandas version (observed 259 vs 260 on
    # pandas 3.x), which previously raised
    # "ValueError: Length of values (260) does not match length of index (259)".
    for periods in [50, 259, 260, 261, 500]:
        df = synthetic_ohlcv("TEST", periods=periods)
        assert len(df) == len(df.index)
        assert len(df["Close"]) == len(df.index)


def test_synthetic_ohlcv_is_deterministic_per_symbol():
    df1 = synthetic_ohlcv("AAPL")
    df2 = synthetic_ohlcv("AAPL")
    pd.testing.assert_frame_equal(df1, df2)


def test_synthetic_ohlcv_differs_across_symbols():
    df1 = synthetic_ohlcv("AAPL")
    df2 = synthetic_ohlcv("MSFT")
    assert not df1["Close"].equals(df2["Close"])


def test_get_history_never_raises_and_returns_dataframe():
    # No network in this sandbox -> should fall back to synthetic data
    # rather than raising or returning something malformed.
    df = get_history("AAPL", "6mo", "1d")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert len(df) == len(df.index)


class _FakeTicker:
    def __init__(self, info):
        self.info = info


@pytest.fixture(autouse=True)
def _clear_quote_meta_cache():
    # get_quote_meta caches in-process by symbol - each test needs a clean
    # slate or an earlier test's fake/real fetch would leak into a later one.
    market_data._quote_meta_cache.clear()
    yield
    market_data._quote_meta_cache.clear()


def test_get_quote_meta_uses_real_market_cap_and_sector(monkeypatch):
    # Regression test: get_quote_meta() used to be a pure stub returning a
    # fake market cap seeded from hash(symbol) - "Minimum market cap" never
    # actually filtered on real data. This is the real-data path.
    monkeypatch.setattr(market_data, "yf", type("_yf", (), {
        "Ticker": staticmethod(lambda symbol: _FakeTicker({"marketCap": 4_600_000_000_000, "sector": "Technology", "industry": "Consumer Electronics"}))
    }))
    meta = get_quote_meta("AAPL")
    assert meta["market_cap"] == 4_600_000_000_000
    assert meta["sector"] == "Technology"
    assert meta["industry"] == "Consumer Electronics"


def test_get_quote_meta_falls_back_when_yfinance_unavailable(monkeypatch):
    monkeypatch.setattr(market_data, "yf", None)
    meta = get_quote_meta("AAPL")
    assert meta["market_cap"] > 0  # deterministic fallback, not zero/missing
    assert meta["sector"] == "Unknown"


def test_get_quote_meta_falls_back_when_fetch_raises(monkeypatch):
    monkeypatch.setattr(market_data, "yf", type("_yf", (), {
        "Ticker": staticmethod(lambda symbol: (_ for _ in ()).throw(RuntimeError("no network")))
    }))
    meta = get_quote_meta("AAPL")
    assert meta["market_cap"] > 0
    assert meta["sector"] == "Unknown"


def test_get_quote_meta_is_cached_per_symbol(monkeypatch):
    calls = []

    def fake_ticker(symbol):
        calls.append(symbol)
        return _FakeTicker({"marketCap": 1_000_000_000, "sector": "Energy", "industry": "Oil & Gas"})

    monkeypatch.setattr(market_data, "yf", type("_yf", (), {"Ticker": staticmethod(fake_ticker)}))
    get_quote_meta("XOM")
    get_quote_meta("XOM")
    get_quote_meta("XOM")
    assert calls == ["XOM"]  # only fetched once


@pytest.mark.parametrize("summary,expected", [
    ("The Coca-Cola Company, a beverage company, engages in ...", "The Coca-Cola Company"),
    ("Caterpillar Inc. provides construction and mining equipment ...", "Caterpillar Inc."),
    ("JPMorgan Chase & Co. operates as a financial services company ...", "JPMorgan Chase & Co."),
    ("Bank of America Corporation provides banking products ...", "Bank of America Corporation"),
    ("The Procter & Gamble Company provides branded consumer ...", "The Procter & Gamble Company"),
    ("", ""),
])
def test_name_from_summary(summary, expected):
    assert _name_from_summary(summary) == expected


def test_company_name_prefers_longname_then_shortname():
    assert _company_name_from_info({"longName": "Apple Inc.", "shortName": "Apple"}, "AAPL") == "Apple Inc."
    assert _company_name_from_info({"shortName": "Apple"}, "AAPL") == "Apple"


def test_company_name_falls_back_to_summary_when_no_long_short_name():
    # The real-world KO/CAT/JPM case: no longName/shortName, but a summary.
    info = {"displayName": "Coca-Cola",
            "longBusinessSummary": "The Coca-Cola Company, a beverage company, engages ..."}
    assert _company_name_from_info(info, "KO") == "The Coca-Cola Company"


def test_company_name_falls_back_to_displayname_then_symbol():
    assert _company_name_from_info({"displayName": "Caterpillar"}, "CAT") == "Caterpillar"
    assert _company_name_from_info({}, "ZZZZ") == "ZZZZ"


def test_company_name_rejects_filler_summary_start():
    # ETF summaries often start "In seeking to track ..." - the leading run
    # ("In") is not a real name and must be rejected, not shown as the name.
    info = {"longBusinessSummary": "In seeking to track the S&P 500 index, the fund invests ...",
            "displayName": "Technology Select"}
    assert _company_name_from_info(info, "XLK") == "Technology Select"
    assert _company_name_from_info({"longBusinessSummary": "In seeking to track ..."}, "XLK") == "XLK"


def test_get_quote_meta_uses_aum_and_category_for_etfs(monkeypatch):
    # ETFs have no marketCap/sector: get_quote_meta must fall back to AUM
    # (totalAssets) for size and the fund `category` for the group label.
    info = {"quoteType": "ETF", "totalAssets": 781_000_000_000,
            "category": "Large Blend", "longName": "SPDR S&P 500 ETF Trust"}
    monkeypatch.setattr(market_data, "yf", type("_yf", (), {
        "Ticker": staticmethod(lambda symbol: _FakeTicker(info))}))
    meta = get_quote_meta("SPY")
    assert meta["market_cap"] == 781_000_000_000
    assert meta["sector"] == "Large Blend"
    assert meta["name"] == "SPDR S&P 500 ETF Trust"
    assert meta["quote_type"] == "ETF"


def test_get_quote_meta_resolves_name_from_displayname_and_summary(monkeypatch):
    # End-to-end: a KO-shaped info dict (no longName/shortName) still yields a
    # real company name, not the ticker.
    info = {"marketCap": 350_000_000_000, "sector": "Consumer Defensive",
            "displayName": "Coca-Cola",
            "longBusinessSummary": "The Coca-Cola Company, a beverage company, engages ..."}
    monkeypatch.setattr(market_data, "yf", type("_yf", (), {
        "Ticker": staticmethod(lambda symbol: _FakeTicker(info))}))
    assert get_quote_meta("KO")["name"] == "The Coca-Cola Company"


def _multi_ticker_frame(symbols, rows=5):
    # Mimics yfinance's group_by="ticker" output: a (ticker, field) MultiIndex
    # column frame. `symbols` set to None come back all-NaN, which is how
    # yfinance reports a ticker it couldn't fill inside an otherwise-good batch.
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    data = {}
    for sym, ok in symbols.items():
        for field in ("Open", "High", "Low", "Close", "Volume"):
            values = list(range(1, rows + 1)) if ok else [float("nan")] * rows
            data[(sym, field)] = values
    frame = pd.DataFrame(data, index=dates)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


def _fake_yf(recorder, per_symbol_ok):
    def download(tickers, **kwargs):
        tickers = list(tickers) if isinstance(tickers, (list, tuple)) else [tickers]
        recorder.append(list(tickers))
        return _multi_ticker_frame({s: per_symbol_ok.get(s, True) for s in tickers})
    return type("_yf", (), {"download": staticmethod(download)})


def test_yahoo_histories_batches_in_chunks(monkeypatch):
    # Regression test for the Market-refresh stall: ~90 symbols used to be
    # fetched one HTTP request at a time, tripping Yahoo's rate limit. They must
    # now go out in a few multi-ticker batches instead.
    calls = []
    symbols = [f"S{i}" for i in range(90)]
    monkeypatch.setattr(market_data, "yf", _fake_yf(calls, {}))
    out = _yahoo_histories(symbols, chunk_size=40)
    assert set(out) == set(symbols)               # every symbol accounted for
    assert len(calls) == 3                          # 40 + 40 + 10, not 90 calls
    assert all(len(batch) <= 40 for batch in calls)
    for df in out.values():
        assert {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns)


def test_yahoo_histories_falls_back_to_synthetic_for_empty_symbol(monkeypatch):
    # A ticker Yahoo returns all-NaN for inside a good batch must be backfilled
    # with synthetic data, not left empty, so the dashboard has no holes.
    calls = []
    monkeypatch.setattr(market_data, "yf", _fake_yf(calls, {"BAD": False}))
    out = _yahoo_histories(["GOOD", "BAD"], chunk_size=40)
    assert not out["GOOD"].empty and not out["BAD"].empty
    # BAD is the deterministic synthetic series for that symbol.
    pd.testing.assert_frame_equal(out["BAD"], synthetic_ohlcv("BAD"))


def test_yahoo_histories_dedups_preserving_order(monkeypatch):
    calls = []
    monkeypatch.setattr(market_data, "yf", _fake_yf(calls, {}))
    out = _yahoo_histories(["AAA", "BBB", "AAA", "CCC"], chunk_size=40)
    assert list(out) == ["AAA", "BBB", "CCC"]
    assert calls == [["AAA", "BBB", "CCC"]]         # requested once each


def test_yahoo_histories_synthetic_when_yfinance_unavailable(monkeypatch):
    monkeypatch.setattr(market_data, "yf", None)
    out = _yahoo_histories(["AAA", "BBB"])
    assert set(out) == {"AAA", "BBB"}
    pd.testing.assert_frame_equal(out["AAA"], synthetic_ohlcv("AAA"))


def test_yahoo_histories_survives_download_raising(monkeypatch):
    # A whole-batch failure (network drop mid-refresh) must degrade to synthetic
    # data for that chunk rather than raising out of the worker thread.
    def boom(tickers, **kwargs):
        raise RuntimeError("no network")
    monkeypatch.setattr(market_data, "yf", type("_yf", (), {"download": staticmethod(boom)}))
    out = _yahoo_histories(["AAA", "BBB"], chunk_size=40)
    assert set(out) == {"AAA", "BBB"}
    for df in out.values():
        assert not df.empty


@pytest.mark.parametrize("market_cap,expected", [
    (300_000_000_000, "Mega"),
    (200_000_000_000, "Mega"),
    (50_000_000_000, "Large"),
    (10_000_000_000, "Large"),
    (5_000_000_000, "Mid"),
    (2_000_000_000, "Mid"),
    (500_000_000, "Small"),
    (300_000_000, "Small"),
    (100_000_000, "Micro"),
    (0, "Micro"),
])
def test_market_cap_bucket(market_cap, expected):
    assert market_cap_bucket(market_cap) == expected
