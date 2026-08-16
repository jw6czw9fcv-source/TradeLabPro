"""Heading anchors for the manual, in one place.

The manual's table of contents is written as ordinary markdown links —
`[8. Portfolio…](#8-portfolio-analytics-dividends--retirement)` — and three
different things have to agree on what that slug means: the published HTML page,
the in-app viewer, and the manual itself. Two implementations of the rule is one
too many; when they drift, half the links silently stop working and nothing
fails loudly.

Qt-free, so the build tool can use it without importing the UI.
"""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """GitHub's heading-anchor rules, which is what the links in the manual
    were written against.

    Punctuation is dropped rather than replaced, which is why an ampersand
    leaves a double dash behind — the spaces on either side of it each become
    one dash and the `&` itself becomes nothing.
    """
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s", "-", text)
