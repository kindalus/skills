"""Migration into correio.db: the v1 file mailbox, 2.7 swarm runs (read-only legacy spaces) and the JSONL
host queue. Every importer is idempotent: a rerun adds what is new and refuses bytes that changed."""
from __future__ import annotations

import json
import pathlib
import re
import uuid
from typing import Any

from . import envelope as env
from . import library
from .store import CorreioError, Store

V1_NAMESPACE = uuid.UUID("6f1b2c1e-4d0a-4a53-9d59-0f6c2f0f8a11")
ROLE_BY_NAME = ((re.compile(r"^(orquestrador|orchestrator)$"), "orchestrator"),
                (re.compile(r"^porta-voz$"), "spokesperson"),
                (re.compile(r"(preparer|preparador)"), "preparer"),
                (re.compile(r"^(consultor|consultant)"), "consultant"),
                (re.compile(r"^(executor|bugs-)"), "executor"))
EVENT_KEYS = {"id", "runId", "type", "from", "fromGeneration", "to", "sentAt", "payload"}


def role_for(name: str) -> str:
    for pattern, role in ROLE_BY_NAME:
        if pattern.search(name):
            return role
    return "other"


def _scalar_split(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scalars go to fields; structured values are kept as canonical JSON strings."""
    fields: dict[str, Any] = {}
    structured: dict[str, Any] = {}
    for key, value in payload.items():
        if not env.FIELD_KEY.match(str(key)):
            structured[key] = value
        elif value is None or isinstance(value, (bool, int, str)) and not (
                isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10 ** 18):
            fields[key] = value
        else:
            fields[key] = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            structured[key] = value
    return fields, structured


def _safe_text(value: Any, limit: int = 300) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] or "(sem assunto)"


def _store_imported(store: Store, space: dict[str, Any], header: dict[str, Any], fields: dict[str, Any],
                    attachments: list[dict[str, Any]], body: str, delivery: str, source: str) -> tuple[bool, str]:
    data = env.emit(header, fields, attachments, body)
    parsed = env.parse(data)
    existed = store.message(parsed["id"]) is not None
    library.store_message(store, space, data, parsed, delivery, imported_from=source)
    return not existed, parsed["id"]


# -- v1 file mailbox ------------------------------------------------------------------------------------------------------
def import_files(store: Store, root: pathlib.Path | str, *, space: str | None = None) -> dict[str, Any]:
    """``correio/inbox/<agent>/*.json`` and ``receipts/<agent>/*.json`` of mail v1 into the orchestration space."""
    root = pathlib.Path(root).expanduser().resolve()
    space_id = library.resolve_space(store, space)
    sp = store.space(space_id)
    module = library.protocol_of(sp)
    counts = {"messages": 0, "skipped": 0, "receipts": 0, "members": 0, "errors": [], "warnings": []}
    files = sorted((root / "inbox").glob("*/*.json"))
    agents = {p.parent.name for p in files} | {p.parent.name for p in (root / "receipts").glob("*/*.json")}
    for message_path in files:
        try:
            agents.add(str(json.loads(message_path.read_text(encoding="utf-8")).get("from", "")))
        except (OSError, ValueError):
            pass
    with store.tx():
        for agent in sorted(a for a in agents if a and a not in {"correio"} and env.NAME.match(a)):
            if store.member(space_id, agent) is None:
                library.add_member(store, space_id, agent, role_for(agent))
                counts["members"] += 1
        for message_path in files:
            try:
                raw = message_path.read_bytes()
                v1 = json.loads(raw)
                message_id = str(uuid.uuid5(V1_NAMESPACE, str(v1["id"])))
                known = store.message(message_id)
                if known is not None:
                    # Imported before: the v1 file is the identity. Unchanged, the stored envelope stays as it is
                    # (an attachment that changed since is a warning) and only the receipts below are new.
                    if known["fields"].get("legacySha256") != env.sha256(raw):
                        raise CorreioError(f"v1 file changed since its import as {message_id}")
                    for item in store.q("SELECT path, sha256, bytes FROM attachments WHERE message_id=?",
                                        (message_id,)):
                        warning = _attachment_drift(item)
                        if warning:
                            counts["warnings"].append({"path": item["path"], "message": message_id,
                                                       "warning": warning})
                    counts["skipped"] += 1
                    _import_v1_receipt(store, root, message_path, message_id, counts)
                    continue
                payload = v1.get("payload") if isinstance(v1.get("payload"), dict) else {}
                thread = library.infer_thread(v1.get("subject"), v1.get("body"), payload)
                fields, _structured = _scalar_split(payload)
                fields.update(legacyId=str(v1["id"]), legacySha256=env.sha256(raw))
                attachments = []
                body = v1.get("body") if isinstance(v1.get("body"), str) else ""
                body_file = v1.get("bodyFile") if isinstance(v1.get("bodyFile"), dict) else None
                if body_file and isinstance(body_file.get("path"), str) and body_file["path"].startswith("/"):
                    path = pathlib.Path(body_file["path"])
                    attachments.append({"path": str(path), "sha256": str(body_file.get("sha256", "0" * 64)),
                                        "bytes": path.stat().st_size if path.is_file() else 0})
                    body = body or f"(corpo em anexo: {path})\n"
                kind = v1.get("type") if v1.get("type") in module.TYPES else "INFO"
                header = {"correio": env.CORREIO, "id": str(uuid.uuid5(V1_NAMESPACE, str(v1["id"]))),
                          "space": space_id, "protocol": sp["protocol"], "version": sp["version"], "thread": thread,
                          "type": kind, "from": str(v1["from"]), "from_generation": None,
                          "to": message_path.parent.name, "in_reply_to": None, "sent_at": str(v1["sentAt"]),
                          "subject": _safe_text(v1.get("subject"))}
                created, message_id = _store_imported(store, sp, header, fields, attachments, body,
                                                      module.TYPES[kind], str(message_path))
                counts["messages" if created else "skipped"] += 1
                _import_v1_receipt(store, root, message_path, message_id, counts)
            except (OSError, ValueError, KeyError, TypeError, CorreioError) as exc:
                counts["errors"].append({"path": str(message_path), "error": str(exc)[:300]})
    return counts


def _attachment_drift(item: Any) -> str | None:
    """Why an imported attachment no longer matches, or None. Never raises: any failure to read it (missing, no
    permission, a directory) is a warning, so it never stops the receipts that follow."""
    path = pathlib.Path(item["path"])
    try:
        if not path.is_file():
            return "attachment missing or not a file since the import"
        if path.stat().st_size != item["bytes"]:
            return "attachment changed since the import (size)"
        if item["sha256"] != "0" * 64 and library.sha256_file(path) != item["sha256"]:
            return "attachment changed since the import (sha256)"
    except OSError as exc:
        return f"attachment unreadable: {exc.strerror or exc}"
    return None


def _import_v1_receipt(store: Store, root: pathlib.Path, message_path: pathlib.Path, message_id: str,
                       counts: dict[str, Any]) -> None:
    receipt_path = root / "receipts" / message_path.parent.name / message_path.name
    if receipt_path.is_file() and store.receipt(message_id) is None:
        v1r = json.loads(receipt_path.read_text(encoding="utf-8"))
        message = store.message(message_id)
        store.x("INSERT INTO receipts(message_id, agent, accepted, disposition, message_sha256, "
                "receipted_at) VALUES (?,?,?,?,?,?)",
                (message_id, message["to_agent"], 1, str(v1r.get("disposition") or "recibo v1"),
                 message["sha256"], str(v1r.get("receiptedAt") or store.now())))
        counts["receipts"] += 1


# -- 2.7 swarm runs -------------------------------------------------------------------------------------------------------
def import_run(store: Store, run_dir: pathlib.Path | str) -> dict[str, Any]:
    """A 2.7 run as a read-only legacy space: contract, members, tasks, state, events and receipts."""
    root = pathlib.Path(run_dir).expanduser().resolve()
    launch = json.loads((root / "launch.json").read_text(encoding="utf-8"))
    marker = json.loads((root / "automation.json").read_text(encoding="utf-8"))
    version = str(marker.get("automationVersion"))
    if version == "3.0.0":
        raise CorreioError("a 3.0.0 run already lives in correio; nothing to import")
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    space_id = str(launch["prefix"])
    counts = {"space": space_id, "messages": 0, "skipped": 0, "receipts": 0, "tasks": 0, "errors": []}
    with store.tx():
        existing = store.space(space_id)
        if existing and (not existing["legacy"] or (existing["contract"] or {}).get("runId") != launch["runId"]):
            raise CorreioError(f"space {space_id} exists and is not this run's legacy import")
        sp = existing or library.create_space(
            store, space_id=space_id, kind="swarm", protocol="swarm", version=version, slice_id=launch.get("sliceId"),
            prefix=space_id, run_dir=str(root), repo_path=launch.get("repoPath"), base_sha=launch.get("baseSha"),
            spec_path=launch.get("specPath"), contract=launch, legacy=True, state=str(state.get("state") or "running"))
        responsible = launch.get("responsible", {})
        roster: dict[str, dict[str, Any]] = {responsible.get("agent"): {"role": "responsible", "generation": 1,
                                                                         "paneId": responsible.get("paneId"),
                                                                         "workspaceId": responsible.get("workspaceId")}}
        for name, agent in (state.get("agents") or {}).items():
            roster[name] = agent
        for name, agent in roster.items():
            if not name or not env.NAME.match(name):
                continue
            cols = {"role": str(agent.get("role") or "other"), "generation": int(agent.get("generation") or 1),
                    "pane_id": agent.get("paneId"), "workspace_id": agent.get("workspaceId")}
            if store.member(space_id, name) is None:
                store.x("INSERT INTO members(space_id, agent, role, generation, pane_id, workspace_id, configuration,"
                        " ready, attributes, joined_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (space_id, name, cols["role"], cols["generation"], cols["pane_id"], cols["workspace_id"],
                         json.dumps({"value": agent.get("configuration")}) if agent.get("configuration") else None,
                         int(bool(agent.get("ready"))), "{}", store.now()))
            else:
                store.update_member(space_id, name, generation=cols["generation"], pane_id=cols["pane_id"],
                                    workspace_id=cols["workspace_id"])
        for task_id, task in (state.get("tasks") or {}).items():
            if not isinstance(task, dict):
                continue
            store.upsert_task(space_id, str(task_id), "import-run", state=str(task.get("state") or "unknown"),
                              revision=task.get("revision") if isinstance(task.get("revision"), int) else None,
                              assignment_id=task.get("assignmentId"), candidate_sha=task.get("candidateSha"),
                              worktree=task.get("worktree"), branch=task.get("branch"), owner=task.get("owner"))
            counts["tasks"] += 1
        terminal = None
        for event_path in sorted(root.glob("inbox/*/*.json")):
            try:
                raw = event_path.read_bytes()
                event = json.loads(raw)
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                fields, structured = _scalar_split(payload)
                for key in ("taskId", "assignmentId", "revision", "candidateSha", "runId"):
                    if key in event:
                        fields[key] = event[key]
                task = event.get("taskId")
                body = ""
                if structured:
                    body = "```json\n" + json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n```\n"
                header = {"correio": env.CORREIO, "id": str(event["id"]), "space": space_id, "protocol": "swarm",
                          "version": version, "thread": str(task or launch.get("sliceId") or space_id),
                          "type": str(event["type"]), "from": str(event["from"]),
                          "from_generation": event.get("fromGeneration") if isinstance(
                              event.get("fromGeneration"), int) else None,
                          "to": event_path.parent.name, "in_reply_to": None,
                          "sent_at": str(event.get("sentAt") or "1970-01-01T00:00:00Z"),
                          "subject": _safe_text(f"{event['type']} {task or launch.get('sliceId', '')}")}
                attachments = [{"path": str(event_path), "sha256": env.sha256(raw), "bytes": len(raw)}]
                created, message_id = _store_imported(store, sp, header, fields, attachments, body, "wake",
                                                      str(event_path))
                counts["messages" if created else "skipped"] += 1
                receipt_path = root / "receipts" / event_path.parent.name / event_path.name
                if receipt_path.is_file():
                    r = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if store.receipt(message_id) is None:
                        message = store.message(message_id)
                        store.x("INSERT INTO receipts(message_id, agent, accepted, disposition, message_sha256, "
                                "receipted_at) VALUES (?,?,?,?,?,?)",
                                (message_id, message["to_agent"], int(bool(r.get("accepted"))),
                                 str(r.get("disposition") or "recibo 2.7"), message["sha256"],
                                 str(r.get("validatedAt") or store.now())))
                        counts["receipts"] += 1
                    if r.get("accepted") is True and event.get("type") in {"SLICE_ACCEPTED", "CANCEL"} and (
                            event["type"] == "SLICE_ACCEPTED" or event_path.parent.name.endswith("-principal")):
                        terminal = ("accepted" if event["type"] == "SLICE_ACCEPTED" else "cancelled",
                                    str(r.get("validatedAt") or store.now()))
            except (OSError, ValueError, KeyError, TypeError, CorreioError) as exc:
                counts["errors"].append({"path": str(event_path), "error": str(exc)[:300]})
        snapshot = {"state": terminal[0] if terminal else str(state.get("state") or "running"),
                    "legacy": True, "automationVersion": version, "stateJson": str(state_path),
                    "plan": state.get("plan"), "openFindings": len(state.get("openFindings") or []),
                    "updatedAt": state.get("updatedAt")}
        store.set_space_state(space_id, snapshot, "import-run")
        if terminal:
            store.x("UPDATE spaces SET closed_at=COALESCE(closed_at, ?) WHERE id=?", (terminal[1], space_id))
    return counts


# -- JSONL host queue -------------------------------------------------------------------------------------------------------
def import_jobs(store: Store, path: pathlib.Path | str) -> dict[str, Any]:
    """``lease-queue.jsonl`` rows into ``jobs``, in file order; the file stays as it is."""
    counts = {"jobs": 0, "skipped": 0, "errors": []}
    with store.tx():
        with library.jsonl_lock(path):  # whole lines only: a v1 writer that takes the lock is never read halfway
            text = pathlib.Path(path).read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if store.one("SELECT 1 FROM jobs WHERE id=?", (str(row["id"]),)):
                    counts["skipped"] += 1
                    continue
                raw_state = str(row.get("state", "queued"))
                exit_code = None
                state = raw_state
                if raw_state.startswith("done"):
                    state = "done"
                    match = re.search(r"exit=(-?\d+)", raw_state)
                    exit_code = int(match.group(1)) if match else None
                if state not in {"queued", "running", "done"}:
                    raise ValueError(f"unknown state {raw_state!r}")
                kind = str(row.get("kind")) if row.get("kind") in library.JOB_KINDS else "lote"
                store.x("INSERT INTO jobs(id, kind, who, cmd, priority, state, at, started_at, ended_at, exit) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (str(row["id"]), kind, str(row.get("who", "")), str(row.get("cmd", "")), 0, state,
                         str(row.get("at") or store.now()), row.get("startedAt"), row.get("endedAt"), exit_code))
                counts["jobs"] += 1
            except (ValueError, KeyError, TypeError) as exc:
                counts["errors"].append({"line": n, "error": str(exc)[:300]})
    return counts
