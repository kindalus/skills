---
name: zafir-development-process
description: |
  Use this skill whenever the user explicitly invokes zafir-development-process or asks to use, follow, or apply the Zafir development process to a project, feature, feature extension, or bug fix. The skill applies the Four Agent Operating Principles — think before coding, simplicity first, surgical changes, and goal-driven execution — plus the Zafir workflow with slice-driven development, HTML slide-deck specs, mandatory live brainstorm deck → design → plan → implement, brown-field feature additions starting with brainstorm, and bug-fix flow. This skill is self-contained: do not bootstrap, create, or modify the repository's AGENTS.md as part of using it. Trigger on phrases like "use zafir-development-process", "use the Zafir process", "apply the Zafir workflow", "follow the Zafir process", "add a feature using Zafir", or any explicit request to operate within the Zafir development process.
license: MIT
---

# Zafir Development Process

The official development workflow at Zafir. Every project, green-field build, brown-field feature addition, or feature extension follows the same shape: check governing context, brainstorm into a live HTML deck, agree on design and architecture, cut into slices, then implement slices one at a time. **No new feature work starts at slicing.** Bug fixes have their own focused workflow.

All agent behaviour under this skill is governed first by the Four Agent Operating Principles: think before coding, simplicity first, surgical changes, and goal-driven execution. The Zafir process tells agents _when_ to brainstorm, design, slice, and implement; these principles define _how_ agents behave at every step.

## Four Agent Operating Principles

These principles apply to all agent work while this skill is active: code, tests, docs, specs, slide decks, `docs/wiki/`, reviews, and bug fixes. If a process rule appears to push against a principle, surface the tradeoff to the user instead of resolving it silently.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly — if uncertain, ask rather than guess.
- Present multiple interpretations when ambiguity exists; do not pick silently.
- Push back when warranted; if a simpler approach exists, say so.
- Stop when confused; name what is unclear and ask for clarification.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No flexibility or configurability that was not requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

The test: would a senior engineer say this is overcomplicated? If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Do not improve adjacent code, comments, or formatting.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- If you notice unrelated dead code, mention it; do not delete it.
- Remove imports, variables, functions, or files that your own changes made unused.
- Do not remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request or to a mandatory Zafir process artefact.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform imperative tasks into verifiable goals:

| Instead of...    | Transform to...                                       |
| ---------------- | ----------------------------------------------------- |
| "Add validation" | "Write tests for invalid inputs, then make them pass" |
| "Fix the bug"    | "Write a test that reproduces it, then make it pass"  |
| "Refactor X"     | "Ensure tests pass before and after"                  |

For multi-step tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let agents loop independently. Weak criteria such as "make it work" require clarification.

### Collision handling between the principles and the Zafir process

- Mandatory Zafir artefacts (specs, slice decks, `STATUS.md`, and `docs/wiki/` updates) are in scope when the workflow requires them, but they must still be minimal and directly traceable to the task.
- Simplicity First does not override real legal, security, data-integrity, or acceptance-test requirements. If those requirements add complexity, state why.
- Surgical Changes does not forbid removing unused code that your own edits created; it forbids unrelated cleanups.
- Goal-Driven Execution applies at every step: define success criteria before acting and verify them before moving on.

## Zafir workflow principles

- **Slice-driven development.** Work is decomposed into small, related-feature slices, stored under `docs/specs/`.
- **Specs are HTML slide decks.** Brainstormings, design/architecture decisions, and slice specs always live as HTML slide decks — reviewable, presentable, and version-friendly.
- **`docs/wiki/` is the project LLM Wiki.** Whenever this directory exists, it is governed by the `llm-wiki` skill for project references, deliberations, decisions, domain rules, constraints, and legal/regulatory materials when applicable.
- **The brainstorm deck is live.** A brainstorm deck is created as soon as brainstorming starts and updated after every user/agent iteration before the next question or step.
- **Feature additions also begin with brainstorm.** In a brown-field codebase, a request to add or extend functionality still starts at Step 1/Step 2, produces an approved feature brainstorm deck, and only then moves to design and slicing.
- **One slice at a time.** A slice must be fully green before the next one starts.
- **Enrich, never overwrite.** When updating shared documentation, the goal is to aggregate and refine — never to silently replace what is already there.

## Step 0 — Apply this skill

When this skill is invoked, use the instructions in this file as the active workflow for the requested work. The skill is self-contained and does not install itself into the repository.

- Do not create, modify, or require `AGENTS.md` as part of this workflow.
- Treat existing repository instructions, when present, as normal project context.
- If existing project instructions conflict with this workflow, surface the conflict to the user and ask how to proceed.
- Before acting on multi-step work, state a brief goal-driven plan with verification checks.

## Step 1 — Governing context check

At the very start of every project or feature brainstorm — before design, slicing, or implementation — identify the governing context for the work. Governing context includes not only legal/regulatory material, but also project references, existing decisions, domain rules, internal policies, customer or contractual requirements, security/data-integrity requirements, and architecture constraints.

