"""Free-form notes scratchpad (Qt-free, offline-testable).

A single persistent notes document — trading plan, watch ideas, reminders —
saved as plain text in data/notes.txt. The UI (NotesPanel) auto-saves it.
"""
from __future__ import annotations

from pathlib import Path

from tradelab.core.config import DATA_DIR

NOTES_PATH = DATA_DIR / "notes.txt"


def load_notes(path: str | Path | None = None) -> str:
    p = Path(path) if path else NOTES_PATH
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def save_notes(text: str, path: str | Path | None = None) -> None:
    p = Path(path) if path else NOTES_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text if text is not None else "", encoding="utf-8")
    except Exception:
        pass
