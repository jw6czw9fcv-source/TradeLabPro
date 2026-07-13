"""Tests for symbol-universe validation in tradelab/data/universe.py."""
import pytest

from tradelab.data.universe import is_tradeable_symbol


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "RY.TO", "SHOP.TO", "BRK.B", "A", "AB1", "1A"])
def test_real_tickers_are_tradeable(symbol):
    assert is_tradeable_symbol(symbol) is True


@pytest.mark.parametrize("symbol", ["41", "123", "0", "999", "1.5"])
def test_purely_numeric_junk_is_rejected(symbol):
    # Regression test: "41" showed up as a scan result row - a real ticker
    # always has at least one letter, so a purely numeric string is junk
    # from a bad feed line, not a tradeable symbol.
    assert is_tradeable_symbol(symbol) is False


@pytest.mark.parametrize("symbol", ["", "NAN", "NONE", "AA^B", "AA$", "AA:B", "AA|B", "AA=B"])
def test_empty_or_flagged_junk_is_rejected(symbol):
    assert is_tradeable_symbol(symbol) is False


@pytest.mark.parametrize("symbol", ["ABC-W", "ABC-WS", "ABC-WT", "ABC-R", "ABC-U"])
def test_rights_warrants_units_are_skipped(symbol):
    assert is_tradeable_symbol(symbol) is False
