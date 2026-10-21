# Migration and process revisions

Read when migrating a register, adopting an opt-in schema option, adopting a process revision, or following a citation to a section that moved (*Moved sections*). Never migrate silently: every migration is proposed, approved by the user and recorded in a dated note.

## Process revision 2026-10-21

| Change | Project action |
| --- | --- |
| Every slice (from phase 2), bug fix, trivial change and R-lane change runs on its own branch and integrates with `--no-ff`; the sequential shortcut leaves the queue's update steps empty | From the next slice or fix; work already committed on the integration branch stays as it is |
| Lite projects approve slice specs by their Markdown, without HTML; lite Step 5 follows the three stages of 5.5 | From the next lite approval; existing approval HTML stays valid |
| Feature closure fills the feature row's `evidence.commits` and `evidence.tests` (invariants 8–9) | Features closing after adoption; closed features are not reopened |
| Invoking the skill authorizes the marker commits; Step 0 states the commits it will make | Apply by default |
| Register template (`assets/STATUS.template.json`) and validator (`scripts/validate_register.py`); `placeholders.reuses` and `replaces` are lists of names | New registers start from the template; existing v3 registers may be validated as they are |
| *Terms* in SKILL.md; the 5.4 and phase-2 register rows name stages and green steps instead of cycles; moved-section stubs replaced by *Moved sections* below | None |

## Process revision 2026-10-14

| Change | Project action |
| --- | --- |
| 5.5: plan; the slice's whole test battery and RED log, after a contract skeleton or test plumbing when needed; then green one test at a time | Slices whose implementation starts after adoption |
| Batches in the integration queue; when the whole gate runs; documentation-only phase 3 with cheap validators under an integration gate | From the next integration; a local batch or gate rule may be reduced to a pointer |
| M1 covers constructors; M3 migration renumbering; project standing classes | Apply by default; a project may disable any by recorded decision |
| Per-integration metrics; optional task reviews; roles; process version | From the next integration; task reviews only by project decision |

Slices in implementation finish under the version they started with (SKILL.md). The register is unaffected.

## Process revision 2026-10-01

What changed, and what an existing project must do:

| Change | Project action |
| --- | --- |
| Optimistic concurrency with an integration queue replaces the file-disjoint parallel exception | None while sequential. To run concurrently, record the decision (CONCURRENCY *Prerequisites*) and update the Z6 description in `rules` with a dated note (a compatibility profile without Z6 records only the decision); existing `plannedFiles` stay valid as forecasts. A recorded stricter local policy may stay (precedence 1) |
| Branches are updated by merge, never rebase | A local rule allowing rebase should be amended, or record that phase SHAs and `base` lose their evidence value |
| Risk lanes (R, local, transversal) and proportional preparation: impact map, feasible scenarios, delivery package, pre-mortem | Classify new slices from the next Step 4 or 5.1; approved specs are not reopened for this |
| Mechanical amendment classes, one decision round each at preparation, admission, execution and integration, just-in-time preparation with freshness check | Apply by default; a project may disable any by recorded decision |
| One causal proof per fact; never weaken guards; independent review; git-derived metrics; versioned evidence | Apply from the next slice |
| Commit trailers `Slice:` and `Phase:` | From the next commit; repository commit-format rules win (precedence 5) |

The register stays at `schemaVersion 3.0.0`; nothing in this revision breaks a v3 register or a declared compatibility profile. Local decisions that this revision absorbs remain valid; a project may later reduce them to pointers.

## Register v1/v2 → v3

Only when the user chooses to migrate (a declared compatibility profile never requires it), migrate a v1/v2 Zafir register with a JSON library under the safe update procedure, building and validating a candidate copy before replacing anything:

1. Pause register writers, keep a recoverable copy, and inspect the source version, custom columns, rules, validators and consumers; update incompatible consumers first. A newer or custom schema needs its own inspected policy; never downgrade it.
2. Preserve ids, row order, states, qualifiers, dates, evidence, notes and unrelated extensions. Set `parallelAllowed: false` on every slice and investigation; keep `plannedFiles` or use `[]`. A past pair approval does not authorize concurrency with other slices.
3. Keep every dependency initially. Remove a predecessor or fork-join edge only when approved specs prove it artificial, in an approved revision that records each edge and reason; ambiguous edges go to the user.
4. Record the old `parallelWith` values in a dated note, remove that field, replace the rules with Z1–Z6, declare `parallelAllowed` and `plannedFiles`, and set `3.0.0`. Never reinterpret completed slices or erase historical approvals and SHAs.
5. Recompute readiness, validate the invariants and Z1–Z6, report changed ids and blockers, and commit in the next authorized phase commit. On failure publish nothing and keep writers paused.

