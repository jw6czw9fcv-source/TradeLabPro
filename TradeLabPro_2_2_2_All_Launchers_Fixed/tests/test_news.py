"""Market news engine tests - offline via an injected fetcher."""
from tradelab.core.news import (fetch_news, is_macro, is_geopolitical, _parse_one,
                                NewsItem, SECTOR_ETFS, GEO_SYMBOLS, MARKET_SYMBOLS)


def test_is_macro_flags_policy_headlines():
    assert is_macro("Fed signals another rate hike as inflation cools")
    assert is_macro("Tariffs on Chinese imports rattle markets")
    assert is_macro("Election results drive Treasury yields higher")
    assert not is_macro("Apple unveils new MacBook Pro")


def test_is_geopolitical_flags_geo_headlines():
    assert is_geopolitical("Russia-Ukraine war escalates, oil prices spike")
    assert is_geopolitical("OPEC cuts output; Middle East tensions rise")
    assert is_geopolitical("New tariffs on China imports announced")
    assert not is_geopolitical("Fed holds interest rates steady")   # macro but not geo
    assert not is_geopolitical("Nvidia earnings beat estimates")


def test_sector_and_geo_symbol_maps():
    assert SECTOR_ETFS["Technology"] == "XLK"
    assert SECTOR_ETFS["Energy"] == "XLE"
    assert "USO" in GEO_SYMBOLS and "SPY" in MARKET_SYMBOLS


def test_fetch_geo_only_filters():
    feeds = {"SPY": [
        {"title": "Sanctions on Russia widen", "link": "g1", "providerPublishTime": 300},
        {"title": "Fed keeps rates unchanged", "link": "m1", "providerPublishTime": 200},
        {"title": "Apple new iPhone", "link": "a1", "providerPublishTime": 100},
    ]}
    items = fetch_news(["SPY"], fetcher=lambda s: feeds.get(s, []), geo_only=True)
    assert [i.title for i in items] == ["Sanctions on Russia widen"]


def test_parse_old_flat_shape():
    raw = {"title": "Big move", "publisher": "Reuters", "link": "http://x/1",
           "providerPublishTime": 1700000000, "relatedTickers": ["AAPL", "MSFT"]}
    item = _parse_one(raw, "AAPL")
    assert item.title == "Big move" and item.publisher == "Reuters"
    assert item.url == "http://x/1" and item.published == 1700000000
    assert item.tickers == ["AAPL", "MSFT"]


def test_parse_new_nested_shape():
    raw = {"id": "1", "content": {
        "title": "Fed holds rates", "summary": "…",
        "provider": {"displayName": "Bloomberg"},
        "canonicalUrl": {"url": "http://x/2"},
        "pubDate": "2024-01-02T10:00:00Z"}}
    item = _parse_one(raw, "SPY")
    assert item.title == "Fed holds rates" and item.publisher == "Bloomberg"
    assert item.url == "http://x/2" and item.published > 0
    assert item.is_macro                      # "Fed" + "rates"


def _fake_fetcher(feeds):
    return lambda sym: feeds.get(sym, [])


def test_fetch_dedupes_and_sorts_newest_first():
    feeds = {
        "AAPL": [{"title": "A old", "link": "u1", "providerPublishTime": 100},
                 {"title": "shared", "link": "shared", "providerPublishTime": 300}],
        "MSFT": [{"title": "B new", "link": "u2", "providerPublishTime": 500},
                 {"title": "shared", "link": "shared", "providerPublishTime": 300}],  # dup url
    }
    items = fetch_news(["AAPL", "MSFT"], fetcher=_fake_fetcher(feeds))
    titles = [i.title for i in items]
    assert titles == ["B new", "shared", "A old"]     # newest first, deduped
    assert len(items) == 3


def test_fetch_macro_only_filters():
    feeds = {"SPY": [
        {"title": "Fed cuts interest rate", "link": "m1", "providerPublishTime": 200},
        {"title": "Nvidia earnings beat", "link": "n1", "providerPublishTime": 300},
    ]}
    items = fetch_news(["SPY"], fetcher=_fake_fetcher(feeds), macro_only=True)
    assert [i.title for i in items] == ["Fed cuts interest rate"]


def test_fetch_survives_a_failing_symbol():
    def fetcher(sym):
        if sym == "BAD":
            raise RuntimeError("network down")
        return [{"title": "ok", "link": "u", "providerPublishTime": 1}]
    items = fetch_news(["BAD", "GOOD"], fetcher=fetcher)
    assert [i.title for i in items] == ["ok"]
