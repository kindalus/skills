# Status register schema

Read when creating, validating or extending a register. A new register starts from `assets/STATUS.template.json`; `scripts/validate_register.py` checks what a file can show of the invariants, the required `governingContext` assessment, approval dates, recorded verification, Z2–Z6 and the `areas` option, and lists what it cannot. Day-to-day operation (authority, safe updates, transitions, queries) lives in [STATUS-REGISTER.md](STATUS-REGISTER.md); migration and compatibility profiles in [MIGRATION.md](MIGRATION.md).

The register answers separate questions: which work items exist, what each depends on, whether its spec is settled, whether its implementation is finished or blocked, and whether spec or implementation work may start now. The contract is domain-neutral; projects may call items slices, tasks or changes and add policy assessments.

## Normative vocabulary

REQUIRED, OPTIONAL and FORBIDDEN define the contract. Use exactly these values:

| Field | Values |
| --- | --- |
| `spec.state` | `proposed` (draft, approval incomplete), `approved` (explicit approval, dated in `decidedOn`), `blocked` (missing source, decision or dependency), `n/a` (no standalone spec needed) |
| `implementation.state` | `not-started`, `blocked` (concrete unresolved condition), `done` (accepted scope implemented with evidence), `won't-do` (rejected, superseded or closed) |
| `assessments.<name>.state` | `not-required` (with reason), `pending`, `resolved` (obligations, exclusions and tests recorded), `blocked` |
| `verification.state` | `undefined`, `defined` (tests and commands recorded), `passed`, `failed` (against the reported implementation) |

Explanations go in `qualifier`, dates (`YYYY-MM-DD`) in `decidedOn`; never compound states. There is no `ready` or `in-progress`: readiness belongs to `implementable`, activity to an external execution system. A new state needs a schema-version change with migration rules.

## Readiness gates

`specifiable.value = true`: refinement, grilling, assessment and spec writing may start now. It is `false` when the spec is settled and no revision is requested, an upstream decision must come first, the item is closed, or specification is deliberately deferred. An approved item becomes specifiable again when material facts reopen it; record why.

`implementable.value = true` only when all hold: `spec.state` is `approved` (or a permitted `n/a`); every `dependsOn` item is `done`; every required assessment is `resolved` or `not-required`; `verification.state` is `defined` or `passed`; `implementation.state` is `not-started`; no external, policy or project gate is open. Never infer it from approval alone. Every `false` carries a concrete `reason`.

## Document contract

Top-level fields, all required: `schemaVersion` (semantic version), `title`, `summary`, `rules` (invariants with stable ids), `columns` (row-field contract), `noteColumns`, `table` (one current row per item), `notes` (append-only). Each column descriptor has `name`, `label`, `description`, `type`, `required`, and `enum` for every closed vocabulary; a nested object declares an `objectSchema` or points to this file.

## Row contract

```json
{
  "id": "invoicing-03", "name": "Issue immutable invoice snapshots",
  "dependsOn": ["invoicing-02"], "components": ["api", "database"], "contexts": ["invoicing"],
  "spec": {"state": "approved", "qualifier": "Seams: IssueInvoice", "decidedOn": "2026-09-10"},
  "implementation": {"state": "not-started"},
  "specifiable": {"value": false, "reason": "Spec approved."},
  "implementable": {"value": true},
  "assessments": {"governingContext": {"state": "resolved", "references": ["docs/wiki/invoicing.md"]}},
  "verification": {"state": "defined", "tests": ["issues snapshot"], "commands": ["make test"]},
  "nextAction": "Scenario: issues snapshot",
  "evidence": {"commits": [], "tests": [], "specs": ["docs/specs/invoicing/slices/03-snapshots.md"], "reviews": []}
}
```

All fields above are required (`dependsOn` may be empty; `assessments` may be `{}`; evidence arrays may be empty before completion). `dependsOnText` is optional for qualifications ids cannot express. `nextAction` is `None` on terminal items.

## Note contract

`{"date", "title", "body", "items"}`; `title` and `body` required. A compatibility profile may name the item field differently (MIGRATION); declare the choice in `noteColumns`.

## Invariants

A validator checks all:

1. Unique `id`s.
2. Every dependency exists and is not the row itself.
3. No dependency cycle unless the project declares cycle semantics.
4. States belong to the declared enums.
5. Qualifiers encode no extra state.
6. `implementable=true` satisfies every implementation gate.
7. `done` implies `implementable=false`.
8. `done` implies `verification.state=passed`.
9. `done` has at least one immutable revision and the required test evidence.
10. `blocked` names a concrete blocker in qualifier, reason or next action.
11. `won't-do` records the decision or successor.
12. Every negative readiness has a reason.
13. Components and contexts use declared vocabularies.
14. Dates are valid ISO-8601.
15. Notes reference existing ids.
16. A state-changing commit updates the register atomically with the change it reports.

## State transitions

Typical: `spec proposed → approved → implementation not-started + implementable → done`. Blocked items return to `not-started` when the blocker resolves; `won't-do` may follow any non-terminal state. Reopening a completed item normally creates a successor; reverting `done` is allowed only to correct a wrong completion, recorded in a note.

