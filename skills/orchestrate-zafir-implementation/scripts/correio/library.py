"""Correio v2 operations: spaces, members, send, receipt, queries, export and the host job queue.

Every write runs in one short ``BEGIN IMMEDIATE`` transaction. ``send`` builds the envelope, validates it
with the protocol module pinned by the space, and stores it; an INFO is projected on send. ``receipt``
records the recipient's verdict and, for an accepted wake message, applies the protocol's projection in
the same transaction.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import uuid
from typing import Any, Iterable

from . import envelope as env
from . import protocols
from .store import CorreioError, Store, parse_iso

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
CLI = f"python3 {SCRIPTS / 'correio.py'}"
SPACE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ROLE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAX_DISPOSITION = 1000


def sha256_file(path: os.PathLike[str] | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protocol_of(space: dict[str, Any]):
    if space["legacy"]:
        raise CorreioError(f"space {space['id']} is a legacy {space['protocol']} {space['version']} import: read-only")
    try:
        return protocols.load(space["protocol"], space["version"])
    except protocols.ProtocolMissing as exc:
        raise CorreioError(str(exc)) from exc


def _space(store: Store, space_id: str) -> dict[str, Any]:
    space = store.space(space_id)
    if space is None:
        raise CorreioError(f"no space {space_id}")
    return space


def resolve_space(store: Store, space_id: str | None = None) -> str:
    """The named space, else $CORREIO_SPACE, else the one open orchestration space."""
    space_id = space_id or os.environ.get("CORREIO_SPACE")
    if space_id:
        _space(store, space_id)
        return space_id
    rows = store.q("SELECT id FROM spaces WHERE kind='orchestration' AND legacy=0 AND closed_at IS NULL")
    if len(rows) != 1:
        raise CorreioError("name the space with --space (there is not exactly one open orchestration space)")
    return rows[0]["id"]


# -- spaces and members ----------------------------------------------------------------------------------------
def create_space(store: Store, *, space_id: str, kind: str, protocol: str, version: str, slice_id: str | None = None,
                 prefix: str | None = None, run_dir: str | None = None, repo_path: str | None = None,
                 base_sha: str | None = None, spec_path: str | None = None, contract: dict[str, Any] | None = None,
                 legacy: bool = False, state: str | None = None) -> dict[str, Any]:
    if not SPACE_ID.match(space_id):
        raise CorreioError(f"invalid space id: {space_id!r}")
    if kind not in {"orchestration", "swarm"}:
        raise CorreioError("kind is orchestration or swarm")
    if not legacy:
        try:
            module = protocols.load(protocol, version)
        except protocols.ProtocolMissing as exc:
            raise CorreioError(str(exc)) from exc
        if kind == "swarm" and module.NAME != "swarm":
            raise CorreioError("a swarm space uses the swarm protocol")
        if kind == "swarm" and not isinstance(contract, dict):
            raise CorreioError("a swarm space needs its launch contract (--contract)")
    initial = state or ("open" if kind == "orchestration" else "starting")
    with store.tx():
        existing = store.space(space_id)
        if existing:
            same = (existing["kind"], existing["protocol"], existing["version"], existing["legacy"]) == (
                kind, protocol, version, legacy) and (contract is None or existing["contract"] == contract)
            if not same:
                raise CorreioError(f"space {space_id} already exists with another kind, protocol, version or contract")
            return existing
        store.x("INSERT INTO spaces(id, kind, slice, prefix, protocol, version, state, created_at, run_dir, repo_path,"
                " base_sha, spec_path, contract, legacy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (space_id, kind, slice_id, prefix, protocol, version, initial, store.now(), run_dir, repo_path,
                 base_sha, spec_path, json.dumps(contract, sort_keys=True, ensure_ascii=False) if contract else None,
                 int(legacy)))
        store.set_space_state(space_id, {"state": initial}, "space create")
    return _space(store, space_id)


def close_space(store: Store, space_id: str) -> dict[str, Any]:
    with store.tx():
        _space(store, space_id)
        store.close_space(space_id)
        store.x("UPDATE spaces SET state=CASE WHEN state IN ('accepted','cancelled') THEN state ELSE 'closed' END "
                "WHERE id=?", (space_id,))
    return _space(store, space_id)


def list_spaces(store: Store, *, open_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT id FROM spaces" + (" WHERE closed_at IS NULL" if open_only else "") + " ORDER BY created_at, id"
    return [_space(store, row["id"]) for row in store.q(sql)]


def add_member(store: Store, space_id: str, agent: str, role: str, *, generation: int = 1,
               pane_id: str | None = None, workspace_id: str | None = None, configuration: Any = None,
               attributes: dict[str, Any] | None = None, ready: bool = False) -> dict[str, Any]:
    if not env.NAME.match(agent) or agent in {"correio", "swarmctl"}:
        raise CorreioError(f"invalid or reserved agent name: {agent!r}")
    if not ROLE.match(role):
        raise CorreioError(f"invalid role: {role!r}")
    if type(generation) is not int or generation < 1:
        raise CorreioError("generation must be a positive integer")
    with store.tx():
        _space(store, space_id)
        current = store.member(space_id, agent)
        if current and current["left_at"] is None:
            if current["role"] != role:
                raise CorreioError(f"{agent} is already a {current['role']} of {space_id}")
            return current
        if current:
            store.update_member(space_id, agent, role=role, left_at=None, joined_at=store.now(), pane_id=pane_id,
                                workspace_id=workspace_id)
        else:
            store.x("INSERT INTO members(space_id, agent, role, generation, pane_id, workspace_id, configuration, ready,"
                    " attributes, joined_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (space_id, agent, role, generation, pane_id, workspace_id,
                     json.dumps(configuration, sort_keys=True) if configuration is not None else None, int(ready),
                     json.dumps(attributes or {}, sort_keys=True), store.now()))
        return store.member(space_id, agent)


def update_member(store: Store, space_id: str, agent: str, *, set_attributes: dict[str, Any] | None = None,
                  clear_attributes: Iterable[str] = (), **cols: Any) -> dict[str, Any]:
    allowed = {"pane_id", "workspace_id", "generation", "ready", "configuration", "role"}
    unknown = set(cols) - allowed
    if unknown:
        raise CorreioError(f"cannot update {sorted(unknown)}")
    if "generation" in cols and (type(cols["generation"]) is not int or cols["generation"] < 1):
        raise CorreioError("generation must be a positive integer")
    with store.tx():
        member = store.member(space_id, agent)
        if member is None:
            raise CorreioError(f"no member {agent} in space {space_id}")
        if set_attributes or clear_attributes:
            attributes = dict(member["attributes"])
            attributes.update(set_attributes or {})
            for key in clear_attributes:
                attributes.pop(key, None)
            cols["attributes"] = attributes
        if "ready" in cols:
            cols["ready"] = int(bool(cols["ready"]))
        store.update_member(space_id, agent, **cols)
        return store.member(space_id, agent)


def leave_member(store: Store, space_id: str, agent: str) -> dict[str, Any]:
    with store.tx():
        if store.member(space_id, agent) is None:
            raise CorreioError(f"no member {agent} in space {space_id}")
        store.update_member(space_id, agent, left_at=store.now())
        return store.member(space_id, agent)


def bump_generation(store: Store, space_id: str, agent: str, *, to: int | None = None) -> int:
    """Generation N+1 for a restarted agent (idempotent when ``to`` is already reached)."""
    with store.tx():
        member = store.member(space_id, agent)
        if member is None:
            raise CorreioError(f"no member {agent} in space {space_id}")
        target = to if to is not None else member["generation"] + 1
        if member["generation"] not in {target - 1, target}:
            raise CorreioError(f"{agent} is at generation {member['generation']}, not {target - 1}")
        store.update_member(space_id, agent, generation=target, ready=0)
        return target


# -- sender authenticity --------------------------------------------------------------------------------------------
def verify_pane(members: dict[str, dict[str, Any]], agent: str, space_id: str = "") -> None:
    """Inside Herdr ($HERDR_PANE_ID set) an agent acts only as itself: the calling pane must be the pane
    recorded for it in the space. Outside Herdr nothing is checked.

    Service processes are the explicit exception: the courier's own mail goes through ``system_mail``
    (``system=True``, sender ``correio``) and swarmctl's INFO through ``system=True`` (sender ``swarmctl``);
    neither runs in an agent's pane. The orchestrator's host scripts run without $HERDR_PANE_ID.
    """
    pane = os.environ.get("HERDR_PANE_ID")
    if not pane:
        return
    member = members.get(agent)
    recorded = member.get("pane_id") if member else None
    if not recorded:
        raise CorreioError(f"{agent} has no pane recorded in {space_id or 'this space'}, so this pane ({pane}) "
                           f"cannot act as it: record it with correio member update --agent {agent} --pane {pane}")
    if recorded != pane:
        raise CorreioError(f"{agent} is recorded in pane {recorded}, not in this pane ({pane}); "
                           "agents send and receipt only as themselves")


# -- send and receipt ------------------------------------------------------------------------------------------------
def attachment(path: os.PathLike[str] | str) -> dict[str, Any]:
    resolved = pathlib.Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise CorreioError(f"attachment is not a file: {resolved}")
    return {"path": str(resolved), "sha256": sha256_file(resolved), "bytes": resolved.stat().st_size}


def _ensure_thread(store: Store, space_id: str, key: str, subject: str, sender: str) -> int:
    row = store.one("SELECT id, state FROM threads WHERE space_id=? AND key=?", (space_id, key))
    if row is None:
        cur = store.x("INSERT INTO threads(space_id, key, subject, state, opened_by, opened_at) VALUES (?,?,?,?,?,?)",
                      (space_id, key, subject, "open", sender, store.now()))
        return int(cur.lastrowid)
    if row["state"] == "closed":
        store.set_thread_state(space_id, key, "open")
    return int(row["id"])


def store_message(store: Store, space: dict[str, Any], data: bytes, parsed: dict[str, Any], delivery: str,
                  imported_from: str | None = None) -> dict[str, Any]:
    """Insert one validated envelope (inside the caller's transaction)."""
    existing = store.message(parsed["id"])
    if existing:
        if existing["sha256"] != env.sha256(data):
            raise CorreioError(f"message {parsed['id']} already exists with other bytes")
        return existing
    thread_id = _ensure_thread(store, space["id"], parsed["thread"], parsed["subject"], parsed["from"])
    store.x("INSERT INTO messages(id, space_id, thread_id, protocol, version, type, delivery, from_agent, "
            "from_generation, to_agent, in_reply_to, subject, sent_at, sha256, envelope, fields, body, imported_from)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (parsed["id"], space["id"], thread_id, parsed["protocol"], parsed["version"], parsed["type"], delivery,
             parsed["from"], parsed["from_generation"], parsed["to"], parsed["in_reply_to"], parsed["subject"],
             parsed["sent_at"], env.sha256(data), data, json.dumps(parsed["fields"], sort_keys=True,
                                                                   ensure_ascii=False),
             parsed["body"], imported_from))
    for item in parsed["attachments"]:
        store.x("INSERT INTO attachments(message_id, path, sha256, bytes) VALUES (?,?,?,?)",
                (parsed["id"], item["path"], item["sha256"], item["bytes"]))
    return store.message(parsed["id"])


