# Swarm

A swarm implements one approved slice (Zafir 5.5–5.7) from the project's **delivery package** and hands it to the orchestrator as `SLICE_READY`. The orchestrator is the swarm's **responsible agent**: it launches and supervises the run, owns the host's exclusive lease, answers escalations, and is the single integrator into main. Versioned scripts do the deterministic mechanics (bootstrap, event delivery, snapshots, gates); agents keep every scope, review, integration and recovery decision. Reading this section launches nothing.

## Roster

| Role | Count | Default triple | Does |
| --- | --- | --- | --- |
| Principal | exactly 1 | `codex gpt-6.1-sol high` (yolo mode) | plans, implements every task, integrates tasks into the slice branch, asks for the slice gate |
| Reviewer | exactly 1 | `claude claude-opus-5-5 high` | reviews tasks and the slice; always a model family other than the Principal's |

**No coders** (owner decision 2026-10-14): the Principal implements every task in series, and `roster.coders` is always 0. The orchestrator copies the triples into the launch contract explicitly (owner or project defaults win over these); the scripts reject a reviewer of the same family as the Principal. Sole exception, by owner decision: when the Claude reviewer exhausts its quota, `MODEL_REPLACE` may install the **reviewer quota fallback** `codex gpt-6.1-sol high` for task reviews, and the Claude reviewer re-reviews those tasks in the deep slice review before `SLICE_READY` ([Models](references/models.md#reviewer-quota-fallback-owner-decision-2026-10-02)).

## Launch

- Launch only after reading the admission's dispatch notes, not just its verdict. The notes are binding: copy them into the BOOT brief, and a technical blocker among them stops the launch.
- **Preflight:** delivery package, launch contract, `swarmctl doctor`, `bootstrap responsible --dry-run`. Done when the dry run is clean.
- **Bootstrap:** `bootstrap responsible` creates the slice worktree's Herdr workspace and starts the Principal in its root pane; after its `AGENT_READY` and the orchestrator's `RESUME`, `bootstrap principal` starts the reviewer. Done on a validated `SWARM_READY`.

## Cycle

1. **Plan.** The Principal writes the slice plan on top of the delivery package: tasks in order (dependency, then risk), the scenarios and tests of each task, and the write scope.
2. **All the slice's tests, then tasks.** Following Zafir IMPLEMENTATION 5.5: before any production code (except, when the seams are new, one commit with only their fail-closed contract skeleton so the tests compile), the Principal writes the tests of every scenario of the slice, runs them once and keeps the **slice RED log** (each test failing for its own reason; one that only fails to compile is fixed first), in one tests-only commit that every task branches from. When fixture mechanics keep tests from their target, one bounded test-plumbing commit may precede the battery, and a fact still unreachable is NON-CAUSAL in the RED log, with an omission mutant at its green step. Then it assigns every task to itself, in series (while one waits for its verdict it may start the next independent one, never more than two open). Each task has its own task worktree and one grant.
3. **One cycle per task:** turn the task's tests green **one at a time** (or a small cohesive group), in the plan's order, with the smallest correct change each and a commit per green step; a purely mechanical change (M1: rename, argument propagated to consumers) may go in one batch. Then `REVIEW_REQUEST` to the reviewer (a FIFO queue); fix on each verdict until approved. A fact without its own causal RED (already green in the slice RED, green without new code, done in a batch) gets one omission mutant, restored and hash-verified.
4. **Integrate.** With every task approved, the Principal merges them into the slice branch (`merge --no-ff`, never rebase) and runs the focused tests.
5. **Refactor.** With every test green, the Principal refactors the slice diff with `ponytail`: behaviour unchanged, every test still green, one refactor commit.
6. **Before the gate:** merge current main into the slice branch (never rebase, each resolution recorded), then run the project's full compliance suite and the tests of every guard the slice touches.
7. **Deep slice review**, by the reviewer, fixing until convergence; a fix that changes code reruns step 6.
8. **Merge queue.** With the deep review approved, the Principal sends `LEASE_REQUEST` with the exact, clean slice head SHA and leaves the worktree alone. When the lease is free, the orchestrator merges current main into the slice branch:
   - a conflict returns the slice to the Principal without the lease: merge main, record each resolution, run the focused tests, and send a new `LEASE_REQUEST`;
   - a clean merge gets the whole gate on that exact SHA under the exclusive lease. The Principal never runs the gate. Red returns the result; green integrates the code into main at once, because nothing else entered main under the lease, and the orchestrator asks for step 9. Meanwhile the reviewer gives the files changed by both main and the slice a short look for semantic conflicts.
9. **Hand off.** With the code in main, merge main into the slice branch and make one **documentation-only commit** (Zafir IMPLEMENTATION 5.7, phase 3): final spec and its amendments log; in the register, only the slice's row and notes; in each per-slice assessment record (for example a privacy impact assessment), only the slice's entry; in a compliance matrix, only notes, with no promotion or reclassification; generated files and pinned hashes only through the project's generator. No new whole gate: the code is already in main, and the delta integrates as a documentation batch; the reviewer gives it a short review. Then `SLICE_READY`, which now means "phase 3 ready". These phase-3 paths are pre-authorised, without asking the orchestrator, as long as they stay within this list.

## Rules

- **Minimum evidence is a closed list.** Slice RED log (all the slice's tests, before production code), and per task: the task's tests green in the order run, and the omission mutants for facts without their own causal RED, with verified restoration. Slice: the compliance suite and touched guards green after the main merge, and the full gate green on the exact commit, with protected host resources checked before and after. Nothing else is mandatory: no per-step hash-bound ledgers, prewrite annexes, per-stage resource tuples, paired restore runs or recorder scripts.
- **Review scope:** code correctness, test meaning and minimum evidence. Process deviations are notes, never blockers unless minimum evidence is missing. Task reviews are short; the slice review is deep.
- **Three review rounds** per task and per slice, then escalate with the open findings.
- **Escalate only** scope, product, legal or compliance rules, security, migrations, guard weakening and models to the orchestrator, which takes the owner's classes to the owner. The Principal decides everything else, records it in the open-findings list and continues: record-and-continue, never stop-on-first.
- **Autonomous tests:** every test passes inside the project's full gate alone: no swarm-only environment variables, machine paths, or leaked database roles or databases.
- **Host:** focused runs go in parallel without a lease, on resources the agent owns. The full gate, browser runs and fixed ports need the exclusive lease.
- **Worktrees are Herdr workspaces**, at the paths of [Naming](../references/naming.md#table): slice and task worktrees come from `herdr worktree create`, review checkouts are opened with `herdr worktree open`, all through `swarmctl`; the team runs in the slice and task workspaces, never in the orchestrator's. **No pane without an agent:** `swarmctl` waits for each new pane to be an available shell before `agent start`, and closes the idle shells nobody uses (a Principal task's workspace, a review workspace after its verdict). Removal is `herdr worktree remove`, after acceptance and an authorized cleanup; never `workspace close --group` ([Execution](references/execution.md#worktrees-and-integration)).
- **Merge, never rebase:** phase SHAs are evidence; each conflict resolution is recorded (file, side, why).
- **Guards only get stricter**; a looser guard is an escalation.
- **Model incidents** go through `MODEL_ERROR` and `MODEL_REPLACE`; nobody substitutes a model or shrinks the team.
- **State lives in files** (plan, `state.json`, reports). The Principal may ask for a clean restart between phases; nothing forces one.
- **Direct-execution fallback:** when the swarm stalls on mechanical work, the orchestrator may do it itself, still sending it to the reviewer.
- **Process frozen at start:** the cards and the process are read at startup. A later change to the project's process applies only to slices whose implementation starts after it (Zafir SKILL.md *Process version*); a slice in progress finishes with the cycle it started with and records the transition in its spec's amendments log.
- No push, team edits on main, force-push, credential changes, destructive cleanup or extra agents. `SLICE_READY` means ready to integrate, not merged.

The slice spec, repository instructions and development process stay authoritative; discover their commands instead of assuming them. This section waives no approval or commit policy; settle conflicts **before dispatch**.

## Reading

Startup reading is the role card plus the launch contract; references load on demand.

| Reader | At startup | On demand |
| --- | --- | --- |
| Orchestrator (responsible) | this file, [Responsible card](roles/responsible.md), `herdr` skill | [Automation](references/automation.md), [Execution](references/execution.md), [Models](references/models.md), [Threat model](references/threat-model.md) |
| Principal | [Principal card](roles/principal.md), `launch.json`, `herdr` skill, `ponytail` | Execution, Automation, Models |
| Coder | Only for runs launched before 2.4.0: [Coder card](roles/coder.md), `launch.json`, `ponytail` | Execution |
| Reviewer | [Reviewer card](roles/reviewer.md), `launch.json` | Execution |

A missing required skill is reported, never silently substituted.

## Launch contract

| Input | Requirement |
| --- | --- |
| `sliceId`, `prefix` | Stable slice code; `prefix` is the `<slice>` of [Naming](../references/naming.md#table), at most 21 characters |
| `specPath` | Absolute path to the approved spec and its delivery package |
| `repoPath`, `baseSha` | The repository's main checkout (Herdr creates worktrees only from it) and the immutable starting commit |
| `processPaths` | Applicable instructions; commands for the full gate, the compliance suite and focused tests; commit and merge policy; the admission file with its dispatch notes |
| `roster` | `{"coders": 0}` (always; owner decision 2026-10-14) |
| `models` | `principal` and `reviewer`, each `harness model thinking_effort` |
| `responsible` | The orchestrator: its Herdr agent name, pane ID, workspace and session |
| `slice`, `worktreeRoot`, `runDir` | Slice branch and worktree, and the worktree root: omit them to take the Naming *Swarm slice* row and its location; a new contract that names another layout is rejected. `runDir` under `J/runs/`, outside the repository |
| `skillRoot`, `ponytailPath` | Absolute path of this `swarm/` directory (it holds `swarm.md` and `roles/`); resolved `ponytail` SKILL.md |

The scripts start both under their Naming agent names and pane titles: the Principal with `--kind codex -- --model gpt-6.1-sol -c 'model_reasoning_effort="high"' --dangerously-bypass-approvals-and-sandbox`, the reviewer with `--kind claude -- --model claude-opus-5-5 --effort high --dangerously-skip-permissions` ([Models](references/models.md)).

## Supervise and receive

- **Supervise:** keep the supervisor alive, answer escalations and lease requests, handle model incidents. Done on `SLICE_READY`, a genuine blocker or cancellation.
- **Receive:** the code integrates through the merge queue (Cycle, step 8); on the phase-3 `SLICE_READY`, verify the slice SHA and minimum evidence, then integrate the phase-3 delta as a documentation batch ([Integration](../integration/integration.md)) or return findings. Done when the hand-off is acknowledged.

## Success criteria

- The team matches the roster with explicit models and an independent reviewer.
- Every task maps to the plan, ran one cycle, and carries its minimum evidence and an approval of its exact SHA.
- The slice was refactored with `ponytail` on green, merged with current main, passed the compliance suite and the touched guards, has the reviewer's deep approval, and passed the full gate under the lease on its exact commit merged with current main; open findings are closed or escalated.
- The orchestrator receives branch, base and head SHAs, evidence and the open-findings list; no claim rests on Herdr state or agent prose.
