"""Is there a newer TradeLab than the one running? (Qt-free, offline-testable.)

Two places can say so:

* **an installer folder** - where `tools/build_release.py` writes
  `TradeLabPro-Setup-X.Y.Z.exe`. A newer installer there can be run in one
  click, which is the whole point: the installed app had fallen two months
  behind the source without anyone noticing.
* **GitHub's tags** - a release can be published before its installer is
  built on this PC; then the app can only say that it exists.

Nothing here downloads or runs anything; the UI decides what to do.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

GITHUB_TAGS_URL = "https://api.github.com/repos/jw6czw9fcv-source/TradeLabPro/tags"
INSTALLER_RE = re.compile(r"^TradeLabPro-Setup-(\d+(?:\.\d+)*)\.exe$", re.IGNORECASE)


def parse_version(text) -> tuple:
    """'2.53.0 Waiting for a pension' / 'v2.53.0' -> (2, 53, 0); () when none."""
    m = re.search(r"(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def version_text(version: tuple) -> str:
    return ".".join(str(p) for p in version)


def installers_in(folder) -> list:
    """[(version, path)] of the installers in folder, newest first."""
    try:
        entries = list(Path(folder).iterdir()) if folder else []
    except OSError:
        return []
    found = []
    for path in entries:
        m = INSTALLER_RE.match(path.name)
        if m and path.is_file():
            found.append((parse_version(m.group(1)), path))
    return sorted(found, reverse=True)


def newer_installer(folder, current) -> Optional[tuple]:
    """(version, path) of the newest installer in folder that is newer than
    the running version, else None."""
    mine = parse_version(current)
    for version, path in installers_in(folder):
        if version > mine:
            return version, path
        break
    return None


def _http_get(url: str, timeout: float = 6.0) -> bytes:
    from urllib.request import Request, urlopen
    req = Request(url, headers={"Accept": "application/vnd.github+json",
                                "User-Agent": "TradeLabPro-update-check"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def latest_published(fetch: Callable[[str], bytes] = _http_get) -> Optional[tuple]:
    """The highest release version tagged on GitHub, or None if it can't be read."""
    try:
        tags = json.loads(fetch(GITHUB_TAGS_URL))
    except Exception:
        return None
    versions = [parse_version(t.get("name")) for t in tags if isinstance(t, dict)]
    versions = [v for v in versions if v]
    return max(versions) if versions else None
