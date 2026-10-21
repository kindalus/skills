---
name: implement-with-swarm
description: Orchestrates implementation of one approved slice with a Herdr team (a Principal that plans, implements and integrates, and one reviewer from another model family) under the responsible agent, ending in a single-integrator handoff to main.
compatibility: Requires a Herdr-managed session (HERDR_ENV=1) with `herdr worktree`, Git worktrees, a shared local filesystem, and explicitly configured pi, claude or agy harnesses. The responsible agent must remain available to supervise the run.
---

# Implement with Swarm

One team implements one approved slice from the project's **delivery package**. Versioned scripts do the deterministic mechanics (bootstrap, event delivery, snapshots, gates); agents keep every scope, review, integration and recovery decision. Reading this skill launches nothing.

## Team

| Role | Count | Default triple | Does |
| --- | --- | --- | --- |
| Principal | exactly 1 | `pi openai-codex/gpt-6.1-sol medium` | plans, implements every task, integrates tasks into the slice branch, asks for the slice gate |
| Reviewer | exactly 1 | `claude claude-opus-5-5 high` | reviews tasks and the slice; always a different model family from the implementers |

**Always Principal and reviewer only** (owner decision 2026-10-14, no exceptions): there are no coders; the Principal implements every task in series. `roster.coders` is always 0. The responsible agent copies the triples into the launch contract explicitly (owner or project defaults win over these); the scripts reject a reviewer of the same family as any implementer. Sole exception, by owner decision: when the Claude reviewer exhausts its quota, `MODEL_REPLACE` may install the **reviewer quota fallback** `pi openai-codex/gpt-6.1-sol high` for task reviews, and the Claude reviewer re-reviews those tasks in the deep slice review before `SLICE_READY` ([Models](references/models.md)).

## Macro

1. **Plan.** The Principal writes the slice plan file on top of the delivery package: tasks in order (dependency, then risk), the scenarios and tests of each task, and write scope.
2. **All the slice's tests, then tasks.** By the project's process (Zafir IMPLEMENTATION 5.5): before any production code (except, when the seams are new, one commit with only their fail-closed contract skeleton so the tests compile), the Principal writes the tests of every scenario of the slice, runs them once and keeps the **slice RED log** (each test failing for its own reason; one that only fails to compile is fixed first), in one tests-only commit that every task branches from. When fixture mechanics keep tests from their target, one bounded test-plumbing commit may precede the battery, and a fact still unreachable is NON-CAUSAL in the RED log, with an omission mutant at its green step (Zafir IMPLEMENTATION 5.5). Then it assigns every task to itself, in series (while one waits for its verdict it may start the next independent one, never more than two open). Each task has its own task worktree and one grant.
3. **One cycle per task:** turn the task's tests green **one at a time** (or a small cohesive group), in the plan's order, with the smallest correct change each and a commit per green step; a purely mechanical change (M1: rename, argument propagated to consumers) may be done in one batch. Then send `REVIEW_REQUEST` to the reviewer (a FIFO queue); fix on each verdict until approved. A fact without its own causal RED (already green in the slice RED, green without new code, done in a batch) gets one omission mutant, restored and hash-verified.
4. **Integrate.** With every task approved, the Principal merges them into the slice branch (`merge --no-ff`, never rebase) and runs the focused tests. For the full gate it sends `LEASE_REQUEST` with the exact, clean slice head SHA; the **responsible agent** runs the full gate on that SHA under the exclusive host lease and returns the result. The Principal never runs the gate. Then it sends the slice to the reviewer and fixes until convergence.
5. **Hand off.** After green and the deep slice review's approval, one **documentation-only commit** (Zafir IMPLEMENTATION 5.7, phase 3): final spec and its amendments log; in the register, only the slice's row and notes; in each per-slice assessment record (for example a privacy impact assessment), only the slice's entry; in a compliance matrix, only notes, with no promotion or reclassification; generated files and pinned hashes only through the project's generator. No new gate (the code does not change; the integration gate covers the final tree); the reviewer gives that delta a short review. Then `SLICE_READY`; the responsible agent is the single integrator into main. These phase-3 paths are pre-authorised, without asking the responsible agent, as long as they stay within this list.

## Rules

