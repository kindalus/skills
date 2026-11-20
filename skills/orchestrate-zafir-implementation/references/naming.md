# Naming

The one source for every worktree path, branch, Herdr agent name, pane title, workspace label and tab the team creates (owner-approved). Every other file points here; when a name changes, change it here only.

## Location

Every worktree lives at `<repo>/.worktrees/<name>`, `<repo>` being the project's main checkout root (Herdr creates worktrees only from it). `.worktrees/` stays transient to Git through the local, unversioned `<repo>/.git/info/exclude`, never `.gitignore`: `scripts/preflight.sh --project <repo>` appends `/.worktrees/` when it is missing (`--check` only reports it). The job directory `J` and every run directory stay outside the repository.

Because the excluded `.worktrees/` holds every live checkout, clean the main checkout only with `git clean` without `-x`/`-X`.

## Table

`<slice>` is the lowercase slice ID (`s567`). `<task>` is the task's short name, chosen by the lead (`t01`). A review checkout's `<task>` is the reviewed task ID lowercased without its `<slice>-` head (`slice` for the deep slice review), and `-r<n>` is the review revision. `<id>` is the lowercase bug ID; `<n>` a number.

| Element | Worktree | Branch | Herdr agent | Pane title | Workspace / tab |
| --- | --- | --- | --- | --- | --- |
| Slice | `.worktrees/<slice>` | `slice/<slice>` | — | — | workspace label and tab `<slice>`, opened from the repo's workspace |
| Implementer lead | the slice worktree | — | `<slice>-lead` | `<slice> · lead` | tab `<slice>` |
| Task | `.worktrees/<slice>-<task>` | `task/<slice>/<task>` | — | — | — |
| Review checkout | `.worktrees/<slice>-review-<task>-r<n>` | — (detached) | — | — | — |
| Preparer | `.worktrees/<slice>-preparation` | `prep/<slice>` | `<slice>-preparer` | `<slice> · preparer` | workspace label and tab `<slice> · preparation`, open while the preparer works and holding its pane, so the owner can follow it |
| Orchestrator | — | — | `orchestrator` | `orchestrator` | tab `Orchestrator` |
| Consultants | — | — | `consultant-claude`, `consultant-codex`, `consultant-agy` | `consultant-<cli> · free` or `consultant-<cli> · <slice>` | tab `Consultants` |
| Bug executors | `.worktrees/bug-<id>` | `bug/<id>` | `bugs-1` … `bugs-4` | `bugs-<n> · <id>` | tab `Bugs` |
| Batch | `.worktrees/batch-<n>` | `integ/batch-<n>` | — | — | workspace `batch-<n>`, closed at the end |
| Admission | `.worktrees/<slice>-admission`, detached | — | — | — | — |
| Setup window | `.worktrees/<slice>-setup`, detached at the preparation's base; untracked manifested sources only, removed after the window | — | — | — | — |

## Applying it

- **Titles:** `herdr pane rename <pane_id> "<title>"` when the agent starts, and again whenever its work changes: a consultant at each grant (`· <slice>`) and release (`· free`), a bug executor at each new bug.
- **Grouping:** a worktree's workspace is grouped under the repo only when Herdr opens it from the repo's workspace (`herdr worktree create --cwd <repo>` or `herdr worktree open --workspace <repo workspace>`). `herdr workspace create --cwd <worktree>` makes a loose workspace: never use it for a worktree. Subagents get the lead's worktrees, never an isolated one their tool would create elsewhere.
- **Detached checkouts** (review, admission): Herdr cannot create one, so run `git -C <repo> worktree add --detach <path> <sha>` and open it with `herdr worktree open`.
