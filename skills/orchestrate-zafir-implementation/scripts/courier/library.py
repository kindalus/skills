"""Courier v2 operations: spaces, members, send, receipt, queries, export and the host job queue.

Every write runs in one short ``BEGIN IMMEDIATE`` transaction. ``send`` builds the envelope, validates it
with the protocol module pinned by the space, and stores it; an INFO is projected on send. ``receipt``
records the recipient's verdict and, for an accepted wake message, applies the protocol's projection in
the same transaction.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import uuid
from typing import Any, Iterable

from . import envelope as env
from . import protocols
from .store import CourierError, Store, parse_iso

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
CLI = f"python3 {SCRIPTS / 'courier.py'}"


def cli_for(db: os.PathLike[str] | str) -> str:
    """The CLI as an agent must type it: always with ``--db``, since an agent never inherits the courier's
    environment ($COURIER_DB) and would otherwise read the default database."""
    import shlex
    return f"{CLI} --db {shlex.quote(str(pathlib.Path(db).resolve()))}"
SPACE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ROLE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAX_DISPOSITION = 1000
# The courier's receipt for an agent that cannot write one (a read-only sandbox), after a delivered prompt.
READONLY_DISPOSITION = "delivered to a read-only agent (courier receipt)"
# The courier's own sender name. Mail and receipts written before its rename, and spaces on a protocol published
# before it (orchestration/1.0.0, whose SYSTEM_SENDERS is {"correio"}), carry LEGACY_COURIER: it is the courier too.
COURIER, LEGACY_COURIER = "courier", "correio"
COURIER_SENDERS = {COURIER, LEGACY_COURIER}
SERVICE_SENDERS = COURIER_SENDERS | {"swarmctl"}
SERVICE_RECEIPTERS = {COURIER}
# v1 mail (the file mailbox) types requests and deliveries as these.
V1_REQUEST, V1_DELIVERY = "PEDIDO", "ENTREGA"
# The type of a request and of a delivery, for the protocols published before modules named them (REQUEST_TYPE and
# DELIVERY_TYPE): the courier's own mail, v1 imports and the rollback map through these, never through literals.
LEGACY_MAIL_TYPES = {("orchestration", "1.0.0"): {"request": V1_REQUEST, "delivery": V1_DELIVERY}}


def sha256_file(path: os.PathLike[str] | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protocol_of(space: dict[str, Any]):
    if space["legacy"]:
        raise CourierError(f"space {space['id']} is a legacy {space['protocol']} {space['version']} import: read-only")
    try:
        return protocols.load(space["protocol"], space["version"])
    except protocols.ProtocolMissing as exc:
        raise CourierError(str(exc)) from exc


def mail_type(space: dict[str, Any], kind: str) -> str | None:
    """The type ``kind`` (``request`` or ``delivery``) has in the space's protocol, or None when it has none."""
    module = protocol_of(space)
    named = getattr(module, f"{kind.upper()}_TYPE", None)
    if named is not None:
        return named
    return LEGACY_MAIL_TYPES.get((space["protocol"], space["version"]), {}).get(kind)


def from_v1_type(space: dict[str, Any], module: Any, v1_type: Any) -> str:
    """The space's type for a v1 message: its request or delivery type, the same type when the protocol has it,
    else INFO."""
    kind = {V1_REQUEST: "request", V1_DELIVERY: "delivery"}.get(v1_type)
    mapped = mail_type(space, kind) if kind else None
    if mapped in module.TYPES:
        return mapped
    return v1_type if v1_type in module.TYPES else "INFO"


def _space(store: Store, space_id: str) -> dict[str, Any]:
    space = store.space(space_id)
    if space is None:
        raise CourierError(f"no space {space_id}")
    return space


def resolve_space(store: Store, space_id: str | None = None) -> str:
    """The named space, else $COURIER_SPACE, else the one open orchestration space."""
    space_id = space_id or os.environ.get("COURIER_SPACE")
    if space_id:
        _space(store, space_id)
        return space_id
    rows = store.q("SELECT id FROM spaces WHERE kind='orchestration' AND legacy=0 AND closed_at IS NULL")
    if len(rows) != 1:
        raise CourierError("name the space with --space (there is not exactly one open orchestration space)")
    return rows[0]["id"]


