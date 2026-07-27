"""Render docs/USER_MANUAL.md into a single self-contained HTML page.

The markdown stays the one source of truth: the in-app Help viewer reads it
directly (`ManualBrowser.setMarkdown`), and this script only produces a
web-friendly shell around the same words. Nothing here edits the manual, so the
page can never drift from what the app shows — rerun it after editing the
markdown and republish.

What the shell adds over plain markdown: a sticky section nav that tracks where
you are while scrolling, a readable measure, tables that scroll instead of
breaking the layout, and a light/dark palette taken from the app's own theme.

Usage:
    python tools/build_manual_html.py [--out docs/USER_MANUAL.html]

Requires markdown-it-py (a build-time dependency only — the app itself does not
need it):  pip install markdown-it-py
"""
from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import sys
from html import escape, unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "USER_MANUAL.md"
DEFAULT_OUT = ROOT / "docs" / "USER_MANUAL.html"

# The manual's own table of contents is replaced by the sidebar, so rendering it
# too would just be the same list twice.
TOC_HEADING = "## Table of Contents"


def slugify(text: str) -> str:
    """GitHub's heading-anchor rules, so the links already written inside the
    manual (`(#8-portfolio-analytics--dividends)`) keep working here.

    Punctuation is dropped rather than replaced, which is why an ampersand
    leaves a double dash behind — its surrounding spaces each become one.
    """
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s", "-", text)


def strip_toc(md: str) -> str:
    """Drop the markdown TOC block (heading through the following rule)."""
    start = md.find(TOC_HEADING)
    if start == -1:
        return md
    rule = md.find("\n---", md.find("\n", start))
    return md[:start] + (md[rule + 4:].lstrip("\n") if rule != -1 else "")


def embed_images(html: str, base_dir: Path) -> tuple[str, int]:
    """Inline every local image as a data URI — a published page cannot reach
    back to the repo for `images/*.png`, and the artifact CSP blocks any
    external host regardless."""
    count = 0

    def repl(match: re.Match) -> str:
        nonlocal count
        src = match.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return match.group(0)
        path = (base_dir / src).resolve()
        if not path.is_file():
            print(f"  warning: image not found, left as-is: {src}", file=sys.stderr)
            return match.group(0)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        count += 1
        return f'src="data:{mime};base64,{data}"'

    return re.sub(r'src="([^"]+)"', repl, html), count


def add_heading_ids(html: str) -> tuple[str, list[dict]]:
    """Give every h2/h3 an anchor id and collect the nav entries.

    h2 is a numbered section; h3 is a subsection, nested one level in the nav.
    """
    entries: list[dict] = []

    def repl(match: re.Match) -> str:
        level, inner = int(match.group(1)), match.group(2)
        # Unescape before slugifying: the renderer turns "&" into "&amp;", and
        # slugifying that yields "...-amp-..." instead of matching the anchors
        # the manual's own cross-links already point at.
        text = unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        slug = slugify(text)
        number, _, title = text.partition(". ")
        entries.append({
            "level": level, "slug": slug,
            "number": number if level == 2 and number.isdigit() else "",
            "title": title if (level == 2 and number.isdigit()) else text,
        })
        return f'<h{level} id="{slug}">{inner}</h{level}>'

    html = re.sub(r"<h([23])>(.*?)</h\1>", repl, html, flags=re.S)
    return html, entries


def render_nav(entries: list[dict]) -> str:
    items = []
    for e in entries:
        cls = "nav-sub" if e["level"] == 3 else "nav-top"
        num = f'<span class="nav-num">{e["number"]}</span>' if e["number"] else ""
        # Titles were unescaped for slugifying, so re-escape them for the markup.
        items.append(f'<li class="{cls}"><a href="#{e["slug"]}">{num}'
                     f'<span class="nav-text">{escape(e["title"])}</span></a></li>')
    return "\n".join(items)