- If `docs/wiki/` exists, consult it via `llm-wiki` before asking or deciding, and use any relevant pages as inputs to the brainstorm.
- Ask the user whether any additional governing context or source material exists that is not yet reflected in the wiki or repository.
- If relevant source material is missing, ask the user to provide it or place raw sources in `docs/wiki/raw/` when that convention exists.
- When legal/regulatory material applies, store or ingest it in `docs/wiki/` and treat it as one category of governing context, not the only category.
- From this point on, every decision (scope, design, architecture, slice acceptance, implementation, bug fix) must be checked against the relevant governing context in `docs/wiki/` and the repository.

## Project wiki discipline (`docs/wiki/`)

Whenever `docs/wiki/` exists, treat it as the persistent project knowledge base, not just as a law or compliance folder. Use the `llm-wiki` skill to:

- ingest and organise external or internal references relevant to the project,
- record durable deliberations and decisions that should outlive chat or a slide deck,
- query prior references, deliberations, decisions, domain rules, constraints, and applicable legal/regulatory materials before taking or reviewing scope, design, architecture, slice, implementation, or bug-fix decisions,
- keep wiki pages linked to the relevant specs/decks when their contents affect the project direction.

`docs/wiki/raw/`, when present, is a user-curated source drop zone. Only the user may manually insert files there. Agents must not create, edit, rename, move, or delete files in `docs/wiki/raw/`; they may only read those files and ingest their contents into maintained wiki pages outside `raw/`. If a needed source is missing from `docs/wiki/raw/`, ask the user to place it there.

Legal/regulatory material, when applicable, is one category of wiki content; it does not limit the wiki's broader role.

## Step 2 — Brainstorm

This step is mandatory for every new project, every feature addition, and every non-trivial feature extension — including brown-field work in an existing codebase. Only pure bug fixes may use the bug-fix workflow instead.

Conduct a structured interview directly with the user and use the `idea-refine` skill at each iteration. Do **not** rely on a separate `interview-me` skill; this process must be executable with the skills actually available. Elicit:

- the overall objective of the project or feature,
- technological constraints,
- design and architecture principles to follow,
- non-goals and known boundaries.

### Mandatory live deck discipline

As soon as brainstorming starts, create a feature-specific HTML slide deck under `docs/specs/`, e.g. `docs/specs/brainstorm-<feature-slug>.html`. Use the `html-slide-deck` skill's single-file HTML conventions, but save the deck in the repository under `docs/specs/`, not in `/tmp`.

The deck must always include:

- current objective and user value,
- constraints, principles, non-goals, and known boundaries,
- decisions made so far,
- open questions and blockers,
- an iteration log with intermediate conclusions from each round.

For every brainstorm iteration:

1. Ask/refine with the user.
2. Update the deck on disk with the latest intermediate conclusions, decisions, changed assumptions, and open questions.
3. Only after the deck is updated, ask the next question or move to the next step.

An iteration includes any user answer, agent synthesis, `idea-refine` phase, pivot, decision, or scope change. Do not keep intermediate conclusions only in chat. If the deck cannot be written or updated, stop and tell the user instead of continuing in memory.

For brown-field feature additions:

- Inspect existing repository instructions when present, relevant specs, and relevant code/docs to understand the baseline before or during brainstorming.
- Capture existing architecture constraints and compatibility requirements in the brainstorm deck.
- Existing architecture can be accepted as the baseline in Step 3, but it does **not** cancel the requirement for a feature brainstorm deck.
- Never jump from a raw feature request directly to Step 4 or Step 5 just because the codebase already exists.

If `docs/wiki/` exists, consult it via `llm-wiki` during brainstorming for prior references, deliberations, decisions, domain rules, constraints, and applicable legal/regulatory materials that may affect scope, constraints, or direction. Durable conclusions that should survive beyond the deck should also be written back to the wiki and linked from the deck.

When governing context from `docs/wiki/` or the repository applies, the brainstorm deck must explicitly capture how the objective and constraints align with it — consult the wiki via `llm-wiki` while drafting, and record the relevant references inside the deck.

The brainstorm ends only when the user explicitly approves the slide deck by path. That approved deck is the spec of record for the project or feature.

## Step 3 — Design and architecture

Once the brainstorm deck is approved, work out _how_ the system will be shaped before slicing it.

Ask the user about:

- design constraints (technical, organisational, performance, regulatory),
- desired design principles and architectural patterns,
- existing technology choices that must be honoured.

Iterate with the user until there is alignment on a design and architecture direction — or until the user explicitly chooses to defer this decision. Skipping is allowed only when the user clearly asks for it; never decide that silently.

**For existing projects**, first ask the user whether they want to revisit and refine the current design and architecture. If yes, iterate as above. If no, take the existing codebase as the baseline and respect what it already establishes.

Capture the outcome in an HTML slide deck under `docs/specs/` (e.g. `architecture.html`), updating it after each design iteration. If the step is deferred, record that explicitly in the brainstorm deck before moving to slicing. If `docs/wiki/` exists, consult prior project references, deliberations, decisions, domain rules, constraints, and applicable legal/regulatory materials via `llm-wiki` before settling architecture, and record durable architecture deliberations or decisions back into the wiki.