def _apply_close(store: Store, space: dict[str, Any], module: Any) -> None:
    if module.close_condition(store.space_state(space["id"]), space, store):
        store.close_space(space["id"])


def send(store: Store, *, space: str, sender: str, to: str, type: str, thread: str | None = None,
         subject: str | None = None, body: str = "", fields: dict[str, Any] | None = None,
         attachments: Iterable[os.PathLike[str] | str] = (), reply_to: str | None = None,
         generation: int | None = None, message_id: str | None = None, system: bool = False,
         check_pane: bool = True, self_receipt: str | None = None) -> dict[str, Any]:
    if message_id is not None:
        try:
            if str(uuid.UUID(message_id)) != message_id:
                raise ValueError
        except ValueError as exc:
            raise CorreioError("message id must be a canonical lowercase UUID") from exc
    message_id = message_id or str(uuid.uuid4())
    items = [attachment(p) for p in attachments]
    with store.tx():
        sp = _space(store, space)
        module = protocol_of(sp)
        if sp["closed_at"]:
            raise CorreioError(f"space {space} is closed ({sp['state']})")
        members = store.members(space)
        if not system and check_pane:
            verify_pane(members, sender, space)
        draft = {"type": type, "thread": thread, "subject": subject, "fields": dict(fields or {})}
        try:
            module.prepare(sp, draft)
        except (ValueError, KeyError) as exc:
            raise CorreioError(str(exc)) from exc
        if generation is None and not system:
            if getattr(module, "REQUIRES_GENERATION", False):
                raise CorreioError(f"{sp['protocol']} {sp['version']} needs --generation")
            if sender in members:
                generation = members[sender]["generation"]
        if not draft.get("thread"):
            raise CorreioError("--thread is required (the slice or the request, for example S606 or geral)")
        if not draft.get("subject"):
            raise CorreioError("--subject is required")
        header = {"correio": env.CORREIO, "id": message_id, "space": space, "protocol": sp["protocol"],
                  "version": sp["version"], "thread": draft["thread"], "type": type, "from": sender,
                  "from_generation": generation, "to": to, "in_reply_to": reply_to, "sent_at": store.now(),
                  "subject": draft["subject"]}
        try:
            data = env.emit(header, draft["fields"], items, body)
            parsed = env.parse(data)
            module.validate_send(sp, members, parsed, store, system=system)
        except ValueError as exc:
            raise CorreioError(str(exc)) from exc
        if store.message(message_id):
            raise CorreioError(f"message {message_id} already exists")
        delivery = module.TYPES[type]
        message = store_message(store, sp, data, parsed, delivery)
        if delivery == "info":
            module.project(sp, message, None, store)
            _apply_close(store, sp, module)
        result = {"id": message_id, "space": space, "thread": parsed["thread"], "type": type, "to": to,
                  "delivery": delivery, "sha256": message["sha256"]}
        if self_receipt is not None:
            if to != sender:
                raise CorreioError("--self-receipt is only for a message to yourself")
            result["receipt"] = receipt(store, message_id=message_id, agent=sender, disposition=self_receipt,
                                        check_pane=check_pane)
        return result


