"""Importers: the v1 file mailbox, a 2.7 run (fixtures/run-s605, a scrubbed structural copy of the real S605
run) and the JSONL host queue. Set COURIER_TEST_V1_COPY, COURIER_TEST_RUN_COPIES (os.pathsep-separated run
directories) or COURIER_TEST_JOBS_COPY to also import copies of live data."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import unittest

from courier import importers, library
from courier.store import CourierError
from courier_testing import CourierCase

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "run-s605"


class V1ImportTest(CourierCase):
    def mailbox(self) -> pathlib.Path:
        root = self.temp / "v1-mailbox"
        body = self.temp / "brief.md"
        body.write_text("brief\n")
        messages = [
            ("orchestrator", {"id": "20261025T123708189691Z-05c030e8", "from": "orchestrator", "to": "spokesperson",
                              "type": "PEDIDO", "subject": "TESTE-1: pergunta", "sentAt": "2026-10-25T12:37:08Z",
                              "body": "Pergunta.", "payload": {"request": "TESTE-1", "askUserQuestion": [
                                  {"question": "Q?", "options": [{"label": "A"}, {"label": "B"}]}]}}),
            ("spokesperson", {"id": "20261025T124243008032Z-91cfdfdb", "from": "spokesperson", "to": "orchestrator",
                           "type": "ENTREGA", "subject": "Resposta a TESTE-1", "sentAt": "2026-10-25T12:42:43Z",
                           "body": "TESTE-1 respondido", "payload": {"request": "TESTE-1", "answers": {"Q?": "A"}}}),
            ("s606-preparer", {"id": "20261025T130000000000Z-aaaaaaaa", "from": "s606-preparer", "to": "orchestrator",
                               "type": "ENTREGA", "subject": "S606 setup r13 pronto", "sentAt": "2026-10-25T13:00:00Z",
                               "bodyFile": {"path": str(body), "sha256": "b" * 64}}),
            ("correio", {"id": "20261025T140000000000Z-bbbbbbbb", "from": "correio", "to": "orchestrator",
                         "type": "PEDIDO", "subject": "consultant-codex blocked", "sentAt": "2026-10-25T14:00:00Z",
                         "body": "x"}),
        ]
        for _sender, message in messages:
            path = root / "inbox" / message["to"] / f"{message['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(message, ensure_ascii=False, indent=1) + "\n")
        receipt = root / "receipts" / "spokesperson" / "20261025T123708189691Z-05c030e8.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"id": "20261025T123708189691Z-05c030e8", "agent": "spokesperson",
                                       "disposition": "a apresentar", "receiptedAt": "2026-10-25T12:38:00Z"}))
        return root

    def test_v1_mail_lands_in_threads_by_slice_with_its_receipts(self) -> None:
        library.create_space(self.store, space_id="orch", kind="orchestration", protocol="orchestration",
                             version="2.0.0")
        root = self.mailbox()
        counts = importers.import_files(self.store, root)
        self.assertEqual((counts["messages"], counts["receipts"], counts["errors"]), (4, 1, []))
        self.assertEqual(set(self.store.members("orch")), {"orchestrator", "spokesperson", "s606-preparer"})
        self.assertEqual(self.store.member("orch", "spokesperson")["role"], "spokesperson")
        threads = {r["key"] for r in self.store.q("SELECT key FROM threads WHERE space_id='orch'")}
        self.assertEqual(threads, {"general/TESTE-1", "S606", "general"})
        question = self.store.find_messages("orch", field_legacyId="20261025T123708189691Z-05c030e8")[0]
        self.assertEqual(json.loads(question["fields"]["askUserQuestion"])[0]["question"], "Q?")
        self.assertTrue(self.store.receipt(question["id"])["accepted"])
        brief = self.store.find_messages("orch", thread_id=self.store.one(
            "SELECT id FROM threads WHERE key='S606'")[0])[0]
        self.assertEqual(library.show(self.store, brief["id"])["attachments"][0]["path"],
                         str(self.temp / "brief.md"))
        types = {m["fields"]["legacyId"][-8:]: m["type"] for m in self.store.find_messages("orch")}
        self.assertEqual(types, {"05c030e8": "REQUEST", "91cfdfdb": "DELIVERY", "aaaaaaaa": "DELIVERY",
                                 "bbbbbbbb": "REQUEST"})  # the v1 PEDIDO and ENTREGA in this protocol's names
        again = importers.import_files(self.store, root)
        self.assertEqual((again["messages"], again["skipped"], again["receipts"]), (0, 4, 0))
        pending = library.inbox(self.store, agent="orchestrator")
        self.assertEqual(pending["count"], 3)  # unreceipted v1 mail stays pending, so the courier carries it over

    def test_v1_mail_keeps_its_types_in_a_space_created_before_the_rename(self) -> None:
        library.create_space(self.store, space_id="orch", kind="orchestration", protocol="orchestration",
                             version="1.0.0")
        self.assertEqual(importers.import_files(self.store, self.mailbox())["errors"], [])
        self.assertEqual(sorted(m["type"] for m in self.store.find_messages("orch")),
                         ["ENTREGA", "ENTREGA", "PEDIDO", "PEDIDO"])

    def test_a_changed_attachment_warns_and_later_receipts_still_import(self) -> None:
        library.create_space(self.store, space_id="orch", kind="orchestration", protocol="orchestration",
                             version="2.0.0")
        root = self.mailbox()
        self.assertEqual(importers.import_files(self.store, root)["errors"], [])
        (self.temp / "brief.md").write_text("brief alterado, maior\n")  # the v1 JSON stays as it was
        receipt = root / "receipts" / "orchestrator" / "20261025T130000000000Z-aaaaaaaa.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"id": "20261025T130000000000Z-aaaaaaaa", "agent": "orchestrator",
                                       "disposition": "read", "receiptedAt": "2026-10-25T13:05:00Z"}))
        again = importers.import_files(self.store, root)
        self.assertEqual((again["errors"], again["receipts"], again["messages"]), ([], 1, 0))
        self.assertEqual([w["path"] for w in again["warnings"]], [str(self.temp / "brief.md")])
        message = library.resolve_message(self.store, "20261025T130000000000Z-aaaaaaaa", "orchestrator")
        self.assertEqual(self.store.receipt(message)["disposition"], "read")

    def test_an_unreadable_attachment_warns_and_later_receipts_still_import(self) -> None:
        library.create_space(self.store, space_id="orch", kind="orchestration", protocol="orchestration",
                             version="2.0.0")
        root = self.mailbox()
        self.assertEqual(importers.import_files(self.store, root)["errors"], [])
        brief = self.temp / "brief.md"
        receipt = root / "receipts" / "orchestrator" / "20261025T130000000000Z-aaaaaaaa.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        message = library.resolve_message(self.store, "20261025T130000000000Z-aaaaaaaa", "orchestrator")
        for case in ("chmod 000", "directory", "missing"):
            with self.subTest(case=case):
                if case == "chmod 000":
                    brief.chmod(0)
                elif case == "directory":
                    brief.chmod(0o600)
                    brief.unlink()
                    brief.mkdir()
                else:
                    brief.rmdir()
                again = importers.import_files(self.store, root)
                self.assertEqual(again["errors"], [])
                self.assertEqual([w["path"] for w in again["warnings"]], [str(brief)])
                if case == "chmod 000":  # the receipt arrives while the attachment cannot be read
                    receipt.write_text(json.dumps({"id": "20261025T130000000000Z-aaaaaaaa", "agent": "orchestrator",
                                                   "disposition": "read", "receiptedAt": "2026-10-25T13:05:00Z"}))
                    self.assertEqual(importers.import_files(self.store, root)["receipts"], 1)
                    self.assertEqual(self.store.receipt(message)["disposition"], "read")

    @unittest.skipUnless(os.environ.get("COURIER_TEST_V1_COPY"), "set COURIER_TEST_V1_COPY to a copy of correio/")
    def test_a_copy_of_the_live_v1_mailbox_imports_cleanly(self) -> None:
        library.create_space(self.store, space_id="orch", kind="orchestration", protocol="orchestration",
                             version="2.0.0")
        root = pathlib.Path(os.environ["COURIER_TEST_V1_COPY"])
        counts = importers.import_files(self.store, root)
        files = len(list(root.glob("inbox/*/*.json")))
        self.assertEqual(counts["errors"], [])
        self.assertEqual(counts["messages"], files)
        self.assertEqual(counts["receipts"], len(list(root.glob("receipts/*/*.json"))))


class RunImportTest(CourierCase):
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
        self.assertIn("orquestrador", self.store.members("s605"))  # the name the run recorded, as recorded
        message = self.store.find_messages("s605", type="SLICE_READY")[0]
        source = library.show(self.store, message["id"])
        self.assertTrue(source["attachments"][0]["unchanged"])
        self.assertTrue(source["body"].startswith("```json"))
        again = importers.import_run(self.store, run)
        self.assertEqual((again["messages"], again["skipped"]), (0, events))
        with self.assertRaisesRegex(CourierError, "read-only"):
            library.receipt(self.store, message_id=message["id"], agent="orquestrador", disposition="x")
        self.assertEqual(library.inbox(self.store, agent="orquestrador")["count"], 0)  # legacy never pends

    def test_a_run_imported_before_the_rename_refreshes_without_errors(self) -> None:
        # Its envelopes were stored as "correio: 2"; a refresh rebuilds each one with that marker, same bytes.
        from courier import envelope as env
        run = self.run_copy()
        env.MARKER = env.LEGACY_MARKER
        try:
            first = importers.import_run(self.store, run)
        finally:
            env.MARKER = "courier"
        self.assertEqual(first["errors"], [])
        stored = self.store.find_messages("s605", type="SLICE_READY")[0]["envelope"]
        self.assertTrue(stored.startswith(b"---\ncorreio: 2\n"))
        again = importers.import_run(self.store, run)
        self.assertEqual((again["errors"], again["messages"], again["skipped"]), ([], 0, first["messages"]))

    def test_a_live_legacy_run_refreshes_and_a_foreign_space_is_refused(self) -> None:
        run = self.run_copy()
        for receipt in run.glob("receipts/*/*.json"):
            event = json.loads((run / "inbox" / receipt.parent.name / receipt.name).read_text())
            if event["type"] == "SLICE_ACCEPTED":
                receipt.unlink()
        importers.import_run(self.store, run)
        self.assertIsNone(self.store.space("s605")["closed_at"])
        library.create_space(self.store, space_id="orch", kind="orchestration", protocol="orchestration",
                             version="2.0.0")
        launch = json.loads((run / "launch.json").read_text())
        launch["runId"] = "00000000-0000-4000-8000-000000000000"
        (run / "launch.json").write_text(json.dumps(launch))
        with self.assertRaisesRegex(CourierError, "not this run's legacy import"):
            importers.import_run(self.store, run)

    @unittest.skipUnless(os.environ.get("COURIER_TEST_RUN_COPIES"), "set COURIER_TEST_RUN_COPIES to run copies")
    def test_copies_of_live_runs_import_cleanly(self) -> None:
        for path in os.environ["COURIER_TEST_RUN_COPIES"].split(os.pathsep):
            with self.subTest(run=path):
                counts = importers.import_run(self.store, path)
                self.assertEqual(counts["errors"], [])
                self.assertEqual(counts["messages"], len(list(pathlib.Path(path).glob("inbox/*/*.json"))))


class JobsImportTest(CourierCase):
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
        self.assertEqual([(j["id"], j["kind"], j["state"], j["exit"]) for j in jobs],  # v1 "lote" is a batch
                         [("f2fd8131", "batch", "done", 0), ("cb2d5ce3", "batch", "done", 3),
                          ("q1", "gate", "queued", None)])
        self.assertEqual(importers.import_jobs(self.store, queue)["skipped"], 3)
        self.assertEqual(library.jobs_next(self.store)["id"], "q1")

    @unittest.skipUnless(os.environ.get("COURIER_TEST_JOBS_COPY"), "set COURIER_TEST_JOBS_COPY to a JSONL copy")
    def test_a_copy_of_the_live_queue_imports_cleanly(self) -> None:
        counts = importers.import_jobs(self.store, os.environ["COURIER_TEST_JOBS_COPY"])
        self.assertEqual(counts["errors"], [])


if __name__ == "__main__":
    unittest.main()
