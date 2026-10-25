#!/usr/bin/env python3
"""Idempotent Herdr/Git bootstrap implementation for the orchestrate-zafir-implementation swarm."""
from __future__ import annotations

import concurrent.futures
import contextlib
import fcntl
import json
import time
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

from swarmcore import (
    AUTOMATION_V3, SHA_RE, VERSION, SwarmError, canonical, coder_names, correio_modules, events_for, herdr,
    init_run, is_v3, ledger_path, load_json, load_launch, model_args, now, principal_name as principal_of,
    reviewer_name, roster, run, run_marker, validate_new_launch, write_json_mutable,
)

def git_worktrees(repo: pathlib.Path) -> dict[pathlib.Path, dict[str, str]]:
    text = run(["git", "-C", str(repo), "worktree", "list", "--porcelain"]).stdout
    result: dict[pathlib.Path, dict[str, str]] = {}
    block: dict[str, str] = {}
    for line in text.splitlines() + [""]:
        if not line:
            if "worktree" in block:
                result[canonical(block["worktree"])] = block
            block = {}
        else:
            key, _, value = line.partition(" ")
            block[key] = value
    return result


def require_main_checkout(repo: pathlib.Path) -> None:
    """Herdr creates and opens worktrees only from the repository's main checkout."""
    common = run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"]).stdout
    git_dir = run(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"]).stdout
    if canonical(common.strip()) != canonical(git_dir.strip()):
        raise SwarmError("repoPath must be the main checkout, not a linked worktree")


def herdr_worktree(repo: pathlib.Path, path: pathlib.Path) -> dict[str, Any] | None:
    """Herdr's view of one checkout; ``open_workspace_id`` is None when no workspace shows it."""
    for entry in herdr("worktree", "list", "--cwd", str(repo)).get("worktrees", []):
        if canonical(entry["path"]) == path:
            return entry
    return None


def _workspace_ids(result: dict[str, Any]) -> dict[str, Any]:
    """IDs from ``worktree create``/``open``; ``fresh`` marks a root pane this call created."""
    return {"workspaceId": result["workspace"]["workspace_id"], "tabId": result["tab"]["tab_id"],
            "rootPaneId": result["root_pane"]["pane_id"], "fresh": not result.get("already_open", False)}


# Herdr exposes no "shell ready" flag, and a new pane's shell answers agent_pane_busy while it
# initializes. A pane is an available shell when it hosts no agent, its shell is the only foreground
# process, and it has drawn its screen, unchanged over SHELL_SETTLE_READS consecutive reads.
SHELL_POLL_SECONDS = 0.2
SHELL_SETTLE_READS = 3
SHELL_TIMEOUT_SECONDS = 30.0
AGENT_START_ATTEMPTS = 3


def shell_state(pane_id: str) -> tuple[bool, Any]:
    """``(True, revision)`` for an idle shell prompt, else ``(False, reason)``."""
    pane = herdr("pane", "get", pane_id)["pane"]
    if pane.get("agent"):
        return False, f"agent {pane['agent']} occupies it"
    info = herdr("pane", "process-info", "--pane", pane_id)["process_info"]
    shell = info.get("shell_pid")
    foreground = info.get("foreground_processes") or []
    if not shell or info.get("foreground_process_group_id") != shell or [p.get("pid") for p in foreground] != [shell]:
        return False, f"foreground {[p.get('name') for p in foreground]}"
    if not pane.get("revision"):
        return False, "nothing drawn yet"
    return True, pane["revision"]


def wait_for_shell(pane_id: str) -> None:
    """Block until ``pane_id`` is an available shell; a hosted agent fails at once."""
    deadline = time.monotonic() + SHELL_TIMEOUT_SECONDS
    settled, streak = None, 0
    while True:
        ready, detail = shell_state(pane_id)
        if not ready and str(detail).startswith("agent "):
            raise SwarmError(f"pane {pane_id} is not an available shell: {detail}")
        streak = streak + 1 if ready and detail == settled else int(ready)
        settled = detail if ready else None
        if streak >= SHELL_SETTLE_READS:
            return
        if time.monotonic() >= deadline:
            reason = "still redrawing" if ready else detail
            raise SwarmError(f"pane {pane_id} is not an available shell after {SHELL_TIMEOUT_SECONDS:g}s: {reason}")
        time.sleep(SHELL_POLL_SECONDS)


# An agent that starts in a folder it has never seen (Claude in a new worktree or home) stops at a dialog, and
# ``herdr agent start`` answers agent_not_ready: "blocked during startup". The agent is registered all the same,
# so this is not a failure: the start waits for it. The one dialog accepted here is the folder-trust question
# for exactly the folder the run created for that agent; anything else is announced (ATTENTION on stderr and a
# Herdr notification) and waited for, up to AGENT_READY_TIMEOUT_SECONDS.
AGENT_READY_TIMEOUT_SECONDS = 900.0
AGENT_READY_POLL_SECONDS = 2.0
TRUST_ACCEPT_ATTEMPTS = 3
TRUST_MARKERS = ("Yes,Itrustthisfolder", "Isthisaprojectyoucreatedoroneyoutrust")


def _flat(text: str) -> str:
    """The screen without line breaks, spaces and box borders: a long path wraps across lines."""
    return re.sub(r"[\s│┃|╭╮╰╯─]", "", text)


def trust_dialog_for(screen: str, folder: pathlib.Path) -> bool:
    """Whether ``screen`` shows the folder-trust dialog and the folder it names is exactly ``folder``. The path
    stands on its own line(s) in the dialog; a long one wraps, so consecutive lines are joined, without spaces
    and box borders, and must spell the folder exactly from a line start to a line end."""
    if not any(marker in _flat(screen) for marker in TRUST_MARKERS):
        return False
    want = _flat(str(folder))
    lines = [_flat(line) for line in screen.splitlines()]
    for first in range(len(lines)):
        joined = ""
        for line in lines[first:]:
            joined += line
            if joined == want:
                return True
            if not joined or not want.startswith(joined):
                break
    return False


def await_agent_ready(name: str, pane_id: str, folder: pathlib.Path, *, label: str = "") -> dict[str, Any]:
    """Wait until ``name`` is idle or done, accepting only the trust dialog for ``folder``."""
    deadline = time.monotonic() + AGENT_READY_TIMEOUT_SECONDS
    accepted, announced = 0, False
    while True:
        agent = named_agents().get(name)
        status = agent.get("agent_status") if agent else None
        if agent and status in {"idle", "done", "working"}:
            return agent
        try:
            screen = run(["herdr", "pane", "read", pane_id, "--source", "visible"], timeout=15).stdout
        except SwarmError:
            screen = ""
        if accepted < TRUST_ACCEPT_ATTEMPTS and trust_dialog_for(screen, folder):
            run(["herdr", "pane", "send-keys", pane_id, "down", "enter"], timeout=15)
            accepted += 1
            print(json.dumps({"trustAccepted": {"agent": name, "pane": pane_id, "folder": str(folder)}}),
                  file=sys.stderr, flush=True)
        elif not announced:
            announced = True
            reason = f"{name} is {status or 'not registered'} during startup in pane {pane_id}"
            print(f"ATTENTION: {reason}: answer it in the pane; waiting up to {AGENT_READY_TIMEOUT_SECONDS:g} s",
                  file=sys.stderr, flush=True)
            with contextlib.suppress(SwarmError):
                herdr("notification", "show", f"Swarm {label}: {name} bloqueado no arranque".strip(),
                      "--body", f"{reason}. Responde no pane; a espera continua.", "--sound", "request")
        if time.monotonic() >= deadline:
            raise SwarmError(f"{name} is still {status or 'not registered'} after {AGENT_READY_TIMEOUT_SECONDS:g} s "
                             f"in pane {pane_id}: answer its pane, then run the same command again (it adopts it)")
        time.sleep(AGENT_READY_POLL_SECONDS)


def start_agent(name: str, harness: str, pane_id: str, args: list[str], *, folder: pathlib.Path,
                label: str = "") -> dict[str, Any]:
    """``herdr agent start`` once the pane is an available shell, with a bounded retry on agent_pane_busy; an
    agent blocked during startup (agent_not_ready) is registered, so the start waits for it to be ready."""
    for attempt in range(1, AGENT_START_ATTEMPTS + 1):
        wait_for_shell(pane_id)
        try:
            agent = herdr("agent", "start", name, "--kind", harness, "--pane", pane_id, "--", *args,
                          timeout=60)["agent"]
        except SwarmError as exc:
            if "agent_not_ready" in str(exc):
                return await_agent_ready(name, pane_id, folder, label=label)
            if "agent_pane_busy" not in str(exc) or attempt == AGENT_START_ATTEMPTS:
                raise
            continue
        if agent.get("agent_status") == "blocked":
            return await_agent_ready(name, pane_id, folder, label=label)
        return agent
    raise AssertionError("unreachable")


def close_idle_pane(pane_id: str) -> dict[str, str] | None:
    """``herdr pane close`` for an idle shell; returns the kept pane and why otherwise."""
    try:
        wait_for_shell(pane_id)
    except SwarmError as exc:
        return {"paneId": pane_id, "reason": str(exc)}
    herdr("pane", "close", pane_id)
    return None


def close_idle_workspace(workspace_id: str, *, strict: bool = False) -> dict[str, Any]:
    """Plain ``herdr workspace close`` (never ``--group``) when every pane in it is an idle shell.

    The worktree and its branch stay; ``herdr worktree open`` reopens the workspace.
    """
    kept = []
    for pane in _workspace_panes(workspace_id):
        try:
            wait_for_shell(pane["pane_id"])
        except SwarmError as exc:
            kept.append({"paneId": pane["pane_id"], "reason": str(exc)})
    if kept and strict:
        raise SwarmError(f"workspace {workspace_id} stays open: {kept}")
    if not kept:
        herdr("workspace", "close", workspace_id)
    return {"closedWorkspace": None if kept else workspace_id, "keptPanes": kept}


def open_worktree(repo: pathlib.Path, path: pathlib.Path, label: str) -> dict[str, str]:
    """Open an existing checkout in its Herdr workspace; an already open one is returned as is."""
    return _workspace_ids(herdr("worktree", "open", "--cwd", str(repo), "--path", str(path), "--label", label,
                                "--no-focus", timeout=60))


def ensure_worktree(repo: pathlib.Path, path: pathlib.Path, branch: str, base: str, label: str, *,
                    dry_run: bool = False, allow_advanced_adoption: bool = False,
                    open_existing: bool = True) -> dict[str, Any]:
    """Create or adopt a branch worktree in its own Herdr workspace (``herdr worktree create``).

    ``open_existing=False`` adopts an existing checkout without reopening a closed workspace.
    """
    run(["git", "check-ref-format", "--branch", branch])
    run(["git", "-C", str(repo), "cat-file", "-e", f"{base}^{{commit}}"])
    require_main_checkout(repo)
    existing = git_worktrees(repo).get(path)
    if existing:
        actual = run(["git", "-C", str(path), "rev-parse", "HEAD"]).stdout.strip()
        actual_branch = run(["git", "-C", str(path), "branch", "--show-current"]).stdout.strip()
        if actual_branch != branch:
            raise SwarmError(f"worktree branch mismatch: {actual_branch}")
        if not allow_advanced_adoption:
            dirty = run(["git", "-C", str(path), "status", "--porcelain"]).stdout.strip()
            if actual != base or dirty:
                raise SwarmError("unowned worktree is not clean at its base")
        adopted = {"action": "adopt", "path": str(path), "branch": branch, "head": actual}
        if dry_run or not open_existing:
            entry = herdr_worktree(repo, path) or {}
            return {**adopted, "workspaceId": entry.get("open_workspace_id"), "fresh": False}
        return {**adopted, **open_worktree(repo, path, label)}
    if path.exists():
        raise SwarmError(f"unrecorded worktree path already exists: {path}")
    ref = run(["git", "-C", str(repo), "show-ref", "--verify", f"refs/heads/{branch}"], check=False)
    argv = ["worktree", "create", "--cwd", str(repo), "--branch", branch, "--path", str(path),
            "--label", label, "--no-focus"]
    if ref.returncode == 0:
        # Herdr checks out an existing branch as it is and ignores --base: verify the head here.
        if run(["git", "-C", str(repo), "rev-parse", branch]).stdout.strip() != base:
            raise SwarmError(f"existing branch {branch} is not at its base")
    else:
        argv += ["--base", base]
    if dry_run:
        return {"action": "create", "argv": ["herdr", *argv], "path": str(path), "branch": branch, "head": base}
    path.parent.mkdir(parents=True, exist_ok=True)
    created = herdr(*argv, timeout=120)
    return {"action": "create", "path": str(path), "branch": branch,
            "head": run(["git", "-C", str(path), "rev-parse", "HEAD"]).stdout.strip(), **_workspace_ids(created)}


def ensure_slice_worktree(launch: dict[str, Any], *, dry_run: bool = False,
                          allow_advanced_adoption: bool = False) -> dict[str, Any]:
    return ensure_worktree(canonical(launch["repoPath"], exists=True), canonical(launch["slice"]["worktree"]),
                           launch["slice"]["branch"], launch["baseSha"], launch["prefix"], dry_run=dry_run,
                           allow_advanced_adoption=allow_advanced_adoption)


def pane_title(launch: dict[str, Any], role: str) -> str:
    """Pane title of a team member, ``<prefix> · <role>`` (references/naming.md of the skill)."""
    return f"{launch['prefix']} \u00b7 {role}"


def label_slice_workspace(launch: dict[str, Any], workspace_id: str, tab_id: str, principal_pane: str) -> None:
    """Workspace and tab labelled ``<prefix>``, the Principal's pane titled; idempotent, rerun on every bootstrap."""
    herdr("workspace", "rename", workspace_id, launch["prefix"])
    herdr("tab", "rename", tab_id, launch["prefix"])
    herdr("pane", "rename", principal_pane, pane_title(launch, "principal"))


def named_agents() -> dict[str, dict[str, Any]]:
    result = herdr("agent", "list")
    return {a["name"]: a for a in result.get("agents", []) if a.get("name")}


def validate_responsible_resource(launch: dict[str, Any]) -> None:
    responsible = launch["responsible"]
    panes = herdr("pane", "list", "--workspace", responsible["workspaceId"]).get("panes", [])
    matches = [pane for pane in panes if pane.get("pane_id") == responsible["paneId"]]
    if len(matches) != 1:
        raise SwarmError("responsible pane is absent or ambiguous in the recorded workspace")
    named = named_agents().get(responsible["agent"])
    if named and named.get("pane_id") != responsible["paneId"]:
        raise SwarmError("responsible agent name is live in an unexpected pane")


def recover_boot_event(root: pathlib.Path, launch: dict[str, Any], sender: str,
                       recipient: str, expected_configuration: str) -> str | None:
    """The generation-1 BOOT already published for ``recipient`` (a file path in 2.7.0, a message id in 3.0.0)."""
    matches = [ref for ref, event in events_for(root, launch).find("BOOT", sender, recipient)
               if event["payload"].get("generation") == 1
               and event["payload"].get("expectedConfiguration") == expected_configuration]
    if len(matches) > 1:
        raise SwarmError(f"multiple recoverable BOOT events for {recipient}")
    return matches[0] if matches else None


def correio_member(root: pathlib.Path, agent: str, **cols: Any) -> None:
    """3.0.0: keep the agent's member row (pane, workspace, generation) in step with Herdr."""
    if not is_v3(root):
        return
    marker = run_marker(root)
    library, store_module = correio_modules(marker["correio"].get("scripts"))
    store = store_module.Store(marker["correio"]["db"])
    try:
        library.update_member(store, marker["correio"]["space"], agent, **cols)
    except Exception as exc:
        raise SwarmError(f"correio: {exc}") from exc
    finally:
        store.close()


def boot_prompt(root: pathlib.Path, ref: str, tail: str) -> str:
    if is_v3(root):
        cli = f"python3 {run_marker(root)['correio']['scripts']}/correio.py"
        return (f"Read and receipt BOOT {ref}: {cli} show {ref}, then {cli} receipt --agent <you> --id {ref} "
                f"--disposition '<what you do>'. Send events with {cli} send (swarm/3.0.0). {tail}")
    return f"Read and receipt BOOT {ref}. {tail}"


def bootstrap_journal(root: pathlib.Path, launch: dict[str, Any]) -> dict[str, Any]:
    path = root / "bootstrap.json"
    if path.exists():
        value = load_json(path)
        if value.get("runId") != launch["runId"]:
            raise SwarmError("bootstrap journal runId mismatch")
        return value
    value = {"schemaVersion": 1, "automationVersion": AUTOMATION_V3 if is_v3(root) else VERSION,
             "runId": launch["runId"], "responsible": {}, "principal": {}, "updatedAt": now()}
    write_json_mutable(path, value)
    return value


def save_bootstrap(root: pathlib.Path, value: dict[str, Any]) -> None:
    value["updatedAt"] = now()
    write_json_mutable(root / "bootstrap.json", value)


def bootstrap_responsible(contract_path: pathlib.Path, run_dir: pathlib.Path, *, dry_run: bool,
                          no_supervisor: bool) -> dict[str, Any]:
    contract = validate_new_launch(load_json(contract_path), run_dir)
    validate_responsible_resource(contract)
    existing_journal = canonical(run_dir) / "bootstrap.json"
    owned_at_plan = False
    if existing_journal.is_file():
        prior = load_json(existing_journal)
        owned_at_plan = prior.get("responsible", {}).get("worktree", {}).get("path") == contract["slice"]["worktree"]
    plan: dict[str, Any] = {
        "runDir": str(canonical(run_dir)),
        "worktree": ensure_slice_worktree(contract, dry_run=True, allow_advanced_adoption=owned_at_plan),
        "principalName": principal_of(contract), "principalModel": contract["models"]["principal"],
        "startsChildren": False,
        "childrenStartedByPrincipal": [reviewer_name(contract), *coder_names(contract)],
    }
    if dry_run:
        return {"dryRun": True, "plan": plan}
    init = init_run(contract_path, run_dir)
    root, launch = load_launch(run_dir)
    journal = bootstrap_journal(root, launch)
    owned_worktree = journal["responsible"].get("worktree", {}).get("path") == launch["slice"]["worktree"]
    worktree = ensure_slice_worktree(launch, allow_advanced_adoption=owned_worktree)
    journal["responsible"]["worktree"] = worktree
    save_bootstrap(root, journal)
    principal_name = principal_of(launch)
    generation = journal["responsible"].get("principalGeneration", 1)
    agents = named_agents()
    workspace_id = worktree["workspaceId"]
    if principal_name in agents:
        agent = agents[principal_name]
        if canonical(agent["cwd"]) != canonical(launch["slice"]["worktree"]):
            raise SwarmError("live Principal has unexpected cwd")
        if agent.get("workspace_id") != workspace_id:
            raise SwarmError("live Principal is outside the slice workspace")
        pane_id, tab_id = agent["pane_id"], agent["tab_id"]
    elif generation > 1:
        raise SwarmError("Principal was restarted; start it again with bootstrap restart-principal")
    else:
        # The Principal starts in the root pane of the slice worktree's Herdr workspace.
        pane_id, tab_id = worktree["rootPaneId"], worktree["tabId"]
        root_pane = [p for p in _workspace_panes(workspace_id) if p.get("pane_id") == pane_id]
        if len(root_pane) != 1 or canonical(root_pane[0].get("cwd", "/")) != canonical(launch["slice"]["worktree"]):
            raise SwarmError("cannot safely adopt the slice workspace root pane")
        journal["responsible"].update(principalPaneId=pane_id, principalTabId=tab_id)
        save_bootstrap(root, journal)
        harness, args = model_args(launch["models"]["principal"])
        start_agent(principal_name, harness, pane_id, args, folder=canonical(launch["slice"]["worktree"]),
                    label=launch["prefix"])
    label_slice_workspace(launch, workspace_id, tab_id, pane_id)
    journal["responsible"].update(principalPaneId=pane_id, principalTabId=tab_id,
                                   principalWorkspaceId=workspace_id,
                                   principalGeneration=generation, principalStarted=True)
    save_bootstrap(root, journal)
    events = events_for(root, launch)
    if events.version == AUTOMATION_V3:
        correio_member(root, principal_name, pane_id=pane_id, workspace_id=workspace_id)
    else:
        supervisor = load_json(root / "supervisor.json")
        supervisor["principal"] = {"agent": principal_name, "paneId": pane_id, "generation": generation}
        supervisor["updatedAt"] = now()
        write_json_mutable(root / "supervisor.json", supervisor)
    boot_ref = journal["responsible"].get(events.journal_key, "")
    if not events.exists(boot_ref):
        boot_ref = recover_boot_event(root, launch, launch["responsible"]["agent"], principal_name,
                                      launch["models"]["principal"]) or ""
    if not events.exists(boot_ref):
        payload = {
            "rolePath": str(canonical(launch["skillRoot"]) / "roles" / "principal.md"),
            "launchPath": str(root / "launch.json"), "generation": 1,
            "expectedConfiguration": launch["models"]["principal"], "ponytailPath": launch["ponytailPath"],
            "instruction": "Read rolePath and launchPath only; load references on demand. Validate identity/runtime, "
                           "emit AGENT_READY, then wait for Responsible validation before child bootstrap.",
        }
        boot_ref = events.send(sender=launch["responsible"]["agent"], generation=1, recipient=principal_name,
                               event_type="BOOT", payload=payload)
        journal["responsible"][events.journal_key] = boot_ref
        save_bootstrap(root, journal)
    agent = named_agents().get(principal_name)
    if agent and agent.get("agent_status") in {"idle", "done"}:
        tools = ("" if events.version == AUTOMATION_V3 else f"Use {root / 'runtime/swarmctl.py'} for events. ")
        herdr("agent", "prompt", principal_name, boot_prompt(
            root, boot_ref, tools + "Emit AGENT_READY with native runtime evidence; do not create children before "
                                    "Responsible RESUME."))
    supervisor_result = None
    if not no_supervisor and events.version != AUTOMATION_V3:
        supervisor_result = start_supervisor(root)
    return {"dryRun": False, "init": init, "worktree": worktree, "principal": {
        "name": principal_name, "paneId": pane_id, "tabId": tab_id, "workspaceId": workspace_id,
        events.journal_key: boot_ref},
        "supervisor": supervisor_result}


def create_initial_state(launch: dict[str, Any], principal: dict[str, Any]) -> dict[str, Any]:
    """Initial ledger; ``principal`` holds paneId, tabId, workspaceId and generation.

    The Principal is its sole writer. ``workspaceId`` is the slice worktree's Herdr workspace.
    """
    agents: dict[str, Any] = {principal_of(launch): {
        "role": "principal", "generation": principal["generation"], "paneId": principal["paneId"],
        "tabId": principal["tabId"], "workspaceId": principal["workspaceId"],
        "configuration": launch["models"]["principal"], "ready": True, "activeAssignments": []}}
    agents[reviewer_name(launch)] = {"role": "reviewer", "generation": 1, "paneId": None, "tabId": None,
                                     "workspaceId": None, "configuration": launch["models"]["reviewer"],
                                     "ready": False, "activeAssignments": []}
    for name in coder_names(launch):
        agents[name] = {"role": "coder", "generation": 1, "paneId": None, "tabId": None, "workspaceId": None,
                        "configuration": launch["models"]["coders"], "ready": False,
                        "activeAssignments": []}
    return {
        "schemaVersion": 2, "automationVersion": VERSION, "runId": launch["runId"],
        "sliceId": launch["sliceId"], "prefix": launch["prefix"], "state": "starting",
        "responsible": launch["responsible"],
        "branch": launch["slice"]["branch"], "worktree": launch["slice"]["worktree"],
        "workspaceId": principal["workspaceId"], "baseSha": launch["baseSha"], "roleConfigurations": {
            key: {"value": value, "revision": 1, "history": []} for key, value in launch["models"].items()},
        "agents": agents, "plan": None, "tasks": {}, "openFindings": [], "leases": [],
        "processedEventIds": [], "resourceOwnership": {}, "updatedAt": now(),
    }


def create_resource_ledger(launch: dict[str, Any], principal: dict[str, Any]) -> dict[str, Any]:
    """3.0.0: panes, workspaces and task worktrees only; agent, task and slice state are correio projections."""
    agents: dict[str, Any] = {principal_of(launch): {
        "role": "principal", "paneId": principal["paneId"], "tabId": principal["tabId"],
        "workspaceId": principal["workspaceId"]}}
    for name, role in [(reviewer_name(launch), "reviewer"), *((n, "coder") for n in coder_names(launch))]:
        agents[name] = {"role": role, "paneId": None, "tabId": None, "workspaceId": None}
    return {"schemaVersion": 1, "automationVersion": AUTOMATION_V3, "runId": launch["runId"],
            "prefix": launch["prefix"], "agents": agents, "tasks": {}, "resourceOwnership": {}, "updatedAt": now()}


def validate_principal_authorization(root: pathlib.Path, launch: dict[str, Any], path: Any) -> dict[str, Any]:
    event = events_for(root, launch).get(str(path), principal_of(launch))
    if event["type"] != "RESUME" or event["from"] != launch["responsible"]["agent"]:
        raise SwarmError("child bootstrap requires Responsible RESUME")
    if event["payload"].get("bootstrapChildrenAuthorized") is not True:
        raise SwarmError("RESUME does not explicitly authorize child bootstrap")
    return event


def _workspace_panes(workspace_id: str | None = None) -> list[dict[str, Any]]:
    """Panes of one workspace, or of every workspace when ``workspace_id`` is None."""
    args = ("pane", "list", "--workspace", workspace_id) if workspace_id else ("pane", "list")
    return herdr(*args).get("panes", [])


def _check_recorded_layout(root: pathlib.Path, layout: dict[str, Any]) -> None:
    # A coder's pane may have moved into a task workspace, so look across every workspace.
    live_panes = {p["pane_id"]: p for p in _workspace_panes()}
    for name, resource in layout.items():
        pane = live_panes.get(resource.get("paneId"))
        if pane is None or canonical(pane.get("cwd", "/")) != canonical(root / "homes" / name):
            raise SwarmError(f"recorded child pane is absent or has unexpected cwd: {name}")


def _adopt_pane(workspace_id: str, expected_cwd: pathlib.Path,
                tab_id: str | None = None) -> dict[str, str] | None:
    matches = [p for p in _workspace_panes(workspace_id) if canonical(p.get("cwd", "/")) == canonical(expected_cwd)
               and (tab_id is None or p.get("tab_id") == tab_id)]
    if len(matches) > 1:
        raise SwarmError(f"multiple panes match bootstrap home: {expected_cwd}")
    return ({"paneId": matches[0]["pane_id"], "tabId": matches[0]["tab_id"], "workspaceId": workspace_id}
            if matches else None)


def _ensure_split(root: pathlib.Path, workspace_id: str, journal: dict[str, Any],
                  layout: dict[str, Any], name: str, source: str, direction: str,
                  tab_id: str) -> dict[str, str]:
    """Create/adopt one pane and journal it before the next side effect."""
    if name in layout:
        return layout[name]
    home = root / "homes" / name
    resource = _adopt_pane(workspace_id, home, tab_id)
    if resource is None:
        pane = herdr("pane", "split", source, "--direction", direction, "--cwd", str(home),
                     "--no-focus")["pane"]
        resource = {"paneId": pane["pane_id"], "tabId": tab_id, "workspaceId": workspace_id}
    layout[name] = resource
    save_bootstrap(root, journal)
    return resource


def _ensure_tab(root: pathlib.Path, workspace_id: str, journal: dict[str, Any],
                layout: dict[str, Any], name: str, label: str) -> dict[str, str]:
    """Create/adopt a labelled tab whose root pane is ``name``'s home."""
    if name in layout:
        return layout[name]
    home = root / "homes" / name
    adopted = _adopt_pane(workspace_id, home)
    if adopted is None:
        tabs = herdr("tab", "list", "--workspace", workspace_id).get("tabs", [])
        matches = [t for t in tabs if t.get("label") == label]
        if len(matches) > 1:
            raise SwarmError(f"multiple tabs match bootstrap label: {label}")
        if matches:
            adopted = _adopt_pane(workspace_id, home, matches[0]["tab_id"])
            if adopted is None:
                raise SwarmError(f"tab {label} exists without the recorded {name} home")
        else:
            created = herdr("tab", "create", "--workspace", workspace_id,
                            "--cwd", str(home), "--label", label, "--no-focus")
            adopted = {"paneId": created["root_pane"]["pane_id"], "tabId": created["tab"]["tab_id"],
                       "workspaceId": workspace_id}
    layout[name] = adopted
    save_bootstrap(root, journal)
    return adopted


def _create_child_layout(root: pathlib.Path, launch: dict[str, Any], journal: dict[str, Any],
                         principal: dict[str, Any]) -> dict[str, dict[str, str]]:
    """In the slice workspace: the reviewer beside the Principal; coders, if any, side by side in their tab.

    ``swarmctl worktree task`` later moves each coder's pane into the workspace of its current task.
    """
    prefix, workspace_id = launch["prefix"], principal["workspace_id"]
    layout = journal["principal"].setdefault("layout", {})
    _check_recorded_layout(root, layout)
    _ensure_split(root, workspace_id, journal, layout, reviewer_name(launch), principal["pane_id"], "right",
                  principal["tab_id"])
    letters = roster(launch)
    if "a" in letters:
        coder_a = _ensure_tab(root, workspace_id, journal, layout, f"{prefix}-coder-a", f"{prefix}-coders")
    if "b" in letters:
        _ensure_split(root, workspace_id, journal, layout, f"{prefix}-coder-b", coder_a["paneId"], "right",
                      coder_a["tabId"])
    return layout


def _load_or_create_state(root: pathlib.Path, launch: dict[str, Any],
                          principal: dict[str, Any]) -> dict[str, Any]:
    state_path = ledger_path(root)
    if is_v3(root):
        if state_path.exists():
            state = load_json(state_path)
            expected_agents = {principal_of(launch), reviewer_name(launch), *coder_names(launch)}
            if (state.get("runId") != launch["runId"] or state.get("automationVersion") != AUTOMATION_V3
                    or set(state.get("agents", {})) != expected_agents):
                raise SwarmError("cannot adopt unknown or incomplete resource ledger")
            return state
        state = create_resource_ledger(launch, principal)
        write_json_mutable(state_path, state)
        return state
    if state_path.exists():
        state = load_json(state_path)
        required_state = {"runId", "schemaVersion", "agents", "tasks", "openFindings",
                          "processedEventIds", "resourceOwnership"}
        expected_agents = {principal_of(launch), reviewer_name(launch), *coder_names(launch)}
        if (state.get("runId") != launch["runId"] or state.get("schemaVersion") != 2
                or state.get("automationVersion") != VERSION or state.get("prefix") != launch["prefix"]
                or required_state - state.keys() or set(state.get("agents", {})) != expected_agents):
            raise SwarmError("cannot adopt unknown or incomplete state schema")
        return state
    state = create_initial_state(launch, principal)
    write_json_mutable(state_path, state)
    return state


def _boot_and_start_children(root: pathlib.Path, launch: dict[str, Any], journal: dict[str, Any],
                             section: str, layout: dict[str, dict[str, str]], sender: str,
                             sender_generation: int, state: dict[str, Any]) -> dict[str, Any]:
    """Record panes in state, reserve every BOOT serially, then start the children concurrently."""
    state_path = ledger_path(root)
    events = events_for(root, launch)
    for name, resource in layout.items():
        state["agents"][name].update(paneId=resource["paneId"], tabId=resource["tabId"],
                                     workspaceId=resource["workspaceId"])
        state["resourceOwnership"][resource["paneId"]] = name
        correio_member(root, name, pane_id=resource["paneId"], workspace_id=resource["workspaceId"])
    state["updatedAt"] = now()
    write_json_mutable(state_path, state)
    live = named_agents()

    def configuration(name: str) -> str:
        if events.version == AUTOMATION_V3:
            return launch["models"]["reviewer" if name == reviewer_name(launch) else "coders"]
        return state["agents"][name]["configuration"]

    # The threads below never write shared state or the bootstrap journal.
    boot_events = journal[section].setdefault("bootEvents", {})
    for name in sorted(layout):
        if events.exists(boot_events.get(name, "")):
            continue
        role = "reviewer" if name == reviewer_name(launch) else "coder"
        ref = recover_boot_event(root, launch, sender, name, configuration(name)) or ""
        if events.exists(ref):
            boot_events[name] = ref
            save_bootstrap(root, journal)
            continue
        payload = {
            "rolePath": str(canonical(launch["skillRoot"]) / "roles" / f"{role}.md"),
            "launchPath": str(root / "launch.json"), "generation": 1, "coordinator": sender,
            "expectedConfiguration": configuration(name),
            "ponytailPath": launch["ponytailPath"] if role == "coder" else None,
            "instruction": "Read rolePath and launchPath only; load references on demand. Validate runtime and "
                           "emit AGENT_READY. No productive work until a TASK_ASSIGN (coder) or a "
                           "REVIEW_REQUEST (reviewer).",
        }
        boot_events[name] = events.send(sender=sender, generation=sender_generation, recipient=name,
                                        event_type="BOOT", payload=payload)
        save_bootstrap(root, journal)

    def start_child(name: str, resource: dict[str, str]) -> tuple[str, dict[str, Any]]:
        if name in live:
            if live[name]["pane_id"] != resource["paneId"]:
                raise SwarmError(f"live child pane mismatch: {name}")
            result = live[name]
        else:
            key = "reviewer" if name == reviewer_name(launch) else "coders"
            harness, args = model_args(launch["models"][key])
            result = start_agent(name, harness, resource["paneId"], args, folder=root / "homes" / name,
                                 label=launch["prefix"])
        ref = boot_events[name]
        if result.get("agent_status") in {"idle", "done"}:
            herdr("agent", "prompt", name, boot_prompt(
                root, ref, "Read rolePath and launch contract, verify native runtime evidence, "
                           f"then emit AGENT_READY to {sender}; no productive work."))
        return name, {"paneId": resource["paneId"], events.journal_key: ref, "status": result.get("agent_status")}

    started: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(start_child, name, resource): name for name, resource in layout.items()}
        for future in concurrent.futures.as_completed(futures):
            name, result = future.result()
            started[name] = result
    journal[section]["childrenStarted"] = started
    save_bootstrap(root, journal)
    if reviewer_name(launch) in layout:
        herdr("pane", "rename", layout[reviewer_name(launch)]["paneId"], pane_title(launch, "reviewer"))
    for name, result in started.items():
        state["agents"][name]["liveStatus"] = result["status"]
    state["updatedAt"] = now()
    write_json_mutable(state_path, state)
    return started


