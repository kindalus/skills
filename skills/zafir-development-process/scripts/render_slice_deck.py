#!/usr/bin/env python3
"""Render a slice spec (Markdown) into its approval deck (HTML), deterministically.

Usage: render_slice_deck.py SPEC [DECK]        write DECK (default: SPEC with .html)
       render_slice_deck.py --check SPEC DECK  verify DECK is SPEC's exact rendering

Contract (SPEC-LAYOUT.md *Deck generation*): same input, same bytes; the source's
SHA-256 embedded; the full Markdown embedded and checked by round trip. Run it from
the repository root with a repository-relative SPEC path: the path is part of the
output. It writes only DECK. Exit codes: 0 ok, 1 check failed. Standard library only.
"""

from __future__ import annotations

import hashlib
import html
import re
import sys
from pathlib import Path

GENERATOR = "zafir render_slice_deck 1"
SOURCE_OPEN = '<pre id="zafir-source">'
SOURCE_CLOSE = "</pre>"

STYLE = """
:root { --bg: #fff; --fg: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7; --code: #f5f5f7; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161617; --fg: #f5f5f7; --muted: #a1a1a6; --line: #424245; --code: #232325; }
}
body { margin: 0 auto; max-width: 60rem; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
  font: 16px/1.55 system-ui, sans-serif; }
header { border-bottom: 1px solid var(--line); margin-bottom: 1.5rem; color: var(--muted); font-size: .85rem; }
section.slide { border: 1px solid var(--line); border-radius: 8px; padding: 1rem 1.5rem; margin: 1rem 0; }
code, pre { background: var(--code); font-family: ui-monospace, monospace; font-size: .9em; }
pre { padding: .75rem; overflow-x: auto; white-space: pre-wrap; }
table { border-collapse: collapse; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--line); padding: .3rem .6rem; text-align: left; vertical-align: top; }
blockquote { border-left: 3px solid var(--line); margin: 0; padding-left: 1rem; color: var(--muted); }
""".strip()


def inline(text: str) -> str:
    """Escape, then apply code spans, links, bold and italics; code spans stay literal."""
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        part = html.escape(part)
        part = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', part)
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", part)
        out.append(part)
    return "".join(out)


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_blocks(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
        elif stripped.startswith("```"):
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(body)) + "</code></pre>")
        elif m := re.match(r"(#{1,6})\s+(.*)", stripped):
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
        elif stripped.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|?[\s:|-]+\|?", lines[i + 1].strip()):
            head = table_cells(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(table_cells(lines[i]))
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            out.extend("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in rows)
            out.append("</tbody></table>")
        elif stripped.startswith(">"):
            quoted = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quoted.append(lines[i].strip()[1:].lstrip())
                i += 1
            out.append("<blockquote>" + "".join(render_blocks(quoted)) + "</blockquote>")
        elif re.match(r"([-*+]|\d+[.)])\s+", stripped):
            ordered = bool(re.match(r"\d", stripped))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < len(lines) and lines[i].strip():
                item = re.match(r"\s*([-*+]|\d+[.)])\s+(.*)", lines[i])
                if item and not lines[i].startswith(("    ", "\t")):
                    items.append(item.group(2))
                elif items:
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(it)}</li>" for it in items) + f"</{tag}>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"\s*(#{1,6}\s|```|\||>|([-*+]|\d+[.)])\s)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>" + inline(" ".join(para)) + "</p>")
    return out


def slides(lines: list[str]) -> list[list[str]]:
    """One slide per level-2 heading; content before the first one is the title slide."""
    groups: list[list[str]] = [[]]
    fenced = False
    for line in lines:
        if line.strip().startswith("```"):
            fenced = not fenced
        if not fenced and re.match(r"##\s", line):
            groups.append([])
        groups[-1].append(line)
    return [g for g in groups if any(l.strip() for l in g)]


def render(source: str, source_path: str) -> str:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    lines = source.splitlines()
    title = next((l.strip()[2:].strip() for l in lines if l.startswith("# ")), source_path)
    body = [f'<section class="slide">{"".join(render_blocks(group))}</section>' for group in slides(lines)]
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta name="generator" content="{GENERATOR}">',
        f'<meta name="zafir-source" content="{html.escape(source_path)}">',
        f'<meta name="zafir-source-sha256" content="{digest}">',
        f"<title>{html.escape(title)}</title>",
        f"<style>{STYLE}</style>",
        "</head>",
        "<body>",
        f"<header>Source: <code>{html.escape(source_path)}</code> · SHA-256 <code>{digest}</code> · {GENERATOR}</header>",
        *body,
        "<details><summary>Approved Markdown source</summary>",
        SOURCE_OPEN + html.escape(source) + SOURCE_CLOSE,
        "</details>",
        "</body>",
        "</html>",
        "",
    ])


def embedded_source(deck: str) -> str | None:
    start = deck.find(SOURCE_OPEN)
    end = deck.find(SOURCE_CLOSE, start)
    if start < 0 or end < 0:
        return None
    return html.unescape(deck[start + len(SOURCE_OPEN):end])


def read_source(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def main(argv: list[str]) -> int:
    check = "--check" in argv
    args = [a for a in argv[1:] if a != "--check"]
    if not args or len(args) > 2 or (check and len(args) != 2):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        print(__doc__.strip().splitlines()[3], file=sys.stderr)
        return 1
    spec = Path(args[0])
    deck = Path(args[1]) if len(args) == 2 else spec.with_suffix(".html")
    source = read_source(spec)
    rendered = render(source, spec.as_posix())
    if embedded_source(rendered) != source:
        print(f"{spec}: round trip failed; the deck would not carry the Markdown exactly", file=sys.stderr)
        return 1
    if check:
        if not deck.exists():
            print(f"{deck}: missing", file=sys.stderr)
            return 1
        if deck.read_bytes() != rendered.encode("utf-8"):
            print(f"{deck}: differs from the rendering of {spec} (stale or hand-edited)", file=sys.stderr)
            return 1
        print(f"{deck}: identical rendering of {spec}, SHA-256 {hashlib.sha256(source.encode('utf-8')).hexdigest()}")
        return 0
    deck.write_bytes(rendered.encode("utf-8"))
    print(f"{deck}: rendered from {spec}, SHA-256 {hashlib.sha256(source.encode('utf-8')).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
