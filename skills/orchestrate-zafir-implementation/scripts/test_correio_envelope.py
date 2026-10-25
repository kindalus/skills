"""Envelope: strict YAML subset, canonical bytes, stable sha256."""
from __future__ import annotations

import unittest

from correio import envelope as env

HEADER = {"correio": 2, "id": "3e47dbe8-af70-4acd-8671-41ff97accd29", "space": "s617", "protocol": "swarm",
          "version": "3.0.0", "thread": "S617/T03", "type": "BLOCKED", "from": "s617-principal",
          "from_generation": 1, "to": "orquestrador", "in_reply_to": None,
          "sent_at": "2026-10-25T14:30:00.123456Z", "subject": "T03: censo do guard de substrato abaixo do piso"}
FIELDS = {"taskId": "S617-T03", "assignmentId": "61c4fde4-878c-4fd6-a2d1-9643226e51cf", "revision": 1,
          "candidateSha": "f6b5c63d402fd18471c25d724f25f813da748548", "close": True, "note": None,
          "count": "12", "word": "null", "neg": -3}
ATTACHMENTS = [{"path": "/r/reports/s617-principal/T03 BLOCKED.md", "sha256": "a" * 64, "bytes": 12}]


class EnvelopeTest(unittest.TestCase):
    def test_round_trip_is_canonical_and_its_sha_is_stable(self) -> None:
        data = env.emit(HEADER, FIELDS, ATTACHMENTS, "Corpo em **Markdown**.\n\nÁcentos — e ---\n")
        parsed = env.parse(data)
        self.assertEqual({k: parsed[k] for k in HEADER}, HEADER)
        self.assertEqual(parsed["fields"], FIELDS)
        self.assertEqual(parsed["attachments"], ATTACHMENTS)
        again = env.emit({k: parsed[k] for k in HEADER}, parsed["fields"], parsed["attachments"], parsed["body"])
        self.assertEqual(again, data)
        self.assertEqual(env.sha256(again), env.sha256(data))
        text = data.decode()
        self.assertTrue(text.startswith("---\ncorreio: 2\nid: 3e47dbe8"))
        self.assertIn('subject: "T03: censo', text)  # ": " forces quotes
        self.assertIn("thread: S617/T03\n", text)  # a safe plain scalar stays plain
        self.assertIn('  count: "12"\n', text)  # a string that looks like an integer is quoted
        self.assertIn('  word: "null"\n', text)
        self.assertIn("  neg: -3\n", text)
        self.assertLess(text.index("  assignmentId"), text.index("  taskId"))  # fields in sorted order

    def test_empty_maps_and_bodies(self) -> None:
        data = env.emit(HEADER, {}, [], "")
        self.assertIn(b"fields: {}\nattachments: []\n---\n", data)
        self.assertTrue(data.endswith(b"---\n"))
        self.assertEqual(env.parse(data)["body"], "")
        self.assertTrue(env.emit(HEADER, {}, [], "no newline").endswith(b"no newline\n"))

    def test_the_parser_refuses_everything_outside_the_subset(self) -> None:
        good = env.emit(HEADER, {"taskId": "T1"}, [], "body\n").decode()
        mutations = {
            "reordered": good.replace("space: s617\nprotocol: swarm\n", "protocol: swarm\nspace: s617\n"),
            "extra key": good.replace("fields:", "extra: 1\nfields:"),
            "single quotes": good.replace("space: s617", "space: 's617'"),
            "needless quotes": good.replace("space: s617", 'space: "s617"'),
            "flow map": good.replace('fields:\n  taskId: T1', "fields: {taskId: T1}"),
            "comment": good.replace("space: s617", "space: s617 # c"),
            "anchor": good.replace("space: s617", "space: &a s617"),
            "tab indent": good.replace("  taskId", "\ttaskId"),
            "nested map": good.replace("  taskId: T1", "  taskId:\n    deep: 1"),
            "list in fields": good.replace("  taskId: T1", "  taskId:\n  - 1"),
            "crlf": good.replace("\n", "\r\n", 3),
            "duplicate field": good.replace("  taskId: T1", "  taskId: T1\n  taskId: T2"),
            "missing attachments": good.replace("attachments: []\n", ""),
            "bad bool": good.replace("from_generation: 1", "from_generation: yes"),
            "leading zero": good.replace("from_generation: 1", "from_generation: 01"),
            "multiline string": good.replace('subject: "T03', 'subject: |\n  T03'),
            "no close": good.replace("---\nbody", "body"),
            "bad uuid": good.replace("id: 3e47dbe8-af70", "id: 3E47DBE8-af70"),
            "version 1": good.replace("correio: 2", "correio: 1"),
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(env.EnvelopeError):
                    env.parse(text.encode())
        with self.assertRaises(env.EnvelopeError):
            env.parse(b"\xff\xfe")

    def test_emit_refuses_non_scalars_bad_names_and_oversize(self) -> None:
        for fields in ({"x": {"a": 1}}, {"x": [1]}, {"x": 1.5}, {"bad-key": 1}, {"1x": 1}):
            with self.subTest(fields=fields):
                with self.assertRaises(env.EnvelopeError):
                    env.emit(HEADER, fields, [], "")
        with self.assertRaises(env.EnvelopeError):
            env.emit(HEADER, {}, [{"path": "relative", "sha256": "a" * 64, "bytes": 1}], "")
        with self.assertRaises(env.EnvelopeError):
            env.emit(HEADER, {}, [], "x" * env.MAX_ENVELOPE_BYTES)
        with self.assertRaises(env.EnvelopeError):
            env.parse(env.emit({**HEADER, "subject": "two\nlines"}, {}, [], ""))


if __name__ == "__main__":
    unittest.main()