def bootstrap_principal(run_dir: pathlib.Path, authorization: pathlib.Path) -> dict[str, Any]:
    root, launch = load_launch(run_dir)
    auth = validate_principal_authorization(root, launch, authorization)
    principal_name = principal_of(launch)
    events_for(root, launch).receipt(str(authorization), principal_name, True, "Child bootstrap authorized")
    agents = named_agents()
    principal = agents.get(principal_name)
    if not principal:
        raise SwarmError("Principal is not live in Herdr")
    if os.environ.get("HERDR_PANE_ID") and os.environ["HERDR_PANE_ID"] != principal["pane_id"]:
        raise SwarmError("bootstrap must run from the recorded Principal pane")
    journal = bootstrap_journal(root, launch)
    if principal.get("workspace_id") != journal["responsible"].get("principalWorkspaceId"):
        raise SwarmError("Principal is not in the recorded slice workspace")
    generation = journal["responsible"].get("principalGeneration", 1)
    state = _load_or_create_state(root, launch, {"paneId": principal["pane_id"], "tabId": principal["tab_id"],
                                                 "workspaceId": principal["workspace_id"],
                                                 "generation": generation})
    if not is_v3(root):
        generation = state["agents"][principal_name]["generation"]
        supervisor = load_json(root / "supervisor.json")
        supervisor.update(principalValidated=True, principalValidationEvent=auth["id"], updatedAt=now())
        write_json_mutable(root / "supervisor.json", supervisor)
    layout = _create_child_layout(root, launch, journal, principal)
    started = _boot_and_start_children(root, launch, journal, "principal", layout, principal_name,
                                       generation, state)
    return {"principal": principal_name, "authorizationEvent": auth["id"], "children": started,
            "startsProductiveWork": False}


