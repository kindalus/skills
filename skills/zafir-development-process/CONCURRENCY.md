# Concurrency and integration

Procedure under [SKILL.md](SKILL.md), using its [Terms](SKILL.md#terms). Read it when more than one slice is in execution, and at every integration. Every slice, bug fix and R-lane change reaches the integration branch through the integration queue ([Own branch, always](SKILL.md#standing-rules)).

This file replaces the former file-disjoint *Parallel exception*. Overlapping files are allowed: safety comes from the integration queue, not from file reservations.

## Prerequisites

Execution is sequential by default. Concurrency is a project decision recorded once, not a per-slice ceremony. Record it as an `architecture.md` Decisions entry, in the project's decisions location, or as a dated register note.

Concurrency requires all three:

1. a whole gate ([Green means the whole gate](SKILL.md#green-means-the-whole-gate)) that runs reliably on the combined tree (the integration branch merged with the candidate slice or batch);
2. independent review, by someone who did not write the diff ([independent reviewer](SKILL.md#roles));
3. one named integrator and one authoritative integration branch.

Without all three, run one slice at a time.

A project that recorded a stricter policy (for example, file-disjoint envelopes) keeps it under [precedence rule 1](SKILL.md#precedence-and-exceptions). Every rule below still applies to it.

## Cap

- By default, at most **3 slices** are in execution. A transversal slice counts as two.
- A project may set another cap locally ([precedence](SKILL.md#precedence-and-exceptions) rule 1 or 5).
- Real capacity (hosts, disk, gate time) may lower dispatch below the cap.
- Review the cap with the metrics of [Step 6](IMPLEMENTATION.md#step-6--close-the-feature).

## Admission

A slice enters execution only when all hold:

- Its preparation is complete: 5.4 is approved.
- The **authoritative** register shows it `implementable`.
- Every dependency is authoritatively `done`: integrated, not merely `done` on a worker's copy.
- The admission freshness check passed ([Just-in-time and freshness](PREPARATION.md#just-in-time-and-freshness)).
- The cap allows it.
- The serial rules below hold against every slice in execution.

**Serial only for:**

1. **Behaviour dependencies:** one slice consumes another's behaviour, contract, decision or discovery, directly or transitively. Learning is a dependency.
2. **Two transversal slices**, unless they are partitioned by domain with no shared function.
3. **The same function, rule, guard or migration** changed by two slices, unless their impact maps prove they do not touch it.

Envelopes (`plannedFiles`, and the optional `areas`) are forecasts, not reservations. Their overlap alone never blocks admission.

- Prefer the decided table order.
- The integrator serializes admission decisions, so two checks cannot race.
- A dependency discovered during execution pauses the later slice, and admission is recomputed. Unrelated slices continue.

Each slice runs on its own branch and worktree, with isolated mutable test resources (databases, ports, caches, fixtures, run directories). Workers, worktrees and admission events live in the external execution system. They add no register state and no commit.

## Integration queue

One integrator runs one integration at a time, in order of readiness. An integration takes a single slice (the steps below) or a [batch](#batches). A younger slice overtakes an older one only through a declared dependency.

1. **Freeze** the candidate head. Its own `git diff <base>` review (5.7) is complete.
2. **Update by merge:** merge the current integration branch into the slice branch. Use merge only, never rebase, squash or cherry-pick: phase commits, their SHAs and `base` remain evidence.
3. **Record each conflict resolution** (file, side kept, why) in the merge commit message.
4. **Re-run** the focused tests of the areas in conflict or changed by the update. Then run the **whole gate on the combined tree**.
5. **Review the update delta**: what the merge changed relative to the reviewed head. An independent reviewer does it, in addition to the review of the slice diff.
6. **Stop** when the update changes approved behaviour or touches another slice's rule, compliance proof or guard. The responsible decides; the user decides product, scope or compliance.
7. **Integrate** with `git merge --no-ff`, carrying the reconciled register and the integration evidence. Do it only if the integration branch has not moved since step 2; otherwise repeat from step 2.

**Commit (integration):** the `--no-ff` merge at step 7, with trailers `Slice: <id>` and `Phase: integration`.

- Only now is the slice's `done` authoritative.
- Release its dependents at once. Never hold them for slices outside this integration.
- On failure, the integration branch stays unchanged, the slice branch is preserved, and the blocker is reported.

**Sequential shortcut:** it applies when the integration branch has not moved since the slice branch started (no other work in execution).

- Steps 2–5 are empty.
- Step 7 is a plain `git merge --no-ff`.
- The last whole gate on the frozen head ([When it runs](SKILL.md#green-means-the-whole-gate)) is the combined-tree evidence.

**Merge queue.** When one exclusive lease serialises whole gates, it is the default for slices developed in parallel, and it replaces the slice's separate integration gate:

1. The slice finishes its tasks and its review (5.7 before 5.6), then asks for the gate.
2. When the lease is free, the integrator merges the current integration branch into the slice branch (queue steps 2–3). A code conflict returns the slice to its team without the lease; registers and shared records still merge by `id`.
3. A clean merge gets the whole gate (5.6) on that exact commit, under the lease. Meanwhile an independent reviewer looks at the files both sides changed (queue step 5).
4. Green integrates at once (queue step 7): nothing else entered under the lease, so the gated tree is the combined tree. Red returns the result.
5. Phase 3 follows on top of the integration branch and integrates as documentation (cheap validators).

**Routing a ready slice.** Outside the merge queue, a slice merges the current integration branch before its own whole gate. When it is ready (phase 3 committed), compute its merge with the current integration branch without a worktree (`git merge-tree --write-tree`) and compare the result with the tree of its last green whole gate:

| Combined tree | Route | Gate |
| --- | --- | --- |
| identical | integrate now, alone | none: cite the slice's green whole gate |
| differs only in documentation | integrate now, alone | cheap validators |
| differs in code, merges cleanly | join the next [batch](#batches) with every element ready then | one whole gate for the batch |
| conflicts | back to the slice branch: queue steps 2–5, then its own whole gate again | as its new route |

"Documentation" is the project's documentation tree; tests, migrations, scripts, build files and fixtures are code.

### Batches

A batch is the normal way to integrate several ready elements: slices with phase 3 committed, bug fixes, R-lane work. It saves gates, never checks.

1. **Batch branch:** cut it from the current integration branch. Each element arrives frozen and reviewed (queue step 1). Elements are not updated separately.
2. **One merge per element:** `git merge --no-ff` with its trailers (`Slice: <id>` and `Phase: integration` for slices). Registers and shared records merge by `id`, element by element ([Registers and shared records](#registers-and-shared-records)).
3. **Record each conflict resolution** in its merge commit (queue step 3).
4. **Review resolutions before the gate.** This is the batch's update-delta review (queue step 5).
   - The reviewer is someone who did not make the merge.
   - They review the exact delta of every code conflict resolution, or hand edit, beyond the merged sides.
   - They also get the list of files changed by two or more elements, even without conflict, for a short look at semantic conflicts.
5. **Stop** under queue step 6.
6. **One whole gate on the combined tree**, after the focused tests of the conflicting areas.
7. **Integrate**, if the integration branch has not moved since batch step 1:
   - fast-forward it to the batch branch, or `git merge --no-ff` the batch branch if the project prefers;
   - if it moved, merge the integration branch into the batch branch and repeat from step 4 for what changed.

   A documentation-only closure commit (register states, notes, evidence) is published with the batch. It runs cheap validators instead of a new gate ([When it runs](SKILL.md#green-means-the-whole-gate)). Each element's dependents are released when the batch lands.
8. **Failure:** diagnose. Cut a new batch branch without the culprit and repeat. The culprit returns to its branch with the finding. If no culprit can be isolated, integrate the elements one at a time.

**Commit (integration):** each element's merge at step 2, and the closure commit at step 7 (one `Slice:` trailer per slice, `Phase: integration`). On failure, the integration branch stays unchanged.

**Metrics per integration:** the integration commit states these per element; for a batch, its closure commit does:

- admission-to-integration time (from admission into execution to integration);
- conflicts, and the time to resolve them;
- whole-gate runs;
- amendments and spec gaps.

Step 6 aggregates them from Git. They may be reviewed at any integration, not only at closure.

## Registers and shared records

- Merge the register **by `id`**, by script ([Tool discipline](SKILL.md#tool-discipline)), never as a whole file:
  - apply the candidate's row changes and new notes onto the authoritative register;
  - keep the authoritative scheduling fields (`dependsOn`, `parallelAllowed`, envelope);
  - recompute readiness.

  Resolve the register semantically even when Git reports no conflict.
- Other id-keyed shared records (matrices, assessments, indexes) merge by `id` too.
- Regenerate generated files on the combined tree; never merge them by hand.
- Only the integrator writes the authoritative register, serialized with integrations. This includes phase-1 commits ([5.4](PREPARATION.md#54-agree-the-seams-then-define-the-acceptance-scenarios)), plan revisions and feature closure.
- A plan revision pauses only the slices whose plan artefacts change.
- Feature closure needs the feature's own slices integrated, not every worker idle.

## Register fields

- `parallelAllowed: true` records permission: per slice, or through the project's concurrency decision cited in the Step 4 note.
- `plannedFiles` and the optional `areas` ([Zafir extension fields](REGISTER-SCHEMA.md#zafir-extension-fields)) form the envelope forecast.
- Within a declared area, work proceeds, and the integrator records and reports new paths.
- A new area follows [Scope changes](IMPLEMENTATION.md#scope-changes).
