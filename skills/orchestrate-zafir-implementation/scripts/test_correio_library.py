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

from correio import library, protocols
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


class StoreTest(CorreioCase):
    def test_pragmas_permissions_and_schema(self) -> None:
        con = self.store.con
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.store.path.parent.stat().st_mode), 0o700)
        self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "1")
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


class JobsTest(CorreioCase):
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
        self.assertIn("--thread is required", refused.stderr)
        self.assertIn("orq", self.cli("open").stdout)
        job = json.loads(self.cli("jobs", "add", "--kind", "gate", "--who", "s1", "--", "bash", "x.sh", "a b").stdout)
        self.assertEqual(job["cmd"], "bash x.sh a b")
        self.assertEqual(json.loads(self.cli("jobs", "next").stdout)["id"], job["id"])
        self.assertIsNone(json.loads(self.cli("jobs", "next").stdout))
        self.assertIn("legacy", self.cli("legacy", "--help").stdout)


if __name__ == "__main__":
    unittest.main()
