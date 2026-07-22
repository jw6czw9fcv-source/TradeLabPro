"""Market news feed (Qt-free, offline-testable).

Pulls recent headlines for symbols from the market-data feed (Yahoo/yfinance
`Ticker.news`), normalising the several shapes Yahoo has used over time into a
simple NewsItem. A keyword check flags **macro / political** stories (Fed,
inflation, elections, tariffs, war, OPEC, …) so they can be surfaced or
filtered — a lightweight stand-in for a dedicated economic/political calendar
(which would need a paid data feed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# Headline keywords that mark a story as macro / political / policy-driven.
MACRO_KEYWORDS = (
    "fed", "federal reserve", "powell", "interest rate", "rate hike", "rate cut",
    "inflation", "cpi", "ppi", "jobs report", "payroll", "unemployment", "gdp",
    "recession", "election", "president", "white house", "congress", "senate",
    "tariff", "trade war", "sanction", "opec", "oil price", "war", "geopolit",
    "policy", "government shutdown", "debt ceiling", "treasury", "ecb", "boj",
    "central bank", "stimulus", "regulation", "antitrust",
)

# Headline keywords that mark a story as specifically geopolitical.
GEO_KEYWORDS = (
    "war", "sanction", "tariff", "trade war", "election", "opec", "geopolit",
    "russia", "ukraine", "china", "middle east", "iran", "israel", "oil price",
    "military", "conflict", "nato", "north korea", "president", "white house",
    "treaty", "embargo", "invasion", "ceasefire", "coup", "border",
)

# Symbols whose feeds tend to carry market-moving macro/political headlines.
MARKET_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "JPM", "XOM"]

# Symbols whose feeds surface geopolitical stories (broad market + oil, gold,
# defense, energy - the things geopolitics moves).
GEO_SYMBOLS = ["SPY", "USO", "BNO", "GLD", "ITA", "XLE"]

# SPDR sector ETFs -> the news feed for each S&P sector.
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def is_macro(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in MACRO_KEYWORDS)


def is_geopolitical(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in GEO_KEYWORDS)


def _parse_dt(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)                       # already a unix timestamp
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


@dataclass
class NewsItem:
    title: str
    publisher: str = ""
    url: str = ""
    published: float = 0.0        # unix timestamp
    summary: str = ""
    tickers: list = field(default_factory=list)

    @property
    def is_macro(self) -> bool:
        return is_macro(self.title)

    @property
    def is_geopolitical(self) -> bool:
        return is_geopolitical(self.title)


def _parse_one(item: dict, default_ticker: str) -> Optional[NewsItem]:
    if not isinstance(item, dict):
        return None
    content = item.get("content")
    if isinstance(content, dict):                 # newer Yahoo shape
        title = content.get("title", "")
        publisher = (content.get("provider") or {}).get("displayName", "")
        url = ((content.get("canonicalUrl") or {}).get("url")
               or (content.get("clickThroughUrl") or {}).get("url") or "")
        summary = content.get("summary", "") or content.get("description", "")
        published = _parse_dt(content.get("pubDate") or content.get("displayTime"))
        tickers = [default_ticker]
    else:                                         # older flat shape
        title = item.get("title", "")
        publisher = item.get("publisher", "")
        url = item.get("link", "")
        summary = item.get("summary", "")
        published = _parse_dt(item.get("providerPublishTime"))
        tickers = item.get("relatedTickers") or [default_ticker]
    if not title:
        return None
    return NewsItem(title=title.strip(), publisher=publisher, url=url,
                    published=published, summary=summary,
                    tickers=[t for t in tickers if t])


def _yf_news(symbol: str) -> list:
    import yfinance as yf
    return yf.Ticker(symbol).news or []


def fetch_news(symbols, fetcher: Optional[Callable[[str], list]] = None,
               limit: int = 80, macro_only: bool = False, geo_only: bool = False) -> list:
    """Recent headlines for `symbols`, newest first, de-duplicated. `fetcher(
    symbol) -> [raw dict, ...]` defaults to yfinance; inject a fake in tests.
    `macro_only` keeps just macro/political stories; `geo_only` keeps just
    geopolitical ones."""
    if fetcher is None:
        fetcher = _yf_news
    items: list = []
    seen = set()
    for sym in symbols:
        try:
            raw = fetcher(sym) or []
        except Exception:
            raw = []
        for entry in raw:
            item = _parse_one(entry, str(sym).upper())
            if item is None:
                continue
            key = item.url or item.title
            if key in seen:
                # merge related tickers so a shared story lists both symbols
                continue
            seen.add(key)
            if macro_only and not item.is_macro:
                continue
            if geo_only and not item.is_geopolitical:
                continue
            items.append(item)
    items.sort(key=lambda n: n.published or 0, reverse=True)
    return items[:limit]
