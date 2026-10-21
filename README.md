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
| `implement-with-swarm` | Implement an approved slice with a Herdr-managed Principal and independent reviewer, supervised by the responsible agent. |
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
- `implement-with-swarm` requires a Herdr-managed session, Git worktrees, configured agent harnesses, and a supervising responsible agent.
- `zafir-development-process` and `implement-with-swarm` reference companion skills by name; install those separately when required.

## Validation

Run the local validator before publishing changes:

```bash
python3 scripts/validate_skills.py
```

## License

MIT. See [LICENSE](./LICENSE).