# -- spaces and members ----------------------------------------------------------------------------------------
def create_space(store: Store, *, space_id: str, kind: str, protocol: str, version: str, slice_id: str | None = None,
                 prefix: str | None = None, run_dir: str | None = None, repo_path: str | None = None,
                 base_sha: str | None = None, spec_path: str | None = None, contract: dict[str, Any] | None = None,
                 legacy: bool = False, state: str | None = None) -> dict[str, Any]:
    if not SPACE_ID.match(space_id):
        raise CourierError(f"invalid space id: {space_id!r}")
    if kind not in {"orchestration", "swarm"}:
        raise CourierError("kind is orchestration or swarm")
    if not legacy:
        try:
            module = protocols.load(protocol, version)
        except protocols.ProtocolMissing as exc:
            raise CourierError(str(exc)) from exc
        if kind == "swarm" and module.NAME != "swarm":
            raise CourierError("a swarm space uses the swarm protocol")
        if kind == "swarm" and not isinstance(contract, dict):
            raise CourierError("a swarm space needs its launch contract (--contract)")
    initial = state or ("open" if kind == "orchestration" else "starting")
    with store.tx():
        existing = store.space(space_id)
        if existing:
            same = (existing["kind"], existing["protocol"], existing["version"], existing["legacy"]) == (
                kind, protocol, version, legacy) and (contract is None or existing["contract"] == contract)
            if not same:
                raise CourierError(f"space {space_id} already exists with another kind, protocol, version or contract")
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


def upgrade_space(store: Store, space_id: str, target: str) -> dict[str, Any]:
    """Move an open space to a newer published version of its own protocol (``target`` is ``name/version``).

    Stored mail keeps its bytes and its version; from here on the space validates, projects and stamps new mail
    with the newer module. The ``spaces_pinned`` trigger is lifted only inside this transaction, for this one
    update, and restored from its own definition before the commit. Rerunning at the target changes nothing."""
    name, slash, version = str(target).partition("/")
    if not slash:
        raise CourierError("the protocol is name/version, for example swarm/3.0.1")
    with store.tx():
        sp = _space(store, space_id)
        if sp["legacy"]:
            raise CourierError(f"space {space_id} is a legacy {sp['protocol']} {sp['version']} import: read-only")
        if sp["closed_at"]:
            raise CourierError(f"space {space_id} is closed ({sp['state']}): only an open space is upgraded")
        if name != sp["protocol"]:
            raise CourierError(f"a space keeps its protocol ({sp['protocol']}); only its version moves")
        if version == sp["version"]:
            return {**sp, "upgradedFrom": None}
        try:
            protocols.load(name, version)
        except protocols.ProtocolMissing as exc:
            raise CourierError(str(exc)) from exc
        new, old = (tuple(map(int, v.split("."))) for v in (version, sp["version"]))
        if new < old:
            raise CourierError(f"{name}/{version} is older than the space's {sp['version']}")
        if new[0] != old[0]:
            raise CourierError(f"an upgrade stays within major version {old[0]}")
        pin = store.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='spaces_pinned'")
        if pin is None:
            raise CourierError("the spaces_pinned trigger is missing; refusing to upgrade")
        store.x("DROP TRIGGER spaces_pinned")
        store.x("UPDATE spaces SET version=? WHERE id=?", (version, space_id))
        store.x(pin["sql"])
    return {**_space(store, space_id), "upgradedFrom": sp["version"]}


