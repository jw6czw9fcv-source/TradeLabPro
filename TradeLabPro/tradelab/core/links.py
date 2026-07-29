"""Saved links / bookmarks (Qt-free, offline-testable).

A small personal bookmark list: name + URL (+ optional group and notes) for the
research sites, broker pages, news, and screeners you use. Stored locally in
data/links.json; opening a link is the UI layer's job (default browser).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from tradelab.core.config import DATA_DIR

LINKS_PATH = DATA_DIR / "links.json"

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def normalize_url(url: str) -> str:
    """Tidy a user-typed URL: trim it and default the scheme to https:// when
    none was given (so 'finviz.com/map' becomes 'https://finviz.com/map')."""
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if not _SCHEME_RE.match(u):
        u = "https://" + u
    return u


@dataclass
class Link:
    name: str
    url: str
    group: str = ""
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.name = (self.name or "").strip()
        self.url = normalize_url(self.url)
        self.group = (self.group or "").strip()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "url": self.url,
                "group": self.group, "notes": self.notes, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, data: dict) -> "Link":
        link = cls(name=data.get("name", ""), url=data.get("url", ""),
                   group=data.get("group", ""), notes=data.get("notes", ""))
        if data.get("id"):
            link.id = data["id"]
        if data.get("created_at") is not None:
            link.created_at = float(data["created_at"])
        return link


class LinkStore:
    """JSON-backed list of Links (data/links.json, gitignored per-user data)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else LINKS_PATH
        self._links: list = []
        self.load()

    def all(self) -> list:
        return list(self._links)

    def get(self, link_id: str) -> Optional[Link]:
        return next((l for l in self._links if l.id == link_id), None)

    def add(self, link: Link) -> Link:
        self._links.append(link)
        self.save()
        return link

    def update(self, link_id: str, name=None, url=None, group=None, notes=None) -> bool:
        link = self.get(link_id)
        if link is None:
            return False
        if name is not None:
            link.name = name.strip()
        if url is not None:
            link.url = normalize_url(url)
        if group is not None:
            link.group = group.strip()
        if notes is not None:
            link.notes = notes
        self.save()
        return True

    def remove(self, link_id: str) -> bool:
        before = len(self._links)
        self._links = [l for l in self._links if l.id != link_id]
        changed = len(self._links) != before
        if changed:
            self.save()
        return changed

    def load(self) -> list:
        self._links = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._links = [Link.from_dict(d) for d in data.get("links", [])]
            except Exception:
                self._links = []
        return self._links

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"links": [l.to_dict() for l in self._links]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
