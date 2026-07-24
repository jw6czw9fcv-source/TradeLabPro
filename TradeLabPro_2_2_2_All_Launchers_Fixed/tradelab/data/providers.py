"""Pluggable market-data providers (data-source abstraction).

The rest of the app fetches prices and metadata through
`market_data.get_history()` / `get_quote_meta()`, which delegate to whichever
`DataProvider` is *active*. Two are built in:

* **Yahoo Finance** - the default live source (yfinance), with the existing
  offline synthetic fallback when a symbol/feed fails.
* **Offline (synthetic)** - deterministic generated data, no network at all;
  handy for demos, tests, or when a feed is down.

Adding another source (Alpaca, Polygon, an IBKR data feed, ...) is just a new
`DataProvider` subclass plus a `register(...)` call - no caller changes. This
keeps the app from being hard-wired to a single, fragile dependency.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataProvider(ABC):
    name: str = "provider"
    requires_network: bool = True
    description: str = ""

    @abstractmethod
    def get_history(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        ...

    @abstractmethod
    def get_quote_meta(self, symbol: str) -> dict:
        ...

    def get_histories(self, symbols, period: str = "1y", interval: str = "1d") -> dict:
        """Fetch history for many symbols -> {symbol: DataFrame}. The default is a
        serial loop over get_history(); providers backed by a source that accepts
        a whole ticker list in one request (e.g. Yahoo) override this to avoid the
        per-symbol rate-limiting a long serial refresh hits."""
        return {s: self.get_history(s, period, interval) for s in dict.fromkeys(symbols)}

    def available(self) -> bool:
        return True


class YahooProvider(DataProvider):
    name = "Yahoo Finance"
    requires_network = True
    description = "Live prices & fundamentals via Yahoo (yfinance); synthetic fallback if a symbol fails."

    def get_history(self, symbol, period="1y", interval="1d"):
        from tradelab.data import market_data as md
        return md._yahoo_history(symbol, period, interval)

    def get_quote_meta(self, symbol):
        from tradelab.data import market_data as md
        return md._yahoo_quote_meta(symbol)

    def get_histories(self, symbols, period="1y", interval="1d"):
        from tradelab.data import market_data as md
        return md._yahoo_histories(symbols, period, interval)

    def available(self):
        from tradelab.data import market_data as md
        return md.yf is not None


class SyntheticProvider(DataProvider):
    name = "Offline (synthetic)"
    requires_network = False
    description = "Deterministic generated data, no network. Good for demos/testing or when a feed is down."

    def get_history(self, symbol, period="1y", interval="1d"):
        from tradelab.data.market_data import synthetic_ohlcv
        return synthetic_ohlcv(symbol)

    def get_quote_meta(self, symbol):
        # Deterministic per-symbol market cap, same formula the live provider
        # uses as its own offline fallback, so filters stay usable offline.
        cap = float(3_000_000_000 + (abs(hash(symbol)) % 300_000_000_000))
        return {"market_cap": cap, "sector": "Unknown", "industry": "Unknown",
                "country": "Unknown", "name": symbol, "quote_type": ""}


# --- registry ---------------------------------------------------------------

DEFAULT = "Yahoo Finance"
_REGISTRY: dict = {}
_active_name: str = DEFAULT


def register(provider: DataProvider) -> None:
    _REGISTRY[provider.name] = provider


def provider_names() -> list:
    return list(_REGISTRY.keys())


def providers() -> list:
    return list(_REGISTRY.values())


def get(name: str):
    return _REGISTRY.get(name)


def active() -> DataProvider:
    global _active_name
    if _active_name not in _REGISTRY:
        _active_name = DEFAULT if DEFAULT in _REGISTRY else next(iter(_REGISTRY))
    return _REGISTRY[_active_name]


def active_name() -> str:
    active()          # normalise if the active name went stale
    return _active_name


def set_active(name: str) -> bool:
    """Switch the active source. Invalidates the quote-metadata cache so the
    next lookups come from the new source. Returns False for an unknown name."""
    global _active_name
    if name not in _REGISTRY:
        return False
    _active_name = name
    try:
        from tradelab.data import market_data as md
        md._quote_meta_cache.clear()
    except Exception:
        pass
    return True


register(YahooProvider())
register(SyntheticProvider())
