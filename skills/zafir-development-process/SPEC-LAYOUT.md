# Spec layout

Reference for writing or reading specs: paths, contents, architecture versus design, profile, and slice commit phases. Terms follow [Terms](SKILL.md#terms).

## Files

```text
docs/specs/
├── STATUS.json                ← the project's one status register (STATUS-REGISTER.md)
├── architecture.md            ← one per project, enriched over time, never overwritten
└── <feature-slug>/
    ├── brainstorm.md          ← live during Step 2; spec of record once approved
    ├── design.md              ← Step 3.2 outcome, or an explicit deferral
    └── slices/
        ├── 01-<slice-slug>.md
        └── 02-<slice-slug>.md
```

- **Markdown is authoritative.** Approval is always of the Markdown, by path and version. HTML is a presentation.
- **Slice approval presentation.** This applies to every request to approve a slice spec: 5.4, an amendment, any transition to `spec approved`.
  - Present HTML generated from the current Markdown, with both paths and the Markdown's commit or SHA-256.
  - Ask for approval of that source version.
  - The HTML carries every approval-relevant item faithfully: scope, exclusions, decisions, seams, scenarios, constraints. Verify this before presenting.
  - Record the approval, with both paths and the version, in the spec and the register.
  - HTML alone is not approval.
  - A substantive change before approval requires regenerating the HTML and a new request.
- **Lite approval.** In a `lite` project:
  - The request presents the Markdown itself, by path, with its commit or SHA-256.
  - The approval records that path and version.
  - No HTML is generated unless the user asks for it.
- **Deck generation.**
  - Slice decks come from a deterministic renderer versioned in the project. Its contract:
    - Markdown in, HTML out;
    - the source's SHA-256 embedded;
    - an asserted round trip proving the HTML carries the Markdown text exactly;
    - earlier approval annexes kept byte-identical.
  - A reviewer re-runs the renderer and gets identical bytes.
  - A project without a renderer adopts this skill's `scripts/render_slice_deck.py` at its first slice approval. It is copied into the project's scripts location, committed in that slice's phase 1, run from the repository root, and re-run by the reviewer with `--check`.
  - A project renderer meeting the same contract may replace it by recorded decision.
  - `html-slide-deck` produces non-reproducible output, so it generates only the other decks: `brainstorm.html`, `design.html`, `architecture.html`.
  - Every deck is saved beside its Markdown. When older HTML exists there, use a distinct `<slug>.deck.html`.
  - A deck is regenerated whenever its source changes and committed in the same phase as its source. Edit the source, never the deck.
  - Slice decks are mandatory for approval requests outside `lite` projects. Other decks are made only on request or when presenting beyond the conversation.
- **Numbering.** Slice numbering is per feature. A green-field project's first brainstorm, and a lite project's single brainstorm, use the project's name as `<feature-slug>`.

## Slice spec contents

Every mini-spec references its brainstorm, the architecture sections it relies on, and the design when present. It contains:

- the idea, scope, explicit exclusions and success conditions;
- the **lane** ([Risk lanes](SKILL.md#risk-lanes)): lite in a `lite` project, otherwise local or transversal;
- the size ceiling, when the project sets one;
- decisions and applicable governing context: wiki pages, prior decisions, domain rules, constraints;
- dependencies reused;
- placeholders introduced (contract, placeholder, location, security) and placeholders replaced;
- the **envelope forecast**: known paths and, where adopted, areas.

From Step 5 it also contains:

- the **impact map**;
- seams with their reasons;
- original and derived scenarios with their feasibility designs;
- the **delivery package**, when the implementer did not prepare the slice;
- the **implementation plan** (5.5 stage 1);
- a dated amendments log.

Their format and depth per lane are in [PREPARATION.md](PREPARATION.md#proportionality).

## Architecture vs feature design

| | `architecture.md` (project) | `design.md` (feature) |
| --- | --- | --- |
| How many | One for the project's life | One per feature |
| Changes | Rarely, by approved decision | With every feature |
| Holds | See the list below | Modules and seams touched or created, fit, deviations with reasons |
| Rule | Enrich, never overwrite | Reference the architecture instead of repeating it |

`architecture.md` holds:

- the profile and style headers;
- stack and lock-in choices;
- the system shape;
- the module map with public seams;
- constraints and principles;
- **Cross-cutting conventions**;
- **Decisions**.

A **Decisions** entry is a title plus one to three sentences: context, decision, why. Write one only when the decision is hard to reverse, would surprise a future reader, and came from a real trade-off.

**Cross-cutting conventions** are decided once for the project. Slices cite them instead of re-deciding them. Examples: time sources and timestamp fields, lock order, trigger and default policies, identifier and naming rules, ownership of shared fields. Adding or changing one is an architecture change.

An **architecture change** includes a new module, a new technology, or a seam crossing a boundary.

- Make it in `architecture.md` with a Decisions entry, approved by path before slicing. `design.md` points to it.
- Only **one pending change at a time** (Z2). A second feature needing one waits and records the wait in a dated note.
- When `docs/wiki/` exists, the deliberation behind a decision lives in the wiki and the decision only in `architecture.md`, linked both ways.

## Profile and architecture style

`architecture.md` opens with two lines:

- `Profile: full | lite` — **mandatory**.
  - Lite means declared by the user, or a small, mostly CRUD project with few rules (forms over tables, a script, a thin adapter).
  - Lite follows [Lite project](SHORT-PATHS.md#lite-project).
  - In doubt, recommend `full`.
  - The user may lift lite to full at any time. Going from full to lite needs an approved Decisions entry.
- `Architecture style: <style> | none` — **recorded, never imposed**.
  - [ARCHITECTURE-GUIDELINE.md](ARCHITECTURE-GUIDELINE.md) is offered once, in 3.1.
  - The user adopts it, names another style, or chooses `none`.
  - An adopted style is a Decisions entry that 5.5 and 5.7 apply.

## `docs/specs/STATUS.json` — the status register

The project has one register and no per-feature status files. It holds execution state and pointers only. Operation is in [STATUS-REGISTER.md](STATUS-REGISTER.md); the schema in [REGISTER-SCHEMA.md](REGISTER-SCHEMA.md).

## Commit phases of a slice

The **Commit:** markers in [PREPARATION](PREPARATION.md), [IMPLEMENTATION](IMPLEMENTATION.md) and [CONCURRENCY](CONCURRENCY.md) authorize these phases, each at its own moment. Commit each phase when it happens rather than batching them at the end of the slice.

| Phase | When |
| --- | --- |
| 1 — spec | end of 5.4 |
| 2 — skeleton | stage 2 of 5.5, only when the seams are new |
| 2 — test plumbing | stage 2 of 5.5, only when fixtures cannot reach the target |
| 2 — tests | stage 2 of 5.5, before any behaviour |
| 2 — green step | each green step of stage 3 in 5.5 |
| 3 — done | end of 5.7 |
| Integration | after phase 3 |

What each phase usually contains:

- **1 — spec:** the slice spec, the approval HTML (none in `lite`), the register, and the wiki pages and `CONTEXT.md` terms from preparation.
  - It lands on the integration branch, written by the integrator.
  - It is the slice's **base**: the slice branch starts here.
- **2 — skeleton:** the contract skeleton — declarations, fail-closed bodies, M1 consumers.
- **2 — test plumbing:** the bounded plumbing. Target rules still fail closed.
- **2 — tests:** the slice's whole test battery and its RED log.
- **2 — green step:** the production change that turned those tests green, derived scenarios with their tests, terms, and wiki decisions. It includes the register only when the register's content changes ([STATUS-REGISTER](STATUS-REGISTER.md#how-the-process-writes-the-register)).
- **3 — done:** review fixes, the final spec, and the register (`done`, provisional until integration).
  - Without code changes, it runs cheap validators instead of a new gate when integration gates the final tree ([Green means the whole gate](SKILL.md#green-means-the-whole-gate), *When it runs*).
- **Integration:** the update merge when the integration branch moved, then the `--no-ff` merge, the reconciled register and the combined-tree evidence.
  - In a batch, it is the element's merge and the batch's closure commit.

Contents are the expected set, not a ceiling.

Each commit carries the trailers `Slice: <id>` and `Phase: <n>`, which are its evidence ([Rules Z1–Z7](REGISTER-SCHEMA.md#rules-z1z7), Z7). `evidence.commits` holds `base`, and no phase SHA is appended after the fact. A `3.0.0` register without Z7 follows [Registers without Z7](MIGRATION.md#registers-without-z7).

Merging, never rebasing, keeps every phase SHA and `base` valid.
