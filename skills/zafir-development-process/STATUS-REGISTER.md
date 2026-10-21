# Status register — operation

Read before any register read or write. Terms follow [Terms](SKILL.md#terms). The schema lives in [REGISTER-SCHEMA.md](REGISTER-SCHEMA.md): vocabulary, readiness gates, invariants, Zafir fields, rules Z1–Z7, and the opt-in `areas` and Z8.

## Authority

- A project has one logical register: `docs/specs/STATUS.json`, or the location its repository instructions map.
- The register may be generated from partitioned files (Z8).
- The current row is the present state. Notes are chronological context and never override a row.
- The register holds execution state and pointers to specs, wiki pages and commits. The knowledge itself lives in those sources.
- The copy on the integration branch is authoritative. Worker copies are provisional.
- When work runs on branches, only the integrator writes the authoritative copy ([CONCURRENCY.md](CONCURRENCY.md#registers-and-shared-records)).

## Safe update procedure for a skill

1. Parse the register with a JSON library. Read `schemaVersion`, `columns`, `rules` and the vocabularies.
2. Locate rows by `id`, never by position.
3. Validate the requested transition before changing data.
4. Recompute readiness for the changed row and every transitive dependent.
5. Add a dated note when the change carries decision context.
6. Preserve unrelated keys and row order. Serialize with stable formatting.
7. Run the invariants:
   - with the project's validator, when it has one;
   - otherwise with this skill's `python3 scripts/validate_register.py <register>`, which handles v3 registers and reports the checks it cannot make;
   - for a compatibility profile, by reading, saying which invariants you checked.
8. Report the changed ids with their old and new states, gate reasons and evidence.

Reject the update when an approval, assessment or proof is missing. State what is missing instead of inventing it. Commit the register together with the change it reports.

## How the process writes the register

Each moment below names the row it touches and the changes it makes.

- **Step 2, first iteration — feature row.**
  - Create the register if absent, from `assets/STATUS.template.json`: schema `3.1.0`, Zafir columns, rules including Z7, vocabularies. Fill `title` and `summary`.
  - Row: `spec proposed`, `implementation not-started`, `verification undefined`, `specifiable true`, `implementable false`, `governingContext pending`, `design proposed`, `architecture not-yet-created` or `consistent`, `nextAction` "brainstorm".
- **Step 2, approval — feature row.** `spec approved` with `decidedOn`; `specifiable false`; a note with the brainstorm's path.
- **3.1 / 3.2 — feature row.**
  - `architecture` → `consistent`, or `pending-change` (Z2) and then `changed-and-approved`.
  - `design` → `approved` or `deferred`.
  - A dated note.
- **Step 4 — slice rows.** One row per slice, in the decided order:
  - `spec proposed`, `implementation not-started`, `verification undefined`, `specifiable true`, `implementable false` with reason "spec not approved";
  - `dependsOn`, `tier`, `placeholders`, `governingContext pending`, `evidence.specs`, `nextAction` "prepare";
  - `parallelAllowed` from the project's concurrency decision (default `false`);
  - `plannedFiles` as the envelope forecast (`[]` when unknown).
  - One note records the order, lanes and reasons.
- **5.2 — slice row.** Either `governingContext resolved` with references, or `spec blocked` with the blocker in `qualifier` and `nextAction`.
- **5.4, phase 1 — slice row.**
  - `spec approved` with `decidedOn`, its `qualifier` naming the seams; `seams`.
  - `verification defined`: `tests` = the scenario names, `commands` = the gate commands.
  - `specifiable false`; readiness recomputed; `nextAction` "plan (5.5)".
- **First phase-2 commit — slice row.**
  - `base` = the phase-1 SHA, also recorded in `evidence.commits`. In a lite fold, `base` is that commit's parent ([Lite project](SHORT-PATHS.md#lite-project)).
  - `nextAction` = the next 5.5 stage.
- **Later phase-2 commits — slice row.** Only what changed:
  - `nextAction` when the 5.5 stage changes (tests, then green). Green steps leave it as it is.
  - `placeholders`.
  - Derived scenarios added to `verification.tests`.
- **Amendment in a pre-authorised class — slice row.** A dated note naming the class, paths, change and the reviewer's confirmation.
- **Blocker — slice row.** `implementation blocked`, the blocker in `qualifier` and `nextAction`, `implementable false`.
- **5.6 — slice row.** `verification passed`; `evidence.tests` = the commands run; `evidence.browser` when a browser check ran.
- **5.7, phase 3 — slice row.**
  - `evidence.reviews` with reviewer and date.
  - `implementation done`, `implementable false` with reason "done", `nextAction` "None".
  - Dependents recomputed.
  - All of this stays provisional until integration.
- **Integration — slice row.**
  - The row is merged by `id` onto the authoritative register.
  - It carries the evidence of the combined-tree gate (the whole gate run on the merged tree) and of the update-delta review (or, in a batch, of the batch resolution review, [Batches](CONCURRENCY.md#batches) step 4).
  - The row is now authoritative; dependents are recomputed.
- **Step 6 — feature row.**
  - `verification passed`, `implementation done`, `nextAction` "None".
  - `evidence.commits` = the slices' integration SHAs; `evidence.tests` = the closing gate's commands.
  - Placeholders replaced or kept (Z4, Z5).
  - A note "feature closed".
- **Trivial change, R lane — feature row.** A note naming the feature, committed with the change.
- **Override, deferral, decision — any row.** A dated note, with the row it concerns updated in the same commit.

A register without Z7 also appends phase SHAs after the fact: see [Registers without Z7](MIGRATION.md#registers-without-z7).

A lite slice with nothing to grill goes from creation straight to 5.4. It is approved by its Markdown ([Files](SPEC-LAYOUT.md#files), *Lite approval*).

## Reading the register

Step 0 reads the register in this order:

1. **Version.** Read `schemaVersion` and any declared compatibility profile ([Compatibility profiles](MIGRATION.md#compatibility-profiles)).
   - An earlier version under a declared profile is valid as is. Operate through its mappings; migrate or add fields only when asked.
   - Report an undeclared earlier or custom version before any write.
2. **Authoritative copy.** Read the unfinished features, candidate slices, blocked rows and their `nextAction`.
3. **Slices in execution.** Consult the execution system (branches, worktrees, integrator), then their provisional registers.
   - Inside stage 3 of 5.5 the register names only the stage. The resume point is the slice branch's last `Phase: 2` commit and the first task of the spec's implementation plan whose tests are still red when the battery runs there.
4. **Ownership.** If ownership of a slice cannot be established, stop before dispatching a duplicate worker. `base` or `implementable` alone does not prove activity.

```bash
R=docs/specs/STATUS.json
# Ready to implement
jq -r '.table[] | select(.implementable.value) | "\(.id) \(.name)"' $R
# Blocked items and next actions
jq -r '.table[] | select(.implementation.state=="blocked") | [.id, .nextAction] | @tsv' $R
# Candidate slices (consult the execution system for activity)
jq -r '.table[] | select((.kind // (if (.id | test("-[0-9]+$")) then "slice" else "feature" end)) != "feature" and .implementation.state!="done" and (.base!=null or .implementable.value)) | [.feature, .id, .spec.state, .nextAction] | @tsv' $R
# Pending architecture change (Z2)
jq -r '.table[] | select(.kind=="feature" and .architecture.state=="pending-change") | .id' $R
# Active placeholders
jq -r '[.table[].placeholders.introduces[]?.name] - [.table[] | select(.implementation.state=="done") | .placeholders.replaces[]?] - [.table[].placeholders.kept[]?.name] | .[]' $R
# Notes for one item
jq -r '.notes[] | select((.items // .slices // []) | index("invoicing-03")) | [.date, .title] | @tsv' $R
```
