"""Tests for the Scanner's sector / industry / ETF baskets
(tradelab/core/sectors.py) and their wiring into the universe list."""
import pytest

from tradelab.core.sectors import (
    SECTORS, INDUSTRIES, ETF_BASKETS, BASKET_PREFIX,
    all_baskets, basket_choices, basket_symbols, scanner_universes,
)


def test_all_eleven_gics_sectors_are_present():
    assert len(SECTORS) == 11
    for expected in ("Technology", "Financials", "Energy", "Health Care",
                     "Utilities", "Materials", "Real Estate"):
        assert expected in SECTORS


def test_the_sub_sectors_the_user_asked_for_exist():
    """Gold, finance and tech cuts must be reachable by name."""
    assert "Gold & Precious Metals" in INDUSTRIES
    assert "Banks" in INDUSTRIES
    assert "Technology" in SECTORS
    assert any(name.startswith("ETFs") for name in ETF_BASKETS)


def test_heatmap_themes_are_shared_not_duplicated():
    """Themes like Semiconductors are sub-sectors; both features use one copy."""
    from tradelab.core.heatmap import THEMES
    for name, symbols in THEMES.items():
        assert INDUSTRIES[name] == symbols


def test_every_basket_is_non_empty_with_unique_symbols():
    for name, symbols in all_baskets().items():
        assert symbols, f"{name} is empty"
        assert len(set(symbols)) == len(symbols), f"{name} repeats a symbol"
        assert all(isinstance(s, str) and s.strip() for s in symbols)


def test_basket_symbols_accepts_bare_and_prefixed_names():
    bare = basket_symbols("Gold & Precious Metals")
    prefixed = basket_symbols(f"{BASKET_PREFIX}Gold & Precious Metals")
    assert bare == prefixed
    assert "NEM" in bare
    assert basket_symbols("No Such Basket") == []
    assert basket_symbols("") == []


def test_basket_choices_matches_all_baskets():
    assert basket_choices() == list(all_baskets().keys())
    assert len(basket_choices()) > 30


def test_scanner_universes_are_prefixed():
    universes = scanner_universes()
    assert all(name.startswith(BASKET_PREFIX) for name in universes)
    assert f"{BASKET_PREFIX}Technology" in universes


def test_gold_basket_spans_both_countries():
    """Miners list on both sides of the border - the basket should too."""
    gold = basket_symbols("Gold & Precious Metals")
    assert any(s.endswith(".TO") for s in gold)
    assert any("." not in s for s in gold)


# --- wiring into the scanner universe list --------------------------------

def test_baskets_register_as_available_universes():
    from tradelab.data.universe import available_universes
    universes = available_universes(refresh=False)
    names = [n for n in universes if n.startswith(BASKET_PREFIX)]
    assert len(names) == len(all_baskets())
    assert universes[f"{BASKET_PREFIX}Technology"]


def test_list_symbols_resolves_a_basket():
    from tradelab.data.universe import list_symbols
    rows = list_symbols(exchanges=[f"{BASKET_PREFIX}Banks"])
    symbols = {r.symbol for r in rows}
    assert "JPM" in symbols and "RY.TO" in symbols


def test_basket_country_filter_is_per_symbol():
    """A basket mixes US and Canadian listings, so 'All USA' must not drop the
    whole basket - just its Canadian names (and vice versa)."""
    from tradelab.data.universe import list_symbols
    name = f"{BASKET_PREFIX}Gold & Precious Metals"
    us = list_symbols(exchanges=[name], countries=["US"])
    ca = list_symbols(exchanges=[name], countries=["Canada"])

    assert us and ca, "both sides of the basket should survive their filter"
    assert all(not r.symbol.endswith((".TO", ".V")) for r in us)
    assert all(r.symbol.endswith((".TO", ".V")) for r in ca)
    assert all(r.country == "Canada" for r in ca)
    assert len(us) + len(ca) == len(list_symbols(exchanges=[name]))


# --- Scanner UI exposure ---------------------------------------------------

@pytest.fixture
def scanner_panel(tmp_db_path, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    pytest.importorskip("pyqtgraph")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setattr("tradelab.ui.app.DATA_DIR", tmp_path)
    from tradelab.data.database import Database
    from tradelab.ui.chart_widget import ChartWidget
    from tradelab.ui.app import ScannerPanel
    db = Database(tmp_db_path)
    panel = ScannerPanel(db, ChartWidget())
    yield panel
    db.conn.close()


def _checkbox_labels(panel):
    return [str(cb.property("universe_name") or "") for cb in panel.universe_checks]


def test_scanner_offers_a_sectors_preset(scanner_panel):
    items = [scanner_panel.country.itemText(i)
             for i in range(scanner_panel.country.count())]
    assert "Sectors / Industries" in items


def test_sector_baskets_appear_as_scanner_checkboxes(scanner_panel):
    scanner_panel.country.setCurrentText("Sectors / Industries")
    labels = _checkbox_labels(scanner_panel)
    assert labels, "sector preset should list the baskets"
    assert all(l.startswith(BASKET_PREFIX) for l in labels)
    assert f"{BASKET_PREFIX}Gold & Precious Metals" in labels
    assert f"{BASKET_PREFIX}Technology" in labels


def test_sector_baskets_are_grouped_under_sectors_not_etfs(scanner_panel):
    """An ETF basket is still a sector choice - it must not fall into the
    generic ETFs group, whose rule also matches the word 'ETF'."""
    group = scanner_panel._exchange_group_for_universe_name(
        f"{BASKET_PREFIX}ETFs - Commodities & metals")
    assert group == "Sectors"


def test_sectors_shortcut_selects_only_baskets(scanner_panel):
    scanner_panel.country.setCurrentText("All Exchanges")
    scanner_panel.select_exchange_shortcut("Sectors")
    for cb in scanner_panel.universe_checks:
        label = str(cb.property("universe_name") or "")
        assert cb.isChecked() == label.startswith(BASKET_PREFIX)


def test_selecting_a_sector_basket_scans_only_its_symbols(scanner_panel):
    scanner_panel.country.setCurrentText("Sectors / Industries")
    for cb in scanner_panel.universe_checks:
        cb.setChecked(str(cb.property("universe_name") or "")
                      == f"{BASKET_PREFIX}Gold & Precious Metals")

    symbols = set(scanner_panel.current_symbols())
    assert symbols == set(basket_symbols("Gold & Precious Metals"))
    assert "NEM" in symbols and "AAPL" not in symbols
