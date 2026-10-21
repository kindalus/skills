# Models: explicit configuration and recovery

## Input contract

`models` contains exactly `principal` and `reviewer` (only for runs launched before 2.4.0: plus `coders` when `roster.coders` is 1 or 2). Every value is a string of three whitespace-separated tokens:

```text
harness model thinking_effort
```

Defaults (owner decisions 2026-10-02 and 2026-10-14: Principal effort `medium`, always Principal and reviewer, no coders), copied explicitly into the launch contract unless the owner or the project records others:

```json
{
  "principal": "pi openai-codex/gpt-6.1-sol medium",
  "reviewer": "claude claude-opus-5-5 high"
}
```

The team is always Principal and reviewer, so the contract never has a `coders` entry and `roster.coders` is 0.

No entry, model, or effort is inferred from the caller, environment, another role, or a harness default; the responsible agent writes each triple and validates it for each run. Implementer triples may repeat.

**Independent reviewer.** The reviewer's model family must differ from every implementer's. The scripts derive a coarse family: harness `claude` is Anthropic and `agy` is Google; otherwise the first hint in the model ID (`claude`, `anthropic`, `opus`, `sonnet`, `haiku`, `fable` → Anthropic; `gemini`, `google` → Google; `gpt`, `openai`, `codex` → OpenAI), else the provider prefix. A same-family reviewer is rejected at validation; the one exception is the [reviewer quota fallback](#reviewer-quota-fallback-owner-decision-2026-10-02), never a launch triple. `thinking_effort` is the canonical spelling. Preserve the model identifier's case; require the harness token in lowercase. A triple is data, never an executable shell string.

Supported harnesses are `pi`, `claude` and `agy` (Gemini CLI wrapper). `claude` and `agy` are launched with `--dangerously-skip-permissions` because the team drives them through Herdr prompts with nobody at the permission UI; their effective configuration is read from the process arguments, not from `PI_*` variables. Framework independence does not imply untested harness support. Reject unknown harnesses and report what is missing rather than constructing guessed launch arguments.

## Validation and launch

1. Parse with ordinary string splitting and require exactly three nonempty tokens. Reject control characters, option-like model tokens beginning with `-`, shell operators, and glob patterns. Do not split a Pi model/provider ID at every `/`; the entire token belongs to `--model`.
2. Check the installed executable, `--help`, Herdr `agent` kind list, and current server support. No automatic installation, trust escalation, login, or global settings changes.
3. Verify the exact model or documented alias and requested effort against the harness's available catalog/configuration. Pi supports provider/model IDs and `--list-models`; a listed model proves catalog/auth presence, not working credentials, entitlement, remaining quota, or provider uptime. Claude aliases and model IDs must be verified rather than guessed from a marketing name.
4. Translate to separate argument values as below. Prefer subprocess argument arrays; if issuing a shell command, quote every validated value independently. Do not use `eval`, raw triple interpolation, arbitrary extra flags, or credential arguments.
5. Start in the recorded pane with the exact role configuration. Herdr interactive readiness is only stage one. Send a minimal `BOOT` that reads the role/contract, performs a harmless local tool check, and produces `AGENT_READY`; this exercises an actual model request. Do not ask it to edit project code during this check.
6. Confirm configured and effective model/effort from native session metadata, runtime configuration, or diagnostic output where the harness exposes them. In Pi, the agent's shell tools expose `PI_PROVIDER`, `PI_MODEL`, and `PI_REASONING_LEVEL`; inherited parent environment outside those tools is not proof. Do not trust an LLM's unaided statement of its own identity. If the runtime clamps the effort, substitutes a model, or cannot substantiate the requested configuration, report the mismatch/unverified configuration before productive work.

| Harness | Native arguments after Herdr's `--` |
| --- | --- |
| `pi` | `--model <model> --thinking <thinking_effort>` |
| `claude` | `--model <model> --effort <thinking_effort> --dangerously-skip-permissions` |
| `agy` | `--model <model> --effort <thinking_effort> --dangerously-skip-permissions` |

Exact launches, with the pane ID taken from Herdr:

```bash
herdr agent start s463-principal --kind pi --pane <id> -- --model openai-codex/gpt-6.1-sol --thinking high
herdr agent start s463-reviewer --kind claude --pane <id> -- \
  --model claude-opus-5-5 --effort high --dangerously-skip-permissions
```

Herdr passes everything after `--` to the harness unchanged. For Claude, use the full model ID (`claude-opus-5-5`), not the moving alias `opus`, so the process arguments prove the model; evidence is `/proc/<pid>/cmdline` of the pane's `claude` process. The user setting `skipDangerousModePermissionPrompt` must already be true, or the bypass warning blocks readiness; a workspace-trust dialog in a new home is answered by the user, never guessed.

The installed CLI and model-specific capabilities are authoritative. Pi's vocabulary is `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; Claude Code 2.1's `--effort` takes only `low`, `medium`, `high`, `xhigh`, `max`, and the scripts reject the rest. Matching names are not equivalent reasoning budgets. An unsupported level is an incident, not permission to lower it. Do not enable Claude's `--fallback-model` or accept a silent fallback from existing configuration; obtain an explicit replacement decision.

Only role/instruction prompts and scoped file access are added as needed through documented harness mechanisms. Preserve repository instructions and user permissions. If a nested harness refuses startup, report the incompatibility instead of removing safety environment variables blindly.

## Model incident

Detect incidents both during startup and while agents work. The Principal checks its children; the responsible agent checks the Principal. A successful initial request never guarantees future quota.

The first observer publishes `MODEL_ERROR` immediately on observation, with:

- run, role, agent, generation, pane and native session identity;
- configured triple and any verified effective mismatch;
- classification: `model-unavailable`, `auth-or-access`, `quota-exhausted`, `rate-limited`, `unsupported-effort`, `startup-failed`, or `unresponsive-unknown`;
- sanitized error text/code, timestamp, active task/assignment/candidate, preserved paths, and the required decision;
- whether the old process is still running and can safely checkpoint.

Classify only from evidence. HTTP 429 may be rate limiting rather than exhausted quota. Herdr `blocked` can mean a permission/question UI; a timeout or `unknown` is not proof of model failure. Inspect before retrying and never resubmit a possibly delivered assignment under a new ID.

Suspend new assignments to the affected role. Healthy agents may finish safe checkpoints and independent reviews, but partial startup never becomes `SWARM_READY`, and unresolved configuration failures never become `SLICE_READY`. Preserve branches, dirty files, reports, inboxes, and native session IDs. If repeated retry is clearly unsafe or cannot progress, stop immediately rather than exhausting the account.

The responsible agent either supplies an explicit new triple via `MODEL_REPLACE`, authorizes a bounded retry/wait for the original model, or pauses/cancels the run. Suggestions are not authorization; do not choose a substitute or reduce team size yourself. An access/trust dialog still requires the user or an already-authorized permission handler, not a fabricated approval.

## Replacing a role

`MODEL_REPLACE` comes only from the recorded responsible agent and includes `role`, complete `configuration`, and the incident ID. It changes that role's configuration, not the other roles or account credentials, and a reviewer replacement must still be another model family. The scripts validate the payload (`role`, `configuration`, `incidentId`) and reject a same-family reviewer except the quota fallback below. Only for runs launched before 2.4.0: apply the same configuration to every coder, and pause new assignments during the change rather than leaving a mixed pool.

1. Validate the new triple; record the decision and bump the role configuration revision in `state.json`.
2. Ask affected workers to pause/checkpoint. Record current task state, dirty paths, candidate SHA, outstanding findings, inbox receipts, and session identity. If a worker cannot answer, inspect its worktree and process from the supervisor; do not invent a checkpoint commit or discard files.
3. Stop the old instance using the harness's documented graceful controls. Confirm through Herdr/process inspection that it and any mutating child command have stopped before another writer can access the same worktree. If that cannot be established, remain blocked and ask the responsible agent. Do not stop the Herdr server or unrelated processes.
4. Increment each affected agent generation, retain its logical name/pane where possible, and restart with the new explicit configuration. Start only in an available shell pane. Pass the role file, run contract, current assignment/checkpoint, and pending findings; a new harness need not understand another harness's native session format.
5. Validate `AGENT_READY` for the new generation and resume only the preserved assignment. Deduplicate old inbox events; reject old-generation work/verdicts. A review interrupted by replacement starts afresh on the frozen candidate; no verdict is inferred from partial output. Already accepted approvals remain tied to their original SHA unless code changed.

**Principal failure is different.** Principal cannot reliably report or replace itself when its model is unusable. Responsible detects failed startup, terminal/provider errors, or lack of responsiveness through CLI inspection and bounded checks, chooses an explicit replacement, and stops/confirms the old Principal before starting the new generation. Children create no replacement Principal. They pause at checkpoints when they observe the outage or receive the responsible agent's pause notice; that notice does not assign them new work. The replacement Principal takes over `state.json`, inventories existing children/worktrees, revalidates reservations and in-flight integration, and adopts rather than duplicates them. Responsible still launches only a Principal, never the workers. `bootstrap restart-principal` restarts the **launch** configuration for an optional clean restart; it is not a model replacement.

All incidents and decisions stay in the run records. Report recovery with the actual role triple and affected agents. Recovery restores execution; it does not approve any task.

## Reviewer quota fallback (owner decision 2026-10-02)

When the Claude reviewer (`claude claude-opus-5-5 high`) hits its weekly usage limit, the replacement reviewer is `pi openai-codex/gpt-6.1-sol high` (catalog row `openai-codex gpt-6.1-sol`; owner decision 2026-10-14, was `gpt-6-astra medium`). It is a recorded exception to **Independent reviewer**: the same OpenAI family and model as the Principal, at a higher effort.

- **Trigger:** a `MODEL_ERROR` with `payload.role: "reviewer"` and `payload.classification: "quota-exhausted"`, from the reviewer or from the Principal observing it, through the incident flow above. A `rate-limited` 429 is not quota.
- **Decision:** the responsible agent sends `MODEL_REPLACE` with `{"role": "reviewer", "configuration": "pi openai-codex/gpt-6.1-sol high", "incidentId": "<MODEL_ERROR id>", "reviewerFallback": "<MODEL_ERROR id>"}`. The scripts accept a same-family reviewer only in this shape: the exact triple, the marker equal to `incidentId`, naming this run's reviewer quota `MODEL_ERROR`. Any other configuration carrying the marker is rejected; launch validation rejects the fallback triple outright.
- **Start:** `herdr agent start <prefix>-reviewer --kind pi --pane <id> -- --model openai-codex/gpt-6.1-sol --thinking high`. Native proof: `PI_PROVIDER`, `PI_MODEL` and `PI_REASONING_LEVEL` from the agent's shell tools match `openai-codex/gpt-6.1-sol` and `high`.
- **Record:** the Principal writes `roleConfigurations.reviewer.reviewerFallback` in `state.json`: `{"incidentId": "<id>", "independence": "reduced: same family (openai) as the implementers", "reviewedTasks": []}`, appends each task the fallback approves, and keeps one open finding, re-review by the Claude reviewer, until it closes. Every fallback report states the reduced independence.
- **Return to Claude:** when quota returns, the responsible agent sends `MODEL_REPLACE` back to `claude claude-opus-5-5 high` with the same `incidentId`. The deep slice review belongs to the Claude reviewer and re-reviews every task in `reviewedTasks` before `SLICE_READY`. If quota has not returned when the slice is otherwise ready, the responsible agent escalates to the owner; the fallback's approvals never close the slice alone.

## Sources to recheck when adapting launch behavior

- Installed `herdr --help` and `herdr agent`, plus the installed Herdr skill.
- Pi's installed `README.md` CLI reference and `docs/models.md` / `docs/environment-variables.md` (resolve from its package directory), plus the [Pi documentation](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent).
- Installed `claude --help` and the [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference).

Do not copy a model catalog into this skill; availability, aliases, and effort support must be checked for each run.
