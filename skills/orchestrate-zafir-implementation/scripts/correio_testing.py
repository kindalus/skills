"""Shared fixtures of the correio tests: temporary database, stepping clock, fake Herdr."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import unittest
from typing import Any

from correio import daemon, library
from correio.store import Clock, Store

FAKE_HERDR = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
state = pathlib.Path(os.environ["FAKE_HERDR_STATE"]); log = pathlib.Path(os.environ["FAKE_HERDR_LOG"])
args = sys.argv[1:]
data = json.loads(state.read_text()) if state.exists() else {"agents": []}
with log.open("a") as out:
    out.write(json.dumps(args) + "\n")
if args[:2] == ["agent", "list"]:
    print(json.dumps({"result": {"agents": data["agents"]}}))
elif args[:2] == ["agent", "prompt"]:
    if args[2] in data.get("failPrompt", []):
        print("agent_prompt_stalled", file=sys.stderr); raise SystemExit(1)
    print(json.dumps({"result": {}}))
elif args[:2] == ["notification", "show"]:
    print(json.dumps({"result": {}}))
else:
    print("unsupported", file=sys.stderr); raise SystemExit(1)
'''


class StepClock(Clock):
    def __init__(self, start: float = 1_800_000_000.0):
        self.t = start

    def epoch(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeHerdr(daemon.Herdr):
    """In-process Herdr: a list of agents, and a log of prompts and notifications."""

    def __init__(self, agents: list[dict[str, Any]] | None = None):
        super().__init__("fake-herdr")
        self.listed = agents or []
        self.prompts: list[tuple[str, str]] = []
        self.notes: list[tuple[str, str]] = []
        self.fail: set[str] = set()

    def set(self, name: str, status: str, pane: str | None = None) -> None:
        for agent in self.listed:
            if agent["name"] == name:
                agent["agent_status"] = status
                if pane:
                    agent["pane_id"] = pane
                return
        self.listed.append({"name": name, "agent_status": status, "pane_id": pane or f"p-{name}"})

    def agents(self) -> list[dict[str, Any]]:
        return [dict(a) for a in self.listed]

    def prompt(self, target: str, text: str) -> None:
        if target in self.fail:
            raise daemon.HerdrError("agent_prompt_stalled")
        self.prompts.append((target, text))

    def notify(self, title: str, body: str, sound: str = "request") -> None:
        self.notes.append((title, body))


class CorreioCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = pathlib.Path(tempfile.mkdtemp(prefix="correio-test-")).resolve()
        self.old_env = os.environ.copy()
        os.environ.pop("HERDR_PANE_ID", None)
        os.environ.pop("CORREIO_SPACE", None)
        os.environ["CORREIO_DB"] = str(self.temp / "state" / "correio.db")
        self.clock = StepClock()
        self.store = Store(self.temp / "state" / "correio.db", clock=self.clock)

    def tearDown(self) -> None:
        self.store.close()
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.temp, ignore_errors=True)

    def orchestration(self, space: str = "orq") -> str:
        library.create_space(self.store, space_id=space, kind="orchestration", protocol="orchestration",
                             version="1.0.0")
        for agent, role in (("orquestrador", "orchestrator"), ("porta-voz", "spokesperson"),
                            ("s606-preparer", "preparer"), ("consultor-claude", "consultant")):
            library.add_member(self.store, space, agent, role, pane_id=f"p-{agent}")
        return space

    def send(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("space", "orq")
        kwargs.setdefault("thread", "S606")
        kwargs.setdefault("subject", "assunto")
        kwargs.setdefault("type", "PEDIDO")
        return library.send(self.store, **kwargs)

    def fake_herdr_binary(self, agents: list[dict[str, Any]]) -> tuple[pathlib.Path, pathlib.Path]:
        binary = self.temp / "bin" / "herdr"
        binary.parent.mkdir(exist_ok=True)
        binary.write_text(FAKE_HERDR)
        binary.chmod(0o755)
        state, log = self.temp / "herdr.json", self.temp / "herdr.log"
        state.write_text(json.dumps({"agents": agents}))
        log.write_text("")
        os.environ.update(CORREIO_HERDR=str(binary), FAKE_HERDR_STATE=str(state), FAKE_HERDR_LOG=str(log))
        return state, log
