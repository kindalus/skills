# Spec layout

Reference for writing or reading specs: paths, contents, architecture versus design, profile, and slice commit phases.

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

- **Markdown is authoritative:** approval is always of the Markdown, by path and version. HTML is a presentation.
- **Slice approval presentation:** every request to approve a slice spec (5.4, an amendment, any transition to `spec approved`) presents HTML generated from the current Markdown, with both paths and the Markdown's commit or SHA-256, and asks approval of that source version. The HTML carries every approval-relevant item faithfully (scope, exclusions, decisions, seams, scenarios, constraints); verify before presenting. Record the approval with both paths and the version in the spec and the register. HTML alone is not approval; a substantive change before approval requires regeneration and a new request.
- **Lite approval:** in a `lite` project the request presents the Markdown itself, by path with its commit or SHA-256, and the approval records that path and version; no HTML is generated unless the user asks for it.
- **Deck generation:** with `html-slide-deck` when it is installed, otherwise with a deterministic renderer versioned in the project (Markdown in, HTML out; the source's SHA-256 embedded; an asserted round trip proving the HTML carries the Markdown text exactly; earlier approval annexes kept byte-identical), saved beside the Markdown (a distinct `<slug>.deck.html` when older HTML exists), regenerated whenever the source changes, never hand-edited, committed in the same phase as its source; a reviewer re-runs the generator and gets identical bytes. Slice decks are mandatory for approval requests outside `lite` projects; other decks (`brainstorm.html`, `design.html`, `architecture.html`) only on request or when presenting beyond the conversation.
- Slice numbering is per feature. A green-field project's first brainstorm, and a lite project's single brainstorm, use the project's name as `<feature-slug>`.

## Slice spec contents

Every mini-spec references its brainstorm, the architecture sections it relies on and the design when present, and contains:

- idea, scope, explicit exclusions and success conditions;
- **lane** (lite in a `lite` project, otherwise local or transversal; SKILL.md *Risk lanes*) and, when the project sets one, its size ceiling;
- decisions and applicable governing context (wiki pages, prior decisions, domain rules, constraints);
- dependencies reused, placeholders introduced (contract, placeholder, location, security) and placeholders replaced;
- **envelope forecast**: known paths and, where adopted, areas;
- from Step 5: the **impact map**, seams with reasons, original and derived scenarios with their feasibility designs, the **delivery package** when the implementer did not prepare the slice, and a dated amendments log. Their format and depth per lane are in PREPARATION.md.

## Architecture vs feature design

| | `architecture.md` (project) | `design.md` (feature) |
| --- | --- | --- |
| How many | One for the project's life | One per feature |
| Changes | Rarely, by approved decision | With every feature |
| Holds | Profile and style headers; stack and lock-in choices; system shape; module map with public seams; constraints; principles; **Cross-cutting conventions**; **Decisions** | Modules and seams touched or created, fit, deviations with reasons |
| Rule | Enrich, never overwrite | Reference the architecture; never repeat it |

A **Decisions** entry is a title plus one to three sentences (context, decision, why), written only when the decision is hard to reverse, would surprise a future reader, and came from a real trade-off.

**Cross-cutting conventions** are decided once for the project and cited by slices instead of being re-decided per slice: time sources and timestamp fields, lock order, trigger and default policies, identifier and naming rules, ownership of shared fields. Adding or changing one is an architecture change.

An architecture change (new module, technology, or seam crossing a boundary) is made in `architecture.md` with a Decisions entry and approved by path before slicing; `design.md` points to it. Only **one pending change at a time** (Z2): a second feature needing one waits and records the wait in a dated note. When `docs/wiki/` exists, the deliberation behind a decision lives in the wiki, the decision only in `architecture.md`, linked both ways.

## Profile and architecture style

`architecture.md` opens with two lines:

- `Profile: full | lite` — **mandatory**. Lite: declared by the user, or a small, mostly CRUD project with few rules (forms over tables, a script, a thin adapter). Lite follows SHORT-PATHS *Lite project*. In doubt, recommend `full`. The user may lift lite to full at any time; the reverse needs an approved Decisions entry.
- `Architecture style: <style> | none` — **recorded, never imposed**. ARCHITECTURE-GUIDELINE.md is offered once in 3.1; the user adopts it, names another style, or chooses `none`. An adopted style is a Decisions entry that 5.5 and 5.7 apply.

## `docs/specs/STATUS.json` — the status register

One register for the project, with no per-feature status files, holding execution state and pointers only. Operation is in STATUS-REGISTER.md; the schema in REGISTER-SCHEMA.md.

## Commit phases of a slice

The **Commit:** markers in PREPARATION, IMPLEMENTATION and CONCURRENCY authorize these phases at their moments, never batched at slice end:

| Phase | When | Usually contains |
| --- | --- | --- |
| 1 — spec | end of 5.4 | slice spec, approval HTML (none in `lite`), register, wiki pages and `CONTEXT.md` terms from preparation. The slice's **base**; the slice branch starts here |
| 2 — skeleton | stage 2 of 5.5, only when the seams are new | the contract skeleton: declarations, fail-closed bodies, M1 consumers |
| 2 — test plumbing | stage 2 of 5.5, only when fixtures cannot reach the target | the bounded plumbing; target rules still fail closed |
| 2 — tests | stage 2 of 5.5, before any behaviour | the slice's whole test battery and its RED log |
| 2 — green step | each green step of stage 3 in 5.5 | the production change that turned those tests green, derived scenarios with their tests, terms, register, wiki decisions |
| 3 — done | end of 5.7 | review fixes, final spec, register (`done`, provisional until integration); without code changes, cheap validators instead of a new gate when integration gates the final tree (SKILL *When it runs*) |
| Integration | after phase 3 | update merge when the integration branch moved, and `--no-ff` merge (in a batch: its merge and the closure commit), reconciled register, combined-tree evidence |

Contents are the expected set, not a ceiling. Each commit carries the trailers `Slice: <id>` and `Phase: <n>`. A commit cannot carry its own SHA: unless Z7 is adopted, each phase SHA is appended by the next commit touching the register. Merging (never rebasing) keeps every phase SHA and `base` valid.