def wait_agent(run_dir: pathlib.Path, name: str) -> dict[str, Any]:
    """After a manual ``herdr agent start`` (a MODEL_REPLACE restart, models.md) that answered agent_not_ready:
    wait for the run's agent as the bootstrap does, accepting only the trust dialog for the folder the run
    created for it (the slice worktree for the Principal, homes/<name> for a child)."""
    root, launch = load_launch(run_dir)
    if name == principal_of(launch):
        folder = canonical(launch["slice"]["worktree"])
    elif name == reviewer_name(launch) or name in coder_names(launch):
        folder = root / "homes" / name
    else:
        raise SwarmError(f"{name} is not an agent of this run")
    agent = named_agents().get(name)
    if agent is None:
        raise SwarmError(f"{name} is not registered in Herdr: start it first (herdr agent start)")
    if canonical(agent.get("cwd", "/")) != canonical(folder):
        raise SwarmError(f"{name} runs in {agent.get('cwd')}, not in the run's folder {folder}")
    ready = await_agent_ready(name, agent["pane_id"], folder, label=launch["prefix"])
    return {"agent": name, "paneId": ready.get("pane_id"), "status": ready.get("agent_status"), "folder": str(folder)}


def rotate_principal(run_dir: pathlib.Path, reason: str) -> dict[str, Any]:
    """Optional clean restart: start a gracefully quit Principal as generation N+1 in its pane.

    Nothing requires it; the Principal may ask for it between phases. The caller (responsible
    agent) has already quit the old session; this bumps the generation in the journal, supervisor
    registry and state ledger, starts the same configuration in the same pane, and publishes a
    replacement BOOT. Re-running resumes an interrupted restart.
    """
    root, launch = load_launch(run_dir)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise SwarmError("restart requires a nonempty reason of at most 500 characters")
    principal_name = principal_of(launch)
    journal = bootstrap_journal(root, launch)
    record = journal["responsible"]
    pane_id = record.get("principalPaneId")
    if not pane_id or not record.get("principalStarted"):
        raise SwarmError("Principal was never bootstrapped")
    live = named_agents()
    rotation = record.get("rotation")
    if rotation is None or rotation.get("completed"):
        if principal_name in live:
            raise SwarmError("Principal is still live; quit it gracefully before the restart")
        current = record.get("principalGeneration", 1)
        rotation = {"generation": current + 1, "previousGeneration": current, "reason": reason,
                    "startedAt": now(), "completed": False}
        record["rotation"] = rotation
        save_bootstrap(root, journal)
    generation = rotation["generation"]
    panes = [p for p in _workspace_panes() if p.get("pane_id") == pane_id]
    if len(panes) != 1:
        raise SwarmError("recorded Principal pane is absent")
    if canonical(panes[0].get("cwd", "/")) != canonical(launch["slice"]["worktree"]):
        raise SwarmError("recorded Principal pane has unexpected cwd")
    events = events_for(root, launch)
    state_path = ledger_path(root)
    if events.version == AUTOMATION_V3:
        marker = run_marker(root)
        library, store_module = correio_modules(marker["correio"].get("scripts"))
        store = store_module.Store(marker["correio"]["db"])
        try:
            library.bump_generation(store, marker["correio"]["space"], principal_name, to=generation)
        except Exception as exc:
            raise SwarmError(f"correio: {exc}") from exc
        finally:
            store.close()
    else:
        if state_path.exists():
            state = load_json(state_path)
            entry = state.get("agents", {}).get(principal_name)
            if not isinstance(entry, dict) or entry.get("generation") not in {generation - 1, generation}:
                raise SwarmError("state Principal generation does not match the restart")
            entry.update(generation=generation, ready=False)
            state["updatedAt"] = now()
            write_json_mutable(state_path, state)
        supervisor = load_json(root / "supervisor.json")
        supervisor["principal"] = {"agent": principal_name, "paneId": pane_id, "generation": generation}
        supervisor["updatedAt"] = now()
        write_json_mutable(root / "supervisor.json", supervisor)
    record["principalGeneration"] = generation
    save_bootstrap(root, journal)
    if principal_name in live:
        if live[principal_name].get("pane_id") != pane_id:
            raise SwarmError("live Principal is in an unexpected pane")
        agent = live[principal_name]
    else:
        harness, args = model_args(launch["models"]["principal"])
        agent = start_agent(principal_name, harness, pane_id, args, folder=canonical(launch["slice"]["worktree"]),
                            label=launch["prefix"])
    herdr("pane", "rename", pane_id, pane_title(launch, "principal"))
    key = events.journal_key
    boot_ref = rotation.get(key, "")
    if not events.exists(boot_ref):
        payload: dict[str, Any] = {
            "rolePath": str(canonical(launch["skillRoot"]) / "roles" / "principal.md"),
            "launchPath": str(root / "launch.json"), "generation": generation,
            "expectedConfiguration": launch["models"]["principal"], "ponytailPath": launch["ponytailPath"],
        }
        if events.version == AUTOMATION_V3:
            payload.update(rotationReason=rotation["reason"], previousGeneration=generation - 1,
                           reportsPath=str(root / "reports"),
                           instruction="Restarted session: read rolePath and launchPath, then resume from the "
                                       "space's projections (correio space show), the plan and the reports on disk. "
                                       "Emit AGENT_READY and wait for Responsible RESUME before acting.")
        else:
            payload.update(rotation={"reason": rotation["reason"], "previousGeneration": generation - 1,
                                     "statePath": str(state_path), "reportsPath": str(root / "reports")},
                           instruction="Restarted session: read rolePath and launchPath, then resume from statePath, "
                                       "the plan and the reports on disk. Emit AGENT_READY and wait for Responsible "
                                       "RESUME before acting.")
        boot_ref = events.send(sender=launch["responsible"]["agent"], generation=1, recipient=principal_name,
                               event_type="BOOT", payload=payload)
        rotation[key] = boot_ref
        save_bootstrap(root, journal)
    if agent.get("agent_status") in {"idle", "done"}:
        tools = "" if events.version == AUTOMATION_V3 else f"Use {root / 'runtime/swarmctl.py'} for events. "
        herdr("agent", "prompt", principal_name, boot_prompt(
            root, boot_ref, tools + f"Emit AGENT_READY as generation {generation}; act only after Responsible RESUME."))
    if events.version == AUTOMATION_V3:
        correio_member(root, principal_name, pane_id=agent.get("pane_id") or pane_id)
    rotation["completed"] = True
    record.setdefault("rotations", []).append({k: rotation[k] for k in (
        "generation", "previousGeneration", "reason", "startedAt", key)})
    save_bootstrap(root, journal)
    return {"principal": principal_name, "paneId": pane_id, "generation": generation, key: boot_ref}


