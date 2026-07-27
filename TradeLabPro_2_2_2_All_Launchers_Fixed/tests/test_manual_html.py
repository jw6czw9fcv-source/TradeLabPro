"""Tests for the manual's HTML build (tools/build_manual_html.py).

The point of the generator is that the published page can never drift from
docs/USER_MANUAL.md, so these run against the *real* manual: every section it
contains has to reach the navigation, and every link has to resolve.
"""
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("markdown_it")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_manual_html import build, slugify, strip_toc  # noqa: E402

MANUAL = ROOT / "docs" / "USER_MANUAL.md"


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    out = tmp_path_factory.mktemp("manual") / "USER_MANUAL.html"
    build(MANUAL, out)
    return out.read_text(encoding="utf-8")


def test_every_section_reaches_the_navigation(page):
    headings = re.findall(r"^## (.+)$", MANUAL.read_text(encoding="utf-8"), flags=re.M)
    sections = [h for h in headings if h != "Table of Contents"]
    assert sections, "the manual should have sections"
    for heading in sections:
        slug = slugify(heading)
        assert f'<h2 id="{slug}">' in page, f"{heading} has no anchor"
        assert f'href="#{slug}"' in page, f"{heading} is missing from the nav"


def test_slugs_match_the_links_written_inside_the_manual():
    # The manual's own cross-links use GitHub's anchor rules; the generator has
    # to produce the same slugs or every internal link breaks.
    assert slugify("4. Home") == "4-home"
    assert slugify("8. Portfolio, Analytics & Dividends") == "8-portfolio-analytics--dividends"
    assert slugify("22. Settings & your data") == "22-settings--your-data"


def test_internal_links_all_resolve(page):
    ids = set(re.findall(r'<h[23] id="([^"]+)"', page))
    targets = {h for h in re.findall(r'href="#([^"]+)"', page)}
    missing = targets - ids
    assert not missing, f"links point at nothing: {sorted(missing)}"


def test_page_is_self_contained(page):
    # A published artifact cannot reach the repo for images, and its CSP blocks
    # every external host, so nothing may reference one.
    assert not re.search(r'(?:src|href)="https?://', page)
    assert 'src="images/' not in page
    assert page.count("data:image/") >= 1        # screenshots inlined instead


def test_the_markdown_toc_is_not_duplicated(page):
    # The sidebar replaces it; rendering both would show the same list twice.
    assert "Table of Contents" not in page
    assert "## Table of Contents" not in strip_toc(MANUAL.read_text(encoding="utf-8"))


def test_both_themes_are_defined(page):
    # The viewer's toggle stamps data-theme on the root and must win over the
    # OS preference in both directions.
    assert "@media (prefers-color-scheme: dark)" in page
    assert ':root[data-theme="dark"]' in page
    assert ':root[data-theme="light"]' in page


def test_version_is_carried_into_the_page(page):
    version = re.search(r"^\*\*Version (.+?)\*\*", MANUAL.read_text(encoding="utf-8"),
                        flags=re.M).group(1)
    assert version in page