## Evidence rules

Evidence reports what happened against a specific revision; intent and field names are not evidence. Families: `commits`, `tests`, `specs`, `reviews`, `browser`; projects may add families but never change existing meanings.

## Extension rules

Declare every added field in `columns` with enums for closed vocabularies; keep current state out of notes and policy knowledge in its source. A backward-compatible addition bumps the minor version; renamed fields, removed values or changed semantics bump the major version. Normalize component and context names (`DB` and `database` are not two categories).

## Zafir profile

### Rows

- **Feature row:** `id` = `<feature-slug>`; `spec` is the brainstorm; `dependsOn` empty; `implementable` false ("features close in Step 6").
- **Slice row:** `id` = `<feature-slug>-NN`, `feature` = owning feature, `kind` = `slice` or `investigation`. `dependsOn` holds real dependencies (including learning and decisions) and approved must-finish-before constraints; never its feature row.

### Zafir extension fields

| Field | On | Meaning |
| --- | --- | --- |
| `kind` | all | `feature` \| `slice` \| `investigation` |
| `feature` | slice, investigation | owning feature id |
| `tier` | slice, investigation | `business` \| `security` \| `infrastructure` |
| `design` | feature | `{state: proposed \| approved \| deferred, decidedOn}` |
| `architecture` | feature | `{state: not-yet-created \| consistent \| pending-change \| changed-and-approved, decidedOn}` |
| `base` | slice, investigation | phase-1 commit SHA (absent before) |
| `parallelAllowed` | slice, investigation | required boolean, default `false`; recorded permission for concurrent admission (Z6) |
| `plannedFiles` | slice, investigation | required; envelope forecast of repository-relative paths, `[]` when unknown |
| `seams` | slice | seams listed in 5.4 |
| `placeholders` | slice, investigation | `{reuses: [name], introduces: [{name, standsInFor, livesAt, security, replacedBy}], replaces: [name], kept: [{name, decision}]}`; `reuses` names existing implementations used as they are, `replaces` names placeholders this slice deletes |

`components` and `contexts` are enums declared at the first Step 4 (module map plus `api`, `ui`, `database`, `tests`, `docs`; contexts from `CONTEXT-MAP.md` or the single project context); new values bump the minor version. The required assessment is `governingContext` (pending at creation, resolved in 5.2 with references, blocked when a source is missing); projects add others as governing context requires.

A placeholder is **active** when some row introduces it, no `done` row replaces it, and no row keeps it. It is derived, never stored.

### Rules Z1–Z7

- **Z1** — Table order is the decided default priority. Without concurrency a slice starts only as its feature's next unfinished slice; with `parallelAllowed`, admission follows CONCURRENCY.md. Concurrent execution implies no predecessor or join edge. Each slice waits only for its own dependencies, authoritatively `done`. Removing an edge needs evidence and an approved plan revision.
- **Z2** — At most one feature row has `architecture.state = pending-change`.
- **Z3** — `done` requires `base`, `verification passed`, a recorded review, and every earlier phase commit: found by trailer under Z7, otherwise listed in `evidence.commits`. The completing commit proves itself through Git history (without Z7, its SHA is appended at the next register commit). A slice is authoritatively `done` only with its integration commit and combined-tree evidence; a branch's `done` releases nothing.
- **Z4** — A security placeholder still active at feature closure is in `kept` with a decision covering deployable builds, possible only for builds holding test data.
- **Z5** — A feature is `done` only when its slices are `done` or `won't-do` and none of its placeholders is active without a `kept` decision.
- **Z6** — `parallelAllowed: true` requires recorded user authorization (per slice, or the project's concurrency decision cited in the Step 4 note) and nonempty, unique, normalized `plannedFiles` without globs. Overlapping envelopes do not block admission; CONCURRENCY.md's serial rules do. File disjointness never proves independence.
- **Z7** — Phase evidence comes from Git: slice commits carry the trailers `Slice: <id>` and `Phase: 1|2|3|integration`; `evidence.commits` holds `base`, and Z3 finds the other phase commits with `git log --grep "^Slice: <id>$"`. No SHA is appended after the fact. The template declares it (`3.1.0`); a `3.0.0` register adopts it by recorded decision (MIGRATION *Opting into 3.1.0*) and appends phase SHAs until then.

## Opt-in options (schema 3.1.0)

Each option is independent and adopted by recorded project decision: declare its column or rule and bump `schemaVersion` to `3.1.0` (a register created from the template is already there, with Z7). Registers at `3.0.0` and declared compatibility profiles remain valid indefinitely.

- **`areas`** (column, slice and investigation): repository-relative directories ending in `/`, each covering its direct files only (non-recursive). They extend the envelope forecast: new paths inside an area need no approval.
- **Z8 — partitioned storage:** rows and notes live in per-id files under a declared directory; a project script generates the aggregate register, which is never hand-edited and is what validators and queries read. The logical register remains one, merged by `id`.

## Completion criterion

A register conforms when every row passes the invariants, every closed vocabulary is explicit, readiness derives from recorded gates, and every terminal state has its decision or behavioural evidence.
