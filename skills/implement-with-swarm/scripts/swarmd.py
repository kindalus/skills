#!/usr/bin/env python3
"""Receipt-driven event courier and health observer for implement-with-swarm."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import signal
import sys
import time
from typing import Any

from swarmcore import SwarmError, herdr, load_json, load_launch, now, pending_events, write_json_mutable

MAX_BACKOFF = 300.0
STOP = False


def stop(_signum: int, _frame: Any) -> None:
    global STOP
    STOP = True


def live_agents(launch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = herdr("agent", "list")
    listed = result.get("agents", [])
    agents = {a["name"]: a for a in listed if a.get("name")}
    responsible = launch["responsible"]
    named = agents.get(responsible["agent"])
    matches = [a for a in listed if a.get("pane_id") == responsible["paneId"]]
    if len(matches) > 1:
        raise SwarmError("multiple agents report the responsible pane")
    if named and named.get("pane_id") != responsible["paneId"]:
        # The recorded pane is authoritative: a same-named agent elsewhere is
        # another session, not this run's responsible. Warn, never stall the run.
        print(f"warning: responsible name {responsible['agent']!r} is live in pane "
              f"{named.get('pane_id')}, expected {responsible['paneId']}; resolving by pane",
              file=sys.stderr)
        agents.pop(responsible["agent"], None)
    if matches:
        agents[responsible["agent"]] = matches[0]
    return agents


def delay_for(attempts: int, minimum: float) -> float:
    return min(MAX_BACKOFF, minimum * (2 ** max(0, attempts - 1)))


def notify(title: str, message: str) -> None:
    with contextlib.suppress(SwarmError):
        herdr("notification", "show", title, "--body", message, "--sound", "request", timeout=5)


def cycle(root: pathlib.Path, launch: dict[str, Any], delivery: dict[str, Any],
          minimum_retry: float) -> dict[str, Any]:
    scan = pending_events(root, launch)
    agents = live_agents(launch)
    timestamp, epoch_now = now(), time.time()
    actions: list[dict[str, Any]] = []
    heads: set[str] = set()  # FIFO: only each recipient's oldest unreceipted event is delivered
    current_ids = {event["id"] for event in scan["pending"]}
    delivery["events"] = {key: value for key, value in delivery.get("events", {}).items()
                          if key in current_ids}
    for event in scan["pending"]:
        event_id, recipient = event["id"], event["to"]
        record = delivery.setdefault("events", {}).setdefault(event_id, {
            "eventPath": event["path"], "eventSha256": event["sha256"], "recipient": recipient,
            "attempts": 0, "lastAttemptEpoch": None, "lastAttemptAt": None,
        })
        if record["eventSha256"] != event["sha256"] or record["recipient"] != recipient:
            raise SwarmError(f"event identity changed after observation: {event_id}")
        agent = agents.get(recipient)
        status = agent.get("agent_status") if agent else "absent"
        last = record.get("lastAttemptEpoch")
        due = last is None or epoch_now - float(last) >= delay_for(int(record["attempts"]), minimum_retry)
        action = {"eventId": event_id, "recipient": recipient, "agentStatus": status, "action": "wait"}
        # Close the scan-to-delivery race as far as the filesystem protocol permits.
        receipted = (root / "receipts" / recipient / f"{event_id}.json").exists()
        queued = not receipted and recipient in heads
        if not receipted:
            heads.add(recipient)
        if receipted:
            action["action"] = "already-receipted"
        elif queued:
            action["action"] = "queued"
        elif status in {"idle", "done"} and due:
            message = (f"Swarm event pending for {recipient}: read and validate {event['path']}. "
                       f"Record receipt with {root / 'runtime/swarmctl.py'} before acting "
                       "(exception: a Principal receiving the RESUME that authorizes child bootstrap does NOT receipt it; "
                       "it passes the file straight to swarmctl bootstrap principal --authorization-event, which records the receipt itself). "
                       "Then act on it: an accepted TASK_ASSIGN starts the task's whole cycle until one "
                       "REVIEW_REQUEST or BLOCKED; at the reviewer, an accepted REVIEW_REQUEST (oldest first) is "
                       "continuous work until its verdict; an accepted verdict or RESUME is continuous work until the "
                       "next review request, decision, or BLOCKED; a receipt alone is not a stopping point. "
                       "The courier grants no scope, verdict, permission, or model replacement.")
            target = agent.get("name") or agent.get("pane_id")
            if not target:
                raise SwarmError(f"recipient has no prompt target: {recipient}")
            herdr("agent", "prompt", target, message, timeout=10)
            record.update(attempts=int(record["attempts"]) + 1,
                          lastAttemptEpoch=epoch_now, lastAttemptAt=timestamp,
                          lastAgentStateSeq=agent.get("state_change_seq"))
            action["action"] = "prompt"
        elif status in {"absent", "blocked"} and due:
            title = f"Swarm {launch['prefix']}: {recipient} {status}"
            message = f"Pending {event['type']} event: {event['path']}"
            notify(title, message)
            record.update(attempts=int(record["attempts"]) + 1,
                          lastAttemptEpoch=epoch_now, lastAttemptAt=timestamp,
                          lastAgentStateSeq=agent.get("state_change_seq") if agent else None)
            action["action"] = "notify"
        actions.append(action)
    invalid_records = delivery.setdefault("invalid", {})
    current_invalid: set[str] = set()
    for invalid in scan["invalid"]:
        key = hashlib.sha256(f"{invalid['path']}\0{invalid['error']}".encode()).hexdigest()
        current_invalid.add(key)
        record = invalid_records.setdefault(key, {"attempts": 0, "lastAttemptEpoch": None})
        last = record.get("lastAttemptEpoch")
        due = last is None or epoch_now - float(last) >= delay_for(int(record["attempts"]), minimum_retry)
        if due:
            notify(f"Swarm {launch['prefix']}: invalid event",
                   f"{invalid['path']}: {invalid['error'][:250]}")
            record.update(attempts=int(record["attempts"]) + 1,
                          lastAttemptEpoch=epoch_now, lastAttemptAt=timestamp)
    delivery["invalid"] = {key: value for key, value in invalid_records.items() if key in current_invalid}
    state = None
    state_path = root / "state.json"
    if state_path.exists():
        with contextlib.suppress(SwarmError):
            state = load_json(state_path)
    terminal = bool(state and (state.get("state") == "cancelled" or state.get("accepted") is True))
    status = {
        "schemaVersion": 1, "runId": launch["runId"], "pid": os.getpid(), "checkedAt": timestamp,
        "pending": scan["pending"], "invalid": scan["invalid"], "actions": actions,
        "agents": {name: agent.get("agent_status") for name, agent in agents.items()
                   if name in {event["to"] for event in scan["pending"]}},
        "terminal": terminal,
    }
    write_json_mutable(root / "supervision" / "status.json", status)
    delivery.update(schemaVersion=1, runId=launch["runId"], updatedAt=timestamp)
    write_json_mutable(root / "supervision" / "delivery.json", delivery)
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--retry-min", type=float, default=30.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.interval <= 0 or args.retry_min <= 0:
        print(json.dumps({"error": "intervals must be positive"}), file=sys.stderr)
        return 2
    try:
        root, launch = load_launch(args.run_dir)
        lock_path = root / "supervision" / "swarmd.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SwarmError("another supervisor owns this run")
            delivery_path = root / "supervision" / "delivery.json"
            delivery = load_json(delivery_path) if delivery_path.exists() else {"events": {}}
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            while not STOP:
                try:
                    status = cycle(root, launch, delivery, args.retry_min)
                except Exception as exc:
                    status = {"schemaVersion": 1, "runId": launch["runId"], "pid": os.getpid(),
                              "checkedAt": now(), "error": {"type": type(exc).__name__,
                                                               "message": str(exc)[:500]},
                              "terminal": False}
                    write_json_mutable(root / "supervision" / "status.json", status)
                if args.once or status.get("terminal"):
                    break
                time.sleep(args.interval)
        return 0
    except (SwarmError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
