#!/usr/bin/env python3
"""Print one value of a JSON file, addressed by path and by record ID.

Usage: json_get.py FILE PATH [--key KEY] [--fields F1,F2] [--compact]

PATH is dot-separated. A segment is an object key, a list index, or
`name[ID]`, which selects the record of list `name` whose KEY (default `id`)
equals ID. Examples:

    json_get.py docs/specs/STATUS.json 'table[invoicing-03]'
    json_get.py docs/specs/STATUS.json 'table[invoicing-03].implementation.state'
    json_get.py docs/specs/STATUS.json 'notes.-1'
    json_get.py matrix.json 'rows[DP71-22-3]' --key requirement --fields status,notes

Exit codes: 0 found, 1 not found or ambiguous, 2 usage error. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

SEGMENT = re.compile(r"^(?P<name>[^\[\]]*)(?:\[(?P<id>[^\]]+)\])?$")


class NotFound(Exception):
    pass


def select(value: Any, path: str, key: str) -> Any:
    for raw in [p for p in path.split(".") if p] if path else []:
        match = SEGMENT.match(raw)
        if not match:
            raise NotFound(f"bad path segment: {raw}")
        name, record_id = match["name"], match["id"]
        if name:
            value = step(value, name)
        if record_id is not None:
            if not isinstance(value, list):
                raise NotFound(f"{raw}: not a list")
            found = [item for item in value if isinstance(item, dict) and str(item.get(key)) == record_id]
            if len(found) != 1:
                raise NotFound(f"{raw}: {len(found)} records with {key}={record_id}")
            value = found[0]
    return value


def step(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        if name not in value:
            raise NotFound(f"missing key: {name}")
        return value[name]
    if isinstance(value, list) and re.fullmatch(r"-?\d+", name):
        try:
            return value[int(name)]
        except IndexError as exc:
            raise NotFound(f"index out of range: {name}") from exc
    raise NotFound(f"cannot step into {type(value).__name__} with {name}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file")
    parser.add_argument("path", nargs="?", default="")
    parser.add_argument("--key", default="id", help="record key used by name[ID] (default: id)")
    parser.add_argument("--fields", help="comma-separated fields to keep from the selected object")
    parser.add_argument("--compact", action="store_true", help="one-line output")
    args = parser.parse_args(argv)
    with open(args.file, encoding="utf-8") as handle:
        data = json.load(handle)
    try:
        value = select(data, args.path, args.key)
    except NotFound as exc:
        print(f"json_get: {exc}", file=sys.stderr)
        return 1
    if args.fields:
        if not isinstance(value, dict):
            print("json_get: --fields needs an object", file=sys.stderr)
            return 2
        value = {f: value[f] for f in args.fields.split(",") if f in value}
    print(json.dumps(value, ensure_ascii=False, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
