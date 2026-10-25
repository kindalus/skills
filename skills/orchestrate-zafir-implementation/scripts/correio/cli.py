"""correio: one mail system for the orchestration team and the swarms (correio v2).

  space create|close|show|list      member add|update|leave
  send                              receipt (one, or --all-info)
  inbox, show, thread, open, search export, import-files, import-run, import-jobs, compat
  export-v1, export-jobs            rollback: back to the v1 mailbox and the JSONL queue
  jobs add|next|start|attach|finish|recover|list   daemon, watchdog, backup
  legacy <v1 subcommand>            the v1 file mailbox, kept for rollback

The database is $CORREIO_DB or ~/.local/state/orchestrate-zafir-implementation/<$CORREIO_REPO_KEY>/correio.db.
Writes print one JSON object; errors print {"error": ...} on stderr and exit 2.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from typing import Any

from . import daemon, importers, library
from .store import CorreioError, Store, default_db_path

FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_]{0,63})(:?=)(.*)$", re.S)


def parse_field(raw: str) -> tuple[str, Any]:
    """``k=v`` is a string; ``k:=<json>`` a JSON value, structured ones kept as canonical JSON text."""
    match = FIELD.match(raw)
    if not match:
        raise CorreioError(f"--field takes key=value or key:=json, not {raw!r}")
    key, op, value = match.groups()
    if op == "=":
        return key, value
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CorreioError(f"--field {key}:= needs valid JSON") from exc
    return key, _field_value(decoded)


def _field_value(decoded: Any) -> Any:
    if isinstance(decoded, (dict, list)) or isinstance(decoded, float):
        return json.dumps(decoded, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return decoded


def parse_field_file(raw: str) -> tuple[str, Any]:
    key, sep, path = raw.partition("=")
    if not sep or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
        raise CorreioError(f"--field-file takes key=path, not {raw!r}")
    try:
        return key, _field_value(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorreioError(f"--field-file {key}: {exc}") from exc


def out(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def store_from(args: argparse.Namespace) -> Store:
    return Store(args.db or default_db_path())


# -- text views (agents read these; --json gives the data) --------------------------------------------------------------
def text_inbox(result: dict[str, Any]) -> str:
    lines = []
    for title, key in (("Por tratar", "pending"), ("INFO por ler", "info"), ("Inválidas", "invalid")):
        items = result[key]
        if not items:
            continue
        lines.append(f"{title} ({len(items)}):")
        for m in items:
            lines.append(f"  {m['sentAt'][:19]}Z {m['id']} {m['space']}/{m['thread']} {m['type']} "
                         f"{m['from']} -> {m['to']}: {m['subject']}" + (f"  [{m['error']}]" if m.get("error") else ""))
    return "\n".join(lines) or "Nada por tratar."


def text_overview(result: dict[str, Any]) -> str:
    lines = []
    beat = result["heartbeat"].get("courier")
    lines.append(f"Estafeta: {'sem heartbeat' if not beat else str(beat['ageSeconds']) + ' s (pid ' + str(beat['pid']) + ')'}")
    for sp in result["spaces"]:
        lines.append(f"\n{sp['id']} [{sp['kind']} {sp['protocol']}{' legacy' if sp['legacy'] else ''}] "
                     f"estado {sp['state']}")
        for m in sp["undelivered"]:
            lines.append(f"  sem recibo: {m['id']} {m['type']} {m['from']} -> {m['to']} há {m['ageSeconds']} s, "
                         f"{m['attempts']} tentativa(s), {m['lastAction'] or '—'}"
                         + (f", escalada {m['escalatedAt']}" if m['escalatedAt'] else "") + f": {m['subject']}")
        for agent, n in sp["unreadInfo"].items():
            lines.append(f"  INFO por ler: {agent} {n}")
        for m in sp["unanswered"]:
            lines.append(f"  sem resposta: {m['id']} {m['thread']} {m['type']} {m['from']} -> {m['to']}: {m['subject']}")
        threads = sp["openThreads"]
        if threads:
            lines.append("  threads abertas: " + ", ".join(f"{t['key']} ({t['messages']})" for t in threads[:20])
                         + (f" e mais {len(threads) - 20}" if len(threads) > 20 else ""))
        blocked = [n for n, m in sp["members"].items() if m["blocked"]]
        grants = [f"{n}={m['attributes']['grant']}" for n, m in sp["members"].items() if m["attributes"].get("grant")]
        if blocked:
            lines.append("  bloqueados: " + ", ".join(blocked))
        if grants:
            lines.append("  concessões: " + ", ".join(grants))
        for t in sp["tasks"]:
            if t["state"] != "integrated":
                lines.append(f"  tarefa {t['task_id']}: {t['state']} r{t['revision']} "
                             f"{(t['candidate_sha'] or '')[:9]}")
    jobs = result["jobs"]
    if jobs:
        lines.append("\nFila do host:")
        for j in jobs:
            lines.append(f"  {j['id']} {j['state']} {j['kind']} {j['who']} p{j['priority']} {j['at'][:16]}")
    return "\n".join(lines)


def text_thread(result: dict[str, Any]) -> str:
    lines = []
    for t in result["threads"]:
        lines.append(f"{t['space_id']}/{t['key']} ({t['state']}): {t['subject']}")
        for m in t["messages"]:
            r = m["receipt"]
            mark = "—" if not r else ("aceite" if r["accepted"] else "recusada") + f": {r['disposition'][:80]}"
            lines.append(f"  {m['sentAt'][:19]}Z {m['id']} {m['type']} {m['from']} -> {m['to']}: {m['subject']} [{mark}]")
    return "\n".join(lines)


# -- commands ---------------------------------------------------------------------------------------------------------------
def cmd_space(args: argparse.Namespace, store: Store) -> Any:
    if args.space_command == "create":
        contract = json.loads(pathlib.Path(args.contract).read_text(encoding="utf-8")) if args.contract else None
        return library.create_space(store, space_id=args.id, kind=args.kind, protocol=args.protocol,
                                    version=args.version, slice_id=args.slice, prefix=args.prefix,
                                    run_dir=args.run_dir, repo_path=args.repo_path, base_sha=args.base_sha,
                                    spec_path=args.spec_path, contract=contract)
    if args.space_command == "close":
        space = library.close_space(store, args.space)
        if args.export:
            space["export"] = library.export_space(store, args.space, args.export)
        return space
    if args.space_command == "show":
        space = store.space(args.space)
        if space is None:
            raise CorreioError(f"no space {args.space}")
        return {**space, "state": store.space_state(args.space), "members": store.members(args.space, include_left=True),
                "tasks": store.tasks(args.space)}
    return library.list_spaces(store, open_only=args.open)


def cmd_member(args: argparse.Namespace, store: Store) -> Any:
    space = library.resolve_space(store, args.space)
    if args.member_command == "add":
        configuration = json.loads(args.configuration) if args.configuration else None
        return library.add_member(store, space, args.agent, args.role, generation=args.generation,
                                  pane_id=args.pane, workspace_id=args.workspace, configuration=configuration)
    if args.member_command == "leave":
        return library.leave_member(store, space, args.agent)
    cols: dict[str, Any] = {}
    for key, value in (("pane_id", args.pane), ("workspace_id", args.workspace), ("generation", args.generation),
                       ("role", args.role)):
        if value is not None:
            cols[key] = value
    if args.ready is not None:
        cols["ready"] = args.ready == "true"
    attrs = dict(a.split("=", 1) for a in args.attr)
    if args.grant:
        attrs["grant"] = args.grant
    clear = list(args.clear_attr) + (["grant"] if args.clear_grant else [])
    return library.update_member(store, space, args.agent, set_attributes=attrs, clear_attributes=clear, **cols)


def cmd_send(args: argparse.Namespace, store: Store) -> Any:
    if args.body is not None and args.body_file is not None:
        raise CorreioError("give --body or --body-file, not both")
    body = args.body or ""
    if args.body_file:
        path = pathlib.Path(args.body_file)
        if path.stat().st_size > 900 * 1024:
            raise CorreioError("body file is too large for an envelope; send it with --attach")
        body = path.read_text(encoding="utf-8")
    fields: dict[str, Any] = {}
    for raw in args.field:
        key, value = parse_field(raw)
        fields[key] = value
    for raw in args.field_file:
        key, value = parse_field_file(raw)
        fields[key] = value
    for key, value in (("taskId", args.task_id), ("assignmentId", args.assignment_id), ("revision", args.revision),
                       ("candidateSha", args.candidate_sha)):
        if value is not None:
            fields[key] = value
    space = library.resolve_space(store, args.space)
    thread, compat = args.thread, None
    sp = store.space(space)
    if (thread is None or args.payload_file) and sp and sp["kind"] == "orchestration":
        # The v1 form: no --thread, and structure in --payload-file. It works only inside the cutover window.
        if not library.compat_v1(store)["active"]:
            raise CorreioError(
                "correio v2: send needs --thread (the slice or the request: S606, S606/REQUEST-15 or geral) and "
                "takes fields with --field/--field-file, not --payload-file; the v1 form ended at the cutover, so "
                "nothing was sent. Send again in the v2 form (references/operations.md, Mail).")
        payload: dict[str, Any] = {}
        if args.payload_file:
            payload = json.loads(pathlib.Path(args.payload_file).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise CorreioError("--payload-file must hold a JSON object; nothing was sent")
            scalars, structured = importers._scalar_split(payload)
            fields = {**scalars, **fields}
            if structured:
                body += "\n```json\n" + json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n```\n"
        thread = thread or library.infer_thread(args.subject, body, payload)
        compat = "v1"
        print(json.dumps({"warning": f"v1 compatibility: thread {thread}; from now on send with --thread "
                                     "and --field (references/operations.md, Mail)"}, ensure_ascii=False),
              file=sys.stderr)
    result = library.send(store, space=space, sender=args.sender, to=args.to, type=args.type, thread=thread,
                          subject=args.subject, body=body, fields=fields, attachments=args.attach,
                          reply_to=args.reply_to, generation=args.generation, message_id=args.id,
                          self_receipt=args.self_receipt)
    return {**result, "compat": compat} if compat else result


def cmd_receipt(args: argparse.Namespace, store: Store) -> Any:
    if args.all_info:
        done = library.receipt_all_info(store, agent=args.agent, disposition=args.disposition, space=args.space)
        return {"agent": args.agent, "receipted": [r["message_id"] for r in done]}
    if not args.id:
        raise CorreioError("give --id, or --all-info")
    return library.receipt(store, message_id=args.id, agent=args.agent, disposition=args.disposition,
                           accepted=not args.reject)


def caller_agent(store: Store) -> str | None:
    pane = os.environ.get("HERDR_PANE_ID")
    if not pane:
        return None
    rows = store.q("SELECT DISTINCT m.agent FROM members m JOIN spaces s ON s.id=m.space_id WHERE m.pane_id=? "
                   "AND m.left_at IS NULL AND s.closed_at IS NULL", (pane,))
    return rows[0]["agent"] if len(rows) == 1 else None


def cmd_inbox(args: argparse.Namespace, store: Store) -> Any:
    agent = args.agent or caller_agent(store)
    result = library.inbox(store, agent=agent, space=args.space, include_receipted=args.all)
    return result if args.json else text_inbox(result)


def cmd_show(args: argparse.Namespace, store: Store) -> Any:
    message_id = args.message_id or args.id
    if not message_id:
        raise CorreioError("show needs a message id")
    result = library.show(store, message_id, args.agent)
    if args.json:
        return result
    if args.raw:
        sys.stdout.write(result["envelope"])
        return None
    receipt = result["receipt"]
    tail = ["", f"# recibo: {'nenhum' if not receipt else ('aceite' if receipt['accepted'] else 'recusada')}"
            + (f" por {receipt['agent']}" + (f" (registado por {receipt['receipted_by']})"
                                              if receipt.get("receipted_by") else "")
               + f" em {receipt['receipted_at']}: {receipt['disposition']}" if receipt else "")]
    for item in result["attachments"]:
        tail.append(f"# anexo {item['path']}: {'inalterado' if item['unchanged'] else 'ALTERADO OU EM FALTA'}")
    if result["replies"]:
        tail.append("# respostas: " + ", ".join(result["replies"]))
    return result["envelope"] + "\n".join(tail)


def cmd_import(args: argparse.Namespace, store: Store) -> Any:
    if args.command == "import-files":
        return importers.import_files(store, args.root, space=args.space)
    if args.command == "import-run":
        return importers.import_run(store, args.run_dir)
    return importers.import_jobs(store, args.file)


def cmd_jobs(args: argparse.Namespace, store: Store) -> Any:
    if args.jobs_command == "add":
        parts = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
        cmd = " ".join(parts).strip()
        return library.jobs_add(store, kind=args.kind, who=args.who, cmd=cmd, priority=args.priority, job_id=args.id)
    if args.jobs_command == "next":
        return library.jobs_next(store, runner_pid=args.runner_pid)
    if args.jobs_command == "start":
        return library.jobs_start(store, args.job_id, runner_pid=args.runner_pid)
    if args.jobs_command == "attach":
        return library.jobs_attach(store, args.job_id, args.pid)
    if args.jobs_command == "recover":
        return library.jobs_recover(store)
    if args.jobs_command == "close":
        return library.jobs_close(store, args.reason)
    if args.jobs_command == "reopen":
        return library.jobs_reopen(store)
    if args.jobs_command == "finish":
        return library.jobs_finish(store, args.job_id, args.exit)
    return library.jobs_list(store, everything=args.all, last=args.last)


def cmd_daemon(args: argparse.Namespace, store: Store) -> int:
    options = daemon.Options(
        retry_min=args.retry_min, max_backoff=args.max_backoff, escalate_after=args.escalate_after,
        stuck_after=args.stuck_after, watch_to=args.watch_to, done_pattern=args.done_pattern,
        quiet=tuple(filter(None, args.quiet.split(","))), watch_ref=tuple(args.watch_ref),
        fetch_every=args.fetch_every, watch_runs=tuple(args.watch_runs), watch_jobs=tuple(args.watch_jobs),
        space=args.space, backup_dir=None if args.no_backup else (args.backup_dir or str(store.path.parent / "backups")),
        backup_keep=args.backup_keep, legacy_refresh=args.legacy_refresh, readonly=args.readonly,
        only_kind=args.only_kind, sync_v1_root=args.sync_v1_root, sync_v1_jobs=args.sync_v1_jobs)
    return daemon.run(store, daemon.Herdr(), options, interval=args.interval, once=args.once)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="correio", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="database path (default $CORREIO_DB or the repo key's correio.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    space = sub.add_parser("space").add_subparsers(dest="space_command", required=True)
    p = space.add_parser("create")
    p.add_argument("--id", required=True)
    p.add_argument("--kind", required=True, choices=["orchestration", "swarm"])
    p.add_argument("--protocol", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--contract", help="launch.json of a swarm")
    for name in ("--slice", "--prefix", "--run-dir", "--repo-path", "--base-sha", "--spec-path"):
        p.add_argument(name)
    p = space.add_parser("close")
    p.add_argument("--space", required=True)
    p.add_argument("--export", help="also export the evidence archive to this empty directory")
    p = space.add_parser("show")
    p.add_argument("--space", required=True)
    p = space.add_parser("list")
    p.add_argument("--open", action="store_true")

    member = sub.add_parser("member").add_subparsers(dest="member_command", required=True)
    for name in ("add", "update", "leave"):
        p = member.add_parser(name)
        p.add_argument("--space")
        p.add_argument("--agent", required=True)
        if name == "leave":
            continue
        p.add_argument("--role", required=name == "add")
        p.add_argument("--pane")
        p.add_argument("--workspace")
        p.add_argument("--generation", type=int, default=1 if name == "add" else None)
        if name == "add":
            p.add_argument("--configuration", help="JSON")
        else:
            p.add_argument("--ready", choices=["true", "false"])
            p.add_argument("--grant", help="mark a consultant or executor grant active (the done observer uses it)")
            p.add_argument("--clear-grant", action="store_true")
            p.add_argument("--attr", action="append", default=[], metavar="KEY=VALUE")
            p.add_argument("--clear-attr", action="append", default=[], metavar="KEY")

    p = sub.add_parser("send", help="write, validate and store one message")
    p.add_argument("--space")
    p.add_argument("--thread")
    p.add_argument("--type", required=True)
    p.add_argument("--from", dest="sender", required=True)
    p.add_argument("--generation", type=int)
    p.add_argument("--to", required=True)
    p.add_argument("--reply-to")
    p.add_argument("--subject")
    p.add_argument("--body")
    p.add_argument("--body-file")
    p.add_argument("--field", action="append", default=[], metavar="KEY=VALUE|KEY:=JSON")
    p.add_argument("--field-file", action="append", default=[], metavar="KEY=JSONFILE")
    p.add_argument("--attach", action="append", default=[], metavar="PATH")
    p.add_argument("--task-id")
    p.add_argument("--assignment-id")
    p.add_argument("--revision", type=int)
    p.add_argument("--candidate-sha")
    p.add_argument("--id", help=argparse.SUPPRESS)
    p.add_argument("--self-receipt", metavar="DISPOSITION", help="receipt a message to yourself in the same step")
    p.add_argument("--payload-file", help=argparse.SUPPRESS)  # v1 form, only inside the compatibility window

    p = sub.add_parser("receipt")
    p.add_argument("--id")
    p.add_argument("--agent", required=True)
    p.add_argument("--disposition", required=True)
    p.add_argument("--reject", action="store_true")
    p.add_argument("--all-info", action="store_true")
    p.add_argument("--space")

    for name in ("inbox", "pending"):
        p = sub.add_parser(name)
        p.add_argument("--agent")
        p.add_argument("--space")
        p.add_argument("--all", action="store_true", help="include receipted messages")
        p.add_argument("--json", action="store_true")
    p = sub.add_parser("show")
    p.add_argument("message_id", nargs="?")
    p.add_argument("--id")
    p.add_argument("--agent", help=argparse.SUPPRESS)
    p.add_argument("--raw", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("thread")
    p.add_argument("key")
    p.add_argument("--space")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("open", help="what needs attention now")
    p.add_argument("--space")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("search")
    p.add_argument("text")
    p.add_argument("--space")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("export")
    p.add_argument("--space", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("export-v1", help="rollback: an orchestration space back into a v1 mailbox")
    p.add_argument("--space", required=True)
    p.add_argument("--root", required=True, help="the v1 correio/ root (adds only what is missing)")
    p = sub.add_parser("export-jobs", help="rollback: the jobs table back into the v1 JSONL queue (merges)")
    p.add_argument("--file", required=True)
    p = sub.add_parser("import-files")
    p.add_argument("--root", required=True)
    p.add_argument("--space")
    p = sub.add_parser("import-run")
    p.add_argument("--run-dir", required=True)
    p = sub.add_parser("import-jobs")
    p.add_argument("--file", required=True)

    jobs = sub.add_parser("jobs").add_subparsers(dest="jobs_command", required=True)
    p = jobs.add_parser("add")
    p.add_argument("--kind", required=True, choices=sorted(library.JOB_KINDS))
    p.add_argument("--who", required=True)
    p.add_argument("--priority", type=int, default=0)
    p.add_argument("--id", help=argparse.SUPPRESS)
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    p = jobs.add_parser("next", help="claim the next queued job unless one is running")
    p.add_argument("--runner-pid", type=int, help="the runner that waits for the job (its identity is recorded)")
    for name in ("start", "finish", "attach"):
        p = jobs.add_parser(name)
        p.add_argument("job_id")
        if name == "start":
            p.add_argument("--runner-pid", type=int)
        if name == "finish":
            p.add_argument("--exit", type=int, required=True)
        if name == "attach":
            p.add_argument("--pid", type=int, required=True, help="the process running the job's command")
    jobs.add_parser("recover", help="close running jobs whose command and runner are gone (exit -1)")
    p = jobs.add_parser("close", help="rollback barrier: jobs add fails until reopen")
    p.add_argument("--reason", required=True)
    jobs.add_parser("reopen")
    p = jobs.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.add_argument("--last", type=int)

    p = sub.add_parser("daemon", help="courier and observers")
    p.add_argument("--interval", type=float, default=10.0)
    p.add_argument("--retry-min", type=float, default=30.0)
    p.add_argument("--max-backoff", type=float, default=480.0)
    p.add_argument("--escalate-after", type=float, default=7200.0)
    p.add_argument("--stuck-after", type=float, default=120.0)
    p.add_argument("--space", help="orchestration space for the courier's own mail")
    p.add_argument("--watch-to", default="orquestrador")
    p.add_argument("--done-pattern", default="")
    p.add_argument("--sync-v1-root", metavar="DIR", help="while the v1 window is open, import this v1 mailbox each cycle")
    p.add_argument("--sync-v1-jobs", metavar="JSONL", help="while the v1 window is open, import this v1 queue each cycle")
    p.add_argument("--only-kind", choices=["swarm"],
                   help="after a rollback to v1: deliver only swarm spaces, with no observers and no mail")
    p.add_argument("--readonly", default="", metavar="REGEX",
                   help="read-only (sandboxed) agents: the courier writes their copy and receipts after the prompt")
    p.add_argument("--quiet", default="porta-voz")
    p.add_argument("--watch-ref", action="append", default=[], metavar="REPO:REF")
    p.add_argument("--fetch-every", type=float, default=60.0)
    p.add_argument("--watch-runs", action="append", default=[], metavar="RUNS_DIR")
    p.add_argument("--watch-jobs", action="append", default=[], metavar="JSONL")
    p.add_argument("--backup-dir")
    p.add_argument("--backup-keep", type=int, default=14)
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--legacy-refresh", type=float, default=300.0)
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("compat", help="the cutover window in which v1 send still works")
    p.add_argument("which", choices=["v1"])
    group = p.add_mutually_exclusive_group()
    group.add_argument("--hours", type=float)
    group.add_argument("--until")
    group.add_argument("--off", action="store_true")
    p = sub.add_parser("watchdog", help="restart the courier when its heartbeat is stale")
    p.add_argument("--max-age", type=float, default=120.0)
    p.add_argument("--unit")
    p = sub.add_parser("backup")
    p.add_argument("--dir")
    p.add_argument("--keep", type=int, default=14)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["legacy"]:
        from . import legacy_v1
        return legacy_v1.main(argv[1:])
    os.umask(0o077)
    try:
        args = build_parser().parse_args(argv)
        if args.command == "watchdog":  # no Store: opening one migrates under the write lock it must watch
            result = daemon.watchdog(args.db or default_db_path(), daemon.Herdr(), max_age=args.max_age,
                                     unit=args.unit)
            out(result)
            return 0 if result["ok"] else 1
        store = store_from(args)
        if args.command == "daemon":
            return cmd_daemon(args, store)
        if args.command == "backup":
            import datetime as dt
            day = dt.datetime.fromtimestamp(store.clock.epoch(), dt.timezone.utc).date()
            target = daemon.backup(store, pathlib.Path(args.dir or store.path.parent / "backups"), day, args.keep)
            out({"backup": str(target)})
            return 0
        handlers = {"space": cmd_space, "member": cmd_member, "send": cmd_send, "receipt": cmd_receipt,
                    "inbox": cmd_inbox, "pending": cmd_inbox, "show": cmd_show, "jobs": cmd_jobs,
                    "import-files": cmd_import, "import-run": cmd_import, "import-jobs": cmd_import}
        if args.command in handlers:
            result = handlers[args.command](args, store)
        elif args.command == "thread":
            result = library.thread(store, args.key, args.space)
            result = result if args.json else text_thread(result)
        elif args.command == "open":
            result = library.overview(store, args.space)
            result = result if args.json else text_overview(result)
        elif args.command == "search":
            result = library.search(store, args.text, space=args.space, limit=args.limit)
        elif args.command == "compat":
            if args.off:
                result = library.set_compat_v1(store, until=None)
            elif args.hours is not None or args.until:
                until = args.until or store.clock.iso(store.clock.epoch() + args.hours * 3600)
                result = library.set_compat_v1(store, until=until)
            else:
                result = library.compat_v1(store)
        elif args.command == "export":
            result = library.export_space(store, args.space, args.out)
        elif args.command == "export-v1":
            result = library.export_v1(store, args.space, args.root)
        elif args.command == "export-jobs":
            result = library.export_jobs(store, args.file)
        else:
            raise CorreioError(f"unsupported command {args.command}")
        if isinstance(result, str):
            print(result)
        elif result is not None or args.command == "jobs":
            out(result)
        return 0
    except (CorreioError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
