#!/usr/bin/env bash
# Fail-closed environment check for orchestrate-zafir-implementation.
# Usage: preflight.sh [--project <repo>] [--check]
# With --project, also lists /.worktrees/ in the repository's .git/info/exclude when absent
# (references/naming.md); --check only reports it as missing. .gitignore is never touched.
# Exit 0 when every requirement is present; exit 1 listing what is missing.
set -u

project=""
check=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project) project="${2:-}"; shift 2 || shift ;;
    --check) check=1; shift ;;
    *) printf 'preflight: unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

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
  if git -C "$project" worktree list >/dev/null 2>&1; then
    # The common directory is the main checkout's .git, also when --project names a linked worktree.
    common="$(git -C "$project" rev-parse --path-format=absolute --git-common-dir)"
    exclude="$common/info/exclude"
    if ! grep -qsxE '/?\.worktrees/?' "$exclude"; then
      if [ -n "$check" ]; then
        missing+=("/.worktrees/ in $exclude")
      else
        mkdir -p "$common/info"
        [ -s "$exclude" ] && [ -n "$(tail -c 1 "$exclude")" ] && printf '\n' >>"$exclude"
        printf '/.worktrees/\n' >>"$exclude"
        printf 'preflight: added /.worktrees/ to %s\n' "$exclude"
      fi
    fi
  else
    missing+=("git worktree in $project")
  fi
fi

if [ ${#missing[@]} -gt 0 ]; then
  printf 'preflight: FAIL\n'
  printf '  missing %s\n' "${missing[@]}"
  exit 1
fi
printf 'preflight: OK\n'