def receipt(store: Store, *, message_id: str, agent: str, disposition: str, accepted: bool = True,
            check_pane: bool = True) -> dict[str, Any]:
    if not isinstance(disposition, str) or not disposition.strip():
        raise CorreioError("receipt requires a nonempty disposition")
    if len(disposition) > MAX_DISPOSITION:
        raise CorreioError(f"receipt disposition exceeds {MAX_DISPOSITION} characters")
    with store.tx():
        message = store.message(message_id)
        if message is None:
            raise CorreioError(f"no message {message_id}")
        sp = _space(store, message["space_id"])
        module = protocol_of(sp)
        if message["to_agent"] != agent:
            raise CorreioError("receipt actor is not the message recipient")
        if check_pane:
            verify_pane(store.members(sp["id"], include_left=True), agent, sp["id"])
        new = {"message_id": message_id, "agent": agent, "accepted": bool(accepted), "disposition": disposition,
               "message_sha256": message["sha256"], "receipted_at": store.now()}
        existing = store.receipt(message_id)
        if existing:
            identity = ("agent", "accepted", "disposition", "message_sha256")
            if all(existing[key] == new[key] for key in identity):
                return {**existing, "idempotent": True}
            raise CorreioError(f"conflicting receipt exists for {message_id}")
        try:
            module.validate_receipt(sp, message, new, store)
        except ValueError as exc:
            raise CorreioError(str(exc)) from exc
        store.x("INSERT INTO receipts(message_id, agent, accepted, disposition, message_sha256, receipted_at) "
                "VALUES (?,?,?,?,?,?)", (message_id, agent, int(new["accepted"]), disposition, new["message_sha256"],
                                         new["receipted_at"]))
        if new["accepted"] and message["delivery"] == "wake":
            module.project(sp, message, new, store)
        _apply_close(store, sp, module)
        return {**new, "idempotent": False}


