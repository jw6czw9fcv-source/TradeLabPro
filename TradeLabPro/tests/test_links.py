"""Saved-links engine tests - pure/offline."""
from tradelab.core.links import Link, LinkStore, normalize_url


def test_normalize_url_defaults_https():
    assert normalize_url("finviz.com/map.ashx") == "https://finviz.com/map.ashx"
    assert normalize_url("  example.com  ") == "https://example.com"
    assert normalize_url("http://x.com") == "http://x.com"      # scheme kept
    assert normalize_url("https://x.com") == "https://x.com"
    assert normalize_url("//cdn.x.com") == "https://cdn.x.com"
    assert normalize_url("") == ""


def test_link_normalizes_on_construction():
    link = Link(name="  Finviz Map  ", url="finviz.com/map.ashx", group=" Screeners ")
    assert link.name == "Finviz Map"
    assert link.url == "https://finviz.com/map.ashx"
    assert link.group == "Screeners"


def test_roundtrip_to_from_dict():
    link = Link(name="IBKR", url="interactivebrokers.com", group="Broker", notes="portal")
    restored = Link.from_dict(link.to_dict())
    assert restored.id == link.id
    assert restored.name == "IBKR" and restored.url == "https://interactivebrokers.com"
    assert restored.group == "Broker" and restored.notes == "portal"


def test_store_add_update_remove_persist(tmp_path):
    path = tmp_path / "links.json"
    store = LinkStore(path)
    assert store.all() == []
    link = store.add(Link(name="Yahoo", url="finance.yahoo.com"))
    assert len(store.all()) == 1 and path.exists()

    assert store.update(link.id, name="Yahoo Finance", url="finance.yahoo.com/quote")
    reloaded = LinkStore(path)
    got = reloaded.get(link.id)
    assert got.name == "Yahoo Finance"
    assert got.url == "https://finance.yahoo.com/quote"

    assert reloaded.remove(link.id) is True
    assert LinkStore(path).all() == []


def test_update_unknown_id_returns_false(tmp_path):
    store = LinkStore(tmp_path / "links.json")
    assert store.update("nope", name="x") is False


def test_store_survives_corrupt_file(tmp_path):
    path = tmp_path / "links.json"
    path.write_text("{ not json", encoding="utf-8")
    assert LinkStore(path).all() == []
