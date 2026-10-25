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