- **Minimum evidence is a closed list.** Slice RED log (all the slice's tests, before production code), and per task: the task's tests green in the order run, and the omission mutants for facts without their own causal RED, with verified restoration. Slice: the full gate green on the exact commit, with protected host resources checked before and after. Nothing else is mandatory: no per-step hash-bound ledgers, prewrite annexes, per-stage resource tuples, paired restore runs or recorder scripts.
- **Review scope:** code correctness, test meaning and minimum evidence. Process deviations are notes, never blockers unless minimum evidence is missing. Task reviews are short; the slice review is deep.
- **Three review rounds** per task and per slice, then escalate with the open findings.
- **Escalate only** scope, product, legal or compliance rules, security, migrations, guard weakening and models to the responsible agent (and the owner where the project requires). The Principal decides everything else, records it in the open-findings list and continues: record-and-continue, never stop-on-first.
- **Autonomous tests:** every test passes inside the project's full gate alone: no swarm-only environment variables, machine paths, or leaked database roles or databases.
- **Host:** focused runs go in parallel without a lease, on resources the agent owns. The full gate, browser runs and fixed ports need the exclusive lease.
- **Worktrees are Herdr workspaces:** slice and task worktrees come from `herdr worktree create`, review checkouts are opened with `herdr worktree open`, all through `swarmctl`; the team runs in the slice and task workspaces, never in the responsible agent's. **No pane without an agent:** `swarmctl` waits for each new pane to be an available shell before `agent start`, and closes the idle shells nobody uses (a Principal task's workspace, a review workspace after its verdict). Removal is `herdr worktree remove`, after acceptance and an authorized cleanup; never `workspace close --group` ([Execution](references/execution.md#worktrees-and-integration)).
- **Merge, never rebase:** phase SHAs are evidence; each conflict resolution is recorded (file, side, why).
- **Guards only get stricter**; a looser guard is an escalation.
- **Model incidents** go through `MODEL_ERROR` and `MODEL_REPLACE`; nobody substitutes a model or shrinks the team.
- **State lives in files** (plan, `state.json`, reports). The Principal may ask for a clean restart between phases; nothing forces one.
- **Direct-execution fallback:** when the swarm stalls on mechanical work, the responsible agent may do it itself, still sending it to the reviewer.
- **Process frozen at start:** the cards and the process are read at startup. A later change to the project's process applies only to slices whose implementation starts after it (Zafir SKILL.md *Process version*); a slice in progress finishes with the cycle it started with and records the transition in its spec's amendments log.
- No push, team edits on main, force-push, credential changes, destructive cleanup or extra agents. `SLICE_READY` means ready to integrate, not merged.

## Authority

The slice spec, repository instructions and development process stay authoritative; discover their commands instead of assuming them. This skill waives no approval or commit policy; settle conflicts **before dispatch**.

## Reading

Resolve paths from this skill's directory and pass absolute paths in every BOOT. Startup reading is the role card plus the launch contract; references load on demand.

| Reader | At startup | On demand |
| --- | --- | --- |
| Responsible agent | this file, [Responsible card](roles/responsible.md), `herdr` skill | [Automation](references/automation.md), [Execution](references/execution.md), [Models](references/models.md), [Threat model](references/threat-model.md) |
| Principal | [Principal card](roles/principal.md), `launch.json`, `herdr` skill, `ponytail` | Execution, Automation, Models |
| Coder | Only for runs launched before 2.4.0: [Coder card](roles/coder.md), `launch.json`, `ponytail` | Execution |
| Reviewer | [Reviewer card](roles/reviewer.md), `launch.json` | Execution |

A missing required skill is reported, never silently substituted.

## Launch contract

| Input | Requirement |
| --- | --- |
| `sliceId`, `prefix` | Stable slice code; Herdr prefix of at most 21 characters |
| `specPath` | Absolute path to the approved spec and its delivery package |
| `repoPath`, `baseSha` | The repository's main checkout (Herdr creates worktrees only from it) and the immutable starting commit |
| `processPaths` | Applicable instructions; commands for the full gate and focused tests; commit and merge policy |
| `roster` | `{"coders": 0}` (always; owner decision 2026-10-14) |
| `models` | `principal` and `reviewer`, each `harness model thinking_effort` |
| `responsible` | Live Herdr agent name, pane ID, workspace and session |
| `slice`, `worktreeRoot`, `runDir` | Slice branch and worktree; absolute user-owned locations outside the main checkout; `runDir` outside all worktrees |
| `skillRoot`, `ponytailPath` | Resolved absolute paths |

The reviewer starts as `herdr agent start <prefix>-reviewer --kind claude --pane <id> -- --model claude-opus-5-5 --effort high --dangerously-skip-permissions` ([Models](references/models.md)).

## Procedure

1. **Preflight:** delivery package, contract, `swarmctl doctor`, `bootstrap responsible --dry-run`. Done when the dry run is clean.
2. **Bootstrap:** `bootstrap responsible` creates the slice worktree's Herdr workspace and starts the Principal in its root pane; after its `AGENT_READY` and the responsible agent's `RESUME`, `bootstrap principal` starts the reviewer. Done on a validated `SWARM_READY`.
3. **Supervise:** keep the supervisor alive, answer escalations and lease requests, handle model incidents. Done on `SLICE_READY`, a genuine blocker or cancellation.
4. **Receive:** verify the slice SHA and minimum evidence, integrate into main through the project's process, or return findings. Done when the handoff is acknowledged.

## Success criteria

- The team matches the roster with explicit models and an independent reviewer.
- Every task maps to the plan, ran one cycle, and carries its minimum evidence and an approval of its exact SHA.
- The slice passes the full gate on its exact commit under the lease and has the reviewer's approval; open findings are closed or escalated.
- The responsible agent receives branch, base and head SHAs, evidence and the open-findings list; no claim rests on Herdr state or agent prose.
