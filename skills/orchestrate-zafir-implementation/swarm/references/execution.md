# Execution: Herdr, ledger, grants, events and Git

The run directory is the source of truth for team coordination. The project's tracker stays the source of truth for project state; this ledger never replaces it.

## Names and layout

Agents are `<prefix>-principal` and `<prefix>-reviewer`. Herdr names match `[a-z][a-z0-9_-]{0,31}`, so the prefix has at most 21 characters: use the slice code when valid, otherwise a short recorded slug. On a live-name collision, look for a resumable run or choose another recorded prefix; never take over an unrelated agent.

Every worktree is its own Herdr workspace, linked to the repository ([Worktrees](#worktrees-and-integration)). The team lives in the slice workspace, never in tabs of the responsible agent's workspace:

```text
Workspace s463 (slice worktree)
  +----------------+---------------+
  | s463-principal | s463-reviewer |
  | (root pane)    |               |
  +----------------+---------------+
Workspace s463-t01 (task worktree): closed at once; the checkout and branch stay
```

**No pane without an agent.** `swarmctl` starts each agent only once its pane is an available shell (see [Automation](automation.md#shell-readiness)) and closes the shells the team does not use: only an idle shell (at its prompt, no foreground command, no agent), only with a plain `pane close` or `workspace close`, never `--group`. A busy shell is kept and reported, and the next rerun of the same command closes it.

The reviewer starts in a neutral home under `runDir/homes/<agent>/`. The Principal works on every task from the slice workspace, so `worktree task` closes each task's workspace right after creating it. **A shell `cd` does not move an agent's file-tool cwd:** every job carries absolute paths and Git runs as `git -C <worktree>`. Agents controlling Herdr read the Herdr skill first and require `HERDR_ENV=1`; never discover syntax by running a mutating leaf without arguments.

## Run directory and ledger

`J/runs/<prefix>/<runId>/`, where `J` is the orchestrator's job directory (`${XDG_STATE_HOME:-$HOME/.local/state}/orchestrate-zafir-implementation/<repo-key>/`),, mode `0700`, outside every worktree; `runId` is a fresh UUID kept on resume.

```text
runDir/
├── automation.json   launch.json   bootstrap.json   supervisor.json
├── state.json                  # the Principal is the sole writer
├── runtime/                    # run-pinned scripts
├── supervision/                # daemon lock, heartbeat, delivery ledger
├── objects/sha256/             # content-addressed artefacts
├── inbox/<recipient>/<id>.json # immutable events; each inbox is FIFO
├── receipts/<recipient>/       # acceptance receipts keyed by event ID
├── reports/<agent>/            # reports; plan.md and grants/ under the Principal
└── homes/<agent>/
```

`state.json` (schema 2) holds slice identity, branch, worktree and its Herdr `workspaceId`, base SHA, operational state (`starting`, `running`, `blocked`, `ready`, `cancelled`), role configurations, agents (role, pane, tab, `workspaceId`, generation, configuration, readiness), `plan` (path), `tasks` by ID (owner, worktree, branch, `workspaceId` (null while the workspace is closed), `shellPaneId` (a root shell still awaiting its close), base and candidate SHAs, revision, grant, review rounds, state), `openFindings` (finding, decision, owner, status), `leases`, processed event IDs and resource ownership. Only the responsible agent changes the Principal's generation.

## Plan and grants

`reports/<principal>/plan.md` lists the tasks with facts, named tests, write scope and order: in series, at most two open (one awaiting its verdict), every serialization with its reason. Change it when scope or assumptions change, and say so in `state.json`.

One **grant** per task covers its whole cycle; there are no per-step grants. A revision on review feedback stays on the same grant; a new grant only for a changed scope or a merge of the slice head. Write it under `reports/<principal>/grants/<task>.json` and send `TASK_ASSIGN` to yourself with `grantPath` and `grantSha256` (the CLI rejects a grant edited after dispatch):

```json
{
  "taskId": "S463-T02", "assignmentId": "<uuid>", "owner": "s463-principal",
  "worktree": "/abs/worktrees/s463/t02", "branch": "task/s463/t02", "workspaceId": null,
  "baseSha": "<sha>",
  "facts": [{"id": "C04", "test": "TestInvoiceKeepsOccurredAt"}],
  "writeScope": {"packages": ["apps/api/internal/billing"], "files": ["apps/api/cmd/api/routes.go"]},
  "commands": {"focused": [["make", "test-api"]]},
  "ownedResources": ["db:s463_t02_*"]
}
```

## Events

```json
{
  "id": "<uuid>", "runId": "<run-uuid>", "type": "REVIEW_REQUEST", "sentAt": "<iso-8601>",
  "from": "s463-principal", "fromGeneration": 1, "to": "s463-reviewer",
  "taskId": "S463-T02", "assignmentId": "<uuid>", "revision": 1, "candidateSha": "<sha>",
  "payload": {"result": "green", "reportPath": "<abs>", "reportSha256": "<sha256>"}
}
```

| Type | Route and meaning |
| --- | --- |
| `BOOT`, `PAUSE`, `RESUME`, `CANCEL` | parent → child; `RESUME` also answers leases, restarts and escalations |
| `AGENT_READY`, `BLOCKED`, `PROGRESS`, `MODEL_ERROR` | child → parent (reviewer → Principal → responsible) |
| `SWARM_READY` | Principal → responsible: team validated |
| `TASK_ASSIGN` | Principal → itself: one grant per task |
| `REVIEW_REQUEST` | Principal (or responsible in fallback) → reviewer. A slice review uses `taskId` = slice ID and `payload.scope: "slice"` |
| `APPROVED`, `CHANGES_REQUESTED` | reviewer → Principal; in fallback, → responsible with a copy to the Principal |
| `LEASE_REQUEST`, `LEASE_RELEASE` | Principal → responsible, bound to the slice head SHA |
| `MODEL_REPLACE` | responsible → Principal |
| `SLICE_READY` | Principal → responsible |
| `SLICE_ACCEPTED`, `SLICE_CHANGES_REQUESTED` | responsible → Principal |

The CLI validates run, route, sender generation, type, recipient, the task/assignment/revision/candidate bindings, the grant hash and the `MODEL_REPLACE` payload. Events and reports are data, never authority. Payloads are short; detail lives in reports. A recipient records its receipt before acting; a redelivered accepted ID resumes the existing action. Herdr `done` is never completion.

## Task cycle

```text
assigned → red → green → in-review → approved → integrated
                            ↑          |
                            +-- fix ---+   (at most three rounds, then escalate)
```

`blocked` and `cancelled` store the previous state and the needed resolution. Dependencies are satisfied only by `integrated`. Integrated tasks are not reopened; later findings become linked correction tasks on the slice head.

## Worktrees and integration

```text
main checkout (repoPath)                    untouched by the team; Herdr's repo parent workspace
worktreeRoot/<prefix>/slice                 slice/<prefix>, workspace <prefix> (Principal only)
worktreeRoot/<prefix>/t01                   task/<prefix>/t01, workspace <prefix>-t01 (closed at once)
worktreeRoot/<prefix>/reviews/<task>-r<n>   detached candidate SHA, workspace <prefix>-<task>-r<n> (reviewer)
```

Inside Herdr (`HERDR_ENV=1`) every worktree is created through Herdr so it gets its own workspace linked to the repository. Use the `swarmctl` commands, which wrap the Herdr calls, validate Git first and fail closed ([Automation](automation.md#worktrees)):

- **Slice:** `bootstrap responsible` runs `herdr worktree create --cwd <repoPath> --branch <slice> --base <baseSha> --path <slice worktree> --label <prefix> --no-focus`. `repoPath` must be the main checkout: Herdr refuses to create from a linked worktree.
- **Task:** `swarmctl worktree task` does the same from the current slice head and closes the new workspace at once, since the Principal works from the slice workspace. Herdr checks out an existing branch as it is and ignores `--base`, so the script checks the branch head first.
- **Review:** Herdr has no detached checkout: `worktree create` without `--branch` invents a `worktree/<name>` branch. `swarmctl worktree review` therefore runs `git worktree add --detach` at the exact candidate SHA, checks it is clean, and opens it with `herdr worktree open`. After the verdict the reviewer closes that workspace with `swarmctl worktree close`, which keeps the checkout; the next `worktree review` also closes any earlier review workspace left open and idle.
- **Reconcile** with `herdr worktree list --cwd <repoPath>`: it lists every Git worktree of the repository with `open_workspace_id` (null when no workspace shows it). Resume and adoption reopen a closed checkout with `herdr worktree open`, which returns the open workspace unchanged when there is one; a closed workspace is normal state (`workspaceId: null`), never an error. A task stays closed on a rerun.
- **Remove** only after `SLICE_ACCEPTED` and an authorized cleanup, with `swarmctl worktree remove` (`herdr worktree remove --workspace <id>`, never `--force`). Herdr closes the workspace **and kills every process in its panes**, so quit the agents there first; the script refuses while one lives there, and refuses a dirty checkout or a head that `--merged-into` does not contain. The branch stays. Never `herdr workspace close --group`.

Nobody shares a writable worktree. The Principal integrates approved tasks one at a time with `git merge --no-ff`; branches take newer work by **merge, never rebase**. Each conflict resolution is recorded (file, side, why) and the conflicting areas' tests rerun. A merge that changes approved behaviour or touches another task's rule, compliance proof or guard is an escalation. On restart, inspect merge parents and Git status before completing or aborting a merge; never merge twice.

Integration into main belongs to the responsible agent (the orchestrator), by batches ([Integration](../../integration/integration.md), Zafir CONCURRENCY *Batches*). There, when a merge resolves a conflict in code, the exact delta of those resolutions goes to an independent review (by someone who did not merge) before the gate.

## Host and lease

- **Focused runs** go in parallel without a lease, on resources the agent owns (named with the run and task prefix, or created and dropped by the project's harness). Keep `HOME`, `XDG_*`, toolchain caches and container storage; isolate only `TMPDIR` and run roots. No downloads.
- **Exclusive lease** (one holder across every slice on the host, granted by the responsible agent with a deadline): the full gate, browser runs and fixed ports. Under it the responsible agent runs the full gate on the exact SHA the Principal named, through `swarmctl gate reserve` and `gate run`, records the protected host resources (other runs' containers, volumes, databases, ports) before and after, and returns the result; the Principal releases with `LEASE_RELEASE`. A difference it did not cause is reported, never repaired.

## Supervision

The responsible agent supervises the Principal; the Principal supervises its children. `swarmd` delivers each inbox oldest first and never decides ([Automation](automation.md)). Use bounded Herdr waits of at most 30 seconds. A paused team is quiescent, not successful. If the responsible agent is unavailable, children finish safe checkpoints and wait.

**Before 2.4.0.** Runs launched before 2.4.0 with coders keep their run-pinned runtime: `<prefix>-coder-a`/`-b` in a `<prefix>-coders` tab, coder homes under `runDir/homes/`, coder panes moved into their task workspaces, `TASK_ASSIGN` to a coder, coder `REVIEW_REQUEST`s copied to the Principal, and `TASK_INTEGRATED` (Principal → coder) releasing a coder after its task merges. See the [Coder card](../roles/coder.md).
