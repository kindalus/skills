#!/usr/bin/env python3
"""Correio: durable mailbox and courier for the agents outside a swarm (orchestrator, spokesperson,
preparers, consultants, bug executors).

Every message is a file in inbox/<recipient>/; a receipt in receipts/<recipient>/ closes it. The courier
delivers each recipient's oldest unreceipted message (FIFO) by `herdr agent prompt`, only while the
recipient is idle or done; a blocked or absent recipient gets a Herdr notification instead. It retries
with backoff (30 s doubling, 480 s ceiling) and never gives up: the file stays until it is receipted.

  correio.py send --from A --to B --type PEDIDO|ENTREGA|INFO --subject S (--body TEXT | --body-file F)
                  [--payload-file JSON]
  correio.py receipt --agent B --id ID --disposition TEXT
  correio.py pending --agent B
  correio.py show --agent B --id ID
  correio.py daemon [--interval 10] [--retry-min 30] [--max-backoff 480]

The root is $CORREIO_ROOT or ~/.local/state/orchestrate-zafir-implementation/<repo-key>/correio, with
<repo-key> from $CORREIO_REPO_KEY (default: uwassi).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
import uuid
from typing import Any

TYPES = ("PEDIDO", "ENTREGA", "INFO")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
STOP = False


def root_dir() -> pathlib.Path:
    explicit = os.environ.get("CORREIO_ROOT")
    if explicit:
        return pathlib.Path(explicit)
    key = os.environ.get("CORREIO_REPO_KEY", "uwassi")
    return pathlib.Path.home() / ".local/state/orchestrate-zafir-implementation" / key / "correio"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def die(message: str, code: int = 2) -> None:
    print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def check_name(value: str, what: str) -> str:
    if not NAME.match(value):
        die(f"invalid {what}: {value!r}")
    return value


def private_dir(path: pathlib.Path) -> pathlib.Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def write_atomic(path: pathlib.Path, data: dict[str, Any], exclusive: bool = True) -> None:
    private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    if exclusive:
        os.link(tmp, path)  # fails if the target exists
        os.unlink(tmp)
    else:
        os.replace(tmp, path)


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: pathlib.Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def messages(root: pathlib.Path, agent: str) -> list[dict[str, Any]]:
    inbox = root / "inbox" / agent
    if not inbox.is_dir():
        return []
    found = []
    for path in sorted(inbox.glob("*.json")):
        with contextlib.suppress(OSError, ValueError):
            message = load(path)
            message["path"] = str(path)
            message["receipted"] = (root / "receipts" / agent / f"{message['id']}.json").exists()
            found.append(message)
    found.sort(key=lambda m: (m.get("sentAt", ""), m.get("id", "")))
    return found


def cmd_send(args: argparse.Namespace) -> None:
    root = root_dir()
    sender, recipient = check_name(args.sender, "sender"), check_name(args.to, "recipient")
    if (args.body is None) == (args.body_file is None):
        die("give exactly one of --body or --body-file")
    message_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    message: dict[str, Any] = {
        "schemaVersion": 1, "id": message_id, "from": sender, "to": recipient, "type": args.type,
        "subject": args.subject, "sentAt": now(),
    }
    if args.body is not None:
        message["body"] = args.body
    else:
        body = pathlib.Path(args.body_file).resolve()
        if not body.is_file():
            die(f"body file not found: {body}")
        message["bodyFile"] = {"path": str(body), "sha256": sha256_file(body)}
    if args.payload_file:
        payload_path = pathlib.Path(args.payload_file)
        message["payload"] = load(payload_path)
    path = root / "inbox" / recipient / f"{message_id}.json"
    write_atomic(path, message)
    print(json.dumps({"id": message_id, "path": str(path), "sha256": sha256_file(path)}))


def cmd_receipt(args: argparse.Namespace) -> None:
    root = root_dir()
    agent = check_name(args.agent, "agent")
    path = root / "inbox" / agent / f"{args.id}.json"
    if not path.is_file():
        die(f"no such message for {agent}: {args.id}")
    receipt = {"schemaVersion": 1, "id": args.id, "agent": agent, "messageSha256": sha256_file(path),
               "disposition": args.disposition, "receiptedAt": now()}
    out = root / "receipts" / agent / f"{args.id}.json"
    try:
        write_atomic(out, receipt)
    except FileExistsError:
        die(f"already receipted: {args.id}", 1)
    print(json.dumps({"receiptPath": str(out), "sha256": sha256_file(out)}))


def cmd_pending(args: argparse.Namespace) -> None:
    root = root_dir()
    agent = check_name(args.agent, "agent")
    pending = [{k: m.get(k) for k in ("id", "from", "type", "subject", "sentAt", "path")}
               for m in messages(root, agent) if not m["receipted"]]
    print(json.dumps({"agent": agent, "count": len(pending), "pending": pending}, ensure_ascii=False, indent=1))


def cmd_show(args: argparse.Namespace) -> None:
    root = root_dir()
    path = root / "inbox" / check_name(args.agent, "agent") / f"{args.id}.json"
    if not path.is_file():
        die(f"no such message: {args.id}")
    print(path.read_text(encoding="utf-8"), end="")


def herdr(*argv: str, timeout: float = 15) -> dict[str, Any]:
    binary = os.environ.get("CORREIO_HERDR", "herdr")
    proc = subprocess.run([binary, *argv], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"herdr exit {proc.returncode}")
    with contextlib.suppress(ValueError):
        return json.loads(proc.stdout).get("result", {})
    return {}


def delay_for(attempts: int, minimum: float, ceiling: float) -> float:
    return min(ceiling, minimum * (2 ** min(32, max(0, attempts - 1))))  # cap the exponent: a float overflows past 2**1023


def prompt_text(root: pathlib.Path, message: dict[str, Any], queued: int, readonly: bool = False) -> str:
    me = pathlib.Path(__file__).resolve()
    tail = f" (+{queued} na fila)" if queued else ""
    if readonly:  # a sandboxed agent cannot write receipts or mail: the courier receipts, it answers in its text
        return (f"Correio {message['type']} de {message['from']}: {message['subject']}{tail}. "
                f"Lê {message['path']}. O recibo fica registado pelo estafeta. "
                "Responde no teu texto final: o remetente lê-o do teu transcript.")
    return (f"Correio {message['type']} de {message['from']}: {message['subject']}{tail}. "
            f"Lê {message['path']}. Antes de agir, regista o recibo: "
            f"python3 {me} receipt --agent {message['to']} --id {message['id']} --disposition '<o que fazes>'. "
            "Responde pela tua caixa de correio (correio.py send), nunca por herdr agent prompt.")


def system_mail(root: pathlib.Path, to: str, kind: str, subject: str, body: str) -> None:
    message_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    write_atomic(root / "inbox" / to / f"{message_id}.json", {
        "schemaVersion": 1, "id": message_id, "from": "correio", "to": to, "type": kind,
        "subject": subject, "sentAt": now(), "body": body})


def observe(root: pathlib.Path, state: dict[str, Any], agents: dict[str, dict[str, Any]], args: argparse.Namespace) -> None:
    """Turn agent transitions and ref advances into mail for the watcher (--watch-to), so nobody re-arms watchers."""
    if not args.watch_to:
        return
    seen = state.setdefault("agentStatus", {})
    first = not seen
    done_pattern = re.compile(args.done_pattern) if args.done_pattern else None
    quiet = set(filter(None, args.quiet.split(",")))
    for name, agent in agents.items():
        status, before = agent.get("agent_status"), seen.get(name)
        seen[name] = status
        if first or before == status or name in quiet or name == args.watch_to:
            continue
        if status == "blocked":
            system_mail(root, args.watch_to, "PEDIDO", f"{name} blocked",
                        f"{name} ({agent.get('pane_id')}) passou de {before} a blocked: uma pergunta ou permissão espera resposta.")
        elif done_pattern and done_pattern.search(name) and before == "working" and status in ("done", "idle"):
            system_mail(root, args.watch_to, "ENTREGA", f"{name} terminou",
                        f"{name} ({agent.get('pane_id')}) passou de working a {status}. Lê o resultado no ecrã ou no transcript.")
    for name in list(seen):
        if name not in agents:
            seen.pop(name)
    # Swarm safety net: an event its swarmd has not got receipted for 120 s (dead or stuck supervisor).
    warned = state.setdefault("swarmWarned", {})
    for runs in args.watch_runs:
        for status_path in pathlib.Path(runs).glob("*/supervision/status.json"):
            with contextlib.suppress(Exception):
                status = load(status_path)
                if status.get("terminal"):
                    continue
                for event in status.get("pending", []):
                    sent = dt.datetime.fromisoformat(str(event.get("sentAt", "")).replace("Z", "+00:00"))
                    age = (dt.datetime.now(dt.timezone.utc) - sent).total_seconds()
                    key = f"{status_path.parent.parent.name}:{event.get('id')}"
                    if age > 120 and key not in warned:
                        warned[key] = now()
                        # swarmd never prompts the orchestrator, so its own events surface here as mail.
                        mine = event.get("to") == args.watch_to
                        system_mail(root, args.watch_to, "PEDIDO",
                                    f"swarm {status_path.parent.parent.name}: {event.get('type')} para ti" if mine
                                    else f"swarm {status_path.parent.parent.name}: evento parado",
                                    f"{event.get('type')} para {event.get('to')} sem recibo há {int(age)} s: {event.get('path')}")
    # Job queue (JSONL, one job per line with id/kind/who/state): a job that ends with a non-zero exit.
    jobs_first = "jobsReported" not in state  # seed silently the first time this observer runs
    reported = state.setdefault("jobsReported", {})
    for queue in args.watch_jobs:
        with contextlib.suppress(Exception):
            for line in pathlib.Path(queue).read_text(encoding="utf-8").splitlines():
                job = json.loads(line)
                job_state = str(job.get("state", ""))
                if job_state.startswith("done exit=") and job_state != "done exit=0" and job.get("id") not in reported:
                    reported[job["id"]] = now()
                    if jobs_first:
                        continue  # do not replay history on the first cycle
                    system_mail(root, args.watch_to, "PEDIDO", f"job {job['id']} falhou ({job.get('who')})",
                                f"{job.get('kind')} de {job.get('who')} terminou com {job_state} às {job.get('endedAt')}: {str(job.get('cmd'))[:400]}")
    for spec in args.watch_ref:
        repo, _, ref = spec.partition(":")
        refs = state.setdefault("refs", {})
        last_fetch = state.setdefault("lastFetch", {})
        if time.time() - float(last_fetch.get(spec, 0)) < args.fetch_every:
            continue
        last_fetch[spec] = time.time()
        with contextlib.suppress(Exception):
            subprocess.run(["git", "-C", repo, "fetch", "-q"], capture_output=True, timeout=60)
            head = subprocess.run(["git", "-C", repo, "rev-parse", ref], capture_output=True, text=True, timeout=10).stdout.strip()
            if head and refs.get(spec) and refs[spec] != head:
                log = subprocess.run(["git", "-C", repo, "log", "--oneline", f"{refs[spec]}..{head}"],
                                     capture_output=True, text=True, timeout=10).stdout.strip()
                system_mail(root, args.watch_to, "ENTREGA", f"{ref} avançou para {head[:9]}",
                            f"{repo} {ref}: {refs[spec][:9]} -> {head[:9]}\n{log[:2000]}")
            if head:
                refs[spec] = head


def cycle(root: pathlib.Path, state: dict[str, Any], retry_min: float, ceiling: float,
          args: argparse.Namespace | None = None) -> dict[str, Any]:
    listed = herdr("agent", "list").get("agents", [])
    agents = {a["name"]: a for a in listed if a.get("name")}
    if args is not None:
        observe(root, state, agents, args)
    epoch, stamp = time.time(), now()
    records = state.setdefault("messages", {})
    alive: set[str] = set()
    actions = []
    inbox = root / "inbox"
    recipients = sorted(p.name for p in inbox.iterdir() if p.is_dir()) if inbox.is_dir() else []
    for recipient in recipients:
        pending = [m for m in messages(root, recipient) if not m["receipted"]]
        if not pending:
            continue
        head = pending[0]
        alive.add(head["id"])
        record = records.setdefault(head["id"], {"recipient": recipient, "attempts": 0, "lastAttemptEpoch": None})
        agent = agents.get(recipient)
        status = agent.get("agent_status") if agent else "absent"
        last = record.get("lastAttemptEpoch")
        due = last is None or epoch - float(last) >= delay_for(int(record["attempts"]), retry_min, ceiling)
        action = {"id": head["id"], "recipient": recipient, "status": status, "action": "wait"}
        if due and status in {"idle", "done"}:
            try:
                readonly = bool(args and args.readonly and re.search(args.readonly, recipient))
                herdr("agent", "prompt", recipient, prompt_text(root, head, len(pending) - 1, readonly), timeout=15)
                action["action"] = "prompt"
                if readonly:
                    with contextlib.suppress(FileExistsError):
                        write_atomic(root / "receipts" / recipient / f"{head['id']}.json",
                                     {"schemaVersion": 1, "id": head["id"], "agent": recipient,
                                      "messageSha256": sha256_file(pathlib.Path(head["path"])),
                                      "disposition": "entregue a agente só de leitura (recibo do estafeta)",
                                      "receiptedAt": now()})
            except Exception as error:  # noqa: BLE001 - the next due cycle retries
                action["action"], action["error"] = "prompt-failed", str(error)[:300]
            record.update(attempts=int(record["attempts"]) + 1, lastAttemptEpoch=epoch, lastAttemptAt=stamp)
        elif due and status in {"blocked", "absent"}:
            with contextlib.suppress(Exception):
                herdr("notification", "show", f"Correio: {recipient} {status}",
                      "--body", f"{head['type']} de {head['from']}: {head['subject']}"[:250], timeout=5)
            action["action"] = "notify"
            record.update(attempts=int(record["attempts"]) + 1, lastAttemptEpoch=epoch, lastAttemptAt=stamp)
        actions.append(action)
    state["messages"] = {k: v for k, v in records.items() if k in alive}
    state.update(schemaVersion=1, pid=os.getpid(), checkedAt=stamp, actions=actions)
    return state


def cmd_daemon(args: argparse.Namespace) -> None:
    root = private_dir(root_dir())
    lock = open(root / "courier.lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        die("another courier is running", 1)

    def stop(_s: int, _f: Any) -> None:
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    state_path = root / "delivery.json"
    state = load(state_path) if state_path.exists() else {}
    while not STOP:
        try:
            state = cycle(root, state, args.retry_min, args.max_backoff, args)
            write_atomic(state_path, state, exclusive=False)
        except Exception as error:  # noqa: BLE001 - keep the courier alive
            print(f"{now()} cycle error: {error}", file=sys.stderr, flush=True)
        for _ in range(int(args.interval * 10)):
            if STOP:
                break
            time.sleep(0.1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("send")
    p.add_argument("--from", dest="sender", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--type", choices=TYPES, required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--body")
    p.add_argument("--body-file")
    p.add_argument("--payload-file")
    p.set_defaults(func=cmd_send)
    p = sub.add_parser("receipt")
    p.add_argument("--agent", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--disposition", required=True)
    p.set_defaults(func=cmd_receipt)
    p = sub.add_parser("pending")
    p.add_argument("--agent", required=True)
    p.set_defaults(func=cmd_pending)
    p = sub.add_parser("show")
    p.add_argument("--agent", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("daemon")
    p.add_argument("--interval", type=float, default=10.0)
    p.add_argument("--retry-min", type=float, default=30.0)
    p.add_argument("--max-backoff", type=float, default=480.0)
    p.add_argument("--watch-to", default="", help="agent that receives the observer mail (e.g. orquestrador)")
    p.add_argument("--done-pattern", default="", help="regex of agent names whose working→done/idle is mailed")
    p.add_argument("--readonly", default="", help="regex of sandboxed agents: the courier receipts on delivery")
    p.add_argument("--quiet", default="porta-voz", help="comma list of agents whose transitions are not mailed")
    p.add_argument("--watch-ref", action="append", default=[], help="REPO:REF whose advance is mailed (repeatable)")
    p.add_argument("--fetch-every", type=float, default=60.0)
    p.add_argument("--watch-runs", action="append", default=[], help="swarm runs/ directory to watch for stuck events")
    p.add_argument("--watch-jobs", action="append", default=[], help="JSONL job queue whose failed jobs are mailed")
    p.set_defaults(func=cmd_daemon)
    args = parser.parse_args()
    os.umask(0o077)  # the mailbox is private to the owner
    args.func(args)


if __name__ == "__main__":
    main()