TASK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
# Other checkouts of the same slice share the <prefix>- namespace under .worktrees/ (references/naming.md).
RESERVED_TASK_NAMES = {"preparation", "admission"}
REVIEW_INFIX = "review"


def task_worktree_path(launch: dict[str, Any], name: str) -> pathlib.Path:
    """``<repoPath>/.worktrees/<prefix>-<name>``."""
    return canonical(launch["worktreeRoot"]) / f"{launch['prefix']}-{name}"


def review_name(launch: dict[str, Any], task_id: str, revision: int) -> str:
    """``<task>-r<revision>``: the task ID lowercased without its ``<sliceId>-`` head; ``slice`` for a slice review."""
    task, slice_id = task_id.lower(), launch["sliceId"].lower()
    if task == slice_id:
        task = "slice"
    elif task.startswith(f"{slice_id}-"):
        task = task[len(slice_id) + 1:]
    return f"{task}-r{revision}"


def review_worktree_path(launch: dict[str, Any], name: str) -> pathlib.Path:
    """``<repoPath>/.worktrees/<prefix>-review-<task>-r<revision>``."""
    return canonical(launch["worktreeRoot"]) / f"{launch['prefix']}-{REVIEW_INFIX}-{name}"


def is_review_checkout(launch: dict[str, Any], path: pathlib.Path) -> bool:
    return (path.parent == canonical(launch["worktreeRoot"])
            and path.name.startswith(f"{launch['prefix']}-{REVIEW_INFIX}-"))


