"""Tests for the core scan_symbols() engine in tradelab/core/scanner.py.

get_history/get_quote_meta are monkeypatched so these run fast and
deterministically without touching the network.
"""
import pandas as pd
import pytest

import tradelab.core.scanner as scanner_module
from tradelab.core.config import ScannerConfig
from tradelab.core.filters import FilterCondition
from tradelab.core.scanner import scan_symbols


@pytest.fixture
def permissive_cfg():
    cfg = ScannerConfig()
    cfg.min_price = 0
    cfg.min_volume = 0
    cfg.min_market_cap = 0
    cfg.min_score = 0
    return cfg


@pytest.fixture(autouse=True)
def _fake_history_and_meta(monkeypatch, ohlcv_df):
    monkeypatch.setattr(scanner_module, "get_history", lambda symbol, period, interval: ohlcv_df)
    monkeypatch.setattr(scanner_module, "get_quote_meta", lambda symbol: {
        "market_cap": 50_000_000_000.0, "sector": "Technology", "industry": "Software",
    })


def test_scan_symbols_includes_cap_and_sector_columns(permissive_cfg):
    df = scan_symbols(["AAPL"], permissive_cfg)
    assert not df.empty
    assert "Cap" in df.columns
    assert "Sector" in df.columns
    assert df.iloc[0]["Sector"] == "Technology"
    assert df.iloc[0]["Cap"] == "Large"  # 50B -> Large bucket


def test_scan_symbols_market_cap_filter_uses_real_meta(monkeypatch, ohlcv_df, permissive_cfg):
    monkeypatch.setattr(scanner_module, "get_quote_meta", lambda symbol: {
        "market_cap": 1_000_000.0, "sector": "Energy", "industry": "Oil & Gas",
    })
    permissive_cfg.min_market_cap = 2_000_000_000  # symbol's cap is far below this
    df = scan_symbols(["AAPL"], permissive_cfg)
    assert df.empty


def test_scan_symbols_applies_custom_filters(permissive_cfg):
    permissive_cfg.custom_filters = [FilterCondition(field="rsi14", operator="Below", value1=1).to_dict()]
    df = scan_symbols(["AAPL"], permissive_cfg)
    assert df.empty  # RSI < 1 is effectively impossible


def test_scan_symbols_error_rows_have_empty_cap_and_sector(monkeypatch, permissive_cfg):
    def raise_error(symbol, period, interval):
        raise RuntimeError("boom")
    monkeypatch.setattr(scanner_module, "get_history", raise_error)

    df = scan_symbols(["BADSYM"], permissive_cfg)
    assert len(df) == 1
    assert df.iloc[0]["Signal"] == "ERROR"
    assert df.iloc[0]["Cap"] == ""
    assert df.iloc[0]["Sector"] == ""
