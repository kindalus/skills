"""Store, library and the orchestration/1.0.0 protocol: send, receipt, queries, export, jobs, concurrency."""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import pathlib
import sqlite3
import stat
import subprocess
import sys
import unittest

from correio import library, migrations, protocols
from correio.store import CorreioError, Store
from correio_testing import CorreioCase

HERE = pathlib.Path(__file__).resolve().parent


def _writer(db: str, sender: str, count: int, queue) -> None:
    os.environ.pop("HERDR_PANE_ID", None)
    store = Store(db)
    try:
        for n in range(count):
            library.send(store, space="orq", sender=sender, to="orquestrador", type="INFO", thread="geral",
                         subject=f"{sender} {n}")
        queue.put(("ok", sender))
    except Exception as exc:  # noqa: BLE001
        queue.put(("error", repr(exc)))
    finally:
        store.close()


def _slow_writer(db: str, sender: str, count: int, hold: float, start, queue) -> None:
    """A writer whose transactions take ``hold`` seconds (a slow fsync), with a 1 s busy timeout."""
    import time
    from correio import store as store_module
    os.environ.pop("HERDR_PANE_ID", None)
    store_module.BUSY_TIMEOUT_MS = 1000
    original = library.store_message

    def slow(*args, **kwargs):
        time.sleep(hold)
        return original(*args, **kwargs)
    library.store_message = slow
    store = Store(db)
    try:
        start.wait(60)
        for n in range(count):
            library.send(store, space="orq", sender=sender, to="orquestrador", type="INFO", thread="geral",
                         subject=f"{sender} {n}")
        queue.put(("ok", sender))
    except Exception as exc:  # noqa: BLE001
        queue.put(("error", repr(exc)))
    finally:
        store.close()


def _owner_that_forks_and_dies(db: str, how: str, out: str) -> None:
    """Takes the write lock, leaves a child behind (fork, or fork+exec keeping inheritable fds), and dies."""
    store = Store(db)
    with store.tx():
        if how == "hold":  # a child that ends at once must not free the lock its parent still holds
            pid = os.fork()
            if pid == 0:
                os._exit(0)
            os.waitpid(pid, 0)
            pathlib.Path(out).write_text(str(pid))
            import time
            time.sleep(2)
            os._exit(0)
        if how == "fork":
            pid = os.fork()
            if pid == 0:
                import time
                time.sleep(5)
                os._exit(0)
        else:
            pid = subprocess.Popen(["sleep", "5"], close_fds=False).pid
        pathlib.Path(out).write_text(str(pid))
        os._exit(0)  # the owner dies holding the lock; the kernel releases what it alone held


FORK_WHILE_WAITING = r"""
import os, pathlib, sys, threading, time
from correio.store import Store
db = pathlib.Path(sys.argv[1])
ready, go, acquired = threading.Event(), threading.Event(), threading.Event()
def writer():
    store = Store(db)
    ready.set()
    go.wait(30)
    with store.tx():
        acquired.set()
        time.sleep(30)
threading.Thread(target=writer, daemon=True).start()
assert ready.wait(30)
print("READY", flush=True)
assert sys.stdin.readline().strip() == "GO"
go.set()
deadline = time.monotonic() + 10
while str(db) + ".write.lock" not in [os.readlink(f) for f in pathlib.Path("/proc/self/fd").iterdir()
                                      if f.exists()]:  # the writer has opened its lock fd and waits in flock
    if time.monotonic() > deadline:
        raise SystemExit("the writer never opened its lock fd")
    time.sleep(0.01)
time.sleep(0.1)
child = os.fork()  # from another thread, while the writer waits
if child == 0:
    time.sleep(6)
    os._exit(0)
print("FORKED", child, flush=True)
assert acquired.wait(30)
os._exit(0)  # dies holding the lock
"""