def is_task_checkout(root: pathlib.Path, path: pathlib.Path) -> bool:
    """A task worktree this run recorded in ``state.json``; the flat namespace is shared, so the name alone proves nothing."""
    state_path = ledger_path(root)
    tasks = load_json(state_path).get("tasks", {}) if state_path.is_file() else {}
    return any(task.get("worktree") == str(path) for task in tasks.values())


def _require_principal_pane(state: dict[str, Any], launch: dict[str, Any]) -> None:
    pane = os.environ.get("HERDR_PANE_ID")
    if pane and pane != state["agents"][principal_of(launch)]["paneId"]:
        raise SwarmError("task worktrees are created from the Principal pane")


def _move_into(state: dict[str, Any], journal: dict[str, Any], name: str,
               target: dict[str, str]) -> dict[str, str]:
    """Move ``name``'s pane beside the root pane of ``target``; Herdr gives the moved pane a new ID."""
    entry = state["agents"][name]
    live = named_agents().get(name)
    pane_id = live["pane_id"] if live else entry.get("paneId")
    panes = {p["pane_id"]: p for p in _workspace_panes()}
    if pane_id not in panes:
        raise SwarmError(f"pane of {name} is absent")
    pane = panes[pane_id]
    if pane.get("workspace_id") != target["workspaceId"]:
        pane = herdr("pane", "move", pane_id, "--tab", target["tabId"], "--split", "right",
                     "--target-pane", target["rootPaneId"], "--no-focus")["move_result"]["pane"]
    resource = {"paneId": pane["pane_id"], "tabId": pane["tab_id"], "workspaceId": pane["workspace_id"]}
    state["resourceOwnership"].pop(pane_id, None)
    state["resourceOwnership"][resource["paneId"]] = name
    entry.update(resource)
    journal["principal"].setdefault("layout", {})[name] = resource
    return resource


