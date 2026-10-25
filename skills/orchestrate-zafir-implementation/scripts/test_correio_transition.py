"""The cutover and its rollback: v1 commands against correio v2 (a time-boxed compatibility window), v1 IDs in
receipts, and the conversion back to a v1 mailbox and the JSONL host queue that the v1 readers accept."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

from correio import importers, library
from correio.store import Store
from correio_testing import CorreioCase
import test_correio_importers as importer_tests  # not ``from ... import``: its tests would run twice

HERE = pathlib.Path(__file__).resolve().parent
V1_OPEN = "20261025T124243008032Z-91cfdfdb"  # the porta-voz ENTREGA to orquestrador, unreceipted in v1


class TransitionCase(CorreioCase):
    mailbox = importer_tests.V1ImportTest.mailbox

    def setUp(self) -> None:
        super().setUp()
        self.orchestration()
        self.v1_root = self.mailbox()
        self.assertEqual(importers.import_files(self.store, self.v1_root, space="orq")["errors"], [])

    def cli(self, *argv: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["/usr/bin/python3", str(HERE / "correio.py"), *argv], text=True, capture_output=True,
                              env={**os.environ, **(env or {})}, check=check)

    def count(self) -> int:
        store = Store(os.environ["CORREIO_DB"])
        try:
            return store.one("SELECT COUNT(*) FROM messages")[0]
        finally:
            store.close()


class V1CommandsTest(TransitionCase):
    def test_imported_v1_ids_are_accepted_by_receipt_and_show(self) -> None:
        shown = json.loads(self.cli("show", "--agent", "orquestrador", "--id", V1_OPEN, "--json").stdout)
        self.assertEqual(shown["fields"]["legacyId"], V1_OPEN)
        done = json.loads(self.cli("receipt", "--agent", "orquestrador", "--id", V1_OPEN,
                                   "--disposition", "tratado").stdout)
        self.assertEqual(done["message_id"], shown["id"])
        self.assertTrue(library.show(self.store, shown["id"])["receipt"]["accepted"])
        # A v1 ID names the message of that recipient only.
        refused = self.cli("receipt", "--agent", "porta-voz", "--id", V1_OPEN, "--disposition", "x", check=False)
        self.assertEqual(refused.returncode, 2)

    def test_a_v1_send_fails_clearly_and_sends_nothing_outside_the_window(self) -> None:
        before = self.count()
        payload = self.temp / "payload.json"
        payload.write_text(json.dumps({"request": "REQUEST-15", "answers": {"Q?": "A"}}))
        for extra in ([], ["--payload-file", str(payload)]):
            result = self.cli("send", "--from", "s606-preparer", "--to", "orquestrador", "--type", "ENTREGA",
                              "--subject", "S606 pronto", "--body", "feito", *extra, check=False)
            self.assertEqual(result.returncode, 2)
            error = json.loads(result.stderr)["error"]
            self.assertIn("nothing was sent", error)
            self.assertIn("--thread", error)
        self.assertEqual(self.count(), before)

    def test_inside_the_window_a_v1_send_works_with_an_inferred_thread(self) -> None:
        window = json.loads(self.cli("compat", "v1", "--hours", "2").stdout)
        self.assertTrue(window["active"])
        payload = self.temp / "payload.json"
        payload.write_text(json.dumps({"request": "REQUEST-15", "answers": {"Q?": "A"}}))
        result = self.cli("send", "--from", "s606-preparer", "--to", "orquestrador", "--type", "ENTREGA",
                          "--subject", "S606 pronto", "--body", "feito", "--payload-file", str(payload))
        sent = json.loads(result.stdout)
        self.assertEqual((sent["thread"], sent["compat"]), ("S606/REQUEST-15", "v1"))
        self.assertIn("v1 compatibility", result.stderr)
        message = library.show(self.store, sent["id"])
        self.assertEqual(json.loads(message["fields"]["answers"]), {"Q?": "A"})
        self.assertIn('"answers"', message["body"])
        self.cli("compat", "v1", "--off")
        refused = self.cli("send", "--from", "s606-preparer", "--to", "orquestrador", "--type", "ENTREGA",
                           "--subject", "S606 outra", "--body", "x", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("nothing was sent", refused.stderr)


class RollbackTest(TransitionCase):
    def v1_pending(self, root: pathlib.Path, agent: str) -> list[str]:
        result = self.cli("legacy", "pending", "--agent", agent, env={"CORREIO_ROOT": str(root)})
        return [m["id"] for m in json.loads(result.stdout)["pending"]]

    def test_the_export_is_a_v1_mailbox_the_v1_reader_accepts(self) -> None:
        native = self.send(sender="s606-preparer", to="orquestrador", type="ENTREGA", subject="S606 pronto",
                           body="feito")["id"]
        handled = self.send(sender="orquestrador", to="s606-preparer", subject="S606 faz")["id"]
        library.receipt(self.store, message_id=handled, agent="s606-preparer", disposition="a fazer")
        questions = json.dumps([{"question": "Q?", "options": [{"label": "A"}, {"label": "B"}]}])
        ask = self.send(sender="orquestrador", to="porta-voz", type="OWNER_QUESTION", thread="S606/REQUEST-15",
                        fields={"askUserQuestion": questions, "request": "REQUEST-15"})["id"]
        empty = self.temp / "v1-novo"
        result = library.export_v1(self.store, "orq", empty)
        self.assertEqual(result["errors"], [])
        inbox = self.v1_pending(empty, "orquestrador")
        native_v1 = self.store.message(native)["sent_at"]
        self.assertEqual(len(inbox), 4)  # the three unreceipted v1 imports and the v2 ENTREGA
        self.assertTrue(any(i.endswith("-" + native.replace("-", "")) for i in inbox), (inbox, native_v1))
        self.assertEqual(self.v1_pending(empty, "s606-preparer"), [])  # receipted in v2: not asked again
        (question,) = self.v1_pending(empty, "porta-voz")
        shown = json.loads(self.cli("legacy", "show", "--agent", "porta-voz", "--id", question,
                                    env={"CORREIO_ROOT": str(empty)}).stdout)
        self.assertEqual((shown["type"], shown["payload"]["askUserQuestion"][0]["question"],
                          shown["correioV2"]["id"], shown["correioV2"]["type"]), ("PEDIDO", "Q?", ask, "OWNER_QUESTION"))
        self.cli("legacy", "receipt", "--agent", "porta-voz", "--id", question, "--disposition", "ok",
                 env={"CORREIO_ROOT": str(empty)})
        self.assertEqual(self.v1_pending(empty, "porta-voz"), [])

    def test_exporting_into_the_live_v1_mailbox_repeats_nothing_and_loses_nothing(self) -> None:
        library.receipt(self.store, message_id=V1_OPEN, agent="orquestrador", disposition="tratado no v2")
        native = self.send(sender="s606-preparer", to="orquestrador", type="ENTREGA", subject="S606 novo")["id"]
        files = lambda: sorted(p.relative_to(self.v1_root) for p in self.v1_root.rglob("*.json"))
        before = files()
        first = library.export_v1(self.store, "orq", self.v1_root)
        self.assertEqual((first["messages"], first["receipts"]), (1, 1))  # the new ENTREGA; V1_OPEN's v2 receipt
        pending = self.v1_pending(self.v1_root, "orquestrador")
        self.assertNotIn(V1_OPEN, pending)
        self.assertEqual(len([p for p in pending if p.endswith("-" + native.replace("-", ""))]), 1)
        self.assertTrue(set(before) <= set(files()))
        after = files()
        again = library.export_v1(self.store, "orq", self.v1_root)  # rerun after the CLI swap: only what is new
        self.assertEqual((again["messages"], again["receipts"]), (0, 0))
        self.assertEqual(files(), after)
        library.create_space(self.store, space_id="s900", kind="swarm", protocol="swarm", version="2.7.0",
                             contract={"runId": "x"}, legacy=True)
        with self.assertRaisesRegex(library.CorreioError, "orchestration"):
            library.export_v1(self.store, "s900", self.temp / "x")

    def test_a_legacy_id_is_trusted_only_from_an_import_and_a_collision_fails(self) -> None:
        # A native message that carries the same legacyId as an imported one, to the same recipient, unreceipted.
        imported = library.resolve_message(self.store, V1_OPEN, "orquestrador")
        library.receipt(self.store, message_id=imported, agent="orquestrador", disposition="tratado")
        native = self.send(sender="porta-voz", to="orquestrador", type="ENTREGA", subject="outra",
                           fields={"legacyId": V1_OPEN})["id"]
        self.assertEqual(library.resolve_message(self.store, V1_OPEN, "orquestrador"), imported)
        out = self.temp / "v1-colisao"
        library.export_v1(self.store, "orq", out)
        pending = self.v1_pending(out, "orquestrador")
        self.assertNotIn(V1_OPEN, pending)  # the imported one, receipted
        self.assertIn(library.v1_id(self.store.message(native)), pending)  # the native one keeps its own id
        receipt = json.loads((out / "receipts" / "orquestrador" / f"{V1_OPEN}.json").read_text())
        self.assertEqual(receipt["correioV2"]["id"], imported)
        # A file at the target that is another message: explicit failure, nothing written.
        foreign = self.temp / "v1-alheia"
        target = foreign / "inbox" / "orquestrador" / f"{V1_OPEN}.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"id": V1_OPEN, "from": "x", "to": "orquestrador", "type": "PEDIDO",
                                      "subject": "outra coisa", "sentAt": "2026-10-25T00:00:00Z", "body": "?"}))
        with self.assertRaisesRegex(library.CorreioError, "collision, nothing exported"):
            library.export_v1(self.store, "orq", foreign)
        self.assertEqual(sorted(p.name for p in foreign.rglob("*.json")), [f"{V1_OPEN}.json"])
        # A receipt file that belongs to other bytes is a collision too.
        library.export_v1(self.store, "orq", self.v1_root)
        receipt_path = self.v1_root / "receipts" / "orquestrador" / f"{V1_OPEN}.json"
        receipt_path.write_text(json.dumps({"id": V1_OPEN, "messageSha256": "0" * 64}))  # another file's
        with self.assertRaisesRegex(library.CorreioError, "is not the receipt of"):
            library.export_v1(self.store, "orq", self.v1_root)

    def test_a_v1_append_during_the_export_is_kept(self) -> None:
        # The v1 producer (rollback/lease-queue-v1.sh add) appends under flock on <jsonl>.lock; the export reads
        # and replaces the file under the same lock, so an append in between waits instead of being overwritten.
        import fcntl
        import threading
        from unittest import mock
        queue = self.temp / "lease-queue.jsonl"
        queue.write_text("")
        library.jobs_add(self.store, kind="gate", who="s1", cmd="x")
        real_replace = os.replace

        def v1_add() -> None:
            with open(f"{queue}.lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with queue.open("a") as out:
                    out.write(json.dumps({"id": "v1late", "kind": "lote", "who": "s2", "cmd": "y",
                                          "state": "queued", "at": "2026-10-26T00:00:00Z"}) + "\n")
        producer = threading.Thread(target=v1_add)

        def replace_after_a_v1_append(src, dst):
            producer.start()
            producer.join(0.5)  # the producer gets its turn now if nothing holds the lock
            return real_replace(src, dst)
        with mock.patch.object(library.os, "replace", replace_after_a_v1_append):
            library.export_jobs(self.store, queue)
        producer.join(5)
        self.assertIn("v1late", [json.loads(line)["id"] for line in queue.read_text().splitlines()])

    def test_the_jobs_go_back_to_the_jsonl_queue_in_v1_order(self) -> None:
        queue = self.temp / "lease-queue.jsonl"
        rows = [{"id": "old1", "at": "2026-10-24T10:00:00Z", "kind": "gate", "who": "s601", "cmd": "a",
                 "state": "done exit=0"},
                {"id": "old2", "at": "2026-10-24T11:00:00Z", "kind": "lote", "who": "s591", "cmd": "b",
                 "state": "queued"}]
        queue.write_text("".join(json.dumps(r) + "\n" for r in rows))
        importers.import_jobs(self.store, queue)
        done = library.jobs_add(self.store, kind="gate", who="s602", cmd="c")
        library.jobs_start(self.store, done["id"])
        library.jobs_finish(self.store, done["id"], 3)
        urgent = library.jobs_add(self.store, kind="gate", who="s605", cmd="d", priority=1)
        later = library.jobs_add(self.store, kind="janela", who="s619", cmd="e")
        with queue.open("a") as out:  # added by the v1 script after the swap back, before the second export
            out.write(json.dumps({"id": "v1new", "at": "2026-10-26T09:00:00Z", "kind": "lote", "who": "s620",
                                  "cmd": "f", "state": "queued"}) + "\n")
        running = library.jobs_add(self.store, kind="lote", who="s700", cmd="g")
        library.jobs_start(self.store, running["id"])
        with self.assertRaisesRegex(library.CorreioError, "is running"):
            library.export_jobs(self.store, queue)
        library.jobs_finish(self.store, running["id"], 0)
        result = library.export_jobs(self.store, queue)
        out = [json.loads(line) for line in queue.read_text().splitlines()]
        self.assertEqual(result["rows"], len(out))
        self.assertEqual(len({r["id"] for r in out}), len(out))
        states = {r["id"]: r["state"] for r in out}
        self.assertEqual((states["old1"], states[done["id"]], states[running["id"]]),
                         ("done exit=0", "done exit=3", "done exit=0"))
        # The v1 runner serves the first "queued" line of the file: the v2 order, then what v1 added.
        self.assertEqual([r["id"] for r in out if r["state"] == "queued"], [urgent["id"], "old2", later["id"], "v1new"])
        self.assertEqual(library.export_jobs(self.store, queue)["rows"], len(out))  # idempotent

    def test_the_cli_exports_both(self) -> None:
        out = self.temp / "v1-cli"
        result = json.loads(self.cli("export-v1", "--space", "orq", "--root", str(out)).stdout)
        self.assertEqual((result["messages"], result["errors"]), (4, []))
        self.assertEqual(len(self.v1_pending(out, "orquestrador")), 3)
        library.jobs_add(self.store, kind="gate", who="s1", cmd="x")
        jobs = json.loads(self.cli("export-jobs", "--file", str(self.temp / "q.jsonl")).stdout)
        self.assertEqual(jobs["rows"], 1)