def build(manual: Path = MANUAL, out: Path = DEFAULT_OUT) -> Path:
    try:
        from markdown_it import MarkdownIt
    except ImportError:  # pragma: no cover - depends on the environment
        raise SystemExit("markdown-it-py is required: pip install markdown-it-py")

    md_text = manual.read_text(encoding="utf-8")
    version = ""
    match = re.search(r"^\*\*Version ([^*]+)\*\*", md_text, flags=re.M)
    if match:
        version = match.group(1).strip()

    # "gfm-like" gives tables and strikethrough; linkify is off so the manual's
    # own bracketed links stay exactly as written.
    parser = MarkdownIt("gfm-like", {"linkify": False})
    html = parser.render(strip_toc(md_text))
    html, entries = add_heading_ids(html)
    html, images = embed_images(html, manual.parent)

    page = PAGE.format(version=version, nav=render_nav(entries), body=html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    try:
        shown = out.relative_to(ROOT)
    except ValueError:          # building somewhere outside the repo (tests)
        shown = out
    print(f"Wrote {shown} — {len(entries)} nav entries, "
          f"{images} images inlined, {len(page) / 1024:,.0f} KB")
    return out


# The page shell. Colours come from the app's own semantic palette
# (tradelab/ui/theme.py) so the manual looks like the product it documents:
# bullish green as the single accent, slate-biased neutrals, amber for callouts.
PAGE = """<title>TradeLab Pro — User Manual</title>
<style>
  :root {{
    --bg: #f7f8fa;          --panel: #eef1f5;      --text: #2b333c;
    --muted: #6b7480;       --rule: #d8dee6;       --accent: #1f8f3f;
    --accent-soft: #e3f2e7; --warn: #8a6a12;       --warn-bg: #fdf6e3;
    --code-bg: #e9edf2;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #10151b;        --panel: #161c24;      --text: #c7d0d8;
      --muted: #8a9099;     --rule: #263039;       --accent: #3fb950;
      --accent-soft: #14251a; --warn: #e3b341;     --warn-bg: #221c0c;
      --code-bg: #1c232c;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #10151b;          --panel: #161c24;      --text: #c7d0d8;
    --muted: #8a9099;       --rule: #263039;       --accent: #3fb950;
    --accent-soft: #14251a; --warn: #e3b341;       --warn-bg: #221c0c;
    --code-bg: #1c232c;
  }}
  :root[data-theme="light"] {{
    --bg: #f7f8fa;          --panel: #eef1f5;      --text: #2b333c;
    --muted: #6b7480;       --rule: #d8dee6;       --accent: #1f8f3f;
    --accent-soft: #e3f2e7; --warn: #8a6a12;       --warn-bg: #fdf6e3;
    --code-bg: #e9edf2;
  }}

  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif;
    font-size: 16.5px; line-height: 1.65;
  }}
  .layout {{ display: grid; grid-template-columns: 272px minmax(0, 1fr); gap: 48px;
             max-width: 1180px; margin: 0 auto; padding: 0 28px; }}

  /* --- sidebar --- */
  .sidebar {{ position: sticky; top: 0; align-self: start; max-height: 100vh;
              overflow-y: auto; padding: 32px 0 48px; }}
  .masthead {{ padding-bottom: 18px; border-bottom: 1px solid var(--rule); margin-bottom: 18px; }}
  .masthead b {{ display: block; font-size: 1.02rem; letter-spacing: -0.01em; }}
  .eyebrow {{ font-family: "Cascadia Code", "Consolas", ui-monospace, monospace;
              font-size: 0.72rem; color: var(--muted); text-transform: uppercase;
              letter-spacing: 0.09em; }}
  .sidebar ul {{ list-style: none; margin: 0; padding: 0; display: flex;
                 flex-direction: column; gap: 1px; }}
  .sidebar a {{ display: flex; gap: 9px; padding: 4px 10px 4px 11px; text-decoration: none;
                color: var(--muted); font-size: 0.855rem; line-height: 1.4;
                border-left: 2px solid transparent; border-radius: 0 3px 3px 0; }}
  .sidebar a:hover {{ color: var(--text); background: var(--panel); }}
  .sidebar a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -2px; }}
  .nav-num {{ font-family: "Cascadia Code", "Consolas", ui-monospace, monospace;
              font-size: 0.75rem; min-width: 1.5em; text-align: right;
              font-variant-numeric: tabular-nums; opacity: 0.65; }}
  .nav-sub a {{ padding-left: 32px; font-size: 0.8rem; }}
  .sidebar a.active {{ color: var(--text); border-left-color: var(--accent);
                       background: var(--accent-soft); }}
  .sidebar a.active .nav-num {{ color: var(--accent); opacity: 1; }}

  /* --- content --- */
  main {{ padding: 40px 0 120px; min-width: 0; }}
  main > * {{ max-width: 68ch; }}
  h1 {{ font-size: 2.1rem; letter-spacing: -0.02em; line-height: 1.15;
        text-wrap: balance; margin: 0 0 6px; }}
  h2 {{ font-size: 1.42rem; letter-spacing: -0.015em; text-wrap: balance;
        margin: 64px 0 4px; padding-top: 22px; border-top: 1px solid var(--rule);
        scroll-margin-top: 24px; }}
  h3 {{ font-size: 1.06rem; margin: 34px 0 2px; scroll-margin-top: 24px;
        color: var(--text); }}
  h4 {{ font-size: 0.95rem; margin: 24px 0 0; color: var(--muted); }}
  p, ul, ol {{ margin: 12px 0; }}
  li {{ margin: 5px 0; }}
  li > ul, li > ol {{ margin: 4px 0; }}
  a {{ color: var(--accent); text-underline-offset: 2px; }}
  strong {{ color: var(--text); font-weight: 650; }}
  hr {{ border: 0; height: 0; margin: 0; }}   /* section rules come from h2 */

  code {{ font-family: "Cascadia Code", "Consolas", ui-monospace, monospace;
          font-size: 0.86em; background: var(--code-bg); padding: 0.12em 0.38em;
          border-radius: 3px; }}
  pre {{ background: var(--code-bg); padding: 14px 16px; border-radius: 6px;
         overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}

  blockquote {{ margin: 20px 0; padding: 12px 18px; background: var(--warn-bg);
                border-left: 3px solid var(--warn); border-radius: 0 4px 4px 0;
                color: var(--text); }}
  blockquote > :first-child {{ margin-top: 0; }}
  blockquote > :last-child {{ margin-bottom: 0; }}

  .table-wrap {{ overflow-x: auto; margin: 18px 0; max-width: 100%; }}
  table {{ border-collapse: collapse; font-size: 0.9rem;
           font-variant-numeric: tabular-nums; }}
  th, td {{ text-align: left; padding: 7px 14px 7px 0; vertical-align: top;
            border-bottom: 1px solid var(--rule); }}
  th {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.07em;
        color: var(--muted); font-weight: 600; white-space: nowrap; }}

  img {{ max-width: 100%; height: auto; border: 1px solid var(--rule);
         border-radius: 5px; display: block; margin: 18px 0; }}

  @media (max-width: 900px) {{
    .layout {{ grid-template-columns: minmax(0, 1fr); gap: 0; padding: 0 20px; }}
    .sidebar {{ position: static; max-height: none; padding: 24px 0 0; }}
    .sidebar ul {{ max-height: 320px; overflow-y: auto; }}
    main {{ padding-top: 24px; }}
  }}
  @media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior: auto; }} }}
  @media (prefers-reduced-motion: no-preference) {{ html {{ scroll-behavior: smooth; }} }}
</style>

<div class="layout">
  <nav class="sidebar" aria-label="Manual sections">
    <div class="masthead">
      <b>TradeLab Pro</b>
      <span class="eyebrow">Manual · {version}</span>
    </div>
    <ul>
{nav}
    </ul>
  </nav>
  <main>
{body}
  </main>
</div>

<script>
(function () {{
  // Wrap tables so a wide one scrolls inside its own box instead of pushing
  // the page sideways.
  document.querySelectorAll("main table").forEach(function (t) {{
    var wrap = document.createElement("div");
    wrap.className = "table-wrap";
    t.parentNode.insertBefore(wrap, t);
    wrap.appendChild(t);
  }});

  // Scroll-spy: highlight the section you are actually reading. Tracks the
  // heading nearest the top of the viewport rather than whichever one happens
  // to intersect, so a long section stays lit the whole way down.
  var links = {{}};
  document.querySelectorAll(".sidebar a").forEach(function (a) {{
    links[a.getAttribute("href").slice(1)] = a;
  }});
  var heads = Array.prototype.slice.call(document.querySelectorAll("main h2, main h3"));
  var current = null;
  function sync() {{
    var best = null;
    for (var i = 0; i < heads.length; i++) {{
      if (heads[i].getBoundingClientRect().top <= 96) best = heads[i];
      else break;
    }}
    if (!best) best = heads[0];
    if (!best || best === current) return;
    if (current && links[current.id]) links[current.id].classList.remove("active");
    current = best;
    var link = links[best.id];
    if (link) {{
      link.classList.add("active");
      if (link.scrollIntoViewIfNeeded) link.scrollIntoViewIfNeeded();
    }}
  }}
  var ticking = false;
  window.addEventListener("scroll", function () {{
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {{ sync(); ticking = false; }});
  }}, {{ passive: true }});
  sync();
}})();
</script>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manual", type=Path, default=MANUAL)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    build(args.manual, args.out)


if __name__ == "__main__":
    main()