def receipt_all_info(store: Store, *, agent: str, disposition: str, space: str | None = None,
                     check_pane: bool = True) -> list[dict[str, Any]]:
    with store.tx():
        rows = _unreceipted(store, agent=agent, space=space, delivery="info")
        return [receipt(store, message_id=row["id"], agent=agent, disposition=disposition, check_pane=check_pane)
                for row in rows]


# -- queries ----------------------------------------------------------------------------------------------------------
def _unreceipted(store: Store, *, agent: str | None = None, space: str | None = None, delivery: str | None = None,
                 include_receipted: bool = False, open_only: bool = False) -> list[dict[str, Any]]:
    clauses, args = ["s.legacy=0"], []
    if not include_receipted:
        clauses.append("r.message_id IS NULL")
    if agent:
        clauses.append("m.to_agent=?")
        args.append(agent)
    if space:
        clauses.append("m.space_id=?")
        args.append(space)
    if delivery:
        clauses.append("m.delivery=?")
        args.append(delivery)
    if open_only:
        clauses.append("s.closed_at IS NULL")
    rows = store.q("SELECT m.id FROM messages m JOIN spaces s ON s.id=m.space_id LEFT JOIN receipts r ON "
                   "r.message_id=m.id WHERE " + " AND ".join(clauses) + " ORDER BY m.sent_at, m.rowid", args)
    return [store.message(row["id"]) for row in rows]


