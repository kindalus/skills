# Integration

The orchestrator is the single integrator into main. Zafir CONCURRENCY *Integration queue* and *Batches* are the procedure; this section adds only how the team feeds them.

- Route each `SLICE_READY` at once by Zafir CONCURRENCY *Routing a ready slice*: an unchanged or documentation-only combined tree integrates now, alone, reusing the slice's green whole gate; a combined tree that changed in code joins the next code batch, with every slice and bug fix ready then; a conflict goes back to the swarm to merge main and gate again.
- **Merge, never rebase**, at every step. Record each conflict resolution (file, side kept, why) in its merge commit.
- Shell output and records follow Zafir *Tool discipline*: registers and shared records merge by ID through `zafir-development-process/scripts/json_merge_by_id.py`, never by hand.

## Code batches

1. **Freeze.** For each element, confirm the head SHA still matches its branch and its minimum evidence ([responsible card](../swarm/roles/responsible.md#receive-and-integrate)). Number the batch with the next free ID and log its elements.
2. **Batch branch.** Cut `integ/batch-<n>` from current main in its own Herdr worktree and merge each element with `git merge --no-ff` and its trailers (CONCURRENCY *Batches*, steps 1–3).
3. **Resolution review.** When a merge resolved a code conflict, send the exact delta of the resolutions, and the list of files two or more elements changed, to an independent reviewer who did not merge: a consultant grant, or the reviewer of a swarm in the batch. Stop under queue step 6.
4. **Gate plan.** The focused tests of the conflicting areas, then one whole gate on the combined tree under the exclusive host lease, run with the project's real command; record its log, exit and the protected host resources before and after in `J/gates/batch-<n>/`. On red, CONCURRENCY *Batches* step 8.
5. **Close.** Fast-forward main to the batch branch (or `--no-ff`, per the project), with the documentation-only closure commit (register states, notes, metrics per element). If main moved, merge it into the batch branch and repeat from step 3 for what changed.
6. **Push** main at batch close: this is the batch flow. Any other push goes to the owner.
7. **Accept.** Send `SLICE_ACCEPTED` to each swarm in the batch, release the dependents, and log the batch with its SHA.

Done when main holds the batch, the push succeeded, and every element is accepted or returned with its finding.

## Documentation batches

Phase-1 commits from preparers (and other documentation-only commits) integrate in documentation batches:

1. Cut `integ/batch-<n>` from main and merge each `prep/<slice>` with `--no-ff`; resolve the register and shared records by ID, by script.
2. Run the project's cheap validators (register, specs, generator check) instead of a gate (Zafir *Green means the whole gate*, *When it runs*).
3. Fast-forward main, push, log the batch, and close each preparer whose phase 1 landed.

A documentation batch may join a code batch when both are ready at the same moment; the code batch's gate then covers it.

## Cleanup

Only after acceptance, and once the cleanup is authorized:

- **Swarms:** the responsible card's *Receive and integrate*, step 4: quit the team's agents, then `swarmctl worktree remove` each run worktree, unforced, keeping the branches.
- **Preparers and batches:** quit the agent first, then `herdr worktree remove --workspace <id>` for a clean worktree whose head main contains (reopen a closed one with `herdr worktree open` to get its workspace). A dirty or uncontained one stays and is reported; never `--force`, never `herdr workspace close --group`.
- Log what was removed and what stayed, with the reason.
