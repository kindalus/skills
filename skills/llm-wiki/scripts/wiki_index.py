#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy>=1.24",
#   "onnxruntime>=1.17",
#   "tokenizers>=0.15",
#   "sqlite-vec>=0.1.6",
# ]
# ///
"""Optional semantic index for an OKF-backed LLM wiki.

The index is a derived, rebuildable SQLite file at `<root>/db/wiki-index.sqlite`.
It stores one embedding per wiki page section plus the citation metadata needed
to cite original sources. It is never a source of truth: `wiki/` is.

Commands:
  index   Embed new and changed pages; remove deleted ones. `--all` rebuilds.
  search  Return the best-matching sections with resolved source citations.
  status  Report whether the index is current. Exit 0 current, 1 stale, 2 absent.

Always run it with uv: `uv run <skill>/scripts/wiki_index.py <command> ...`.
uv reads the inline metadata above and runs the script in an isolated, cached
environment, so nothing is installed into the machine's Python.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = "1"
CHUNKER_VERSION = "1"
MODEL_ID = "Xenova/multilingual-e5-small"
MODEL_FILES = {
    "onnx/model_int8.onnx": "4d24e2bc01a447951524466ef533e52944bf48509e6552810bcee1a2711cb02c",
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
}
MODEL_URL = "https://huggingface.co/" + MODEL_ID + "/resolve/main/"
DIMENSIONS = 384
MAX_TOKENS = 512
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
BATCH_SIZE = 32
MIN_SECTION_CHARS = 40
MAX_SECTION_CHARS = 1500
DB_RELATIVE_PATH = Path("db") / "wiki-index.sqlite"
RESERVED_PAGES = {"index.md", "log.md"}

FRONTMATTER_RE = re.compile(r"\A---\r?\n([\s\S]*?)\r?\n---\r?\n?")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
CITATIONS_RE = re.compile(r"^#{1,6}\s+Citations\s*$", re.MULTILINE | re.IGNORECASE)
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
SOURCE_LINK_RE = re.compile(r"\]\(([^)]*?sources/[^)#]+\.md)(?:#[^)]*)?\)")


class IndexError_(Exception):
    """A user-facing failure; printed without a traceback."""


# ---------------------------------------------------------------------------
# Wiki parsing


@dataclass
class Section:
    heading: str
    text: str


@dataclass
class Page:
    path: str  # relative to wiki/, POSIX separators
    sha256: str
    meta: dict[str, str]
    sections: list[Section]
    citations: str
    cited_sources: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.meta.get("title") or self.path

    @property
    def type(self) -> str:
        return self.meta.get("type", "")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Read top-level scalar keys only; nested YAML is ignored on purpose."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line or line[0].isspace() or ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip()] = value
    return meta, text[match.end():]


def plain(text: str) -> str:
    return LINK_RE.sub(r"\1", text).strip()


def split_long(text: str) -> list[str]:
    if len(text) <= MAX_SECTION_CHARS:
        return [text]
    parts, current = [], ""
    for paragraph in re.split(r"\n\s*\n", text):
        if current and len(current) + len(paragraph) + 2 > MAX_SECTION_CHARS:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
        while len(current) > MAX_SECTION_CHARS:
            parts.append(current[:MAX_SECTION_CHARS])
            current = current[MAX_SECTION_CHARS:]
    if current:
        parts.append(current)
    return parts


def resolve_source_link(page_path: str, target: str) -> str | None:
    """Map a markdown link to a source page onto a wiki-relative path."""
    if target.startswith("/"):
        resolved = target.lstrip("/")
    else:
        resolved = os.path.normpath(os.path.join(os.path.dirname(page_path), target)).replace(os.sep, "/")
    return resolved if resolved.startswith("sources/") else None


def parse_page(wiki_dir: Path, file: Path) -> Page:
    raw = file.read_bytes()
    rel = file.relative_to(wiki_dir).as_posix()
    meta, body = parse_frontmatter(raw.decode("utf-8", errors="replace"))
    citation_match = CITATIONS_RE.search(body)
    citations = body[citation_match.end():].strip() if citation_match else ""
    if citation_match:
        body = body[: citation_match.start()]

    sections: list[Section] = []
    description = meta.get("description", "").strip()
    if description:
        sections.append(Section("", description))
    marks = list(HEADING_RE.finditer(body))
    spans = [("", body[: marks[0].start()] if marks else body)]
    spans += [
        (m.group(2), body[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(body)])
        for i, m in enumerate(marks)
    ]
    for heading, text in spans:
        text = plain(text)
        if len(text) < MIN_SECTION_CHARS:
            continue
        for piece in split_long(text):
            sections.append(Section(plain(heading), piece.strip()))

    cited = []
    for target in SOURCE_LINK_RE.findall(citations):
        resolved = resolve_source_link(rel, target)
        if resolved and resolved not in cited:
            cited.append(resolved)
    return Page(rel, hashlib.sha256(raw).hexdigest(), meta, sections, plain(citations), cited)


def wiki_files(wiki_dir: Path) -> list[Path]:
    return sorted(
        p for p in wiki_dir.rglob("*.md")
        if p.is_file() and p.relative_to(wiki_dir).as_posix() not in RESERVED_PAGES
    )


def source_file_for(meta: dict[str, str]) -> str:
    """`../../raw/a.pdf` -> `raw/a.pdf`: the root-relative original source."""
    value = meta.get("source_path", "").replace("\\", "/")
    while value.startswith("../") or value.startswith("./"):
        value = value.split("/", 1)[1]
    return value


# ---------------------------------------------------------------------------
# Model


def default_model_dir() -> Path:
    configured = os.environ.get("LLM_WIKI_MODEL_DIR")
    if configured:
        return Path(configured).expanduser()
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache / "llm-wiki" / "models" / MODEL_ID.replace("/", "--")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_model(model_dir: Path, offline: bool) -> Path:
    for rel, expected in MODEL_FILES.items():
        target = model_dir / rel
        if target.exists():
            continue
        if offline:
            raise IndexError_(
                f"model file missing: {target}. Copy {MODEL_ID} ({', '.join(MODEL_FILES)}) "
                "into the model directory, or run once without --offline to download it."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        print(f"downloading {MODEL_URL}{rel}", file=sys.stderr)
        with urllib.request.urlopen(MODEL_URL + rel, timeout=120) as response, partial.open("wb") as out:
            while block := response.read(1 << 20):
                out.write(block)
        actual = sha256_file(partial)
        if actual != expected:
            partial.unlink(missing_ok=True)
            raise IndexError_(f"checksum mismatch for {rel}: expected {expected}, got {actual}")
        partial.replace(target)
    return model_dir


class Embedder:
    def __init__(self, model_dir: Path):
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise IndexError_(
                f"missing dependency ({exc.name}). Run this script with `uv run`, "
                "which provides its dependencies in an isolated environment."
            ) from exc
        self.np = np
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(model_dir / "onnx/model_int8.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        pad_id = self.tokenizer.token_to_id("<pad>")
        self.tokenizer.enable_padding(pad_id=pad_id if pad_id is not None else 0, pad_token="<pad>")

    def embed(self, texts: list[str]) -> "list":
        np = self.np
        vectors = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = self.tokenizer.encode_batch(texts[start: start + BATCH_SIZE])
            ids = np.array([e.ids for e in batch], dtype=np.int64)
            mask = np.array([e.attention_mask for e in batch], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            weights = mask[..., None].astype(np.float32)
            pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
            pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            vectors.extend(pooled.astype(np.float32))
        return vectors


# ---------------------------------------------------------------------------
# Database

DDL = """
create table if not exists meta(key text primary key, value text not null);
create table if not exists pages(
  path text primary key, sha256 text not null, type text, title text,
  description text, citations text, cited_sources text not null default '[]',
  source_title text, source_file text, indexed_at text not null
);
create table if not exists sections(
  id integer primary key, path text not null references pages(path) on delete cascade,
  ord integer not null, heading text, text text not null, vector blob not null
);
create index if not exists sections_path on sections(path);
"""

EXPECTED_META = {
    "schema_version": SCHEMA_VERSION,
    "chunker_version": CHUNKER_VERSION,
    "model": MODEL_ID,
    "model_sha256": MODEL_FILES["onnx/model_int8.onnx"],
    "dimensions": str(DIMENSIONS),
    "query_prefix": QUERY_PREFIX,
    "passage_prefix": PASSAGE_PREFIX,
}


def connect(db_path: Path) -> tuple[sqlite3.Connection, str]:
    con = sqlite3.connect(db_path)
    con.execute("pragma foreign_keys = on")
    backend = "numpy"
    try:
        import sqlite_vec

        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        backend = "sqlite-vec"
    except (ImportError, AttributeError, sqlite3.OperationalError):
        pass  # this Python cannot load SQLite extensions; search falls back to numpy
    return con, backend


def read_meta(con: sqlite3.Connection) -> dict[str, str]:
    try:
        return dict(con.execute("select key, value from meta"))
    except sqlite3.OperationalError:
        return {}


def meta_mismatch(meta: dict[str, str]) -> list[str]:
    return [k for k, v in EXPECTED_META.items() if meta.get(k) != v]


# ---------------------------------------------------------------------------
# Commands


def resolve_root(args) -> tuple[Path, Path, Path]:
    root = Path(args.root).expanduser().resolve()
    wiki_dir = root / "wiki"
    if not wiki_dir.is_dir():
        raise IndexError_(f"no wiki/ directory under {root}; pass --root <wiki repo root>")
    db_path = Path(args.db).expanduser().resolve() if args.db else root / DB_RELATIVE_PATH
    return root, wiki_dir, db_path


def plan(con: sqlite3.Connection, wiki_dir: Path) -> tuple[list[Path], list[str], dict[str, str]]:
    files = wiki_files(wiki_dir)
    known = dict(con.execute("select path, sha256 from pages")) if read_meta(con) else {}
    current = {f.relative_to(wiki_dir).as_posix(): f for f in files}
    changed = [f for rel, f in current.items() if known.get(rel) != sha256_file(f)]
    removed = sorted(set(known) - set(current))
    return changed, removed, known


def cmd_index(args) -> int:
    _, wiki_dir, db_path = resolve_root(args)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con, _ = connect(db_path)
    con.executescript(DDL)
    mismatch = meta_mismatch(read_meta(con)) if read_meta(con) else []
    if mismatch and not args.all:
        raise IndexError_(
            f"index was built with different settings ({', '.join(mismatch)}); rebuild with `index --all`"
        )
    if args.all:
        con.execute("delete from sections")
        con.execute("delete from pages")
    changed, removed, _ = plan(con, wiki_dir)
    started = time.perf_counter()
    pages = [parse_page(wiki_dir, f) for f in changed]
    embedder = Embedder(ensure_model(Path(args.model_dir).expanduser(), args.offline)) if pages else None
    texts = [
        f"{PASSAGE_PREFIX}{p.title}. {s.heading + '. ' if s.heading else ''}{s.text}"
        for p in pages for s in p.sections
    ]
    vectors = embedder.embed(texts) if texts else []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with con:
        for rel in removed:
            con.execute("delete from pages where path = ?", (rel,))
        cursor = 0
        for page in pages:
            con.execute("delete from pages where path = ?", (page.path,))
            is_source = page.type == "Source" or page.path.startswith("sources/")
            con.execute(
                "insert into pages values(?,?,?,?,?,?,?,?,?,?)",
                (
                    page.path, page.sha256, page.type, page.title, page.meta.get("description", ""),
                    page.citations, json.dumps(page.cited_sources),
                    page.title if is_source else None, source_file_for(page.meta) if is_source else None, now,
                ),
            )
            for ord_, section in enumerate(page.sections):
                con.execute(
                    "insert into sections(path, ord, heading, text, vector) values(?,?,?,?,?)",
                    (page.path, ord_, section.heading, section.text, vectors[cursor].tobytes()),
                )
                cursor += 1
        for key, value in {**EXPECTED_META, "indexed_at": now}.items():
            con.execute("insert or replace into meta values(?, ?)", (key, value))
    elapsed = time.perf_counter() - started
    total = con.execute("select count(*) from pages").fetchone()[0]
    print(
        f"indexed {len(pages)} page(s), {len(texts)} section(s); removed {len(removed)}; "
        f"{total} page(s) in {db_path} ({elapsed:.1f}s)"
    )
    return 0


def cmd_status(args) -> int:
    root, wiki_dir, db_path = resolve_root(args)
    if not db_path.exists():
        report = {"state": "absent", "db": str(db_path)}
        code = 2
    else:
        con, backend = connect(db_path)
        meta = read_meta(con)
        changed, removed, known = plan(con, wiki_dir)
        mismatch = meta_mismatch(meta) if meta else list(EXPECTED_META)
        missing = [f.relative_to(wiki_dir).as_posix() for f in changed if f.relative_to(wiki_dir).as_posix() not in known]
        stale = [f.relative_to(wiki_dir).as_posix() for f in changed if f.relative_to(wiki_dir).as_posix() in known]
        code = 1 if (changed or removed or mismatch) else 0
        report = {
            "state": "current" if code == 0 else ("rebuild" if mismatch else "stale"),
            "db": str(db_path.relative_to(root)) if db_path.is_relative_to(root) else str(db_path),
            "pages": len(known),
            "sections": con.execute("select count(*) from sections").fetchone()[0] if meta else 0,
            "not_indexed": missing,
            "stale": stale,
            "deleted": removed,
            "settings_mismatch": mismatch,
            "indexed_at": meta.get("indexed_at"),
            "search_backend": backend,
        }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for key, value in report.items():
            if isinstance(value, list):
                value = f"{len(value)}" + (f" ({', '.join(value[:10])}{', …' if len(value) > 10 else ''})" if value else "")
            print(f"{key}: {value}")
    return code


def rank(con: sqlite3.Connection, backend: str, query, exclude: list[str], k: int) -> list[tuple]:
    where = " and ".join(["s.path not like ?"] * len(exclude)) or "1"
    params = [f"{prefix.rstrip('/')}/%" for prefix in exclude]
    columns = "s.path, s.ord, s.heading, s.text, p.title, p.type, p.citations, p.cited_sources"
    sql = f"select {columns}, %s from sections s join pages p on p.path = s.path where {where}"
    if backend == "sqlite-vec":
        rows = con.execute(
            sql % "vec_distance_cosine(s.vector, ?) as d" + " order by d limit ?",
            [query.tobytes(), *params, k],
        ).fetchall()
        return [(*row[:-1], 1.0 - row[-1]) for row in rows]
    import numpy as np

    rows = con.execute(sql % "s.vector", params).fetchall()
    if not rows:
        return []
    matrix = np.frombuffer(b"".join(r[-1] for r in rows), dtype=np.float32).reshape(len(rows), DIMENSIONS)
    with np.errstate(all="ignore"):  # some BLAS builds raise spurious FP warnings on matmul
        scores = np.nan_to_num(matrix @ query, nan=-1.0)
    order = np.argsort(-scores)[:k]
    return [(*rows[i][:-1], float(scores[i])) for i in order]


def cmd_search(args) -> int:
    _, wiki_dir, db_path = resolve_root(args)
    if not db_path.exists():
        raise IndexError_(f"no index at {db_path}; build it with `index --all`")
    con, backend = connect(db_path)
    mismatch = meta_mismatch(read_meta(con))
    if mismatch:
        raise IndexError_(f"index settings differ ({', '.join(mismatch)}); rebuild with `index --all`")
    embedder = Embedder(ensure_model(Path(args.model_dir).expanduser(), args.offline))
    query = embedder.embed([QUERY_PREFIX + args.query])[0]
    hits = rank(con, backend, query, args.exclude, args.k)
    stale = bool(plan(con, wiki_dir)[0]) if args.check_stale else False

    cited: list[str] = []
    results = []
    for path, _, heading, text, title, type_, citations, cited_sources, score in hits:
        for src in json.loads(cited_sources or "[]"):
            if src not in cited:
                cited.append(src)
        results.append({
            "path": f"wiki/{path}", "title": title, "type": type_, "heading": heading,
            "text": text, "citations": citations, "score": round(score, 4),
        })
    sources = []
    for src in cited:
        row = con.execute("select source_title, source_file from pages where path = ?", (src,)).fetchone()
        if row and row[1]:
            sources.append({"page": f"wiki/{src}", "sourceTitle": row[0], "sourceFile": row[1]})

    if args.format == "json":
        print(json.dumps({"query": args.query, "results": results, "sources": sources, "stale": stale},
                         ensure_ascii=False, indent=2))
        return 0
    blocks = []
    for i, r in enumerate(results, 1):
        block = f"[{i}] {r['path']} | {r['title']} (score {r['score']:.3f})"
        if r["heading"]:
            block += f"\n## {r['heading']}"
        block += f"\n{r['text']}"
        if r["citations"]:
            block += f"\nPage citations: {' '.join(r['citations'].split())}"
        blocks.append(block)
    print("\n\n".join(blocks) if blocks else "(no results)")
    if sources:
        print("\nSources (use these exact values for sourceTitle and sourceFile):")
        for s in sources:
            print(f"- {s['page']} -> sourceTitle: {json.dumps(s['sourceTitle'], ensure_ascii=False)}, "
                  f"sourceFile: {json.dumps(s['sourceFile'], ensure_ascii=False)}")
    if stale:
        print("\nWarning: the index is stale; run `index` before relying on these results.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="wiki repo root (contains wiki/); default: current directory")
    common.add_argument("--db", help=f"index file; default: <root>/{DB_RELATIVE_PATH.as_posix()}")
    common.add_argument("--model-dir", default=str(default_model_dir()),
                        help="model directory; default: $LLM_WIKI_MODEL_DIR or the user cache")
    common.add_argument("--offline", action="store_true", default=os.environ.get("LLM_WIKI_OFFLINE") == "1",
                        help="never download the model (also LLM_WIKI_OFFLINE=1)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", parents=[common], help="embed new and changed pages")
    p_index.add_argument("--all", action="store_true", help="rebuild the whole index (first adoption, model change)")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", parents=[common], help="find the sections closest to a question")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=6, help="number of sections to return (default 6)")
    p_search.add_argument("--exclude", action="append", default=[], metavar="DIR",
                          help="wiki-relative directory to leave out, e.g. sources/ (repeatable)")
    p_search.add_argument("--format", choices=["text", "json"], default="text")
    p_search.add_argument("--check-stale", action="store_true", help="warn when pages changed since indexing")
    p_search.set_defaults(func=cmd_search)

    p_status = sub.add_parser("status", parents=[common], help="report whether the index is current")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except IndexError_ as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