def list_spaces(store: Store, *, open_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT id FROM spaces" + (" WHERE closed_at IS NULL" if open_only else "") + " ORDER BY created_at, id"
    return [_space(store, row["id"]) for row in store.q(sql)]


def add_member(store: Store, space_id: str, agent: str, role: str, *, generation: int = 1,
               pane_id: str | None = None, workspace_id: str | None = None, configuration: Any = None,
               attributes: dict[str, Any] | None = None, ready: bool = False) -> dict[str, Any]:
    if not env.NAME.match(agent) or agent in SERVICE_SENDERS:
        raise CourierError(f"invalid or reserved agent name: {agent!r}")
    if not ROLE.match(role):
        raise CourierError(f"invalid role: {role!r}")
    if type(generation) is not int or generation < 1:
        raise CourierError("generation must be a positive integer")
    with store.tx():
        _space(store, space_id)
        current = store.member(space_id, agent)
        if current and current["left_at"] is None:
            if current["role"] != role:
                raise CourierError(f"{agent} is already a {current['role']} of {space_id}")
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
        raise CourierError(f"cannot update {sorted(unknown)}")
    if "generation" in cols and (type(cols["generation"]) is not int or cols["generation"] < 1):
        raise CourierError("generation must be a positive integer")
    with store.tx():
        member = store.member(space_id, agent)
        if member is None:
            raise CourierError(f"no member {agent} in space {space_id}")
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
            raise CourierError(f"no member {agent} in space {space_id}")
        store.update_member(space_id, agent, left_at=store.now())
        return store.member(space_id, agent)


def bump_generation(store: Store, space_id: str, agent: str, *, to: int | None = None) -> int:
    """Generation N+1 for a restarted agent (idempotent when ``to`` is already reached)."""
    with store.tx():
        member = store.member(space_id, agent)
        if member is None:
            raise CourierError(f"no member {agent} in space {space_id}")
        target = to if to is not None else member["generation"] + 1
        if member["generation"] not in {target - 1, target}:
            raise CourierError(f"{agent} is at generation {member['generation']}, not {target - 1}")
        store.update_member(space_id, agent, generation=target, ready=0)
        return target


# -- sender authenticity --------------------------------------------------------------------------------------------
def _herdr_result(*argv: str) -> dict[str, Any] | None:
    """One read-only Herdr call ($COURIER_HERDR names another binary); None when it fails."""
    import subprocess
    try:
        proc = subprocess.run([os.environ.get("COURIER_HERDR", "herdr"), *argv], capture_output=True, text=True,
                              timeout=10)
        return json.loads(proc.stdout).get("result") if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _ancestry() -> set[int]:
    """This process and its ancestors, by /proc."""
    chain, pid = set(), os.getpid()
    while pid > 1 and pid not in chain:
        chain.add(pid)
        try:
            stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
            pid = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return chain


def runs_in_pane(recorded: str) -> bool:
    """Whether Herdr shows this process inside ``recorded``: the pane's shell or one of its foreground processes
    (the agent) is an ancestor of this process. No environment variable plays a part."""
    info = (_herdr_result("pane", "process-info", "--pane", recorded) or {}).get("process_info")
    if not isinstance(info, dict):
        return False
    pids = {info.get("shell_pid"), info.get("foreground_process_group_id")}
    pids |= {p.get("pid") for p in info.get("foreground_processes") or [] if isinstance(p, dict)}
    return bool(pids & _ancestry())


def verify_pane(members: dict[str, dict[str, Any]], agent: str, space_id: str = "") -> None:
    """Inside Herdr ($HERDR_PANE_ID set) an agent acts only as itself: it must run in the pane recorded for it
    in the space. Outside Herdr nothing is checked.

    $HERDR_PANE_ID is the fast path. It is inherited, so it goes stale when Herdr renumbers a pane (a
    reorganized workspace); when it differs from the recorded pane, Herdr itself decides (``runs_in_pane``): the
    caller is accepted only if its process tree runs inside the recorded pane. No proof, no send.

    Service processes are the explicit exception: the courier's own mail goes through ``system_mail``
    (``system=True``, sender ``courier``, or ``correio`` on a protocol published before the rename) and swarmctl's
    INFO through ``system=True`` (sender ``swarmctl``); neither runs in an agent's pane. The orchestrator's host
    scripts run without $HERDR_PANE_ID.
    """
    pane = os.environ.get("HERDR_PANE_ID")
    if not pane:
        return
    member = members.get(agent)
    recorded = member.get("pane_id") if member else None
    where = space_id or "this space"
    if not recorded:
        raise CourierError(f"{agent} has no pane recorded in {where}, so this pane ({pane}) "
                           f"cannot act as it: record it with courier member update --agent {agent} --pane {pane}")
    if recorded != pane and not runs_in_pane(recorded):
        raise CourierError(
            f"{agent} is recorded in pane {recorded}, and this process (HERDR_PANE_ID {pane}) does not run in it: "
            "Herdr does not show its process tree there. Agents send and receipt only as "
            f"themselves. If you are {agent} and your pane changed, ask the orchestrator to record your current "
            f"pane (herdr agent get {agent} shows it): courier member update --space {space_id or '<space>'} "
            f"--agent {agent} --pane <pane>. Do not rewrite HERDR_PANE_ID.")


# -- the v1 transition ----------------------------------------------------------------------------------------------
SLICE_IN_TEXT = re.compile(r"\b[Ss](\d{3,4})\b")
REQUEST_IN_TEXT = re.compile(r"\b(REQUEST-\d+|TESTE-\d+)\b")
COMPAT_V1 = "v1_compat_until"


def infer_thread(subject: Any, body: Any, payload: dict[str, Any] | None = None) -> str:
    """The thread of a v1 message: its slice (S606) or general, plus /<request> when it names one."""
    text = f"{subject or ''} {body or ''}"
    slice_match = SLICE_IN_TEXT.search(text)
    request = (payload or {}).get("request")
    if not request and REQUEST_IN_TEXT.search(text):
        request = REQUEST_IN_TEXT.search(text).group(1)
    thread = f"S{slice_match.group(1)}" if slice_match else "general"
    if request and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(request)):
        thread = f"{thread}/{request}"
    return thread


