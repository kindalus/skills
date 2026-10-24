#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("swarmctl", HERE / "swarmctl.py")
assert SPEC and SPEC.loader
swarmctl = importlib.util.module_from_spec(SPEC)
sys.modules["swarmctl"] = swarmctl
SPEC.loader.exec_module(swarmctl)
import swarmbootstrap
import swarmcore


FAKE_HERDR = r'''#!/usr/bin/env python3
import fcntl,json,os,pathlib,subprocess,sys
state_path=pathlib.Path(os.environ['FAKE_HERDR_STATE']);log_path=pathlib.Path(os.environ['FAKE_HERDR_LOG'])
state_path.parent.mkdir(parents=True,exist_ok=True)
# A new pane's shell initializes for WARMUP process-info reads: it runs init children and has drawn
# nothing (revision 0), and agent start answers agent_pane_busy. START_BUSY extra busy answers
# follow on a settled pane; ROOT_BUSY leaves each worktree root pane running a foreground command.
WARMUP=int(os.environ.get('FAKE_HERDR_WARMUP','2'));START_BUSY=int(os.environ.get('FAKE_HERDR_START_BUSY','0'))
ROOT_BUSY=os.environ.get('FAKE_HERDR_ROOT_BUSY')=='1'
def opt(name,default=None):
    return args[args.index(name)+1] if name in args else default
def log(entry):
    with log_path.open('a') as out: out.write(json.dumps(entry)+'\n')
def fail(code,message=''):
    print(json.dumps({'error':{'code':code,'message':message,'args':args}}),file=sys.stderr);raise SystemExit(1)
def git(*argv):
    return subprocess.run(['git',*argv],text=True,capture_output=True)
with open(str(state_path)+'.lock','a+') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    try: state=json.loads(state_path.read_text())
    except Exception: state={'counter':0,'tabs':{},'panes':{},'agents':{}}
    for key in ('workspaces','worktrees'): state.setdefault(key,{})
    args=sys.argv[1:]
    def new(prefix):
        state['counter']+=1;return prefix+str(state['counter'])
    def result(value):
        state_path.write_text(json.dumps(state));print(json.dumps({'id':'fake','result':value}));raise SystemExit(0)
    def in_workspace(items):
        ws=opt('--workspace');return [i for i in items if ws is None or i.get('workspace_id')==ws]
    def mkpane(tab,ws,cwd,busy=False):
        pane=new('p');p={'pane_id':pane,'tab_id':tab,'workspace_id':ws,'cwd':cwd,'agent_status':'idle',
                         'warmup':WARMUP,'start_busy':START_BUSY,'shell_pid':10000+state['counter']}
        if busy: p['busy_command']='sleep'
        state['panes'][pane]=p;return p
    def occupant(pane_id):
        return next((a for a in state['agents'].values() if a.get('pane_id')==pane_id),None)
    def drop_workspace_if_empty(ws):
        if not any(t['workspace_id']==ws for t in state['tabs'].values()):
            workspace=state['workspaces'].pop(ws,None)
            if workspace: state['worktrees'].pop(workspace['path'],None)
    def drop_pane(pane_id):
        old=state['panes'].pop(pane_id);tab=state['tabs'][old['tab_id']];tab['pane_count']-=1
        state['agents']={k:v for k,v in state['agents'].items() if v.get('pane_id')!=pane_id}
        if tab['pane_count']==0:
            state['tabs'].pop(tab['tab_id']);drop_workspace_if_empty(old['workspace_id'])
        return old
    def open_workspace(repo,path,label):
        ws=new('ws');tab=new('t');p=mkpane(tab,ws,path,ROOT_BUSY)
        state['workspaces'][ws]={'workspace_id':ws,'label':label,'repo':repo,'path':path,'root':p['pane_id']}
        state['tabs'][tab]={'tab_id':tab,'workspace_id':ws,'label':'1','pane_count':1}
        state['worktrees'][path]=ws
        return {'workspace':state['workspaces'][ws],'tab':state['tabs'][tab],'root_pane':p}
    def worktree_entries(repo):
        out=git('-C',repo,'worktree','list','--porcelain').stdout;entries=[];block={}
        for line in out.splitlines()+['']:
            if not line:
                if block:
                    path=str(pathlib.Path(block['worktree']).resolve())
                    entries.append({'path':path,'branch':block.get('branch','').replace('refs/heads/','') or None,
                                    'is_detached':'detached' in block,'open_workspace_id':state['worktrees'].get(path)})
                block={}
            else:
                key,_,value=line.partition(' ');block[key]=value
        return entries
    if args[:2]==['status','server']:
        print('status: running');raise SystemExit(0)
    if args[:2]==['agent','list']:
        result({'agents':list(state['agents'].values()),'type':'agent_list'})
    if args[:2]==['tab','list']:
        result({'tabs':in_workspace(state['tabs'].values()),'type':'tab_list'})
    if args[:2]==['pane','list']:
        result({'panes':in_workspace(state['panes'].values()),'type':'pane_list'})
    if args[:2]==['pane','get']:
        p=state['panes'].get(args[2])
        if p is None: fail('pane_not_found',args[2])
        a=occupant(p['pane_id'])
        result({'pane':dict(p,agent=a['agent'] if a else None,revision=0 if p.get('warmup') else 1),'type':'pane_info'})
    if args[:2]==['pane','process-info']:
        p=state['panes'].get(opt('--pane'))
        if p is None: fail('pane_not_found',opt('--pane'))
        shell=p['shell_pid'];procs=[{'name':'zsh','pid':shell}];group=shell;a=occupant(p['pane_id'])
        if p.get('warmup'):
            p['warmup']-=1;procs.append({'name':'conda','pid':shell+1})
        elif a:
            group=shell+2;procs=[{'name':a['agent'],'pid':group}]
        elif p.get('busy_command'):
            group=shell+3;procs=[{'name':p['busy_command'],'pid':group}]
        result({'process_info':{'pane_id':p['pane_id'],'shell_pid':shell,'foreground_process_group_id':group,
                                'foreground_processes':procs},'type':'pane_process_info'})
    if args[:2]==['tab','create']:
        tab=new('t');workspace=opt('--workspace');p=mkpane(tab,workspace,opt('--cwd'))
        t={'tab_id':tab,'workspace_id':workspace,'label':opt('--label'),'pane_count':1}
        state['tabs'][tab]=t;result({'tab':t,'root_pane':p})
    if args[:2]==['pane','split']:
        src=state['panes'][args[2]];p=mkpane(src['tab_id'],src['workspace_id'],opt('--cwd'))
        state['tabs'][src['tab_id']]['pane_count']+=1;result({'pane':p})
    if args[:2]==['pane','move']:
        old_id=args[2];old=state['panes'].pop(old_id);tab=state['tabs'][opt('--tab')];pane=new('p')
        p=dict(old,pane_id=pane,tab_id=tab['tab_id'],workspace_id=tab['workspace_id'])
        state['panes'][pane]=p;tab['pane_count']+=1;state['tabs'][old['tab_id']]['pane_count']-=1
        if state['tabs'][old['tab_id']]['pane_count']==0:
            state['tabs'].pop(old['tab_id']);drop_workspace_if_empty(old['workspace_id'])
        for agent in state['agents'].values():
            if agent.get('pane_id')==old_id: agent.update(pane_id=pane,tab_id=p['tab_id'],workspace_id=p['workspace_id'])
        log({'command':'move','args':args})
        result({'move_result':{'pane':p,'previous_pane_id':old_id},'type':'pane_move'})
    if args[:2]==['pane','close']:
        if args[2] not in state['panes']: fail('pane_not_found',args[2])
        log({'command':'pane-close','args':args});drop_pane(args[2]);result({'type':'ok'})
    if args[:2]==['workspace','close']:
        ws=args[2]
        if ws not in state['workspaces']: fail('workspace_not_found',ws)
        log({'command':'workspace-close','args':args})
        for pane_id in [k for k,v in state['panes'].items() if v['workspace_id']==ws]: drop_pane(pane_id)
        result({'type':'ok'})
    if args[:2]==['worktree','list']:
        result({'worktrees':worktree_entries(opt('--cwd')),'type':'worktree_list'})
    if args[:2]==['worktree','create']:
        repo=opt('--cwd');branch=opt('--branch');path=opt('--path')
        exists=git('-C',repo,'show-ref','--verify','refs/heads/'+branch).returncode==0
        argv=['-C',repo,'worktree','add',path,branch] if exists else ['-C',repo,'worktree','add','-b',branch,path,opt('--base','HEAD')]
        done=git(*argv)
        if done.returncode: fail('worktree_create_failed',done.stderr)
        log({'command':'worktree-create','args':args})
        path=str(pathlib.Path(path).resolve())
        result(dict(open_workspace(repo,path,opt('--label')),type='worktree_created'))
    if args[:2]==['worktree','open']:
        repo=opt('--cwd');path=str(pathlib.Path(opt('--path')).resolve())
        if not any(e['path']==path for e in worktree_entries(repo)): fail('worktree_not_found')
        ws=state['worktrees'].get(path)
        if ws in state['workspaces']:
            # Herdr answers with the workspace's first pane once the original root pane is closed.
            workspace=state['workspaces'][ws];root=state['panes'].get(workspace['root']) or next(
                p for p in state['panes'].values() if p['workspace_id']==ws)
            result({'already_open':True,'workspace':workspace,'tab':state['tabs'][root['tab_id']],'root_pane':root,'type':'worktree_opened'})
        log({'command':'worktree-open','args':args})
        result(dict(open_workspace(repo,path,opt('--label')),already_open=False,type='worktree_opened'))
    if args[:2]==['worktree','remove']:
        ws=opt('--workspace');workspace=state['workspaces'].get(ws)
        if workspace is None: fail('not_linked_worktree')
        done=git('-C',workspace['repo'],'worktree','remove',workspace['path'])
        if done.returncode: fail('dirty_worktree_requires_force',done.stderr)
        log({'command':'worktree-remove','args':args})
        state['workspaces'].pop(ws);state['worktrees'].pop(workspace['path'],None)
        for table in ('tabs','panes'):
            state[table]={k:v for k,v in state[table].items() if v.get('workspace_id')!=ws}
        state['agents']={k:v for k,v in state['agents'].items() if v.get('workspace_id')!=ws}
        result({'path':workspace['path'],'workspace_id':ws,'forced':False,'type':'worktree_removed'})
    if args[:2]==['agent','start']:
        name=args[2];pane=opt('--pane');p=state['panes'][pane]
        if p.get('warmup') or p.get('start_busy') or p.get('busy_command') or occupant(pane):
            if p.get('start_busy') and not p.get('warmup'): p['start_busy']-=1
            log({'command':'start-busy','args':args})
            state_path.write_text(json.dumps(state))
            fail('agent_pane_busy','agent target pane '+pane+' is not an available shell')
        log({'command':'start','args':args})
        a={'name':name,'agent':opt('--kind'),'agent_status':'idle','interactive_ready':True,'pane_id':pane,'tab_id':p['tab_id'],'workspace_id':p['workspace_id'],'cwd':p['cwd'],'state_change_seq':1}
        state['agents'][name]=a;result({'agent':a,'type':'agent_started'})
    if args[:2]==['agent','prompt']:
        name=args[2];message=args[3]
        agent=state['agents'].get(name) or next((a for a in state['agents'].values() if a.get('pane_id')==name),None)
        if agent is None: fail('agent_not_found',name)
        log({'command':'prompt','target':name,'message':message})
        result({'agent':agent,'type':'agent_prompted'})
    if args[:2]==['notification','show']:
        log({'command':'notify','args':args})
        result({'type':'notification_shown'})
    fail('unsupported')
'''


class SwarmTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = pathlib.Path(tempfile.mkdtemp(prefix="swarmctl-test-")).resolve()
        self.repo = self.temp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Swarm Test"], cwd=self.repo, check=True)
        (self.repo / "spec.md").write_text("# spec\n")
        (self.repo / "process.md").write_text("# process\n")
        (self.repo / "tracked.txt").write_text("original\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        self.base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.run_id = str(uuid.uuid4())
        self.run_dir = self.temp / "state" / self.run_id
        self.worktree_root = self.temp / "worktrees" / self.run_id
        ponytail_path = self.temp / "ponytail" / "SKILL.md"
        ponytail_path.parent.mkdir()
        ponytail_path.write_text("# Ponytail test fixture\n")
        self.contract = {
            "runId": self.run_id, "prefix": "t123", "sliceId": "T123",
            "specPath": str(self.repo / "spec.md"), "repoPath": str(self.repo), "baseSha": self.base,
            "slice": {"branch": f"swarm/t123-{self.run_id[:8]}",
                      "worktree": str(self.worktree_root / "slice")},
            "responsible": {"agent": "orchestrator", "paneId": "p0", "workspaceId": "w1", "session": "test"},
            "worktreeRoot": str(self.worktree_root), "runDir": str(self.run_dir),
            "skillRoot": str(HERE.parent),
            "ponytailPath": str(ponytail_path),
            "roster": {"coders": 0},
            "models": {"principal": "pi ollama/example high", "reviewer": "claude claude-opus-5-5 high"},
            "processPaths": [str(self.repo / "process.md")],
        }
        self.contract_path = self.temp / "contract.json"
        self.contract_path.write_text(json.dumps(self.contract))
        self.fake_bin = self.temp / "bin"
        self.fake_bin.mkdir()
        (self.fake_bin / "herdr").write_text(FAKE_HERDR)
        os.chmod(self.fake_bin / "herdr", 0o755)
        self.fake_state = self.temp / "fake-herdr.json"
        self.fake_log = self.temp / "fake-herdr.log"
        self.fake_state.write_text(json.dumps({"counter": 0, "tabs": {}, "panes": {
            "p0": {"pane_id": "p0", "tab_id": "t0", "workspace_id": "w1", "cwd": str(self.repo),
                   "agent_status": "idle"}}, "agents": {
            "orchestrator": {"agent": "pi", "agent_status": "idle",
                              "interactive_ready": True, "pane_id": "p0", "tab_id": "t0",
                              "workspace_id": "w1", "cwd": str(self.repo), "state_change_seq": 1}}}))
        self.fake_log.write_text("")
        self.old_env = os.environ.copy()
        self.old_timing = {name: getattr(swarmbootstrap, name, None)
                           for name in ("SHELL_POLL_SECONDS", "SHELL_TIMEOUT_SECONDS")}
        swarmbootstrap.SHELL_POLL_SECONDS = 0  # the fake's shells settle by reads, not by time
        os.environ.update(PATH=str(self.fake_bin) + os.pathsep + self.old_env["PATH"],
                          FAKE_HERDR_STATE=str(self.fake_state), FAKE_HERDR_LOG=str(self.fake_log),
                          HERDR_ENV="1")

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)
        for name, value in self.old_timing.items():
            setattr(swarmbootstrap, name, value)
        shutil.rmtree(self.temp, ignore_errors=True)

    def init(self) -> tuple[pathlib.Path, dict]:
        swarmctl.init_run(self.contract_path, self.run_dir)
        return swarmctl.load_launch(self.run_dir)

    def write_contract(self) -> None:
        self.contract_path.write_text(json.dumps(self.contract))

    def legacy_coders(self) -> None:
        """The contract of a run launched before 2.4.0 with two coders."""
        self.contract["roster"] = {"coders": 2}
        self.contract["models"]["coders"] = "pi ollama/coder medium"
        self.write_contract()

    @contextlib.contextmanager
    def pre_240_creation(self):
        """Creates a run as the runtime before 2.4.0 did, which accepted coders. Only creation lifts
        the 2.4.0 gate on new contracts; afterwards the test drives the run through reload paths."""
        self.legacy_coders()
        with mock.patch.object(swarmcore, "require_solo_team", lambda value: None):
            yield

    def legacy_init(self) -> tuple[pathlib.Path, dict]:
        with self.pre_240_creation():
            return self.init()

    def legacy_team(self) -> tuple[dict, pathlib.Path, dict]:
        with self.pre_240_creation():
            return self.bootstrap_team()

    def grant(self, root: pathlib.Path, name: str = "t01-r1") -> dict:
        path = root / "reports" / "t123-principal" / "grants" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"taskId": "T01", "facts": [], "name": name}))
        return {"grantPath": str(path), "grantSha256": swarmctl.sha256_file(path)}

    def authorize_children(self) -> tuple[dict, pathlib.Path]:
        responsible = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                                     no_supervisor=True)
        root, launch = swarmctl.load_launch(self.run_dir)
        authorization = swarmctl.send_event(root, launch, sender="orchestrator", generation=1,
                                            recipient="t123-principal", event_type="RESUME",
                                            payload={"bootstrapChildrenAuthorized": True})
        return responsible, authorization

    def principal_pane(self, pane_id: str):
        old_pane = os.environ.get("HERDR_PANE_ID")
        os.environ["HERDR_PANE_ID"] = pane_id

        @contextlib.contextmanager
        def scope():
            try:
                yield
            finally:
                if old_pane is None:
                    os.environ.pop("HERDR_PANE_ID", None)
                else:
                    os.environ["HERDR_PANE_ID"] = old_pane
        return scope()

    def quit_agent(self, name: str) -> None:
        fake = json.loads(self.fake_state.read_text())
        agent = fake["agents"].pop(name)
        fake["panes"][agent["pane_id"]]["warmup"] = 1  # the shell redraws its prompt
        self.fake_state.write_text(json.dumps(fake))

    def log_entries(self, command: str) -> list[dict]:
        return [entry for entry in map(json.loads, self.fake_log.read_text().splitlines())
                if entry["command"] == command]

    def test_doctor_cli_smoke(self) -> None:
        result = subprocess.run([sys.executable, str(HERE / "swarmctl.py"), "doctor",
                                 "--contract", str(self.contract_path), "--run-dir", str(self.run_dir),
                                 "--skip-herdr", "--skip-model-catalog"], env=os.environ.copy(), text=True,
                                capture_output=True, check=True)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_model_triple_rejects_shell_input_and_unsupported_effort(self) -> None:
        self.assertEqual(swarmctl.parse_model_triple("pi ollama/model high"), ("pi", "ollama/model", "high"))
        self.assertEqual(swarmctl.parse_model_triple("claude claude-opus-5-5 high"),
                         ("claude", "claude-opus-5-5", "high"))
        for raw in ("pi model;touch high", "pi model impossible", "claude claude-opus-5-5 minimal",
                    "claude -x high", "codex gpt-6.1-sol max", "codex gpt-6.1-sol off", "codex -m high"):
            with self.subTest(raw=raw):
                with self.assertRaises(swarmctl.SwarmError):
                    swarmctl.parse_model_triple(raw)

    def test_claude_reviewer_launch_arguments(self) -> None:
        self.assertEqual(swarmcore.model_args("claude claude-opus-5-5 high"),
                         ("claude", ["--model", "claude-opus-5-5", "--effort", "high",
                                     "--dangerously-skip-permissions"]))
        self.assertEqual(swarmcore.model_args("pi openai-codex/gpt-6.1-sol medium"),
                         ("pi", ["--model", "openai-codex/gpt-6.1-sol", "--thinking", "medium"]))

    def test_codex_principal_launch_arguments(self) -> None:
        self.assertEqual(swarmctl.parse_model_triple("codex gpt-6.1-sol high"), ("codex", "gpt-6.1-sol", "high"))
        self.assertEqual(swarmcore.model_args("codex gpt-6.1-sol high"),
                         ("codex", ["--model", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"',
                                    "--dangerously-bypass-approvals-and-sandbox"]))
        for effort in ("minimal", "low", "medium", "xhigh"):
            with self.subTest(effort=effort):
                self.assertIn(f'model_reasoning_effort="{effort}"',
                              swarmcore.model_args(f"codex gpt-6.1-sol {effort}")[1])

    def test_codex_principal_with_claude_reviewer_is_a_valid_launch(self) -> None:
        self.contract["models"].update(principal="codex gpt-6.1-sol high")
        swarmctl.validate_launch(self.contract, self.run_dir)
        for reviewer in ("codex gpt-6.1-sol high", "pi openai-codex/gpt-6.1-sol high", "codex o9 high"):
            with self.subTest(reviewer=reviewer):
                with self.assertRaisesRegex(swarmctl.SwarmError, "different model family"):
                    swarmctl.validate_launch({**self.contract, "models": {**self.contract["models"],
                                                                         "reviewer": reviewer}}, self.run_dir)

    def test_reviewer_must_be_another_model_family(self) -> None:
        family = swarmcore.model_family
        self.assertEqual(family("claude opus high"), "anthropic")
        self.assertEqual(family("pi anthropic/claude-opus-5-5 high"), "anthropic")
        self.assertEqual(family("pi openai-codex/gpt-6.1-sol high"), "openai")
        self.assertEqual(family("codex gpt-6.1-sol high"), "openai")
        self.assertEqual(family("codex o9 high"), "openai")  # the harness names the family
        self.assertEqual(family("pi google/gemini-3-pro high"), "google")
        self.assertEqual(family("pi ollama/example high"), "ollama")
        same = [{"reviewer": "pi ollama/reviewer xhigh"},
                {"principal": "pi anthropic/claude-opus-5-5 high"}]
        for change in same:
            with self.subTest(change=change):
                with self.assertRaisesRegex(swarmctl.SwarmError, "different model family"):
                    swarmctl.validate_launch({**self.contract, "models": {**self.contract["models"], **change}},
                                             self.run_dir)
        swarmctl.validate_launch(self.contract, self.run_dir)
        legacy = {**self.contract, "roster": {"coders": 1},
                  "models": {**self.contract["models"], "coders": "pi openrouter/claude-sonnet-5 medium"}}
        with self.assertRaisesRegex(swarmctl.SwarmError, "different model family"):
            swarmctl.validate_launch(legacy, self.run_dir)  # a reloaded launch.json from before 2.4.0

    FALLBACK = "codex gpt-6.1-sol high"

    def openai_team(self) -> tuple[pathlib.Path, dict]:
        """The default team: OpenAI implementers, so the quota fallback reviewer is same-family."""
        self.contract["models"].update(principal="codex gpt-6.1-sol high")
        self.write_contract()
        return self.init()

    def model_error(self, root: pathlib.Path, launch: dict, *, role: str = "reviewer",
                    classification: str = "quota-exhausted", sender: str = "t123-principal",
                    recipient: str = "orchestrator") -> str:
        path = swarmctl.send_event(root, launch, sender=sender, generation=1, recipient=recipient,
                                   event_type="MODEL_ERROR",
                                   payload={"role": role, "classification": classification})
        return path.stem

    def replace_reviewer(self, root: pathlib.Path, launch: dict, configuration: str,
                         **marker: str) -> pathlib.Path:
        payload = {"role": "reviewer", "configuration": configuration,
                   "incidentId": marker.get("reviewerFallback", "i1"), **marker}
        return swarmctl.send_event(root, launch, sender="orchestrator", generation=1,
                                   recipient="t123-principal", event_type="MODEL_REPLACE", payload=payload)

    def test_reviewer_quota_fallback_accepts_the_exact_pair_with_its_marker(self) -> None:
        root, launch = self.openai_team()
        for sender, recipient in (("t123-principal", "orchestrator"), ("t123-reviewer", "t123-principal")):
            with self.subTest(observer=sender):
                incident = self.model_error(root, launch, sender=sender, recipient=recipient)
                event = self.replace_reviewer(root, launch, self.FALLBACK, reviewerFallback=incident)
                pending = swarmctl.pending_events(root, launch, "t123-principal")
                self.assertIn(str(event), [item["path"] for item in pending["pending"]])
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
            swarmctl.send_event(root, launch, sender="orchestrator", generation=1,
                                recipient="t123-principal", event_type="MODEL_REPLACE",
                                payload={"role": "coders", "configuration": self.FALLBACK,
                                         "incidentId": incident, "reviewerFallback": incident})
        not_quota = [self.model_error(root, launch, classification="rate-limited"),
                     self.model_error(root, launch, role="coders"), str(uuid.uuid4()), "../x"]
        for marker in not_quota:
            with self.subTest(marker=marker):
                with self.assertRaises(swarmctl.SwarmError):
                    self.replace_reviewer(root, launch, self.FALLBACK, reviewerFallback=marker)
        with self.assertRaisesRegex(swarmctl.SwarmError, "must equal the incidentId"):
            swarmctl.send_event(root, launch, sender="orchestrator", generation=1,
                                recipient="t123-principal", event_type="MODEL_REPLACE",
                                payload={"role": "reviewer", "configuration": self.FALLBACK,
                                         "incidentId": "other", "reviewerFallback": incident})

    def test_same_family_reviewer_stays_rejected_outside_the_quota_fallback(self) -> None:
        root, launch = self.openai_team()
        for contract in ({**self.contract, "models": {**self.contract["models"], "reviewer": self.FALLBACK}},
                         {**self.contract, "models": {**self.contract["models"], "reviewer": self.FALLBACK},
                          "reviewerFallback": str(uuid.uuid4())}):
            with self.subTest(contract=sorted(contract)):
                with self.assertRaisesRegex(swarmctl.SwarmError, "different model family"):
                    swarmctl.validate_launch(contract, self.run_dir)
        for configuration in ("pi openai-codex/gpt-6.1-sol high", "pi openrouter/gpt-6.1-sol high",
                              "codex gpt-6-astra medium"):
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(swarmctl.SwarmError, "different model family"):
                    self.replace_reviewer(root, launch, configuration)
        self.assertTrue(self.replace_reviewer(root, launch, "claude claude-opus-5-5 high").is_file())

    def test_reloaded_roster_still_reads_one_principal_one_reviewer_and_up_to_two_coders(self) -> None:
        # roster() and validate_launch also reload launch.json of runs launched before 2.4.0.
        roster = swarmbootstrap.roster
        self.assertEqual(roster({}), "")
        self.assertEqual(roster(self.contract), "")
        self.assertEqual(roster({"roster": {"principal": 1, "reviewer": 1, "coders": 1}}), "a")
        self.assertEqual(roster({"roster": {"coders": 2}}), "ab")
        invalid = [{"coders": 3}, {"coders": -1}, {"coders": 1.0}, {"coders": "1"}, {"coders": True},
                   {"reviewer": 2}, {"reviewer": 0}, {"principal": 2}, {"reviewers": 1, "coders": 2},
                   [1, 2], None]
        for value in invalid:
            with self.subTest(roster=value):
                with self.assertRaises(swarmctl.SwarmError):
                    roster({"roster": value})
                with self.assertRaises(swarmctl.SwarmError):
                    swarmctl.validate_launch({**self.contract, "roster": value}, self.run_dir)
        with self.assertRaisesRegex(swarmctl.SwarmError, "tier was removed"):
            swarmctl.validate_launch({**self.contract, "tier": 2}, self.run_dir)
        models = self.contract["models"]
        legacy_models = {**models, "coders": "pi ollama/coder medium"}
        swarmctl.validate_launch(self.contract, self.run_dir)
        swarmctl.validate_launch({k: v for k, v in self.contract.items() if k != "roster"}, self.run_dir)
        swarmctl.validate_launch({**self.contract, "roster": {"coders": 2}, "models": legacy_models}, self.run_dir)
        for change in ({"roster": {"coders": 2}}, {"models": legacy_models},
                       {"models": {**models, "reviewers": models["reviewer"]}}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(swarmctl.SwarmError, "models must contain exactly"):
                    swarmctl.validate_launch({**self.contract, **change}, self.run_dir)

    def test_new_contracts_are_always_principal_and_reviewer(self) -> None:
        models = self.contract["models"]
        coders = {"coders": "pi ollama/coder medium"}
        rejected = [({"roster": {"coders": 1}, "models": {**models, **coders}}, "roster.coders must be 0 since 2.4.0"),
                    ({"roster": {"coders": 2}, "models": {**models, **coders}}, "roster.coders must be 0 since 2.4.0"),
                    ({"roster": {"coders": 1}}, "roster.coders must be 0 since 2.4.0"),
                    ({"models": {**models, **coders}}, "models.coders is not allowed since 2.4.0")]
        for change, message in rejected:
            self.contract_path.write_text(json.dumps({**self.contract, **change}))
            with self.subTest(change=change):
                with self.assertRaisesRegex(swarmctl.SwarmError, message):
                    swarmctl.validate_new_launch({**self.contract, **change}, self.run_dir)
                with self.assertRaisesRegex(swarmctl.SwarmError, message):
                    swarmctl.init_run(self.contract_path, self.run_dir)
                for dry_run in (True, False):
                    with self.assertRaisesRegex(swarmctl.SwarmError, message):
                        swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=dry_run,
                                                       no_supervisor=True)
                doctor = subprocess.run([sys.executable, str(HERE / "swarmctl.py"), "doctor",
                                         "--contract", str(self.contract_path), "--run-dir", str(self.run_dir),
                                         "--skip-herdr", "--skip-model-catalog"], env=os.environ.copy(),
                                        text=True, capture_output=True)
                self.assertNotEqual(doctor.returncode, 0)
                self.assertIn(message, doctor.stdout + doctor.stderr)
                self.assertFalse(self.run_dir.exists())
                self.assertEqual(self.log_entries("worktree-create"), [])
        swarmctl.validate_new_launch({k: v for k, v in self.contract.items() if k != "roster"}, self.run_dir)
        self.write_contract()
        swarmctl.validate_new_launch(self.contract, self.run_dir)
        root, launch = self.init()
        self.assertEqual(swarmcore.coder_names(launch), [])
        self.assertEqual(json.loads((root / "automation.json").read_text())["automationVersion"], "2.5.0")

    def test_a_reloaded_launch_with_coders_still_loads(self) -> None:
        root, launch = self.legacy_init()
        self.assertEqual(swarmctl.load_launch(root)[1]["roster"], {"coders": 2})
        self.assertEqual(swarmcore.coder_names(launch), ["t123-coder-a", "t123-coder-b"])

    def test_init_is_idempotent_and_private(self) -> None:
        first = swarmctl.init_run(self.contract_path, self.run_dir)
        second = swarmctl.init_run(self.contract_path, self.run_dir)
        self.assertEqual(first["launchSha256"], second["launchSha256"])
        self.assertEqual(os.stat(self.run_dir).st_mode & 0o777, 0o700)
        self.assertTrue((self.run_dir / "runtime/swarmd.py").is_file())
        self.assertEqual({p.name for p in (self.run_dir / "homes").iterdir()}, {"t123-reviewer"})

    def test_runtime_hash_tampering_fails_closed(self) -> None:
        root, _launch = self.init()
        runtime = root / "runtime/swarmd.py"
        runtime.write_text(runtime.read_text() + "# tampered\n")
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.load_launch(root)

    def test_run_pinned_cli_is_self_contained(self) -> None:
        root, _launch = self.init()
        ctl = root / "runtime/swarmctl.py"
        sent = subprocess.run([str(ctl), "event", "send", "--run-dir", str(root),
                               "--from", "orchestrator", "--generation", "1",
                               "--to", "t123-principal", "--type", "BOOT"],
                              text=True, capture_output=True, check=True)
        event_path = pathlib.Path(json.loads(sent.stdout)["eventPath"])
        self.assertTrue(event_path.is_file())
        pending = subprocess.run([str(ctl), "event", "pending", "--run-dir", str(root),
                                  "--recipient", "t123-principal"],
                                 text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(pending.stdout)["count"], 1)

    def test_event_pending_receipt_and_route(self) -> None:
        root, launch = self.init()
        event = swarmctl.send_event(root, launch, sender="orchestrator", generation=1,
                                    recipient="t123-principal", event_type="BOOT", payload={"safe": True})
        self.assertEqual(swarmctl.pending_events(root, launch, "t123-principal")["count"], 1)
        receipt = swarmctl.receipt_event(root, launch, event, "t123-principal", True, "accepted")
        self.assertTrue(receipt.is_file())
        self.assertEqual(swarmctl.pending_events(root, launch, "t123-principal")["count"], 0)
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.receipt_event(root, launch, event, "t123-principal", False, "rejected")
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.send_event(root, launch, sender="t123-coder-a", generation=1,
                                recipient="orchestrator", event_type="APPROVED", payload={})
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                recipient="t123-coder-a", event_type="TASK_ASSIGN", payload={})

    def test_routes_follow_the_task_review_and_slice_flow(self) -> None:
        root, launch = self.legacy_init()  # the coder routes of runs launched before 2.4.0
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
            ("t123-principal", "orchestrator", "LEASE_REQUEST", {"kind": "full-gate"}, sha),
            ("t123-principal", "orchestrator", "LEASE_RELEASE", {"exit": 0}, sha),
            ("t123-principal", "orchestrator", "SLICE_READY", {}, sha),
            ("orchestrator", "t123-principal", "SLICE_ACCEPTED", {}, sha),
            ("orchestrator", "t123-principal", "MODEL_REPLACE",
             {"role": "coders", "configuration": "pi ollama/coder high", "incidentId": "i1"}, {}),
            ("t123-coder-a", "t123-principal", "BLOCKED", {}, {}),
            ("t123-reviewer", "t123-principal", "PROGRESS", {}, {}),
            ("t123-principal", "orchestrator", "BLOCKED", {}, {}),
            ("t123-principal", "t123-reviewer", "PAUSE", {}, {}),
            ("orchestrator", "t123-principal", "RESUME", {"lease": "full-gate"}, {}),
        ]
        for sender, recipient, kind, payload, fields in allowed:
            with self.subTest(route=(sender, recipient, kind)):
                self.assertTrue(swarmctl.send_event(root, launch, sender=sender, generation=1,
                                                    recipient=recipient, event_type=kind,
                                                    payload=payload, fields=fields).is_file())
        rejected = [
            ("t123-coder-a", "t123-coder-b", "TASK_ASSIGN", self.grant(root), bound),
            ("orchestrator", "t123-coder-a", "TASK_ASSIGN", self.grant(root), bound),
            ("t123-principal", "t123-reviewer", "TASK_ASSIGN", self.grant(root), bound),
            ("t123-principal", "t123-principal", "TASK_INTEGRATED", {}, candidate),
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
        ]
        for sender, recipient, kind, payload, fields in rejected:
            with self.subTest(route=(sender, recipient, kind)):
                with self.assertRaises(swarmctl.SwarmError):
                    swarmctl.send_event(root, launch, sender=sender, generation=1, recipient=recipient,
                                        event_type=kind, payload=payload, fields=fields)
        self.assertNotIn("REVIEW_ASSIGN", swarmctl.EVENT_TYPES)

    def test_task_assignment_requires_an_unchanged_grant_file_in_the_run(self) -> None:
        root, launch = self.init()
        fields = {"taskId": "T01", "assignmentId": "a1", "revision": 1}
        grant = self.grant(root)
        outside = self.temp / "grant.json"
        outside.write_text(pathlib.Path(grant["grantPath"]).read_text())
        invalid = [{}, {**grant, "grantSha256": "0" * 64},
                   {**grant, "grantPath": "relative.json"}, {**grant, "grantPath": str(outside)}]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(swarmctl.SwarmError):
                    swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                        recipient="t123-principal", event_type="TASK_ASSIGN",
                                        payload=payload, fields=fields)
        event = swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                    recipient="t123-principal", event_type="TASK_ASSIGN",
                                    payload=grant, fields=fields)
        pathlib.Path(grant["grantPath"]).write_text("{}")  # grant edited after dispatch
        pending = swarmctl.pending_events(root, launch, "t123-principal")
        self.assertEqual(pending["count"], 0)
        self.assertEqual([item["path"] for item in pending["invalid"]], [str(event)])

    def test_stale_sender_generation_is_rejected(self) -> None:
        root, launch = self.init()
        (root / "state.json").write_text(json.dumps({
            "agents": {"t123-principal": {"generation": 2}}
        }))
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                recipient="t123-reviewer", event_type="REVIEW_REQUEST", payload={},
                                fields={"taskId": "T01", "assignmentId": "a1", "revision": 1,
                                        "candidateSha": "a" * 40})

    def test_pending_events_are_first_in_first_out(self) -> None:
        root, launch = self.init()
        candidate = {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "b" * 40}
        sent = []
        for task in ("T03", "T01", "T02"):
            sent.append(str(swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                                recipient="t123-reviewer", event_type="REVIEW_REQUEST",
                                                payload={}, fields={**candidate, "taskId": task})))
        queue = swarmctl.pending_events(root, launch, "t123-reviewer")["pending"]
        self.assertEqual([item["path"] for item in queue], sent)

    def test_nonempty_legacy_run_is_never_migrated(self) -> None:
        self.run_dir.mkdir(mode=0o700, parents=True)
        sentinel = self.run_dir / "legacy-state.json"
        sentinel.write_text("preserve me\n")
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.init_run(self.contract_path, self.run_dir)
        self.assertEqual(sentinel.read_text(), "preserve me\n")
        self.assertFalse((self.run_dir / "runtime").exists())

    def test_snapshot_and_content_addressed_artifact(self) -> None:
        root, launch = self.init()
        output = root / "reports/orchestrator/snapshot.json"
        value = swarmctl.snapshot_create(root, launch, self.repo, ["tracked.txt"], output)
        self.assertEqual(value["files"]["tracked.txt"]["sha256"], swarmctl.sha256_file(self.repo / "tracked.txt"))
        self.assertTrue(swarmctl.snapshot_verify(root, launch, output)["ok"])
        (self.repo / "tracked.txt").write_text("changed\n")
        self.assertFalse(swarmctl.snapshot_verify(root, launch, output)["ok"])
        stored = swarmctl.artifact_put(root, launch, self.repo / "tracked.txt")
        self.assertTrue(pathlib.Path(stored["path"]).is_file())

    def test_gate_is_single_execution_and_rejects_shell(self) -> None:
        root, launch = self.init()
        contract = root / "reports/orchestrator/gate.json"
        log = root / "reports/orchestrator/gate.log"
        exit_path = root / "reports/orchestrator/gate.exit"
        swarmctl.gate_reserve(root, launch, self.repo, [sys.executable, "-c", "print('ok')"], [],
                              log, exit_path, contract)
        self.assertEqual(swarmctl.gate_run(root, launch, contract), 0)
        self.assertEqual(exit_path.read_text(), "0\n")
        self.assertIn("ok", log.read_text())
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.gate_run(root, launch, contract)
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.gate_reserve(root, launch, self.repo, ["sh", "-c", "true"], [],
                                  root / "reports/orchestrator/x.log",
                                  root / "reports/orchestrator/x.exit",
                                  root / "reports/orchestrator/x.json")

    def run_supervisor_once(self, root: pathlib.Path) -> None:
        subprocess.run([sys.executable, str(HERE / "swarmd.py"), "--run-dir", str(root), "--once",
                        "--retry-min", "300"], env=os.environ.copy(), check=True)

    def test_supervisor_wakes_the_event_recipient_not_principal(self) -> None:
        root, launch = self.init()
        event = swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                    recipient="orchestrator", event_type="BLOCKED", payload={"reason": "decision"})
        self.run_supervisor_once(root)
        entries = self.log_entries("prompt")
        self.assertEqual(entries[-1]["target"], "p0")
        self.assertIn(str(event), entries[-1]["message"])
        self.run_supervisor_once(root)
        self.assertEqual(len(self.log_entries("prompt")), len(entries))
        swarmctl.receipt_event(root, launch, event, "orchestrator", True, "handled")
        self.run_supervisor_once(root)
        self.assertEqual(len(self.log_entries("prompt")), len(entries))

    def test_supervisor_delivers_the_review_queue_oldest_first(self) -> None:
        root, launch = self.init()
        fake = json.loads(self.fake_state.read_text())
        fake["agents"]["t123-reviewer"] = {"name": "t123-reviewer", "agent": "claude", "agent_status": "idle",
                                           "pane_id": "p9", "tab_id": "t0", "workspace_id": "w1",
                                           "cwd": str(root / "homes/t123-reviewer"), "state_change_seq": 1}
        self.fake_state.write_text(json.dumps(fake))
        candidate = {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "b" * 40}
        first = swarmctl.send_event(root, launch, sender="t123-principal", generation=1, recipient="t123-reviewer",
                                    event_type="REVIEW_REQUEST", payload={}, fields=candidate)
        second = swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                     recipient="t123-reviewer", event_type="REVIEW_REQUEST", payload={},
                                     fields={**candidate, "taskId": "T02"})
        self.run_supervisor_once(root)
        prompts = self.log_entries("prompt")
        self.assertEqual(len(prompts), 1)
        self.assertIn(str(first), prompts[0]["message"])
        swarmctl.receipt_event(root, launch, first, "t123-reviewer", True, "reviewing")
        self.run_supervisor_once(root)
        prompts = self.log_entries("prompt")
        self.assertEqual(len(prompts), 2)
        self.assertIn(str(second), prompts[1]["message"])

    def test_responsible_bootstrap_dry_run_has_no_side_effects(self) -> None:
        result = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=True,
                                                no_supervisor=False)
        self.assertTrue(result["dryRun"])
        self.assertEqual(result["plan"]["childrenStartedByPrincipal"], ["t123-reviewer"])
        self.assertFalse(self.run_dir.exists())
        self.assertFalse(pathlib.Path(self.contract["slice"]["worktree"]).exists())
        self.assertEqual(set(json.loads(self.fake_state.read_text())["agents"]), {"orchestrator"})

    def test_responsible_bootstrap_is_idempotent_and_starts_only_principal(self) -> None:
        first = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                               no_supervisor=True)
        journal_path = self.run_dir / "bootstrap.json"
        journal = json.loads(journal_path.read_text())
        journal["responsible"].pop("bootEventPath")  # crash-window simulation
        journal_path.write_text(json.dumps(journal))
        second = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                                no_supervisor=True)
        self.assertEqual(first["principal"]["paneId"], second["principal"]["paneId"])
        fake = json.loads(self.fake_state.read_text())
        self.assertEqual(set(fake["agents"]), {"orchestrator", "t123-principal"})
        boots = list((self.run_dir / "inbox/t123-principal").glob("*.json"))
        self.assertEqual(len(boots), 1)
        boot = json.loads(boots[0].read_text())
        self.assertEqual(boot["payload"]["ponytailPath"], self.contract["ponytailPath"])
        self.assertEqual(subprocess.check_output(["git", "-C", self.contract["slice"]["worktree"],
                                                  "rev-parse", "HEAD"], text=True).strip(), self.base)

    def test_responsible_bootstrap_starts_a_codex_principal_in_yolo_mode(self) -> None:
        self.contract["models"].update(principal="codex gpt-6.1-sol high")
        self.write_contract()
        swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        (start,) = self.log_entries("start")
        args = start["args"]
        self.assertEqual(args[args.index("--kind") + 1], "codex")
        self.assertEqual(args[args.index("--") + 1:],
                         ["--model", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"',
                          "--dangerously-bypass-approvals-and-sandbox"])

    def test_unowned_dirty_worktree_is_not_adopted(self) -> None:
        path = pathlib.Path(self.contract["slice"]["worktree"])
        path.parent.mkdir(parents=True)
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b",
                        self.contract["slice"]["branch"], str(path), self.base], check=True)
        (path / "tracked.txt").write_text("unowned change\n")
        with self.assertRaises(swarmctl.SwarmError):
            swarmbootstrap.ensure_slice_worktree(self.contract)

    def test_artifact_and_snapshot_reject_escape(self) -> None:
        root, launch = self.init()
        outside = self.temp / "secret.txt"
        outside.write_text("secret\n")
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.artifact_put(root, launch, outside)
        (self.repo / "escape").symlink_to(outside)
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.snapshot_create(root, launch, self.repo, ["escape"],
                                     root / "reports/orchestrator/escape.json")

    def test_supervisor_does_not_inject_into_working_recipient(self) -> None:
        root, launch = self.init()
        swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                            recipient="orchestrator", event_type="BLOCKED", payload={"reason": "decision"})
        fake = json.loads(self.fake_state.read_text())
        fake["agents"]["orchestrator"]["agent_status"] = "working"
        self.fake_state.write_text(json.dumps(fake))
        subprocess.run([sys.executable, str(HERE / "swarmd.py"), "--run-dir", str(root), "--once"],
                       env=os.environ.copy(), check=True)
        self.assertEqual(self.fake_log.read_text(), "")

    def test_principal_bootstrap_requires_explicit_authority(self) -> None:
        responsible = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                                     no_supervisor=True)
        root, launch = swarmctl.load_launch(self.run_dir)
        authorization = swarmctl.send_event(root, launch, sender="orchestrator", generation=1,
                                            recipient="t123-principal", event_type="RESUME",
                                            payload={"decision": "unrelated-resume"})
        with self.principal_pane(responsible["principal"]["paneId"]):
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.bootstrap_principal(self.run_dir, authorization)

    def test_principal_bootstrap_starts_reviewer_and_coders_once(self) -> None:
        with self.pre_240_creation():
            responsible, authorization = self.authorize_children()
        root, launch = swarmctl.load_launch(self.run_dir)
        with self.principal_pane(responsible["principal"]["paneId"]):
            first = swarmctl.bootstrap_principal(self.run_dir, authorization)
            journal_path = self.run_dir / "bootstrap.json"
            journal = json.loads(journal_path.read_text())
            journal["principal"]["bootEvents"].pop("t123-coder-a")  # crash-window simulation
            journal_path.write_text(json.dumps(journal))
            second = swarmctl.bootstrap_principal(self.run_dir, authorization)
        children = ["t123-reviewer", "t123-coder-a", "t123-coder-b"]
        self.assertEqual(set(first["children"]), set(children))
        self.assertEqual(set(second["children"]), set(children))
        fake = json.loads(self.fake_state.read_text())
        self.assertEqual(set(fake["agents"]), {"orchestrator", "t123-principal", *children})
        starts = {entry["args"][2]: entry["args"] for entry in self.log_entries("start")}
        self.assertEqual(len(self.log_entries("start")), 4)  # Principal plus three children, once each
        reviewer = starts["t123-reviewer"]
        self.assertEqual(reviewer[reviewer.index("--kind") + 1], "claude")
        self.assertEqual(reviewer[reviewer.index("--") + 1:],
                         ["--model", "claude-opus-5-5", "--effort", "high", "--dangerously-skip-permissions"])
        coder = starts["t123-coder-a"]
        self.assertEqual(coder[coder.index("--") + 1:], ["--model", "ollama/coder", "--thinking", "medium"])
        run_state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(set(run_state["agents"]), {"t123-principal", *children})
        self.assertEqual((run_state["schemaVersion"], run_state["openFindings"], run_state["plan"]), (2, [], None))
        self.assertNotIn("parallelism", run_state)
        layout = json.loads((self.run_dir / "bootstrap.json").read_text())["principal"]["layout"]
        created = sorted(layout, key=lambda name: int(layout[name]["paneId"].lstrip("p")))
        self.assertEqual(created, children)  # fake Herdr pane IDs increase with creation order
        principal_tab = responsible["principal"]["tabId"]
        self.assertEqual(layout["t123-reviewer"]["tabId"], principal_tab)
        self.assertEqual(layout["t123-coder-a"]["tabId"], layout["t123-coder-b"]["tabId"])
        self.assertNotEqual(layout["t123-coder-a"]["tabId"], principal_tab)
        self.assertEqual(fake["tabs"][principal_tab]["pane_count"], 2)
        reviewer_boot = json.loads(next((self.run_dir / "inbox/t123-reviewer").glob("*.json")).read_text())
        self.assertEqual((reviewer_boot["payload"]["coordinator"], reviewer_boot["payload"]["ponytailPath"]),
                         ("t123-principal", None))
        with self.assertRaisesRegex(swarmctl.SwarmError, "not part of this run"):
            swarmctl.send_event(root, launch, sender="t123-principal", generation=1,
                                recipient="t123-coder-c", event_type="TASK_ASSIGN", payload=self.grant(root),
                                fields={"taskId": "x", "assignmentId": "y", "revision": 1})

    def test_principal_alone_starts_only_the_reviewer(self) -> None:
        responsible, authorization = self.authorize_children()
        with self.principal_pane(responsible["principal"]["paneId"]):
            result = swarmctl.bootstrap_principal(self.run_dir, authorization)
        self.assertEqual(set(result["children"]), {"t123-reviewer"})
        fake = json.loads(self.fake_state.read_text())
        self.assertEqual(set(fake["agents"]), {"orchestrator", "t123-principal", "t123-reviewer"})
        self.assertFalse(any(tab["label"] == "t123-coders" for tab in fake["tabs"].values()))
        root, launch = swarmctl.load_launch(self.run_dir)
        candidate = {"taskId": "T01", "assignmentId": "a1", "revision": 1, "candidateSha": "b" * 40}
        swarmctl.send_event(root, launch, sender="t123-principal", generation=1, recipient="t123-principal",
                            event_type="TASK_ASSIGN", payload=self.grant(root),
                            fields={k: candidate[k] for k in ("taskId", "assignmentId", "revision")})
        swarmctl.send_event(root, launch, sender="t123-principal", generation=1, recipient="t123-reviewer",
                            event_type="REVIEW_REQUEST", payload={}, fields=candidate)
        swarmctl.send_event(root, launch, sender="t123-reviewer", generation=1, recipient="t123-principal",
                            event_type="APPROVED", payload={}, fields=candidate)
        with self.assertRaisesRegex(swarmctl.SwarmError, "not part of this run"):
            swarmctl.send_event(root, launch, sender="t123-principal", generation=1, recipient="t123-coder-a",
                                event_type="TASK_ASSIGN", payload=self.grant(root), fields=candidate)

    def test_principal_restart_bumps_generation_in_the_same_pane(self) -> None:
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
        fake = json.loads(self.fake_state.read_text())
        self.assertEqual(fake["agents"]["t123-principal"]["pane_id"], pane)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["agents"]["t123-principal"]["generation"], 2)
        self.assertEqual(json.loads((self.run_dir / "supervisor.json").read_text())["principal"]["generation"], 2)
        boot = json.loads(pathlib.Path(result["bootEventPath"]).read_text())
        self.assertEqual((boot["type"], boot["payload"]["generation"]), ("BOOT", 2))
        self.assertEqual(boot["payload"]["rotation"]["statePath"], str(self.run_dir / "state.json"))
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.send_event(root, launch, sender="t123-principal", generation=1, recipient="orchestrator",
                                event_type="PROGRESS", payload={})
        swarmctl.send_event(root, launch, sender="t123-principal", generation=2, recipient="orchestrator",
                            event_type="AGENT_READY", payload={})
        again = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False,
                                               no_supervisor=True)
        self.assertEqual(again["principal"]["paneId"], pane)
        self.quit_agent("t123-principal")
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        cli = subprocess.run([sys.executable, str(root / "runtime/swarmctl.py"), "bootstrap", "restart-principal",
                              "--run-dir", str(root), "--reason", "phase 2"], env=os.environ.copy(),
                             text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(cli.stdout)["generation"], 3)
        journal = json.loads((self.run_dir / "bootstrap.json").read_text())
        self.assertEqual([r["generation"] for r in journal["responsible"]["rotations"]], [2, 3])

    def test_interrupted_restart_resumes_without_a_second_bump(self) -> None:
        swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        self.quit_agent("t123-principal")
        journal_path = self.run_dir / "bootstrap.json"
        journal = json.loads(journal_path.read_text())
        journal["responsible"]["rotation"] = {"generation": 2, "previousGeneration": 1, "reason": "crash",
                                              "startedAt": "x", "completed": False}
        journal_path.write_text(json.dumps(journal))  # crash after the intent was journaled
        result = swarmctl.rotate_principal(self.run_dir, "retry")
        self.assertEqual(result["generation"], 2)
        boot = json.loads(pathlib.Path(result["bootEventPath"]).read_text())
        self.assertEqual(boot["payload"]["rotation"]["reason"], "crash")
        boots = list((self.run_dir / "inbox/t123-principal").glob("*.json"))
        self.assertEqual(len(boots), 2)  # original BOOT plus one replacement


    # Herdr worktrees (2.2.0)

    def git(self, *argv: str, cwd: pathlib.Path | None = None) -> str:
        return subprocess.check_output(["git", "-C", str(cwd or self.repo), *argv], text=True).strip()

    def bootstrap_team(self) -> tuple[dict, pathlib.Path, dict]:
        responsible, authorization = self.authorize_children()
        with self.principal_pane(responsible["principal"]["paneId"]):
            swarmctl.bootstrap_principal(self.run_dir, authorization)
        root, launch = swarmctl.load_launch(self.run_dir)
        return responsible, root, launch

    def test_slice_worktree_is_a_herdr_workspace_hosting_the_principal(self) -> None:
        responsible, root, _launch = self.bootstrap_team()
        create = self.log_entries("worktree-create")
        self.assertEqual(len(create), 1)
        args = create[0]["args"]
        self.assertEqual([args[args.index(k) + 1] for k in ("--cwd", "--branch", "--base", "--label")],
                         [str(self.repo), self.contract["slice"]["branch"], self.base, "t123"])
        self.assertIn("--no-focus", args)
        workspace = responsible["worktree"]["workspaceId"]
        self.assertNotEqual(workspace, "w1")
        self.assertEqual((responsible["principal"]["workspaceId"], responsible["principal"]["paneId"]),
                         (workspace, responsible["worktree"]["rootPaneId"]))
        fake = json.loads(self.fake_state.read_text())
        self.assertFalse([t for t in fake["tabs"].values() if t["workspace_id"] == "w1"])  # responsible untouched
        self.assertEqual({a["workspace_id"] for n, a in fake["agents"].items() if n.startswith("t123-")}, {workspace})
        state = json.loads((root / "state.json").read_text())
        self.assertEqual(state["workspaceId"], workspace)
        self.assertEqual({a["workspaceId"] for a in state["agents"].values()}, {workspace})
        again = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        self.assertEqual(again["worktree"]["workspaceId"], workspace)
        self.assertEqual(len(self.log_entries("worktree-create")), 1)

    def test_dry_run_plans_herdr_worktree_create(self) -> None:
        plan = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=True,
                                              no_supervisor=True)["plan"]["worktree"]
        self.assertEqual(plan["argv"][:3], ["herdr", "worktree", "create"])
        self.assertEqual(self.fake_log.read_text(), "")

    def test_existing_branch_at_base_is_checked_out_without_base(self) -> None:
        self.git("branch", self.contract["slice"]["branch"], self.base)
        swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        self.assertNotIn("--base", self.log_entries("worktree-create")[0]["args"])
        self.git("commit", "-q", "--allow-empty", "-m", "ahead")
        other = dict(self.contract["slice"], branch="swarm/ahead", worktree=str(self.worktree_root / "ahead"))
        self.git("branch", "swarm/ahead", "HEAD")
        with self.assertRaisesRegex(swarmctl.SwarmError, "not at its base"):
            swarmbootstrap.ensure_slice_worktree(dict(self.contract, slice=other))

    def test_clean_git_worktree_is_adopted_by_opening_it_in_herdr(self) -> None:
        path = pathlib.Path(self.contract["slice"]["worktree"])
        path.parent.mkdir(parents=True)
        self.git("worktree", "add", "-q", "-b", self.contract["slice"]["branch"], str(path), self.base)
        result = swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        self.assertEqual(result["worktree"]["action"], "adopt")
        self.assertEqual(len(self.log_entries("worktree-open")), 1)
        self.assertEqual(self.log_entries("worktree-create"), [])
        self.assertEqual(result["principal"]["workspaceId"], result["worktree"]["workspaceId"])

    def test_repo_path_must_be_the_main_checkout(self) -> None:
        linked = self.temp / "linked"
        self.git("worktree", "add", "-q", "--detach", str(linked), self.base)
        with self.assertRaisesRegex(swarmctl.SwarmError, "main checkout"):
            swarmbootstrap.require_main_checkout(linked)
        swarmbootstrap.require_main_checkout(self.repo)

    def test_task_worktree_moves_the_coder_into_its_workspace(self) -> None:
        responsible, root, launch = self.legacy_team()
        with self.principal_pane(responsible["principal"]["paneId"]):
            first = swarmctl.task_worktree(root, launch, "T123-T01", "t01", "t123-coder-a", self.base)
            again = swarmctl.task_worktree(root, launch, "T123-T01", "t01", "t123-coder-a", self.base)
            own = swarmctl.task_worktree(root, launch, "T123-T02", "t02", "t123-principal", self.base)
            with self.assertRaisesRegex(swarmctl.SwarmError, "not an implementer"):
                swarmctl.task_worktree(root, launch, "T123-T03", "t03", "t123-reviewer", self.base)
        with self.principal_pane("elsewhere"), self.assertRaisesRegex(swarmctl.SwarmError, "Principal pane"):
            swarmctl.task_worktree(root, launch, "T123-T04", "t04", "t123-coder-b", self.base)
        workspace = first["worktree"]["workspaceId"]
        self.assertEqual(first["worktree"]["branch"], "task/t123/t01")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=pathlib.Path(first["worktree"]["path"])), self.base)
        self.assertEqual((again["worktree"]["action"], again["worktree"]["workspaceId"]), ("adopt", workspace))
        self.assertEqual(len(self.log_entries("move")), 1)
        self.assertIsNone(own["ownerPane"])
        fake = json.loads(self.fake_state.read_text())
        coder = fake["agents"]["t123-coder-a"]
        self.assertEqual((coder["workspace_id"], coder["pane_id"]), (workspace, first["ownerPane"]["paneId"]))
        self.assertEqual(fake["agents"]["t123-principal"]["workspace_id"], responsible["worktree"]["workspaceId"])
        state = json.loads((root / "state.json").read_text())
        self.assertEqual(state["agents"]["t123-coder-a"]["paneId"], coder["pane_id"])
        self.assertEqual(state["resourceOwnership"][coder["pane_id"]], "t123-coder-a")
        self.assertEqual(state["tasks"]["T123-T01"]["workspaceId"], workspace)
        self.assertEqual(state["tasks"]["T123-T02"]["owner"], "t123-principal")
        resume = [p for p in (root / "inbox/t123-principal").glob("*.json")
                  if json.loads(p.read_text())["type"] == "RESUME"][0]
        with self.principal_pane(responsible["principal"]["paneId"]):
            swarmctl.bootstrap_principal(self.run_dir, resume)  # adopts the moved coder
        self.assertEqual(len(self.log_entries("start")), 4)

    def test_review_checkout_is_detached_at_the_candidate_and_opened_in_herdr(self) -> None:
        root, launch = self.init()
        self.git("commit", "-q", "--allow-empty", "-m", "candidate")
        sha = self.git("rev-parse", "HEAD")
        first = swarmctl.review_worktree(root, launch, "T123-T01", 1, sha)
        path = pathlib.Path(first["path"])
        self.assertEqual(path, self.worktree_root.resolve() / "t123" / "reviews" / "t123-t01-r1")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=path), sha)
        self.assertEqual(self.git("branch", "--show-current", cwd=path), "")
        again = swarmctl.review_worktree(root, launch, "T123-T01", 1, sha)
        self.assertEqual((again["action"], again["workspaceId"]), ("adopt", first["workspaceId"]))
        with self.assertRaisesRegex(swarmctl.SwarmError, "not detached at the candidate"):
            swarmctl.review_worktree(root, launch, "T123-T01", 1, self.base)

    def test_remove_is_unforced_and_only_for_clean_contained_unoccupied_worktrees(self) -> None:
        responsible, root, launch = self.legacy_team()
        with self.principal_pane(responsible["principal"]["paneId"]):
            task = swarmctl.task_worktree(root, launch, "T123-T01", "t01", "t123-coder-a", self.base)
        path = pathlib.Path(task["worktree"]["path"])
        with self.assertRaisesRegex(swarmctl.SwarmError, "agents still live"):
            swarmctl.remove_worktree(root, launch, path, "main")
        self.quit_agent("t123-coder-a")
        (path / "tracked.txt").write_text("dirty\n")
        with self.assertRaisesRegex(swarmctl.SwarmError, "nothing is forced"):
            swarmctl.remove_worktree(root, launch, path, "main")
        self.git("commit", "-qam", "task work", cwd=path)
        with self.assertRaisesRegex(swarmctl.SwarmError, "not contained in main"):
            swarmctl.remove_worktree(root, launch, path, "main")
        self.git("merge", "-q", "--no-ff", "-m", "integrate", "task/t123/t01")
        with self.assertRaisesRegex(swarmctl.SwarmError, "only this run"):
            swarmctl.remove_worktree(root, launch, self.repo, "main")
        result = swarmctl.remove_worktree(root, launch, path, "main")
        self.assertEqual((result["workspaceId"], result["branchKept"]),
                         (task["worktree"]["workspaceId"], "task/t123/t01"))
        self.assertFalse(path.exists())
        self.assertTrue(self.git("branch", "--list", "task/t123/t01"))
        removes = self.log_entries("worktree-remove")
        self.assertEqual(len(removes), 1)
        self.assertNotIn("--force", removes[0]["args"])
        review = swarmctl.review_worktree(root, launch, "T123-T01", 1, self.base)
        fake = json.loads(self.fake_state.read_text())
        fake["workspaces"].pop(review["workspaceId"])  # the reviewer closed it after its verdict
        fake["worktrees"].pop(review["path"])
        self.fake_state.write_text(json.dumps(fake))
        removed = swarmctl.remove_worktree(root, launch, pathlib.Path(review["path"]), "main")
        self.assertIsNone(removed["branchKept"])
        self.assertFalse(pathlib.Path(review["path"]).exists())


    # Shell readiness and empty panes (2.3.0)

    def fake(self) -> dict:
        return json.loads(self.fake_state.read_text())

    def edit_fake(self, change) -> None:
        fake = self.fake()
        change(fake)
        self.fake_state.write_text(json.dumps(fake))

    def panes_of(self, workspace: str) -> list[str]:
        return [p["pane_id"] for p in self.fake()["panes"].values() if p["workspace_id"] == workspace]

    def test_agent_start_waits_until_a_fresh_pane_is_an_available_shell(self) -> None:
        # Fake panes initialize for two reads; an immediate start answers agent_pane_busy (S463 race).
        self.bootstrap_team()
        self.assertEqual(self.log_entries("start-busy"), [])
        self.assertEqual(len(self.log_entries("start")), 2)  # Principal and reviewer
        self.quit_agent("t123-principal")
        swarmctl.rotate_principal(self.run_dir, "clean restart between phases")
        self.assertEqual(self.log_entries("start-busy"), [])
        self.assertEqual(len(self.log_entries("start")), 3)

    def test_agent_start_retries_busy_answers_a_bounded_number_of_times(self) -> None:
        os.environ["FAKE_HERDR_START_BUSY"] = "1"
        responsible, authorization = self.authorize_children()
        self.assertEqual((len(self.log_entries("start-busy")), len(self.log_entries("start"))), (1, 1))
        os.environ["FAKE_HERDR_START_BUSY"] = str(swarmbootstrap.AGENT_START_ATTEMPTS)
        with self.principal_pane(responsible["principal"]["paneId"]):
            with self.assertRaisesRegex(swarmctl.SwarmError, "agent_pane_busy"):
                swarmctl.bootstrap_principal(self.run_dir, authorization)

    def test_shell_wait_times_out_with_a_clear_error(self) -> None:
        os.environ["FAKE_HERDR_WARMUP"] = "1000000"
        swarmbootstrap.SHELL_TIMEOUT_SECONDS = 0.3
        with self.assertRaisesRegex(swarmctl.SwarmError, "is not an available shell after"):
            swarmctl.bootstrap_responsible(self.contract_path, self.run_dir, dry_run=False, no_supervisor=True)
        self.assertEqual(self.log_entries("start") + self.log_entries("start-busy"), [])

    def test_task_worktree_closes_the_root_shell_beside_the_coder(self) -> None:
        responsible, root, launch = self.legacy_team()
        with self.principal_pane(responsible["principal"]["paneId"]):
            task = swarmctl.task_worktree(root, launch, "T123-T01", "t01", "t123-coder-a", self.base)
            again = swarmctl.task_worktree(root, launch, "T123-T01", "t01", "t123-coder-a", self.base)
        workspace, shell = task["worktree"]["workspaceId"], task["worktree"]["rootPaneId"]
        self.assertEqual(task["closedPanes"], [shell])
        self.assertEqual(again["closedPanes"], [])
        self.assertEqual([entry["args"] for entry in self.log_entries("pane-close")], [["pane", "close", shell]])
        self.assertEqual(self.panes_of(workspace), [task["ownerPane"]["paneId"]])
        state = json.loads((root / "state.json").read_text())
        self.assertEqual(state["tasks"]["T123-T01"]["workspaceId"], workspace)
        self.assertNotIn("shellPaneId", state["tasks"]["T123-T01"])
        with self.principal_pane(responsible["principal"]["paneId"]):
            second = swarmctl.task_worktree(root, launch, "T123-T02", "t02", "t123-coder-a", self.base)
        # The coder's move empties its previous workspace, which Herdr closes.
        self.assertNotIn(workspace, self.fake()["workspaces"])
        self.assertEqual(self.panes_of(second["worktree"]["workspaceId"]), [second["ownerPane"]["paneId"]])
        state = json.loads((root / "state.json").read_text())
        self.assertIsNone(state["tasks"]["T123-T01"]["workspaceId"])

    def test_principal_task_workspace_is_closed_and_reopens_with_worktree_open(self) -> None:
        responsible, root, launch = self.legacy_team()
        with self.principal_pane(responsible["principal"]["paneId"]):
            own = swarmctl.task_worktree(root, launch, "T123-T02", "t02", "t123-principal", self.base)
            again = swarmctl.task_worktree(root, launch, "T123-T02", "t02", "t123-principal", self.base)
        workspace = own["worktree"]["workspaceId"]
        self.assertEqual(own["closedWorkspace"], workspace)
        self.assertEqual([entry["args"] for entry in self.log_entries("workspace-close")],
                         [["workspace", "close", workspace]])  # plain close, never --group
        self.assertIsNone(again["worktree"]["workspaceId"])
        self.assertEqual(self.log_entries("worktree-open"), [])  # a rerun keeps it closed
        path = pathlib.Path(own["worktree"]["path"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=path), self.base)
        self.assertIsNone(swarmbootstrap.herdr_worktree(self.repo, path.resolve())["open_workspace_id"])
        state = json.loads((root / "state.json").read_text())
        self.assertIsNone(state["tasks"]["T123-T02"]["workspaceId"])
        with self.principal_pane(responsible["principal"]["paneId"]):
            handed = swarmctl.task_worktree(root, launch, "T123-T02", "t02", "t123-coder-b", self.base)
        self.assertEqual(len(self.log_entries("worktree-open")), 1)
        reopened = handed["worktree"]["workspaceId"]
        self.assertEqual(self.panes_of(reopened), [handed["ownerPane"]["paneId"]])
        state = json.loads((root / "state.json").read_text())
        self.assertEqual(state["tasks"]["T123-T02"]["workspaceId"], reopened)

    def test_a_busy_root_shell_is_kept_reported_and_closed_on_a_rerun(self) -> None:
        responsible, root, launch = self.legacy_team()
        os.environ["FAKE_HERDR_ROOT_BUSY"] = "1"
        swarmbootstrap.SHELL_TIMEOUT_SECONDS = 0.3
        with self.principal_pane(responsible["principal"]["paneId"]):
            coder = swarmctl.task_worktree(root, launch, "T123-T01", "t01", "t123-coder-a", self.base)
            own = swarmctl.task_worktree(root, launch, "T123-T02", "t02", "t123-principal", self.base)
        self.assertEqual(self.log_entries("pane-close") + self.log_entries("workspace-close"), [])
        self.assertEqual([kept["paneId"] for kept in coder["keptPanes"]], [coder["worktree"]["rootPaneId"]])
        self.assertIsNone(own["closedWorkspace"])
        self.assertTrue(own["keptPanes"])
        state = json.loads((root / "state.json").read_text())
        self.assertEqual(state["tasks"]["T123-T01"]["shellPaneId"], coder["worktree"]["rootPaneId"])
        self.assertEqual(state["tasks"]["T123-T02"]["workspaceId"], own["worktree"]["workspaceId"])

        def command_ends(fake: dict) -> None:
            for pane in fake["panes"].values():
                pane.pop("busy_command", None)
        self.edit_fake(command_ends)
        with self.principal_pane(responsible["principal"]["paneId"]):
            coder = swarmctl.task_worktree(root, launch, "T123-T01", "t01", "t123-coder-a", self.base)
            own = swarmctl.task_worktree(root, launch, "T123-T02", "t02", "t123-principal", self.base)
        self.assertEqual(coder["closedPanes"], [state["tasks"]["T123-T01"]["shellPaneId"]])
        self.assertEqual(own["closedWorkspace"], state["tasks"]["T123-T02"]["workspaceId"])
        state = json.loads((root / "state.json").read_text())
        self.assertNotIn("shellPaneId", state["tasks"]["T123-T01"])
        self.assertIsNone(state["tasks"]["T123-T02"]["workspaceId"])

    def test_review_workspace_closes_after_the_verdict_only_when_idle(self) -> None:
        root, launch = self.init()
        self.git("commit", "-q", "--allow-empty", "-m", "candidate")
        sha = self.git("rev-parse", "HEAD")
        first = swarmctl.review_worktree(root, launch, "T123-T01", 1, sha)
        path = pathlib.Path(first["path"])

        def intruder(fake: dict) -> None:
            pane = fake["panes"][first["rootPaneId"]]
            fake["agents"]["intruder"] = {"name": "intruder", "agent": "pi", "agent_status": "idle",
                                          "pane_id": pane["pane_id"], "tab_id": pane["tab_id"],
                                          "workspace_id": pane["workspace_id"], "cwd": pane["cwd"]}
        self.edit_fake(intruder)
        with self.assertRaisesRegex(swarmctl.SwarmError, "not an available shell"):
            swarmctl.close_worktree(root, launch, path)
        self.edit_fake(lambda fake: fake["agents"].pop("intruder"))
        cli = subprocess.run([sys.executable, str(root / "runtime/swarmctl.py"), "worktree", "close",
                              "--run-dir", str(root), "--path", str(path)], env=os.environ.copy(),
                             text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(cli.stdout)["closedWorkspace"], first["workspaceId"])
        self.assertEqual([entry["args"] for entry in self.log_entries("workspace-close")],
                         [["workspace", "close", first["workspaceId"]]])
        self.assertTrue(path.is_dir())
        self.assertIsNone(swarmctl.close_worktree(root, launch, path)["closedWorkspace"])  # already closed
        with self.assertRaisesRegex(swarmctl.SwarmError, "task or review"):
            swarmctl.close_worktree(root, launch, pathlib.Path(self.contract["slice"]["worktree"]))
        # A review workspace left open is closed by the next review.
        forgotten = swarmctl.review_worktree(root, launch, "T123-T01", 1, sha)
        second = swarmctl.review_worktree(root, launch, "T123-T01", 2, sha)
        self.assertEqual(second["closedWorkspaces"], [forgotten["workspaceId"]])
        self.assertNotIn(forgotten["workspaceId"], self.fake()["workspaces"])
        self.assertIn(second["workspaceId"], self.fake()["workspaces"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
