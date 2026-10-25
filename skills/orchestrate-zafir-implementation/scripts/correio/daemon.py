"""The courier: delivers wake messages, digests INFO, escalates, and runs the orchestrator's observers.

It never validates semantics and never changes space or task state; it only reads messages and receipts
and writes its own tables (deliveries, observers, heartbeat). Per recipient it prompts the oldest
unreceipted wake message, only while the agent is idle or done, retrying on a 30 s backoff doubling to
480 s. A blocked or absent recipient gets a Herdr notification instead. Nothing is ever dropped: a wake
message without a receipt for 2 h raises a notification and a PEDIDO to the orchestrator, and stays.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import fcntl
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
from typing import Any

from . import library
from .store import CorreioError, Store, parse_iso

STOP = False


class HerdrError(RuntimeError):
    pass


class Herdr:
    """The ``herdr`` CLI; ``$CORREIO_HERDR`` names another binary (tests use a fake)."""

    def __init__(self, binary: str | None = None):
        self.binary = binary or os.environ.get("CORREIO_HERDR", "herdr")

    def call(self, *argv: str, timeout: float = 15) -> dict[str, Any]:
        try:
            proc = subprocess.run([self.binary, *argv], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HerdrError(str(exc)) from exc
        if proc.returncode != 0:
            raise HerdrError(proc.stderr.strip()[:300] or proc.stdout.strip()[:300] or f"exit {proc.returncode}")
        with contextlib.suppress(ValueError):
            return json.loads(proc.stdout).get("result", {}) or {}
        return {}

    def agents(self) -> list[dict[str, Any]]:
        return list(self.call("agent", "list").get("agents", []))

    def prompt(self, target: str, text: str) -> None:
        self.call("agent", "prompt", target, text, timeout=15)

    def notify(self, title: str, body: str, sound: str = "request") -> None:
        with contextlib.suppress(HerdrError):
            self.call("notification", "show", title, "--body", body[:250], "--sound", sound, timeout=5)


@dataclasses.dataclass
class Options:
    retry_min: float = 30.0
    max_backoff: float = 480.0
    escalate_after: float = 7200.0
    stuck_after: float = 120.0
    watch_to: str = "orquestrador"
    done_pattern: str = ""
    quiet: tuple[str, ...] = ("porta-voz",)
    watch_ref: tuple[str, ...] = ()
    fetch_every: float = 60.0
    watch_runs: tuple[str, ...] = ()
    watch_jobs: tuple[str, ...] = ()
    space: str | None = None
    backup_dir: str | None = None
    backup_keep: int = 14
    legacy_refresh: float = 300.0
    readonly: str = ""  # regex of read-only (sandboxed) agents: the courier receipts for them after the prompt
    cli: str = library.CLI


def delay_for(attempts: int, minimum: float, ceiling: float) -> float:
    return min(ceiling, minimum * (2 ** min(32, max(0, attempts - 1))))  # cap the exponent: a float overflows past 2**1023


def resolve_agent(listed: list[dict[str, Any]], name: str, member: dict[str, Any] | None
                  ) -> tuple[dict[str, Any] | None, str | None]:
    """By name; by the member's recorded pane when the name is absent, ambiguous or in another pane."""
    pane = member.get("pane_id") if member else None
    named = [a for a in listed if a.get("name") == name]
    if len(named) == 1 and (not pane or named[0].get("pane_id") == pane):
        return named[0], name
    if pane:
        by_pane = [a for a in listed if a.get("pane_id") == pane]
        if len(by_pane) == 1:
            agent = by_pane[0]
            return agent, name if agent.get("name") == name else pane
    return None, None


