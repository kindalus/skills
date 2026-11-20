---
name: implement-with-subagents
description: Takes one Zafir slice to ready-to-integrate from a single Claude Code or Codex session that plans, delegates the work to cheaper subagents and reviews with a clean-context subagent; prepares the slice first (5.1–5.4) when its phase 1 is not closed. Use when told to implement or prepare a slice with subagents, with or without an orchestrator.
compatibility: Claude Code or Codex only, with their native subagents. Git worktrees; the project supplies its host rules. Herdr and an orchestrator are optional.
---

# Implement with subagents

One session (the **lead**) takes one slice through Zafir 5.5–5.7. The lead plans and decides; subagents write the code and the tests; a clean-context subagent reviews. The lead hands the finished slice branch to whoever integrates it into main.

The lead owns the outcome. How it plans, how it splits the work, which subagents it starts and with which models are its choices.

## The requester

The **requester** is whoever started the lead, and the lead's only channel for questions, approvals and host requests:

- **Orchestrated:** an orchestrator started the lead with a brief. The brief names the base commit, the admission notes, the host rules and the channel; the orchestrator integrates.
- **Standalone:** the user started the lead directly, with or without Herdr. The channel is this session: ask the user, with the options and a recommendation, and wait. The user decides what an orchestrator would and what the owner would, and integrates or tells the lead how.

The rest of this file says *requester* and means either.

## Start

1. Read this file, the project's instructions (`AGENTS.md` or `CLAUDE.md`) and the process they cite, and the Zafir `IMPLEMENTATION.md` (5.5 to 5.7). Where the brief or the user's prompt and the project's instructions disagree, ask the requester before acting.
2. **Is phase 1 closed?** It is when the project's register shows the slice's 5.4 approval and the phase 1 commit is on main. If not, prepare the slice first by [Preparation](PREPARATION.md), then come back here. Done when the slice is implementable on the register, or the requester says to implement it as it stands.
3. **Worktree.** Use the worktree the requester names; otherwise create one on `slice/<id>` from current main. Subagents work in that worktree or in task worktrees the lead creates and removes. No edits on the main checkout.
4. **Where worktrees live.** Every worktree of the slice sits in `<repo>/.worktrees/`, `<repo>` being the main checkout root, with the same names and branches a swarm uses (`<slice>` is the lowercase slice ID, `s567`; `<task>` the task's short name, `t01`):

   | Worktree | Path | Branch |
   | --- | --- | --- |
   | Slice | `.worktrees/<slice>` | `slice/<slice>` |
   | Task | `.worktrees/<slice>-<task>` | `task/<slice>/<task>` |
   | Review checkout | `.worktrees/<slice>-review-<task>-r<n>` | detached |
   | Preparation | `.worktrees/<slice>-preparation` | `prep/<slice>` |
   | Setup window | `.worktrees/<slice>-setup` | detached |

   `.worktrees/` stays out of Git through `<repo>/.git/info/exclude`, never `.gitignore`. A subagent works in the worktree the lead gives it, never in an isolated one its tool would create elsewhere. Done when `git worktree list` shows no worktree of the slice outside `<repo>/.worktrees/`.
5. **Under Herdr.** Create branch worktrees with `herdr worktree create --cwd <repo> --branch <branch> --path <repo>/.worktrees/<name>`; for a detached one, `git -C <repo> worktree add --detach <path> <sha>` then `herdr worktree open`. The slice's workspace label and tab are `<slice>`; the lead agent is `<slice>-lead`, with pane title `<slice> · lead`; a preparation workspace is `<slice> · preparation`. Without Herdr, use `git worktree add` with the same paths and branches.

## Fixed points

These hold whatever the lead decides:

- **RED first.** All the slice's tests are written before production code, and the RED log shows each one failing for its own cause (Zafir 5.5, stage 2). A wrong RED is fixed before any production code.
- **One green step at a time.** Production code turns the tests green in plan order, with a commit per green step.
- **Omissions.** Every fact without its own causal RED gets an omission mutant, applied one at a time, run, and restored by hash.
- **Review.** Each task, and then the whole slice, is reviewed by a subagent that starts with a clean context and gets only the spec, the plan and the diff. It is never the subagent that wrote the code. The lead fixes the findings and runs the review again, for at most three rounds, then escalates.
- **Ponytail.** A final pass for the smallest correct change, measured against the ledger in the spec.
- **Evidence is a summary.** Versioned evidence is one short summary per proof: the command, the SHA, the counts and the sha256 of the raw logs. Raw logs stay out of the repository.
- **Host.** The host may be shared with other work. Every run that needs a database, containers or the whole test suite follows the project's host rules: its lock, its wrappers and its exclusions. Browser runs, fixed ports, the full gate and any exclusive window are **host requests** to the requester, unless the project's instructions let the lead run them; the lead or a subagent never starts one otherwise. Subagents run tests in parallel only when they touch no shared resource. A **hold** from the requester stops new heavy runs until the requester lifts it.
- **Escalate, then stop.** The lead stops and asks the requester before any of these: product or legal rules, Givens or Thens that change, guards that would get weaker, security or ACL, migration content beyond the spec, or a scope change.
- **Size is a diagnostic until the end.** Line ceilings and estimates never stop the work while coding: the lead measures as it goes and keeps going. The size is checked once, measured, in the final ponytail pass (step 4); if it is still above the ceiling then, the lead sends the requester one request with the measurement and its causes, and nothing earlier.
- **No integration by default.** The lead never merges into main, pushes, rebases or force-pushes unless the requester asks for that integration by name. Handing off means the slice is ready to integrate, not merged.

## Steps

1. **Plan.** Write the plan from the delivery package: the tasks in dependency then risk order, the tests and scenarios of each, the write scope and which subagent does what. Done when every test maps to a scenario and every scenario to a task.
2. **RED.** Delegate the slice's tests to subagents, task by task, and collect the RED log. Done when every test fails for its own cause and nothing fails for a build, setup or import error.
3. **Green.** Delegate production code task by task. For each task: green steps, omissions, review by a clean subagent, fixes. Merge each approved task into the slice branch with `merge --no-ff`. Done when every task is approved and merged and the slice's focused tests are green.
4. **Slice review.** One deep review of the whole slice by a clean subagent, then the fixes, then the ponytail pass. Done when the review approves and the measured size is within the ledger, or the requester has answered the single size request.
5. **Phase 3.** The documentation-only commit (Zafir 5.7): final spec and amendments log, the slice's own row and notes in the register, and the evidence summaries.
6. **Handoff.** Get the full gate on the exact, clean slice SHA: as a host request, or run it yourself where the project's instructions allow. When it is green, report the slice ready to integrate, with the slice SHA, the tree, the gate result and the paths and sha256 of the RED log and the omission results. Remove the task worktrees and keep the slice worktree until the slice is in main.

## Talking to the requester

State the request in the first line, with paths and sha256 for every file you cite. While a question is open, keep working on whatever does not depend on the answer.

With the `orchestrate-zafir-implementation` courier (named in the brief), the channel is the `orch` space on the slice's own thread: a `REQUEST` for each question and for each host request, with a subject that says which it is; a `DELIVERY` for results and for the handoff. Record the receipt of each message before acting on it.
