# Migration and process revisions

Terms follow [Terms](SKILL.md#terms). Read this file when you:

- migrate a register;
- adopt an opt-in schema option;
- adopt a process revision;
- operate a register without Z7 ([Registers without Z7](#registers-without-z7));
- follow a citation to a section that moved ([Moved sections](#moved-sections)).

Every migration is proposed, approved by the user and recorded in a dated note. Never migrate silently.

## Process revision 2026-10-21

| Change | Project action |
| --- | --- |
| Every slice (from phase 2), bug fix, trivial change and R-lane change runs on its own branch and integrates with `--no-ff`. The sequential shortcut leaves the queue's update steps empty | From the next slice or fix. Work already committed on the integration branch stays as it is |
| Lite projects approve slice specs by their Markdown, without HTML. Lite Step 5 follows the three stages of 5.5 | From the next lite approval. Existing approval HTML stays valid |
| Feature closure fills the feature row's `evidence.commits` and `evidence.tests` (invariants 8–9) | Features closing after adoption. Closed features are not reopened |
| Invoking the skill authorizes the marker commits. Step 0 states the commits it will make | Apply by default |
| Register template (`assets/STATUS.template.json`) and validator (`scripts/validate_register.py`). `placeholders.reuses` and `replaces` are lists of names | New registers start from the template. Existing v3 registers may be validated as they are |
| [Terms](SKILL.md#terms) added. The 5.4 and phase-2 register rows name stages and green steps instead of cycles. Moved-section stubs replaced by [Moved sections](#moved-sections). The precedence list no longer repeats the commit rule ([Commits are the markers](SKILL.md#commits-are-the-markers) holds it) | None |
| Z7 (phase evidence by commit trailer) is the default. The template declares it at `3.1.0`; no phase SHA is appended after the fact | New registers start with it. A `3.0.0` register adopts it by recorded decision ([Opting into 3.1.0](#opting-into-310)), which is recommended, and follows [Registers without Z7](#registers-without-z7) until then |
| Slice approval decks always come from the project's deterministic renderer. `html-slide-deck` only generates the other decks | From the next slice approval. Decks already approved stay valid |
| The validator requires the `governingContext` assessment on every row, and reports malformed fields instead of crashing | A register lacking `governingContext` adds it (`pending`, or `resolved` with references) in its next authorized commit |
| The validator requires `decidedOn` on an approved spec, and `tests` and `commands` on `defined` verification (and on a slice's `passed`). It warns when a blocker is not in the blocked field's own `qualifier` | A register failing these fills them from the spec and its approval record in its next authorized commit |
| Phase-1 commits land on the integration branch, written by the integrator | Apply by default. Approved specs already committed stay as they are |
| `scripts/render_slice_deck.py` is the reference slice-deck renderer, adopted at a project's first slice approval when it has none | Projects with their own conforming renderer keep it |
| Lite folds: phase 1 into the first phase-2 commit (`base` = its parent); phase 3 into the last green step, after gate and review | From the next lite slice |
| The independent reviewer is defined in [Roles](SKILL.md#roles). A fresh subagent qualifies | Apply by default |
| Green steps no longer update `nextAction`. The implementation plan lives in the slice spec and, with the slice branch, gives the resume point inside stage 3 | Slices whose implementation starts after adoption |

## Process revision 2026-10-14

| Change | Project action |
| --- | --- |
| 5.5: plan; then the slice's whole test battery and RED log, after a contract skeleton or test plumbing when needed; then green one test at a time | Slices whose implementation starts after adoption |
| Batches in the integration queue. When the whole gate runs. Documentation-only phase 3 with cheap validators under an integration gate | From the next integration. A local batch or gate rule may be reduced to a pointer |
| M1 covers constructors. M3 migration renumbering. Project standing classes | Apply by default. A project may disable any by recorded decision |
| Per-integration metrics; optional task reviews; roles; process version | From the next integration. Task reviews only by project decision |

Slices in implementation finish under the version they started with ([SKILL.md](SKILL.md)). The register is unaffected.

## Process revision 2026-10-01

What changed, and what an existing project must do:

| Change | Project action |
| --- | --- |
| Optimistic concurrency with an integration queue replaces the file-disjoint parallel exception | See the list below |
| Branches are updated by merge, never rebase | Amend a local rule allowing rebase, or record that phase SHAs and `base` lose their evidence value |
| Risk lanes (R, local, transversal) and proportional preparation: impact map, feasible scenarios, delivery package, pre-mortem | Classify new slices from the next Step 4 or 5.1. Approved specs are not reopened for this |
| Mechanical amendment classes; one decision round each at preparation, admission, execution and integration; just-in-time preparation with a freshness check | Apply by default. A project may disable any by recorded decision |
| One causal proof per fact; never weaken guards; independent review; git-derived metrics; versioned evidence | Apply from the next slice |
| Commit trailers `Slice:` and `Phase:` | From the next commit. Repository commit-format rules win (precedence 5) |

Project action for optimistic concurrency:

- Nothing while the project runs sequentially.
- To run concurrently, record the decision ([Prerequisites](CONCURRENCY.md#prerequisites)) and update the Z6 description in `rules` with a dated note.
  - A compatibility profile without Z6 records only the decision.
- Existing `plannedFiles` stay valid as forecasts.
- A recorded stricter local policy may stay (precedence 1).

The register stays at `schemaVersion 3.0.0`. Nothing in this revision breaks a v3 register or a declared compatibility profile. Local decisions that this revision absorbs remain valid; a project may later reduce them to pointers.

## Register v1/v2 → v3

Migrate only when the user chooses to; a declared compatibility profile never requires it. Migrate a v1/v2 Zafir register with a JSON library, under the [safe update procedure](STATUS-REGISTER.md#safe-update-procedure-for-a-skill). Build and validate a candidate copy before replacing anything.

1. **Prepare.**
   - Pause register writers and keep a recoverable copy.
   - Inspect the source version, custom columns, rules, validators and consumers.
   - Update incompatible consumers first.
   - A newer or custom schema needs its own inspected policy. Never downgrade it.
2. **Preserve.**
   - Keep ids, row order, states, qualifiers, dates, evidence, notes and unrelated extensions.
   - Set `parallelAllowed: false` on every slice and investigation.
   - Keep `plannedFiles`, or use `[]`.
   - A past pair approval does not authorize concurrency with other slices.
3. **Dependencies.**
   - Keep every dependency initially.
   - Remove a predecessor or fork-join edge only when approved specs prove it artificial, in an approved revision that records each edge and its reason.
   - Ambiguous edges go to the user.
4. **Restructure.**
   - Record the old `parallelWith` values in a dated note, then remove that field.
   - Replace the rules with Z1–Z7.
   - Declare `parallelAllowed` and `plannedFiles`, and set `3.1.0`.
   - Never reinterpret completed slices or erase historical approvals and SHAs.
5. **Validate and commit.**
   - Recompute readiness and validate the invariants and Z1–Z7.
   - Report changed ids and blockers.
   - Commit in the next authorized phase commit.
   - On failure, publish nothing and keep writers paused.

## Opting into 3.1.0

Adopt `areas`, Z7 or Z8 ([Opt-in options](REGISTER-SCHEMA.md#opt-in-options-schema-310)) one at a time, by recorded decision.

- Declare the column or rule and set `3.1.0`.
- Update validators and consumers in the same commit.
- Adopting Z7 keeps the phase SHAs already in `evidence.commits`. They remain the evidence of commits made before adoption, with or without trailers.
- For Z8, generate the aggregate and verify it equals the previous register byte for byte (or field for field) before switching writers.

## Registers without Z7

A `3.0.0` register that has not adopted Z7 keeps phase evidence in `evidence.commits` instead of finding it by trailer:

- A commit cannot carry its own SHA. Each phase SHA is therefore appended at the next commit touching the register.
  - Each later phase-2 commit appends the previous phase-2 SHA.
  - The next register commit after phase 3 or integration appends the phase-3 or integration SHA.
- Z3 finds the earlier phase commits listed in `evidence.commits`. The completing commit's SHA is appended at the next register commit.
- Adopting Z7 is recommended ([Opting into 3.1.0](#opting-into-310)).

## Compatibility profiles

A register at an earlier or custom schema version stays valid indefinitely under a declared **compatibility profile**. This includes a v1 shape with rows in `table`, a free-text policy field, tests inside `evidence`, `notes[].slices`, implicit state domains, and none of the Zafir extension fields. Migration is a user choice. It is never a precondition for this process or a consequence of a process revision.

- **Declaration.** The profile is named by the register's `summary` or a rule, or by the repository instruction that maps the register's location. Step 0 detects it ([Reading the register](STATUS-REGISTER.md#reading-the-register)).
- **Operation.** The safe update procedure, readiness gates, invariants and transitions apply through the mappings below.
  - Write only the fields the register declares, in its own vocabulary and rules.
  - Add Zafir columns, bump `schemaVersion` or normalize values only when asked.
- **Absent Zafir fields** keep their meaning outside the row, and Z1–Z7 apply to those sources:
  - `parallelAllowed` → the project's recorded concurrency decision;
  - `plannedFiles` and `areas` → the slice spec or a project envelope file;
  - `base` and phase SHAs → the spec, `evidence.commits` or commit trailers;
  - `seams`, `placeholders` and the lane → the slice spec;
  - `kind` and `feature` → the id and spec path.

| Legacy shape | Read as | Portable field, if the user chooses to normalize |
| --- | --- | --- |
| free-text policy field (for example a legal-impact text) | that assessment; resolved only when the text records obligations, exclusions and tests | `assessments.<name>.summary` plus a normalized `state` |
| tests embedded in `evidence` | gate tests defined as the register's readiness rule states; embedded tests are executed proof | `verification` for the gate, `evidence.tests` for executed proof |
| `notes[].slices` | note items | `notes[].items`, or keep `slices` declared in `noteColumns` |
| single `status` field | spec and implementation states as the register's rules define them | separate `spec`, `implementation` and readiness fields |
| implicit state domains | the values the register's rules and current rows use | explicit enums and a validator |
| free component aliases | as written | declared vocabulary with a one-time alias migration |

Preserve source text when migrating. Normalize into new fields while keeping every qualifier, note and piece of evidence.

## Moved sections

A project document citing a former section finds it here:

| Former section | Now |
| --- | --- |
| SPEC-LAYOUT *Rows* | [Rows](REGISTER-SCHEMA.md#rows) (REGISTER-SCHEMA *Zafir profile*) |
| SPEC-LAYOUT *Zafir extension fields, declared in `columns`* | [Zafir extension fields](REGISTER-SCHEMA.md#zafir-extension-fields) and [Rules Z1–Z7](REGISTER-SCHEMA.md#rules-z1z7) (Z6 governs permission and envelope) |
| REGISTER-SCHEMA *Rules Z1–Z6*; *Opt-in options* › Z7 | [Rules Z1–Z7](REGISTER-SCHEMA.md#rules-z1z7) |
| SKILL.md *Precedence and exceptions* rule 7 (commits) | [Commits are the markers](SKILL.md#commits-are-the-markers) |
| SPEC-LAYOUT *Zafir register version and migration* | this file |
| SPEC-LAYOUT *Admission and readiness* | [Admission](CONCURRENCY.md#admission); [Readiness gates](REGISTER-SCHEMA.md#readiness-gates) |
| SPEC-LAYOUT *How the process writes the register*, *Reading the register* | [STATUS-REGISTER.md](STATUS-REGISTER.md), same titles |
| STATUS-REGISTER *Purpose* | [STATUS-REGISTER.md](STATUS-REGISTER.md) introduction |
| STATUS-REGISTER *Normative vocabulary*, *Readiness gates*, *Document contract*, *Row contract*, *Note contract*, *Invariants*, *State transitions*, *Evidence rules*, *Extension rules*, *Completion criterion* | [REGISTER-SCHEMA.md](REGISTER-SCHEMA.md), same titles |
| STATUS-REGISTER v1 compatibility table | [Compatibility profiles](#compatibility-profiles) |
| SLICE-DISCIPLINE *Parallel exception* (replaced 2026-10-01) | [CONCURRENCY.md](CONCURRENCY.md) |
| SLICE-DISCIPLINE *Eligibility and scheduling* | [Admission](CONCURRENCY.md#admission) |
| SLICE-DISCIPLINE *Scope changes and recovery* | [Scope changes](IMPLEMENTATION.md#scope-changes) |
| SLICE-DISCIPLINE *Single-writer integration* | [Integration queue](CONCURRENCY.md#integration-queue) |
| IMPLEMENTATION 5.1–5.4 | [PREPARATION.md](PREPARATION.md), same numbers |
| STATUS-REGISTER *first cycle*, *later cycles* rows | *First phase-2 commit* and *Later phase-2 commits* in [How the process writes the register](STATUS-REGISTER.md#how-the-process-writes-the-register) |