def _forget_closed_workspaces(state: dict[str, Any]) -> None:
    """Clear task ``workspaceId``s whose Herdr workspace is gone (Herdr closes a workspace left without panes)."""
    live = {p.get("workspace_id") for p in _workspace_panes()}
    for task in state["tasks"].values():
        if task.get("workspaceId") and task["workspaceId"] not in live:
            task["workspaceId"] = None


def task_worktree(root: pathlib.Path, launch: dict[str, Any], task_id: str, name: str, owner: str,
                  base: str) -> dict[str, Any]:
    """Create/adopt ``task/<prefix>/<name>`` in its own Herdr workspace, leaving no pane without an agent.

    A coder's pane moves into the workspace and the root shell there is closed. A Principal task's
    workspace is closed (the Principal works from the slice workspace); the checkout stays and a
    rerun keeps it closed, while a rerun for a coder reopens it with ``herdr worktree open``.
    Only idle shells are closed; a busy one is kept, reported, and retried by the next rerun.
    """
    if not TASK_ID_RE.fullmatch(task_id) or not TASK_NAME_RE.fullmatch(name):
        raise SwarmError("invalid task ID or worktree name")
    if name in RESERVED_TASK_NAMES or name == REVIEW_INFIX or name.startswith(f"{REVIEW_INFIX}-"):
        raise SwarmError(f"task worktree name is reserved for another checkout of the slice: {name}")
    if owner not in {principal_of(launch), *coder_names(launch)}:
        raise SwarmError(f"task owner is not an implementer of this run: {owner}")
    if not SHA_RE.fullmatch(base):
        raise SwarmError("task base must be a full lowercase Git SHA")
    state_path = ledger_path(root)
    if not state_path.is_file():
        raise SwarmError(f"{state_path.name} is missing: run bootstrap principal first")
    state = load_json(state_path)
    _require_principal_pane(state, launch)
    path = task_worktree_path(launch, name)
    task = state["tasks"].setdefault(task_id, {})
    if task.get("worktree") not in {None, str(path)}:
        raise SwarmError(f"task {task_id} already has another worktree")
    own_task = owner == principal_of(launch)
    worktree = ensure_worktree(canonical(launch["repoPath"], exists=True), path,
                               f"task/{launch['prefix']}/{name}", base, path.name,
                               allow_advanced_adoption=task.get("worktree") == str(path),
                               open_existing=not own_task)
    task.update(worktree=str(path), branch=worktree["branch"], workspaceId=worktree["workspaceId"], owner=owner)
    task.setdefault("baseSha", base)
    if worktree["fresh"]:
        task["shellPaneId"] = worktree["rootPaneId"]  # journaled before it is closed
    state["updatedAt"] = now()
    write_json_mutable(state_path, state)
    placed, closed_panes, kept, closed_workspace = None, [], [], None
    if not own_task:
        journal = bootstrap_journal(root, launch)
        placed = _move_into(state, journal, owner, worktree)
        correio_member(root, owner, pane_id=placed["paneId"], workspace_id=placed["workspaceId"])
        _forget_closed_workspaces(state)
        save_bootstrap(root, journal)
        shell = task.get("shellPaneId")
        if shell in {p["pane_id"] for p in _workspace_panes(task["workspaceId"])} \
                and shell not in state["resourceOwnership"]:
            refusal = close_idle_pane(shell)
            if refusal:
                kept.append(refusal)
            else:
                closed_panes.append(shell)
        if not kept:
            task.pop("shellPaneId", None)
    elif task["workspaceId"]:
        outcome = close_idle_workspace(task["workspaceId"])
        kept, closed_workspace = outcome["keptPanes"], outcome["closedWorkspace"]
        if closed_workspace:
            task["workspaceId"] = None
            task.pop("shellPaneId", None)
    else:
        task.pop("shellPaneId", None)
    state["updatedAt"] = now()
    write_json_mutable(state_path, state)
    return {"taskId": task_id, "owner": owner, "worktree": worktree, "ownerPane": placed,
            "closedPanes": closed_panes, "closedWorkspace": closed_workspace, "keptPanes": kept}