def pid_alive(pid: Any, needle: str | None = None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    if needle:
        try:
            return needle.encode() in pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return False
    return True


def _read_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def legacy_terminal(run_dir: pathlib.Path) -> bool:
    """A 2.7 run is over when cancelled, accepted, or its SLICE_ACCEPTED has an accepted receipt."""
    state = _read_json(run_dir / "state.json") or {}
    status = _read_json(run_dir / "supervision" / "status.json") or {}
    if state.get("state") in {"cancelled", "accepted", "closed"} or state.get("accepted") is True or status.get(
            "terminal"):
        return True
    for event_path in run_dir.glob("inbox/*/*.json"):
        event = _read_json(event_path) or {}
        if event.get("type") == "SLICE_ACCEPTED":
            receipt = _read_json(run_dir / "receipts" / event_path.parent.name / event_path.name) or {}
            if receipt.get("accepted") is True:
                return True
    return False


class Courier:
    def __init__(self, store: Store, herdr: Herdr, options: Options | None = None):
        self.store, self.herdr, self.opts = store, herdr, options or Options()

    # -- helpers ----------------------------------------------------------------------------------------------------
    def now(self) -> float:
        return self.store.clock.epoch()

    def mail(self, kind: str, subject: str, body: str, thread: str) -> None:
        with contextlib.suppress(CorreioError):
            library.system_mail(self.store, to=self.opts.watch_to, type=kind, subject=subject, body=body,
                                thread=thread, space=self.opts.space)

    def observer(self, name: str) -> tuple[dict[str, Any], bool]:
        """The observer's saved state and whether this is its first run (seed silently, per observer)."""
        state = self.store.observer(name)
        return (state if state is not None else {}), state is None

    def save(self, name: str, state: dict[str, Any]) -> None:
        with self.store.tx():
            self.store.set_observer(name, state)

    def pending_wake(self) -> list[dict[str, Any]]:
        rows = self.store.q(
            "SELECT m.id FROM messages m JOIN spaces s ON s.id=m.space_id LEFT JOIN receipts r ON r.message_id=m.id "
            "WHERE r.message_id IS NULL AND s.legacy=0 AND s.closed_at IS NULL AND m.delivery='wake' "
            "AND m.from_agent<>m.to_agent ORDER BY m.sent_at, m.rowid")
        return [self.store.message(r["id"]) for r in rows]

    def readonly(self, agent: str, module: Any) -> bool:
        """A read-only recipient, in a protocol whose receipts project nothing (never a swarm)."""
        return bool(self.opts.readonly and re.search(self.opts.readonly, agent)
                    and getattr(module, "READONLY_RECEIPTS", False))

    def readonly_copy(self, message: dict[str, Any]) -> pathlib.Path:
        """The envelope's exact bytes in a file a read-only agent can read (it cannot open the database)."""
        directory = self.store.path.parent / "leitura" / message["to_agent"]
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = directory / f"{message['id']}.md"
        if not target.is_file() or target.read_bytes() != message["envelope"]:
            tmp = directory / f".{message['id']}.{os.getpid()}.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(message["envelope"])
            os.replace(tmp, target)
        return target

    def unread_info_messages(self, agent: str, space_id: str) -> list[dict[str, Any]]:
        return library._unreceipted(self.store, agent=agent, space=space_id, delivery="info")

    def unread_info(self, agent: str) -> int:
        row = self.store.one(
            "SELECT COUNT(*) FROM messages m JOIN spaces s ON s.id=m.space_id LEFT JOIN receipts r ON "
            "r.message_id=m.id WHERE r.message_id IS NULL AND s.legacy=0 AND m.delivery='info' AND m.to_agent=?",
            (agent,))
        return int(row[0])

    # -- one cycle --------------------------------------------------------------------------------------------------
    def cycle(self) -> dict[str, Any]:
        report: dict[str, Any] = {"actions": [], "errors": []}
        try:
            listed = self.herdr.agents()
        except HerdrError as exc:
            listed = None
            report["errors"].append(f"herdr agent list: {exc}")
        steps = [("escalate", self.escalate), ("swarm-stuck", self.observe_swarm_stuck),
                 ("jobs", self.observe_jobs), ("refs", self.observe_refs), ("legacy", self.observe_legacy),
                 ("backup", self.maybe_backup), ("legacy-refresh", self.maybe_refresh_legacy)]
        if listed is not None:
            steps = [("agents", lambda: self.observe_agents(listed)),
                     ("deliver", lambda: report["actions"].extend(self.deliver(listed)))] + steps
        for name, step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - one failing step never stops the courier
                report["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        with self.store.tx():
            self.store.beat("courier")
        return report

    def deliver(self, listed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        queues: dict[str, list[dict[str, Any]]] = {}
        for message in self.pending_wake():
            queues.setdefault(message["to_agent"], []).append(message)
        actions = []
        for agent_name, queue in queues.items():
            head = queue[0]
            space = self.store.space(head["space_id"])
            member = self.store.member(head["space_id"], agent_name)
            agent, target = resolve_agent(listed, agent_name, member)
            status = agent.get("agent_status") if agent else "absent"
            row = self.store.one("SELECT * FROM deliveries WHERE message_id=?", (head["id"],))
            attempts = int(row["attempts"]) if row else 0
            last = row["last_attempt_epoch"] if row else None
            now = self.now()
            due = last is None or now - float(last) >= delay_for(attempts, self.opts.retry_min, self.opts.max_backoff)
            action = {"id": head["id"], "to": agent_name, "status": status, "action": "wait"}
            if due and status in {"idle", "done"}:
                if self.store.receipt(head["id"]):
                    action["action"] = "already-receipted"
                else:
                    module = library.protocol_of(space)
                    readonly = self.readonly(agent_name, module)
                    infos = self.unread_info_messages(agent_name, space["id"]) if readonly else []
                    if readonly:
                        copy = str(self.readonly_copy(head))
                        for info in infos:
                            self.readonly_copy(info)
                        text = module.prompt(head, len(queue) - 1, len(infos), cli=self.opts.cli, copy=copy)
                    else:
                        text = module.prompt(head, len(queue) - 1, self.unread_info(agent_name), cli=self.opts.cli)
                    try:
                        self.herdr.prompt(target, text)
                        action["action"] = "prompt"
                    except HerdrError as exc:
                        action.update(action="prompt-failed", error=str(exc)[:300])
                    else:
                        if readonly:  # it cannot write its receipt: the courier records it, marked as its own
                            for message in [head, *infos]:
                                library.receipt(self.store, message_id=message["id"], agent=agent_name,
                                                disposition=library.READONLY_DISPOSITION, by="correio")
                            action["action"] = "prompt-readonly"
                    attempts += 1
                    last = now
            elif due and status in {"blocked", "absent"}:
                self.herdr.notify(f"Correio: {agent_name} {status}",
                                  f"{head['type']} de {head['from_agent']}: {head['subject']}")
                action["action"] = "notify"
                attempts += 1
                last = now
            with self.store.tx():
                self.store.x(
                    "INSERT INTO deliveries(message_id, attempts, last_attempt_at, last_attempt_epoch, "
                    "last_agent_status, last_action) VALUES (?,?,?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET "
                    "attempts=excluded.attempts, last_attempt_at=excluded.last_attempt_at, "
                    "last_attempt_epoch=excluded.last_attempt_epoch, last_agent_status=excluded.last_agent_status, "
                    "last_action=excluded.last_action",
                    (head["id"], attempts, self.store.clock.iso(last) if last is not None else None, last, status,
                     action["action"]))
            actions.append(action)
        return actions

    def escalate(self) -> None:
        now = self.now()
        for message in self.pending_wake():
            sent = parse_iso(message["sent_at"])
            if sent is None or now - sent < self.opts.escalate_after:
                continue
            row = self.store.one("SELECT escalated_at FROM deliveries WHERE message_id=?", (message["id"],))
            if row and row["escalated_at"]:
                continue
            hours = (now - sent) / 3600
            title = f"Correio: {message['to_agent']} sem recibo há {hours:.1f} h"
            self.herdr.notify(title, f"{message['type']} de {message['from_agent']}: {message['subject']}")
            if message["to_agent"] != self.opts.watch_to and message["from_agent"] != "correio":
                self.mail("PEDIDO", f"{message['to_agent']} sem recibo há {hours:.1f} h: {message['subject']}",
                          f"{message['type']} {message['id']} ({message['space_id']}, {message['thread']}) de "
                          f"{message['from_agent']} para {message['to_agent']}, enviada {message['sent_at']}, ainda "
                          f"sem recibo. Ver: {self.opts.cli} show {message['id']}", "correio/escalada")
            with self.store.tx():
                self.store.x("INSERT INTO deliveries(message_id, escalated_at) VALUES (?,?) ON CONFLICT(message_id) "
                             "DO UPDATE SET escalated_at=excluded.escalated_at", (message["id"], self.store.now()))

    # -- observers --------------------------------------------------------------------------------------------------
    def active_grant(self, agent: str) -> str | None:
        for row in self.store.q("SELECT m.attributes FROM members m JOIN spaces s ON s.id=m.space_id WHERE "
                                "m.agent=? AND m.left_at IS NULL AND s.closed_at IS NULL AND s.legacy=0", (agent,)):
            grant = json.loads(row["attributes"] or "{}").get("grant")
            if grant:
                return str(grant)
        return None

    def observe_agents(self, listed: list[dict[str, Any]]) -> None:
        state, first = self.observer("agents")
        seen = state.setdefault("status", {})
        done_re = re.compile(self.opts.done_pattern) if self.opts.done_pattern else None
        current = {a["name"]: a for a in listed if a.get("name")}
        for name, agent in current.items():
            status, before = agent.get("agent_status"), seen.get(name)
            seen[name] = status
            if first or before is None or before == status or name in self.opts.quiet or name == self.opts.watch_to:
                continue
            if status == "blocked":
                self.mail("PEDIDO", f"{name} blocked",
                          f"{name} ({agent.get('pane_id')}) passou de {before} a blocked: uma pergunta ou permissão "
                          "espera resposta.", "correio/agentes")
            elif before == "working" and status in {"done", "idle"} and (done_re is None or done_re.search(name)):
                grant = self.active_grant(name)
                if grant:
                    self.mail("ENTREGA", f"{name} terminou ({grant})",
                              f"{name} ({agent.get('pane_id')}) passou de working a {status} com a concessão {grant} "
                              "activa. Lê o resultado no ecrã ou no transcript.", "correio/agentes")
        for name in list(seen):
            if name not in current:
                seen.pop(name)
        self.save("agents", state)

    def observe_swarm_stuck(self) -> None:
        state, first = self.observer("swarm-stuck")
        warned = state.setdefault("warned", {})
        now, pending = self.now(), set()
        for message in self.pending_wake():
            space = self.store.space(message["space_id"])
            if space["kind"] != "swarm":
                continue
            pending.add(message["id"])
            sent = parse_iso(message["sent_at"])
            if (sent is None or now - sent <= self.opts.stuck_after or message["id"] in warned
                    or message["to_agent"] == self.opts.watch_to):
                continue
            warned[message["id"]] = self.store.now()
            if not first:
                self.mail("PEDIDO", f"swarm {space['id']}: evento parado",
                          f"{message['type']} {message['id']} para {message['to_agent']} sem recibo há "
                          f"{int(now - sent)} s. Ver: {self.opts.cli} show {message['id']}", "correio/swarms")
        # Legacy 2.7 runs: their swarmd's status.json (the v1 safety net), until they close.
        for runs in self.opts.watch_runs:
            for status_path in pathlib.Path(runs).glob("*/supervision/status.json"):
                status = _read_json(status_path) or {}
                if status.get("terminal"):
                    continue
                for event in status.get("pending", []):
                    sent = parse_iso(event.get("sentAt"))
                    key = f"{status_path.parent.parent.name}:{event.get('id')}"
                    pending.add(key)
                    if sent is None or now - sent <= self.opts.stuck_after or key in warned:
                        continue
                    warned[key] = self.store.now()
                    if not first:
                        # swarmd never prompts the orchestrator, so its own events surface here as mail (v1 6fa721c).
                        mine = event.get("to") == self.opts.watch_to
                        run = status_path.parent.parent.name
                        self.mail("PEDIDO", f"swarm {run}: {event.get('type')} para ti" if mine
                                  else f"swarm {run}: evento parado",
                                  f"{event.get('type')} para {event.get('to')} sem recibo há {int(now - sent)} s: "
                                  f"{event.get('path')}", "correio/swarms")
        state["warned"] = {k: v for k, v in warned.items() if k in pending}
        self.save("swarm-stuck", state)

    def observe_jobs(self) -> None:
        state, first = self.observer("jobs")
        reported = set(state.get("reported", []))
        for row in self.store.q("SELECT * FROM jobs WHERE state='done' AND exit<>0 ORDER BY seq"):
            if row["id"] in reported:
                continue
            reported.add(row["id"])
            if not first:
                self.mail("PEDIDO", f"job {row['id']} falhou ({row['who']})",
                          f"{row['kind']} de {row['who']} terminou com exit {row['exit']} às {row['ended_at']}: "
                          f"{str(row['cmd'])[:400]}", "correio/jobs")
        state["reported"] = sorted(reported)
        self.save("jobs", state)
        for queue in self.opts.watch_jobs:
            name = f"jobs-jsonl:{queue}"
            state, first = self.observer(name)
            reported = set(state.get("reported", []))
            path = pathlib.Path(queue)
            lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            for line in lines:
                with contextlib.suppress(ValueError, KeyError, TypeError):
                    job = json.loads(line)
                    job_state = str(job.get("state", ""))
                    if (job_state.startswith("done exit=") and job_state != "done exit=0"
                            and job["id"] not in reported):
                        reported.add(job["id"])
                        if not first:
                            self.mail("PEDIDO", f"job {job['id']} falhou ({job.get('who')})",
                                      f"{job.get('kind')} de {job.get('who')} terminou com {job_state} às "
                                      f"{job.get('endedAt')}: {str(job.get('cmd'))[:400]}", "correio/jobs")
            state["reported"] = sorted(reported)
            self.save(name, state)

    def observe_refs(self) -> None:
        for spec in self.opts.watch_ref:
            repo, _, ref = spec.partition(":")
            name = f"ref:{spec}"
            state, first = self.observer(name)
            if self.now() - float(state.get("lastFetch", 0)) < self.opts.fetch_every:
                continue
            state["lastFetch"] = self.now()
            subprocess.run(["git", "-C", repo, "fetch", "-q"], capture_output=True, timeout=60)
            head = subprocess.run(["git", "-C", repo, "rev-parse", ref], capture_output=True, text=True,
                                  timeout=10).stdout.strip()
            before = state.get("head")
            if head and before and before != head and not first:
                log = subprocess.run(["git", "-C", repo, "log", "--oneline", f"{before}..{head}"],
                                     capture_output=True, text=True, timeout=10).stdout.strip()
                self.mail("ENTREGA", f"{ref} avançou para {head[:9]}", f"{repo} {ref}: {before[:9]} -> {head[:9]}\n"
                          f"{log[:2000]}", "correio/main")
            if head:
                state["head"] = head
            self.save(name, state)

    def legacy_runs(self) -> list[pathlib.Path]:
        runs = {pathlib.Path(r["run_dir"]) for r in self.store.q(
            "SELECT run_dir FROM spaces WHERE legacy=1 AND closed_at IS NULL AND run_dir IS NOT NULL")}
        for root in self.opts.watch_runs:
            for marker in pathlib.Path(root).glob("*/automation.json"):
                if (_read_json(marker) or {}).get("automationVersion") != "3.0.0":
                    runs.add(marker.parent)
        return sorted(runs)

    def observe_legacy(self) -> None:
        """A 2.7 run that is still open with its swarmd dead."""
        state, first = self.observer("legacy-swarmd")
        warned = state.setdefault("warned", {})
        for run_dir in self.legacy_runs():
            key = str(run_dir)
            if not run_dir.is_dir() or legacy_terminal(run_dir):
                warned.pop(key, None)
                continue
            status = _read_json(run_dir / "supervision" / "status.json") or {}
            process = _read_json(run_dir / "supervision" / "process.json") or {}
            alive = any(pid_alive(p, "swarmd.py") for p in (status.get("pid"), process.get("pid")))
            if alive:
                warned.pop(key, None)
                continue
            if key in warned:
                continue
            warned[key] = self.store.now()
            if not first:
                self.mail("PEDIDO", f"swarm legacy {run_dir.name}: swarmd parado",
                          f"A run 2.7 {run_dir} está aberta e o swarmd não corre (status {status.get('checkedAt')}). "
                          f"Reinicia-o pelo runtime da run: {run_dir}/runtime/swarmd.py --run-dir {run_dir}",
                          "correio/swarms")
        self.save("legacy-swarmd", state)

    def maybe_backup(self) -> None:
        if not self.opts.backup_dir:
            return
        today = dt.datetime.fromtimestamp(self.now(), dt.timezone.utc).date()
        state, _first = self.observer("backup")
        if state.get("date") == today.isoformat():
            return
        backup(self.store, pathlib.Path(self.opts.backup_dir), today, self.opts.backup_keep)
        self.save("backup", {"date": today.isoformat()})

    def maybe_refresh_legacy(self) -> None:
        if not self.opts.legacy_refresh:
            return
        state, _first = self.observer("legacy-refresh")
        if self.now() - float(state.get("lastEpoch", 0)) < self.opts.legacy_refresh:
            return
        from . import importers
        for row in self.store.q("SELECT run_dir FROM spaces WHERE legacy=1 AND closed_at IS NULL "
                                "AND run_dir IS NOT NULL"):
            if pathlib.Path(row["run_dir"]).is_dir():
                importers.import_run(self.store, row["run_dir"])
        self.save("legacy-refresh", {"lastEpoch": self.now()})


def backup(store: Store, directory: pathlib.Path, day: dt.date, keep: int) -> pathlib.Path:
    """Daily ``correio-<date>.db`` beside the database, keeping ``keep`` days."""
    target = store.backup(directory / f"correio-{day.isoformat()}.db")
    for old in directory.glob("correio-*.db"):
        with contextlib.suppress(ValueError):
            if (day - dt.date.fromisoformat(old.stem.removeprefix("correio-"))).days >= keep:
                old.unlink()
    return target


def watchdog(store: Store, herdr: Herdr, *, component: str = "courier", max_age: float = 120.0,
             unit: str | None = None) -> dict[str, Any]:
    """Restart the courier unit when its heartbeat is older than ``max_age`` seconds."""
    row = store.one("SELECT * FROM heartbeat WHERE component=?", (component,))
    age = store.clock.epoch() - float(row["epoch"]) if row else None
    result: dict[str, Any] = {"component": component, "ageSeconds": None if age is None else round(age, 1),
                              "ok": age is not None and age <= max_age, "restarted": False}
    if not result["ok"]:
        if unit:
            proc = subprocess.run(["systemctl", "--user", "restart", unit], capture_output=True, text=True, timeout=60)
            result.update(restarted=proc.returncode == 0, restartError=proc.stderr.strip()[:300] or None)
        herdr.notify("Correio: estafeta parado", f"heartbeat {result['ageSeconds']} s; "
                     + (f"restart de {unit}" if unit else "sem unidade para reiniciar"))
    return result


def _stop(_signum: int, _frame: Any) -> None:
    global STOP
    STOP = True


def run(store: Store, herdr: Herdr, options: Options, *, interval: float, once: bool = False) -> int:
    lock_path = store.path.with_name(store.path.name + ".courier.lock")
    lock = open(lock_path, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"error": "another courier is running"}), file=sys.stderr)
        return 1
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    courier = Courier(store, herdr, options)
    while not STOP:
        try:
            report = courier.cycle()
            if report["errors"]:
                print(f"{store.now()} cycle errors: {report['errors']}", file=sys.stderr, flush=True)
            if once:
                print(json.dumps(report, ensure_ascii=False))
                return 0
        except Exception as exc:  # noqa: BLE001 - keep the courier alive
            print(f"{store.now()} cycle error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            if once:
                return 2
        for _ in range(max(1, int(interval * 10))):
            if STOP:
                break
            time.sleep(0.1)
    return 0
