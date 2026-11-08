# Semantic index

An optional retrieval layer for an OKF-backed LLM wiki. `scripts/wiki_index.py` embeds every section of every page in `wiki/` and stores the vectors in a SQLite file. A query can then start from the best-matching sections, with their source citations already resolved, instead of from `wiki/index.md`.

Read this file in full when the schema enables the semantic index, when the user asks to add semantic or vector search to a new or existing wiki, or when a lint finds the index stale.

## What it is and what it is not

- **Derived and rebuildable.** The index is a cache of `wiki/`, like a search engine's. `wiki/` stays the only source of truth, and every answer still cites wiki pages and their sources, never the index.
- **Optional.** A wiki without the index works exactly as before. The schema records whether it is enabled.
- **Disposable.** Deleting `db/` loses nothing that `index --all` cannot rebuild.

Choose it when the wiki has grown past what `wiki/index.md` can route quickly, or when answers should be faster and cheaper. On a measured 66-page legislation wiki, answering from injected sections halved the median answer time and cut median tokens per answer by about 75%, with the same factual accuracy. The gain came from answering from the retrieved sections without reading the index and pages again.

## Layout

```text
<root>/
  raw/
  converted/
  wiki/
  db/                      # optional, present only when the index is enabled
    wiki-index.sqlite
```

`db/wiki-index.sqlite` holds three tables: `meta` (model, dimensions, chunker and schema versions), `pages` (path, hash, type, title, citations, and the original-source mapping for `Source` pages), and `sections` (heading, text, vector). Suggest adding `db/` to `.gitignore` when the wiki is versioned: it is generated and can be rebuilt.

## Requirement: uv

The script runs only through [uv](https://docs.astral.sh/uv/). uv reads the dependencies declared inside the script (`numpy`, `onnxruntime`, `tokenizers`, `sqlite-vec`) and runs it in an isolated, cached environment, so nothing is installed into the machine's Python.

Before enabling or adopting the index, check for uv:

```bash
uv --version
```

When the command fails, stop. Tell the user that the semantic index needs uv, point them to the installation page (https://docs.astral.sh/uv/getting-started/installation/), and wait until they confirm it is installed. Do not install uv yourself, and do not fall back to `pip` or the system Python.

The first run downloads the embedding model, `Xenova/multilingual-e5-small` (INT8 ONNX, about 120 MB, verified by SHA-256), into `~/.cache/llm-wiki/models/`. Set `LLM_WIKI_MODEL_DIR` to use a model directory you provide, and `LLM_WIKI_OFFLINE=1` (or `--offline`) on machines without network access, where the model must already be in place.

## Commands

Run every command from the wiki root, or pass `--root <wiki root>`. `<skill>` is this skill's directory.

```bash
uv run <skill>/scripts/wiki_index.py index            # embed new and changed pages, drop deleted ones
uv run <skill>/scripts/wiki_index.py index --all      # rebuild everything
uv run <skill>/scripts/wiki_index.py status           # exit 0 current, 1 stale, 2 absent
uv run <skill>/scripts/wiki_index.py search "question" --k 6
```

`search` options:

- `--k N`: the number of sections to return. The default is 6.
- `--exclude DIR`: a wiki-relative directory to leave out, such as `sources/`. Repeat it for several directories. Use the schema's exclusions.
- `--format json`: machine-readable output for hosts and tools.
- `--check-stale`: warn when pages changed since the last `index`.

The text output lists each section with its page path, title, heading and page citations. It ends with a `Sources` block that maps each cited source page to its exact `sourceTitle` and `sourceFile` (`raw/...`).

## Adoption

### New wiki

During initialization, ask whether to enable the semantic index (`references/initialization.md`, question 20). When the user says yes, check for uv as above. Then record it in the schema's `Retrieval` section and create `db/` with `index --all` after the first ingest.

### Existing wiki (late adoption)

1. Check for uv as above, and stop if it is missing.
2. Read the schema, then run `status` to confirm that no index exists yet.
3. Run `index --all`. It indexes every existing page, which takes seconds for a wiki of a few hundred pages.
4. Run one `search` with a question the wiki already answers, and confirm that the expected page appears in the results.
5. Amend the schema: set `Retrieval mode: semantic`, list any exclusions, and append a schema changelog entry.
6. Suggest adding `db/` to `.gitignore`.
7. Log it in `wiki/log.md`: `* **Index**: Enabled the semantic index; indexed N pages.`

## Keeping it current

With the index enabled, run `index` after every operation that writes to `wiki/`: ingest, re-ingest, filed queries, renames, merges, splits and approved lint fixes. It is incremental (content hashes) and removes deleted pages. When the script reports a settings mismatch, such as a different model or chunker version, run `index --all`.

## Query in semantic mode

This replaces steps 2–7 of the Query workflow in `references/operations.md` when `Retrieval mode: semantic`:

1. Run `search "<question>"` with the schema's `--k` and exclusions. When the host has already supplied retrieved wiki excerpts in the prompt, use those and skip the search.
2. Read the excerpts as the candidate set. Prefer an applicable derived page, just as in the standard workflow.
3. When the excerpts fully support the answer and its citations, answer from them directly. Whole retrieved sections count as reading the page, so `wiki/index.md` and the pages themselves stay unread.
4. When the excerpts are insufficient, ambiguous or conflicting, continue with the standard workflow from `wiki/index.md`, reading the excerpts' pages first.
5. Cite with the `sourceTitle` and `sourceFile` values from the `Sources` block exactly as printed.
6. File substantive answers as usual, then run `index`.

Questions that combine many cases, such as every situation that requires notice, are where excerpts most often fall short. Treat a question whose answer is a list of cases as one that needs the standard workflow unless the excerpts plainly cover every case.

## Hosts without a shell

Some harnesses give the agent file tools only, with no shell. There the agent cannot run the script, and the host application owns the index:

- After each ingest, the host runs `index`.
- For each question, the host runs `search --format json` and puts the results in the prompt as retrieved wiki excerpts, with the `Sources` mapping.
- The agent follows "Query in semantic mode" from step 2.

Keep the JSON contract stable for hosts: `results[]` (`path`, `title`, `type`, `heading`, `text`, `citations`, `score`) and `sources[]` (`page`, `sourceTitle`, `sourceFile`).

## Lint

When the index is enabled, run `status` and report:

- **Warning:** `stale`, `not_indexed` or `deleted` pages. Fix with `index`.
- **Warning:** `settings_mismatch`. Fix with `index --all`.
- **Blocking:** the schema enables the index but `db/wiki-index.sqlite` is absent. Fix with `index --all`, after the uv check.

## Troubleshooting

- **`search_backend: numpy` in `status`:** this Python cannot load SQLite extensions. Search still works, using numpy over the same vectors, and is slower only on very large wikis.
- **Checksum mismatch on download:** the published model changed. Do not bypass the check. Report it to the user.
