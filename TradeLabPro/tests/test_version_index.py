"""Tests for docs/VERSIONS.md and its generator.

The point of a generated index is that it cannot drift from the CHANGELOG, so
the load-bearing test is the last one: the committed file has to match what
the generator produces today.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_version_index import (  # noqa: E402
    build, changelog_versions, tag_dates,
)

CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
VERSIONS = ROOT / "docs" / "VERSIONS.md"


def test_every_changelog_version_is_parsed():
    versions = changelog_versions(CHANGELOG)
    assert len(versions) > 40
    numbers = [v for v, _title in versions]
    assert "2.41.0" in numbers
    assert len(set(numbers)) == len(numbers), "a version is listed twice"


def test_versions_are_listed_newest_first():
    def as_tuple(v):
        return tuple(int(p) for p in v.split("."))
    numbers = [as_tuple(v) for v, _t in changelog_versions(CHANGELOG)]
    assert numbers == sorted(numbers, reverse=True)


def test_every_version_carries_a_title():
    for version, title in changelog_versions(CHANGELOG):
        assert title.strip(), f"{version} has no title"


def test_a_tagged_version_gets_its_tag_date():
    page = build("## 2.40.0 - Retirement tab\n", {"2.40.0": "2026-08-08"})
    assert "| **2.40.0** | 2026-08-08 | Retirement tab |" in page


def test_a_version_newer_than_every_tag_reads_unreleased():
    page = build("## 2.41.0 - New thing\n", {"2.40.0": "2026-08-08"})
    assert "*unreleased*" in page


def test_a_version_older_than_the_newest_tag_is_not_called_unreleased():
    """2.39.0 shipped inside 2.40.0's tag. Reporting it as unreleased would
    say the opposite of what happened."""
    page = build("## 2.39.0 - Folded in\n", {"2.40.0": "2026-08-08"})
    row = [line for line in page.splitlines() if line.startswith("| **2.39.0**")][0]
    assert "unreleased" not in row
    assert "*no tag of its own*" in row


def test_titles_cannot_break_the_table():
    page = build("## 9.9.9 - A | pipe | title\n", {})
    rows = [line for line in page.splitlines() if line.startswith("| **9.9.9**")]
    assert len(rows) == 1
    assert rows[0].count("|") == 4      # leading, two separators, trailing


def test_build_survives_having_no_tags_at_all():
    page = build("## 1.0.0 - First\n", {})
    assert "1.0.0" in page


def test_the_committed_index_is_up_to_date():
    """Regenerating must be a no-op. If this fails, run
    `python tools/build_version_index.py` and commit the result."""
    assert VERSIONS.exists(), "docs/VERSIONS.md has never been generated"
    expected = build(CHANGELOG, tag_dates())
    assert VERSIONS.read_text(encoding="utf-8") == expected


def test_the_index_covers_the_current_version():
    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert f"| **{current}** |" in VERSIONS.read_text(encoding="utf-8")
