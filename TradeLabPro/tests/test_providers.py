"""Data-source provider abstraction tests - offline."""
import pandas as pd
import pytest

from tradelab.data import providers
import tradelab.data.market_data as market_data


@pytest.fixture(autouse=True)
def _reset_provider():
    # Always leave the active source back at the default so provider switches
    # in one test don't leak into another (or the real app).
    providers.set_active(providers.DEFAULT)
    market_data._quote_meta_cache.clear()
    yield
    providers.set_active(providers.DEFAULT)
    market_data._quote_meta_cache.clear()


def test_builtin_providers_registered():
    names = providers.provider_names()
    assert "Yahoo Finance" in names
    assert "Offline (synthetic)" in names


def test_default_active_is_yahoo():
    assert providers.active_name() == "Yahoo Finance"


def test_set_active_switches_and_rejects_unknown():
    assert providers.set_active("Offline (synthetic)") is True
    assert providers.active_name() == "Offline (synthetic)"
    assert providers.set_active("Nonexistent") is False
    assert providers.active_name() == "Offline (synthetic)"   # unchanged


def test_synthetic_provider_history_is_offline_and_deterministic():
    providers.set_active("Offline (synthetic)")
    df1 = market_data.get_history("ANYTHING", "1y", "1d")
    df2 = market_data.get_history("ANYTHING", "1y", "1d")
    assert isinstance(df1, pd.DataFrame) and not df1.empty
    assert list(df1.columns) == ["Open", "High", "Low", "Close", "Volume"]
    pd.testing.assert_frame_equal(df1, df2)                   # deterministic


def test_synthetic_provider_meta_is_deterministic_unknown_sector():
    providers.set_active("Offline (synthetic)")
    m = market_data.get_quote_meta("ZZZZ")
    assert m["sector"] == "Unknown" and m["name"] == "ZZZZ"
    assert m["market_cap"] > 0
    market_data._quote_meta_cache.clear()
    assert market_data.get_quote_meta("ZZZZ")["market_cap"] == m["market_cap"]


def test_switching_provider_clears_quote_cache(monkeypatch):
    # Prime the cache under a fake Yahoo, then switch source -> cache cleared.
    class _FakeTicker:
        def __init__(self, info): self.info = info
    monkeypatch.setattr(market_data, "yf", type("_yf", (), {
        "Ticker": staticmethod(lambda s: _FakeTicker({"marketCap": 5e11, "sector": "Technology"}))}))
    assert market_data.get_quote_meta("AAA")["sector"] == "Technology"
    assert "AAA" in market_data._quote_meta_cache
    providers.set_active("Offline (synthetic)")
    assert market_data._quote_meta_cache == {}                # switch invalidated it
    assert market_data.get_quote_meta("AAA")["sector"] == "Unknown"   # now synthetic


def test_yahoo_history_still_falls_back_offline():
    # Default (Yahoo) path with no network -> synthetic fallback, never raises.
    df = market_data.get_history("AAPL", "6mo", "1d")
    assert isinstance(df, pd.DataFrame) and not df.empty