def close_worktree(root: pathlib.Path, launch: dict[str, Any], path_value: pathlib.Path) -> dict[str, Any]:
    """Close the Herdr workspace of a run task or review checkout whose panes are all idle shells.

    Plain ``herdr workspace close``, never ``--group``: the checkout and branch stay, and
    ``herdr worktree open`` (or a ``worktree task``/``review`` rerun) reopens it. Fails closed while
    any pane there hosts an agent or a foreground command.
    """
    repo = canonical(launch["repoPath"], exists=True)
    path = canonical(path_value)
    if not (is_review_checkout(launch, path) or is_task_checkout(root, path)):
        raise SwarmError("only this run's task or review checkouts can be closed")
    if path not in git_worktrees(repo):
        raise SwarmError(f"not a registered worktree: {path}")
    state_path = ledger_path(root)
    state = load_json(state_path) if state_path.is_file() else None
    tasks = [t for t in (state or {}).get("tasks", {}).values() if t.get("worktree") == str(path)]
    if tasks:
        _require_principal_pane(state, launch)
    workspace_id = (herdr_worktree(repo, path) or {}).get("open_workspace_id")
    result = {"path": str(path), "closedWorkspace": None, "keptPanes": []}
    if workspace_id:
        result.update(close_idle_workspace(workspace_id, strict=True))
    if tasks:
        for task in tasks:
            task["workspaceId"] = None
            task.pop("shellPaneId", None)
        state["updatedAt"] = now()
        write_json_mutable(state_path, state)
    return result


