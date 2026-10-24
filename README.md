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
| `llm-wiki` | Build and maintain persistent, interlinked Markdown knowledge bases that compound over time. |
| `orchestrate-zafir-implementation` | Orchestrate Zafir slices from one Herdr pane: dedicated preparers and consultants through 5.1–5.4, swarms for implementation, and single-integrator batches into main. |
| `vendus-erp-api` | Query Vendus/Cegid Vendus ERP data through read-only API helpers for customers, balances, products, stock, and documents. |
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

- `vendus-erp-api` is strictly read-only and requires a user-provided `VENDUS_API_KEY`.
- `orchestrate-zafir-implementation` requires a Herdr-managed session, Git worktrees, jq, the claude, codex, pi and agy CLIs, and the ponytail, graft and grilling skills; its `scripts/preflight.sh` checks them.
- `zafir-development-process` and `orchestrate-zafir-implementation` reference companion skills by name; install those separately when required.

## Validation

Run the local validator before publishing changes:

```bash
python3 scripts/validate_skills.py
```

## License

MIT. See [LICENSE](./LICENSE).
