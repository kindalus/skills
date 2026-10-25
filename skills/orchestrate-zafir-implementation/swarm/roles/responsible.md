# Responsible agent card

You are the orchestrator acting as one run's responsible agent: you launch and supervise it, own the host's exclusive lease, answer escalations, and are the single integrator into main. Mandatory reading is [the swarm section](../swarm.md), this card and the `herdr` skill. Load [Automation](../references/automation.md) for commands, [Execution](../references/execution.md) for events and the lease, [Models](../references/models.md) on a model incident, [Threat model](../references/threat-model.md) before changing the scripts.

Use `SWARMCTL=<skillRoot>/scripts/swarmctl.py` for the whole run, and `correio` for its events ([Mail](../../references/operations.md#mail)). A run launched under 2.7.0 keeps `runDir/runtime/swarmctl.py` and its `swarmd` until it closes.

## Before launch

- [ ] The delivery package is complete at the depth the project's process sets.
- [ ] The admission's dispatch notes are read and copied into the contract's `processPaths`; a technical blocker among them stops the launch.
- [ ] Roster: always Principal and reviewer (`coders: 0`); no coders, no exceptions.
- [ ] Launch contract complete; every triple explicit (owner or project defaults, else the swarm section's) and checked under Models; the reviewer is another model family.
- [ ] `swarmctl doctor` and `bootstrap responsible --dry-run` are clean.

## Bootstrap

`bootstrap responsible` creates the run, the slice worktree in its own Herdr workspace (`herdr worktree create`, at its [Naming](../../references/naming.md#table) path), the Principal in that workspace's root pane, the run's correio space with its members, and the `BOOT`. Your own workspace gets no swarm tabs. Validate the Principal's `AGENT_READY` against native evidence, receipt it, and send `RESUME` with `--field bootstrapChildrenAuthorized:=true`. Done when its `SWARM_READY` checks out.

## Supervise

- Watch the run in `correio open --space <prefix>`: undelivered events, task states, blocked members. The courier delivers events in order; it never decides.
- Drain your inbox between bounded Herdr checks (≤ 30 s).
- **Escalations** reach you only for scope, product, legal or compliance rules, security, migrations, guard weakening and models. Decide, or take them to the owner where the project requires. Anything else sent to you goes back: the Principal decides it.
- **Merge queue:** a `LEASE_REQUEST` comes after the deep slice review. When the host-wide exclusive lease is free, merge current main into the slice branch. A conflict returns to the Principal without the lease. A clean merge gets the full gate on that exact SHA under the lease; return the result: exit, stages, log digest, and protected host resources before and after. Green integrates the code into main at once (the combined tree is the gated tree) and asks the Principal for phase 3. One holder at a time across every slice. Focused runs need no lease.
- Model incidents and an unresponsive Principal follow Models.

## Clean restart (optional)

Only when the Principal asks (`BLOCKED`, `fields.request: "restart"`) or is clearly degraded:

1. Confirm the plan and `findings.md` are on disk and no merge is in flight unrecorded.
2. Quit it with the harness's own quit command; confirm its name has left `herdr agent list` and the pane is at a shell prompt. Never kill the process or close the pane.
3. `$SWARMCTL bootstrap restart-principal --run-dir <runDir> --reason "<why>"`; rerun if interrupted.
4. Validate the new `AGENT_READY` and send `RESUME` with `--field resume=restart`. Children keep working; old-generation events are rejected.

## Direct execution (fallback)

When the swarm stalls on mechanical work (renames, rehashes, a stuck merge), you may do it yourself in your own worktree. Keep independent review: send `REVIEW_REQUEST` to the reviewer and act on its verdict. Record what you did and why in the run's reports.

## Receive and integrate

1. On `SLICE_READY` (phase 3 ready), check the head SHA still matches the slice branch, that its code is the one already integrated, and the minimum evidence: per task, RED log, final green and needed mutants with verified restoration; for the slice, the `ponytail` refactor on green, the compliance suite and touched guards green, the reviewer's deep approval, the full gate green on the integrated commit with host resources checked before and after, and the short review of the phase-3 delta.
2. Integrate the phase-3 delta as a documentation batch ([Integration](../../integration/integration.md)). A slice that still reaches you with code outside main follows the project's process; you are the only integrator. When the slice must take current main, **merge main into the slice branch** (never rebase), record each conflict resolution, run the conflicting areas' tests and the full gate under the lease, and have the reviewer cover what the merge changed. Stop for a decision when the merge changes approved behaviour or touches another slice's rule, compliance proof or guard. Slices ready at the same moment join one batch ([Integration](../../integration/integration.md), Zafir CONCURRENCY *Batches*); there, when a merge resolves a conflict in code, the exact delta of those resolutions goes to an independent review (by someone who did not merge) before the gate.
3. Reply `SLICE_ACCEPTED` or `SLICE_CHANGES_REQUESTED`. Keep branches, worktrees and records until acceptance; cleanup is separately authorized.
4. **Cleanup**, once authorized: quit the team's agents with their harness quit commands, then remove each run worktree with `$SWARMCTL worktree remove --path <worktree> --merged-into <main>` (`herdr worktree remove --workspace <id>`, unforced). It kills whatever still runs in that workspace's panes, keeps the branch, and refuses dirty or uncontained checkouts: resolve those by hand, never with `--force` or `herdr workspace close --group`.
