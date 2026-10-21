---
name: zafir-development-process
description: The official Zafir development workflow — governing context, brainstorm, design, slices, risk-proportional preparation, test-first implementation, optimistic concurrency through an integration queue, feature closure, and short paths — under the Four Agent Operating Principles.
disable-model-invocation: true
license: MIT
---

# Zafir Development Process

Features follow **governing context → brainstorm → architecture/design → slices → preparation → implementation → integration → closure**. No feature starts at slicing. Short paths serve bug fixes, trivial changes and refactors. Effort scales with risk ([Risk lanes](#risk-lanes)). This skill installs nothing and leaves `AGENTS.md` untouched.

**Process version 2026-10-21.** A slice whose implementation (5.5) started under an earlier version finishes under that version, with a dated note in its spec. Each revision, and the project actions it requires, is in [MIGRATION](MIGRATION.md).

## Read the applicable procedure

Start at Step 0. Read each step's file before acting on that step: links are requirements, not suggestions. Resume at the recorded step, and never replay approved work.

| Step | Produces | Commit marker | Read |
| --- | --- | --- | --- |
| 0 Apply | lane, resume point, plan | — | this file, [SHORT-PATHS](SHORT-PATHS.md) |
| 1–2 Context, brainstorm | `brainstorm.md` approved by path | on approval | [PLANNING](PLANNING.md), [SPEC-LAYOUT](SPEC-LAYOUT.md) |
| 3.1–3.2 Architecture, design | `architecture.md`, `design.md` (or deferral) | on approval | PLANNING; [ARCHITECTURE-GUIDELINE](ARCHITECTURE-GUIDELINE.md) in 3.1 |
| 4 Plan | slice specs, register rows, decided order | on agreement | PLANNING, [SLICE-DISCIPLINE](SLICE-DISCIPLINE.md) |
| 5.1–5.4 Prepare | impact map, feasible scenarios, delivery package, approved slice spec | phase 1 (base) | [PREPARATION](PREPARATION.md), SPEC-LAYOUT |
| 5.5–5.7 Implement | plan, all the slice's tests (RED), then green one test at a time, whole gate, independent review | phase 2, phase 3 | [IMPLEMENTATION](IMPLEMENTATION.md) |
| Integration | merged slice or batch, combined-tree gate | integration | [CONCURRENCY](CONCURRENCY.md) |
| 6 Close | closed feature, metrics | closing | IMPLEMENTATION |

Three files apply across steps:

- **Every register read or write:** [STATUS-REGISTER](STATUS-REGISTER.md).
- **Creating or validating a register:** [REGISTER-SCHEMA](REGISTER-SCHEMA.md).
- **Migrating a register, or following a citation to a section that no longer exists:** [MIGRATION](MIGRATION.md).

## Terms

Each term has one meaning across these files:

| Term | Meaning |
| --- | --- |
| **Step** | a numbered process step: 0–6, with 3.1–3.2 and 5.1–5.7 |
| **Stage** | one of the three parts of 5.5: plan, tests, green |
| **Green step** | one stage-3 change that turns tests green, and its commit |
| **Phase** | a slice commit phase: 1, 2, 3 or integration ([Commit phases of a slice](SPEC-LAYOUT.md#commit-phases-of-a-slice)) |
| **Lane** | the risk classification of a request or slice ([Risk lanes](#risk-lanes)) |
| **Tier** | a slice's ordering group: business, security, infrastructure ([Slice ordering](SLICE-DISCIPLINE.md#slice-ordering)) |
| **Class** | a pre-authorised amendment class: M1–M3 or a listed project class ([Mechanical amendment classes](IMPLEMENTATION.md#mechanical-amendment-classes)) |
| **Profile** | `full` or `lite`, set once per project ([Profile and architecture style](SPEC-LAYOUT.md#profile-and-architecture-style)) |
| **Gate** | the whole gate: every applicable check, run with the repository's real commands ([Green means the whole gate](#green-means-the-whole-gate)) |
| **Base** | the phase-1 commit SHA, where the slice branch starts; in a lite fold, that commit's parent ([Lite project](SHORT-PATHS.md#lite-project)) |
| **Seam** | a public interface where behaviour is observed, listed in 5.4 ([5.4](PREPARATION.md#54-agree-the-seams-then-define-the-acceptance-scenarios)) |
| **Envelope** | the forecast of paths (`plannedFiles`) and areas (`areas`) a slice will touch: a forecast, not a reservation ([Admission](CONCURRENCY.md#admission)) |
| **Integration branch** | the one branch that receives gated trees and holds the authoritative register ([Integration queue](CONCURRENCY.md#integration-queue)) |
| **Authoritative** | as recorded on the integration branch; worker copies are provisional ([Authority](STATUS-REGISTER.md#authority)) |
| **Freshness check** | at admission, the diff of the integration branch since approval, compared with the impact map and envelope ([Just-in-time and freshness](PREPARATION.md#just-in-time-and-freshness)) |
| **Fail closed** | code (a behaviour body, a constructor, a target rule) that fails with an explicit not-implemented error, has no effects and never returns a successful placeholder ([Stage 2](IMPLEMENTATION.md#stage-2--write-all-the-slices-tests-the-red)) |
| **Placeholder** | the simplest adapter that satisfies a contract for an unavailable dependency ([Contracts and placeholders](SLICE-DISCIPLINE.md#contracts-and-placeholders)) |
| **Register** | the project's status register, `docs/specs/STATUS.json` or its mapped location ([Authority](STATUS-REGISTER.md#authority)) |

## Four Agent Operating Principles

- **Think Before Coding.** State assumptions and interpretations instead of choosing silently. Ask product and scope questions in the [Decision round](PREPARATION.md#decision-round). Explain and record mechanism choices. Push back on weak ideas, and name what is unclear.
- **Simplicity First.** Write the minimum correct solution: no unrequested features, speculative flexibility, single-use abstractions or handling of impossible errors.
- **Surgical Changes.** Touch only the request's scope, in its existing style, without adjacent tidying. Remove only what your change made unused. Every changed line traces to the request or to a mandatory artefact.
- **Goal-Driven Execution.** Define verifiable success first, then loop until it is verified. "Fix" means a failing reproduction made green; "refactor" means green before and after. Plans read `step → verify: check`.

**Collision handling:**

- Mandatory artefacts are in scope, kept minimal.
- Simplicity never weakens legal, security, data-integrity or acceptance requirements.
- Surface every conflict between a principle and the process to the user, instead of resolving it silently.

## Roles

| Role | Who | Decides |
| --- | --- | --- |
| **User** | the person who owns the project (the owner) | product, scope, compliance, approvals, overrides, hard-to-reverse decisions |
| **Responsible** | accountable to the user for a slice's preparation and execution | mechanisms, escalations within approved scope, new areas |
| **Integrator** | sole writer of the integration branch and authoritative register; may be the responsible | admission order, integrations and batches, conflict resolutions |
| **Implementer** (worker) | writes the slice's tests and code: an agent, a team or a person | everything inside the approved spec and classes |
| **Reviewer** | did not write the diff under review | findings; confirms amendment classes in writing |

One party may hold several roles. It never reviews its own diff where independent review applies.

**Independent reviewer:** the user, another person, or an agent session that neither wrote nor steered the diff, and that starts from only the diff, the spec and this process.

- A fresh subagent qualifies.
- The author's own session does not, nor does a subagent briefed with the author's conclusions.
- Prefer another model family for transversal slices when one is available.
- `evidence.reviews` names the reviewer and, for an agent, its model.

## Governing context

Governing context is what every decision must respect: prior decisions, domain rules, policies, contractual, security and data-integrity requirements, architectural constraints and applicable law. It lives in `docs/wiki/` and in the repository's instructions, specs, code and docs. Check it before every decision.

**Standing wiki rule.** When `docs/wiki/` exists, `llm-wiki` owns it (schema: `docs/wiki/wiki-schema.md`).

- Consult it before each decision.
- Write durable deliberations back to it, and link them from the specs that rely on them.
- Only the user changes `docs/wiki/raw/`.

## Standing rules

### Green means the whole gate

Inside a red → green step, green means one test passes. Everywhere else, green means every applicable check passes with the repository's real commands:

- the full tests and build;
- type check and lint;
- added migrations, run up and down on a disposable database;
- a real-browser check (load, behaviour, clean console) for changes that run in a browser.

**When it runs:**

- before the slice's final review (5.6);
- after any later change to code, tests, migrations or build inputs;
- on the combined tree at every integration.

A commit that changes none of these inputs (documentation, the register, files regenerated by the project's generator) needs no new gate when either holds:

- a later integration gate covers its tree;
- it only records that gate's evidence.

Such a commit runs the project's cheap validators on what changed instead: the register, the specs, the generator's check. Focused runs never replace the gate.

**Disposable database only:** the gate uses a disposable database, never shared or real data. An irreversible migration records its alternative in the slice spec (expand/contract, verified backup/restore, or forward-fix) instead of a fake down path.

- **Never weaken a guard or test** to obtain green. Outside an approved scenario change, keep every guard and assertion as approved: no removal, skip, loosened assertion or rewritten expectation.
- **Prefer a behaviour test to a pin.** A new pinning guard (hash, regex, text, count) needs a written reason why the behaviour cannot be tested.
- **Honest register:** a state changes only with its evidence. A missing approval, assessment or proof rejects the update. The register on the integration branch is authoritative, and worker copies are provisional.
- **Versioned evidence:** keep or summarise evidence in versioned files. Versioned documents never cite transient paths (`tmp/`, run directories) as support.
- **Sequential by default.** Run work concurrently only under [CONCURRENCY](CONCURRENCY.md). Update branches by **merge, never rebase**, because phase SHAs are evidence.
- **Own branch, always.** Every slice, bug fix, trivial change and R-lane change runs on its own branch, sequential work included.
  - A slice's own branch starts with its phase-2 commits.
  - Each reaches the integration branch through an integration commit ([Integration queue](CONCURRENCY.md#integration-queue)).
  - Red commits (a RED battery, a failing reproduction) live only on the own branch. The integration branch receives only gated trees.
- **Independent review** (see *Independent reviewer* in [Roles](#roles)) applies to local, transversal and R-lane work. Self-review suffices for trivial, lite and bug-fix work.

### Commits are the markers

- This process authorizes exactly the **Commit:** markers in its files, each at its moment. Ask before any other commit.
- Invoking this skill is the user's request for those marker commits. A standing instruction to commit only on demand (`CLAUDE.md`, `AGENTS.md`, memory) is met by them, and still forbids every other commit.
- Without marker commits, `base`, phase SHAs and Z3 have no evidence. When the user withholds them, say so at Step 0 and record the choice (precedence rule 1).
- Stage exactly the files the phase produced (check `git status`), and leave user work unstaged.
- Commit each phase at its marker; never defer work to a catch-all commit.
- Slice commits carry the trailers `Slice: <id>` and `Phase: 1|2|3|integration`. The trailers are their evidence ([Z7](REGISTER-SCHEMA.md#rules-z1z7)).

## Risk lanes

Classify requests at Step 0 and slices at Step 4. In doubt, take the heavier lane and ask.

| Lane | When | Preparation |
| --- | --- | --- |
| Bug fix | existing behaviour is wrong | reproduction first ([Bug fix workflow](SHORT-PATHS.md#bug-fix-workflow)) |
| Trivial | meets the [Trivial change](SHORT-PATHS.md#trivial-change) criteria | the test only |
| R | a refactor with no behaviour, contract or compliance change | technical note, gate before and after |
| Lite | a slice of a lite-profile project | scenarios, with no impact map or package |
| Local | one module or context, with no shared convention, field, guard or migration | short impact map and package |
| Transversal | crosses modules or contexts, changes shared conventions, fields, guards or migrations, or opens a chain | full impact map, package and pre-mortem |

## Precedence and exceptions

Two things sit above this order: the **operating environment** and **hard constraints** (legal obligations, deployable-build security, integrity and privacy of real data). Decline an instruction that crosses them, and offer the nearest compliant alternative.

Within the order, say which rule won:

1. **Explicit user instruction** beats process rules. Record it where the overridden rule lives: a Decisions entry, a register note or the slice spec.
2. **Governing context** beats Simplicity First and slice order. The user may change its project-decision part, never its hard constraints.
3. **Short paths** override only the steps they name.
4. **A step** beats a general section. A remaining conflict is a defect to surface.
5. **Repository instructions** (`AGENTS.md`, `CLAUDE.md`, CI) beat defaults on commands, layout, commit format and tooling. Their conflicts with steps go to the user.
6. **Wiki structure** belongs to `llm-wiki`, and **spec structure** to this process.

## Step 0 — Apply this skill

**Entry:** every request under this process.

1. Follow repository conventions (precedence rule 5).
2. Classify the lane, and ask if unsure. A new project is `full` until Step 2 proposes a profile.
3. Read the register, if any ([Reading the register](STATUS-REGISTER.md#reading-the-register)), and resume exactly where it says. Ask which feature if several are in flight.
4. Run `git status`, and ask what to do with changes this process did not make.
5. State the plan, with its verification checks and the marker commits it will make. Then load the step's file.

**Done when:** the lane, resume point, tree state and plan (with its commits) are stated. No commit.
