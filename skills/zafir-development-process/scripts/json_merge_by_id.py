#!/usr/bin/env python3
"""Merge records into a JSON file's list by ID, printing only the changed lines.

Usage: json_merge_by_id.py TARGET SOURCE [--list PATH] [--key KEY]
                           [--keep F1,F2] [--indent N] [--write]

Each record of SOURCE's list (or SOURCE itself, when it is a list or a single
record) replaces the TARGET record with the same KEY (default `id`); a record
with a new KEY is appended. `--keep` preserves those fields of a matched TARGET
record (for a register: `--keep dependsOn,parallelAllowed,plannedFiles,areas`).
Unrelated keys and record order stay as they are.

Without `--write` it is a dry run. Either way it prints a zero-context diff of
the serialized TARGET and a one-line summary. `--write` replaces TARGET
atomically. A warning goes to stderr when the serialization would also
reformat TARGET.

Exit codes: 0 merged (or nothing to change), 1 invalid input. Standard library only.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import sys
import tempfile
from typing import Any


def records_of(value: Any, path: str) -> list[Any]:
    for name in [p for p in path.split(".") if p]:
        if not isinstance(value, dict) or name not in value:
            raise ValueError(f"missing list path: {path}")
        value = value[name]
    if not isinstance(value, list):
        raise ValueError(f"not a list: {path or '<root>'}")
    return value


def merge(target: Any, source: Any, path: str, key: str, keep: list[str]) -> tuple[Any, dict[str, int]]:
    merged = copy.deepcopy(target)
    rows = records_of(merged, path)
    if isinstance(source, dict) and key in source:
        incoming = [source]
    elif isinstance(source, list):
        incoming = source
    else:
        incoming = records_of(source, path)
    index: dict[str, int] = {}
    for position, row in enumerate(rows):
        if isinstance(row, dict) and key in row:
            if str(row[key]) in index:
                raise ValueError(f"duplicate {key} in target: {row[key]}")
            index[str(row[key])] = position
    counts = {"updated": 0, "added": 0, "unchanged": 0}
    seen: set[str] = set()
    for row in incoming:
        if not isinstance(row, dict) or key not in row:
            raise ValueError(f"source record without {key}: {json.dumps(row)[:80]}")
        record_id = str(row[key])
        if record_id in seen:
            raise ValueError(f"duplicate {key} in source: {record_id}")
        seen.add(record_id)
        if record_id in index:
            old = rows[index[record_id]]
            new = dict(row)
            for field in keep:
                if field in old:
                    new[field] = old[field]
                else:
                    new.pop(field, None)
            counts["unchanged" if new == old else "updated"] += 1
            rows[index[record_id]] = new
        else:
            rows.append(row)
            counts["added"] += 1
    return merged, counts


def serialize(value: Any, indent: int) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target")
    parser.add_argument("source")
    parser.add_argument("--list", default="table", help="dot path of the list in TARGET and SOURCE (default: table)")
    parser.add_argument("--key", default="id")
    parser.add_argument("--keep", default="", help="comma-separated fields kept from matched TARGET records")
    parser.add_argument("--indent", type=int, default=2)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        with open(args.target, encoding="utf-8") as handle:
            original_text = handle.read()
        target = json.loads(original_text)
        with open(args.source, encoding="utf-8") as handle:
            source = json.load(handle)
        merged, counts = merge(target, source, args.list, args.key, [f for f in args.keep.split(",") if f])
    except (OSError, ValueError) as exc:
        print(f"json_merge_by_id: {exc}", file=sys.stderr)
        return 1
    before, after = serialize(target, args.indent), serialize(merged, args.indent)
    if before != original_text:
        print("json_merge_by_id: warning: writing would also reformat TARGET", file=sys.stderr)
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), args.target, args.target,
                                     n=0, lineterm=""):
        print(line)
    print(f"merged by {args.key}: {counts['updated']} updated, {counts['added']} added, "
          f"{counts['unchanged']} unchanged{'' if args.write else ' (dry run)'}")
    if args.write and after != before:
        directory = os.path.dirname(os.path.abspath(args.target))
        fd, temp = tempfile.mkstemp(dir=directory, prefix=".json_merge_")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(after)
        os.chmod(temp, os.stat(args.target).st_mode & 0o7777)
        os.replace(temp, args.target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
