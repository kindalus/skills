# Changelog

Versions up to 2.4.2 were released as the `implement-with-swarm` skill.

## 2.5.0 — 2026-10-24

The swarm moves into `orchestrate-zafir-implementation` as its `swarm/` section; the orchestrator is the responsible agent.

### Changed

- **Codex harness:** `scripts/swarmcore.py` accepts `codex` (efforts `minimal`, `low`, `medium`, `high`, `xhigh`), starts it with `--model <model> -c model_reasoning_effort="<effort>" --dangerously-bypass-approvals-and-sandbox`, and maps it to the OpenAI family.
- **Defaults:** the Principal is `codex gpt-6.1-sol high` in yolo mode (was `pi openai-codex/gpt-6.1-sol medium`); the reviewer quota fallback is `codex gpt-6.1-sol high` (was `pi openai-codex/gpt-6.1-sol high`). `swarm.md`, `references/models.md`, `roles/reviewer.md` and the tests say so.
- **Cycle:** with every test green, the Principal refactors with `ponytail`; before the gate it merges current main (never rebase) and runs the full compliance suite and the touched guards' tests (`swarm.md`, Principal, responsible and reviewer cards).
- **Launch:** only after the admission's dispatch notes are read; they are binding.
- **Paths:** `skillRoot` is the `swarm/` directory and must hold `swarm.md`; run directories live under the orchestrator's job directory.

### Compatibility

- Automation version 2.5.0. Runs launched by `implement-with-swarm` keep their run-pinned runtime; a `MODEL_REPLACE` with the old `pi` fallback triple is rejected by this runtime.

## 2.4.2 — 2026-10-21

### Changed

- **Project-neutral wording:** SKILL.md, the Principal and responsible cards and `references/execution.md` name generic artefacts instead of one project's: the spec's amendments log, per-slice assessment records, the project's generator, Zafir M1–M3 and project classes (Zafir IMPLEMENTATION *Mechanical amendment classes*), Zafir SKILL.md *Process version* and Zafir CONCURRENCY *Batches*. Escalation and serial classes say «rule» and «compliance» where they said «fiscal» and «legal proof». Behaviour is unchanged.

## 2.4.1 — 2026-10-14

Aligns the skill with the project's process and with practice since 2.4.0 (owner-approved alignment of 2026-10-14 between Zafir, Decision 032 in Uwassi and this skill).

### Changed

- **Gate by the responsible agent:** SKILL.md macro step 4 and `references/execution.md` (Host and lease) now say what the Principal card §6.3 and Decision 032 §11 already said: the Principal sends `LEASE_REQUEST` with the exact, clean SHA; the responsible agent runs the full gate under the exclusive lease and returns the result.
- **No coders in the normative text:** `references/execution.md` (layout, homes, plan, grant and event examples, event table, worktrees), `roles/principal.md` (§1, §3, §5) and `roles/reviewer.md` describe only the Principal and the reviewer. `TASK_INTEGRATED` leaves the event table. Runs launched before 2.4.0 keep a short historical note.
- **Phase 3 before `SLICE_READY`:** after the deep slice review's approval, one documentation-only commit (Zafir IMPLEMENTATION 5.7, phase 3): final spec and §21, register row and notes, the slice's LIA entry, matrix notes only (no promotion or reclassification), S390 only through the official generator. No new gate; a short review of that delta. These paths are pre-authorised for phase 3 (SKILL.md macro step 5, Principal card §7).
- **Process frozen at start:** cards and process are read at startup; a later process change applies only to slices whose implementation starts after it; a slice in progress finishes with its cycle and records the transition in §21 (SKILL.md Rules, Principal card).
- **Pre-authorised classes:** a path outside the grant that fits entirely in CP1–CP8 (Decision 032 §10) or Zafir M1/M2 is edited without waiting for the responsible agent, recorded in the plan and §21, with the reviewer's written confirmation of the class; anything else still goes to the responsible agent first (Principal card, «Decide or escalate»).
- **Reviewer quota fallback** is now `pi openai-codex/gpt-6.1-sol high` (was `pi openai-codex/gpt-6-astra medium`): SKILL.md, `references/models.md`, `roles/reviewer.md`, `scripts/swarmcore.py` (`REVIEWER_QUOTA_FALLBACK`) and `scripts/test_swarmctl.py`.
- **Remaining coder text** in `references/automation.md`, `references/models.md` and `references/threat-model.md` is removed or marked «only for runs launched before 2.4.0»; `roles/coder.md` opens with a legacy line. `roles/responsible.md` («Lease and gate») says the responsible agent runs the full gate on the exact SHA and returns exit, stages, log digest and protected resources.
- Also: integration into main follows the project's process, which may be by batches with an independent review of the conflict-resolution delta before the gate (Decision 032 §12 in Uwassi; `roles/responsible.md`, `references/execution.md`); test plumbing before the RED and NON-CAUSAL facts point to Zafir IMPLEMENTATION 5.5 (SKILL.md macro step 2, Principal card §4).

