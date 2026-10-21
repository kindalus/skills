# Status register — operation

Read before any register read or write. The schema — vocabulary, readiness gates, invariants, Zafir fields, rules Z1–Z6 and the opt-in Z7–Z8 — is in [REGISTER-SCHEMA.md](REGISTER-SCHEMA.md).

## Authority

A project has one logical register: `docs/specs/STATUS.json`, or the location its repository instructions map, possibly generated from partitioned files (Z8). The current row is the present state; notes are chronological context and never override a row. The register holds execution state and pointers to specs, wiki pages and commits, never the knowledge itself. The copy on the integration branch is authoritative; worker copies are provisional, and when work runs on branches only the integrator writes the authoritative one (CONCURRENCY.md).

## Safe update procedure for a skill

1. Parse with a JSON library; read `schemaVersion`, `columns`, `rules` and vocabularies.
2. Locate rows by `id`, never by position.
3. Validate the requested transition before changing data.
4. Recompute readiness for the changed row and every transitive dependent.
5. Add a dated note when the change carries decision context.
6. Preserve unrelated keys and row order; serialize with stable formatting.
7. Run the invariants: the project's validator when it has one, otherwise `python3 scripts/validate_register.py <register>` from this skill (v3 registers; it reports the checks it cannot make). For a compatibility profile, check them by reading and say which.
8. Report changed ids with old and new states, gate reasons and evidence.

Reject the update when an approval, assessment or proof is missing; state what is missing instead of inventing it. Commit the register with the change it reports.

## How the process writes the register

| Moment | Row | Change |
| --- | --- | --- |
| Step 2, first iteration | feature | Create the register if absent, from `assets/STATUS.template.json` (`3.0.0`, Zafir columns, rules, vocabularies; fill `title` and `summary`). Row: `spec proposed`, `implementation not-started`, `verification undefined`, `specifiable true`, `implementable false`, `governingContext pending`, `design proposed`, `architecture not-yet-created` or `consistent`, `nextAction` "brainstorm" |
| Step 2, approval | feature | `spec approved` with `decidedOn`; `specifiable false`; note with the path |
| 3.1 / 3.2 | feature | `architecture` → `consistent`, or `pending-change` (Z2) then `changed-and-approved`; `design` → `approved` or `deferred`; dated note |
| Step 4 | slices | One row per slice in the decided order: `spec proposed`, `implementation not-started`, `verification undefined`, `specifiable true`, `implementable false` ("spec not approved"), `dependsOn`, `tier`, `placeholders`, `governingContext pending`, `evidence.specs`, `nextAction` "prepare"; `parallelAllowed` from the project's concurrency decision (default `false`); `plannedFiles` forecast (`[]` when unknown). Note: order, lanes, reasons |
| 5.2 | slice | `governingContext resolved` with references, or `spec blocked` with the blocker in `qualifier` and `nextAction` |
| 5.4, phase 1 | slice | `spec approved` (`qualifier` names the seams), `seams`, `verification defined` (`tests` = scenario names, `commands` = gate commands), `specifiable false`, readiness recomputed, `nextAction` "plan (5.5)" |
| first phase-2 commit | slice | `base` = phase-1 SHA, also in `evidence.commits`; `nextAction` = the next 5.5 stage |
| each later phase-2 commit | slice | previous phase-2 SHA appended (not under Z7); `placeholders`; `nextAction` = the next red test or task |
| amendment in a pre-authorised class | slice | dated note: class, paths, change, reviewer confirmation |
| blocker | slice | `implementation blocked`, blocker in `qualifier` and `nextAction`, `implementable false` |
| 5.6 | slice | `verification passed`; `evidence.tests` = commands run; `evidence.browser` when run |
| 5.7, phase 3 | slice | `evidence.reviews` (reviewer, date); `implementation done`, `implementable false` ("done"), `nextAction` "None"; dependents recomputed. Provisional until integration |
| integration | slice | Row merged by `id` onto the authoritative register with combined-tree gate and update-delta (or batch resolution) review evidence; now authoritative; dependents recomputed |
| next register commit | slice | phase-3 or integration SHA appended (not under Z7) |
| Step 6 | feature | `verification passed`, `implementation done`, `nextAction` "None"; `evidence.commits` = the slices' integration SHAs, `evidence.tests` = closing gate commands; placeholders replaced or kept (Z4, Z5); note "feature closed" |
| trivial change, R lane | feature | note naming the feature, committed with the change |
| override, deferral, decision | any | dated note; the row it concerns updated in the same commit |

A lite slice with nothing to grill goes from creation straight to 5.4, approved by its Markdown (SPEC-LAYOUT *Lite approval*).

## Reading the register

Step 0 first reads `schemaVersion` and any declared compatibility profile (MIGRATION *Compatibility profiles*): an earlier version under a declared profile is valid as is — operate through its mappings, never migrate or add fields unasked; an undeclared earlier or custom version is reported before any write. Then it reads the authoritative copy: unfinished features, candidate slices, blocked rows and their `nextAction`. For slices in execution, consult the execution system (branches, worktrees, integrator), then their provisional registers. If ownership cannot be established, stop before dispatching a duplicate worker; `base` or `implementable` alone does not prove activity.

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
