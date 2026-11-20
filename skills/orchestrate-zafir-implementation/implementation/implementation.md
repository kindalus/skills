# Implementation

The orchestrator does not implement. It launches one **implementer** per admitted slice, serves its host requests and questions, and integrates what it hands off. The implementer is a **lead**: one agent session that takes the slice through Zafir 5.5–5.7 with an implementation skill. The default is `implement-with-subagents`; the owner or the admission may name another skill that honours the same contract.

## Contract

Any implementation skill works if its lead:

- works only in the slice's worktrees, at their [Naming](../references/naming.md#table) paths;
- talks to you only through the orchestration space, on the slice's own thread ([Mail](../references/operations.md#mail)), with a `PEDIDO` per question or host request and an `ENTREGA` per result;
- runs heavy work by the project's host rules and asks you for browser runs, fixed ports, exclusive windows and the full gate as **host requests**;
- obeys a **hold** you send until you lift it;
- escalates the owner's matters (product or legal rules, changed Givens or Thens, weaker guards, security or ACL, migration content beyond the spec, scope) and stops;
- treats line ceilings as diagnostics until its final ponytail pass, then sends at most one size request (owner's standing order);
- hands off a slice **ready to integrate**: clean slice SHA, tree, review approvals, gate result, RED log and omission results, with paths and sha256, and never merges into main.

## Launch

As soon as the slice is implementable and admitted:

1. **Worktree and workspace.** From the repo's own workspace, create the slice worktree with Herdr so it is grouped under the repo: `herdr worktree create --cwd <repo> --branch slice/<slice> --base <main SHA> --path <repo>/.worktrees/<slice> --label <slice> --no-focus` (or `herdr worktree open --workspace <repo workspace> --path <worktree> --label <slice>` for an existing one). Never `herdr workspace create --cwd <worktree>`: that workspace floats outside the repo. Label the tab `<slice>`.
2. **Lead.** Start it in the workspace's root pane, named and titled per [Naming](../references/naming.md#table) (`<slice>-lead`, `<slice> · lead`), on the harness and model the owner or the project sets; add it to the orchestration space with its pane.
3. **Brief.** Write `J/briefs/impl-<slice>.md`: the implementation skill's path, the spec path, the base SHA and worktree, the admission verdict with its path and sha256 (its notes bind the lead), the owner answers and your decisions that bind it, the project's host rules, the size rule above, the channel, and what the first `ENTREGA` must contain (HEAD, plan, estimate). For a lead taking over work already in progress, add the handover note's path and sha256 and say it is the starting point. Prompt the lead with the brief's path and sha256.

Done when the lead's first `ENTREGA` confirms the HEAD and the plan, and the pipeline shows it.

## Serve

- **Questions:** decide what is yours, carry the owner's as owner requests, answer by mail. A question about size before the final ponytail is answered with the size rule.
- **Host requests:** grant, schedule and run them under the host lease, one at a time; send the result with its log paths and sha256. Grant light focused runs to the lead itself, with explicit IO limits, when that is faster than a window.
- **Holds:** before an exclusive window, send each lead a hold on its thread and wait for its receipt; lift it with an explicit end-of-hold message when the window closes. A window that sends holds also sends their lift, even when it fails.
- **Gate request:** a lead's request for the full gate, after its deep review, is its integration through the merge queue ([Integration](../integration/integration.md)).

## Close

After the slice is accepted on main: tell the lead, let it remove its task and review worktrees, quit its harness, remove it from the space, and remove the slice worktree by [Cleanup](../integration/integration.md#cleanup). Log it.

## Handover

To move a slice to a new lead (another skill, harness or model): ask the current one to stop at a clean point and write a handover note in `J/retomas/retoma-<slice>.md` (branch and SHA, done and pending tasks, the task in progress and its exact state, binding decisions, evidence, worktrees, pending host requests, risks); then close it without removing its worktrees and launch the new lead with the note in its brief.
