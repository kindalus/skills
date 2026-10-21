---
name: zafir-development-process
description: The official Zafir development workflow — governing context, brainstorm, design, slices, risk-proportional preparation, test-first implementation, optimistic concurrency through an integration queue, feature closure, and short paths — under the Four Agent Operating Principles.
disable-model-invocation: true
license: MIT
---

# Zafir Development Process

Features follow **governing context → brainstorm → architecture/design → slices → preparation → implementation → integration → closure**; none starts at slicing. Short paths serve bug fixes, trivial changes and refactors. Effort scales with risk (*Risk lanes*). This skill installs nothing and leaves `AGENTS.md` untouched.

**Process version 2026-10-21.** A slice whose implementation (5.5) started under an earlier version finishes under it, with a dated note in its spec; revisions and project actions are in [MIGRATION](MIGRATION.md).

## Read the applicable procedure

Start at Step 0. Read the step's file before acting; links are requirements, not suggestions. Resume at the recorded step; never replay approved work.

| Step | Produces | Commit marker | Read |
| --- | --- | --- | --- |
| 0 Apply | lane, resume point, plan | — | this file, [SHORT-PATHS](SHORT-PATHS.md) |
| 1–2 Context, brainstorm | `brainstorm.md` approved by path | on approval | [PLANNING](PLANNING.md), [SPEC-LAYOUT](SPEC-LAYOUT.md) |
| 3.1–3.2 Architecture, design | `architecture.md`, `design.md` (or deferral) | on approval | PLANNING; [ARCHITECTURE-GUIDELINE](ARCHITECTURE-GUIDELINE.md) in 3.1 |
| 4 Plan | slice specs, register rows, decided order | on agreement | PLANNING, [SLICE-DISCIPLINE](SLICE-DISCIPLINE.md) |
| 5.1–5.4 Prepare | impact map, feasible scenarios, delivery package, approved slice spec | phase 1 (base) | [PREPARATION](PREPARATION.md), SPEC-LAYOUT |
| 5.5–5.7 Implement | plan, all the slice's tests (RED), then green one test at a time; whole gate; independent review | phase 2, phase 3 | [IMPLEMENTATION](IMPLEMENTATION.md) |
| Integration | merged slice or batch, combined-tree gate | integration | [CONCURRENCY](CONCURRENCY.md) |
| 6 Close | closed feature, metrics | closing | IMPLEMENTATION |

Every register read or write follows [STATUS-REGISTER](STATUS-REGISTER.md); creating or validating a register uses [REGISTER-SCHEMA](REGISTER-SCHEMA.md); migrating one, or following a citation to a section that no longer exists, uses [MIGRATION](MIGRATION.md).

## Terms

Each term has one meaning across these files:

| Term | Meaning |
| --- | --- |
| **Step** | a numbered process step: 0–6, with 3.1–3.2 and 5.1–5.7 |
| **Stage** | one of the three parts of 5.5: plan, tests, green |
| **Green step** | one stage-3 change that turns tests green, and its commit |
| **Phase** | a slice commit phase: 1, 2, 3 or integration (SPEC-LAYOUT *Commit phases of a slice*) |
| **Lane** | the risk classification of a request or slice (*Risk lanes*) |
| **Tier** | a slice's ordering group: business, security, infrastructure (SLICE-DISCIPLINE *Slice ordering*) |
| **Class** | a pre-authorised amendment class: M1–M3 or a listed project class (IMPLEMENTATION *Mechanical amendment classes*) |
| **Profile** | `full` or `lite`, set once per project (SPEC-LAYOUT *Profile and architecture style*) |

## Four Agent Operating Principles

| Principle | Required behavior |
| --- | --- |
| **Think Before Coding** | State assumptions and interpretations; never choose silently. Ask product/scope questions in the decision round (PREPARATION *Decision round*); explain and record mechanism choices. Push back on weak ideas; name what is unclear. |
| **Simplicity First** | Minimum correct solution: no unrequested features, speculative flexibility, single-use abstractions or impossible-error handling. |
| **Surgical Changes** | Touch only the request's scope, in its style; no adjacent tidying; remove only what your change made unused. Every changed line traces to the request or a mandatory artefact. |
| **Goal-Driven Execution** | Define verifiable success first ("fix" → failing reproduction made green; "refactor" → green before and after) and loop until verified. Plans read `step → verify: check`. |

**Collision handling.** Mandatory artefacts are in scope but minimal. Simplicity never weakens legal, security, data-integrity or acceptance requirements. Surface principle/process conflicts to the user; never resolve them silently.

## Roles

| Role | Who | Decides |
| --- | --- | --- |
| **User** | the person who owns the project (the owner) | product, scope, compliance, approvals, overrides, hard-to-reverse decisions |
| **Responsible** | accountable to the user for a slice's preparation and execution | mechanisms, escalations within approved scope, new areas |
| **Integrator** | sole writer of the integration branch and authoritative register; may be the responsible | admission order, integrations and batches, conflict resolutions |
| **Implementer** (worker) | writes the slice's tests and code: an agent, a team or a person | everything inside the approved spec and classes |
| **Reviewer** | did not write the diff under review | findings; confirms amendment classes in writing |