def summary(message: dict[str, Any]) -> dict[str, Any]:
    return {"id": message["id"], "space": message["space_id"], "thread": message["thread"], "type": message["type"],
            "delivery": message["delivery"], "from": message["from_agent"], "to": message["to_agent"],
            "subject": message["subject"], "sentAt": message["sent_at"], "sha256": message["sha256"],
            "inReplyTo": message["in_reply_to"]}


def inbox(store: Store, *, agent: str | None = None, space: str | None = None,
          include_receipted: bool = False) -> dict[str, Any]:
    pending, info, invalid = [], [], []
    for message in _unreceipted(store, agent=agent, space=space, include_receipted=include_receipted):
        sp = _space(store, message["space_id"])
        problem = protocol_of(sp).check(sp, message, store)
        item = summary(message)
        if include_receipted:
            item["receipt"] = store.receipt(message["id"])
        if problem:
            invalid.append({**item, "error": problem})
        elif message["delivery"] == "info":
            info.append(item)
        else:
            pending.append(item)
    return {"agent": agent, "count": len(pending), "pending": pending, "info": info, "invalid": invalid}


def show(store: Store, message_id: str) -> dict[str, Any]:
    message = store.message(message_id)
    if message is None:
        raise CorreioError(f"no message {message_id}")
    attachments = []
    for row in store.q("SELECT * FROM attachments WHERE message_id=? ORDER BY path", (message_id,)):
        path = pathlib.Path(row["path"])
        current = sha256_file(path) if path.is_file() else None
        attachments.append({**dict(row), "currentSha256": current, "unchanged": current == row["sha256"]})
    delivery = store.one("SELECT * FROM deliveries WHERE message_id=?", (message_id,))
    replies = [r["id"] for r in store.q("SELECT id FROM messages WHERE in_reply_to=? ORDER BY sent_at", (message_id,))]
    return {**summary(message), "fields": message["fields"], "body": message["body"],
            "envelope": message["envelope"].decode("utf-8"), "receipt": store.receipt(message_id),
            "attachments": attachments, "delivery": dict(delivery) if delivery else None, "replies": replies,
            "importedFrom": message["imported_from"]}