## Opting into 3.1.0

Adopt `areas`, Z7 or Z8 (REGISTER-SCHEMA *Opt-in options*) one at a time by recorded decision: declare the column or rule, set `3.1.0`, and update validators and consumers in the same commit. For Z8, generate the aggregate and verify it equals the previous register byte for byte (or field for field) before switching writers.

## Compatibility profiles

A register at an earlier or custom schema version stays valid indefinitely under a declared **compatibility profile** — including a v1 shape with rows in `table`, a free-text policy field, tests inside `evidence`, `notes[].slices`, implicit state domains and none of the Zafir extension fields. Migration is a user choice, never a precondition for this process or a consequence of a process revision.

- **Declaration:** the register's `summary` or a rule, or the repository instruction that maps the register's location, names the profile. Step 0 detects it (STATUS-REGISTER *Reading the register*).
- **Operation:** the safe update procedure, readiness gates, invariants and transitions apply through the mappings below. Write only the fields the register declares, in its own vocabulary and rules; never add Zafir columns, bump `schemaVersion` or normalize values unasked.
- **Absent Zafir fields** keep their meaning outside the row: `parallelAllowed` → the project's recorded concurrency decision; `plannedFiles` and `areas` → the slice spec or a project envelope file; `base` and phase SHAs → the spec, `evidence.commits` or commit trailers; `seams`, `placeholders` and the lane → the slice spec; `kind` and `feature` → the id and spec path. Z1–Z6 apply to those sources.

| Legacy shape | Read as | Portable field, if the user chooses to normalize |
| --- | --- | --- |
| free-text policy field (for example a legal-impact text) | that assessment; resolved only when the text records obligations, exclusions and tests | `assessments.<name>.summary` plus a normalized `state` |
| tests embedded in `evidence` | gate tests defined as the register's readiness rule states; embedded tests are executed proof | `verification` for the gate, `evidence.tests` for executed proof |
| `notes[].slices` | note items | `notes[].items`, or keep `slices` declared in `noteColumns` |
| single `status` field | spec and implementation states as the register's rules define them | separate `spec`, `implementation` and readiness fields |
| implicit state domains | the values the register's rules and current rows use | explicit enums and a validator |
| free component aliases | as written | declared vocabulary with a one-time alias migration |

Preserve source text when migrating; normalize into new fields without discarding qualifiers, notes or evidence.

## Moved sections

A project document citing a former section finds it here:

| Former section | Now |
| --- | --- |
| SPEC-LAYOUT *Rows* | REGISTER-SCHEMA *Zafir profile* › *Rows* |
| SPEC-LAYOUT *Zafir extension fields, declared in `columns`* | REGISTER-SCHEMA *Zafir extension fields* and *Rules Z1–Z6* (Z6 governs permission and envelope) |
| SPEC-LAYOUT *Zafir register version and migration* | this file |
| SPEC-LAYOUT *Admission and readiness* | CONCURRENCY *Admission*; REGISTER-SCHEMA *Readiness gates* |
| SPEC-LAYOUT *How the process writes the register*, *Reading the register* | STATUS-REGISTER, same titles |
| STATUS-REGISTER *Purpose* | STATUS-REGISTER introduction |
| STATUS-REGISTER *Normative vocabulary*, *Readiness gates*, *Document contract*, *Row contract*, *Note contract*, *Invariants*, *State transitions*, *Evidence rules*, *Extension rules*, *Completion criterion* | REGISTER-SCHEMA, same titles |
| STATUS-REGISTER v1 compatibility table | *Compatibility profiles* above |
| SLICE-DISCIPLINE *Parallel exception* (replaced 2026-10-01) | CONCURRENCY |
| SLICE-DISCIPLINE *Eligibility and scheduling* | CONCURRENCY *Admission* |
| SLICE-DISCIPLINE *Scope changes and recovery* | IMPLEMENTATION *Scope changes* |
| SLICE-DISCIPLINE *Single-writer integration* | CONCURRENCY *Integration queue* |
| IMPLEMENTATION 5.1–5.4 | PREPARATION, same numbers |
| STATUS-REGISTER *first cycle*, *later cycles* rows | STATUS-REGISTER *first phase-2 commit*, *each later phase-2 commit* |