def compat_v1(store: Store) -> dict[str, Any]:
    """The cutover window in which v1 ``send`` (no --thread, --payload-file) still works."""
    row = store.one("SELECT value FROM meta WHERE key=?", (COMPAT_V1,))
    until = row[0] if row else None
    end = parse_iso(until) if until else None
    return {"until": until, "active": bool(end and end > store.clock.epoch()), "sync": store.observer("v1-sync")}


def set_compat_v1(store: Store, *, until: str | None) -> dict[str, Any]:
    with store.tx():
        if until is None:
            store.x("DELETE FROM meta WHERE key=?", (COMPAT_V1,))
        else:
            if parse_iso(until) is None:
                raise CourierError(f"not an ISO time: {until!r}")
            store.x("INSERT OR REPLACE INTO meta VALUES (?, ?)", (COMPAT_V1, until))
    return compat_v1(store)


def resolve_message(store: Store, ref: str, agent: str | None = None) -> str:
    """A message id; an imported v1 id (``fields.legacyId``) of a message to ``agent`` also names it."""
    if store.message(ref) is not None:
        return ref
    rows = store.q("SELECT id FROM messages WHERE json_extract(fields, '$.legacyId')=? AND imported_from IS NOT NULL"
                   + (" AND to_agent=?" if agent else ""), (ref, agent) if agent else (ref,))
    if len(rows) == 1:
        return rows[0]["id"]
    raise CourierError(f"no message {ref}" + (f" for {agent}" if agent else ""))


# -- send and receipt ------------------------------------------------------------------------------------------------
def attachment(path: os.PathLike[str] | str) -> dict[str, Any]:
    resolved = pathlib.Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise CourierError(f"attachment is not a file: {resolved}")
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
            raise CourierError(f"message {parsed['id']} already exists with other bytes")
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
            raise CourierError("message id must be a canonical lowercase UUID") from exc
    message_id = message_id or str(uuid.uuid4())
    items = [attachment(p) for p in attachments]
    with store.tx():
        sp = _space(store, space)
        module = protocol_of(sp)
        if sp["closed_at"]:
            raise CourierError(f"space {space} is closed ({sp['state']})")
        members = store.members(space)
        if not system and check_pane:
            verify_pane(members, sender, space)
        draft = {"type": type, "thread": thread, "subject": subject, "fields": dict(fields or {})}
        try:
            module.prepare(sp, draft)
        except (ValueError, KeyError) as exc:
            raise CourierError(str(exc)) from exc
        if generation is None and not system:
            if getattr(module, "REQUIRES_GENERATION", False):
                raise CourierError(f"{sp['protocol']} {sp['version']} needs --generation")
            if sender in members:
                generation = members[sender]["generation"]
        if not draft.get("thread"):
            raise CourierError("--thread is required (the slice or the request, for example S606 or general)")
        if not draft.get("subject"):
            raise CourierError("--subject is required")
        header = {env.MARKER: env.COURIER, "id": message_id, "space": space, "protocol": sp["protocol"],
                  "version": sp["version"], "thread": draft["thread"], "type": type, "from": sender,
                  "from_generation": generation, "to": to, "in_reply_to": reply_to, "sent_at": store.now(),
                  "subject": draft["subject"]}
        try:
            data = env.emit(header, draft["fields"], items, body)
            parsed = env.parse(data)
            module.validate_send(sp, members, parsed, store, system=system)
        except ValueError as exc:
            raise CourierError(str(exc)) from exc
        if store.message(message_id):
            raise CourierError(f"message {message_id} already exists")
        delivery = module.TYPES[type]
        message = store_message(store, sp, data, parsed, delivery)
        if delivery == "info":
            module.project(sp, message, None, store)
            _apply_close(store, sp, module)
        result = {"id": message_id, "space": space, "thread": parsed["thread"], "type": type, "to": to,
                  "delivery": delivery, "sha256": message["sha256"]}
        if self_receipt is not None:
            if to != sender:
                raise CourierError("--self-receipt is only for a message to yourself")
            result["receipt"] = receipt(store, message_id=message_id, agent=sender, disposition=self_receipt,
                                        check_pane=check_pane)
        return result