class StoreTest(CorreioCase):
    def test_a_fork_while_another_thread_waits_for_the_lock_leaves_nothing_behind(self) -> None:
        import fcntl
        import time
        env = {**os.environ, "PYTHONPATH": str(HERE), "PYTHONDONTWRITEBYTECODE": "1"}
        with open(str(self.store.path) + ".write.lock", "a+") as lock:
            owner = subprocess.Popen([sys.executable, "-u", "-c", FORK_WHILE_WAITING, str(self.store.path)], env=env,
                                     text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                self.assertEqual(owner.stdout.readline().strip(), "READY")
                fcntl.flock(lock, fcntl.LOCK_EX)  # the owner's writer will wait behind this
                owner.stdin.write("GO\n")
                owner.stdin.flush()
                forked = owner.stdout.readline().split()
                self.assertEqual(forked[0], "FORKED")
                child = int(forked[1])
                fcntl.flock(lock, fcntl.LOCK_UN)
                owner.wait(30)
            finally:
                if owner.poll() is None:
                    owner.kill()
        start = time.time()
        with self.store.tx():
            waited = time.time() - start
        self.assertTrue(pathlib.Path(f"/proc/{child}").exists())  # the child is still alive...
        self.assertLess(waited, 2.0)  # ...and holds nothing

    def test_a_child_left_by_a_dead_writer_does_not_keep_the_lock(self) -> None:
        import time
        for how in ("fork", "exec"):
            with self.subTest(how=how):
                ctx = multiprocessing.get_context("spawn")
                out = self.temp / f"child-{how}"
                owner = ctx.Process(target=_owner_that_forks_and_dies, args=(str(self.store.path), how, str(out)))
                owner.start()
                deadline = time.time() + 60
                while owner.is_alive() and time.time() < deadline:  # not join(): the child inherits its sentinel
                    time.sleep(0.05)
                child = int(out.read_text())
                start = time.time()
                with self.store.tx():
                    waited = time.time() - start
                self.assertTrue(pathlib.Path(f"/proc/{child}").exists())  # the child is still alive...
                self.assertLess(waited, 2.0)  # ...and the lock was free anyway
        ctx = multiprocessing.get_context("spawn")
        out = self.temp / "child-hold"
        owner = ctx.Process(target=_owner_that_forks_and_dies, args=(str(self.store.path), "hold", str(out)))
        owner.start()
        while not out.exists():
            time.sleep(0.02)
        start = time.time()
        with self.store.tx():
            self.assertGreater(time.time() - start, 1.0)  # the parent kept its lock after the child closed its copy
        owner.join(30)

    def test_writers_take_turns_when_one_burst_outlasts_the_busy_timeout(self) -> None:
        # SQLite's busy handler polls, so a writer in a tight loop re-takes the lock before a waiting one wakes:
        # the waiter starves for the other's whole burst and fails with "database is locked" past busy_timeout.
        import itertools
        self.orchestration()
        ctx = multiprocessing.get_context("spawn")
        start, queue = ctx.Event(), ctx.Queue()
        procs = [ctx.Process(target=_slow_writer, args=(str(self.store.path), sender, 12, 0.15, start, queue))
                 for sender in ("s606-preparer", "consultor-claude")]
        for proc in procs:
            proc.start()
        import time
        time.sleep(2)
        start.set()
        for proc in procs:
            proc.join(120)
        results = [queue.get(timeout=5) for _ in procs]
        self.assertEqual(sorted(r[0] for r in results), ["ok", "ok"], results)
        senders = [r[0] for r in self.store.q("SELECT from_agent FROM messages WHERE type='INFO' ORDER BY rowid")]
        self.assertLessEqual(max(len(list(g)) for _, g in itertools.groupby(senders)), 2, senders)


    def test_pragmas_permissions_and_schema(self) -> None:
        con = self.store.con
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.store.path.parent.stat().st_mode), 0o700)
        self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                         str(migrations.LATEST))
        self.assertIn("receipted_by", [row[1] for row in con.execute("PRAGMA table_info(receipts)")])
        Store(self.store.path).close()  # reopening migrates nothing twice

    def test_messages_and_receipts_are_immutable(self) -> None:
        self.orchestration()
        sent = self.send(sender="orquestrador", to="s606-preparer")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.x("UPDATE messages SET subject='x' WHERE id=?", (sent["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.x("DELETE FROM messages WHERE id=?", (sent["id"],))
        library.receipt(self.store, message_id=sent["id"], agent="s606-preparer", disposition="ok")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.x("UPDATE receipts SET disposition='y' WHERE message_id=?", (sent["id"],))

    def test_published_protocols_are_pinned_by_hash(self) -> None:
        pinned = protocols.published()
        for key, digest in pinned.items():
            name, version = key.split("/")
            with self.subTest(protocol=key):
                self.assertEqual(hashlib.sha256(protocols.path_of(name, version).read_bytes()).hexdigest(), digest)
        self.assertEqual(set(pinned), {"orchestration/1.0.0", "swarm/3.0.0"})
        with self.assertRaises(protocols.ProtocolMissing):
            protocols.load("swarm", "9.9.9")
        with self.assertRaises(protocols.ProtocolMissing):
            protocols.load("../etc", "1.0.0")

    def test_two_writers_in_wal_both_land(self) -> None:
        self.orchestration()
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        procs = [ctx.Process(target=_writer, args=(str(self.store.path), sender, 40, queue))
                 for sender in ("s606-preparer", "consultor-claude")]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(120)
        results = [queue.get(timeout=5) for _ in procs]
        self.assertEqual(sorted(r[0] for r in results), ["ok", "ok"], results)
        count = self.store.one("SELECT COUNT(*) FROM messages")[0]
        self.assertEqual(count, 80)
        self.assertEqual(self.store.one("PRAGMA integrity_check")[0], "ok")


class OrchestrationProtocolTest(CorreioCase):
    def setUp(self) -> None:
        super().setUp()
        self.orchestration()

    def test_members_threads_and_replies(self) -> None:
        with self.assertRaisesRegex(CorreioError, "not a member"):
            self.send(sender="estranho", to="orquestrador")
        with self.assertRaisesRegex(CorreioError, "not a member"):
            self.send(sender="orquestrador", to="estranho")
        with self.assertRaisesRegex(CorreioError, "thread is required"):
            self.send(sender="orquestrador", to="s606-preparer", thread=None)
        with self.assertRaisesRegex(CorreioError, "thread must be a key"):
            self.send(sender="orquestrador", to="s606-preparer", thread="S606 R2")
        with self.assertRaisesRegex(CorreioError, "reserved sender"):
            self.send(sender="correio", to="s606-preparer")
        ask = self.send(sender="orquestrador", to="s606-preparer")
        with self.assertRaisesRegex(CorreioError, "thread of its message"):
            self.send(sender="s606-preparer", to="orquestrador", type="ENTREGA", thread="S607", reply_to=ask["id"])
        with self.assertRaisesRegex(CorreioError, "addressed to you"):
            self.send(sender="consultor-claude", to="orquestrador", type="ENTREGA", reply_to=ask["id"])
        overview = library.overview(self.store, "orq")["spaces"][0]
        self.assertEqual([m["id"] for m in overview["unanswered"]], [ask["id"]])
        self.send(sender="s606-preparer", to="orquestrador", type="ENTREGA", reply_to=ask["id"])
        overview = library.overview(self.store, "orq")["spaces"][0]
        self.assertEqual(overview["unanswered"], [])
        self.assertEqual(library.show(self.store, ask["id"])["replies"], [library.thread(
            self.store, "S606")["threads"][0]["messages"][1]["id"]])

    def test_info_closes_a_thread_and_new_mail_reopens_it(self) -> None:
        self.send(sender="orquestrador", to="s606-preparer")
        info = self.send(sender="orquestrador", to="s606-preparer", type="INFO", fields={"close": True})
        self.assertEqual(info["delivery"], "info")
        thread = library.thread(self.store, "S606")["threads"][0]
        self.assertEqual(thread["state"], "closed")
        self.send(sender="s606-preparer", to="orquestrador")
        self.assertEqual(library.thread(self.store, "S606")["threads"][0]["state"], "open")
        with self.assertRaisesRegex(CorreioError, "close must be true or false"):
            self.send(sender="orquestrador", to="s606-preparer", type="INFO", fields={"close": "yes"})

    def test_owner_question_and_answer_go_only_through_the_spokesperson(self) -> None:
        questions = json.dumps([{"question": "Aprovas?", "header": "S606", "multiSelect": False,
                                 "options": [{"label": "Sim", "description": "a"}, {"label": "Não", "description": "b"}]}])
        fields = {"askUserQuestion": questions, "request": "REQUEST-15"}
        with self.assertRaisesRegex(CorreioError, "orchestrator to the spokesperson"):
            self.send(sender="s606-preparer", to="porta-voz", type="OWNER_QUESTION", fields=fields)
        with self.assertRaisesRegex(CorreioError, "at least two options"):
            self.send(sender="orquestrador", to="porta-voz", type="OWNER_QUESTION", thread="S606/REQUEST-15",
                      fields={**fields, "askUserQuestion": json.dumps([{"question": "x", "options": []}])})
        with self.assertRaisesRegex(CorreioError, "JSON string"):
            self.send(sender="orquestrador", to="porta-voz", type="OWNER_QUESTION", fields={"request": "R"})
        ask = self.send(sender="orquestrador", to="porta-voz", type="OWNER_QUESTION", thread="S606/REQUEST-15",
                        fields=fields)
        answers = json.dumps({"Aprovas?": "Sim"})
        with self.assertRaisesRegex(CorreioError, "--reply-to the OWNER_QUESTION"):
            self.send(sender="porta-voz", to="orquestrador", type="OWNER_ANSWER", thread="S606/REQUEST-15",
                      fields={"answers": answers, "request": "REQUEST-15"})
        with self.assertRaisesRegex(CorreioError, "must equal the question's request"):
            self.send(sender="porta-voz", to="orquestrador", type="OWNER_ANSWER", thread="S606/REQUEST-15",
                      reply_to=ask["id"], fields={"answers": answers, "request": "REQUEST-16"})
        with self.assertRaisesRegex(CorreioError, "spokesperson to the orchestrator"):
            self.send(sender="porta-voz", to="s606-preparer", type="OWNER_ANSWER", thread="S606/REQUEST-15",
                      fields={"answers": answers, "request": "REQUEST-15"})
        answer = self.send(sender="porta-voz", to="orquestrador", type="OWNER_ANSWER", thread="S606/REQUEST-15",
                           reply_to=ask["id"], fields={"answers": answers, "request": "REQUEST-15"})
        self.assertEqual(json.loads(self.store.message(answer["id"])["fields"]["answers"]), {"Aprovas?": "Sim"})

    def test_receipts_are_idempotent_conflicts_refused_and_info_receipted_in_bulk(self) -> None:
        sent = self.send(sender="orquestrador", to="s606-preparer")
        with self.assertRaisesRegex(CorreioError, "not the message recipient"):
            library.receipt(self.store, message_id=sent["id"], agent="orquestrador", disposition="x")
        with self.assertRaisesRegex(CorreioError, "nonempty disposition"):
            library.receipt(self.store, message_id=sent["id"], agent="s606-preparer", disposition=" ")
        first = library.receipt(self.store, message_id=sent["id"], agent="s606-preparer", disposition="a fazer")
        again = library.receipt(self.store, message_id=sent["id"], agent="s606-preparer", disposition="a fazer")
        self.assertEqual((first["idempotent"], again["idempotent"]), (False, True))
        with self.assertRaisesRegex(CorreioError, "conflicting receipt"):
            library.receipt(self.store, message_id=sent["id"], agent="s606-preparer", disposition="outra")
        for n in range(3):
            self.send(sender="orquestrador", to="s606-preparer", type="INFO", subject=f"info {n}")
        inbox = library.inbox(self.store, agent="s606-preparer")
        self.assertEqual((inbox["count"], len(inbox["info"])), (0, 3))
        done = library.receipt_all_info(self.store, agent="s606-preparer", disposition="lido")
        self.assertEqual(len(done), 3)
        self.assertEqual(library.inbox(self.store, agent="s606-preparer")["info"], [])

    def test_the_sender_is_checked_against_the_calling_pane(self) -> None:
        os.environ["HERDR_PANE_ID"] = "p-s606-preparer"
        with self.assertRaisesRegex(CorreioError, "recorded in pane p-orquestrador"):
            self.send(sender="orquestrador", to="s606-preparer")
        sent = self.send(sender="s606-preparer", to="orquestrador")
        with self.assertRaisesRegex(CorreioError, "recorded in pane p-orquestrador"):
            library.receipt(self.store, message_id=sent["id"], agent="orquestrador", disposition="spoofed")
        library.add_member(self.store, "orq", "sem-pane", "other")
        with self.assertRaisesRegex(CorreioError, "sem-pane has no pane recorded"):  # p-s606-preparer is not its pane
            self.send(sender="sem-pane", to="orquestrador")
        os.environ["HERDR_PANE_ID"] = "p-orquestrador"
        library.receipt(self.store, message_id=sent["id"], agent="orquestrador", disposition="mine")
        os.environ["HERDR_PANE_ID"] = "p-de-ninguem"  # inside Herdr, a member without a pane proves nothing
        with self.assertRaisesRegex(CorreioError, "sem-pane has no pane recorded in orq"):
            self.send(sender="sem-pane", to="orquestrador")
        ask = self.send(sender="orquestrador", to="sem-pane", check_pane=False)
        with self.assertRaisesRegex(CorreioError, "sem-pane has no pane recorded in orq"):
            library.receipt(self.store, message_id=ask["id"], agent="sem-pane", disposition="x")
        with self.assertRaisesRegex(CorreioError, "recorded in pane p-orquestrador"):
            self.send(sender="orquestrador", to="s606-preparer")
        # The courier is a service process: its system mail is never checked against a pane.
        self.assertIsNotNone(library.system_mail(self.store, to="orquestrador", type="INFO", subject="s", body="",
                                                 thread="correio/teste", space="orq"))
        library.update_member(self.store, "orq", "sem-pane", pane_id="p-de-ninguem")
        self.send(sender="sem-pane", to="orquestrador")
        os.environ.pop("HERDR_PANE_ID")
        library.update_member(self.store, "orq", "sem-pane", pane_id=None)
        self.send(sender="sem-pane", to="orquestrador")  # outside Herdr nothing is checked

    def test_attachments_are_cited_by_path_and_hash(self) -> None:
        report = self.temp / "report.md"
        report.write_text("relatório\n")
        sent = self.send(sender="s606-preparer", to="orquestrador", type="ENTREGA", attachments=[report])
        shown = library.show(self.store, sent["id"])
        self.assertEqual(shown["attachments"][0]["sha256"], hashlib.sha256(report.read_bytes()).hexdigest())
        self.assertTrue(shown["attachments"][0]["unchanged"])
        self.assertIn(str(report), shown["envelope"])
        report.write_text("mudou\n")
        self.assertFalse(library.show(self.store, sent["id"])["attachments"][0]["unchanged"])
        with self.assertRaisesRegex(CorreioError, "not a file"):
            self.send(sender="s606-preparer", to="orquestrador", attachments=[self.temp / "missing"])

    def test_search_export_and_its_verifiable_hashes(self) -> None:
        self.send(sender="orquestrador", to="s606-preparer", subject="guard de substrato", body="censo abaixo do piso")
        self.send(sender="s606-preparer", to="orquestrador", type="ENTREGA", subject="outro", body="nada")
        found = library.search(self.store, "piso")
        self.assertEqual(found["mode"], "fts5" if self.store.fts else "like")
        self.assertEqual([r["subject"] for r in found["results"]], ["guard de substrato"])
        out = self.temp / "export"
        result = library.export_space(self.store, "orq", out)
        self.assertEqual(result["messages"], 2)
        rows = [json.loads(line) for line in (out / "messages.jsonl").read_text().splitlines()]
        for row in rows:
            data = (out / row["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertEqual(self.store.message(row["id"])["envelope"], data)
        for line in (out / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)
        with self.assertRaisesRegex(CorreioError, "not empty"):
            library.export_space(self.store, "orq", out)

    def test_a_space_needs_a_published_protocol_and_keeps_it(self) -> None:
        with self.assertRaises(CorreioError):
            library.create_space(self.store, space_id="x", kind="orchestration", protocol="orchestration",
                                 version="1.0.1")
        with self.assertRaisesRegex(CorreioError, "launch contract"):
            library.create_space(self.store, space_id="s1", kind="swarm", protocol="swarm", version="3.0.0")
        with self.assertRaisesRegex(CorreioError, "already exists"):
            library.create_space(self.store, space_id="orq", kind="orchestration", protocol="swarm", version="3.0.0")
        self.assertEqual(library.create_space(self.store, space_id="orq", kind="orchestration",
                                              protocol="orchestration", version="1.0.0")["id"], "orq")
        library.close_space(self.store, "orq")
        with self.assertRaisesRegex(CorreioError, "closed"):
            self.send(sender="orquestrador", to="s606-preparer")

    def test_member_grants_and_generations(self) -> None:
        member = library.update_member(self.store, "orq", "consultor-claude", set_attributes={"grant": "S606-R2"})
        self.assertEqual(member["attributes"], {"grant": "S606-R2"})
        member = library.update_member(self.store, "orq", "consultor-claude", clear_attributes=["grant"])
        self.assertEqual(member["attributes"], {})
        self.assertEqual(library.bump_generation(self.store, "orq", "s606-preparer"), 2)
        with self.assertRaisesRegex(CorreioError, "stale"):
            self.send(sender="s606-preparer", to="orquestrador", generation=1)
        library.leave_member(self.store, "orq", "s606-preparer")
        with self.assertRaisesRegex(CorreioError, "not a member"):
            self.send(sender="orquestrador", to="s606-preparer")


def _starter(db: str, job_id: str, barrier, queue) -> None:
    store = Store(db)
    try:
        barrier.wait(30)
        library.jobs_start(store, job_id, runner_pid=os.getpid())
        queue.put(("ok", job_id))
    except CorreioError as exc:
        queue.put(("refused", str(exc)))
    finally:
        store.close()


class JobsTest(CorreioCase):
    def test_a_closed_queue_refuses_new_jobs_with_the_way_back(self) -> None:
        library.jobs_add(self.store, kind="gate", who="s1", cmd="x")
        library.jobs_close(self.store, "rollback: a fila voltou ao lease-queue.jsonl")
        with self.assertRaisesRegex(CorreioError, "host queue is closed.*lease-queue.jsonl.*nothing was queued"):
            library.jobs_add(self.store, kind="gate", who="s2", cmd="y")
        self.assertEqual(len(library.jobs_list(self.store)), 1)
        library.jobs_reopen(self.store)
        library.jobs_add(self.store, kind="gate", who="s2", cmd="y")

    def test_two_simultaneous_starts_run_one_job(self) -> None:
        a = library.jobs_add(self.store, kind="gate", who="s601", cmd="true")
        b = library.jobs_add(self.store, kind="gate", who="s602", cmd="true")
        ctx = multiprocessing.get_context("spawn")
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        procs = [ctx.Process(target=_starter, args=(str(self.store.path), job["id"], barrier, queue))
                 for job in (a, b)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(60)
        results = sorted(queue.get(timeout=5) for _ in procs)
        self.assertEqual([r[0] for r in results], ["ok", "refused"], results)
        self.assertIn("is running", results[1][1])
        self.assertEqual(len([j for j in library.jobs_list(self.store) if j["state"] == "running"]), 1)

    def test_recovery_keeps_a_live_executor_and_closes_a_dead_one(self) -> None:
        live = subprocess.Popen(["sleep", "60"])
        try:
            job = library.jobs_add(self.store, kind="gate", who="s601", cmd="sleep 60")
            library.jobs_next(self.store, runner_pid=999999999)  # a runner that is gone
            library.jobs_attach(self.store, job["id"], live.pid)  # ...but its command still runs
            self.assertEqual(library.jobs_recover(self.store), [{"id": job["id"], "action": "alive", "pid": live.pid}])
            self.assertEqual(library.jobs_list(self.store)[0]["state"], "running")
            self.assertIsNone(library.jobs_next(self.store))
            live.kill()
            live.wait()
            self.assertEqual(library.jobs_recover(self.store),
                             [{"id": job["id"], "action": "interrupted", "pid": live.pid}])
            self.assertEqual(library.jobs_list(self.store, last=1)[0]["exit"], -1)
        finally:
            live.kill()
            live.wait()
        # The same PID with another start time is another process: a reused PID never keeps a job alive.
        other = library.jobs_add(self.store, kind="lote", who="s602", cmd="x")
        library.jobs_next(self.store, runner_pid=os.getpid())
        self.store.x("UPDATE jobs SET runner_start='other-boot:1' WHERE id=?", (other["id"],))
        self.assertEqual(library.jobs_recover(self.store)[0]["action"], "interrupted")
        # A runner that is alive keeps its job while it has not attached the command yet.
        third = library.jobs_add(self.store, kind="lote", who="s603", cmd="y")
        library.jobs_next(self.store, runner_pid=os.getpid())
        self.assertEqual(library.jobs_recover(self.store), [{"id": third["id"], "action": "alive", "pid": os.getpid()}])
        # A command that ended while its runner lives (before the runner records the exit) is not interrupted.
        done = subprocess.Popen(["sleep", "0.3"])
        library.jobs_attach(self.store, third["id"], done.pid)
        done.wait()
        self.assertEqual(library.jobs_recover(self.store), [{"id": third["id"], "action": "alive", "pid": os.getpid()}])
        # An imported running row has no executor to check: it is closed, as before.
        self.store.x("UPDATE jobs SET runner_pid=NULL, runner_start=NULL, exec_pid=NULL, exec_start=NULL WHERE id=?",
                     (third["id"],))
        self.assertEqual(library.jobs_recover(self.store)[0]["action"], "interrupted")

    def test_priority_then_arrival_and_one_running_at_a_time(self) -> None:
        a = library.jobs_add(self.store, kind="gate", who="s601", cmd="bash fila-merge.sh s601 x r1")
        b = library.jobs_add(self.store, kind="lote", who="s591", cmd="bash lote.sh")
        c = library.jobs_add(self.store, kind="gate", who="s605", cmd="bash fila-merge.sh s605 y r2", priority=1)
        d = library.jobs_add(self.store, kind="janela", who="s619", cmd="bash janela.sh")
        self.assertEqual([j["id"] for j in library.jobs_list(self.store)], [c["id"], a["id"], b["id"], d["id"]])
        first = library.jobs_next(self.store)
        self.assertEqual(first["id"], c["id"])
        self.assertIsNone(library.jobs_next(self.store))  # one job at a time
        with self.assertRaisesRegex(CorreioError, "not running"):
            library.jobs_finish(self.store, a["id"], 0)
        library.jobs_finish(self.store, c["id"], 3)
        order = []
        while (job := library.jobs_next(self.store)) is not None:
            order.append(job["id"])
            library.jobs_finish(self.store, job["id"], 0)
        self.assertEqual(order, [a["id"], b["id"], d["id"]])
        self.assertEqual([j["exit"] for j in library.jobs_list(self.store, last=4)], [0, 0, 3, 0])
        with self.assertRaisesRegex(CorreioError, "kind"):
            library.jobs_add(self.store, kind="other", who="x", cmd="y")


class CliTest(CorreioCase):
    def cli(self, *argv: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["/usr/bin/python3", str(HERE / "correio.py"), *argv], text=True, capture_output=True,
                              env=os.environ.copy(), check=check)

    def test_the_wrapper_drives_the_whole_flow(self) -> None:
        self.cli("space", "create", "--id", "orq", "--kind", "orchestration", "--protocol", "orchestration",
                 "--version", "1.0.0")
        for agent, role in (("orquestrador", "orchestrator"), ("porta-voz", "spokesperson")):
            self.cli("member", "add", "--agent", agent, "--role", role)
        questions = self.temp / "q.json"
        questions.write_text(json.dumps([{"question": "Q?", "options": [{"label": "A"}, {"label": "B"}]}]))
        sent = json.loads(self.cli("send", "--thread", "geral/REQUEST-1", "--type", "OWNER_QUESTION", "--from",
                                   "orquestrador", "--to", "porta-voz", "--subject", "Pergunta",
                                   "--field-file", f"askUserQuestion={questions}", "--field", "request=REQUEST-1",
                                   "--field", "n:=2").stdout)
        message = json.loads(self.cli("show", sent["id"], "--json").stdout)
        self.assertEqual(message["fields"]["n"], 2)
        self.assertEqual(json.loads(message["fields"]["askUserQuestion"])[0]["question"], "Q?")
        self.assertIn("Por tratar (1)", self.cli("inbox", "--agent", "porta-voz").stdout)
        self.assertIn(sent["id"], self.cli("pending", "--agent", "porta-voz").stdout)  # v1 spelling still answers
        self.cli("receipt", "--agent", "porta-voz", "--id", sent["id"], "--disposition", "a perguntar")
        self.assertEqual(self.cli("show", sent["id"], "--raw").stdout.encode(),
                         Store(os.environ["CORREIO_DB"]).message(sent["id"])["envelope"])
        refused = self.cli("send", "--type", "PEDIDO", "--from", "orquestrador", "--to", "porta-voz",
                           "--subject", "x", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("send needs --thread", refused.stderr)
        self.assertIn("orq", self.cli("open").stdout)
        job = json.loads(self.cli("jobs", "add", "--kind", "gate", "--who", "s1", "--", "bash", "x.sh", "a b").stdout)
        self.assertEqual(job["cmd"], "bash x.sh a b")
        self.assertEqual(json.loads(self.cli("jobs", "next").stdout)["id"], job["id"])
        self.assertIsNone(json.loads(self.cli("jobs", "next").stdout))
        self.assertIn("legacy", self.cli("legacy", "--help").stdout)


if __name__ == "__main__":
    unittest.main()
