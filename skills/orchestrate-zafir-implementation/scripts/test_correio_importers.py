"""Importers: the v1 file mailbox, a 2.7 run (fixtures/run-s605, a scrubbed structural copy of the real S605
run) and the JSONL host queue. Set CORREIO_TEST_V1_COPY, CORREIO_TEST_RUN_COPIES (os.pathsep-separated run
directories) or CORREIO_TEST_JOBS_COPY to also import copies of live data."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import unittest

from correio import importers, library
from correio.store import CorreioError
from correio_testing import CorreioCase

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "run-s605"


class V1ImportTest(CorreioCase):
    def mailbox(self) -> pathlib.Path:
        root = self.temp / "correio-v1"
        body = self.temp / "brief.md"
        body.write_text("brief\n")
        messages = [
            ("orquestrador", {"id": "20261025T123708189691Z-05c030e8", "from": "orquestrador", "to": "porta-voz",
                              "type": "PEDIDO", "subject": "TESTE-1: pergunta", "sentAt": "2026-10-25T12:37:08Z",
                              "body": "Pergunta.", "payload": {"request": "TESTE-1", "askUserQuestion": [
                                  {"question": "Q?", "options": [{"label": "A"}, {"label": "B"}]}]}}),
            ("porta-voz", {"id": "20261025T124243008032Z-91cfdfdb", "from": "porta-voz", "to": "orquestrador",
                           "type": "ENTREGA", "subject": "Resposta a TESTE-1", "sentAt": "2026-10-25T12:42:43Z",
                           "body": "TESTE-1 respondido", "payload": {"request": "TESTE-1", "answers": {"Q?": "A"}}}),
            ("s606-preparer", {"id": "20261025T130000000000Z-aaaaaaaa", "from": "s606-preparer", "to": "orquestrador",
                               "type": "ENTREGA", "subject": "S606 setup r13 pronto", "sentAt": "2026-10-25T13:00:00Z",
                               "bodyFile": {"path": str(body), "sha256": "b" * 64}}),
            ("correio", {"id": "20261025T140000000000Z-bbbbbbbb", "from": "correio", "to": "orquestrador",
                         "type": "PEDIDO", "subject": "consultor-codex blocked", "sentAt": "2026-10-25T14:00:00Z",
                         "body": "x"}),
        ]
        for _sender, message in messages:
            path = root / "inbox" / message["to"] / f"{message['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(message, ensure_ascii=False, indent=1) + "\n")
        receipt = root / "receipts" / "porta-voz" / "20261025T123708189691Z-05c030e8.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"id": "20261025T123708189691Z-05c030e8", "agent": "porta-voz",
                                       "disposition": "a apresentar", "receiptedAt": "2026-10-25T12:38:00Z"}))
        return root

    def test_v1_mail_lands_in_threads_by_slice_with_its_receipts(self) -> None:
        library.create_space(self.store, space_id="orq", kind="orchestration", protocol="orchestration",
                             version="1.0.0")
        root = self.mailbox()
        counts = importers.import_files(self.store, root)
        self.assertEqual((counts["messages"], counts["receipts"], counts["errors"]), (4, 1, []))
        self.assertEqual(set(self.store.members("orq")), {"orquestrador", "porta-voz", "s606-preparer"})
        self.assertEqual(self.store.member("orq", "porta-voz")["role"], "spokesperson")
        threads = {r["key"] for r in self.store.q("SELECT key FROM threads WHERE space_id='orq'")}
        self.assertEqual(threads, {"geral/TESTE-1", "S606", "geral"})
        question = self.store.find_messages("orq", field_legacyId="20261025T123708189691Z-05c030e8")[0]
        self.assertEqual(json.loads(question["fields"]["askUserQuestion"])[0]["question"], "Q?")
        self.assertTrue(self.store.receipt(question["id"])["accepted"])
        brief = self.store.find_messages("orq", thread_id=self.store.one(
            "SELECT id FROM threads WHERE key='S606'")[0])[0]
        self.assertEqual(library.show(self.store, brief["id"])["attachments"][0]["path"],
                         str(self.temp / "brief.md"))
        again = importers.import_files(self.store, root)
        self.assertEqual((again["messages"], again["skipped"], again["receipts"]), (0, 4, 0))
        pending = library.inbox(self.store, agent="orquestrador")
        self.assertEqual(pending["count"], 3)  # unreceipted v1 mail stays pending, so the courier carries it over

    @unittest.skipUnless(os.environ.get("CORREIO_TEST_V1_COPY"), "set CORREIO_TEST_V1_COPY to a copy of correio/")
    def test_a_copy_of_the_live_v1_mailbox_imports_cleanly(self) -> None:
        library.create_space(self.store, space_id="orq", kind="orchestration", protocol="orchestration",
                             version="1.0.0")
        root = pathlib.Path(os.environ["CORREIO_TEST_V1_COPY"])
        counts = importers.import_files(self.store, root)
        files = len(list(root.glob("inbox/*/*.json")))
        self.assertEqual(counts["errors"], [])
        self.assertEqual(counts["messages"], files)
        self.assertEqual(counts["receipts"], len(list(root.glob("receipts/*/*.json"))))


class RunImportTest(CorreioCase):
    def run_copy(self) -> pathlib.Path:
        target = self.temp / "runs" / "s605"
        shutil.copytree(FIXTURE, target)
        return target

    def test_a_2_7_run_becomes_a_read_only_legacy_space(self) -> None:
        run = self.run_copy()
        counts = importers.import_run(self.store, run)
        events = len(list(run.glob("inbox/*/*.json")))
        self.assertEqual((counts["messages"], counts["errors"]), (events, []))
        self.assertEqual(counts["receipts"], len(list(run.glob("receipts/*/*.json"))))
        space = self.store.space("s605")
        self.assertEqual((space["legacy"], space["protocol"], space["version"]), (True, "swarm", "2.7.0"))
        self.assertEqual(space["state"], "accepted")  # its SLICE_ACCEPTED was receipted
        self.assertIsNotNone(space["closed_at"])
        state = json.loads((run / "state.json").read_text())
        self.assertEqual({t["task_id"]: t["state"] for t in self.store.tasks("s605")},
                         {k: v.get("state", "unknown") for k, v in state["tasks"].items()})
        self.assertIn("orquestrador", self.store.members("s605"))
        message = self.store.find_messages("s605", type="SLICE_READY")[0]
        source = library.show(self.store, message["id"])
        self.assertTrue(source["attachments"][0]["unchanged"])
        self.assertTrue(source["body"].startswith("```json"))
        again = importers.import_run(self.store, run)
        self.assertEqual((again["messages"], again["skipped"]), (0, events))
        with self.assertRaisesRegex(CorreioError, "read-only"):
            library.receipt(self.store, message_id=message["id"], agent="orquestrador", disposition="x")
        self.assertEqual(library.inbox(self.store, agent="orquestrador")["count"], 0)  # legacy never pends

    def test_a_live_legacy_run_refreshes_and_a_foreign_space_is_refused(self) -> None:
        run = self.run_copy()
        for receipt in run.glob("receipts/*/*.json"):
            event = json.loads((run / "inbox" / receipt.parent.name / receipt.name).read_text())
            if event["type"] == "SLICE_ACCEPTED":
                receipt.unlink()
        importers.import_run(self.store, run)
        self.assertIsNone(self.store.space("s605")["closed_at"])
        library.create_space(self.store, space_id="orq", kind="orchestration", protocol="orchestration",
                             version="1.0.0")
        launch = json.loads((run / "launch.json").read_text())
        launch["runId"] = "00000000-0000-4000-8000-000000000000"
        (run / "launch.json").write_text(json.dumps(launch))
        with self.assertRaisesRegex(CorreioError, "not this run's legacy import"):
            importers.import_run(self.store, run)

    @unittest.skipUnless(os.environ.get("CORREIO_TEST_RUN_COPIES"), "set CORREIO_TEST_RUN_COPIES to run copies")
    def test_copies_of_live_runs_import_cleanly(self) -> None:
        for path in os.environ["CORREIO_TEST_RUN_COPIES"].split(os.pathsep):
            with self.subTest(run=path):
                counts = importers.import_run(self.store, path)
                self.assertEqual(counts["errors"], [])
                self.assertEqual(counts["messages"], len(list(pathlib.Path(path).glob("inbox/*/*.json"))))


class JobsImportTest(CorreioCase):
    def test_the_jsonl_queue_imports_in_order_with_exit_codes(self) -> None:
        queue = self.temp / "lease-queue.jsonl"
        rows = [{"id": "f2fd8131", "at": "2026-10-24T11:27:33Z", "kind": "lote", "who": "s591", "cmd": "a",
                 "state": "done exit=0", "startedAt": "2026-10-24T11:27:53Z", "endedAt": "2026-10-24T12:26:33Z"},
                {"id": "cb2d5ce3", "at": "2026-10-24T09:12:22Z", "kind": "lote", "who": "s591", "cmd": "b",
                 "state": "done exit=3"},
                {"id": "q1", "at": "2026-10-25T09:00:00Z", "kind": "gate", "who": "s617", "cmd": "c", "state": "queued"}]
        queue.write_text("".join(json.dumps(r) + "\n" for r in rows) + "\n")
        counts = importers.import_jobs(self.store, queue)
        self.assertEqual((counts["jobs"], counts["errors"]), (3, []))
        jobs = library.jobs_list(self.store, everything=True)
        self.assertEqual([(j["id"], j["state"], j["exit"]) for j in jobs],
                         [("f2fd8131", "done", 0), ("cb2d5ce3", "done", 3), ("q1", "queued", None)])
        self.assertEqual(importers.import_jobs(self.store, queue)["skipped"], 3)
        self.assertEqual(library.jobs_next(self.store)["id"], "q1")

    @unittest.skipUnless(os.environ.get("CORREIO_TEST_JOBS_COPY"), "set CORREIO_TEST_JOBS_COPY to a JSONL copy")
    def test_a_copy_of_the_live_queue_imports_cleanly(self) -> None:
        counts = importers.import_jobs(self.store, os.environ["CORREIO_TEST_JOBS_COPY"])
        self.assertEqual(counts["errors"], [])


if __name__ == "__main__":
    unittest.main()
