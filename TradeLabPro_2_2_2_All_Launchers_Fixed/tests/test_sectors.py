"""Tests for the Scanner's sector / industry / ETF baskets
(tradelab/core/sectors.py) and their wiring into the universe list.

The central guarantee: US and Canadian baskets are separate lists, so a scan
is never a silent blend of two exchanges.
"""
import pytest

from tradelab.core.sectors import (
    US_SECTORS, CANADA_SECTORS, INDUSTRIES, ETF_BASKETS, BASKET_PREFIX, REGIONS,
    is_canadian, region_baskets, basket_choices, basket_symbols,
    scanner_universes, universe_name, split_universe_name,
)

_CA_SUFFIXES = (".TO", ".V", ".CN", ".NE")


def test_both_markets_carry_all_eleven_gics_sectors():
    assert len(US_SECTORS) == 11
    assert len(CANADA_SECTORS) == 11
    assert set(US_SECTORS) == set(CANADA_SECTORS), "sector names must match across markets"


def test_us_sectors_hold_no_canadian_listings_and_vice_versa():
    for name, symbols in US_SECTORS.items():
        assert not any(is_canadian(s) for s in symbols), f"US {name} leaked a TSX name"
    for name, symbols in CANADA_SECTORS.items():
        assert all(is_canadian(s) for s in symbols), f"Canada {name} leaked a US name"


def test_is_canadian_recognises_every_venue_suffix():
    assert is_canadian("RY.TO") and is_canadian("DML.V")
    assert is_canadian("FOO.CN") and is_canadian("BAR.NE")
    assert not is_canadian("AAPL") and not is_canadian("BRK-B")


def test_region_baskets_never_mix_markets():
    """The whole point of the separation - no basket may contain the other
    market's listings."""
    for region in REGIONS:
        for name, symbols in region_baskets(region).items():
            canadian = [s for s in symbols if is_canadian(s)]
            if region == "Canada":
                assert len(canadian) == len(symbols), f"Canada/{name} has US names"
            else:
                assert not canadian, f"US/{name} has TSX names"


def test_the_sub_sectors_the_user_asked_for_exist_in_both_markets():
    for region in REGIONS:
        baskets = region_baskets(region)
        assert "Gold & Precious Metals" in baskets
        assert "Banks" in baskets
        assert "Technology" in baskets
        assert any(n.startswith("ETFs") for n in baskets)


def test_canada_drops_baskets_with_no_domestic_names():
    """Canada has no domestic semiconductor or social-media names; those
    baskets should be absent rather than empty."""
    canada = region_baskets("Canada")
    assert "Semiconductors" not in canada
    assert "Social Media" not in canada
    assert "Semiconductors" in region_baskets("US")


def test_heatmap_themes_are_shared_not_duplicated():
    """Themes like Semiconductors are sub-sectors; both features use one copy."""
    from tradelab.core.heatmap import THEMES
    for name, symbols in THEMES.items():
        assert INDUSTRIES[name] == symbols


def test_every_basket_is_non_empty_with_unique_symbols():
    for region in REGIONS:
        for name, symbols in region_baskets(region).items():
            assert symbols, f"{region}/{name} is empty"
            assert len(set(symbols)) == len(symbols), f"{region}/{name} repeats a symbol"


def test_unknown_region_falls_back_to_us():
    assert region_baskets("Atlantis") == region_baskets("US")
    assert region_baskets("") == region_baskets("US")


def test_universe_names_carry_their_region():
    assert universe_name("Canada", "Banks") == f"{BASKET_PREFIX}Canada - Banks"
    assert split_universe_name(f"{BASKET_PREFIX}Canada - Banks") == ("Canada", "Banks")
    assert split_universe_name(f"{BASKET_PREFIX}US - Technology") == ("US", "Technology")
    assert split_universe_name("NASDAQ") == (None, "NASDAQ")


def test_basket_symbols_by_region_and_by_full_key():
    us_banks = basket_symbols("Banks", "US")
    ca_banks = basket_symbols("Banks", "Canada")
    assert "JPM" in us_banks and "RY.TO" not in us_banks
    assert "RY.TO" in ca_banks and "JPM" not in ca_banks
    # A full universe key carries its own region.
    assert basket_symbols(f"{BASKET_PREFIX}Canada - Banks") == ca_banks
    assert basket_symbols("No Such Basket", "US") == []


def test_gold_basket_splits_cleanly_between_markets():
    us = basket_symbols("Gold & Precious Metals", "US")
    ca = basket_symbols("Gold & Precious Metals", "Canada")
    assert "NEM" in us and "ABX.TO" in ca
    assert not set(us) & set(ca)


def test_basket_choices_matches_region_baskets():
    for region in REGIONS:
        assert basket_choices(region) == list(region_baskets(region).keys())
    assert len(basket_choices("US")) > len(basket_choices("Canada"))