### Compatibility

- Automation version 2.4.1. A `MODEL_REPLACE` with the reviewer fallback marker now accepts only the new triple; the old `gpt-6-astra medium` triple is rejected like any other same-family reviewer.
- Runs in progress keep their run-pinned runtime and its fallback triple.

## 2.4.0 — 2026-10-14

Implements the owner's decision of 2026-10-14: parallel coders were rarely used, so every team is the Principal and the reviewer only, with no exceptions.

### Changed

- **Team:** always one Principal and one reviewer; no coders. The Principal implements every task in series, with at most two open (one waiting for its verdict while the next independent one starts), and fixes its own `CHANGES_REQUESTED` on the same grant and worktree.
- **Default Principal triple:** `pi openai-codex/gpt-6.1-sol medium` (was `high`). The reviewer stays `claude claude-opus-5-5 high`. The launch contract never has a `coders` entry.
- SKILL.md (description, team table, macro step 2), `references/models.md`, `roles/principal.md` and `roles/responsible.md` say so; `roles/coder.md` stays only for runs launched before 2.4.0.

- **Slice cycle follows the project's process** (owner decision 2026-10-14; Zafir IMPLEMENTATION 5.5 now says the same): plan first; then all the slice's tests, run once into a slice RED log and committed alone before any production code; then each task turns its tests green one at a time with a commit per green step; M1 mechanical changes in one batch; omission mutants only for facts without their own causal RED. Supersedes the 2.0.0 per-task batch RED and the same-day wording «one scenario at a time». SKILL.md (macro steps 1–3, minimum evidence), the Principal card and the reviewer card say so.

- **Gate executor:** the responsible agent runs the slice's full gate under the exclusive lease on the exact SHA the Principal names, and returns the result; the Principal no longer runs it (as practised since S517).

### Compatibility

- Automation version 2.4.0: the scripts enforce the team. A launch contract given to `init`, `doctor` or `bootstrap responsible` is rejected when `roster.coders` is not 0 or `models` has a `coders` entry, with an error that cites the owner decision of 2026-10-14. A run's own `launch.json`, reloaded by every other command, is not checked again, so the coder machinery still reads it as before.
- Runs in progress keep their run-pinned runtime, launch contracts and teams; runs created by 2.3.0 or earlier, with or without coders, are unaffected.

## 2.3.0 — 2026-10-03

Fixes two faults seen in the real S463 bootstrap under 2.2.0, and implements the owner's request that no pane stays without an agent.

### Fixed

- **Start race:** `bootstrap responsible` ran `herdr agent start` right after `herdr worktree create`, while the new workspace's shell was still initializing, and Herdr answered `agent_pane_busy: agent target pane … is not an available shell`. Every `agent start` (Principal, reviewer and coders, restart) now waits until the pane is an available shell: no agent, the shell as sole foreground process (`herdr pane process-info`) and a drawn screen (`herdr pane get` revision), unchanged over 3 reads 0.2 s apart, with a 30 s timeout whose error names the pane and what still runs. The prompt text is never matched. A remaining `agent_pane_busy` is retried, 3 attempts in all, each after a fresh wait; this replaces the single 3 s retry for children.

### Changed

- **No empty panes:** `worktree task` closes the root shell of a coder task's workspace once the coder's pane is in, and closes the whole workspace of a Principal task (`herdr workspace close`, never `--group`; option A), since the Principal works from the slice workspace. A rerun keeps a Principal task closed; handing the task to a coder reopens it with `herdr worktree open`.
- When a coder moves on, Herdr closes the emptied workspace of its previous task; `state.json` clears that task's `workspaceId`.
- `worktree review` closes any earlier review workspace of the run left open and idle.
- Only idle shells are closed. A busy one is kept, listed in `keptPanes` with the reason, and its ID stays in the task's `shellPaneId` so the next rerun closes it.
- `state.json`: a task's `workspaceId` is null while its workspace is closed; `shellPaneId` marks a root shell awaiting its close.

### Added

- `swarmctl worktree close --path <checkout>`: plain workspace close for this run's task and review checkouts (never the slice) when every pane there is an idle shell; fails closed otherwise and clears the task's `workspaceId`. The reviewer card uses it after each verdict in place of a bare `herdr workspace close`.

### Compatibility

- Automation version 2.3.0: runs created by 2.2.0, such as S463's, keep their run-pinned runtime and its behaviour.

## 2.2.0 — 2026-10-03

Implements the owner's decision of 2026-10-03: inside Herdr, worktrees are created with Herdr's worktree feature so each swarm and worktree is managed as its own workspace.

### Changed

