"""Protocol swarm/3.0.0: the swarm event protocol of automation 2.7.0, carried by correio.

A 1:1 port of the 2.7.0 rules (swarmcore.validate_route, validate_event, validate_model_replace and the
receipt rules), plus TASK_PHASE (info), INFO (info, recorded by swarmctl for files it creates) and the
explicit projections into ``space_state``, ``tasks`` and ``members``. Published: never edit this file;
publish the next version instead. Every check raises ValueError with the reason.

Differences from 2.7.0, all additive: the payload is the envelope's one-level ``fields`` map (rich detail
goes in the Markdown body or an attachment); ``TASK_INTEGRATED`` may also go from the Principal to itself,
because without coders it is the only way to mark a task integrated; a reject receipt is always allowed,
so an event whose grant changed can be refused instead of waiting forever.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import uuid
from typing import Any

NAME = "swarm"
VERSION = "3.0.0"
EVENTS_270 = (
    "BOOT", "AGENT_READY", "SWARM_READY", "TASK_ASSIGN", "REVIEW_REQUEST",
    "CHANGES_REQUESTED", "APPROVED", "TASK_INTEGRATED", "LEASE_REQUEST", "LEASE_RELEASE",
    "BLOCKED", "MODEL_ERROR", "MODEL_REPLACE", "PAUSE", "RESUME", "CANCEL",
    "SLICE_READY", "SLICE_ACCEPTED", "SLICE_CHANGES_REQUESTED",
)
TYPES = {**{name: "wake" for name in EVENTS_270}, "TASK_PHASE": "info", "INFO": "info"}
UNANSWERED: set[str] = set()
SYSTEM_SENDERS = {"swarmctl"}
REQUIRES_GENERATION = True
AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BINDING_RE = re.compile(r"[A-Za-z0-9._:-]+")
BAD_MODEL_CHARS = set(";&|`$<>\\*?[]{}()!\n\r\x00")
EFFORTS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
HARNESSES = {"pi", "claude", "agy", "codex"}
HARNESS_EFFORTS = {"claude": {"low", "medium", "high", "xhigh", "max"},
                   "codex": {"minimal", "low", "medium", "high", "xhigh"}}
BOUND_EVENT_FIELDS = {
    "TASK_ASSIGN": {"taskId", "assignmentId", "revision"},
    "TASK_PHASE": {"taskId", "assignmentId", "revision"},
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
PHASES = {"red", "green"}
FAMILY_HINTS = (("claude", "anthropic"), ("anthropic", "anthropic"), ("opus", "anthropic"),
                ("sonnet", "anthropic"), ("haiku", "anthropic"), ("fable", "anthropic"),
                ("gemini", "google"), ("google", "google"), ("gpt", "openai"),
                ("openai", "openai"), ("codex", "openai"))
# Owner decision 2026-10-02: the one same-family reviewer ever accepted, and only through a reviewer
# MODEL_REPLACE whose fields.reviewerFallback names the reviewer's quota MODEL_ERROR.
REVIEWER_QUOTA_FALLBACK = ("codex", "gpt-6.1-sol", "high")
CODER_LETTERS = "ab"
ROSTER_KEYS = {"principal", "reviewer", "coders"}
TERMINAL = {"accepted", "cancelled"}
TASK_STATES = {"TASK_ASSIGN": "assigned", "REVIEW_REQUEST": "in-review", "CHANGES_REQUESTED": "changes-requested",
               "APPROVED": "approved", "TASK_INTEGRATED": "integrated"}
SPACE_STATES = {"SWARM_READY": "running", "LEASE_REQUEST": "lease-requested", "SLICE_READY": "ready"}


# -- launch contract (copied from swarmcore 2.7.0) ---------------------------------------------------------------
def parse_model_triple(raw: Any) -> tuple[str, str, str]:
    if not isinstance(raw, str):
        raise ValueError("model configuration must be a string")
    parts = raw.split()
    if len(parts) != 3:
        raise ValueError("model configuration must be: harness model thinking_effort")
    harness, model, effort = parts
    if harness not in HARNESSES:
        raise ValueError(f"unsupported harness: {harness}")
    if not model or model.startswith("-") or any(ch in BAD_MODEL_CHARS or ord(ch) < 32 for ch in model):
        raise ValueError("unsafe model identifier")
    if effort not in HARNESS_EFFORTS.get(harness, EFFORTS):
        raise ValueError(f"unsupported thinking effort for {harness}: {effort}")
    return harness, model, effort


def model_family(triple: str) -> str:
    harness, model, _effort = parse_model_triple(triple)
    if harness == "claude":
        return "anthropic"
    if harness == "agy":
        return "google"
    if harness == "codex":
        return "openai"
    text = model.lower()
    for hint, family in FAMILY_HINTS:
        if hint in text:
            return family
    return text.split("/", 1)[0]


def roster(launch: dict[str, Any]) -> str:
    value = launch.get("roster", {})
    if not isinstance(value, dict) or not set(value) <= ROSTER_KEYS:
        raise ValueError("roster may contain only principal, reviewer and coders")
    count = value.get("coders", 0)
    if type(count) is not int or not 0 <= count <= len(CODER_LETTERS):
        raise ValueError(f"roster.coders must be an integer from 0 to {len(CODER_LETTERS)}")
    return CODER_LETTERS[:count]


def principal_name(launch: dict[str, Any]) -> str:
    return f"{launch['prefix']}-principal"


def reviewer_name(launch: dict[str, Any]) -> str:
    return f"{launch['prefix']}-reviewer"


def coder_names(launch: dict[str, Any]) -> list[str]:
    return [f"{launch['prefix']}-coder-{letter}" for letter in roster(launch)]


def model_roles(launch: dict[str, Any]) -> set[str]:
    return {"principal", "reviewer"} | ({"coders"} if roster(launch) else set())


def allowed_agents(launch: dict[str, Any]) -> set[str]:
    return {launch["responsible"]["agent"], principal_name(launch), reviewer_name(launch), *coder_names(launch)}


def parent_of(agent: str, launch: dict[str, Any]) -> str | None:
    if agent == principal_name(launch):
        return launch["responsible"]["agent"]
    if agent == reviewer_name(launch) or agent in coder_names(launch):
        return principal_name(launch)
    return None


# -- routes ---------------------------------------------------------------------------------------------------
def validate_route(event_type: str, sender: str, recipient: str, launch: dict[str, Any]) -> None:
    if not all(isinstance(value, str) for value in (event_type, sender, recipient)):
        raise ValueError("event type, sender, and recipient must be strings")
    if event_type not in TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    agents = allowed_agents(launch)
    if sender not in agents or recipient not in agents:
        raise ValueError("event sender or recipient is not part of this run")
    responsible, principal = launch["responsible"]["agent"], principal_name(launch)
    reviewer, coders = reviewer_name(launch), set(coder_names(launch))
    implementers = {principal, *coders}
    allowed = False
    if event_type in {"BOOT", "PAUSE", "RESUME", "CANCEL"}:
        allowed = parent_of(recipient, launch) == sender
    elif event_type in {"AGENT_READY", "BLOCKED", "MODEL_ERROR"}:
        allowed = recipient == parent_of(sender, launch)
    elif event_type == "MODEL_REPLACE":
        allowed = sender == responsible and recipient == principal
    elif event_type in {"SWARM_READY", "SLICE_READY", "LEASE_REQUEST", "LEASE_RELEASE", "TASK_PHASE"}:
        allowed = sender == principal and recipient == responsible
    elif event_type in {"SLICE_ACCEPTED", "SLICE_CHANGES_REQUESTED"}:
        allowed = sender == responsible and recipient == principal
    elif event_type == "TASK_ASSIGN":
        allowed = sender == principal and recipient in implementers
    elif event_type == "TASK_INTEGRATED":
        allowed = sender == principal and recipient in implementers
    elif event_type == "REVIEW_REQUEST":
        allowed = ((sender in implementers or sender == responsible) and recipient == reviewer
                   or sender in coders and recipient == principal)
    elif event_type in {"APPROVED", "CHANGES_REQUESTED"}:
        allowed = sender == reviewer and (recipient in implementers or recipient == responsible)
    elif event_type == "INFO":
        allowed = True
    if not allowed:
        raise ValueError(f"invalid {event_type} route: {sender} -> {recipient}")


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _beneath(path: pathlib.Path, root: pathlib.Path) -> bool:
    return root in path.parents


def _check_grant(space: dict[str, Any], fields: dict[str, Any]) -> pathlib.Path:
    grant_path, grant_sha = fields.get("grantPath"), fields.get("grantSha256")
    if (not isinstance(grant_path, str) or not pathlib.Path(grant_path).is_absolute()
            or not isinstance(grant_sha, str) or not SHA256_RE.fullmatch(grant_sha)):
        raise ValueError("TASK_ASSIGN requires an absolute fields.grantPath and its grantSha256")
    grant = pathlib.Path(grant_path).expanduser().resolve()
    reports = (pathlib.Path(space["run_dir"]) / "reports").resolve()
    if not _beneath(grant, reports):
        raise ValueError(f"grant is outside allowed root: {grant}")
    if not grant.is_file() or _sha256_file(grant) != grant_sha:
        raise ValueError("TASK_ASSIGN grant file is missing or its SHA-256 differs")
    return grant


def reviewer_quota_incident(space: dict[str, Any], db: Any, event_id: Any) -> dict[str, Any]:
    """The reviewer's quota-exhausted MODEL_ERROR named by ``event_id``; immutable, so stable on revalidation."""
    launch = space["contract"]
    try:
        canonical_id = str(uuid.UUID(event_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("reviewerFallback must be the MODEL_ERROR event UUID") from exc
    if canonical_id != event_id:
        raise ValueError("reviewerFallback must use canonical lowercase UUID form")
    event = db.message(event_id)
    if (event is not None and event["space_id"] == space["id"] and event["type"] == "MODEL_ERROR"
            and event["to_agent"] in (principal_name(launch), launch["responsible"]["agent"])):
        validate_route("MODEL_ERROR", event["from_agent"], event["to_agent"], launch)
        if event["fields"].get("role") != "reviewer" or event["fields"].get("classification") != "quota-exhausted":
            raise ValueError("reviewerFallback requires a MODEL_ERROR with role reviewer and "
                             "classification quota-exhausted")
        return event
    raise ValueError("reviewerFallback does not name a MODEL_ERROR of this run")


def validate_model_replace(space: dict[str, Any], fields: dict[str, Any], db: Any) -> None:
    launch = space["contract"]
    role, configuration, incident = fields.get("role"), fields.get("configuration"), fields.get("incidentId")
    roles = model_roles(launch)
    if role not in roles:
        raise ValueError(f"MODEL_REPLACE role must be one of: {', '.join(sorted(roles))}")
    triple = parse_model_triple(configuration)
    if not isinstance(incident, str) or not incident.strip() or len(incident) > 128:
        raise ValueError("MODEL_REPLACE requires fields.incidentId")
    if "reviewerFallback" in fields:
        if role != "reviewer" or triple != REVIEWER_QUOTA_FALLBACK:
            raise ValueError("reviewerFallback is valid only for a reviewer replacement with exactly: "
                             + " ".join(REVIEWER_QUOTA_FALLBACK))
        if fields["reviewerFallback"] != incident:
            raise ValueError("reviewerFallback must equal the incidentId of the reviewer's MODEL_ERROR")
        reviewer_quota_incident(space, db, fields["reviewerFallback"])
    elif role == "reviewer":
        implementers = {model_family(launch["models"][key]) for key in roles - {"reviewer"}}
        if model_family(configuration) in implementers:
            raise ValueError("the reviewer must use a different model family from the implementers")


# -- protocol interface ---------------------------------------------------------------------------------------
def prepare(space: dict[str, Any], draft: dict[str, Any]) -> None:
    """Fill what the 2.7.0 CLI stamped: runId, and a default thread and subject."""
    launch = space["contract"]
    fields = draft.setdefault("fields", {})
    fields.setdefault("runId", launch["runId"])
    task = fields.get("taskId")
    if not draft.get("thread"):
        draft["thread"] = task if isinstance(task, str) and task else launch["sliceId"]
    if not draft.get("subject"):
        draft["subject"] = f"{draft.get('type')} {task}" if task else f"{draft.get('type')} {launch['sliceId']}"


def validate_send(space: dict[str, Any], members: dict[str, dict[str, Any]], envelope: dict[str, Any], db: Any,
                  *, system: bool = False) -> None:
    launch = space["contract"]
    kind, sender, recipient, fields = envelope["type"], envelope["from"], envelope["to"], envelope["fields"]
    if kind not in TYPES:
        raise ValueError(f"unknown event type: {kind}")
    if fields.get("runId") != launch["runId"]:
        raise ValueError("event runId mismatch")
    if system:
        if sender not in SYSTEM_SENDERS or kind != "INFO":
            raise ValueError("system mail is an INFO from swarmctl")
        if recipient not in allowed_agents(launch):
            raise ValueError("event sender or recipient is not part of this run")
    else:
        if sender in SYSTEM_SENDERS:
            raise ValueError(f"{sender} is a reserved sender")
        generation = envelope.get("from_generation")
        if type(generation) is not int or generation < 1:
            raise ValueError("fromGeneration must be positive")
        validate_route(kind, sender, recipient, launch)
        if sender not in members or recipient not in members:
            raise ValueError("event sender or recipient is not a member of this space")
        if members[sender]["generation"] != generation:
            raise ValueError("event sender generation is stale")
    if kind == "TASK_ASSIGN":
        _check_grant(space, fields)
    if kind == "MODEL_REPLACE":
        validate_model_replace(space, fields, db)
    for key in ("taskId", "assignmentId"):
        if key in fields and (not isinstance(fields[key], str) or not fields[key] or len(fields[key]) > 128
                              or not BINDING_RE.fullmatch(fields[key])):
            raise ValueError(f"{key} is invalid")
    if "revision" in fields and (type(fields["revision"]) is not int or fields["revision"] < 1):
        raise ValueError("revision must be a positive integer")
    if "candidateSha" in fields and (not isinstance(fields["candidateSha"], str)
                                     or not SHA_RE.fullmatch(fields["candidateSha"])):
        raise ValueError("candidateSha must be a full lowercase Git SHA")
    missing = BOUND_EVENT_FIELDS.get(kind, set()) - fields.keys()
    if missing:
        raise ValueError(f"{kind} missing bindings: {sorted(missing)}")
    if kind == "TASK_PHASE" and fields.get("phase") not in PHASES:
        raise ValueError("TASK_PHASE needs fields.phase red or green")


def check(space: dict[str, Any], message: dict[str, Any], db: Any) -> str | None:
    """What makes a stored event invalid later (the 2.7.0 pending and receipt rules): its sender has moved to
    another generation, or its grant was edited after dispatch."""
    generation = message.get("from_generation")
    if message["from_agent"] not in SYSTEM_SENDERS and generation is not None:
        sender = db.member(space["id"], message["from_agent"])
        if sender is not None and sender["generation"] != generation:
            return "event sender generation is stale"
    if message["type"] == "TASK_ASSIGN":
        try:
            _check_grant(space, message["fields"])
        except ValueError as exc:
            return str(exc)
    return None


def validate_receipt(space: dict[str, Any], message: dict[str, Any], receipt: dict[str, Any], db: Any) -> None:
    if receipt["accepted"]:
        problem = check(space, message, db)
        if problem:
            raise ValueError(f"cannot accept this event: {problem}; receipt it with --reject")


def _grant(fields: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(pathlib.Path(fields["grantPath"]).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, KeyError):
        return {}


def project(space: dict[str, Any], message: dict[str, Any], receipt: dict[str, Any] | None, db: Any) -> None:
    """State changes of an accepted event (an info event on send), in the transaction that accepts it."""
    if receipt is not None and not receipt["accepted"]:
        return
    launch, kind, fields = space["contract"], message["type"], message["fields"]
    sid, by = space["id"], message["id"]
    task_id = fields.get("taskId")
    state = db.space_state(sid)
    if kind in TASK_STATES or kind == "TASK_PHASE":
        if task_id == launch["sliceId"]:
            if kind in TASK_STATES:
                state["sliceReview"] = {"state": TASK_STATES[kind], "revision": fields.get("revision"),
                                        "candidateSha": fields.get("candidateSha"), "event": by}
                db.set_space_state(sid, state, by)
        else:
            cols: dict[str, Any] = {"state": TASK_STATES.get(kind) or fields["phase"]}
            if kind == "TASK_ASSIGN":
                grant = _grant(fields)
                cols.update(owner=message["to_agent"], worktree=grant.get("worktree"), branch=grant.get("branch"),
                            candidate_sha=None)
            for key, col in (("revision", "revision"), ("assignmentId", "assignment_id"),
                             ("candidateSha", "candidate_sha")):
                if key in fields:
                    cols[col] = fields[key]
            db.upsert_task(sid, task_id, by, **cols)
    # accepted and cancelled are final: a late receipt of an older event never moves the space out of them.
    terminal = state.get("state") in TERMINAL
    if kind in SPACE_STATES and not terminal:
        state["state"] = SPACE_STATES[kind]
        db.set_space_state(sid, state, by)
    if kind == "SLICE_ACCEPTED" and not terminal:
        state.update(state="accepted", acceptedSha=fields["candidateSha"])
        db.set_space_state(sid, state, by)
    if kind == "CANCEL" and message["to_agent"] == principal_name(launch) and not terminal:
        state["state"] = "cancelled"
        db.set_space_state(sid, state, by)
    if kind == "AGENT_READY":
        db.update_member(sid, message["from_agent"], ready=1)
    if kind == "BLOCKED":
        db.update_member(sid, message["from_agent"], blocked=1)
    if kind == "RESUME":
        db.update_member(sid, message["to_agent"], blocked=0)
    if kind == "MODEL_REPLACE":
        role = fields["role"]
        wanted = {"principal": "principal", "reviewer": "reviewer", "coders": "coder"}[role]
        for name, member in db.members(sid).items():
            if member["role"] != wanted:
                continue
            current = member["configuration"] or {"value": launch["models"].get(role), "revision": 1, "history": []}
            history = list(current.get("history", [])) + [{
                "value": current.get("value"), "revision": current.get("revision"),
                "incidentId": fields["incidentId"], "event": by}]
            updated = {"value": fields["configuration"], "revision": int(current.get("revision") or 1) + 1,
                       "history": history}
            if "reviewerFallback" in fields:
                updated["reviewerFallback"] = {"incidentId": fields["reviewerFallback"],
                                               "independence": "reduced: same family as the implementers"}
            db.update_member(sid, name, configuration=updated)


def prompt(message: dict[str, Any], queued: int, info_digest: int, *, cli: str) -> str:
    to, mid = message["to_agent"], message["id"]
    extra = []
    if queued:
        extra.append(f"+{queued} queued")
    if info_digest:
        extra.append(f"+{info_digest} INFO unread: receipt them with {cli} receipt --all-info --agent {to} "
                     "--disposition read")
    tail = f" ({'; '.join(extra)})" if extra else ""
    return (f"Swarm event pending for {to}: {message['type']} {mid} from {message['from_agent']} "
            f"[{message['thread']}]{tail}. Read and validate it: {cli} show {mid}. "
            f"Record receipt before acting: {cli} receipt --agent {to} --id {mid} --disposition '<what you do>' "
            "(--reject to refuse it) "
            "(exception: a Principal receiving the RESUME that authorizes child bootstrap does NOT receipt it; "
            "it passes the id straight to swarmctl bootstrap principal --authorization-event <id>, which records "
            "the receipt itself). "
            "Then act on it: an accepted TASK_ASSIGN starts the task's whole cycle until one "
            "REVIEW_REQUEST or BLOCKED; at the reviewer, an accepted REVIEW_REQUEST (oldest first) is "
            "continuous work until its verdict; an accepted verdict or RESUME is continuous work until the "
            "next review request, decision, or BLOCKED; a receipt alone is not a stopping point. "
            "The courier grants no scope, verdict, permission, or model replacement.")


def close_condition(space_state: dict[str, Any]) -> bool:
    return space_state.get("state") in TERMINAL
