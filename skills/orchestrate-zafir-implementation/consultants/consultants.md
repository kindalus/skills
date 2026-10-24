# Consultants

Consultants investigate, refine and stress-test a preparer's slice, and review bug fixes. They advise; they never decide. The orchestrator reads this whole file; a consultant reads only its [Mandate](#mandate).

## Roster

One consultant per model family, all at reasoning high, in the consultants' tab. `<cli>` names it: its agent name and pane title are its [Naming](../references/naming.md#table) row.

| `<cli>` | Family | Start, after `herdr agent start <name> --pane <id>` | Clear context |
| --- | --- | --- | --- |
| `claude` | Anthropic | `--kind claude -- --model claude-opus-5-5 --effort high --dangerously-skip-permissions` | `/clear` |
| `codex` | OpenAI | `--kind codex -- --model gpt-6.1-sol -c 'model_reasoning_effort="high"' -a never` | `/new` |
| `agy` | Google | `--kind agy -- --model gemini-3.8-flash --effort high --dangerously-skip-permissions` | `/new` |

Clear with `herdr agent prompt <name> "<command>" --wait --timeout 300000`. A new-context command can drop the agent's Herdr name: confirm it in `herdr agent list` and, when it is gone, re-register it by pane (`herdr agent rename <pane_id> <name>`) before the next prompt. A consultant whose model is out (quota, persistent API failure) leaves the roster until it returns; serve the queue with the other families, and tell the owner when no eligible family is left.

## Queue

`J/consultants-queue.md` holds the holder table and a single first-come-first-served queue:

```markdown
| Consultant | Holder | Since (UTC) | For |
| --- | --- | --- | --- |
| consultant-claude | FREE | 16:19Z | released by s563-preparer (S563 R2, answer 3d3ce8e0) |

## Queue
1. (served) s593-preparer, S593 R1: claude and codex granted 12:58Z, request 9b42adac
2. s595-preparer, S595 pre-mortem: request d4db1d7b; any family but OpenAI
```

1. **Enqueue** a request only when it is [ready](#requests); an incomplete one goes back to its preparer.
2. **Grant** in queue order. Clear the consultant's context, confirm its name, set the holder row, retitle its pane with the slice ([Naming](../references/naming.md#applying-it)), and tell the preparer which consultants it holds. Every grant starts from a clean context.
3. **Release.** The preparer releases each consultant to the orchestrator individually, with the answer's sha256. Set the row to `FREE`, retitle the pane free, mark the item served, log it, and grant the next item.

**Families.** The final pre-mortem is always by a consultant from a family other than the preparer's, with a clean context. A bug review is by a family other than the executor's.

## Requests

A request is a file in the preparer's worktree, under the slice's evidence directory (in `J/prep-<slice>/` only while the worktree is not ready), sent to the orchestrator as path and sha256. It is ready when it has:

- **frozen inputs**, listed with their sha256;
- **numbered questions**, each with options;
- the **answer format**: one line per question, `Q<n>: <option> — reason`, plus findings with severity.

The preparer dispatches the request to each consultant it holds, separately and without `--wait`, so each answers without seeing the others' answers. When the Herdr capture of an answer fails, the preparer asks the orchestrator, which recovers the text from the consultant's session transcript.

## Mandate

You are a consultant: you answer one request, then stop.

- Verify each input's sha256 against the request before relying on it.
- Ground every claim in a file and line, or in a command you ran. Read through graft or `rg -n` plus a line range.
- Answer in the request's format, as public text in your reply.
