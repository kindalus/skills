#!/usr/bin/env python3
"""Deterministic control plane for the orchestrate-zafir-implementation swarm.

Scripts move bytes and verify facts. Agents retain product and authority decisions.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
from typing import Any

from swarmbootstrap import (
    bootstrap_principal, bootstrap_responsible, close_worktree, remove_worktree, require_main_checkout,
    review_worktree, rotate_principal, task_worktree, wait_agent,
)
from swarmcore import (
    AUTOMATION_V3, EVENT_TYPES, V3_EVENT_TYPES, SwarmError, artifact_put, events_for, gate_reserve, gate_run, herdr,
    init_run, load_json, load_launch, parse_model_triple, pending_events, receipt_event, send_event, sha256_file,
    snapshot_create, snapshot_verify, validate_new_launch, validate_launch, canonical, run, VERSION,
)

def cmd_doctor(args: argparse.Namespace) -> dict[str, Any]:
    contract = validate_new_launch(load_json(args.contract), canonical(args.run_dir) if args.run_dir else None)
    parsed_models = {key: parse_model_triple(value) for key, value in contract["models"].items()}
    executables = {"git", "herdr", *(triple[0] for triple in parsed_models.values())}
    checks = {name: shutil.which(name) for name in sorted(executables)}
    if any(value is None for value in checks.values()):
        raise SwarmError(f"missing executables: {checks}")
    if not args.skip_herdr:
        if os.environ.get("HERDR_ENV") != "1":
            raise SwarmError("HERDR_ENV=1 is required")
        status = run(["herdr", "status", "server"]).stdout.strip()
        panes = herdr("pane", "list", "--workspace", contract["responsible"]["workspaceId"]).get("panes", [])
        matches = [pane for pane in panes if pane.get("pane_id") == contract["responsible"]["paneId"]]
        if len(matches) != 1:
            raise SwarmError("responsible pane is absent or ambiguous in the recorded workspace")
        agents = herdr("agent", "list").get("agents", [])
        named = [agent for agent in agents if agent.get("name") == contract["responsible"]["agent"]]
        if named and any(agent.get("pane_id") != contract["responsible"]["paneId"] for agent in named):
            raise SwarmError("responsible agent name is live in an unexpected pane")
        herdr("worktree", "list", "--cwd", contract["repoPath"])
        herdr_help = run(["herdr", "agent", "start", "--help"]).stdout
        for harness in {triple[0] for triple in parsed_models.values()}:
            if not re.search(rf"\b{re.escape(harness)}\b", herdr_help):
                raise SwarmError(f"Herdr does not advertise harness kind: {harness}")
            run([harness, "--help"])
    else:
        status = "skipped"
    repo = canonical(contract["repoPath"], exists=True)
    require_main_checkout(repo)
    run(["git", "-C", str(repo), "cat-file", "-e", f"{contract['baseSha']}^{{commit}}"])
    run(["git", "check-ref-format", "--branch", contract["slice"]["branch"]])
    catalog: dict[str, str] = {}
    if not args.skip_model_catalog:
        for key, (harness, model, _effort) in parsed_models.items():
            if harness != "pi":
                catalog[key] = "executable-verified; alias requires Responsible confirmation"
                continue
            if "/" not in model:
                raise SwarmError(f"Pi model must use exact provider/model form: {model}")
            provider, model_id = model.split("/", 1)
            env = os.environ.copy()
            env["PI_OFFLINE"] = "1"
            listing = run(["pi", "--list-models", model], env=env).stdout.splitlines()[1:]
            available = any(len(row.split()) >= 2 and row.split()[:2] == [provider, model_id]
                            for row in listing)
            if not available:
                raise SwarmError(f"Pi model is unavailable: {model}")
            catalog[key] = "exact-catalog-match"
    return {"ok": True, "version": VERSION, "executables": checks, "herdr": status,
            "runId": contract["runId"], "models": parsed_models, "modelCatalog": catalog}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--contract", type=pathlib.Path, required=True)
    doctor.add_argument("--run-dir", type=pathlib.Path)
    doctor.add_argument("--skip-herdr", action="store_true", help=argparse.SUPPRESS)
    doctor.add_argument("--skip-model-catalog", action="store_true", help=argparse.SUPPRESS)
    init = sub.add_parser("init")
    init.add_argument("--contract", type=pathlib.Path, required=True)
    init.add_argument("--run-dir", type=pathlib.Path, required=True)
    boot = sub.add_parser("bootstrap")
    boot_sub = boot.add_subparsers(dest="bootstrap_command", required=True)
    responsible = boot_sub.add_parser("responsible")
    responsible.add_argument("--contract", type=pathlib.Path, required=True)
    responsible.add_argument("--run-dir", type=pathlib.Path, required=True)
    responsible.add_argument("--dry-run", action="store_true")
    responsible.add_argument("--no-supervisor", action="store_true", help=argparse.SUPPRESS)
    principal = boot_sub.add_parser("principal")
    principal.add_argument("--run-dir", type=pathlib.Path, required=True)
    principal.add_argument("--authorization-event", type=pathlib.Path, required=True)
    wait = boot_sub.add_parser("wait-agent", help="wait for a run agent blocked at startup (MODEL_REPLACE restart)")
    wait.add_argument("--run-dir", type=pathlib.Path, required=True)
    wait.add_argument("--agent", required=True)
    rotate = boot_sub.add_parser("restart-principal", aliases=["rotate-principal"])
    rotate.add_argument("--run-dir", type=pathlib.Path, required=True)
    rotate.add_argument("--reason", required=True)
    worktree = sub.add_parser("worktree")
    worktree_sub = worktree.add_subparsers(dest="worktree_command", required=True)
    task = worktree_sub.add_parser("task")
    task.add_argument("--run-dir", type=pathlib.Path, required=True)
    task.add_argument("--task-id", required=True)
    task.add_argument("--name", required=True)
    task.add_argument("--owner", required=True)
    task.add_argument("--base", required=True)
    review = worktree_sub.add_parser("review")
    review.add_argument("--run-dir", type=pathlib.Path, required=True)
    review.add_argument("--task-id", required=True)
    review.add_argument("--revision", type=int, required=True)
    review.add_argument("--candidate-sha", required=True)
    close = worktree_sub.add_parser("close")
    close.add_argument("--run-dir", type=pathlib.Path, required=True)
    close.add_argument("--path", type=pathlib.Path, required=True)
    remove = worktree_sub.add_parser("remove")
    remove.add_argument("--run-dir", type=pathlib.Path, required=True)
    remove.add_argument("--path", type=pathlib.Path, required=True)
    remove.add_argument("--merged-into", required=True)
    event = sub.add_parser("event")
    event_sub = event.add_subparsers(dest="event_command", required=True)
    send = event_sub.add_parser("send")
    send.add_argument("--run-dir", type=pathlib.Path, required=True)
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--generation", type=int, required=True)
    send.add_argument("--to", required=True)
    send.add_argument("--type", required=True, choices=sorted(V3_EVENT_TYPES))
    send.add_argument("--payload-file", type=pathlib.Path)
    send.add_argument("--subject", help="3.0.0 runs: one-line subject (default: type and task)")
    send.add_argument("--body-file", type=pathlib.Path, help="3.0.0 runs: Markdown body")
    send.add_argument("--thread", help="3.0.0 runs: thread key (default: the task ID, else the slice ID)")
    send.add_argument("--attach", action="append", default=[], help="3.0.0 runs: file cited by path and sha256")
    send.add_argument("--id")
    send.add_argument("--task-id")
    send.add_argument("--assignment-id")
    send.add_argument("--revision", type=int)
    send.add_argument("--candidate-sha")
    receipt = event_sub.add_parser("receipt")
    receipt.add_argument("--run-dir", type=pathlib.Path, required=True)
    receipt.add_argument("--event", required=True, help="event file (2.7.0) or message id (3.0.0)")
    receipt.add_argument("--recipient", required=True)
    receipt.add_argument("--reject", action="store_true")
    receipt.add_argument("--disposition", required=True)
    pending = event_sub.add_parser("pending")
    pending.add_argument("--run-dir", type=pathlib.Path, required=True)
    pending.add_argument("--recipient")
    artifact = sub.add_parser("artifact")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    put = artifact_sub.add_parser("put")
    put.add_argument("--run-dir", type=pathlib.Path, required=True)
    put.add_argument("--file", type=pathlib.Path, required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot_sub = snapshot.add_subparsers(dest="snapshot_command", required=True)
    create = snapshot_sub.add_parser("create")
    create.add_argument("--run-dir", type=pathlib.Path, required=True)
    create.add_argument("--root", type=pathlib.Path, required=True)
    create.add_argument("--paths-file", type=pathlib.Path, required=True)
    create.add_argument("--output", type=pathlib.Path, required=True)
    verify = snapshot_sub.add_parser("verify")
    verify.add_argument("--run-dir", type=pathlib.Path, required=True)
    verify.add_argument("--snapshot", type=pathlib.Path, required=True)
    gate = sub.add_parser("gate")
    gate_sub = gate.add_subparsers(dest="gate_command", required=True)
    reserve = gate_sub.add_parser("reserve")
    reserve.add_argument("--run-dir", type=pathlib.Path, required=True)
    reserve.add_argument("--cwd", type=pathlib.Path, required=True)
    reserve.add_argument("--argv-file", type=pathlib.Path, required=True)
    reserve.add_argument("--unset-env", action="append", default=[])
    reserve.add_argument("--log", type=pathlib.Path, required=True)
    reserve.add_argument("--exit", dest="exit_path", type=pathlib.Path, required=True)
    reserve.add_argument("--output", type=pathlib.Path, required=True)
    execute = gate_sub.add_parser("run")
    execute.add_argument("--run-dir", type=pathlib.Path, required=True)
    execute.add_argument("--contract", type=pathlib.Path, required=True)
    return parser


def dispatch(args: argparse.Namespace) -> tuple[Any, int]:
    if args.command == "doctor":
        return cmd_doctor(args), 0
    if args.command == "init":
        return init_run(args.contract, args.run_dir), 0
    if args.command == "bootstrap":
        if args.bootstrap_command == "responsible":
            return bootstrap_responsible(args.contract, args.run_dir, dry_run=args.dry_run,
                                         no_supervisor=args.no_supervisor), 0
        if args.bootstrap_command in {"restart-principal", "rotate-principal"}:
            return rotate_principal(args.run_dir, args.reason), 0
        if args.bootstrap_command == "wait-agent":
            return wait_agent(args.run_dir, args.agent), 0
        return bootstrap_principal(args.run_dir, args.authorization_event), 0
    root, launch = load_launch(args.run_dir)
    events = events_for(root, launch)

    def recorded(result: dict[str, Any], kind: str, subject: str, attachments: list[Any] = (),
                 **fields: Any) -> dict[str, Any]:
        """3.0.0: an INFO to the responsible agent cites what this command created, by path and sha256."""
        if events.version == AUTOMATION_V3:
            info = events.info(kind=kind, subject=subject, attachments=[str(a) for a in attachments],
                               fields={k: v for k, v in fields.items() if v is not None})
            result = {**result, "info": info}
        return result

    if args.command == "worktree":
        if args.worktree_command == "task":
            result = task_worktree(root, launch, args.task_id, args.name, args.owner, args.base)
            return recorded(result, "worktree", f"task worktree {args.task_id}", taskId=args.task_id,
                            path=result["worktree"]["path"], branch=result["worktree"]["branch"],
                            head=result["worktree"]["head"]), 0
        if args.worktree_command == "review":
            result = review_worktree(root, launch, args.task_id, args.revision, args.candidate_sha)
            return recorded(result, "worktree", f"review checkout {args.task_id} r{args.revision}",
                            taskId=args.task_id, revision=args.revision, candidateSha=args.candidate_sha,
                            path=result["path"]), 0
        if args.worktree_command == "close":
            return close_worktree(root, launch, args.path), 0
        return remove_worktree(root, launch, args.path, args.merged_into), 0
    if args.command == "event":
        if args.event_command == "pending":
            return events.pending(args.recipient), 0
        if args.event_command == "receipt":
            return events.receipt(args.event, args.recipient, not args.reject, args.disposition), 0
        payload = load_json(args.payload_file) if args.payload_file else {}
        fields = {k: v for k, v in {
            "taskId": args.task_id, "assignmentId": args.assignment_id,
            "revision": args.revision, "candidateSha": args.candidate_sha,
        }.items() if v is not None}
        if events.version != AUTOMATION_V3:
            if args.type not in EVENT_TYPES:
                raise SwarmError(f"unknown event type: {args.type}")
            if args.subject or args.body_file or args.thread or args.attach:
                raise SwarmError("--subject, --body-file, --thread and --attach need a 3.0.0 run")
            ref = events.send(sender=args.sender, generation=args.generation, recipient=args.to,
                              event_type=args.type, payload=payload, event_id=args.id, fields=fields)
            return {"eventPath": ref, "sha256": sha256_file(ref)}, 0
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else None
        ref = events.send(sender=args.sender, generation=args.generation, recipient=args.to, event_type=args.type,
                          payload=payload, event_id=args.id, fields=fields, subject=args.subject, body=body,
                          thread=args.thread, attachments=args.attach)
        return {"id": ref, "sha256": events.store.message(ref)["sha256"], "space": events.space}, 0
    if args.command == "artifact":
        result = artifact_put(root, launch, args.file)
        return recorded(result, "artifact", f"artifact {pathlib.Path(args.file).name}", [result["path"]],
                        source=str(canonical(args.file))), 0
    if args.command == "snapshot":
        if args.snapshot_command == "verify":
            result = snapshot_verify(root, launch, args.snapshot)
            return result, 0 if result["ok"] else 1
        paths = load_json(args.paths_file)
        if not isinstance(paths, list) or any(not isinstance(x, str) for x in paths):
            raise SwarmError("paths-file must contain a string array")
        value = snapshot_create(root, launch, args.root, paths, args.output)
        result = {"snapshotPath": str(args.output), "files": len(value["files"]), "sha256": sha256_file(args.output)}
        return recorded(result, "snapshot", f"snapshot {pathlib.Path(args.output).name}", [args.output]), 0
    if args.command == "gate":
        if args.gate_command == "run":
            code = gate_run(root, launch, args.contract)
            contract = load_json(args.contract)
            result = {"gateExit": code, "contract": str(args.contract)}
            return recorded(result, "gate", f"gate {contract['id']} exit {code}",
                            [args.contract, contract["logPath"], contract["exitPath"]], gateId=contract["id"],
                            exit=code), code
        argv = load_json(args.argv_file)
        if not isinstance(argv, list):
            raise SwarmError("argv-file must contain an array")
        value = gate_reserve(root, launch, args.cwd, argv, args.unset_env, args.log,
                             args.exit_path, args.output)
        result = {"contractPath": str(args.output), "id": value["id"], "sha256": sha256_file(args.output)}
        return recorded(result, "gate", f"gate {value['id']} reserved", [args.output], gateId=value["id"]), 0
    raise SwarmError("unsupported command")


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result, code = dispatch(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return code
    except (SwarmError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
