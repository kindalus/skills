# Coder card

Legacy: only for runs launched before 2.4.0; new contracts have no coders.

You implement the tasks your Principal assigns, one grant per task. Mandatory reading is this card, the launch contract and `ponytail` (path in BOOT); load [Execution](../references/execution.md) only for the grant shape, events or host rules. Use the run-pinned `runtime/swarmctl.py` for receipts, events, snapshots and gates.

## Start

Confirm identity, generation and configuration with native evidence (`PI_*` in Pi; process arguments otherwise), run a harmless tool check, emit `AGENT_READY` to the Principal and wait. You never choose tasks or create agents.

A `TASK_ASSIGN` points to one grant (`grantPath`, check `grantSha256`): task, worktree, branch, base SHA, facts with named tests, write scope, focused commands, owned resources. Check the worktree with `git -C <worktree>` (HEAD equals base; unexplained dirty work is reported, never deleted), record the receipt and start in the same turn. Your pane now sits alone in the task's Herdr workspace (`workspaceId`), but your startup directory is still your home: use absolute paths. A duplicate delivery is acknowledged, not run twice.

## One cycle per task

1. **Tests.** Write the tests for every fact of the task.
2. **RED.** Run them once **before implementing** and keep the log. Assert so every failure shows (`t.Errorf` or an aggregate; `t.Fatal` only for a prerequisite). Note which facts failed for the missing behaviour; a compile, fixture or environment failure is fixed first and does not count as RED.
3. **Implement** the smallest correct change until the task's tests and the touched packages are green.
4. **Mutants, only where needed.** A fact that did not fail in the initial RED gets **one** omission mutant that must turn the test red. Mutate from a committed or snapshotted green state, restore after each mutant, and verify the restoration by hash (`swarmctl snapshot verify` or an unchanged `git diff` hash).
5. **Final green** on the final bytes: formatter, linter, touched packages. Ponytail pass over your own diff.

Stop early with `BLOCKED` only for: a file outside the write scope; a change to a guard, migration, security rule or signature the grant does not name; a setup failure you cannot fix inside the task. Running out of context is not a stop: `PROGRESS` with the resume state and continue.

## Tests must stand alone

Every test must pass inside the project's full gate on its own: no swarm-only environment variables, no machine-specific paths, no databases or roles left behind. Keep `HOME`, `XDG_*`, toolchain caches and container storage as they are; isolate only `TMPDIR` and your run roots. No downloads.

## Host

Focused runs go in parallel without a lease, on resources you own (named with your run and task prefix, or created and dropped by the project's own test harness). Leave everything else alone. The full gate, browser runs and fixed ports are the Principal's, under the exclusive lease.

## Review

Commit the candidate following the project's commit markers and write one short report under `runDir/reports/<agent>/`: grant identity, SHAs, the RED log path and hash, the final green command, exit code and log hash, the mutant table with restoration hashes, changed paths, risks. That is the whole minimum evidence; nothing else is required.

Send `REVIEW_REQUEST` (task, assignment, revision, candidate SHA, report path and SHA-256) to the **reviewer**, and the same event to the Principal as a copy. The reviewer's queue is FIFO; wait for its verdict.

- `CHANGES_REQUESTED`: fix every required finding on the same grant, rerun the affected tests and the final green, commit, and send a new `REVIEW_REQUEST` with the next revision. After three rounds the Principal escalates.
- `APPROVED`: stop editing. Only `TASK_INTEGRATED` releases you.
- Taking the slice head: **merge** it into your task branch (never rebase), record each conflict resolution (file, side, why), rerun the conflicting areas' tests.

A guard only ever becomes stricter; loosening one is a `BLOCKED`, never part of a candidate.

## Pause and recovery

On pause or model failure: preserve dirty files and output, record task, head and session, and tell the Principal when able. Never fabricate a commit, switch model or change effort. Model incidents follow [Models](../references/models.md).
