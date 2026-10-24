#!/usr/bin/env bash
# Fail-closed environment check for orchestrate-zafir-implementation.
# Usage: preflight.sh [--project <repo>]
# Exit 0 when every requirement is present; exit 1 listing what is missing.
set -u

project=""
[ "${1:-}" = "--project" ] && project="${2:-}"

missing=()

[ "${HERDR_ENV:-}" = 1 ] || missing+=("Herdr session (HERDR_ENV=1)")

for bin in herdr jq claude codex pi agy git; do
  command -v "$bin" >/dev/null 2>&1 || missing+=("command: $bin")
done

skill_dirs=("$HOME/.agents/skills" "$HOME/.claude/skills")
[ -n "$project" ] && skill_dirs+=("$project/.agents/skills" "$project/.claude/skills")
for skill in ponytail graft grilling; do
  found=""
  for d in "${skill_dirs[@]}"; do
    [ -f "$d/$skill/SKILL.md" ] && found=1 && break
  done
  [ -n "$found" ] || missing+=("skill: $skill")
done
command -v graft >/dev/null 2>&1 || missing+=("command: graft")

if [ -n "$project" ]; then
  if ls "$project"/compose*.y*ml "$project"/docker-compose*.y*ml "$project"/Containerfile "$project"/Dockerfile >/dev/null 2>&1 \
     || grep -qsE '\b(podman|docker)\b' "$project/Makefile"; then
    command -v podman >/dev/null 2>&1 || command -v docker >/dev/null 2>&1 || missing+=("command: podman or docker")
  fi
  git -C "$project" worktree list >/dev/null 2>&1 || missing+=("git worktree in $project")
fi

if [ ${#missing[@]} -gt 0 ]; then
  printf 'preflight: FAIL\n'
  printf '  missing %s\n' "${missing[@]}"
  exit 1
fi
printf 'preflight: OK\n'
