# Concurrency and integration

Read when more than one slice is in execution, and at every integration: every slice, bug fix and R-lane change reaches the integration branch through it (SKILL.md *Own branch, always*). It replaces the former file-disjoint *Parallel exception*: overlapping files are allowed, and safety comes from the integration queue, not from reservations.

## Prerequisites

Execution is sequential by default. Concurrency is a project decision recorded once (an `architecture.md` Decisions entry, the project's decisions location, or a dated register note), not a per-slice ceremony. It requires all three:

1. a whole gate (SKILL.md) that runs reliably on the combined tree;
2. independent review (someone who did not write the diff);
3. one named integrator and one authoritative integration branch.

Without them, run one slice at a time. A project that recorded a stricter policy (for example, file-disjoint envelopes) keeps it under precedence rule 1; every rule below still applies to it.

## Cap

Default: at most **3 slices in execution**, a transversal slice counting as two. A project may set another cap locally (precedence 1 or 5); real capacity (hosts, disk, gate time) may lower dispatch. Review the cap with the metrics of Step 6.

## Admission

A slice enters execution only when:

- its preparation is complete (5.4 approved) and the **authoritative** register shows `implementable`, with every dependency authoritatively `done` (integrated, not worker `done`);
- the admission freshness check passed (PREPARATION *Just-in-time and freshness*);
- the cap allows it and the serial rules below hold against every slice in execution.

**Serial only for:**

1. **Behaviour dependencies** — one slice consumes another's behaviour, contract, decision or discovery, directly or transitively. Learning is a dependency.
2. **Two transversal slices**, unless partitioned by domain with no shared function.
3. **The same function, rule, guard or migration** changed by two slices, unless their impact maps prove they do not touch it.

Envelopes (`plannedFiles`, optional `areas`) are forecasts, not reservations; their overlap alone never blocks admission. Prefer the decided table order; the integrator serializes admission decisions so two checks cannot race. A dependency discovered during execution pauses the later slice and admission is recomputed; unrelated slices continue.

Each slice runs on its own branch and worktree with isolated mutable test resources (databases, ports, caches, fixtures, run directories). Workers, worktrees and admission events live in the external execution system; they add no register state and no commit.

## Integration queue

One integrator runs one integration at a time, in order of readiness: a single slice (below) or a batch (*Batches*); a younger slice overtakes an older one only through a declared dependency.

1. **Freeze** the candidate head; its own `git diff <base>` review (5.7) is complete.
2. **Update by merge:** merge the current integration branch into the slice branch. Never rebase, squash or cherry-pick: phase commits, their SHAs and `base` remain evidence.
3. **Record each conflict resolution** — file, side kept, why — in the merge commit message.
4. **Re-run** the focused tests of the areas in conflict or changed by the update, then the **whole gate on the combined tree**.
5. **Review the update delta** (what the merge changed relative to the reviewed head) independently, in addition to the slice diff.
6. **Stop** when the update changes approved behaviour or touches another slice's rule, compliance proof or guard: the responsible decides; the user decides product, scope or compliance.
7. **Integrate** with `git merge --no-ff` once the integration branch has not moved since step 2 (otherwise repeat from step 2), carrying the reconciled register and integration evidence.

**Commit (integration):** the `--no-ff` merge, at step 7, with trailers `Slice: <id>` and `Phase: integration`. Only now is the slice's `done` authoritative; release its dependents at once, never holding them for slices outside this integration. On failure, the integration branch stays unchanged, the slice branch is preserved, and the blocker is reported.

**Sequential shortcut:** when the integration branch has not moved since the branch started (no other work in execution), steps 2–5 are empty; step 7 is a plain `git merge --no-ff`, and the last whole gate on the frozen head (SKILL.md *When it runs*) is the combined-tree evidence.

### Batches

The normal way to integrate several ready elements (slices with phase 3 committed, bug fixes, R-lane work): it saves gates, never checks.

1. **Batch branch** from the current integration branch. Each element arrives frozen and reviewed (queue step 1); it is not updated separately.
2. **One merge per element:** `git merge --no-ff` with its trailers (`Slice: <id>`, `Phase: integration` for slices); registers and shared records merge by `id`, element by element (*Registers and shared records*).
3. **Record each conflict resolution** in its merge commit (queue step 3).
4. **Review resolutions before the gate:** the exact delta of every code conflict resolution, or hand edit, beyond the merged sides is reviewed by someone who did not make the merge, who also gets the list of files changed by two or more elements, even without conflict, for a short look at semantic conflicts. This is the batch's update-delta review (queue step 5).
5. **Stop** under queue step 6.
6. **One whole gate on the combined tree**, after the focused tests of the conflicting areas.
7. **Integrate** once the integration branch has not moved since batch step 1: fast-forward to the batch branch, or `git merge --no-ff` of it if the project prefers; otherwise merge the integration branch into the batch branch and repeat from step 4 for what changed. A documentation-only closure commit (register states, notes, evidence) is published with it, with cheap validators instead of a new gate (SKILL *When it runs*). Each element's dependents are released when the batch lands.
8. **Failure:** diagnose; cut a new batch branch without the culprit and repeat; the culprit returns to its branch with the finding. If no culprit can be isolated, integrate the elements one at a time.

**Commit (integration):** each element's merge at step 2 and the closure commit at step 7 (one `Slice:` trailer per slice, `Phase: integration`). On failure, the integration branch stays unchanged.

**Metrics per integration:** the integration commit (a batch's closure commit) states, per element: admission-to-integration time, conflicts and time to resolve them, whole-gate runs, amendments and spec gaps. Step 6 aggregates them from Git; they may be reviewed at any integration, not only at closure.

## Registers and shared records

- Merge the register **by `id`**, never by whole file: apply the candidate's row changes and new notes onto the authoritative register; keep authoritative scheduling fields (`dependsOn`, `parallelAllowed`, envelope); recompute readiness. Resolve it semantically even when Git reports no conflict.
- Other id-keyed shared records (matrices, assessments, indexes) merge by `id` too. Generated files are regenerated on the combined tree, never merged by hand.
- Only the integrator writes the authoritative register, including plan revisions and feature closure, serialized with integrations. A plan revision pauses only the slices whose plan artefacts change. Feature closure needs its own slices integrated, not every worker idle.

## Register fields

`parallelAllowed: true` records permission: per slice, or the project's concurrency decision cited in the Step 4 note. `plannedFiles` and the optional `areas` (REGISTER-SCHEMA) form the envelope forecast. Within a declared area, work proceeds and the integrator records and reports new paths; a new area follows IMPLEMENTATION *Scope changes*.
