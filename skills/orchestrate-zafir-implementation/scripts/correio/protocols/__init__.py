"""Versioned protocols: ``protocols/<name>/<version>.py``.

A published version is immutable. ``PUBLISHED.json`` pins the sha256 of every published module, and the
loader refuses a module whose bytes differ: to change behaviour, add the next version and pin it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
from types import ModuleType

HERE = pathlib.Path(__file__).resolve().parent
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
INTERFACE = ("TYPES", "prepare", "validate_send", "validate_receipt", "project", "check", "prompt", "close_condition")
_cache: dict[tuple[str, str], ModuleType] = {}


class ProtocolMissing(LookupError):
    pass


def published() -> dict[str, str]:
    return json.loads((HERE / "PUBLISHED.json").read_text(encoding="utf-8"))


def path_of(name: str, version: str) -> pathlib.Path:
    if not NAME_RE.match(name) or not VERSION_RE.match(version):
        raise ProtocolMissing(f"invalid protocol {name!r} or version {version!r}")
    return HERE / name / f"{version}.py"


def load(name: str, version: str) -> ModuleType:
    key = (name, version)
    if key in _cache:
        return _cache[key]
    path = path_of(name, version)
    if not path.is_file():
        raise ProtocolMissing(f"no protocol module {name}/{version}")
    pinned = published().get(f"{name}/{version}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if pinned != actual:
        raise ProtocolMissing(f"protocol {name}/{version} is not published with these bytes "
                              f"(pinned {pinned}, found {actual}); publish a new version instead of editing one")
    spec = importlib.util.spec_from_file_location(f"correio_protocol_{name}_{version.replace('.', '_')}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [attr for attr in INTERFACE if not hasattr(module, attr)]
    if missing:
        raise ProtocolMissing(f"protocol {name}/{version} lacks {missing}")
    _cache[key] = module
    return module