## Step 4 — Plan: cut into slices

Before cutting slices, verify that there is an approved brainstorm deck for this project/feature and an approved or explicitly deferred design/architecture outcome. If either gate is missing, stop and return to the relevant earlier step. Take the approved brainstorm deck (and the design/architecture deck, when present) and divide the work into slices of correlated functionality.

- Each slice gets its own HTML slide deck under `docs/specs/slices/`, numbered sequentially (`01-*.html`, `02-*.html`, ...).
- Each slice deck is a mini-spec containing: idea, scope, decisions, likely implementation zones, success conditions, and explicit exclusions.
- Each slice deck must reference the brainstorm deck that originated it, and the design/architecture deck when one exists.
- If `docs/wiki/` exists, each slice deck must also reference any relevant project references, deliberations, decisions, domain rules, constraints, or applicable legal/regulatory materials from the wiki; consult `llm-wiki` when defining or reviewing the slice.
- Each slice deck must declare which governing context applies to its scope, including relevant wiki pages, prior decisions, domain rules, constraints, and applicable legal/regulatory materials — consult `docs/wiki/` via `llm-wiki` when defining the slice and link the relevant references inside the deck.
- Track canonical progress across all slices in `docs/specs/slices/STATUS.md`.

Never create a slice deck directly from a raw feature request. Slices are derived from approved decks, not from chat-only conclusions.

## Step 5 — Implement a slice

Slices are implemented strictly one at a time. A slice does not start until the previous one is fully green.

### 5.1 Pick or create the slice

Locate the slice deck in `docs/specs/slices/` and confirm its status in `docs/specs/slices/STATUS.md`. If the user is requesting new behaviour that is not already covered by an approved brainstorm deck, this is not "create a new slice"; return to Step 1/Step 2 and produce the feature brainstorm deck first. If a new slice is needed within an approved feature plan, create it now, numbered sequentially.

### 5.2 Refine the idea before implementing

Run the `idea-refine` skill on the slice before any code is written.

- If there is any product uncertainty, **stop and ask the user**. Never invent direction silently.
- Update the slice's slide deck with the refined understanding.

### 5.3 Stress-test the decisions

Run the `grill-me` skill on the refined slice. This forces concrete decisions before any test or code is written. Any decision that cannot be settled is logged as a blocker inside the slice deck. If `docs/wiki/` exists, record durable deliberations and decisions from this stress test in the wiki via `llm-wiki` and link them from the slice deck.

### 5.4 Keep documentation in sync

Whenever a slice changes state, update both `docs/specs/slices/STATUS.md` and the slice's own deck.

**Already-implemented decks are not rewritten to change their original scope.** Any new behaviour belongs in a future slice.

### 5.5 Acceptance tests first

Before implementation, write acceptance tests directly from the slice's success conditions.

- Tests cover **external behaviour**, not internal details.
- These tests are what the slice will ultimately be measured against.
- When relevant governing context can be expressed as observable behaviour, write acceptance tests that verify alignment with it. This includes legal/regulatory requirements, security/data-integrity rules, domain constraints, and prior product decisions from `docs/wiki/` or the repository. Treat these as first-class tests, not optional extras.

### 5.6 Implement incrementally

- Decompose the slice into small, verifiable tasks with acceptance criteria and a sensible dependency order.
- When practical, follow TDD: failing test → smallest correct change → refactor with tests green.
- Split large changes into smaller ones.
- Use these skills throughout: `incremental-implementation`, `test-driven-development`, `context-engineering`, `source-driven-development`.
- When the slice involves APIs or interfaces, also use `api-and-interface-design`.
- When the slice touches the UI, also use `frontend-ui-engineering`.
- If `docs/wiki/` exists, consult it via `llm-wiki` whenever a design choice could be affected by project references, prior deliberations, decisions, domain rules, constraints, or legal/regulatory materials.

### 5.7 Verify

Run the full test suite. The slice is only done when **everything is green**. Apply standard quality gates before merging.

### 5.8 Phased commits

For every new slice, produce separate commits for:

1. refinement / spec changes (slice deck + `STATUS.md`),
2. `grill-me` decisions,
3. acceptance tests,
4. verified implementation.

Only when all of the above is in place does the next slice begin.

## Bug fix workflow

Bug fixes do not go through the full slice workflow, but they are still disciplined:

1. **Diagnose the issue.** Reproduce it and understand the root cause before touching code. If diagnosis shows the request is actually new functionality or a feature extension, switch to the full Step 1 → Step 5 workflow before planning slices or code.
2. **Test coverage:**
   - If a test already covers this behaviour, adjust it as needed.
   - If no test covers it, write one that fails for the current bug.
3. **Patch narrowly.** Touch only the code strictly required to fix the issue. No drive-by refactors.
4. **Green bar.** All tests must pass before the fix is considered done.
5. If `docs/wiki/` exists, verify the fix still aligns with relevant project references, deliberations, decisions, domain rules, constraints, and applicable legal/regulatory materials in the wiki (via `llm-wiki`).