def receipt(store: Store, *, message_id: str, agent: str, disposition: str, accepted: bool = True,
            check_pane: bool = True, by: str | None = None) -> dict[str, Any]:
    """``agent`` is the recipient; ``by`` names a service that receipts for it (only the courier, for a
    read-only agent), recorded in ``receipted_by``."""
    if by is not None and by not in SERVICE_RECEIPTERS:
        raise CourierError(f"only {sorted(SERVICE_RECEIPTERS)} receipt for another agent")
    if not isinstance(disposition, str) or not disposition.strip():
        raise CourierError("receipt requires a nonempty disposition")
    if len(disposition) > MAX_DISPOSITION:
        raise CourierError(f"receipt disposition exceeds {MAX_DISPOSITION} characters")
    with store.tx():
        message_id = resolve_message(store, message_id, agent)
        message = store.message(message_id)
        sp = _space(store, message["space_id"])
        module = protocol_of(sp)
        if message["to_agent"] != agent:
            raise CourierError("receipt actor is not the message recipient")
        if by is not None and not getattr(module, "READONLY_RECEIPTS", False):
            raise CourierError(f"{sp['protocol']} {sp['version']} does not allow a receipt by {by}: "
                               "its receipts project state, so the recipient receipts itself")
        if check_pane and by is None:
            verify_pane(store.members(sp["id"], include_left=True), agent, sp["id"])
        new = {"message_id": message_id, "agent": agent, "accepted": bool(accepted), "disposition": disposition,
               "message_sha256": message["sha256"], "receipted_at": store.now()}
        existing = store.receipt(message_id)
        if existing:
            identity = ("agent", "accepted", "disposition", "message_sha256")
            if all(existing[key] == new[key] for key in identity):
                return {**existing, "idempotent": True}
            raise CourierError(f"conflicting receipt exists for {message_id}")
        try:
            module.validate_receipt(sp, message, new, store)
        except ValueError as exc:
            raise CourierError(str(exc)) from exc
        store.x("INSERT INTO receipts(message_id, agent, accepted, disposition, message_sha256, receipted_at, "
                "receipted_by) VALUES (?,?,?,?,?,?,?)", (message_id, agent, int(new["accepted"]), disposition,
                                                         new["message_sha256"], new["receipted_at"], by))
        new["receipted_by"] = by
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


def show(store: Store, message_id: str, agent: str | None = None) -> dict[str, Any]:
    message_id = resolve_message(store, message_id, agent)
    message = store.message(message_id)
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
        raise CourierError(f"no thread {key}")
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
    services = sorted(SERVICE_SENDERS)
    rows = store.q(f"SELECT m.id FROM messages m WHERE m.space_id=? AND m.type IN ({','.join('?' * len(types))}) "
                   f"AND m.imported_from IS NULL AND m.from_agent NOT IN ({','.join('?' * len(services))}) "
                   "AND NOT EXISTS (SELECT 1 FROM messages x WHERE x.in_reply_to=m.id) ORDER BY m.sent_at",
                   (space["id"], *types, *services))
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
            raise CourierError(f"no space {space}")
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
        raise CourierError("search needs text")
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
        raise CourierError(f"export directory is not empty: {out}")
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


# -- rollback to v1 -----------------------------------------------------------------------------------------------------
V1_TYPES = {"INFO": "INFO", "OWNER_QUESTION": V1_REQUEST, "OWNER_ANSWER": V1_DELIVERY}
# The v2 export's record in a v1 file; files exported before the rename carry LEGACY_V1_KEY.
V1_KEY, LEGACY_V1_KEY = "courierV2", "correioV2"


def to_v1_type(space: dict[str, Any], message_type: str) -> str:
    """The v1 type of a message of this space: its request and delivery types map to v1's, the rest by V1_TYPES."""
    for kind, v1_type in (("request", V1_REQUEST), ("delivery", V1_DELIVERY)):
        if message_type == mail_type(space, kind):
            return v1_type
    return V1_TYPES.get(message_type, V1_REQUEST)


def v1_id(message: dict[str, Any]) -> str:
    """The v1 id: the original one for a message imported from v1 (``imported_from`` and ``fields.legacyId``),
    else ``<sentAt as %Y%m%dT%H%M%S%fZ>-<the whole UUID in hex>``, unambiguous by construction."""
    legacy = message["fields"].get("legacyId")
    if (message.get("imported_from") and isinstance(legacy, str)
            and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", legacy)):
        return legacy
    stamp = re.sub(r"[^0-9T]", "", message["sent_at"].split("+")[0].rstrip("Z"))
    date, _, clock = stamp.partition("T")
    return f"{date}T{(clock + '000000000000')[:12]}Z-{message['id'].replace('-', '')}"


def _v1_owner(path: pathlib.Path, message: dict[str, Any]) -> bool:
    """Whether the v1 file at ``path`` is this message: the original v1 bytes it was imported from, or the file
    an earlier export wrote for it."""
    from . import legacy_v1
    if message.get("imported_from") and message["fields"].get("legacySha256") == legacy_v1.sha256_file(path):
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data.get(V1_KEY) or data.get(LEGACY_V1_KEY) or {}).get("id") == message["id"]
    except (OSError, ValueError, AttributeError):
        return False


