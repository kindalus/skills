---
name: orchestrate-zafir-implementation
description: Orchestrates Zafir slices from one Herdr pane — dedicated preparers and consultants take each slice through 5.1–5.4, swarms implement it, and the orchestrator integrates batches into main. Use when the user asks to prepare, implement or integrate slices, or to run the agent team on bugs.
compatibility: Requires a Herdr session (HERDR_ENV=1), jq, the claude, codex, pi and agy CLIs, and the ponytail, graft and grilling skills; scripts/preflight.sh checks them.
---

# Orchestrate Zafir implementation

You are the **orchestrator**: the single coordinator and integrator. Preparers take slices through Zafir 5.1–5.4, consultants advise them, swarms implement 5.5–5.7, bug executors fix bugs, and you integrate every `SLICE_READY` into main. The Zafir development process (`zafir-development-process`) stays authoritative: read its SKILL.md and the step files it links before acting on a step. This skill adds the team, the hand-offs and your authority, never a second copy of the procedure. The project's own instructions (`AGENTS.md` and its process docs) add their gates on top.

## Sections

| Reader | Reads |
| --- | --- |
| Orchestrator | this file, then each section when its branch fires |
| Preparer | [Preparation](preparation/preparer.md) |
| Consultant | [Consultants](consultants/consultants.md#mandate) (the mandate only) |
| Swarm (Principal, reviewer) | [Swarm](swarm/swarm.md) and its role cards |
| Orchestrator integrating | [Integration](integration/integration.md) |
| Anyone driving Herdr or writing shell | [Operations](references/operations.md) |
| Anyone creating or titling a worktree, branch, agent, pane, workspace or tab | [Naming](references/naming.md) |

Resolve every path from this skill's directory and pass absolute paths in every brief.

## Start

1. **Preflight.** Run `scripts/preflight.sh --project <repo>`. It fails closed when the session is not Herdr, `jq` is missing, any of `claude`, `codex`, `pi`, `agy` is missing, the `ponytail`, `graft` or `grilling` skill is missing, or the project uses containers or worktrees without `podman`/`docker` and `git worktree`; it also adds the [Naming](references/naming.md#location) exclude for `.worktrees/` when missing. On failure, report the missing items and stop: nothing is launched.
2. **Register.** Give this pane the orchestrator's agent name, pane title and tab from [Naming](references/naming.md#table) (`herdr agent rename "$HERDR_PANE_ID"`, `herdr pane rename`, `herdr tab rename`). If another live orchestrator exists, stop and ask.
3. **Job directory.** `J=${XDG_STATE_HOME:-$HOME/.local/state}/orchestrate-zafir-implementation/<repo-key>/`, mode `0700`, outside every worktree. It holds the [decision log](#decision-log), the [owner requests](#owner-requests), the [consultant queue](consultants/consultants.md#queue), `preparers.txt`, briefs, admissions, gate logs and the swarms' `runs/`. Reuse it on resume.
4. **Environment.** Read `herdr agent list` and create only the missing tabs and agents, named and titled per [Naming](references/naming.md#table): the consultants at reasoning high ([Roster](consultants/consultants.md#roster)), the bug executors, codex in yolo mode ([Bugs](#bugs)), and one workspace per preparer, opened on demand ([Preparers](#preparers)). Swarms run in their own Herdr workspaces, created by the swarm bootstrap.

Done when preflight passes, the name is registered, `J` exists and every tab holds its live agents.

## Authority

**You decide**, record in the decision log and continue:

- New IDs (splits, bugs, nominal owners, parts, request numbers). Compute the next free ID by script from the register, the branches and `J`, never from memory, and write it in the log entry.
- Every technical and operational question the owner list below does not name.

**The owner decides.** Send an [owner request](#owner-requests) with options and a recommendation, and wait:

- push outside the batch flow; new legal or fiscal matter; security; guards; protected data or resources; privileges; migration content; 5.4 approvals.
- A guard amendment is yours only when it does not weaken the guard. Any widening goes to 5.4 or to the owner.

Every message to the owner follows the Zafir rule *Talking to the user*.

### Decision log

`J/decisions.md`, append-only, one line per event: `- <YYYY-MM-DD HH:MMZ>: <slice or ID>: <what happened or was decided>; <evidence: SHA, path and sha256>`. It records decisions, grants, launches, verdicts, owner answers and lessons. Rebuild your state from it after a compaction; read it with `rg -n` and `tail`, never whole.

### Owner requests

One file per request, `J/requests/REQUEST-<n>.md`, `<n>` the next free number. It states the slice and the question, the options with their consequences, your recommendation, and, for a 5.4 approval, the paths and sha256 of the spec, the approval deck and every assessment the project requires. Send the owner the path and its sha256. Record the owner's answer as `ANSWER <n>` in the decision log and apply it.

## Capacity and readiness

- **No cap** on slices in preparation or in swarm. This is the owner's instruction over Zafir CONCURRENCY *Cap* (Zafir precedence rule 1); record it once in the project's concurrency decision. Only behaviour dependencies and envelope collisions limit entry, and you manage minimal collisions yourself (order, a shared owner, a serial pair).
- Launch a swarm as soon as its slice is implementable and admitted ([Swarm launch](swarm/swarm.md#launch)).
- Integrate through the **merge queue**: a slice's `LEASE_REQUEST`, after its deep review, gets main merged in, the whole gate, and integration at once on green; its phase-3 `SLICE_READY` follows as a documentation batch ([Integration](integration/integration.md)).

### Admission

An approved slice (phase 1 on main, `implementable` on the authoritative register) gets an **admission** before its swarm: a read-only check on a detached checkout of current main at its [Naming](references/naming.md#table) path. Following Zafir CONCURRENCY *Admission* and PREPARATION *Just-in-time and freshness*, it covers:

1. the preconditions and consumed contracts, against the real signatures (graft);
2. freshness: the diff of main since approval, against the impact map and envelope;
3. collisions and serial rules, against every slice in swarm and every open batch;
4. the guards and map points the slice touches.

It ends in a verdict, `ADMIT`, `ADMIT WITH NOTES` or `RETURN TO 5.4`, with technical blockers separated from capacity notes, in `J/admission-<slice>.md`. Its notes are the swarm's binding dispatch notes ([Launch](swarm/swarm.md#launch)). Done when the verdict file exists and its result is in the log.

### Pipeline

Keep one table of every slice and bug, and show it at each transition:

| Slice | Phase | Work | Agents | Herdr state | Last activity |
| --- | --- | --- | --- | --- | --- |
| S430 | 5.2 | grill and decisions | s430-preparer, consultant-claude | working | 14:18, answering Q3 |

The Herdr state comes from `herdr agent list`; the last activity is your one-line summary of a bounded `agent read`.

## Preparers

0. **Eligible.** Before opening one, read the slice's register row (`specifiable` and its reason, `dependsOn`) and the dependencies the project's plan sets for its family or phase. A slice deferred by just-in-time, or whose plan dependency is not yet integrated, gets no preparer; record its trigger in the pipeline. A slice without approved scope goes back to Zafir Steps 1–4 as an owner request, not to a preparer.
1. **Open.** One new, dedicated preparer per slice, named and titled per [Naming](references/naming.md#table), in its own workspace. Create the worktree through Herdr, which opens that workspace: `herdr worktree create --cwd <repo> --branch <branch> --base <main SHA> --path <worktree> --label "<workspace label>" --no-focus`; label its tab, then start the preparer in the workspace's root pane, `herdr agent start <name> --kind pi --pane <id> -- --model openai-codex/gpt-6.1-sol --thinking high`, and set its pane title.
2. **Brief.** Write `J/briefs/prep-<slice>.md`: slice ID, spec path, main SHA, the preparer's worktree path, branch and workspace label from Naming, the decisions and owner answers that bind it, and the path of [the preparer card](preparation/preparer.md). Prompt the preparer with the brief's path and sha256. Add its agent name to `J/preparers.txt`.
3. **Serve** its consultant requests from the [queue](consultants/consultants.md#queue), and carry its owner questions as owner requests.
4. **Close** it when 5.4 is approved and phase 1 is delivered: quit its harness, remove it from `preparers.txt`, log it. Its worktree and workspace stay until phase 1 is on main ([Cleanup](integration/integration.md)).

Just-in-time: a slice that depends on one still in swarm opens its preparer only when that dependency reaches `SLICE_READY` (PREPARATION *Just-in-time and freshness*). Record the trigger in the pipeline.

## Bugs

- Executors, named per [Naming](references/naming.md#table): `herdr agent start <name> --kind codex --pane <id> -- --model gpt-6.1-sol -c 'model_reasoning_effort="high"' --dangerously-bypass-approvals-and-sandbox`.
- Each bug gets an ID (the next free one) and a brief, and follows Zafir SHORT-PATHS *Bug fix workflow* on its own branch and worktree; the executor's pane title names the bug ([Naming](references/naming.md#table)).
- Its review is independent and from a family other than codex's: a Claude or agy consultant grant from the queue.
- An executor stops before a fix that needs a new decision and brings options; you decide, or send an owner request.
- A pre-existing defect found in a slice is recorded as a separate bug; the slice preserves the behaviour.
- The fix joins the next batch.

## Supervision

- **Swarm events.** Each swarm's supervisor (`swarmd`) delivers its events to your inbox. Drain them with `<runDir>/runtime/swarmctl.py event pending --run-dir <runDir> --recipient orchestrator`, and answer escalations, `LEASE_REQUEST`, `MODEL_ERROR` and `SLICE_READY` as the [responsible card](swarm/roles/responsible.md) sets. Restart a stale supervisor (`supervision/status.json`) from its runtime.
- **Blocked agents.** Answer a `blocked` agent at once.
- **Stalls.** A `working` agent that stops progressing, or whose last lines show a network or model error, gets the [stall procedure](references/operations.md#stalls).
- **Context.** To compact an agent, or yourself, follow [Context](references/operations.md#context).

Done for a run when every slice is integrated, returned with its blocker, or waiting on an owner request, and the pipeline says which.
