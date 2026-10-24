# Control-plane threat model

The scripts protect workflow integrity and reduce accidents. All agents currently share one Unix account, so this is not a hostile-process sandbox.

## Trust seams and assets

Untrusted inputs cross the interface through launch JSON, event/report JSON, model output, filesystem paths, environment variables, Git state, and Herdr responses. Protect:

- main-checkout work and Git history;
- run/slice ownership and the single-writer rules;
- agent identity, generation, model, and assignment;
- test/evidence integrity;
- credentials and provider output;
- token/time budgets and liveness.

## Threats and controls

| Threat | Required control |
| --- | --- |
| Duplicate bootstrap or split-brain | Per-run journal, unique names, live-resource reconciliation, one Principal generation, one supervisor lock; a restart only after the old Principal's name has left Herdr, in the recorded pane, with a journaled intent that resumes without a second bump |
| Self-review or same-family review | Exactly one reviewer, distinct from every implementer; launch and `MODEL_REPLACE` validation reject a reviewer of an implementer's model family, except the exact reviewer quota fallback whose marker names the reviewer's `quota-exhausted` `MODEL_ERROR`; verdicts come only from the reviewer |
| Wrong assigner | Only the Principal sends `TASK_ASSIGN` (to itself; to a coder, and `TASK_INTEGRATED`, only for runs launched before 2.4.0); only the Principal requests the lease or declares `SLICE_READY` |
| Grant changed after dispatch | `TASK_ASSIGN` binds the grant file by path under `runDir/reports` and SHA-256; a later edit invalidates the event |
| Stale/replayed event | Validate run, route, current sender generation, type-required assignment/revision/SHA bindings and grant hash on task dispatch; receipt keyed by event UUID and event hash |
| Review queue starvation or reordering | Events stamped `sentAt`; pending lists and supervisor delivery are first in, first out per recipient |
| Partial/concurrent file write | Unique same-directory temporary file, file and directory `fsync`, atomic replace for mutable projections, exclusive immutable publication |
| Evidence overwrite | Destination must not exist; identical idempotence only where explicitly supported; logs/exits become read-only |
| Path traversal or symlink escape | Canonicalize and require containment below allowlisted roots; never operate on a raw payload path |
| Command/model injection | Parse model triples as exactly three validated tokens; use subprocess argument arrays; no `eval`; reject shell gate executables |
| Git/WIP destruction | Bootstrap creates only the recorded worktree/branch; an unowned worktree must be clean at `baseSha`; an existing branch must already be at its base, because Herdr ignores `--base` for it; no reset, force, push, or automatic cleanup |
| LLM output grants authority | Scripts validate facts and routes only; no script accepts product scope, failing gates, permissions, findings, or integration |
| Wake sent to wrong agent | Scan every inbox and route directly to the validated `event.to` recipient |
| Lost wake | Persistent delivery ledger; retry until receipt with bounded exponential backoff |
| Duplicate/injected wake | Prompt only ready recipients; filesystem receipt is the idempotency boundary; recheck receipt immediately before prompting |
| Recipient absent or UI-blocked | Herdr notification; do not answer, replace, or approve automatically |
| Crash after a side effect | Journal each resource immediately; on restart observe and adopt matching resources, fail closed on ambiguity |
| Silent model substitution | Require native evidence after a real request (`PI_PROVIDER`, `PI_MODEL`, `PI_REASONING_LEVEL` in Pi; full model ID and effort in the Claude, agy or Codex process arguments); use generation replacement rather than a live slash-command assumption |
| False success from Herdr state | `idle`/`done` means ready for input only; completion requires protocol event, receipt, exact evidence, and applicable gate |
| Event/report flooding | 1 MiB JSON limit, compact projections, persistent backoff, one prompt per recipient per cycle |
| Credential leakage | Run directory mode `0700`, files `0600`/`0400`, no environment dumps or unsanitized provider payloads |
| Supervisor failure | PID/lock plus `supervision/status.json`; responsible verifies heartbeat during supervision |
| Unsafe cleanup | Cleanup remains a separately authorized decision of the responsible agent. `worktree remove` only executes it: this run's checkouts, clean, head contained in the named ref, no live agent in the workspace (Herdr kills pane processes on removal), never `--force`, branch kept; never `workspace close --group`. Empty-pane closing (`worktree task`, `review`, `close`) touches only idle shells (no agent, the shell as sole foreground process) with a plain `pane close` or `workspace close`; a busy pane is kept and reported |

## Fail-closed conditions

Stop and report instead of repairing when:

- an existing resource has the expected name but a different cwd, pane, branch, run, or owner;
- immutable bytes differ;
- an event route or identity is invalid;
- a gate output already exists;
- a worktree path exists but is not recorded;
- more than one matching tab/pane or supervisor is found;
- a new path, model, permission, product decision, or destructive action is needed.

## Known residual risks

- A process with the same Unix identity can modify another agent's files and impersonate it. Strong isolation requires separate OS identities or containers.
- Atomic rename cannot make an external Herdr/Git side effect and the journal update one transaction. Recovery therefore observes real resources and rejects ambiguity.
- A prompt may race with receipt creation. The courier rechecks the receipt immediately before delivery, but one benign duplicate wake remains possible.
- Herdr/provider availability is external. The supervisor detects missing/blocked recipients but cannot safely replace them.