def _v1_value(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def export_v1(store: Store, space_id: str, root: os.PathLike[str] | str) -> dict[str, Any]:
    """Convert an orchestration space back into a v1 mailbox (``inbox/<to>/<id>.json`` and ``receipts/``) that the
    v1 CLI and courier read. Into the live v1 root it adds only what is missing: a file that exists is never
    rewritten, so a rerun after the CLI swap picks up just the mail and receipts written in between. Receipted
    in v2 means receipted in v1 (a rejection keeps its verdict in the disposition), so nothing handled comes
    back and nothing unhandled is lost."""
    from . import legacy_v1
    sp = _space(store, space_id)
    if sp["kind"] != "orchestration":
        raise CourierError(f"{space_id} is a {sp['kind']} space: only orchestration mail goes back to v1; "
                           "v3 swarm runs finish on the courier (CUTOVER.md, rollback)")
    root = pathlib.Path(root).expanduser().resolve()
    counts: dict[str, Any] = {"space": space_id, "root": str(root), "messages": 0, "receipts": 0, "skipped": 0,
                              "errors": []}
    messages = [store.message(r["id"]) for r in store.q("SELECT id FROM messages WHERE space_id=? "
                                                         "ORDER BY sent_at, rowid", (space_id,))]
    # First every target and its owner, then the writes: a collision fails the whole export, before any write.
    plan, seen, collisions = [], {}, []
    for message in messages:
        ident = v1_id(message)
        path = root / "inbox" / message["to_agent"] / f"{ident}.json"
        if path in seen:
            collisions.append(f"{message['id']} and {seen[path]} both map to {path}")
            continue
        seen[path] = message["id"]
        exists = path.exists()
        if exists and not _v1_owner(path, message):
            collisions.append(f"{path} exists and is not message {message['id']}")
            continue
        target = root / "receipts" / message["to_agent"] / f"{ident}.json"
        if exists and target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                existing = {}
            owner = existing.get("messageSha256") if isinstance(existing, dict) else None
            if (not isinstance(existing, dict) or existing.get("id") != ident
                    or owner is not None and owner != legacy_v1.sha256_file(path)):
                collisions.append(f"{target} is not the receipt of {path}")
                continue
        plan.append((message, ident, path, target, exists))
    if collisions:
        raise CourierError("v1 identity collision, nothing exported: " + "; ".join(collisions[:10]))
    for message, ident, path, target, exists in plan:
        try:
            if exists:
                counts["skipped"] += 1
            else:
                payload = {k: _v1_value(v) for k, v in message["fields"].items()
                           if k not in {"legacyId", "legacySha256"}}
                attachments = [dict(a) for a in store.q("SELECT path, sha256, bytes FROM attachments WHERE "
                                                        "message_id=? ORDER BY path", (message["id"],))]
                body = message["body"] + ("".join(f"\n- anexo: {a['path']} (sha256 {a['sha256']})"
                                                  for a in attachments) if attachments else "")
                data: dict[str, Any] = {
                    "schemaVersion": 1, "id": ident, "from": message["from_agent"], "to": message["to_agent"],
                    "type": to_v1_type(sp, message["type"]), "subject": message["subject"],
                    "sentAt": message["sent_at"], "body": body,
                    V1_KEY: {"id": message["id"], "space": space_id, "thread": message["thread"],
                                  "type": message["type"], "sha256": message["sha256"],
                                  "inReplyTo": message["in_reply_to"]}}
                if payload:
                    data["payload"] = payload
                if attachments:
                    data["attachments"] = attachments
                legacy_v1.write_atomic(path, data)
                counts["messages"] += 1
            receipt = store.receipt(message["id"])
            if receipt and not target.exists():
                disposition = receipt["disposition"] if receipt["accepted"] else f"recusada: {receipt['disposition']}"
                legacy_v1.write_atomic(target, {
                    "schemaVersion": 1, "id": ident, "agent": message["to_agent"],
                    "messageSha256": legacy_v1.sha256_file(path), "disposition": disposition,
                    "receiptedAt": receipt["receipted_at"],
                    V1_KEY: {"id": message["id"], "accepted": receipt["accepted"],
                                  "receiptedBy": receipt.get("receipted_by")}})
                counts["receipts"] += 1
        except (OSError, ValueError) as exc:
            counts["errors"].append({"id": message["id"], "error": str(exc)[:300]})
    return counts


@contextlib.contextmanager
def jsonl_lock(path: os.PathLike[str] | str) -> Iterable[None]:
    """flock of ``<jsonl>.lock``, the lock the v1 queue script (rollback/lease-queue-v1.sh) takes to write."""
    old_umask = os.umask(0o077)
    try:
        handle = open(f"{path}.lock", "a")
    finally:
        os.umask(old_umask)
    with handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def export_jobs(store: Store, path: os.PathLike[str] | str) -> dict[str, Any]:
    """The ``jobs`` table back into the v1 JSONL queue, whose runner serves the first ``queued`` line: done
    jobs first, then the queued ones in v2 order (priority, then arrival), then lines only the file has (added
    by the v1 script after the swap back). Refused while a job runs; rerunning it merges again."""
    path = pathlib.Path(path)
    with store.tx():
        running = _running(store)
        if running:
            raise CourierError(f"job {running['id']} is running: wait for it (or jobs recover) before exporting")
        rows = [dict(r) for r in store.q("SELECT * FROM jobs ORDER BY state='queued', "
                                         "CASE WHEN state='queued' THEN -priority ELSE 0 END, seq")]
    with jsonl_lock(path):  # the v1 producers append under the same lock: none lands between read and replace
        known = {r["id"] for r in rows}
        extra = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if str(row.get("id")) not in known:
                        extra.append(row)
        out = []
        for r in rows:
            state = r["state"] if r["state"] != "done" else (f"done exit={r['exit']}" if r["exit"] is not None else "done")
            item = {"id": r["id"], "at": r["at"], "kind": r["kind"], "who": r["who"], "cmd": r["cmd"], "state": state}
            for key, col in (("startedAt", "started_at"), ("endedAt", "ended_at")):
                if r[col]:
                    item[key] = r[col]
            out.append(item)
        out += extra
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
        os.replace(tmp, path)
    return {"file": str(path), "rows": len(out), "fromV2": len(rows), "keptFromFile": len(extra),
            "queued": [r["id"] for r in out if r["state"] == "queued"]}


# -- system mail ------------------------------------------------------------------------------------------------------------
def system_mail(store: Store, *, to: str, kind: str, subject: str, body: str, thread: str,
                space: str | None = None) -> dict[str, Any] | None:
    """Mail from the courier itself, in the orchestration space; skipped when ``to`` is not a member there.

    ``kind`` is ``request`` or ``delivery``: the type is the one the space's protocol gives it, and the sender is
    ``courier``, or ``correio`` when the protocol was published before the rename (its SYSTEM_SENDERS)."""
    try:
        space_id = resolve_space(store, space)
    except CourierError:
        return None
    if store.member(space_id, to) is None:
        return None
    sp = _space(store, space_id)
    type = mail_type(sp, kind)
    if type is None:
        raise CourierError(f"{sp['protocol']} {sp['version']} has no {kind} type for the courier's mail")
    senders = getattr(protocol_of(sp), "SYSTEM_SENDERS", set())
    sender = LEGACY_COURIER if LEGACY_COURIER in senders and COURIER not in senders else COURIER
    return send(store, space=space_id, sender=sender, to=to, type=type, thread=thread, subject=subject[:300],
                body=body, system=True)


# -- host job queue ------------------------------------------------------------------------------------------------------------
JOB_KINDS = {"gate", "batch", "window"}
# Kinds of the v1 JSONL queue and of jobs stored before the rename.
LEGACY_JOB_KINDS = {"lote": "batch", "janela": "window"}
JOBS_CLOSED = "jobs_closed"


def job_kind(kind: Any) -> str:
    """The kind of an imported job: a known kind, a legacy one renamed, else ``batch``."""
    kind = LEGACY_JOB_KINDS.get(kind, kind)
    return kind if kind in JOB_KINDS else "batch"


def jobs_close(store: Store, reason: str) -> dict[str, Any]:
    """Barrier of a rollback: ``jobs add`` fails (and queues nothing) until ``jobs_reopen``."""
    if not reason.strip():
        raise CourierError("jobs close needs a reason (where the queue went)")
    with store.tx():
        store.x("INSERT OR REPLACE INTO meta VALUES (?, ?)", (JOBS_CLOSED, reason))
    return {"closed": reason}


def jobs_reopen(store: Store) -> dict[str, Any]:
    with store.tx():
        store.x("DELETE FROM meta WHERE key=?", (JOBS_CLOSED,))
    return {"closed": None}


def _job(row: Any) -> dict[str, Any]:
    return dict(row) if row else None


def jobs_add(store: Store, *, kind: str, who: str, cmd: str, priority: int = 0, job_id: str | None = None,
             at: str | None = None) -> dict[str, Any]:
    if kind not in JOB_KINDS:
        raise CourierError(f"job kind is one of {sorted(JOB_KINDS)}")
    if not cmd.strip():
        raise CourierError("job needs a command")
    job_id = job_id or uuid.uuid4().hex[:8]
    with store.tx():
        closed = store.one("SELECT value FROM meta WHERE key=?", (JOBS_CLOSED,))
        if closed:
            raise CourierError(f"the host queue is closed ({closed[0]}); nothing was queued")
        store.x("INSERT INTO jobs(id, kind, who, cmd, priority, state, at) VALUES (?,?,?,?,?,?,?)",
                (job_id, kind, who, cmd, int(priority), "queued", at or store.now()))
        return _job(store.one("SELECT * FROM jobs WHERE id=?", (job_id,)))


def process_identity(pid: Any) -> str | None:
    """``<boot id>:<start time>`` of a live process, or None: a PID reused later has another identity."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        boot = pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None
    fields = stat[stat.rindex(")") + 2:].split()  # fields[0] is field 3 (state); field 22 is the start time
    if fields[0] in {"Z", "X"}:
        return None
    return f"{boot}:{fields[19]}"


def _claim(store: Store, job_id: str, runner_pid: int | None) -> dict[str, Any]:
    store.x("UPDATE jobs SET state='running', started_at=?, runner_pid=?, runner_start=? WHERE id=?",
            (store.now(), runner_pid, process_identity(runner_pid), job_id))
    return _job(store.one("SELECT * FROM jobs WHERE id=?", (job_id,)))


def _running(store: Store) -> Any:
    return store.one("SELECT id FROM jobs WHERE state='running'")


def jobs_next(store: Store, *, runner_pid: int | None = None) -> dict[str, Any] | None:
    """Claim the next queued job (highest priority, then arrival) unless one is running; ``runner_pid`` is
    the runner that will wait for it."""
    with store.tx():
        if _running(store):
            return None
        row = store.one("SELECT * FROM jobs WHERE state='queued' ORDER BY priority DESC, seq LIMIT 1")
        if row is None:
            return None
        return _claim(store, row["id"], runner_pid)


def jobs_start(store: Store, job_id: str, *, runner_pid: int | None = None) -> dict[str, Any]:
    """Claim one named job; refused while another runs (one at a time, as ``next``)."""
    with store.tx():
        running = _running(store)
        if running:
            raise CourierError(f"job {running['id']} is running; one job at a time")
        if store.one("SELECT 1 FROM jobs WHERE id=? AND state='queued'", (job_id,)) is None:
            raise CourierError(f"job {job_id} is not queued")
        return _claim(store, job_id, runner_pid)


def jobs_attach(store: Store, job_id: str, pid: int) -> dict[str, Any]:
    """Record the process that runs the job's command (it may outlive its runner)."""
    identity = process_identity(pid)
    if identity is None:
        raise CourierError(f"no live process {pid}")
    with store.tx():
        cur = store.x("UPDATE jobs SET exec_pid=?, exec_start=? WHERE id=? AND state='running'", (pid, identity, job_id))
        if cur.rowcount != 1:
            raise CourierError(f"job {job_id} is not running")
        return _job(store.one("SELECT * FROM jobs WHERE id=?", (job_id,)))


def jobs_recover(store: Store) -> list[dict[str, Any]]:
    """For each running job: ``alive`` while its command or its runner is still the same process (a runner
    outlives its command until it records the exit); ``interrupted`` only when neither is, finished with exit -1
    for the orchestrator to decide."""
    report = []
    with store.tx():
        for row in store.q("SELECT * FROM jobs WHERE state='running' ORDER BY seq"):
            live = [pid for pid, start in ((row["exec_pid"], row["exec_start"]), (row["runner_pid"], row["runner_start"]))
                    if pid and start is not None and process_identity(pid) == start]
            alive = bool(live)
            pid = live[0] if live else (row["exec_pid"] or row["runner_pid"])
            if not alive:
                store.x("UPDATE jobs SET state='done', exit=-1, ended_at=? WHERE id=?", (store.now(), row["id"]))
            report.append({"id": row["id"], "action": "alive" if alive else "interrupted", "pid": pid})
    return report


def jobs_finish(store: Store, job_id: str, exit_code: int) -> dict[str, Any]:
    with store.tx():
        cur = store.x("UPDATE jobs SET state='done', exit=?, ended_at=? WHERE id=? AND state='running'",
                      (int(exit_code), store.now(), job_id))
        if cur.rowcount != 1:
            raise CourierError(f"job {job_id} is not running")
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
