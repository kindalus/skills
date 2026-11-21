# Kindalus Skills

A public collection of Agent Skills maintained by Kindalus.

Skills follow the [Agent Skills specification](https://agentskills.io/specification) and are intended to be installable through the [`skills` CLI](https://www.skills.sh/docs/cli).

[![skills.sh](https://skills.sh/b/kindalus/skills)](https://skills.sh/kindalus/skills)

## Install

Install all skills from this repository:

```bash
npx skills add kindalus/skills
```

Install a specific skill:

```bash
npx skills add kindalus/skills --skill llm-wiki
npx skills add kindalus/skills --skill vendus-erp-api
```

## Available skills

| Skill | Purpose |
|---|---|
| `harness-status-bar` | Canonical, responsive two-line terminal status bar layout specification for AI coding agent harnesses. |
| `llm-wiki` | Build and maintain persistent, interlinked Markdown knowledge bases that compound over time. |
| `implement-with-subagents` | Take one Zafir slice to ready-to-integrate from a single Claude Code or Codex lead that delegates to cheaper subagents and reviews with a clean-context subagent; prepares the slice first when phase 1 is open. Works with or without an orchestrator or Herdr. |
| `orchestrate-zafir-implementation` | Orchestrate Zafir slices from one Herdr pane: dedicated preparers and consultants through 5.1–5.4, one implementer lead per slice (by default `implement-with-subagents`), and single-integrator batches into main. |
| `vendus-erp-api` | Query Vendus/Cegid Vendus ERP data and create documents after explicit confirmation. |
| `zafir-development-process` | Apply the Zafir workflow from governing context and design through slice preparation, test-first implementation, integration, and closure. |

## Repository structure

```text
skills/
  <skill-name>/
    SKILL.md          # Required metadata and instructions
    references/       # Optional on-demand documentation
    scripts/          # Optional helper scripts
    assets/           # Optional static resources
```

## Notes

- `vendus-erp-api` requires a user-provided `VENDUS_API_KEY`. Queries and confirmed document creation are supported; updates, deletions, and cancellations remain blocked.
- `orchestrate-zafir-implementation` requires a Herdr-managed session, Git worktrees, jq, the claude, codex, pi and agy CLIs, and the ponytail, graft and grilling skills; its `scripts/preflight.sh` checks them.
- `llm-wiki` works with plain files; its optional semantic index requires [uv](https://docs.astral.sh/uv/) and downloads a ~120 MB embedding model on first use.
- `zafir-development-process` and `orchestrate-zafir-implementation` reference companion skills by name; install those separately when required.

## Validation

Run the local validator before publishing changes:

```bash
python3 scripts/validate_skills.py
```

## License

MIT. See [LICENSE](./LICENSE).
