# Migration to orchestrate-zafir-implementation

Temporary. Delete this file, `implement-with-swarm` and `prepare-slices-with-agents` once every item is done.

## Into this skill

- [x] `swarm/`: move implement-with-swarm's body, `roles/`, `references/` and `scripts/` (with tests), keeping the event protocol.
- [x] `swarm/`: add the `codex` harness to `scripts/swarmcore.py` (`HARNESSES`, efforts, start arguments, yolo flag) and its tests; set the Principal default to `codex gpt-6.1-sol high`.
- [x] `swarm/`: refactor step (ponytail) after all green, before the deep review; compliance, touched guards and main merge before `SLICE_READY`.
- [x] `preparation/`: 5.1–5.4 steps and completion criteria from prepare-slices-with-agents, generalised (no Uwassi paths, no Decision 032 citations).
- [x] `consultants/`: start commands, context clearing per CLI, queue, mandate.
- [x] `integration/`: batches, gate plan, documentation batches, cleanup.
- [x] `SKILL.md`: decision log and owner-request formats, admission, supervision.
- [x] `skills.sh.json`: list the skill under Agent Workflows.

## Into zafir-development-process

- [x] JSON is read and written only with `jq` or Python, by ID; provide scripts for the common reads and merges.
- [x] Hashes are computed and checked by tool, never by reading the file.
- [x] Markdown and code are read through graft, or `rg -n` plus a line range.
- [x] Shell output is bounded to about 40 lines.
- [x] ARCHITECTURE-GUIDELINE: prefer ports for every I/O operation (database, clock, network, filesystem).
- [x] IMPLEMENTATION: refactor with ponytail once every test is green, before review.
- [x] Talking to the user: concise, tables where possible, `unslop` patterns applied before sending.

## Removal

- [x] Delete `implement-with-swarm` from this repo (2026-10-24).
- [ ] Delete the installed copy `~/.agents/skills/implement-with-swarm` once no live run uses it as `skillRoot`.
- [ ] Delete `prepare-slices-with-agents` (Uwassi `.agents/skills/`) once no preparer runs under it.
