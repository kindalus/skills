#!/usr/bin/env python3
"""Validate a Zafir status register (schema 3.x) against REGISTER-SCHEMA.md.

Usage: validate_register.py [REGISTER]   (default: docs/specs/STATUS.json)

Checks the invariants and Zafir rules a file can show. What needs Git history or
a recorded decision is listed as not checked. Exit codes: 0 conforms, 1 errors,
2 not a v3 register (check a compatibility profile by reading, MIGRATION.md).
Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

DEFAULT_PATH = "docs/specs/STATUS.json"
TOP_LEVEL = ["schemaVersion", "title", "summary", "rules", "columns", "noteColumns", "table", "notes"]
ROW_REQUIRED = [
    "id", "name", "dependsOn", "components", "contexts", "spec", "implementation",
    "specifiable", "implementable", "assessments", "verification", "nextAction", "evidence",
]
FEATURE_REQUIRED = ["kind", "design", "architecture"]
SLICE_REQUIRED = ["kind", "feature", "tier", "parallelAllowed", "plannedFiles"]
DEFAULT_ENUMS = {
    "spec": ["proposed", "approved", "blocked", "n/a"],
    "implementation": ["not-started", "blocked", "done", "won't-do"],
    "verification": ["undefined", "defined", "passed", "failed"],
    "assessments": ["not-required", "pending", "resolved", "blocked"],
    "design": ["proposed", "approved", "deferred"],
    "architecture": ["not-yet-created", "consistent", "pending-change", "changed-and-approved"],
    "kind": ["feature", "slice", "investigation"],
    "tier": ["business", "security", "infrastructure"],
}
TERMINAL = {"done", "won't-do"}
GLOB_CHARS = set("*?[]{}")
NOT_CHECKED = [
    "I5 qualifiers encode no extra state (read them)",
    "I16 register committed atomically with its change (Git history)",
    "Z1 table order and edge removals (approved plan revisions)",
    "Z3 integration commit and combined-tree evidence (Git history)",
    "Z4 and Z6 recorded user decisions (notes, architecture.md)",
]


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, rule: str, where: str, message: str) -> None:
        self.errors.append(f"ERROR {rule} {where}: {message}")

    def warn(self, rule: str, where: str, message: str) -> None:
        self.warnings.append(f"WARN  {rule} {where}: {message}")


def state(row: dict, field: str) -> str | None:
    value = row.get(field)
    return value.get("state") if isinstance(value, dict) else None


def text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def declared_enums(columns: list) -> dict[str, list[str]]:
    enums = {key: list(values) for key, values in DEFAULT_ENUMS.items()}
    for column in columns:
        if not isinstance(column, dict):
            continue
        name = column.get("name")
        if isinstance(column.get("enum"), list):
            enums[name] = column["enum"]
        schema = column.get("objectSchema")
        if isinstance(schema, dict):
            inner = schema.get("*", schema)
            state_schema = inner.get("state") if isinstance(inner, dict) else None
            if isinstance(state_schema, dict) and isinstance(state_schema.get("enum"), list):
                enums[name] = state_schema["enum"]
    return enums


def valid_date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def normalized_path(path: object) -> bool:
    if not isinstance(path, str) or not path or path.startswith(("/", "./")) or "\\" in path:
        return False
    parts = path.rstrip("/").split("/")
    return all(part not in ("", ".", "..") for part in parts)


def find_cycle(ids: set[str], deps: dict[str, list[str]]) -> list[str] | None:
    colour = {node: 0 for node in ids}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = 1
        stack.append(node)
        for dep in deps.get(node, []):
            if dep not in colour:
                continue
            if colour[dep] == 1:
                return stack[stack.index(dep):] + [dep]
            if colour[dep] == 0:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        colour[node] = 2
        return None

    for node in ids:
        if colour[node] == 0:
            found = visit(node)
            if found:
                return found
    return None


def check_row_shape(row: dict, where: str, enums: dict, report: Report) -> None:
    for field in ROW_REQUIRED:
        if field not in row:
            report.error("contract", where, f"missing required field `{field}`")
    kind = row.get("kind")
    required = FEATURE_REQUIRED if kind == "feature" else SLICE_REQUIRED
    for field in required:
        if field not in row:
            report.error("zafir", where, f"missing Zafir field `{field}`")

    # I4: states belong to the declared enums.
    for field in ("spec", "implementation", "verification", "design", "architecture"):
        value = state(row, field)
        if field in row and value not in enums[field]:
            report.error("I4", where, f"`{field}.state` = {value!r} not in {enums[field]}")
    for name, assessment in (row.get("assessments") or {}).items():
        value = assessment.get("state") if isinstance(assessment, dict) else None
        if value not in enums["assessments"]:
            report.error("I4", where, f"`assessments.{name}.state` = {value!r} not in {enums['assessments']}")
    for field in ("kind", "tier"):
        if field in row and row[field] not in enums[field]:
            report.error("I4", where, f"`{field}` = {row[field]!r} not in {enums[field]}")

    # I13: components and contexts use declared vocabularies.
    for field in ("components", "contexts"):
        allowed = enums.get(field)
        values = row.get(field)
        if not isinstance(values, list):
            continue
        if allowed is None:
            report.warn("I13", where, f"no declared vocabulary for `{field}`")
            continue
        for value in values:
            if value not in allowed:
                report.error("I13", where, f"`{field}` value {value!r} not declared")

    # I14: dates.
    for field in ("spec", "implementation", "design", "architecture"):
        value = row.get(field)
        if isinstance(value, dict) and "decidedOn" in value and not valid_date(value["decidedOn"]):
            report.error("I14", where, f"`{field}.decidedOn` = {value['decidedOn']!r} is not YYYY-MM-DD")


def check_readiness(row: dict, where: str, by_id: dict, report: Report) -> None:
    impl = state(row, "implementation")
    specifiable = row.get("specifiable") or {}
    implementable = row.get("implementable") or {}

    # I12: every negative readiness has a reason.
    for name, gate in (("specifiable", specifiable), ("implementable", implementable)):
        if gate.get("value") is False and not text(gate.get("reason")):
            report.error("I12", where, f"`{name}` is false without a reason")

    # I6: implementable=true satisfies every implementation gate.
    if implementable.get("value") is True:
        if state(row, "spec") not in ("approved", "n/a"):
            report.error("I6", where, "implementable but spec is not approved or n/a")
        for dep in row.get("dependsOn") or []:
            if dep != row.get("id") and dep in by_id and state(by_id[dep], "implementation") != "done":
                report.error("I6", where, f"implementable but dependency {dep} is not done")
        for name, assessment in (row.get("assessments") or {}).items():
            if isinstance(assessment, dict) and assessment.get("state") not in ("resolved", "not-required"):
                report.error("I6", where, f"implementable but assessment {name} is {assessment.get('state')!r}")
        if state(row, "verification") not in ("defined", "passed"):
            report.error("I6", where, "implementable but verification is not defined or passed")
        if impl != "not-started":
            report.error("I6", where, f"implementable but implementation is {impl!r}")
        if row.get("kind") == "feature":
            report.error("zafir", where, "feature rows are never implementable (they close in Step 6)")

    if impl == "done":
        evidence = row.get("evidence") or {}
        if implementable.get("value") is not False:
            report.error("I7", where, "done but implementable is not false")
        if state(row, "verification") != "passed":
            report.error("I8", where, "done but verification is not passed")
        if not evidence.get("commits"):
            report.error("I9", where, "done without an immutable revision in `evidence.commits`")
        if not evidence.get("tests"):
            report.error("I9", where, "done without test evidence in `evidence.tests`")
    if impl in TERMINAL and text(row.get("nextAction")) != "None":
        report.error("contract", where, f"terminal item has nextAction {row.get('nextAction')!r}, expected 'None'")


def check_blockers(row: dict, where: str, noted: set[str], report: Report) -> None:
    blocked = [f for f in ("spec", "implementation") if state(row, f) == "blocked"]
    blocked += [f"assessments.{n}" for n, a in (row.get("assessments") or {}).items()
                if isinstance(a, dict) and a.get("state") == "blocked"]
    if blocked:
        named = (
            any(text((row.get(f) or {}).get("qualifier")) for f in ("spec", "implementation"))
            or text((row.get("implementable") or {}).get("reason"))
            or text(row.get("nextAction")) not in ("", "None")
        )
        if not named:
            report.error("I10", where, f"{', '.join(blocked)} blocked without a concrete blocker")
    if state(row, "implementation") == "won't-do":
        if not text((row.get("implementation") or {}).get("qualifier")) and row["id"] not in noted:
            report.error("I11", where, "won't-do without a recorded decision or successor")


def check_zafir_row(row: dict, where: str, by_id: dict, report: Report) -> None:
    kind = row.get("kind")
    if kind in ("slice", "investigation"):
        feature = row.get("feature")
        owner = by_id.get(feature)
        if owner is None or owner.get("kind") != "feature":
            report.error("zafir", where, f"owning feature {feature!r} is not a feature row")
        elif not re.fullmatch(re.escape(feature) + r"-\d+", row["id"]):
            report.warn("zafir", where, f"id does not follow `{feature}-NN`")
        if feature in (row.get("dependsOn") or []):
            report.error("zafir", where, "depends on its own feature row")

        # Z6: permission and envelope.
        parallel = row.get("parallelAllowed")
        planned = row.get("plannedFiles")
        if "parallelAllowed" in row and not isinstance(parallel, bool):
            report.error("Z6", where, "`parallelAllowed` is not a boolean")
        if "plannedFiles" in row and not isinstance(planned, list):
            report.error("Z6", where, "`plannedFiles` is not a list")
        if parallel is True and isinstance(planned, list):
            if not planned:
                report.error("Z6", where, "parallelAllowed with empty `plannedFiles`")
            if len(set(planned)) != len(planned):
                report.error("Z6", where, "duplicate paths in `plannedFiles`")
            for path in planned:
                if not normalized_path(path) or str(path).endswith("/"):
                    report.error("Z6", where, f"`plannedFiles` path {path!r} is not normalized")
                if GLOB_CHARS & set(str(path)):
                    report.error("Z6", where, f"`plannedFiles` path {path!r} is a glob")
        for area in row.get("areas") or []:
            if not normalized_path(area) or not str(area).endswith("/"):
                report.error("areas", where, f"area {area!r} must be a normalized directory ending in /")

        # Z3: done requires base, a recorded review, and base in the evidence.
        if state(row, "implementation") == "done":
            evidence = row.get("evidence") or {}
            if not row.get("base"):
                report.error("Z3", where, "done without `base`")
            elif row["base"] not in (evidence.get("commits") or []):
                report.error("Z3", where, "`base` is not in `evidence.commits`")
            if not evidence.get("reviews"):
                report.error("Z3", where, "done without a recorded review in `evidence.reviews`")

    placeholders = row.get("placeholders") or {}
    for entry in placeholders.get("introduces") or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not name:
            report.error("placeholders", where, "introduced placeholder without a name")
            continue
        for field in ("standsInFor", "livesAt", "security"):
            if field not in entry:
                report.error("placeholders", where, f"placeholder {name!r} lacks `{field}`")
        if not entry.get("replacedBy"):
            report.warn("placeholders", where, f"placeholder {name!r} has no `replacedBy` (a finding)")
    for field in ("reuses", "replaces"):
        for value in placeholders.get(field) or []:
            if not isinstance(value, str):
                report.error("placeholders", where, f"`placeholders.{field}` holds a non-name {value!r}")
    for entry in placeholders.get("kept") or []:
        if not isinstance(entry, dict) or not text(entry.get("name")) or not text(entry.get("decision")):
            report.error("Z4", where, f"kept placeholder {entry!r} needs `name` and `decision`")


def active_placeholders(rows: list[dict]) -> dict[str, tuple[dict, dict]]:
    introduced = {}
    for row in rows:
        for entry in (row.get("placeholders") or {}).get("introduces") or []:
            if isinstance(entry, dict) and entry.get("name"):
                introduced[entry["name"]] = (row, entry)
    replaced = {
        name
        for row in rows
        if state(row, "implementation") == "done"
        for name in (row.get("placeholders") or {}).get("replaces") or []
    }
    kept = {
        entry.get("name")
        for row in rows
        for entry in (row.get("placeholders") or {}).get("kept") or []
        if isinstance(entry, dict)
    }
    return {name: value for name, value in introduced.items() if name not in replaced and name not in kept}


def validate(register: dict) -> Report:
    report = Report()
    for key in TOP_LEVEL:
        if key not in register:
            report.error("contract", "document", f"missing top-level field `{key}`")
    rows = [row for row in register.get("table") or [] if isinstance(row, dict)]
    notes = register.get("notes") or []
    enums = declared_enums(register.get("columns") or [])
    for field in ("components", "contexts"):
        for value in enums.get(field) or []:
            if isinstance(value, str) and value.startswith("<"):
                report.warn("I13", "columns", f"`{field}` vocabulary still holds the template value {value!r}")

    # I1: unique ids.
    by_id: dict[str, dict] = {}
    for index, row in enumerate(rows):
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            report.error("I1", f"table[{index}]", "row without an id")
            continue
        if row_id in by_id:
            report.error("I1", row_id, "duplicate id")
        by_id[row_id] = row

    # I15 and the note contract; ids named by notes count as recorded decisions (I11).
    item_field = "items"
    for column in register.get("noteColumns") or []:
        if isinstance(column, dict) and column.get("name") in ("items", "slices"):
            item_field = column["name"]
    noted: set[str] = set()
    for index, note in enumerate(notes):
        where = f"notes[{index}]"
        if not isinstance(note, dict):
            report.error("contract", where, "note is not an object")
            continue
        for field in ("title", "body"):
            if not text(note.get(field)):
                report.error("contract", where, f"note lacks `{field}`")
        if "date" in note and not valid_date(note["date"]):
            report.error("I14", where, f"date {note['date']!r} is not YYYY-MM-DD")
        for item in note.get(item_field) or []:
            if item not in by_id:
                report.error("I15", where, f"references unknown id {item!r}")
            noted.add(item)

    # I2 and I3: dependencies.
    deps = {}
    for row_id, row in by_id.items():
        deps[row_id] = [d for d in row.get("dependsOn") or [] if isinstance(d, str)]
        for dep in deps[row_id]:
            if dep == row_id:
                report.error("I2", row_id, "depends on itself")
            elif dep not in by_id:
                report.error("I2", row_id, f"dependency {dep!r} does not exist")
    cycle = find_cycle(set(by_id), deps)
    if cycle:
        report.error("I3", cycle[0], "dependency cycle " + " -> ".join(cycle))

    for row_id, row in by_id.items():
        check_row_shape(row, row_id, enums, report)
        check_readiness(row, row_id, by_id, report)
        check_blockers(row, row_id, noted, report)
        check_zafir_row(row, row_id, by_id, report)

    # Z2: at most one pending architecture change.
    pending = [r["id"] for r in by_id.values() if r.get("kind") == "feature" and state(r, "architecture") == "pending-change"]
    if len(pending) > 1:
        report.error("Z2", ", ".join(pending), "more than one feature with architecture pending-change")

    # Z5 (and Z4 through it): a done feature has closed slices and no undecided active placeholder.
    active = active_placeholders(list(by_id.values()))
    for feature in (r for r in by_id.values() if r.get("kind") == "feature" and state(r, "implementation") == "done"):
        for row in by_id.values():
            if row.get("feature") == feature["id"] and state(row, "implementation") not in TERMINAL:
                report.error("Z5", feature["id"], f"done while slice {row['id']} is {state(row, 'implementation')!r}")
        for name, (owner, entry) in active.items():
            if owner.get("feature") == feature["id"]:
                rule = "Z4" if entry.get("security") else "Z5"
                report.error(rule, feature["id"], f"done with active placeholder {name!r} not kept by decision")
    return report


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else DEFAULT_PATH)
    try:
        register = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 1
    version = str(register.get("schemaVersion", ""))
    if not version.startswith("3."):
        print(f"{path}: schemaVersion {version!r} is not 3.x; check a compatibility profile by reading (MIGRATION.md).")
        return 2
    report = validate(register)
    for line in report.errors + report.warnings:
        print(line)
    print("Not checked by this script: " + "; ".join(NOT_CHECKED) + ".")
    print(f"{path}: {len(report.errors)} error(s), {len(report.warnings)} warning(s).")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
