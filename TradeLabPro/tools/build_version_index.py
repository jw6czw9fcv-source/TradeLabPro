#!/usr/bin/env python3
"""Build docs/VERSIONS.md — one line per release, newest first.

The CHANGELOG says what changed and runs to tens of thousands of words; this
is the index to it: version, date, and the one line that release was about.
Generated rather than hand-kept, because a hand-kept index is one more thing
to forget on release day and it goes stale silently.

Sources, each for what it actually knows:
  * CHANGELOG.md  - which versions exist and what each was called
  * git tags      - when the release was actually cut

A version with no tag is reported as unreleased rather than given a guessed
date. Run it after tagging:

    python tools/build_version_index.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
OUTPUT = ROOT / "docs" / "VERSIONS.md"

HEADING = re.compile(r"^##\s+(\d+\.\d+(?:\.\d+)?)\s*[-–—]\s*(.+?)\s*$", re.M)

HEADER = """# TradeLab Pro — version history

Every release, newest first. **Generated** by `tools/build_version_index.py`
from `CHANGELOG.md` (which versions exist, and what each was about) and the
git tags (when each was cut) — don't edit this file by hand, rebuild it.

The full entry for any version, including what it deliberately does *not* do,
is in [CHANGELOG.md](../CHANGELOG.md). The version the app reports is in
`VERSION` and `tradelab/core/config.py`.

| Version | Date | What shipped |
| --- | --- | --- |
"""

FOOTER = """
{count} releases. Two kinds of row carry no date, and they are not the same
thing: **unreleased** is newer than every tag — built and committed, not yet
tagged (the convention is to tag after pushing: `git tag -a vX.Y.Z -m "…"`).
**no tag of its own** is older than the newest tag: it shipped inside a later
release, or predates the tagging convention.
"""


def _as_tuple(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def changelog_versions(text: str) -> list[tuple[str, str]]:
    """[(version, title)] in the order the CHANGELOG lists them."""
    return [(m.group(1), m.group(2).strip()) for m in HEADING.finditer(text)]


def tag_dates() -> dict[str, str]:
    """{version: YYYY-MM-DD} from annotated tags. Empty if git isn't available
    — the index still builds, it just can't date anything."""
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "--format=%(refname:short)|%(creatordate:short)"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    dates = {}
    for line in out.splitlines():
        name, _, date = line.partition("|")
        name = name.strip()
        if name.startswith("v") and date.strip():
            dates[name[1:]] = date.strip()
    return dates


def build(changelog_text: str, dates: dict[str, str]) -> str:
    newest_tagged = max((_as_tuple(v) for v in dates), default=())
    rows = []
    for version, title in changelog_versions(changelog_text):
        date = dates.get(version)
        if date is None:
            # An untagged version older than the newest tag shipped inside a
            # later release; calling that "unreleased" would be wrong.
            date = ("*unreleased*" if _as_tuple(version) > newest_tagged
                    else "*no tag of its own*")
        # Pipes would break the table; titles are free text in the CHANGELOG.
        rows.append(f"| **{version}** | {date} | {title.replace('|', '/')} |")
    return HEADER + "\n".join(rows) + "\n" + FOOTER.format(count=len(rows))


def main():
    text = CHANGELOG.read_text(encoding="utf-8")
    page = build(text, tag_dates())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(changelog_versions(text))} releases).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