def thread(store: Store, key: str, space: str | None = None) -> dict[str, Any]:
    sql = "SELECT * FROM threads WHERE key=?" + (" AND space_id=?" if space else "")
    rows = store.q(sql, (key, space) if space else (key,))
    if not rows:
        raise CorreioError(f"no thread {key}")
    out = []
    for row in rows:
        messages = [{**summary(store.message(m["id"])), "receipt": store.receipt(m["id"])}
                    for m in store.q("SELECT id FROM messages WHERE thread_id=? ORDER BY sent_at, rowid", (row["id"],))]
        out.append({**dict(row), "messages": messages})
    return {"threads": out}


def unanswered(store: Store, space: dict[str, Any]) -> list[dict[str, Any]]:
    if space["legacy"]:
        return []
    types = sorted(protocol_of(space).UNANSWERED)
    if not types:
        return []
    # Courier mail and imported v1 mail (which had no replies to link) never count as waiting for an answer.
    rows = store.q(f"SELECT m.id FROM messages m WHERE m.space_id=? AND m.type IN ({','.join('?' * len(types))}) "
                   "AND m.imported_from IS NULL AND m.from_agent NOT IN ('correio', 'swarmctl') "
                   "AND NOT EXISTS (SELECT 1 FROM messages x WHERE x.in_reply_to=m.id) ORDER BY m.sent_at",
                   (space["id"], *types))
    return [summary(store.message(r["id"])) for r in rows]


def overview(store: Store, space: str | None = None) -> dict[str, Any]:
    """What needs attention: open spaces, open threads, unanswered requests, undelivered mail, the courier."""
    now = store.clock.epoch()
    spaces = [store.space(space)] if space else list_spaces(store, open_only=True)
    result: dict[str, Any] = {"spaces": [], "heartbeat": {}, "jobs": jobs_list(store)}
    for row in store.q("SELECT * FROM heartbeat ORDER BY component"):
        result["heartbeat"][row["component"]] = {"pid": row["pid"], "at": row["at"],
                                                 "ageSeconds": round(now - row["epoch"], 1)}
    for sp in spaces:
        if sp is None:
            raise CorreioError(f"no space {space}")
        threads = [dict(r) for r in store.q(
            "SELECT t.key, t.subject, t.state, COUNT(m.id) AS messages, MAX(m.sent_at) AS lastAt FROM threads t "
            "LEFT JOIN messages m ON m.thread_id=t.id WHERE t.space_id=? AND t.state='open' GROUP BY t.id "
            "ORDER BY lastAt DESC", (sp["id"],))]
        waiting = []
        for message in ([] if sp["legacy"] else _unreceipted(store, space=sp["id"], delivery="wake")):
            delivery = store.one("SELECT * FROM deliveries WHERE message_id=?", (message["id"],))
            sent = parse_iso(message["sent_at"])
            waiting.append({**summary(message), "ageSeconds": round(now - sent, 1) if sent else None,
                            "attempts": delivery["attempts"] if delivery else 0,
                            "lastAction": delivery["last_action"] if delivery else None,
                            "escalatedAt": delivery["escalated_at"] if delivery else None})
        info = {} if sp["legacy"] else {
            r["to_agent"]: r["n"] for r in store.q(
                "SELECT m.to_agent, COUNT(*) AS n FROM messages m LEFT JOIN receipts r ON r.message_id=m.id WHERE "
                "m.space_id=? AND m.delivery='info' AND r.message_id IS NULL GROUP BY m.to_agent", (sp["id"],))}
        result["spaces"].append({
            "id": sp["id"], "kind": sp["kind"], "protocol": f"{sp['protocol']}/{sp['version']}",
            "legacy": sp["legacy"], "state": store.space_state(sp["id"]).get("state", sp["state"]),
            "closedAt": sp["closed_at"], "openThreads": threads, "unanswered": unanswered(store, sp),
            "undelivered": waiting, "unreadInfo": info,
            "members": {n: {"role": m["role"], "generation": m["generation"], "blocked": m["blocked"],
                            "attributes": m["attributes"]} for n, m in store.members(sp["id"]).items()},
            "tasks": store.tasks(sp["id"]) if sp["kind"] == "swarm" else []})
    return result


