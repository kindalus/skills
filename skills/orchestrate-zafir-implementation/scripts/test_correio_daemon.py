"""The courier with an injected clock and a fake Herdr: FIFO, backoff, INFO digest, escalation, pinning,
observers, heartbeat, watchdog and backup."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import uuid

from correio import daemon, library
from correio_testing import CorreioCase, FakeHerdr

SWARM_CONTRACT = {
    "runId": "11111111-2222-4333-8444-555555555555", "prefix": "s900", "sliceId": "S900",
    "responsible": {"agent": "orquestrador", "paneId": "p-orquestrador", "workspaceId": "w1", "session": "t"},
    "models": {"principal": "codex gpt-6.1-sol high", "reviewer": "claude claude-opus-5-5 high"},
    "roster": {"coders": 0},
}


class CourierCase(CorreioCase):
    def setUp(self) -> None:
        super().setUp()
        self.orchestration()
        self.herdr = FakeHerdr()
        for agent in ("orquestrador", "porta-voz", "s606-preparer", "consultor-claude"):
            self.herdr.set(agent, "idle", f"p-{agent}")
        self.opts = daemon.Options(cli="correio")
        self.courier = daemon.Courier(self.store, self.herdr, self.opts)

    def swarm(self) -> None:
        run_dir = self.temp / "runs" / "s900"
        (run_dir / "reports").mkdir(parents=True)
        library.create_space(self.store, space_id="s900", kind="swarm", protocol="swarm", version="3.0.0",
                             slice_id="S900", prefix="s900", run_dir=str(run_dir), contract=SWARM_CONTRACT)
        library.add_member(self.store, "s900", "orquestrador", "responsible", pane_id="p-orquestrador")
        library.add_member(self.store, "s900", "s900-principal", "principal", pane_id="p-principal")
        library.add_member(self.store, "s900", "s900-reviewer", "reviewer", pane_id="p-reviewer")
        self.herdr.set("s900-principal", "idle", "p-principal")
        self.herdr.set("s900-reviewer", "idle", "p-reviewer")

    def swarm_event(self, sender: str, to: str, kind: str, **fields) -> str:
        return library.send(self.store, space="s900", sender=sender, to=to, type=kind, generation=1,
                            fields=fields)["id"]

    def prompts_to(self, target: str) -> list[str]:
        return [text for who, text in self.herdr.prompts if who == target]

    def mails(self, kind: str | None = None) -> list[dict]:
        rows = self.store.find_messages("orq", from_agent="correio")
        return [m for m in rows if kind is None or m["type"] == kind]


class DeliveryTest(CourierCase):
    def test_each_recipient_gets_its_oldest_wake_message_first(self) -> None:
        first = self.send(sender="orquestrador", to="s606-preparer", subject="primeiro")["id"]
        self.clock.advance(1)
        second = self.send(sender="orquestrador", to="s606-preparer", subject="segundo")["id"]
        self.send(sender="orquestrador", to="porta-voz", subject="outro destinatário")
        self.courier.cycle()
        prompts = self.prompts_to("s606-preparer")
        self.assertEqual(len(prompts), 1)
        self.assertIn(first, prompts[0])
        self.assertIn("+1 na fila", prompts[0])
        self.assertEqual(len(self.prompts_to("porta-voz")), 1)
        self.clock.advance(5)
        self.courier.cycle()
        self.assertEqual(len(self.prompts_to("s606-preparer")), 1)  # backoff, no receipt yet
        library.receipt(self.store, message_id=first, agent="s606-preparer", disposition="ok")
        self.courier.cycle()
        prompts = self.prompts_to("s606-preparer")
        self.assertEqual(len(prompts), 2)
        self.assertIn(second, prompts[1])

    def test_backoff_doubles_from_30_to_480_seconds(self) -> None:
        sent = self.send(sender="orquestrador", to="s606-preparer")["id"]
        times = []
        for _ in range(int(3000)):
            before = len(self.herdr.prompts)
            self.courier.cycle()
            if len(self.herdr.prompts) > before:
                times.append(self.clock.t)
            if len(times) == 8:
                break
            self.clock.advance(1)
        gaps = [round(b - a) for a, b in zip(times, times[1:])]
        self.assertEqual(gaps, [30, 60, 120, 240, 480, 480, 480])
        row = self.store.one("SELECT attempts, last_action FROM deliveries WHERE message_id=?", (sent,))
        self.assertEqual((row["attempts"], row["last_action"]), (8, "prompt"))

    def test_working_waits_blocked_and_absent_are_notified(self) -> None:
        self.send(sender="orquestrador", to="s606-preparer")
        self.herdr.set("s606-preparer", "working")
        self.courier.cycle()
        self.assertEqual((self.herdr.prompts, self.herdr.notes), ([], []))
        self.herdr.set("s606-preparer", "blocked")
        self.courier.cycle()
        self.assertEqual(self.prompts_to("s606-preparer"), [])
        self.assertIn("s606-preparer blocked", self.herdr.notes[-1][0])
        self.herdr.listed = [a for a in self.herdr.listed if a["name"] != "s606-preparer"]
        self.clock.advance(31)
        self.courier.cycle()
        self.assertIn("s606-preparer absent", self.herdr.notes[-1][0])
        self.herdr.set("s606-preparer", "done", "p-s606-preparer")
        self.clock.advance(61)
        self.courier.cycle()
        self.assertEqual(len(self.prompts_to("s606-preparer")), 1)

    def test_info_never_prompts_and_rides_as_a_digest(self) -> None:
        for n in range(3):
            self.send(sender="orquestrador", to="s606-preparer", type="INFO", subject=f"info {n}")
        self.courier.cycle()
        self.assertEqual(self.herdr.prompts, [])
        self.send(sender="orquestrador", to="s606-preparer", subject="acção")
        self.courier.cycle()
        (prompt,) = self.prompts_to("s606-preparer")
        self.assertIn("+3 INFO por ler", prompt)
        self.assertIn("receipt --all-info --agent s606-preparer", prompt)

    def test_a_failed_prompt_is_retried_and_never_dropped(self) -> None:
        sent = self.send(sender="orquestrador", to="s606-preparer")["id"]
        self.herdr.fail.add("s606-preparer")
        self.courier.cycle()
        row = self.store.one("SELECT * FROM deliveries WHERE message_id=?", (sent,))
        self.assertEqual((row["attempts"], row["last_action"]), (1, "prompt-failed"))
        self.herdr.fail.clear()
        self.clock.advance(30)
        self.courier.cycle()
        self.assertEqual(len(self.prompts_to("s606-preparer")), 1)

    def test_escalation_after_two_hours_notifies_and_mails_the_orchestrator_once(self) -> None:
        sent = self.send(sender="s606-preparer", to="consultor-claude", subject="pergunta")["id"]
        self.herdr.set("consultor-claude", "working")
        self.clock.advance(7199)
        self.courier.cycle()
        self.assertEqual(self.mails(), [])
        self.clock.advance(2)
        self.courier.cycle()
        (mail,) = self.mails("PEDIDO")
        self.assertEqual((mail["to_agent"], mail["thread"]), ("orquestrador", "correio/escalada"))
        self.assertIn(sent, mail["body"])
        self.assertTrue(any("sem recibo" in title for title, _ in self.herdr.notes))
        self.clock.advance(3600)
        self.courier.cycle()
        self.assertEqual(len(self.mails("PEDIDO")), 1)
        self.assertIsNone(self.store.receipt(sent))  # escalated, still pending

    def test_the_swarm_prompt_comes_from_its_protocol_and_resolves_by_pane(self) -> None:
        self.swarm()
        event = self.swarm_event("s900-principal", "s900-reviewer", "REVIEW_REQUEST", taskId="S900-T01",
                                 assignmentId="a1", revision=1, candidateSha="a" * 40)
        self.herdr.listed = [a for a in self.herdr.listed if a["name"] != "s900-reviewer"]
        self.herdr.listed.append({"name": None, "agent_status": "idle", "pane_id": "p-reviewer"})
        self.courier.cycle()
        (prompt,) = self.prompts_to("p-reviewer")
        self.assertIn(f"Swarm event pending for s900-reviewer: REVIEW_REQUEST {event}", prompt)
        self.assertIn("The courier grants no scope", prompt)

    def test_self_addressed_closed_and_legacy_spaces_are_not_delivered(self) -> None:
        self.swarm()
        library.create_space(self.store, space_id="s605", kind="swarm", protocol="swarm", version="2.7.0",
                             contract={"runId": "x"}, legacy=True)
        library.add_member(self.store, "s605", "s605-principal", "principal")
        self.store.x("INSERT INTO threads(space_id, key, opened_at) VALUES ('s605', 'S605', 'x')")
        from correio import envelope as env
        header = {"correio": 2, "id": str(uuid.uuid4()), "space": "s605", "protocol": "swarm", "version": "2.7.0",
                  "thread": "S605", "type": "BOOT", "from": "orquestrador", "from_generation": 1,
                  "to": "s605-principal", "in_reply_to": None, "sent_at": self.store.now(), "subject": "BOOT"}
        data = env.emit(header, {}, [], "")
        with self.store.tx():
            library.store_message(self.store, self.store.space("s605"), data, env.parse(data), "wake")
        self.herdr.set("s605-principal", "idle")
        bound = {"taskId": "S900-T01", "assignmentId": "a1", "revision": 1, "candidateSha": "b" * 40}
        library.send(self.store, space="s900", sender="s900-principal", to="s900-principal",
                     type="TASK_INTEGRATED", generation=1, fields=bound)
        self.courier.cycle()
        self.assertEqual(self.herdr.prompts, [])
        accepted = self.swarm_event("orquestrador", "s900-principal", "SLICE_ACCEPTED", candidateSha="c" * 40)
        library.receipt(self.store, message_id=accepted, agent="s900-principal", disposition="ok")
        self.assertIsNotNone(self.store.space("s900")["closed_at"])
        self.courier.cycle()
        self.assertEqual(self.herdr.prompts, [])

    def test_heartbeat_watchdog_and_backup(self) -> None:
        self.courier.cycle()
        self.assertTrue(daemon.watchdog(self.store, self.herdr, max_age=120)["ok"])
        self.clock.advance(121)
        result = daemon.watchdog(self.store, self.herdr, max_age=120)
        self.assertEqual((result["ok"], result["restarted"]), (False, False))
        self.assertIn("estafeta parado", self.herdr.notes[-1][0])
        backups = self.temp / "backups"
        self.opts.backup_dir = str(backups)
        self.courier.cycle()
        day = dt.datetime.fromtimestamp(self.clock.t, dt.timezone.utc).date()
        target = backups / f"correio-{day.isoformat()}.db"
        self.assertTrue(target.is_file())
        old = backups / f"correio-{(day - dt.timedelta(days=15)).isoformat()}.db"
        old.write_bytes(b"")
        self.clock.advance(86400)
        self.courier.cycle()
        self.assertFalse(old.exists())
        self.assertEqual(len(list(backups.glob("correio-*.db"))), 2)

    def test_the_daemon_cli_runs_one_cycle_against_a_herdr_binary(self) -> None:
        _state, log = self.fake_herdr_binary([{"name": "s606-preparer", "agent_status": "idle",
                                               "pane_id": "p-s606-preparer"}])
        sent = self.send(sender="orquestrador", to="s606-preparer")["id"]
        here = pathlib.Path(__file__).resolve().parent
        proc = subprocess.run(["/usr/bin/python3", str(here / "correio.py"), "daemon", "--once", "--no-backup"],
                              env=os.environ.copy(), text=True, capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        prompts = [c for c in calls if c[:2] == ["agent", "prompt"]]
        self.assertEqual(prompts[0][2], "s606-preparer")
        self.assertIn(sent, prompts[0][3])


class ObserverTest(CourierCase):
    def test_blocked_is_mailed_after_a_silent_seed_except_quiet_agents(self) -> None:
        self.herdr.set("s606-preparer", "blocked")
        self.courier.cycle()
        self.assertEqual(self.mails(), [])  # first run seeds silently
        self.herdr.set("s606-preparer", "working")
        self.herdr.set("porta-voz", "working")
        self.courier.cycle()
        self.herdr.set("s606-preparer", "blocked")
        self.herdr.set("porta-voz", "blocked")
        self.courier.cycle()
        (mail,) = self.mails("PEDIDO")
        self.assertEqual(mail["subject"], "s606-preparer blocked")
        restarted = daemon.Courier(self.store, self.herdr, self.opts)
        restarted.cycle()
        self.assertEqual(len(self.mails("PEDIDO")), 1)  # a restart replays nothing

    def test_done_is_mailed_only_with_an_active_grant(self) -> None:
        self.opts.done_pattern = r"^(consultor|executor)-"
        self.courier.cycle()
        for status in ("working", "idle"):
            self.herdr.set("consultor-claude", status)
            self.courier.cycle()
        self.assertEqual(self.mails(), [])
        library.update_member(self.store, "orq", "consultor-claude", set_attributes={"grant": "S606-R2"})
        for status in ("working", "done"):
            self.herdr.set("consultor-claude", status)
            self.courier.cycle()
        (mail,) = self.mails("ENTREGA")
        self.assertEqual(mail["subject"], "consultor-claude terminou (S606-R2)")
        library.update_member(self.store, "orq", "s606-preparer", set_attributes={"grant": "x"})
        for status in ("working", "idle"):
            self.herdr.set("s606-preparer", status)
            self.courier.cycle()
        self.assertEqual(len(self.mails("ENTREGA")), 1)  # outside the done pattern

    def test_a_ref_advance_is_mailed(self) -> None:
        repo = self.temp / "repo"
        repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
        git("init", "-q", "-b", "main")
        git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "one")
        self.opts.watch_ref = (f"{repo}:main",)
        self.opts.fetch_every = 0
        self.courier.cycle()
        git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "two")
        self.clock.advance(1)
        self.courier.cycle()
        (mail,) = self.mails("ENTREGA")
        self.assertTrue(mail["subject"].startswith("main avançou para"))
        self.assertIn("two", mail["body"])

    def test_a_stuck_swarm_event_is_mailed_once(self) -> None:
        self.swarm()
        self.courier.cycle()  # seed
        self.herdr.set("s900-reviewer", "working")
        self.swarm_event("s900-principal", "s900-reviewer", "REVIEW_REQUEST", taskId="S900-T01", assignmentId="a1",
                         revision=1, candidateSha="a" * 40)
        self.clock.advance(100)
        self.courier.cycle()
        self.assertEqual(self.mails(), [])
        self.clock.advance(30)
        self.courier.cycle()
        self.clock.advance(30)
        self.courier.cycle()
        (mail,) = self.mails("PEDIDO")
        self.assertEqual(mail["subject"], "swarm s900: evento parado")

    def test_failed_jobs_are_mailed_and_each_observer_seeds_on_its_own(self) -> None:
        self.courier.cycle()  # the agents observer seeds here, the jobs observers too
        job = library.jobs_add(self.store, kind="gate", who="s601", cmd="bash gate.sh")
        library.jobs_next(self.store)
        library.jobs_finish(self.store, job["id"], 2)
        queue = self.temp / "lease-queue.jsonl"
        queue.write_text(json.dumps({"id": "old1", "kind": "lote", "who": "s591", "cmd": "x",
                                     "state": "done exit=1"}) + "\n")
        self.opts.watch_jobs = (str(queue),)  # a new observer after the daemon ran: seeds silently
        self.courier.cycle()
        self.assertEqual([m["subject"] for m in self.mails()], [f"job {job['id']} falhou (s601)"])
        with queue.open("a") as out:
            out.write(json.dumps({"id": "new2", "kind": "gate", "who": "s605", "cmd": "y",
                                  "state": "done exit=143"}) + "\n")
        self.courier.cycle()
        self.assertEqual(sorted(m["subject"] for m in self.mails()),
                         sorted([f"job {job['id']} falhou (s601)", "job new2 falhou (s605)"]))

    def test_a_legacy_run_with_its_swarmd_dead_is_mailed(self) -> None:
        runs = self.temp / "legacy-runs"
        run = runs / "s605"
        (run / "supervision").mkdir(parents=True)
        (run / "automation.json").write_text(json.dumps({"automationVersion": "2.7.0"}))
        (run / "state.json").write_text(json.dumps({"state": "running"}))
        (run / "supervision" / "status.json").write_text(json.dumps({"pid": os.getpid(), "terminal": False}))
        self.opts.watch_runs = (str(runs),)
        self.courier.cycle()  # seed: this test process is alive but is not a swarmd
        self.assertEqual(self.mails(), [])
        (run / "state.json").write_text(json.dumps({"state": "accepted"}))
        self.courier.cycle()
        (run / "state.json").write_text(json.dumps({"state": "running"}))
        self.courier.cycle()
        (mail,) = self.mails("PEDIDO")
        self.assertEqual(mail["subject"], "swarm legacy s605: swarmd parado")
