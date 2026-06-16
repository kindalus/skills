#!/usr/bin/env python3
"""Validate this repository's Agent Skills layout.

The checker intentionally uses only the Python standard library so it can run in
GitHub Actions without installing dependencies.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", re.MULTILINE)
REFERENCE_RE = re.compile(
    r"(?<!https://)(?<!http://)(?:^|[\s(`\"\[])(?P<path>(?:references|scripts|assets)/[A-Za-z0-9][A-Za-z0-9_./-]*\.[A-Za-z0-9]+)",
    re.MULTILINE,
)
LOCAL_HOME_PREFIXES = ["/" + "Users" + "/", "/" + "home" + "/"]
ABSOLUTE_PATH_RE = re.compile(
    "(" + "|".join(re.escape(prefix) for prefix in LOCAL_HOME_PREFIXES) + r"|[A-Za-z]:\\\\)"
)
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{36}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}"),
]
SKIP_DIR_NAMES = {".git", "node_modules", "dist", "build", "__pycache__"}


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def parse_frontmatter(text: str) -> tuple[dict[str, object], str] | None:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None

    lines = match.group(1).splitlines()
    data: dict[str, object] = {}
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if line[:1].isspace() or ":" not in line:
            index += 1
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        if value in {"|", "|-", "|+", ">", ">-", ">+"}:
            block: list[str] = []
            index += 1
            while index < len(lines):
                next_line = lines[index]
                if next_line and not next_line[:1].isspace() and ":" in next_line:
                    break
                block.append(next_line[2:] if next_line.startswith("  ") else next_line.strip())
                index += 1
            data[key] = "\n".join(block).strip()
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        data[key] = value
        index += 1

    return data, text[match.end() :]


def validate_skill(skill_dir: Path, errors: list[str]) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        add_error(errors, f"{skill_dir.relative_to(ROOT)}: missing SKILL.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    if parsed is None:
        add_error(errors, f"{skill_md.relative_to(ROOT)}: missing YAML frontmatter")
        return

    data, body = parsed
    name = data.get("name")
    description = data.get("description")
    license_name = data.get("license")
    compatibility = data.get("compatibility")

    if not isinstance(name, str) or not name:
        add_error(errors, f"{skill_md.relative_to(ROOT)}: name is required")
    else:
        if len(name) > 64:
            add_error(errors, f"{skill_md.relative_to(ROOT)}: name exceeds 64 characters")
        if not NAME_RE.fullmatch(name):
            add_error(errors, f"{skill_md.relative_to(ROOT)}: invalid name '{name}'")
        if name != skill_dir.name:
            add_error(
                errors,
                f"{skill_md.relative_to(ROOT)}: name '{name}' must match directory '{skill_dir.name}'",
            )

    if not isinstance(description, str) or not description.strip():
        add_error(errors, f"{skill_md.relative_to(ROOT)}: description is required")
    elif len(description) > 1024:
        add_error(errors, f"{skill_md.relative_to(ROOT)}: description exceeds 1024 characters")

    if license_name is not None and not isinstance(license_name, str):
        add_error(errors, f"{skill_md.relative_to(ROOT)}: license must be a string")

    if compatibility is not None:
        if not isinstance(compatibility, str):
            add_error(errors, f"{skill_md.relative_to(ROOT)}: compatibility must be a string")
        elif len(compatibility) > 500:
            add_error(errors, f"{skill_md.relative_to(ROOT)}: compatibility exceeds 500 characters")

    if len(text.splitlines()) > 500:
        add_error(errors, f"{skill_md.relative_to(ROOT)}: SKILL.md should stay under 500 lines")

    if not body.strip():
        add_error(errors, f"{skill_md.relative_to(ROOT)}: body instructions are empty")

    seen_refs: set[str] = set()
    for ref_match in REFERENCE_RE.finditer(text):
        rel_path = ref_match.group("path")
        if rel_path in seen_refs:
            continue
        seen_refs.add(rel_path)
        if not (skill_dir / rel_path).exists():
            add_error(errors, f"{skill_md.relative_to(ROOT)}: referenced file does not exist: {rel_path}")


def iter_repo_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(ROOT).parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def validate_repo_files(errors: list[str]) -> None:
    required_files = ["README.md", "LICENSE", "skills.sh.json"]
    for rel_path in required_files:
        if not (ROOT / rel_path).is_file():
            add_error(errors, f"missing root file: {rel_path}")

    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if "__pycache__" in rel.parts or path.suffix == ".pyc":
            add_error(errors, f"generated Python artifact should not be committed: {rel}")

    for path in iter_repo_files():
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(ROOT)
        if rel == Path("scripts/validate_skills.py"):
            continue
        if ABSOLUTE_PATH_RE.search(text):
            add_error(errors, f"{rel}: contains a local absolute path")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                add_error(errors, f"{rel}: possible committed secret matched {pattern.pattern}")
                break


def validate_skills_sh_json(skill_names: set[str], errors: list[str]) -> None:
    config_path = ROOT / "skills.sh.json"
    if not config_path.exists():
        return

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add_error(errors, f"skills.sh.json: invalid JSON: {exc}")
        return

    groupings = config.get("groupings")
    if not isinstance(groupings, list) or not groupings:
        add_error(errors, "skills.sh.json: groupings must be a non-empty array")
        return

    for index, grouping in enumerate(groupings, start=1):
        if not isinstance(grouping, dict):
            add_error(errors, f"skills.sh.json: grouping {index} must be an object")
            continue
        title = grouping.get("title")
        skills = grouping.get("skills")
        if not isinstance(title, str) or not title.strip():
            add_error(errors, f"skills.sh.json: grouping {index} needs a non-empty title")
        if not isinstance(skills, list) or not skills:
            add_error(errors, f"skills.sh.json: grouping {index} needs at least one skill")
            continue
        for skill in skills:
            if not isinstance(skill, str):
                add_error(errors, f"skills.sh.json: grouping {index} contains a non-string skill")
            elif skill not in skill_names:
                add_error(errors, f"skills.sh.json: unknown skill '{skill}'")


def main() -> int:
    errors: list[str] = []

    if not SKILLS_DIR.is_dir():
        add_error(errors, "missing skills/ directory")
        skill_dirs: list[Path] = []
    else:
        skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
        if not skill_dirs:
            add_error(errors, "skills/ contains no skill directories")

    for skill_dir in skill_dirs:
        validate_skill(skill_dir, errors)

    skill_names = {path.name for path in skill_dirs}
    validate_repo_files(errors)
    validate_skills_sh_json(skill_names, errors)

    if errors:
        print("Skill validation failed:\n", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"OK: validated {len(skill_dirs)} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
