#!/usr/bin/env python3
"""Automation 3.0.0: the 2.7.0 event rules ported onto correio (protocol swarm/3.0.0), plus its projections.

Reuses the fixtures of test_swarmctl.py (temporary repository, fake Herdr on PATH) with a 3.0.0 contract and a
temporary correio database.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest
import uuid

import test_swarmctl as legacy
from test_swarmctl import HERE, swarmbootstrap, swarmcore, swarmctl

library, store_module = swarmcore.correio_modules()
CorreioError = store_module.CorreioError


class SwarmV3Test(unittest.TestCase):
    setUp_legacy = legacy.SwarmTest.setUp
    tearDown = legacy.SwarmTest.tearDown
    init = legacy.SwarmTest.init
    write_contract = legacy.SwarmTest.write_contract
    legacy_coders = legacy.SwarmTest.legacy_coders
    pre_240_creation = legacy.SwarmTest.pre_240_creation
    legacy_init = legacy.SwarmTest.legacy_init
    grant = legacy.SwarmTest.grant
    principal_pane = legacy.SwarmTest.principal_pane
    quit_agent = legacy.SwarmTest.quit_agent
    log_entries = legacy.SwarmTest.log_entries
    FALLBACK = legacy.SwarmTest.FALLBACK

    def setUp(self) -> None:
        self.setUp_legacy()
        self.contract.pop("automation")  # 3.0.0 is the default for a new contract
        self.write_contract()
        os.environ.pop("HERDR_PANE_ID", None)
        os.environ["CORREIO_DB"] = str(self.temp / "state" / "correio.db")

    # -- helpers ------------------------------------------------------------------------------------------------
    def store(self):
        return store_module.Store(os.environ["CORREIO_DB"])

    def send(self, root, launch, **kwargs) -> str:
        kwargs.setdefault("generation", 1)
        kwargs.setdefault("payload", {})
        return swarmcore.events_for(root, launch).send(**kwargs)

    def ev(self, root, launch, sender, recipient, kind, payload=None, fields=None, generation=1) -> str:
        return self.send(root, launch, sender=sender, recipient=recipient, event_type=kind, payload=payload or {},
                         fields=fields or {}, generation=generation)

    def pending(self, root, launch, recipient=None) -> dict:
        return swarmcore.events_for(root, launch).pending(recipient)

    def receipt(self, root, launch, ref, recipient, accepted=True, disposition="ok") -> dict:
        return swarmcore.events_for(root, launch).receipt(ref, recipient, accepted, disposition)

    def authorize_children(self):
        responsible = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                                     no_supervisor=True)
        root, launch = swarmctl.load_launch(self.run_dir)
        authorization = self.ev(root, launch, "orchestrator", "t123-principal", "RESUME",
                                {"bootstrapChildrenAuthorized": True})
        return responsible, authorization

    def bootstrap_team(self):
        responsible, authorization = self.authorize_children()
        with self.principal_pane(responsible["principal"]["paneId"]):
            swarmctl.bootstrap_principal(self.run_dir, authorization)
        root, launch = swarmctl.load_launch(self.run_dir)
        return responsible, root, launch

    def space_state(self) -> dict:
        store = self.store()
        try:
            return store.space_state("t123")
        finally:
            store.close()

    # -- run creation ------------------------------------------------------------------------------------------
    def test_init_creates_the_space_and_members_and_copies_no_runtime(self) -> None:
        first = swarmctl.init_run(self.contract_path, self.run_dir)
        second = swarmctl.init_run(self.contract_path, self.run_dir)
        self.assertEqual((first["launchSha256"], first["space"]), (second["launchSha256"], "t123"))
        marker = json.loads((self.run_dir / "automation.json").read_text())
        self.assertEqual((marker["automationVersion"], marker["correio"]["space"]), ("3.0.0", "t123"))
        for absent in ("runtime", "inbox", "receipts", "supervisor.json", "state.json"):
            self.assertFalse((self.run_dir / absent).exists(), absent)
        self.assertEqual(os.stat(self.run_dir).st_mode & 0o777, 0o700)
        store = self.store()
        space = store.space("t123")
        self.assertEqual((space["protocol"], space["version"], space["legacy"], space["state"]),
                         ("swarm", "3.0.0", False, "starting"))
        members = store.members("t123")
        self.assertEqual({n: m["role"] for n, m in members.items()},
                         {"orchestrator": "responsible", "t123-principal": "principal", "t123-reviewer": "reviewer"})
        self.assertEqual(members["orchestrator"]["pane_id"], "p0")
        self.assertEqual(members["t123-reviewer"]["configuration"]["value"], "claude claude-opus-5-5 high")
        self.assertEqual(swarmctl.load_launch(self.run_dir)[1]["runId"], self.run_id)

    def test_space_protocol_and_version_are_pinned(self) -> None:
        self.init()
        store = self.store()
        with self.assertRaises(Exception):
            store.x("UPDATE spaces SET version='9.9.9' WHERE id='t123'")
        self.assertEqual(store.space("t123")["version"], "3.0.0")

    # -- events (ported from test_swarmctl) ---------------------------------------------------------------------
    def test_event_pending_receipt_and_route(self) -> None:
        root, launch = self.init()
        event = self.ev(root, launch, "orchestrator", "t123-principal", "BOOT", {"safe": True})
        self.assertEqual(self.pending(root, launch, "t123-principal")["count"], 1)
        self.assertFalse(self.receipt(root, launch, event, "t123-principal", True, "accepted")["idempotent"])
        self.assertTrue(self.receipt(root, launch, event, "t123-principal", True, "accepted")["idempotent"])
        self.assertEqual(self.pending(root, launch, "t123-principal")["count"], 0)
        with self.assertRaisesRegex(swarmctl.SwarmError, "conflicting receipt"):
            self.receipt(root, launch, event, "t123-principal", False, "rejected")
        with self.assertRaisesRegex(swarmctl.SwarmError, "not the message recipient"):
            self.receipt(root, launch, event, "t123-reviewer", True, "not mine")
        with self.assertRaises(swarmctl.SwarmError):
            self.ev(root, launch, "t123-coder-a", "orchestrator", "APPROVED")
        with self.assertRaises(swarmctl.SwarmError):
            self.ev(root, launch, "t123-principal", "t123-coder-a", "TASK_ASSIGN")

    def test_routes_follow_the_task_review_and_slice_flow(self) -> None:
        root, launch = self.legacy_init()  # the coder routes of contracts from before 2.4.0
        bound = {"taskId": "T01", "assignmentId": "a1", "revision": 1}
        candidate = {**bound, "candidateSha": "b" * 40}
        sha = {"candidateSha": "c" * 40}
        allowed = [
            ("t123-principal", "t123-coder-a", "TASK_ASSIGN", self.grant(root), bound),
            ("t123-principal", "t123-principal", "TASK_ASSIGN", self.grant(root, "t02-r1"), bound),
            ("t123-coder-a", "t123-reviewer", "REVIEW_REQUEST", {}, candidate),
            ("t123-coder-a", "t123-principal", "REVIEW_REQUEST", {"copy": True}, candidate),
            ("t123-principal", "t123-reviewer", "REVIEW_REQUEST", {}, candidate),
            ("t123-principal", "t123-reviewer", "REVIEW_REQUEST", {"scope": "slice"},
             {"taskId": "T123", "assignmentId": "slice", "revision": 1, "candidateSha": "c" * 40}),
            ("orchestrator", "t123-reviewer", "REVIEW_REQUEST", {"fallback": True}, candidate),
            ("t123-reviewer", "t123-coder-a", "CHANGES_REQUESTED", {}, candidate),
            ("t123-reviewer", "t123-principal", "CHANGES_REQUESTED", {}, candidate),
            ("t123-reviewer", "t123-coder-b", "APPROVED", {}, candidate),
            ("t123-reviewer", "t123-principal", "APPROVED", {}, candidate),
            ("t123-reviewer", "orchestrator", "APPROVED", {}, candidate),
            ("t123-principal", "t123-coder-a", "TASK_INTEGRATED", {}, candidate),
            ("t123-principal", "t123-principal", "TASK_INTEGRATED", {}, candidate),  # new in 3.0.0
            ("t123-principal", "orchestrator", "TASK_PHASE", {"phase": "red"}, bound),  # new in 3.0.0
            ("t123-principal", "orchestrator", "LEASE_REQUEST", {"kind": "full-gate"}, sha),
            ("t123-principal", "orchestrator", "LEASE_RELEASE", {"exit": 0}, sha),
            ("t123-principal", "orchestrator", "SLICE_READY", {}, sha),
            ("orchestrator", "t123-principal", "MODEL_REPLACE",
             {"role": "coders", "configuration": "pi ollama/coder high", "incidentId": "i1"}, {}),
            ("t123-coder-a", "t123-principal", "BLOCKED", {}, {}),
            ("t123-reviewer", "t123-principal", "BLOCKED", {}, {}),
            ("t123-principal", "orchestrator", "BLOCKED", {}, {}),
            ("t123-principal", "t123-reviewer", "PAUSE", {}, {}),
            ("orchestrator", "t123-principal", "RESUME", {"lease": "full-gate"}, {}),
            ("orchestrator", "t123-principal", "SLICE_ACCEPTED", {}, sha),
        ]
        for sender, recipient, kind, payload, fields in allowed:
            with self.subTest(route=(sender, recipient, kind)):
                self.assertTrue(self.ev(root, launch, sender, recipient, kind, payload, fields))
        rejected = [
            ("t123-reviewer", "t123-principal", "PROGRESS", {}, {}),
            ("t123-coder-a", "t123-coder-b", "TASK_ASSIGN", self.grant(root), bound),
            ("orchestrator", "t123-coder-a", "TASK_ASSIGN", self.grant(root), bound),
            ("t123-principal", "t123-reviewer", "TASK_ASSIGN", self.grant(root), bound),
            ("t123-reviewer", "t123-reviewer", "REVIEW_REQUEST", {}, candidate),
            ("t123-coder-a", "orchestrator", "REVIEW_REQUEST", {}, candidate),
            ("t123-coder-a", "t123-principal", "APPROVED", {}, candidate),
            ("t123-principal", "t123-coder-a", "APPROVED", {}, candidate),
            ("t123-coder-a", "orchestrator", "LEASE_REQUEST", {}, sha),
            ("t123-principal", "orchestrator", "LEASE_REQUEST", {}, {}),
            ("t123-coder-a", "orchestrator", "SLICE_READY", {}, sha),
            ("orchestrator", "t123-coder-a", "RESUME", {}, {}),
            ("t123-coder-a", "orchestrator", "BLOCKED", {}, {}),
            ("orchestrator", "t123-principal", "MODEL_REPLACE", {}, {}),
            ("orchestrator", "t123-principal", "MODEL_REPLACE",
             {"role": "coders", "configuration": "pi ollama/coder high"}, {}),
            ("t123-principal", "orchestrator", "TASK_PHASE", {"phase": "blue"}, bound),
            ("t123-principal", "orchestrator", "TASK_PHASE", {"phase": "red"}, {}),
            ("t123-reviewer", "orchestrator", "TASK_PHASE", {"phase": "red"}, bound),
        ]
        for sender, recipient, kind, payload, fields in rejected:
            with self.subTest(route=(sender, recipient, kind)):
                with self.assertRaises(swarmctl.SwarmError):
                    self.ev(root, launch, sender, recipient, kind, payload, fields)

    def test_bindings_are_validated_like_2_7(self) -> None:
        root, launch = self.init()
        bad = [{"taskId": "T 01", "assignmentId": "a1", "revision": 1, "candidateSha": "b" * 40},
               {"taskId": "T01", "assignmentId": "a1", "revision": 0, "candidateSha": "b" * 40},
               {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "B" * 40},
               {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "b" * 39},
               {"taskId": "T01", "assignmentId": "a1", "revision": 1}]
        for fields in bad:
            with self.subTest(fields=fields):
                with self.assertRaises(swarmctl.SwarmError):
                    self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {}, fields)
        with self.assertRaisesRegex(swarmctl.SwarmError, "positive"):
            self.ev(root, launch, "orchestrator", "t123-principal", "BOOT", generation=0)
        with self.assertRaisesRegex(swarmctl.SwarmError, "runId mismatch"):
            self.ev(root, launch, "orchestrator", "t123-principal", "BOOT", fields={"runId": str(uuid.uuid4())})
        with self.assertRaisesRegex(swarmctl.SwarmError, "canonical lowercase UUID"):
            self.send(root, launch, sender="orchestrator", recipient="t123-principal", event_type="BOOT",
                      event_id="NOT-A-UUID")

    def test_task_assignment_requires_an_unchanged_grant_file_in_the_run(self) -> None:
        root, launch = self.init()
        fields = {"taskId": "T01", "assignmentId": "a1", "revision": 1}
        grant = self.grant(root)
        outside = self.temp / "grant.json"
        outside.write_text(pathlib.Path(grant["grantPath"]).read_text())
        invalid = [{}, {**grant, "grantSha256": "0" * 64}, {**grant, "grantPath": "relative.json"},
                   {**grant, "grantPath": str(outside)}]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(swarmctl.SwarmError):
                    self.ev(root, launch, "t123-principal", "t123-principal", "TASK_ASSIGN", payload, fields)
        event = self.ev(root, launch, "t123-principal", "t123-principal", "TASK_ASSIGN", grant, fields)
        pathlib.Path(grant["grantPath"]).write_text("{}")  # grant edited after dispatch
        pending = self.pending(root, launch, "t123-principal")
        self.assertEqual(pending["count"], 0)
        self.assertEqual([item["id"] for item in pending["invalid"]], [event])
        with self.assertRaisesRegex(swarmctl.SwarmError, "grant file is missing or its SHA-256 differs"):
            self.receipt(root, launch, event, "t123-principal", True, "accept")
        self.assertFalse(self.receipt(root, launch, event, "t123-principal", False, "grant changed")["accepted"])

    def test_stale_sender_generation_is_rejected(self) -> None:
        root, launch = self.init()
        store = self.store()
        library.bump_generation(store, "t123", "t123-principal")
        fields = {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "a" * 40}
        with self.assertRaisesRegex(swarmctl.SwarmError, "generation is stale"):
            self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {}, fields)
        self.assertTrue(self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {}, fields,
                                generation=2))

    def test_an_event_of_an_older_generation_can_be_rejected_but_not_accepted(self) -> None:
        root, launch = self.init()
        fields = {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "a" * 40}
        stale = self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {}, fields)
        library.bump_generation(self.store(), "t123", "t123-principal")
        result = self.pending(root, launch, "t123-reviewer")
        self.assertEqual(result["count"], 0)
        self.assertEqual([(i["id"], i["error"]) for i in result["invalid"]],
                         [(stale, "event sender generation is stale")])
        with self.assertRaisesRegex(swarmctl.SwarmError, "generation is stale.*--reject"):
            self.receipt(root, launch, stale, "t123-reviewer", True, "reviewing")
        store = self.store()
        self.assertIsNone(store.task("t123", "T01"))
        self.assertIsNone(store.receipt(stale))
        self.assertFalse(self.receipt(root, launch, stale, "t123-reviewer", False, "stale generation")["accepted"])
        self.assertIsNone(self.store().task("t123", "T01"))

    def test_pending_events_are_first_in_first_out(self) -> None:
        root, launch = self.init()
        candidate = {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "b" * 40}
        sent = [self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {},
                        {**candidate, "taskId": task}) for task in ("T03", "T01", "T02")]
        self.assertEqual([item["id"] for item in self.pending(root, launch, "t123-reviewer")["pending"]], sent)

    def test_structured_payload_goes_to_the_body(self) -> None:
        root, launch = self.init()
        event = self.ev(root, launch, "t123-principal", "orchestrator", "BLOCKED",
                        {"reason": "decision", "options": ["a", "b"], "n": 2})
        store = self.store()
        message = store.message(event)
        self.assertEqual((message["fields"]["reason"], message["fields"]["n"]), ("decision", 2))
        self.assertNotIn("options", message["fields"])
        self.assertIn('"options": [', message["body"])
        self.assertEqual(message["thread"], "T123")

    # -- MODEL_REPLACE and the reviewer quota fallback (ported) ----------------------------------------------------
    def openai_team(self):
        self.contract["models"].update(principal="codex gpt-6.1-sol high")
        self.write_contract()
        return self.init()

    def model_error(self, root, launch, *, role="reviewer", classification="quota-exhausted",
                    sender="t123-principal", recipient="orchestrator") -> str:
        return self.ev(root, launch, sender, recipient, "MODEL_ERROR", {"role": role, "classification": classification})

    def replace_reviewer(self, root, launch, configuration, **marker) -> str:
        payload = {"role": "reviewer", "configuration": configuration,
                   "incidentId": marker.get("reviewerFallback", "i1"), **marker}
        return self.ev(root, launch, "orchestrator", "t123-principal", "MODEL_REPLACE", payload)

    def test_reviewer_quota_fallback_accepts_the_exact_pair_with_its_marker(self) -> None:
        root, launch = self.openai_team()
        for sender, recipient in (("t123-principal", "orchestrator"), ("t123-reviewer", "t123-principal")):
            with self.subTest(observer=sender):
                incident = self.model_error(root, launch, sender=sender, recipient=recipient)
                event = self.replace_reviewer(root, launch, self.FALLBACK, reviewerFallback=incident)
                pending = self.pending(root, launch, "t123-principal")
                self.assertIn(event, [item["id"] for item in pending["pending"]])
                self.assertEqual(pending["invalid"], [])

    def test_reviewer_quota_fallback_is_rejected_without_its_marker(self) -> None:
        root, launch = self.openai_team()
        self.model_error(root, launch)
        with self.assertRaisesRegex(swarmctl.SwarmError, "different model family"):
            self.replace_reviewer(root, launch, self.FALLBACK)

    def test_reviewer_quota_fallback_marker_admits_no_other_model_or_incident(self) -> None:
        root, launch = self.openai_team()
        incident = self.model_error(root, launch)
        for configuration in ("pi openai-codex/gpt-6.1-sol high", "codex gpt-6.1-sol medium",
                              "codex gpt-6-astra high", "codex gpt-6.1-sol-mini high"):
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(swarmctl.SwarmError, "valid only for a reviewer replacement"):
                    self.replace_reviewer(root, launch, configuration, reviewerFallback=incident)
        with self.assertRaisesRegex(swarmctl.SwarmError, "role must be one of: principal, reviewer"):
            self.ev(root, launch, "orchestrator", "t123-principal", "MODEL_REPLACE",
                    {"role": "coders", "configuration": self.FALLBACK, "incidentId": incident,
                     "reviewerFallback": incident})
        not_quota = [self.model_error(root, launch, classification="rate-limited"),
                     self.model_error(root, launch, role="coders"), str(uuid.uuid4()), "../x"]
        for marker in not_quota:
            with self.subTest(marker=marker):
                with self.assertRaises(swarmctl.SwarmError):
                    self.replace_reviewer(root, launch, self.FALLBACK, reviewerFallback=marker)
        with self.assertRaisesRegex(swarmctl.SwarmError, "must equal the incidentId"):
            self.ev(root, launch, "orchestrator", "t123-principal", "MODEL_REPLACE",
                    {"role": "reviewer", "configuration": self.FALLBACK, "incidentId": "other",
                     "reviewerFallback": incident})

    def test_same_family_reviewer_stays_rejected_outside_the_quota_fallback(self) -> None:
        root, launch = self.openai_team()
        for configuration in ("pi openai-codex/gpt-6.1-sol high", "pi openrouter/gpt-6.1-sol high",
                              "codex gpt-6-astra medium"):
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(swarmctl.SwarmError, "different model family"):
                    self.replace_reviewer(root, launch, configuration)
        self.assertTrue(self.replace_reviewer(root, launch, "claude claude-opus-5-5 high"))

    def test_model_replace_revises_the_member_configuration_on_acceptance(self) -> None:
        root, launch = self.openai_team()
        incident = self.model_error(root, launch)
        event = self.replace_reviewer(root, launch, self.FALLBACK, reviewerFallback=incident)
        store = self.store()
        self.assertEqual(store.member("t123", "t123-reviewer")["configuration"]["revision"], 1)
        self.receipt(root, launch, event, "t123-principal", True, "replacing the reviewer")
        configuration = self.store().member("t123", "t123-reviewer")["configuration"]
        self.assertEqual((configuration["value"], configuration["revision"]), (self.FALLBACK, 2))
        self.assertEqual(configuration["reviewerFallback"]["incidentId"], incident)
        self.assertEqual(configuration["history"][0]["value"], "claude claude-opus-5-5 high")

    # -- projections ---------------------------------------------------------------------------------------------
    def test_a_task_runs_its_whole_cycle_in_the_projection(self) -> None:
        root, launch = self.init()
        bound = {"taskId": "T123-T01", "assignmentId": "a1", "revision": 1}
        candidate = {**bound, "candidateSha": "d" * 40}

        def task():
            store = self.store()
            try:
                return store.task("t123", "T123-T01")
            finally:
                store.close()
        assign = self.ev(root, launch, "t123-principal", "t123-principal", "TASK_ASSIGN", self.grant(root), bound)
        self.assertIsNone(task())  # projected only on the accepted receipt
        self.receipt(root, launch, assign, "t123-principal", True, "starting T01")
        self.assertEqual((task()["state"], task()["owner"]), ("assigned", "t123-principal"))
        self.ev(root, launch, "t123-principal", "orchestrator", "TASK_PHASE", {"phase": "red"}, bound)
        self.assertEqual(task()["state"], "red")  # INFO: projected on send, wakes nobody
        self.ev(root, launch, "t123-principal", "orchestrator", "TASK_PHASE", {"phase": "green"}, bound)
        self.assertEqual(task()["state"], "green")
        review = self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {}, candidate)
        self.receipt(root, launch, review, "t123-reviewer", True, "reviewing")
        self.assertEqual((task()["state"], task()["candidate_sha"]), ("in-review", "d" * 40))
        changes = self.ev(root, launch, "t123-reviewer", "t123-principal", "CHANGES_REQUESTED", {}, candidate)
        self.receipt(root, launch, changes, "t123-principal", True, "fixing")
        self.assertEqual(task()["state"], "changes-requested")
        second = {**candidate, "revision": 2, "candidateSha": "e" * 40}
        review = self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {}, second)
        self.receipt(root, launch, review, "t123-reviewer", True, "reviewing r2")
        approved = self.ev(root, launch, "t123-reviewer", "t123-principal", "APPROVED", {}, second)
        self.receipt(root, launch, approved, "t123-principal", True, "integrating")
        self.assertEqual((task()["state"], task()["revision"]), ("approved", 2))
        result = library.send(self.store(), space="t123", sender="t123-principal", to="t123-principal",
                              type="TASK_INTEGRATED", fields={**second}, generation=1, self_receipt="merged")
        self.assertTrue(result["receipt"]["accepted"])
        self.assertEqual(task()["state"], "integrated")
        rejected = self.ev(root, launch, "t123-principal", "t123-reviewer", "REVIEW_REQUEST", {},
                           {**second, "revision": 3})
        self.receipt(root, launch, rejected, "t123-reviewer", False, "superseded")
        self.assertEqual(task()["state"], "integrated")  # a rejected event projects nothing

    def test_the_space_closes_on_slice_accepted(self) -> None:
        root, launch = self.init()
        sha = {"candidateSha": "c" * 40}
        for kind, recipient, state in (("SWARM_READY", "orchestrator", "running"),
                                       ("LEASE_REQUEST", "orchestrator", "lease-requested"),
                                       ("SLICE_READY", "orchestrator", "ready")):
            sender = "t123-principal"
            event = self.ev(root, launch, sender, recipient, kind, {}, sha if kind != "SWARM_READY" else {})
            self.receipt(root, launch, event, recipient, True, kind)
            self.assertEqual(self.space_state()["state"], state)
        accepted = self.ev(root, launch, "orchestrator", "t123-principal", "SLICE_ACCEPTED", {}, sha)
        self.assertIsNone(self.store().space("t123")["closed_at"])
        self.receipt(root, launch, accepted, "t123-principal", True, "accepted")
        space = self.store().space("t123")
        self.assertEqual((space["state"], self.space_state()["acceptedSha"]), ("accepted", "c" * 40))
        self.assertIsNotNone(space["closed_at"])
        with self.assertRaisesRegex(swarmctl.SwarmError, "closed"):
            self.ev(root, launch, "t123-principal", "orchestrator", "BLOCKED")

    def test_cancel_closes_the_space_and_blocked_resume_mark_the_member(self) -> None:
        root, launch = self.init()
        blocked = self.ev(root, launch, "t123-principal", "orchestrator", "BLOCKED", {"reason": "decision"})
        self.receipt(root, launch, blocked, "orchestrator", True, "deciding")
        self.assertTrue(self.store().member("t123", "t123-principal")["blocked"])
        resume = self.ev(root, launch, "orchestrator", "t123-principal", "RESUME", {"decision": "go"})
        self.receipt(root, launch, resume, "t123-principal", True, "going")
        self.assertFalse(self.store().member("t123", "t123-principal")["blocked"])
        cancel = self.ev(root, launch, "orchestrator", "t123-principal", "CANCEL", {"reason": "owner"})
        self.receipt(root, launch, cancel, "t123-principal", True, "stopping")
        space = self.store().space("t123")
        self.assertEqual(space["state"], "cancelled")
        self.assertIsNotNone(space["closed_at"])

    def test_a_late_receipt_never_reopens_a_terminal_space(self) -> None:
        root, launch = self.init()
        ready = self.ev(root, launch, "t123-principal", "orchestrator", "SWARM_READY")
        lease = self.ev(root, launch, "t123-principal", "orchestrator", "LEASE_REQUEST", {}, {"candidateSha": "c" * 40})
        cancel = self.ev(root, launch, "orchestrator", "t123-principal", "CANCEL", {"reason": "owner"})
        self.receipt(root, launch, cancel, "t123-principal", True, "stopping")
        self.receipt(root, launch, ready, "orchestrator", True, "late")
        self.receipt(root, launch, lease, "orchestrator", True, "late")
        space = self.store().space("t123")
        self.assertEqual((space["state"], self.space_state()["state"]), ("cancelled", "cancelled"))
        self.assertIsNotNone(space["closed_at"])

    # -- bootstrap (ported) ----------------------------------------------------------------------------------------
    def test_responsible_bootstrap_dry_run_has_no_side_effects(self) -> None:
        result = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=True, no_supervisor=False)
        self.assertTrue(result["dryRun"])
        self.assertFalse(self.run_dir.exists())
        self.assertIsNone(self.store().space("t123"))

    def test_responsible_bootstrap_is_idempotent_starts_only_the_principal_and_no_swarmd(self) -> None:
        first = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=False)
        self.assertIsNone(first["supervisor"])
        journal_path = self.run_dir / "bootstrap.json"
        journal = json.loads(journal_path.read_text())
        self.assertEqual(journal["automationVersion"], "3.0.0")
        journal["responsible"].pop("bootEventId")  # crash-window simulation
        journal_path.write_text(json.dumps(journal))
        second = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=False)
        self.assertEqual(first["principal"]["bootEventId"], second["principal"]["bootEventId"])
        fake = json.loads(self.fake_state.read_text())
        self.assertEqual(set(fake["agents"]), {"orchestrator", "t123-principal"})
        store = self.store()
        boots = store.find_messages("t123", type="BOOT")
        self.assertEqual(len(boots), 1)
        self.assertEqual(boots[0]["fields"]["ponytailPath"], self.contract["ponytailPath"])
        principal = store.member("t123", "t123-principal")
        self.assertEqual(principal["pane_id"], first["principal"]["paneId"])
        prompt = self.log_entries("prompt")[-1]["message"]
        self.assertIn(f"correio.py show {boots[0]['id']}", prompt)
        self.assertFalse((self.run_dir / "supervision" / "process.json").exists())

    def test_principal_bootstrap_requires_explicit_authority(self) -> None:
        responsible = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                                     no_supervisor=True)
        root, launch = swarmctl.load_launch(self.run_dir)
        authorization = self.ev(root, launch, "orchestrator", "t123-principal", "RESUME",
                                {"decision": "unrelated-resume"})
        with self.principal_pane(responsible["principal"]["paneId"]):
            with self.assertRaisesRegex(swarmctl.SwarmError, "does not explicitly authorize"):
                swarmctl.bootstrap_principal(self.run_dir, authorization)

    def test_principal_alone_starts_only_the_reviewer_and_records_its_pane(self) -> None:
        responsible, authorization = self.authorize_children()
        with self.principal_pane(responsible["principal"]["paneId"]):
            result = swarmctl.bootstrap_principal(self.run_dir, authorization)
            again = swarmctl.bootstrap_principal(self.run_dir, authorization)  # idempotent
        self.assertEqual(set(result["children"]), {"t123-reviewer"})
        self.assertEqual(result["children"]["t123-reviewer"]["bootEventId"],
                         again["children"]["t123-reviewer"]["bootEventId"])
        fake = json.loads(self.fake_state.read_text())
        self.assertEqual(set(fake["agents"]), {"orchestrator", "t123-principal", "t123-reviewer"})
        store = self.store()
        self.assertTrue(store.receipt(authorization)["accepted"])
        reviewer = store.member("t123", "t123-reviewer")
        self.assertEqual(reviewer["pane_id"], fake["agents"]["t123-reviewer"]["pane_id"])
        boot = store.find_messages("t123", type="BOOT", to_agent="t123-reviewer")
        self.assertEqual([b["fields"]["coordinator"] for b in boot], ["t123-principal"])
        ledger = json.loads((self.run_dir / "resources.json").read_text())
        self.assertEqual(set(ledger["agents"]), {"t123-principal", "t123-reviewer"})
        self.assertFalse((self.run_dir / "state.json").exists())

    def test_principal_restart_bumps_the_member_generation_in_the_same_pane(self) -> None:
        responsible, authorization = self.authorize_children()
        root, launch = swarmctl.load_launch(self.run_dir)
        pane = responsible["principal"]["paneId"]
        with self.principal_pane(pane):
            swarmctl.bootstrap_principal(self.run_dir, authorization)
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.rotate_principal(self.run_dir, "clean restart between phases")  # still live
        self.quit_agent("t123-principal")
        result = swarmctl.rotate_principal(self.run_dir, "clean restart between phases")
        self.assertEqual((result["generation"], result["paneId"]), (2, pane))
        store = self.store()
        self.assertEqual(store.member("t123", "t123-principal")["generation"], 2)
        boot = store.message(result["bootEventId"])
        self.assertEqual((boot["type"], boot["fields"]["generation"], boot["fields"]["rotationReason"]),
                         ("BOOT", 2, "clean restart between phases"))
        with self.assertRaisesRegex(swarmctl.SwarmError, "stale"):
            self.ev(root, launch, "t123-principal", "orchestrator", "AGENT_READY")
        self.assertTrue(self.ev(root, launch, "t123-principal", "orchestrator", "AGENT_READY", generation=2))
        self.quit_agent("t123-principal")
        cli = subprocess.run([sys.executable, str(HERE / "swarmctl.py"), "bootstrap", "restart-principal",
                              "--run-dir", str(root), "--reason", "phase 2"], env=os.environ.copy(),
                             text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(cli.stdout)["generation"], 3)
        self.assertEqual(self.store().member("t123", "t123-principal")["generation"], 3)

    def test_interrupted_restart_resumes_without_a_second_bump(self) -> None:
        swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        self.quit_agent("t123-principal")
        journal_path = self.run_dir / "bootstrap.json"
        journal = json.loads(journal_path.read_text())
        journal["responsible"]["rotation"] = {"generation": 2, "previousGeneration": 1, "reason": "crash",
                                              "startedAt": "x", "completed": False}
        journal_path.write_text(json.dumps(journal))
        result = swarmctl.rotate_principal(self.run_dir, "retry")
        self.assertEqual(result["generation"], 2)
        store = self.store()
        self.assertEqual(store.message(result["bootEventId"])["fields"]["rotationReason"], "crash")
        self.assertEqual(len(store.find_messages("t123", type="BOOT")), 2)
        self.assertEqual(store.member("t123", "t123-principal")["generation"], 2)

    # -- swarmctl CLI and the file-based commands -----------------------------------------------------------------
    def swarmctl(self, *argv: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(HERE / "swarmctl.py"), *argv], env=os.environ.copy(),
                              text=True, capture_output=True, check=check)

    def test_swarmctl_event_commands_delegate_to_correio(self) -> None:
        root, _launch = self.init()
        payload = self.temp / "payload.json"
        payload.write_text(json.dumps({"reason": "decision", "detail": {"a": 1}}))
        body = self.temp / "body.md"
        body.write_text("# Bloqueio\n\nDetalhe.\n")
        sent = json.loads(self.swarmctl("event", "send", "--run-dir", str(root), "--from", "t123-principal",
                                        "--generation", "1", "--to", "orchestrator", "--type", "BLOCKED",
                                        "--payload-file", str(payload), "--body-file", str(body),
                                        "--subject", "T01 bloqueada").stdout)
        pending = json.loads(self.swarmctl("event", "pending", "--run-dir", str(root), "--recipient",
                                           "orchestrator").stdout)
        self.assertEqual([p["id"] for p in pending["pending"]], [sent["id"]])
        message = self.store().message(sent["id"])
        self.assertEqual(message["subject"], "T01 bloqueada")
        self.assertTrue(message["body"].startswith("# Bloqueio"))
        self.assertIn('"detail"', message["body"])
        receipt = json.loads(self.swarmctl("event", "receipt", "--run-dir", str(root), "--event", sent["id"],
                                           "--recipient", "orchestrator", "--disposition", "deciding").stdout)
        self.assertTrue(receipt["accepted"])
        phase = self.swarmctl("event", "send", "--run-dir", str(root), "--from", "t123-principal", "--generation",
                              "1", "--to", "orchestrator", "--type", "TASK_PHASE", "--task-id", "T01",
                              "--assignment-id", "a1", "--revision", "1", "--payload-file", str(payload), check=False)
        self.assertNotEqual(phase.returncode, 0)  # TASK_PHASE needs fields.phase
        self.assertIn("phase", phase.stderr)

    def test_file_commands_stay_in_files_and_record_an_info_with_the_hash(self) -> None:
        responsible, root, launch = self.bootstrap_team()
        output = root / "reports/orchestrator/snapshot.json"
        paths = self.temp / "paths.json"
        paths.write_text(json.dumps(["tracked.txt"]))
        snap = json.loads(self.swarmctl("snapshot", "create", "--run-dir", str(root), "--root", str(self.repo),
                                        "--paths-file", str(paths), "--output", str(output)).stdout)
        self.assertTrue(output.is_file())
        art = json.loads(self.swarmctl("artifact", "put", "--run-dir", str(root), "--file",
                                       str(self.repo / "tracked.txt")).stdout)
        self.assertTrue(pathlib.Path(art["path"]).is_file())
        argv = self.temp / "argv.json"
        argv.write_text(json.dumps([sys.executable, "-c", "print('ok')"]))
        gate = root / "reports/orchestrator/gate.json"
        reserved = json.loads(self.swarmctl("gate", "reserve", "--run-dir", str(root), "--cwd", str(self.repo),
                                            "--argv-file", str(argv), "--log", str(root / "reports/orchestrator/g.log"),
                                            "--exit", str(root / "reports/orchestrator/g.exit"),
                                            "--output", str(gate)).stdout)
        ran = json.loads(self.swarmctl("gate", "run", "--run-dir", str(root), "--contract", str(gate)).stdout)
        self.assertEqual(ran["gateExit"], 0)
        with self.principal_pane(responsible["principal"]["paneId"]):
            task = json.loads(self.swarmctl("worktree", "task", "--run-dir", str(root), "--task-id", "T123-T01",
                                            "--name", "t01", "--owner", "t123-principal", "--base", self.base).stdout)
        ledger = json.loads((root / "resources.json").read_text())
        self.assertEqual(ledger["tasks"]["T123-T01"]["worktree"], task["worktree"]["path"])
        store = self.store()
        infos = {m["id"]: m for m in store.find_messages("t123", type="INFO")}
        for result in (snap, art, reserved, ran, task):
            self.assertIn(result["info"], infos)
        snap_info = infos[snap["info"]]
        attached = store.q("SELECT path, sha256 FROM attachments WHERE message_id=?", (snap_info["id"],))
        self.assertEqual([(a["path"], a["sha256"]) for a in attached], [(str(output), snap["sha256"])])
        self.assertEqual(snap_info["from_agent"], "swarmctl")
        self.assertEqual(infos[task["info"]]["from_agent"], "t123-principal")  # the calling pane's member
        self.assertEqual(infos[ran["info"]]["fields"]["exit"], 0)

    def test_a_whole_run_flows_through_the_courier(self) -> None:
        """The canary's cycle with simulated agents: every wake goes out by the courier, in order."""
        from correio import daemon
        os.environ["CORREIO_HERDR"] = str(self.fake_bin / "herdr")
        responsible = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                                     no_supervisor=True)
        root, launch = swarmctl.load_launch(self.run_dir)
        store = self.store()
        courier = daemon.Courier(store, daemon.Herdr(), daemon.Options(cli="correio", legacy_refresh=0))

        def delivered(target: str, kind: str) -> str:
            before = len(self.log_entries("prompt"))
            courier.cycle()
            prompts = self.log_entries("prompt")[before:]
            self.assertEqual([p["target"] for p in prompts], [target], prompts)
            self.assertIn(f"{kind} ", prompts[0]["message"])
            return prompts[0]["message"].split(f"{kind} ", 1)[1].split()[0]

        principal, reviewer, me = "t123-principal", "t123-reviewer", "orchestrator"
        boot = delivered(principal, "BOOT")
        self.receipt(root, launch, boot, principal, True, "booting")
        self.ev(root, launch, principal, me, "AGENT_READY")
        ready = delivered("p0", "AGENT_READY")  # the responsible resolves by its recorded pane
        self.receipt(root, launch, ready, me, True, "validated")
        authorization = self.ev(root, launch, me, principal, "RESUME", {"bootstrapChildrenAuthorized": True})
        self.assertEqual(delivered(principal, "RESUME"), authorization)
        with self.principal_pane(responsible["principal"]["paneId"]):
            swarmctl.bootstrap_principal(self.run_dir, authorization)
        reviewer_boot = delivered(reviewer, "BOOT")
        self.receipt(root, launch, reviewer_boot, reviewer, True, "booting")
        self.ev(root, launch, reviewer, principal, "AGENT_READY")
        self.receipt(root, launch, delivered(principal, "AGENT_READY"), principal, True, "reviewer ok")
        self.ev(root, launch, principal, me, "SWARM_READY")
        self.receipt(root, launch, delivered("p0", "SWARM_READY"), me, True, "go")
        bound = {"taskId": "T123-T01", "assignmentId": "a1", "revision": 1}
        library.send(store, space="t123", sender=principal, to=principal, type="TASK_ASSIGN", generation=1,
                     fields={**bound, **self.grant(root)}, self_receipt="T01")
        for phase in ("red", "green"):
            self.ev(root, launch, principal, me, "TASK_PHASE", {"phase": phase}, bound)
        candidate = {**bound, "candidateSha": "f" * 40}
        self.ev(root, launch, principal, reviewer, "REVIEW_REQUEST", {}, candidate)
        self.receipt(root, launch, delivered(reviewer, "REVIEW_REQUEST"), reviewer, True, "reviewing")
        self.ev(root, launch, reviewer, principal, "APPROVED", {}, candidate)
        self.receipt(root, launch, delivered(principal, "APPROVED"), principal, True, "merging")
        library.send(store, space="t123", sender=principal, to=principal, type="TASK_INTEGRATED", generation=1,
                     fields=candidate, self_receipt="merged")
        self.ev(root, launch, principal, me, "SLICE_READY", {}, {"candidateSha": "e" * 40})
        ready_prompt_id = delivered("p0", "SLICE_READY")
        self.assertIn("+2 INFO unread", self.log_entries("prompt")[-1]["message"])  # the two TASK_PHASE
        self.receipt(root, launch, ready_prompt_id, me, True, "integrating")
        accepted = self.ev(root, launch, me, principal, "SLICE_ACCEPTED", {}, {"candidateSha": "e" * 40})
        self.receipt(root, launch, delivered(principal, "SLICE_ACCEPTED"), principal, True, "done")
        space = store.space("t123")
        self.assertEqual((space["state"], bool(space["closed_at"])), ("accepted", True))
        self.assertEqual(store.task("t123", "T123-T01")["state"], "integrated")
        self.assertTrue(store.receipt(accepted)["accepted"])
        before = len(self.log_entries("prompt"))
        courier.cycle()
        self.assertEqual(len(self.log_entries("prompt")), before)  # a closed space delivers nothing more

    def test_a_legacy_import_is_read_only_and_never_validated_as_3_0_0(self) -> None:
        self.contract["automation"] = "2.7.0"
        self.write_contract()
        root, launch = self.init()
        swarmctl.send_event(root, launch, sender="orchestrator", generation=1, recipient="t123-principal",
                            event_type="BOOT", payload={"rich": {"nested": True}})
        from correio import importers
        store = self.store()
        counts = importers.import_run(store, root)
        self.assertEqual((counts["messages"], counts["errors"]), (1, []))
        space = store.space("t123")
        self.assertEqual((space["legacy"], space["version"]), (True, "2.7.0"))
        with self.assertRaisesRegex(CorreioError, "read-only"):
            library.send(store, space="t123", sender="orchestrator", to="t123-principal", type="BOOT",
                         generation=1)


if __name__ == "__main__":
    unittest.main()