One party may hold several roles, but never reviews its own diff where independent review applies.

## Governing context

Prior decisions, domain rules, policies, contractual, security and data-integrity requirements, architectural constraints and applicable law, found in `docs/wiki/` and the repository's instructions, specs, code and docs. Check it before every decision.

**Standing wiki rule.** `docs/wiki/`, when present, is owned by `llm-wiki` (schema `docs/wiki/wiki-schema.md`): consult it before each decision; write durable deliberations back and link them from the specs relying on them. Only the user changes `docs/wiki/raw/`.

## Standing rules

### Green means the whole gate

Inside red → green, one test passes. Elsewhere, every applicable check passes with the repository's real commands: full tests and build, type check and lint, added migrations up and down on a disposable database, real-browser check (load, behaviour, clean console) for browser-running changes.

**When it runs:** before the slice's final review (5.6); after any later change to code, tests, migrations or build inputs; on the combined tree at every integration. A commit with none of these (documentation, register, files regenerated by the project's generator) needs no new gate when a later integration gate covers its tree or it only records that gate's evidence; it runs the project's cheap validators on what changed (register, specs, the generator's check). Focused runs never replace the gate.

**Disposable database only**, never shared or real data. An irreversible migration records expand/contract, verified backup/restore or forward-fix in the slice spec, never a fake down path.

- **Never weaken a guard or test** to obtain green: no removal, skip, loosened assertion or rewritten expectation outside an approved scenario change. A new pinning guard (hash, regex, text, count) needs a written reason why behaviour cannot be tested; prefer a behaviour test.
- **Honest register:** a state changes only with its evidence; a missing approval, assessment or proof rejects the update. The register on the integration branch is authoritative; worker copies are provisional.
- **Versioned evidence:** versioned documents never cite transient paths (`tmp/`, run directories) as support; keep or summarise the evidence in versioned files.
- **Sequential by default.** Concurrent execution only under CONCURRENCY. Branches are updated by **merge, never rebase**: phase SHAs are evidence.
- **Own branch, always.** Every slice (from its phase-2 commits), bug fix, trivial change and R-lane change runs on its own branch, sequential work included, and reaches the integration branch through an integration commit (CONCURRENCY *Integration queue*). Red commits (a RED battery, a failing reproduction) live only there; the integration branch receives gated trees.
- **Independent review** by someone who did not write the diff for local, transversal and R-lane work; self-review suffices for trivial, lite and bug-fix work.

### Commits are the markers

This process authorizes exactly the **Commit:** markers in its files, at their moments; ask before any other commit. Invoking this skill is the user's request for those marker commits: a standing instruction to commit only on demand (`CLAUDE.md`, `AGENTS.md`, memory) is met by them and still forbids every other commit. Without marker commits, `base`, phase SHAs and Z3 have no evidence; when the user withholds them, say so at Step 0 and record the choice (precedence rule 1). Stage exactly the files the phase produced (check `git status`), never user work; no deferred catch-all commit. Slice commits carry the trailers `Slice: <id>` and `Phase: 1|2|3|integration`.

## Risk lanes

Classify requests at Step 0 and slices at Step 4; in doubt, take the heavier lane and ask.

| Lane | When | Preparation |
| --- | --- | --- |
| Bug fix | existing behaviour is wrong | reproduction first (SHORT-PATHS) |
| Trivial | SHORT-PATHS criteria | the test only |
| R | refactor; no behaviour, contract or compliance change | technical note; gate before and after |
| Lite | slice of a lite-profile project | scenarios; no impact map or package |
| Local | one module or context; no shared convention, field, guard or migration | short impact map and package |
| Transversal | crosses modules/contexts, changes shared conventions, fields, guards or migrations, or opens a chain | full impact map, package and pre-mortem |

## Precedence and exceptions

Above this order sit the **operating environment** and **hard constraints** (legal obligations, deployable-build security, integrity and privacy of real data): decline a crossing instruction and offer the nearest compliant alternative. Within it, say which rule won:

1. **Explicit user instruction** beats process rules; record it where the overridden rule lives (Decisions entry, register note or slice spec).
2. **Governing context** beats Simplicity First and slice order; the user may change its project-decision part, never its hard constraints.
3. **Short paths** override only the steps they name.
4. **A step** beats a general section; a remaining conflict is a defect to surface.
5. **Repository instructions** (`AGENTS.md`, `CLAUDE.md`, CI) beat defaults on commands, layout, commit format and tooling; conflicts with steps go to the user.
6. **Wiki structure** belongs to `llm-wiki`, **spec structure** to this process.
7. **Commits** occur only at the markers.

## Step 0 — Apply this skill

**Entry:** every request under this process.

1. Follow repository conventions (rule 5).
2. Classify the lane; ask if unsure. A new project is full until Step 2 proposes a profile.
3. Read the register, if any (STATUS-REGISTER *Reading the register*), and resume exactly there; ask which feature if several are in flight.
4. Run `git status`; ask what to do with changes this process did not make.
5. State the plan with verification checks and the marker commits it will make; load the step's file.

**Done when:** lane, resume point, tree state and plan (with its commits) are stated. No commit.