def search(store: Store, text: str, *, space: str | None = None, limit: int = 50) -> dict[str, Any]:
    if not text.strip():
        raise CorreioError("search needs text")
    if store.fts:
        query = " ".join('"' + word.replace('"', '""') + '"' for word in text.split())
        sql = ("SELECT m.id FROM messages_fts f JOIN messages m ON m.rowid=f.rowid WHERE messages_fts MATCH ?"
               + (" AND m.space_id=?" if space else "") + " ORDER BY m.sent_at DESC LIMIT ?")
        args: list[Any] = [query, *([space] if space else []), limit]
        mode = "fts5"
    else:
        sql = ("SELECT id FROM messages m WHERE (m.subject LIKE ? OR m.body LIKE ?)"
               + (" AND m.space_id=?" if space else "") + " ORDER BY m.sent_at DESC LIMIT ?")
        like = f"%{text}%"
        args = [like, like, *([space] if space else []), limit]
        mode = "like"
    return {"mode": mode, "results": [summary(store.message(r["id"])) for r in store.q(sql, args)]}


# -- export ------------------------------------------------------------------------------------------------------------
def export_space(store: Store, space_id: str, out: os.PathLike[str] | str) -> dict[str, Any]:
    """Evidence archive: one .md per message (its exact envelope bytes), messages.jsonl, space.json, SHA256SUMS."""
    sp = _space(store, space_id)
    out = pathlib.Path(out).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise CorreioError(f"export directory is not empty: {out}")
    (out / "messages").mkdir(parents=True, exist_ok=True)
    sums: list[str] = []
    lines: list[str] = []
    rows = store.q("SELECT id FROM messages WHERE space_id=? ORDER BY sent_at, rowid", (space_id,))
    for n, row in enumerate(rows, 1):
        message = store.message(row["id"])
        name = f"messages/{n:05d}-{message['id']}.md"
        (out / name).write_bytes(message["envelope"])
        sums.append(f"{message['sha256']}  {name}")
        attachments = [dict(a) for a in store.q("SELECT path, sha256, bytes FROM attachments WHERE message_id=?",
                                                 (message["id"],))]
        lines.append(json.dumps({**summary(message), "file": name, "fields": message["fields"],
                                 "receipt": store.receipt(message["id"]), "attachments": attachments,
                                 "importedFrom": message["imported_from"]}, sort_keys=True, ensure_ascii=False))
    (out / "messages.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    space_doc = {"space": {k: v for k, v in sp.items()}, "state": store.space_state(space_id),
                 "members": store.members(space_id, include_left=True), "tasks": store.tasks(space_id),
                 "threads": [dict(r) for r in store.q("SELECT * FROM threads WHERE space_id=? ORDER BY id",
                                                      (space_id,))]}
    (out / "space.json").write_text(json.dumps(space_doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
    for name in ("messages.jsonl", "space.json"):
        sums.append(f"{sha256_file(out / name)}  {name}")
    (out / "SHA256SUMS").write_text("".join(s + "\n" for s in sums), encoding="utf-8")
    return {"space": space_id, "out": str(out), "messages": len(rows), "sha256sums": sha256_file(out / "SHA256SUMS")}


# -- system mail ------------------------------------------------------------------------------------------------------------
def system_mail(store: Store, *, to: str, type: str, subject: str, body: str, thread: str,
                space: str | None = None) -> dict[str, Any] | None:
    """Mail from the courier itself, in the orchestration space; skipped when ``to`` is not a member there."""
    try:
        space_id = resolve_space(store, space)
    except CorreioError:
        return None
    if store.member(space_id, to) is None:
        return None
    return send(store, space=space_id, sender="correio", to=to, type=type, thread=thread, subject=subject[:300],
                body=body, system=True)


# -- host job queue ------------------------------------------------------------------------------------------------------------
JOB_KINDS = {"gate", "lote", "janela"}


def _job(row: Any) -> dict[str, Any]:
    return dict(row) if row else None


def jobs_add(store: Store, *, kind: str, who: str, cmd: str, priority: int = 0, job_id: str | None = None,
             at: str | None = None) -> dict[str, Any]:
    if kind not in JOB_KINDS:
        raise CorreioError(f"job kind is one of {sorted(JOB_KINDS)}")
    if not cmd.strip():
        raise CorreioError("job needs a command")
    job_id = job_id or uuid.uuid4().hex[:8]
    with store.tx():
        store.x("INSERT INTO jobs(id, kind, who, cmd, priority, state, at) VALUES (?,?,?,?,?,?,?)",
                (job_id, kind, who, cmd, int(priority), "queued", at or store.now()))
        return _job(store.one("SELECT * FROM jobs WHERE id=?", (job_id,)))


def jobs_next(store: Store) -> dict[str, Any] | None:
    """Claim the next queued job (highest priority, then arrival) unless one is running."""
    with store.tx():
        if store.one("SELECT 1 FROM jobs WHERE state='running'"):
            return None
        row = store.one("SELECT * FROM jobs WHERE state='queued' ORDER BY priority DESC, seq LIMIT 1")
        if row is None:
            return None
        store.x("UPDATE jobs SET state='running', started_at=? WHERE id=?", (store.now(), row["id"]))
        return _job(store.one("SELECT * FROM jobs WHERE id=?", (row["id"],)))


def jobs_start(store: Store, job_id: str) -> dict[str, Any]:
    with store.tx():
        cur = store.x("UPDATE jobs SET state='running', started_at=? WHERE id=? AND state='queued'",
                      (store.now(), job_id))
        if cur.rowcount != 1:
            raise CorreioError(f"job {job_id} is not queued")
        return _job(store.one("SELECT * FROM jobs WHERE id=?", (job_id,)))


def jobs_finish(store: Store, job_id: str, exit_code: int) -> dict[str, Any]:
    with store.tx():
        cur = store.x("UPDATE jobs SET state='done', exit=?, ended_at=? WHERE id=? AND state='running'",
                      (int(exit_code), store.now(), job_id))
        if cur.rowcount != 1:
            raise CorreioError(f"job {job_id} is not running")
        return _job(store.one("SELECT * FROM jobs WHERE id=?", (job_id,)))


def jobs_list(store: Store, *, everything: bool = False, last: int | None = None) -> list[dict[str, Any]]:
    if last:
        rows = store.q("SELECT * FROM (SELECT * FROM jobs ORDER BY seq DESC LIMIT ?) ORDER BY seq", (last,))
    elif everything:
        rows = store.q("SELECT * FROM jobs ORDER BY seq")
    else:
        rows = store.q("SELECT * FROM jobs WHERE state IN ('queued','running') "
                       "ORDER BY state='queued', priority DESC, seq")
    return [dict(r) for r in rows]
