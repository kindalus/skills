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
| `port-claude-design-prototype` | Port Claude Design HTML/React prototypes into an existing project stack with visual and behavioral parity. |
| `vendus-erp-api` | Query Vendus/Cegid Vendus ERP data through read-only API helpers for customers, balances, products, stock, and documents. |
| `zafir-development-process` | Apply the Zafir development process for brainstorm → design → plan → implementation workflows. |

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
- `zafir-development-process` intentionally references companion workflow skills by name. Those references are preserved as part of the skill design.

## Validation

Run the local validator before publishing changes:

```bash
python3 scripts/validate_skills.py
```

## License

MIT. See [LICENSE](./LICENSE).