def review_worktree(root: pathlib.Path, launch: dict[str, Any], task_id: str, revision: int,
                    sha: str) -> dict[str, Any]:
    """Detached, clean checkout of exactly ``sha``, opened in Herdr (which cannot create detached ones)."""
    if not TASK_ID_RE.fullmatch(task_id) or not isinstance(revision, int) or revision < 1:
        raise SwarmError("invalid task ID or revision")
    if not SHA_RE.fullmatch(sha):
        raise SwarmError("candidate must be a full lowercase Git SHA")
    repo = canonical(launch["repoPath"], exists=True)
    require_main_checkout(repo)
    run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"])
    path = review_worktree_path(launch, review_name(launch, task_id, revision))
    existing = git_worktrees(repo).get(path)
    if existing is None:
        if path.exists():
            raise SwarmError(f"unrecorded worktree path already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "-C", str(repo), "worktree", "add", "--detach", str(path), sha], timeout=120)
    elif "detached" not in existing or existing.get("HEAD") != sha:
        raise SwarmError("existing review checkout is not detached at the candidate")
    if run(["git", "-C", str(path), "status", "--porcelain"]).stdout.strip():
        raise SwarmError("review checkout is dirty")
    # The reviewer closes each review workspace after its verdict; close any it left open and idle.
    closed = []
    for entry in herdr("worktree", "list", "--cwd", str(repo)).get("worktrees", []):
        other, workspace_id = canonical(entry["path"]), entry.get("open_workspace_id")
        if workspace_id and other != path and is_review_checkout(launch, other):
            if close_idle_workspace(workspace_id)["closedWorkspace"]:
                closed.append(workspace_id)
    return {"action": "adopt" if existing else "create", "path": str(path), "head": sha, "detached": True,
            **open_worktree(repo, path, path.name), "closedWorkspaces": closed}


def remove_worktree(root: pathlib.Path, launch: dict[str, Any], path_value: pathlib.Path,
                    merged_into: str) -> dict[str, Any]:
    """``herdr worktree remove`` for a clean run checkout whose commits ``merged_into`` already holds.

    Never forced. Refuses while an agent lives in the workspace: removal closes it with its panes.
    The branch is kept; deleting it is a separate decision.
    """
    repo = canonical(launch["repoPath"], exists=True)
    path = canonical(path_value)
    if not (path == canonical(launch["slice"]["worktree"]) or is_review_checkout(launch, path)
            or is_task_checkout(root, path)):
        raise SwarmError("only this run's worktrees can be removed")
    existing = git_worktrees(repo).get(path)
    if existing is None:
        raise SwarmError(f"not a registered worktree: {path}")
    if run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"]).stdout.strip():
        raise SwarmError("worktree has changes or untracked files; nothing is forced")
    run(["git", "-C", str(repo), "rev-parse", "--verify", f"{merged_into}^{{commit}}"])
    head = existing["HEAD"]
    held = run(["git", "-C", str(repo), "merge-base", "--is-ancestor", head, merged_into], check=False)
    if held.returncode:
        raise SwarmError(f"worktree head {head} is not contained in {merged_into}")
    entry = herdr_worktree(repo, path) or {}
    workspace_id = entry.get("open_workspace_id") or open_worktree(repo, path, path.name)["workspaceId"]
    residents = [a.get("name") or a.get("pane_id") for a in herdr("agent", "list").get("agents", [])
                 if a.get("workspace_id") == workspace_id]
    if residents:
        raise SwarmError(f"agents still live in workspace {workspace_id}: {residents}")
    herdr("worktree", "remove", "--workspace", workspace_id, timeout=120)
    return {"removed": str(path), "workspaceId": workspace_id, "head": head,
            "branchKept": existing.get("branch", "").removeprefix("refs/heads/") or None}


def start_supervisor(root: pathlib.Path) -> dict[str, Any]:
    status_path = root / "supervision" / "status.json"
    process_path = root / "supervision" / "process.json"
    start_lock_path = root / "supervision" / "swarmd-start.lock"

    def owned_pid(record_path: pathlib.Path) -> int | None:
        if not record_path.exists():
            return None
        pid = load_json(record_path).get("pid")
        if not isinstance(pid, int):
            return None
        try:
            os.kill(pid, 0)
            cmdline = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            expected = str(root / "runtime" / "swarmd.py").encode()
            return pid if expected in cmdline and str(root).encode() in cmdline else None
        except (ProcessLookupError, FileNotFoundError, PermissionError):
            return None

    with start_lock_path.open("a+b") as start_lock:
        fcntl.flock(start_lock, fcntl.LOCK_EX)
        for record_path in (status_path, process_path):
            pid = owned_pid(record_path)
            if pid is not None:
                return {"action": "adopt", "pid": pid, "statusPath": str(status_path)}
        log = open(root / "supervision" / "swarmd.log", "ab", buffering=0)
        process = subprocess.Popen([sys.executable, str(root / "runtime" / "swarmd.py"),
                                    "--run-dir", str(root)], stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True, close_fds=True)
        log.close()
        write_json_mutable(process_path, {"schemaVersion": 1, "runId": load_json(root / "launch.json")["runId"],
                                          "pid": process.pid, "startedAt": now()})
        return {"action": "start", "pid": process.pid, "statusPath": str(status_path)}


