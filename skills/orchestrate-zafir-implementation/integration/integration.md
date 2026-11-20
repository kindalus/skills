# Integration

The orchestrator is the single integrator into main. Zafir CONCURRENCY *Integration queue* and *Batches* are the procedure; this section adds only how the team feeds them.

- **Merge queue** (Zafir CONCURRENCY *Merge queue*): a lead's gate request, sent after its deep review, is its integration. Merge current main into the slice, return a code conflict without the lease, gate the clean merge, and integrate it into main at once on green. Its phase-3 handoff then integrates as a documentation batch.
- Outside the merge queue, route each handoff at once by Zafir CONCURRENCY *Routing a ready slice*: an unchanged or documentation-only combined tree integrates now, alone, reusing the slice's green whole gate; a combined tree that changed in code joins the next code batch, with every slice and bug fix ready then; a conflict goes back to the lead to merge main and gate again.
- **Merge, never rebase**, at every step. Record each conflict resolution (file, side kept, why) in its merge commit.
- Shell output and records follow Zafir *Tool discipline*: registers and shared records merge by ID through `zafir-development-process/scripts/json_merge_by_id.py`, never by hand.

## Code batches

1. **Freeze.** For each element, confirm the head SHA still matches its branch and its minimum evidence: the review approvals (each task and the deep review), the gate record and, for phase 3, the short review of its delta. Do not re-verify what the reviews and the gate already recorded. Number the batch with the next free ID and log its elements.
2. **Batch branch.** Cut the batch branch from current main in its own Herdr worktree and workspace, named per [Naming](../references/naming.md#table), and merge each element with `git merge --no-ff` and its trailers (CONCURRENCY *Batches*, steps 1–3).
3. **Resolution review.** When a merge resolved a code conflict, send the exact delta of the resolutions, and the list of files two or more elements changed, to an independent reviewer who did not merge: a consultant grant. Stop under queue step 6.
4. **Gate plan.** The focused tests of the conflicting areas, then one whole gate on the combined tree under the exclusive host lease, run with the project's real command; record its log, exit and the protected host resources before and after in `J/gates/batch-<n>/`. On red, CONCURRENCY *Batches* step 8.
5. **Close.** Fast-forward main to the batch branch (or `--no-ff`, per the project), with the documentation-only closure commit (register states, notes, metrics per element). If main moved, merge it into the batch branch and repeat from step 3 for what changed.
6. **Push** main at batch close: this is the batch flow. Any other push goes to the owner.
7. **Accept.** Tell each element's lead, on its thread, that the slice is accepted with the main SHA; export the slice's thread into its evidence (`courier thread <SLICE> --space orch --json > <evidence dir>/courier-thread.json`), release the dependents, log the batch with its SHA, and close the batch workspace with a plain `herdr workspace close`.

Done when main holds the batch, the push succeeded, and every element is accepted or returned with its finding.

## Documentation batches

Phase-1 commits from preparers (and other documentation-only commits) integrate in documentation batches:

1. Cut the batch branch ([Naming](../references/naming.md#table)) from main and merge each preparer's branch with `--no-ff`; resolve the register and shared records by ID, by script.
2. Run the project's cheap validators (register, specs, generator check) instead of a gate (Zafir *Green means the whole gate*, *When it runs*).
3. Fast-forward main, push, log the batch, close its workspace as in code batches, and close each preparer whose phase 1 landed.

A documentation batch may join a code batch when both are ready at the same moment; the code batch's gate then covers it.

## Cleanup

Only after acceptance, and once the cleanup is authorized:

- **Implementer leads** ([Close](../implementation/implementation.md#close)): quit the lead, then remove its slice, task and review worktrees with `herdr worktree remove --workspace <id>` (or `git worktree remove`) when clean and contained in main, keeping the branches.
- **Preparers, bug fixes, admissions and batches** (their [Naming](../references/naming.md#table) worktrees): quit the agent first, then `herdr worktree remove --workspace <id>` for a clean worktree whose head main contains (reopen a closed one with `herdr worktree open` to get its workspace). A dirty or uncontained one stays and is reported; never `--force`, never `herdr workspace close --group`.
- Log what was removed and what stayed, with the reason.
