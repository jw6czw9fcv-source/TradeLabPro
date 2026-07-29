"""Notes scratchpad core tests - offline."""
from tradelab.core.notes import load_notes, save_notes


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "notes.txt"
    assert load_notes(path) == ""            # missing file -> empty
    save_notes("my trading plan\n- rule 1\n- rule 2", path)
    assert load_notes(path) == "my trading plan\n- rule 1\n- rule 2"


def test_save_overwrites(tmp_path):
    path = tmp_path / "notes.txt"
    save_notes("first", path)
    save_notes("second", path)
    assert load_notes(path) == "second"


def test_save_none_is_safe(tmp_path):
    path = tmp_path / "notes.txt"
    save_notes(None, path)
    assert load_notes(path) == ""
