#!/usr/bin/env python3
"""Deterministic control plane for implement-with-swarm.

This tool moves bytes and verifies facts. It never decides product scope, accepts a
failing gate, answers a permission prompt, or replaces an agent on its own.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import tempfile
import uuid
from typing import Any, Iterable

VERSION = "2.4.1"
AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
PREFIX_RE = re.compile(r"^[a-z][a-z0-9_-]{0,20}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BAD_MODEL_CHARS = set(";&|`$<>\\*?[]{}()!\n\r\x00")
EFFORTS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
HARNESSES = {"pi", "claude", "agy"}
# Claude Code's --effort accepts a narrower set than Pi's --thinking.
HARNESS_EFFORTS = {"claude": {"low", "medium", "high", "xhigh", "max"}}
EVENT_TYPES = {
    "BOOT", "AGENT_READY", "SWARM_READY", "TASK_ASSIGN", "REVIEW_REQUEST",
    "CHANGES_REQUESTED", "APPROVED", "TASK_INTEGRATED", "LEASE_REQUEST", "LEASE_RELEASE",
    "BLOCKED", "MODEL_ERROR", "MODEL_REPLACE", "PAUSE", "RESUME", "CANCEL",
    "SLICE_READY", "SLICE_ACCEPTED", "SLICE_CHANGES_REQUESTED", "PROGRESS",
}
MAX_JSON_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
BOUND_EVENT_FIELDS = {
    "TASK_ASSIGN": {"taskId", "assignmentId", "revision"},
    "REVIEW_REQUEST": {"taskId", "assignmentId", "revision", "candidateSha"},
    "CHANGES_REQUESTED": {"taskId", "assignmentId", "revision", "candidateSha"},
    "APPROVED": {"taskId", "assignmentId", "revision", "candidateSha"},
    "TASK_INTEGRATED": {"taskId", "assignmentId", "revision", "candidateSha"},
    "LEASE_REQUEST": {"candidateSha"},
    "LEASE_RELEASE": {"candidateSha"},
    "SLICE_READY": {"candidateSha"},
    "SLICE_ACCEPTED": {"candidateSha"},
    "SLICE_CHANGES_REQUESTED": {"candidateSha"},
}


class SwarmError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: os.PathLike[str] | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(path: os.PathLike[str] | str, *, exists: bool = False) -> pathlib.Path:
    p = pathlib.Path(path).expanduser().resolve(strict=exists)
    if "\x00" in str(p):
        raise SwarmError("path contains NUL")
    return p


def beneath(path: pathlib.Path, root: pathlib.Path, *, allow_root: bool = True) -> bool:
    return (allow_root and path == root) or root in path.parents


def require_beneath(path: os.PathLike[str] | str, root: os.PathLike[str] | str,
                    *, allow_root: bool = True, label: str = "path") -> pathlib.Path:
    p, r = canonical(path), canonical(root)
    if not beneath(p, r, allow_root=allow_root):
        raise SwarmError(f"{label} is outside allowed root: {p}")
    return p


def load_json(path: os.PathLike[str] | str) -> Any:
    p = pathlib.Path(path)
    try:
        size = p.stat().st_size
        if size > MAX_JSON_BYTES:
            raise SwarmError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {p}")
        with p.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SwarmError(f"cannot read JSON {p}: {exc}") from exc


def _fsync_dir(path: pathlib.Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_immutable(path: os.PathLike[str] | str, data: bytes, mode: int = 0o600,
                    *, same_ok: bool = False) -> bool:
    """Create path once. Return False only when an identical existing file is allowed."""
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if (same_ok and not target.is_symlink() and target.is_file()
                and stat.S_ISREG(target.lstat().st_mode) and target.read_bytes() == data):
            return False
        raise SwarmError(f"immutable target already exists: {target}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    tmp = pathlib.Path(tmp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError as exc:
            raise SwarmError(f"immutable target raced: {target}") from exc
        _fsync_dir(target.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    return True


def write_json_immutable(path: os.PathLike[str] | str, value: Any, *, same_ok: bool = False) -> bool:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    return write_immutable(path, data, same_ok=same_ok)


def write_json_mutable(path: os.PathLike[str] | str, value: Any, mode: int = 0o600) -> None:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    tmp = pathlib.Path(tmp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        _fsync_dir(target.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def ensure_private_dir(path: pathlib.Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise SwarmError(f"not a directory: {path}")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SwarmError(f"run directory is accessible by group/other: {path}")
    else:
        path.mkdir(parents=True, mode=0o700)
    os.chmod(path, 0o700)


def run(argv: list[str], *, cwd: pathlib.Path | None = None, timeout: float = 30,
        check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SwarmError(f"command failed to start: {argv[0]}: {exc}") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise SwarmError(f"command exited {result.returncode}: {argv!r}: {detail}")
    return result


def herdr(*args: str, timeout: float = 30) -> dict[str, Any]:
    result = run(["herdr", *args], timeout=timeout)
    try:
        value = json.loads(result.stdout)
        return value["result"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SwarmError(f"unexpected Herdr JSON for {args!r}") from exc


def parse_model_triple(raw: str) -> tuple[str, str, str]:
    if not isinstance(raw, str):
        raise SwarmError("model configuration must be a string")
    parts = raw.split()
    if len(parts) != 3:
        raise SwarmError("model configuration must be: harness model thinking_effort")
    harness, model, effort = parts
    if harness not in HARNESSES:
        raise SwarmError(f"unsupported harness: {harness}")
    if not model or model.startswith("-") or any(ch in BAD_MODEL_CHARS or ord(ch) < 32 for ch in model):
        raise SwarmError("unsafe model identifier")
    if effort not in HARNESS_EFFORTS.get(harness, EFFORTS):
        raise SwarmError(f"unsupported thinking effort for {harness}: {effort}")
    return harness, model, effort


# Ordered: the first hint found in the lowercased model identifier names the family.
FAMILY_HINTS = (("claude", "anthropic"), ("anthropic", "anthropic"), ("opus", "anthropic"),
                ("sonnet", "anthropic"), ("haiku", "anthropic"), ("fable", "anthropic"),
                ("gemini", "google"), ("google", "google"), ("gpt", "openai"),
                ("openai", "openai"), ("codex", "openai"))


def model_family(triple: str) -> str:
    """Coarse vendor family used to keep the reviewer independent of the implementers."""
    harness, model, _effort = parse_model_triple(triple)
    if harness == "claude":
        return "anthropic"
    if harness == "agy":
        return "google"
    text = model.lower()
    for hint, family in FAMILY_HINTS:
        if hint in text:
            return family
    return text.split("/", 1)[0]


# Owner decision 2026-10-02: the one same-family reviewer ever accepted, and only through a
# reviewer MODEL_REPLACE whose payload.reviewerFallback names the reviewer's quota MODEL_ERROR.
REVIEWER_QUOTA_FALLBACK = ("pi", "openai-codex/gpt-6.1-sol", "high")


def model_args(triple: str) -> tuple[str, list[str]]:
    harness, model, effort = parse_model_triple(triple)
    args = ["--model", model, "--thinking" if harness == "pi" else "--effort", effort]
    if harness in {"agy", "claude"}:
        # agy and claude prompt for tool permissions; the swarm runs them non-interactively.
        args.append("--dangerously-skip-permissions")
    return harness, args


CODER_LETTERS = "ab"
ROSTER_KEYS = {"principal", "reviewer", "coders"}


def roster(launch: dict[str, Any]) -> str:
    """Return the coder letters ('', 'a' or 'ab'). The team is always one Principal and exactly
    one reviewer; coders are optional (0-2) and absent means 0 (Principal alone with the reviewer)."""
    if "tier" in launch:
        raise SwarmError("tier was removed in 2.0.0; set roster.coders (0 = Principal alone)")
    value = launch.get("roster", {})
    if not isinstance(value, dict) or not set(value) <= ROSTER_KEYS:
        raise SwarmError("roster may contain only principal, reviewer and coders")
    for key in ("principal", "reviewer"):
        if key in value and (type(value[key]) is not int or value[key] != 1):
            raise SwarmError(f"roster.{key} must be exactly 1")
    count = value.get("coders", 0)
    if type(count) is not int or not 0 <= count <= len(CODER_LETTERS):
        raise SwarmError(f"roster.coders must be an integer from 0 to {len(CODER_LETTERS)}")
    return CODER_LETTERS[:count]


def principal_name(launch: dict[str, Any]) -> str:
    return f"{launch['prefix']}-principal"


def reviewer_name(launch: dict[str, Any]) -> str:
    return f"{launch['prefix']}-reviewer"


def coder_names(launch: dict[str, Any]) -> list[str]:
    return [f"{launch['prefix']}-coder-{letter}" for letter in roster(launch)]


def model_roles(launch: dict[str, Any]) -> set[str]:
    return {"principal", "reviewer"} | ({"coders"} if roster(launch) else set())


def require_solo_team(value: Any) -> None:
    """Since 2.4.0 a new launch contract is always one Principal and one reviewer (owner decision
    2026-10-14). Only new contracts pass here (init, doctor, bootstrap responsible); a reloaded
    launch.json goes through validate_launch alone, so roster() and the coder machinery stay as they were."""
    if not isinstance(value, dict):
        return  # validate_launch reports the shape
    team = value.get("roster", {})
    if isinstance(team, dict) and team.get("coders", 0) != 0:
        raise SwarmError("roster.coders must be 0 since 2.4.0: the team is always Principal and reviewer "
                         "(owner decision 2026-10-14)")
    if isinstance(value.get("models"), dict) and "coders" in value["models"]:
        raise SwarmError("models.coders is not allowed since 2.4.0: the team is always Principal and "
                         "reviewer (owner decision 2026-10-14)")


def validate_new_launch(value: Any, expected_run_dir: pathlib.Path | None = None) -> dict[str, Any]:
    """validate_launch for a contract supplied by the caller rather than reloaded from a run."""
    require_solo_team(value)
    return validate_launch(value, expected_run_dir)


def validate_launch(value: Any, expected_run_dir: pathlib.Path | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SwarmError("launch contract must be an object")
    required = {"runId", "prefix", "sliceId", "specPath", "repoPath", "baseSha", "slice",
                "responsible", "worktreeRoot", "runDir", "skillRoot", "ponytailPath",
                "models", "processPaths"}
    missing = sorted(required - value.keys())
    if missing:
        raise SwarmError(f"launch contract missing: {', '.join(missing)}")
    try:
        parsed_run_id = uuid.UUID(value["runId"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise SwarmError("runId is not a UUID") from exc
    if str(parsed_run_id) != value["runId"]:
        raise SwarmError("runId must use canonical lowercase UUID form")
    if not isinstance(value["prefix"], str) or not PREFIX_RE.fullmatch(value["prefix"]):
        raise SwarmError("prefix must match Herdr naming rules and be <=21 characters")
    if not isinstance(value["sliceId"], str) or not value["sliceId"].strip():
        raise SwarmError("sliceId must be a nonempty string")
    if not isinstance(value["baseSha"], str) or not SHA_RE.fullmatch(value["baseSha"]):
        raise SwarmError("baseSha must be a full lowercase Git SHA")
    roles = model_roles(value)  # also validates the roster
    if not isinstance(value["models"], dict) or set(value["models"]) != roles:
        raise SwarmError(f"models must contain exactly {', '.join(sorted(roles))}")
    for triple in value["models"].values():
        parse_model_triple(triple)
    review_family = model_family(value["models"]["reviewer"])
    if any(model_family(value["models"][key]) == review_family for key in roles - {"reviewer"}):
        raise SwarmError("the reviewer must use a different model family from the implementers")
    responsible = value["responsible"]
    if not isinstance(responsible, dict) or not AGENT_RE.fullmatch(str(responsible.get("agent", ""))):
        raise SwarmError("responsible.agent is invalid")
    for key in ("paneId", "workspaceId", "session"):
        if not isinstance(responsible.get(key), str) or not responsible[key]:
            raise SwarmError(f"responsible.{key} is required")
    slice_value = value["slice"]
    if not isinstance(slice_value, dict) or not all(isinstance(slice_value.get(k), str) and slice_value[k]
                                                   for k in ("branch", "worktree")):
        raise SwarmError("slice.branch and slice.worktree are required")
    absolute_keys = ("specPath", "repoPath", "worktreeRoot", "runDir", "skillRoot", "ponytailPath")
    if (any(not isinstance(value[key], str) or not pathlib.Path(value[key]).is_absolute()
            for key in absolute_keys) or not pathlib.Path(slice_value["worktree"]).is_absolute()):
        raise SwarmError("all launch paths must be absolute")
    run_dir = canonical(value["runDir"])
    repo = canonical(value["repoPath"], exists=True)
    worktree_root = canonical(value["worktreeRoot"])
    slice_worktree = canonical(slice_value["worktree"])
    if expected_run_dir is not None and run_dir != canonical(expected_run_dir):
        raise SwarmError("contract runDir differs from requested run directory")
    pairs = ((run_dir, repo), (run_dir, worktree_root), (repo, worktree_root))
    if any(beneath(left, right) or beneath(right, left) for left, right in pairs):
        raise SwarmError("runDir, repository, and worktreeRoot must be disjoint")
    if not beneath(slice_worktree, worktree_root, allow_root=False):
        raise SwarmError("slice worktree must be below worktreeRoot")
    spec_path = canonical(value["specPath"], exists=True)
    skill_root = canonical(value["skillRoot"], exists=True)
    ponytail_path = canonical(value["ponytailPath"], exists=True)
    if not spec_path.is_file() or not beneath(spec_path, repo, allow_root=False):
        raise SwarmError("specPath must be a repository file")
    if not skill_root.is_dir() or not (skill_root / "SKILL.md").is_file():
        raise SwarmError("skillRoot must contain SKILL.md")
    if not ponytail_path.is_file():
        raise SwarmError("ponytailPath must be a file")
    paths = value["processPaths"]
    if (not isinstance(paths, list) or not paths
            or any(not isinstance(p, str) or not pathlib.Path(p).is_absolute() for p in paths)):
        raise SwarmError("processPaths must be a nonempty absolute-path string array")
    missing_paths = [p for p in paths if not pathlib.Path(p).is_file()]
    if missing_paths:
        raise SwarmError(f"missing processPaths: {missing_paths}")
    return value


def load_launch(run_dir: os.PathLike[str] | str) -> tuple[pathlib.Path, dict[str, Any]]:
    root = canonical(run_dir, exists=True)
    marker_path = root / "automation.json"
    if not marker_path.is_file():
        raise SwarmError("run is not owned by the deterministic control plane")
    marker = load_json(marker_path)
    launch_path = root / "launch.json"
    launch = validate_launch(load_json(launch_path), root)
    if (marker.get("schemaVersion") != 1 or marker.get("runId") != launch["runId"]
            or marker.get("automationVersion") != VERSION):
        raise SwarmError("automation ownership marker mismatch")
    supervisor = load_json(root / "supervisor.json")
    if not isinstance(supervisor, dict):
        raise SwarmError("supervisor registry is invalid")
    expected_names = {"swarmctl.py", "swarmcore.py", "swarmbootstrap.py", "swarmd.py"}
    hashes = supervisor.get("runtimeHashes")
    if (supervisor.get("runId") != launch["runId"] or not isinstance(hashes, dict)
            or set(hashes) != expected_names):
        raise SwarmError("runtime hash registry is invalid")
    for name, digest in hashes.items():
        runtime_path = root / "runtime" / name
        if (not runtime_path.is_file() or runtime_path.is_symlink()
                or not SHA256_RE.fullmatch(str(digest)) or sha256_file(runtime_path) != digest):
            raise SwarmError(f"run-pinned runtime hash mismatch: {name}")
    return root, launch


def allowed_agents(launch: dict[str, Any]) -> set[str]:
    return {launch["responsible"]["agent"], principal_name(launch), reviewer_name(launch),
            *coder_names(launch)}


def parent_of(agent: str, launch: dict[str, Any]) -> str | None:
    if agent == principal_name(launch):
        return launch["responsible"]["agent"]
    if agent == reviewer_name(launch) or agent in coder_names(launch):
        return principal_name(launch)
    return None


def validate_route(event_type: str, sender: str, recipient: str, launch: dict[str, Any]) -> None:
    if not all(isinstance(value, str) for value in (event_type, sender, recipient)):
        raise SwarmError("event type, sender, and recipient must be strings")
    if event_type not in EVENT_TYPES:
        raise SwarmError(f"unknown event type: {event_type}")
    agents = allowed_agents(launch)
    if sender not in agents or recipient not in agents:
        raise SwarmError("event sender or recipient is not part of this run")
    responsible, principal = launch["responsible"]["agent"], principal_name(launch)
    reviewer, coders = reviewer_name(launch), set(coder_names(launch))
    implementers = {principal, *coders}
    allowed = False
    if event_type in {"BOOT", "PAUSE", "RESUME", "CANCEL"}:
        allowed = parent_of(recipient, launch) == sender
    elif event_type in {"AGENT_READY", "BLOCKED", "MODEL_ERROR", "PROGRESS"}:
        allowed = recipient == parent_of(sender, launch)
    elif event_type == "MODEL_REPLACE":
        allowed = sender == responsible and recipient == principal
    elif event_type in {"SWARM_READY", "SLICE_READY", "LEASE_REQUEST", "LEASE_RELEASE"}:
        allowed = sender == principal and recipient == responsible
    elif event_type in {"SLICE_ACCEPTED", "SLICE_CHANGES_REQUESTED"}:
        allowed = sender == responsible and recipient == principal
    elif event_type == "TASK_ASSIGN":
        # The Principal assigns to coders and records its own tasks by assigning to itself.
        allowed = sender == principal and recipient in implementers
    elif event_type == "TASK_INTEGRATED":
        allowed = sender == principal and recipient in coders
    elif event_type == "REVIEW_REQUEST":
        # Implementers (and the responsible agent in direct-execution fallback) queue at the
        # reviewer; a coder also sends a copy to the Principal.
        allowed = ((sender in implementers or sender == responsible) and recipient == reviewer
                   or sender in coders and recipient == principal)
    elif event_type in {"APPROVED", "CHANGES_REQUESTED"}:
        # Verdict to the implementer, with a copy to the Principal.
        allowed = sender == reviewer and (recipient in implementers or recipient == responsible)
    if not allowed:
        raise SwarmError(f"invalid {event_type} route: {sender} -> {recipient}")


def reviewer_quota_incident(root: pathlib.Path, launch: dict[str, Any], event_id: Any) -> dict[str, Any]:
    """Return the reviewer's quota-exhausted MODEL_ERROR named by ``event_id``.

    The event is immutable, so this check gives the same answer on every revalidation; it skips the
    sender-generation check because the reviewer's generation is bumped by the replacement itself."""
    try:
        canonical_id = str(uuid.UUID(event_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SwarmError("reviewerFallback must be the MODEL_ERROR event UUID") from exc
    if canonical_id != event_id:
        raise SwarmError("reviewerFallback must use canonical lowercase UUID form")
    for recipient in (principal_name(launch), launch["responsible"]["agent"]):
        path = root / "inbox" / recipient / f"{event_id}.json"
        if not path.is_file():
            continue
        event = load_json(path)
        payload = event.get("payload") if isinstance(event, dict) else None
        if (not isinstance(payload, dict) or event.get("id") != event_id
                or event.get("runId") != launch["runId"] or event.get("type") != "MODEL_ERROR"
                or event.get("to") != recipient):
            break
        validate_route("MODEL_ERROR", event.get("from"), recipient, launch)
        if payload.get("role") != "reviewer" or payload.get("classification") != "quota-exhausted":
            raise SwarmError("reviewerFallback requires a MODEL_ERROR with role reviewer and "
                             "classification quota-exhausted")
        return event
    raise SwarmError("reviewerFallback does not name a MODEL_ERROR of this run")


def validate_model_replace(payload: dict[str, Any], launch: dict[str, Any],
                           root: pathlib.Path | None) -> None:
    role, configuration, incident = (payload.get("role"), payload.get("configuration"),
                                     payload.get("incidentId"))
    roles = model_roles(launch)
    if role not in roles:
        raise SwarmError(f"MODEL_REPLACE role must be one of: {', '.join(sorted(roles))}")
    triple = parse_model_triple(configuration)
    if not isinstance(incident, str) or not incident.strip() or len(incident) > 128:
        raise SwarmError("MODEL_REPLACE requires payload.incidentId")
    if "reviewerFallback" in payload:
        if role != "reviewer" or triple != REVIEWER_QUOTA_FALLBACK:
            raise SwarmError("reviewerFallback is valid only for a reviewer replacement with exactly: "
                             + " ".join(REVIEWER_QUOTA_FALLBACK))
        if payload["reviewerFallback"] != incident:
            raise SwarmError("reviewerFallback must equal the incidentId of the reviewer's MODEL_ERROR")
        if root is None:
            raise SwarmError("reviewerFallback needs the run directory to verify its MODEL_ERROR")
        reviewer_quota_incident(root, launch, payload["reviewerFallback"])
    elif role == "reviewer":
        implementers = {model_family(launch["models"][key]) for key in roles - {"reviewer"}}
        if model_family(configuration) in implementers:
            raise SwarmError("the reviewer must use a different model family from the implementers")


def validate_event(value: Any, launch: dict[str, Any], expected_path: pathlib.Path | None = None,
                   root: pathlib.Path | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SwarmError("event must be an object")
    required = {"id", "runId", "type", "from", "fromGeneration", "to", "payload"}
    missing = required - value.keys()
    if missing:
        raise SwarmError(f"event missing: {sorted(missing)}")
    try:
        parsed_event_id = uuid.UUID(value["id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise SwarmError("event id is not a UUID") from exc
    if str(parsed_event_id) != value["id"]:
        raise SwarmError("event id must use canonical lowercase UUID form")
    if value["runId"] != launch["runId"]:
        raise SwarmError("event runId mismatch")
    if type(value["fromGeneration"]) is not int or value["fromGeneration"] < 1:
        raise SwarmError("fromGeneration must be positive")
    if not isinstance(value["payload"], dict):
        raise SwarmError("payload must be an object")
    if "sentAt" in value and (not isinstance(value["sentAt"], str) or len(value["sentAt"]) > 64):
        raise SwarmError("sentAt must be a short timestamp string")
    if value["type"] == "TASK_ASSIGN":
        grant_path, grant_sha = value["payload"].get("grantPath"), value["payload"].get("grantSha256")
        if (not isinstance(grant_path, str) or not pathlib.Path(grant_path).is_absolute()
                or not isinstance(grant_sha, str) or not SHA256_RE.fullmatch(grant_sha)):
            raise SwarmError("TASK_ASSIGN requires an absolute payload.grantPath and its grantSha256")
        if root is not None:
            grant = require_beneath(grant_path, root / "reports", allow_root=False, label="grant")
            if not grant.is_file() or sha256_file(grant) != grant_sha:
                raise SwarmError("TASK_ASSIGN grant file is missing or its SHA-256 differs")
    validate_route(value["type"], value["from"], value["to"], launch)
    if value["type"] == "MODEL_REPLACE":
        validate_model_replace(value["payload"], launch, root)
    if expected_path is not None:
        if expected_path.stem != value["id"] or expected_path.parent.name != value["to"]:
            raise SwarmError("event filename/recipient mismatch")
    for key in ("taskId", "assignmentId"):
        if key in value and (not isinstance(value[key], str) or not value[key]
                             or len(value[key]) > 128
                             or not re.fullmatch(r"[A-Za-z0-9._:-]+", value[key])):
            raise SwarmError(f"{key} is invalid")
    if "revision" in value and (type(value["revision"]) is not int or value["revision"] < 1):
        raise SwarmError("revision must be a positive integer")
    if "candidateSha" in value and (not isinstance(value["candidateSha"], str)
                                      or not SHA_RE.fullmatch(value["candidateSha"])):
        raise SwarmError("candidateSha must be a full lowercase Git SHA")
    missing_bound = BOUND_EVENT_FIELDS.get(value["type"], set()) - value.keys()
    if missing_bound:
        raise SwarmError(f"{value['type']} missing bindings: {sorted(missing_bound)}")
    if root is not None:
        state_path = root / "state.json"
        if state_path.is_file():
            state = load_json(state_path)
            if not isinstance(state, dict) or not isinstance(state.get("agents"), dict):
                raise SwarmError("state agent registry is invalid")
            sender = state["agents"].get(value["from"])
            if sender is not None and (not isinstance(sender, dict)
                                       or sender.get("generation") != value["fromGeneration"]):
                raise SwarmError("event sender generation is stale")
    return value


def send_event(root: pathlib.Path, launch: dict[str, Any], *, sender: str, generation: int,
               recipient: str, event_type: str, payload: dict[str, Any], event_id: str | None = None,
               fields: dict[str, Any] | None = None) -> pathlib.Path:
    event_id = event_id or str(uuid.uuid4())
    event = {
        "id": event_id, "runId": launch["runId"], "type": event_type,
        "from": sender, "fromGeneration": generation, "to": recipient, "sentAt": now(),
        **(fields or {}), "payload": payload,
    }
    validate_event(event, launch, root=root)
    encoded = (json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_JSON_BYTES:
        raise SwarmError(f"event exceeds {MAX_JSON_BYTES} bytes")
    path = root / "inbox" / recipient / f"{event_id}.json"
    write_immutable(path, encoded)
    return path


def pending_events(root: pathlib.Path, launch: dict[str, Any], recipient: str | None = None) -> dict[str, Any]:
    recipients = [recipient] if recipient else sorted(p.name for p in (root / "inbox").iterdir() if p.is_dir())
    pending: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for name in recipients:
        if name not in allowed_agents(launch):
            invalid.append({"path": str(root / "inbox" / name), "error": "unknown recipient"})
            continue
        for path in sorted((root / "inbox" / name).glob("*.json")):
            try:
                event = validate_event(load_json(path), launch, path, root)
                event_hash = sha256_file(path)
                receipt_path = root / "receipts" / name / path.name
                if receipt_path.exists():
                    receipt = load_json(receipt_path)
                    expected = {"eventId": event["id"], "eventSha256": event_hash,
                                "runId": launch["runId"], "recipient": name}
                    if (not isinstance(receipt, dict)
                            or any(receipt.get(key) != value for key, value in expected.items())
                            or not isinstance(receipt.get("accepted"), bool)
                            or not isinstance(receipt.get("disposition"), str)):
                        raise SwarmError("invalid or mismatched event receipt")
                    continue
                pending.append({
                    "id": event["id"], "type": event["type"], "from": event["from"],
                    "to": event["to"], "path": str(path), "sha256": event_hash,
                    "sentAt": event.get("sentAt", ""),
                })
            except SwarmError as exc:
                invalid.append({"path": str(path), "error": str(exc)})
    # FIFO per recipient: the reviewer's inbox is the review queue.
    pending.sort(key=lambda item: (item["to"], item["sentAt"], item["path"]))
    return {"pending": pending, "invalid": invalid, "count": len(pending)}


def receipt_event(root: pathlib.Path, launch: dict[str, Any], event_path: pathlib.Path,
                  recipient: str, accepted: bool, disposition: str) -> pathlib.Path:
    if not isinstance(accepted, bool) or not isinstance(disposition, str) or not disposition.strip():
        raise SwarmError("receipt requires a boolean verdict and nonempty disposition")
    if len(disposition) > 1000:
        raise SwarmError("receipt disposition exceeds 1000 characters")
    expected_dir = root / "inbox" / recipient
    path = require_beneath(event_path, expected_dir, allow_root=False, label="event")
    event = validate_event(load_json(path), launch, path, root)
    if event["to"] != recipient:
        raise SwarmError("receipt actor is not event recipient")
    target = root / "receipts" / recipient / path.name
    receipt = {
        "eventId": event["id"], "eventSha256": sha256_file(path), "runId": launch["runId"],
        "recipient": recipient, "accepted": accepted, "validatedAt": now(),
        "disposition": disposition,
    }
    if target.exists():
        existing = load_json(target)
        identity = ("eventId", "eventSha256", "runId", "recipient", "accepted", "disposition")
        if all(existing.get(key) == receipt[key] for key in identity):
            return target
        raise SwarmError(f"conflicting receipt exists: {target}")
    write_json_immutable(target, receipt)
    return target


def init_run(contract_path: pathlib.Path, requested_run_dir: pathlib.Path) -> dict[str, Any]:
    contract = validate_new_launch(load_json(contract_path), requested_run_dir)
    root = canonical(requested_run_dir)
    if root.exists() and not root.is_dir():
        raise SwarmError(f"run directory path is not a directory: {root}")
    if root.exists() and any(root.iterdir()) and not (root / "automation.json").is_file():
        raise SwarmError("refusing to migrate a nonempty run not owned by this control plane")
    ensure_private_dir(root)
    marker = {"schemaVersion": 1, "automationVersion": VERSION, "runId": contract["runId"]}
    write_json_immutable(root / "automation.json", marker, same_ok=True)
    for relative in ("inbox", "receipts", "reports", "homes", "runtime", "objects/sha256", "supervision"):
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    for agent in allowed_agents(contract):
        for parent in (root / "inbox", root / "receipts", root / "reports"):
            (parent / agent).mkdir(mode=0o700, exist_ok=True)
        if agent not in {contract["responsible"]["agent"], principal_name(contract)}:
            (root / "homes" / agent).mkdir(mode=0o700, exist_ok=True)
    write_json_immutable(root / "launch.json", contract, same_ok=True)
    script_root = pathlib.Path(__file__).resolve().parent
    runtime_hashes: dict[str, str] = {}
    for name in ("swarmctl.py", "swarmcore.py", "swarmbootstrap.py", "swarmd.py"):
        source = script_root / name
        data = source.read_bytes()
        target = root / "runtime" / name
        write_immutable(target, data, mode=0o700, same_ok=True)
        runtime_hashes[name] = sha256_bytes(data)
    supervisor_path = root / "supervisor.json"
    if supervisor_path.exists():
        supervisor = load_json(supervisor_path)
        if supervisor.get("runId") != contract["runId"]:
            raise SwarmError("supervisor runId mismatch")
    else:
        write_json_mutable(supervisor_path, {
            "schemaVersion": 1, "runId": contract["runId"],
            "responsible": contract["responsible"], "principal": None,
            "principalValidated": False, "runtimeHashes": runtime_hashes,
            "updatedAt": now(),
        })
    return {"runDir": str(root), "launchSha256": sha256_file(root / "launch.json"),
            "runtimeHashes": runtime_hashes}


def snapshot_create(root: pathlib.Path, launch: dict[str, Any], tree: pathlib.Path,
                    paths: Iterable[str], output: pathlib.Path) -> dict[str, Any]:
    tree = canonical(tree, exists=True)
    allowed_roots = [canonical(launch["repoPath"]), canonical(launch["worktreeRoot"])]
    if not any(beneath(tree, allowed) for allowed in allowed_roots):
        raise SwarmError("snapshot tree is outside repository/worktree roots")
    files: dict[str, Any] = {}
    for rel in sorted(set(paths)):
        p = pathlib.PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts or rel in {"", "."}:
            raise SwarmError(f"unsafe snapshot path: {rel}")
        actual = require_beneath(tree / pathlib.Path(*p.parts), tree, allow_root=False, label="snapshot path")
        if not actual.is_file():
            raise SwarmError(f"snapshot path is not a file: {rel}")
        files[rel] = {"sha256": sha256_file(actual), "bytes": actual.stat().st_size,
                      "mode": oct(stat.S_IMODE(actual.stat().st_mode))}
    value = {"schemaVersion": 1, "runId": launch["runId"], "root": str(tree),
             "createdAt": now(), "files": files}
    output = require_beneath(output, root / "reports", allow_root=False, label="snapshot output")
    write_json_immutable(output, value)
    return value


def snapshot_verify(root: pathlib.Path, launch: dict[str, Any], snapshot_path: pathlib.Path) -> dict[str, Any]:
    path = require_beneath(snapshot_path, root / "reports", allow_root=False, label="snapshot")
    value = load_json(path)
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or value.get("runId") != launch["runId"] or not isinstance(value.get("root"), str)
            or not isinstance(value.get("files"), dict)):
        raise SwarmError("invalid snapshot schema or runId")
    tree = canonical(value.get("root", ""), exists=True)
    allowed_roots = [canonical(launch["repoPath"]), canonical(launch["worktreeRoot"])]
    if not any(beneath(tree, allowed) for allowed in allowed_roots):
        raise SwarmError("snapshot root is outside repository/worktree roots")
    mismatches = []
    for rel, expected in value["files"].items():
        if (not isinstance(rel, str) or not isinstance(expected, dict)
                or not SHA256_RE.fullmatch(str(expected.get("sha256", "")))):
            raise SwarmError("invalid snapshot file entry")
        actual = require_beneath(tree / rel, tree, allow_root=False, label="snapshot path")
        observed = sha256_file(actual) if actual.is_file() else None
        if observed != expected["sha256"]:
            mismatches.append({"path": rel, "expected": expected["sha256"], "actual": observed})
    return {"ok": not mismatches, "snapshot": str(path), "mismatches": mismatches,
            "checked": len(value["files"])}


def artifact_put(root: pathlib.Path, launch: dict[str, Any], source: pathlib.Path) -> dict[str, Any]:
    source = canonical(source, exists=True)
    allowed = (root, canonical(launch["repoPath"]), canonical(launch["worktreeRoot"]))
    if not source.is_file() or not any(beneath(source, candidate) for candidate in allowed):
        raise SwarmError("artifact source is outside run/repository/worktree roots")
    if source.stat().st_size > MAX_ARTIFACT_BYTES:
        raise SwarmError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    digest = sha256_file(source)
    target = root / "objects" / "sha256" / digest[:2] / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    created = write_immutable(target, source.read_bytes(), mode=0o400, same_ok=True)
    return {"sha256": digest, "bytes": source.stat().st_size, "path": str(target), "created": created}


def validate_gate_contract(value: Any, root: pathlib.Path, launch: dict[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "id", "runId", "cwd", "argv", "unsetEnv", "logPath", "exitPath"}
    if not isinstance(value, dict) or required - value.keys():
        raise SwarmError("invalid gate contract")
    try:
        parsed_gate_id = uuid.UUID(value["id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise SwarmError("gate id is not a UUID") from exc
    if str(parsed_gate_id) != value["id"]:
        raise SwarmError("gate id must use canonical lowercase UUID form")
    if value["runId"] != launch["runId"]:
        raise SwarmError("gate runId mismatch")
    argv = value["argv"]
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x or "\x00" in x for x in argv):
        raise SwarmError("gate argv must be a nonempty string array")
    cwd = canonical(value["cwd"], exists=True)
    if not (beneath(cwd, canonical(launch["repoPath"])) or beneath(cwd, canonical(launch["worktreeRoot"]))):
        raise SwarmError("gate cwd is outside allowed roots")
    outputs = [require_beneath(value[key], root / "reports", allow_root=False, label=key)
               for key in ("logPath", "exitPath")]
    if outputs[0] == outputs[1]:
        raise SwarmError("gate logPath and exitPath must differ")
    if not isinstance(value["unsetEnv"], list) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x)
                                                         for x in value["unsetEnv"]):
        raise SwarmError("invalid unsetEnv")
    return value


def gate_reserve(root: pathlib.Path, launch: dict[str, Any], cwd: pathlib.Path, argv: list[str],
                 unset_env: list[str], log_path: pathlib.Path, exit_path: pathlib.Path,
                 output: pathlib.Path) -> dict[str, Any]:
    if not isinstance(argv, list) or not argv:
        raise SwarmError("gate argv must be a nonempty array")
    if pathlib.Path(argv[0]).name in {"sh", "bash", "zsh", "fish"}:
        raise SwarmError("shell executables are not valid gate commands")
    value = {"schemaVersion": 1, "id": str(uuid.uuid4()), "runId": launch["runId"],
             "createdAt": now(), "cwd": str(canonical(cwd, exists=True)), "argv": argv,
             "unsetEnv": unset_env, "logPath": str(canonical(log_path)),
             "exitPath": str(canonical(exit_path))}
    validate_gate_contract(value, root, launch)
    output = require_beneath(output, root / "reports", allow_root=False, label="gate contract")
    if output in {canonical(log_path), canonical(exit_path)}:
        raise SwarmError("gate contract and output paths must differ")
    write_json_immutable(output, value)
    return value


def gate_run(root: pathlib.Path, launch: dict[str, Any], contract_path: pathlib.Path) -> int:
    path = require_beneath(contract_path, root / "reports", allow_root=False, label="gate contract")
    value = validate_gate_contract(load_json(path), root, launch)
    lock_path = root / "supervision" / f"gate-{value['id']}.lock"
    with open(lock_path, "a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SwarmError("gate is already running") from exc
        log_path, exit_path = pathlib.Path(value["logPath"]), pathlib.Path(value["exitPath"])
        if log_path.exists() or exit_path.exists():
            raise SwarmError("gate outputs already exist; refusing replay")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        env = os.environ.copy()
        for key in value["unsetEnv"]:
            env.pop(key, None)
        try:
            with os.fdopen(log_fd, "wb") as log:
                try:
                    process = subprocess.run(value["argv"], cwd=value["cwd"], env=env,
                                             stdout=log, stderr=subprocess.STDOUT, check=False)
                    code = process.returncode
                except KeyboardInterrupt:
                    code = 130
                log.flush()
                os.fsync(log.fileno())
            os.chmod(log_path, 0o400)
            write_immutable(exit_path, f"{code}\n".encode(), mode=0o400)
            return code
        except Exception:
            with contextlib.suppress(OSError):
                os.chmod(log_path, 0o400)
            raise