def test_scanner_universes_cover_both_markets():
    universes = scanner_universes()
    assert f"{BASKET_PREFIX}US - Technology" in universes
    assert f"{BASKET_PREFIX}Canada - Technology" in universes
    assert len(universes) == len(region_baskets("US")) + len(region_baskets("Canada"))


def test_etf_baskets_are_defined_per_market():
    assert set(ETF_BASKETS) == set(REGIONS)
    assert all(s.endswith(_CA_SUFFIXES)
               for syms in ETF_BASKETS["Canada"].values() for s in syms)


# --- wiring into the scanner universe list --------------------------------

def test_baskets_register_as_available_universes():
    from tradelab.data.universe import available_universes
    universes = available_universes(refresh=False)
    names = [n for n in universes if n.startswith(BASKET_PREFIX)]
    assert len(names) == len(scanner_universes())


def test_list_symbols_resolves_a_regional_basket():
    from tradelab.data.universe import list_symbols
    ca = {r.symbol for r in list_symbols(exchanges=[f"{BASKET_PREFIX}Canada - Banks"])}
    us = {r.symbol for r in list_symbols(exchanges=[f"{BASKET_PREFIX}US - Banks"])}
    assert "RY.TO" in ca and "JPM" not in ca
    assert "JPM" in us and "RY.TO" not in us


def test_basket_symbols_are_tagged_with_the_right_country():
    from tradelab.data.universe import list_symbols
    rows = list_symbols(exchanges=[f"{BASKET_PREFIX}Canada - Gold & Precious Metals"])
    assert rows and all(r.country == "Canada" for r in rows)
    rows = list_symbols(exchanges=[f"{BASKET_PREFIX}US - Gold & Precious Metals"])
    assert rows and all(r.country == "US" for r in rows)


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


def _labels(panel):
    return [str(cb.property("universe_name") or "") for cb in panel.universe_checks]


def _sources(panel):
    out = []
    for cb in panel.universe_checks:
        out.extend(cb.property("universe_names") or [])
    return out


def test_scanner_offers_a_sectors_preset_and_a_market_selector(scanner_panel):
    items = [scanner_panel.country.itemText(i)
             for i in range(scanner_panel.country.count())]
    assert "Sectors / Industries" in items
    regions = [scanner_panel.sector_region.itemText(i)
               for i in range(scanner_panel.sector_region.count())]
    assert regions == list(REGIONS)
    assert scanner_panel.sector_region.currentText() == "US"


def test_market_selector_switches_which_baskets_are_listed(scanner_panel):
    scanner_panel.country.setCurrentText("Sectors / Industries")

    scanner_panel.sector_region.setCurrentText("US")
    us_sources = _sources(scanner_panel)
    assert us_sources and all(f"{BASKET_PREFIX}US - " in s for s in us_sources)

    scanner_panel.sector_region.setCurrentText("Canada")
    ca_sources = _sources(scanner_panel)
    assert ca_sources and all(f"{BASKET_PREFIX}Canada - " in s for s in ca_sources)
    # Never both at once - that separation is the point.
    assert not set(us_sources) & set(ca_sources)


def test_basket_labels_drop_the_region_the_dropdown_already_states(scanner_panel):
    scanner_panel.country.setCurrentText("Sectors / Industries")
    scanner_panel.sector_region.setCurrentText("Canada")
    labels = _labels(scanner_panel)
    assert f"{BASKET_PREFIX}Banks" in labels
    assert not any("Canada -" in l for l in labels)


def test_sector_baskets_are_grouped_under_sectors_not_etfs(scanner_panel):
    """An ETF basket is still a sector choice - it must not fall into the
    generic ETFs group, whose rule also matches the word 'ETF'."""
    group = scanner_panel._exchange_group_for_universe_name(
        f"{BASKET_PREFIX}US - ETFs - Commodities & metals")
    assert group == "Sectors"


def test_sectors_shortcut_selects_only_baskets(scanner_panel):
    scanner_panel.country.setCurrentText("All Exchanges")
    scanner_panel.select_exchange_shortcut("Sectors")
    for cb in scanner_panel.universe_checks:
        label = str(cb.property("universe_name") or "")
        assert cb.isChecked() == label.startswith(BASKET_PREFIX)


def test_selecting_a_canadian_sector_scans_only_canadian_symbols(scanner_panel):
    scanner_panel.country.setCurrentText("Sectors / Industries")
    scanner_panel.sector_region.setCurrentText("Canada")
    for cb in scanner_panel.universe_checks:
        cb.setChecked(str(cb.property("universe_name") or "")
                      == f"{BASKET_PREFIX}Gold & Precious Metals")

    symbols = set(scanner_panel.current_symbols())
    assert symbols == set(basket_symbols("Gold & Precious Metals", "Canada"))
    assert all(is_canadian(s) for s in symbols)
    assert "NEM" not in symbols and "ABX.TO" in symbols
