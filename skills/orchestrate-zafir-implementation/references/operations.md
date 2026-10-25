# Operations

Shell and Herdr lessons that bite every role. Read the `herdr` skill first; the installed binary is the authority on syntax (`herdr <group> --help`).

## Shell

- **Running scripts:** never edit a script while it runs. Write the new version to another file and install it with `mv`.
- **zsh:** write lines containing backslashes with Python, not `echo`.
- **`pgrep -f`:** use a pattern that cannot match the calling shell, such as a character class (`[s]cript.sh`) or the exact script name.

## Herdr

- Never run `herdr` without a subcommand: it opens the TUI instead of answering.
- Read every ID (workspace, tab, pane, agent) from the JSON answers, never from memory or prediction.
- **Prompt:** `herdr agent prompt <name> "<text>"` submits multi-line text atomically. `--wait --timeout 300000` blocks until that agent settles: use it only for short questions and for commands such as `/clear` or `/compact`. Dispatch work to several agents without `--wait`. On `agent_prompt_stalled`, inspect with `agent get` and `agent read` before resending.
- **Two prompts at once concatenate and both are lost:** send each one separately, after the previous has settled.
- **Read:** `herdr agent read <name> --source recent-unwrapped --lines 40` (raise `--lines` only as far as needed). When the screen hides the answer, the orchestrator recovers it from the agent's session transcript.
- **States:** `working` is busy; `blocked` is a permission UI or a question, to answer now; `idle` and `done` are ready for input, never proof of completion; `unknown` proves nothing, so read the screen.
- **Waiting:** to wait for a command to finish, use `prompt --wait`; `agent wait --until idle` can miss a transition that happens while it runs and return the old state. `--until working` does observe entry into work.
- **Worktrees in large repositories:** the checkout of `herdr worktree create` can outlast its default timeout and leave the worktree locked while Git still writes. Pass a generous `--timeout`, and on a timeout wait for the checkout process to end instead of repeating the command. Stagger many creations: parallel checkouts saturate the disk and slow every gate.
- **Names and titles:** every agent name, pane title, tab and workspace label comes from [Naming](naming.md), which also says when to retitle.
- **Notifications** (`herdr notification show "<title>" --body "<text>" --sound request|done`) only for a slice started or closed, an agent `blocked`, a suspected stall, or a red gate.

## Mail

Agents outside a swarm (orchestrator, spokesperson, preparers, consultants, bug executors) talk through **mail**, never through `herdr agent prompt`: a prompt to a `blocked` agent is rejected with `agent_blocked` and lost. Swarm members keep their run's events (`swarmctl`), which follow the same rules.

- **Mailbox:** `$J/correio/`, one `inbox/<agent>/` and one `receipts/<agent>/` per agent name. A message is a file; a receipt closes it.
- **Send:** `python3 <skill>/scripts/correio.py send --from <you> --to <agent> --type PEDIDO|ENTREGA|INFO --subject "<one line>" --body-file <file>` (or `--body "<short text>"`; `--payload-file <json>` for structured data). `PEDIDO` asks for an action, `ENTREGA` hands over a result to check, `INFO` decides nothing.
- **Receive:** the courier prompts you with the path of your oldest unread message. Record the receipt before acting: `correio.py receipt --agent <you> --id <id> --disposition "<what you do>"`. The next message comes only after that receipt.
- **Courier:** a `systemd --user` service (`correio-<repo-key>.service`) runs `correio.py daemon`. It delivers one message per recipient at a time (FIFO), only while the recipient is `idle` or `done`; for a `blocked` or absent one it raises a Herdr notification. It retries on a 30 s backoff doubling to 480 s and never drops a message.
- **Observers:** the same daemon replaces every re-armed watcher. With `--watch-to orquestrador` it mails the orchestrator when any agent turns `blocked` (except the quiet ones, `--quiet porta-voz`), when an agent matching `--done-pattern` goes from `working` to `done` or `idle`, when a `--watch-ref <repo>:origin/main` advances, and when a swarm event under `--watch-runs <runs dir>` waits more than 120 s for its receipt.
- **Who talks to whom:** agents write to each other directly, without copying the orchestrator; the orchestrator gets only what is addressed to it. Send what changes the recipient's next action, never a bare acknowledgement.
- **Bootstrap exception:** the first instruction to a freshly started agent, and harness commands such as `/clear` or `/compact`, still go by `herdr agent prompt`, because the agent does not know its mailbox yet.

## Owner questions

The orchestrator never asks the owner directly: a question dialog blocks it, and then its mail cannot be delivered. The **spokesperson** (`porta-voz`, [card](spokesperson.md)) asks in its place.

1. Write the owner request (`J/requests/REQUEST-<n>.md`) as usual.
2. Mail a `PEDIDO` to `porta-voz` whose payload is `{"request": "REQUEST-<n>", "askUserQuestion": [<the exact AskUserQuestion questions>]}`, and keep working.
3. The spokesperson returns the owner's verbatim answers as an `ENTREGA`; record them as `ANSWER-<n>` and apply them.

Start the spokesperson once, in a pane of the orchestrator's tab: `herdr agent start porta-voz --kind claude --pane <id> -- --model claude-haiku-5-5 --allowedTools "Bash(python3 <skill>/scripts/correio.py:*)" AskUserQuestion "Write(/tmp/**)"`, then prompt it with the path of its card.

## Stalls

1. `herdr agent get <name>` and a bounded `herdr agent read <name>`.
2. Output progressing: keep waiting.
3. Stopped at a question or approval: answer it.
4. Stuck (loop, silent error, lost prompt, network or model error): resend the instruction, or `herdr agent send-keys <name> esc` and then resend; a persistent model error is a model incident (swarm: `MODEL_ERROR`). Notify the owner with `--sound request`.
5. Log the incident and show it in the pipeline.

## Context

An agent near the end of its context reasons worse, and past it truncates silently; the CLIs' own auto-compaction does not prevent it. Read the CLI the agent runs now (the `agent` field of `herdr agent list`), not its role:

| CLI | Shows usage | Compacts |
| --- | --- | --- |
| `pi` | yes (footer, for example `62.3%/272k`) | `/compact` |
| `codex` | yes | `/compact` |
| `claude` | yes, status line | `/compact` |
| `agy` | no | no |

- **Before delegating,** check the receiving agent; a free, full agent is cleared or compacted at no cost.
- **A working agent** is compacted in three separate calls: `herdr agent send-keys <name> esc`; `herdr agent prompt <name> "/compact" --wait --timeout 300000`; then the resume prompt.
- **The resume prompt** is never "continue". It carries the slice and phase, the work dispatched and to whom, what is half done and what was delivered, and the order to print the pipeline before going on. Copy it from the pipeline and the decision log.
- **The orchestrator itself** cannot compact itself mid-turn. Write the resume state and run `scripts/auto-compact.sh launch < resume.md` (or `--resume-file <path>`); a helper tab interrupts you, compacts, waits for the durable compaction event in the session file, sends the resume and closes. End the turn right after launching it. It reads Pi session files, so it supports a `pi` target only; for another CLI, ask the owner to compact you.