- **Slice worktree:** `bootstrap responsible` creates it with `herdr worktree create` (label `<prefix>`) and starts the Principal in that workspace's root pane. The reviewer and the `<prefix>-coders` tab live in the slice workspace; the responsible agent's workspace gets no swarm tabs.
- **Adoption and resume** reconcile with `herdr worktree list`; a clean existing checkout without a workspace is opened with `herdr worktree open`. An existing branch must already be at its base, since Herdr ignores `--base` for it.
- **State:** `state.json` records the slice `workspaceId`, each agent's `workspaceId` and each task's `worktree`, `branch` and `workspaceId`; the grant carries the task's `workspaceId`. `bootstrap.json` records the Principal's workspace.
- `repoPath` must be the main checkout (Herdr refuses to create worktrees from a linked one); `doctor` checks it and that `herdr worktree list` answers.

### Added

- `swarmctl worktree task`: task worktree via `herdr worktree create` from the slice head; a coder owner's pane moves beside the new workspace's root pane (`herdr pane move`), with the new pane ID recorded in `state.json` and `bootstrap.json`.
- `swarmctl worktree review`: Herdr has no detached checkout (`create` without `--branch` invents a `worktree/<name>` branch), so the review checkout stays `git worktree add --detach` at the exact candidate SHA, checked clean, then opened with `herdr worktree open`. The reviewer closes that workspace after its verdict; the checkout stays.
- `swarmctl worktree remove`: `herdr worktree remove --workspace <id>` for the responsible agent's authorized cleanup after acceptance. Never forced; keeps the branch; refuses checkouts outside the run, dirty ones, heads not contained in `--merged-into`, and workspaces where an agent still lives (Herdr kills their pane processes).

### Compatibility

- Automation version 2.2.0: runs created by 2.1.0 keep their run-pinned runtime and their tabs in the responsible agent's workspace.

## 2.1.0 — 2026-10-02

Implements the owner's decision of 2026-10-02 (explicit exception to the independent reviewer).

### Added

- **Reviewer quota fallback:** when the Claude reviewer (`claude claude-opus-5-5 high`) exhausts its weekly quota, `MODEL_REPLACE` may install `pi openai-codex/gpt-6-astra medium` as the reviewer. Only after a reviewer `MODEL_ERROR` classified `quota-exhausted`; never a launch triple. The run records the reduced independence (same OpenAI family as the implementers), the fallback reviews tasks only, and the Claude reviewer re-reviews those tasks in the deep slice review before `SLICE_READY`; if quota does not return, the responsible agent escalates to the owner.
- **`MODEL_REPLACE` validation:** the payload requires `role`, `configuration` and `incidentId`; a reviewer replacement of an implementer's family is rejected unless it is exactly the fallback triple with `payload.reviewerFallback` equal to `incidentId` and naming this run's reviewer quota `MODEL_ERROR`. A marker on any other configuration is rejected.

### Changed

- Automation version 2.1.0: runs created by 2.0.0 keep their run-pinned runtime.

## 2.0.0 — 2026-10-02 (breaking)

Implements the owner's swarm macro of 2026-10-02.

### Changed

- **Team:** always one Principal, exactly one reviewer and 0–2 coders. The Principal plans, implements its own tasks in its own worktree, integrates into the slice branch and runs the slice gate. Solo (no coders) replaces tier 1; 1–2 coders replace tier 2.
- **Reviewer independence:** launch validation rejects a reviewer whose model family matches an implementer's. Defaults: Principal `pi openai-codex/gpt-6.1-sol high`, reviewer `claude claude-opus-5-5 high`, coders `pi openai-codex/gpt-6.1-sol medium`.
- **One cycle per task:** tests, RED log before implementing, green, review, cyclic fixes; omission mutants only for facts that did not fail in the initial RED. One grant per task.
- **Closed minimum evidence**, reviewer scope limited to correctness, test meaning and minimum evidence, three review rounds then escalation, narrow escalation classes with record-and-continue, autonomous tests, focused runs without lease, direct execution by the responsible agent as a fallback.
- **Review queue:** implementers send `REVIEW_REQUEST` straight to the reviewer; events carry `sentAt`; `event pending` and the supervisor deliver each inbox first in, first out.
- **Principal restart** is optional (`bootstrap restart-principal`, alias `rotate-principal`); no mandatory rotation.
- `references/grants.md` merged into `references/execution.md`.

### Breaking

- Launch contract: `tier` is rejected; `roster` is `{"coders": 0..2}` (absent = 0); `models.reviewers` becomes `models.reviewer`, and `models.coders` is present only with coders.
- Agent names: `<prefix>-reviewer` (was `-reviewer-a`); coders only `-coder-a`/`-coder-b`.
- The responsible agent no longer coordinates tasks; tier-1 bootstrap is gone.
- Events: `REVIEW_ASSIGN` removed; new `LEASE_REQUEST` and `LEASE_RELEASE`; `TASK_ASSIGN` no longer takes `parallelismRevision` nor checks `state.json.parallelism`; verdicts go to the implementer with a copy to the Principal.
- `state.json` schema 2 (`plan`, `openFindings`, `leases`; no `tier`, `parallelism` or `reviewQueue`).
- Automation version 2.0.0: runs created by 1.x keep their run-pinned runtime and their frozen skill snapshot; do not drive them with these scripts.
