"""Run Claude Code or Codex headless inside a project folder and stream normalized events.

Every panel goes through start(RunSpec): chat in the agent dock, writing review passes, code review and explanation,
figure edits, handoff summaries. A run resumes the panel's bound session unless it is ephemeral (one-shot checks).

A CLI run is durable. Its supervisor (supervise.py) is a process of its own that starts the CLI, keeps its stdin and
writes what it prints into ~/.research-deck/runs/<id>/; this server only follows that folder. Closing the page,
reloading it, or restarting the server (a redeploy) leaves the run going: recover() picks up every unfinished run
when the server starts, and the stream replays it (the SSE ids carry BOOT, so a browser that reconnects to a new
server is told to start over with a "reset" event). The fake agent (RD_FAKE_AGENT=1) runs in this process.

While a run works: steer(run, text) gives Claude the message as soon as the tools it is running finish (stream-json
input); Codex cannot take one into a running turn, so steering stops its turn and continues the session with the
message (queued "now", started by the finish hook). cancel() stops a run: an interrupt for Claude, SIGINT for Codex.

Normalized events (also the SSE payloads, see web/src/types.ts AgentEvent):
  start {provider, model, effort, fast, session_id, purpose, steerable}
  session {session_id}            the backend assigned or confirmed a session id
  text {delta}                    assistant text (Claude: token deltas; Codex: whole messages)
  thinking {text?}                a heartbeat while the model reasons
  tool {name, detail}             a tool call, shell command, file change or MCP call
  steer {id, text, at}            a message the researcher sent into the running turn, handed to Claude (not read yet)
  user {id, text}                 Claude read that message (its echo); it goes into the transcript when the run ends
  usage {input, output, cache_read, cost}
  error {message}
  done {ok, text, session_id, duration_ms, cancelled?}
  reset {}                        (the stream only) everything before this is void: the server restarted

Commands (flags verified against Claude Code 2.1.290 and codex-cli 0.166):
  claude -p --input-format stream-json --output-format stream-json --replay-user-messages --verbose
         --include-partial-messages --model M --effort E [--resume SID | --no-session-persistence]
         [--settings {"fastMode":true}] [--permission-mode ...] [--allowedTools ...] [--disallowedTools ...]
         [--mcp-config FILE] [--append-system-prompt S]                      messages and control requests on stdin
  codex exec [resume SID] --json --skip-git-repo-check -m M -c model_reasoning_effort="E"
         -c service_tier="priority|default" -c approval_policy="never" (--sandbox X | -c sandbox_mode="X")
         [-c mcp_servers.research_deck.*] [--ephemeral] -                                              prompt on stdin
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import config
from ..util import append_jsonl, now_iso, read_json, write_json

log = logging.getLogger("research_deck")

READ_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "mcp__research-deck"]
WRITE_TOOLS = READ_TOOLS + ["Edit", "Write", "MultiEdit", "NotebookEdit"]
NEVER_TOOLS = ["Bash"]          # v1: agents driven from the dashboard do not run shell commands
MAX_RUNS_KEPT = 200
SERVER_DIR = Path(__file__).resolve().parents[2]       # where `python -m research_deck…` finds the package
BOOT = uuid.uuid4().hex[:8]     # this server process; a stream reconnecting from another one starts over


@dataclass
class RunSpec:
    project_id: str
    panel: str                      # the panel whose session this is (after resolving "shared")
    provider: str                   # claude | codex | fake
    model: str
    effort: str
    fast: bool
    prompt: str
    cwd: str
    session_id: str | None = None   # resume this session; None starts a new one (unless ephemeral)
    ephemeral: bool = False         # one-shot: no session created, resumed or recorded
    permission: str = "read"        # read | write (edit files inside the project)
    system: str | None = None       # appended to the backend's system prompt
    tools: bool = True              # False: answer from the prompt alone (review passes)
    mcp: bool = True                # offer the research-deck MCP tools
    purpose: str = "chat"
    timeout_s: int = 1800
    user_text: str | None = None    # what the transcript records as the user's message (defaults to prompt)


@dataclass
class Run:
    spec: RunSpec
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "running"         # running | done | error | cancelled
    events: list[dict] = field(default_factory=list)
    text: str = ""
    session_id: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    error: str | None = None
    cancel_requested: bool = False
    dir: Path | None = None         # a CLI run's folder (supervise.py); None for the fake agent
    supervisor: subprocess.Popen | None = None          # when this server started it (to reap it)
    _cond: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, event: dict) -> None:
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    def events_from(self, index: int, timeout: float) -> list[dict]:
        """Events at index and after; waits up to timeout for at least one (empty list on timeout)."""
        with self._cond:
            if index >= len(self.events) and self.status == "running":
                self._cond.wait(timeout)
            return self.events[index:]

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.time() + timeout
        with self._cond:
            while self.status == "running":
                left = None if deadline is None else deadline - time.time()
                if left is not None and left <= 0:
                    return False
                self._cond.wait(left)
        return True

    @property
    def steerable(self) -> bool:
        """A message can reach the running turn itself (Claude's stream-json input)."""
        return self.spec.provider == "claude" and self.dir is not None

    def summary(self) -> dict:
        s = self.spec
        return {"run_id": self.id, "status": self.status, "provider": s.provider, "model": s.model, "effort": s.effort,
                "fast": s.fast, "panel": s.panel, "purpose": s.purpose, "session_id": self.session_id or s.session_id,
                "started": self.started, "finished": self.finished, "error": self.error, "steerable": self.steerable}


_RUNS: dict[str, Run] = {}
_RUNS_LOCK = threading.Lock()
# purpose -> fn(spec) -> answer text, for RD_FAKE_AGENT=1 (tests, offline demos). Modules register their own.
FAKE_RESPONDERS: dict[str, Callable[[RunSpec], str]] = {}
# fn(run) after every run has ended and been recorded (agents/api.py starts the conversation's next queued message)
FINISH_HOOKS: list[Callable[[Run], None]] = []


def register_fake(purpose: str, fn: Callable[[RunSpec], str]) -> None:
    FAKE_RESPONDERS[purpose] = fn


def get(run_id: str) -> Run | None:
    return _RUNS.get(run_id)


def all_runs() -> list[Run]:
    return list(_RUNS.values())


def _register(run: Run) -> None:
    with _RUNS_LOCK:
        _RUNS[run.id] = run
        if len(_RUNS) > MAX_RUNS_KEPT:
            for old in sorted(_RUNS.values(), key=lambda r: r.started)[: len(_RUNS) - MAX_RUNS_KEPT]:
                if old.status != "running":
                    _RUNS.pop(old.id, None)


def _start_event(run: Run) -> dict:
    s = run.spec
    return {"type": "start", "provider": s.provider, "model": s.model, "effort": s.effort, "fast": s.fast,
            "session_id": s.session_id, "purpose": s.purpose, "steerable": run.steerable}


def start(spec: RunSpec) -> Run:
    if config.FAKE_AGENT:
        spec.provider = "fake"
    run = Run(spec=spec)
    run.session_id = spec.session_id
    _register(run)
    if not spec.ephemeral:
        _transcript(spec, "user", spec.user_text or spec.prompt, run.id)
    if spec.provider == "fake":
        threading.Thread(target=_execute, args=(run,), daemon=True, name=f"run-{run.id}").start()
    else:
        run.dir = run_dir(run.id)
        threading.Thread(target=_detached, args=(run, False), daemon=True, name=f"run-{run.id}").start()
    return run


def run_blocking(spec: RunSpec, timeout: float | None = None) -> Run:
    run = start(spec)
    run.wait(timeout if timeout is not None else spec.timeout_s + 30)
    return run


def cancel(run_id: str) -> bool:
    run = _RUNS.get(run_id)
    if not run or run.status != "running":
        return False
    run.cancel_requested = True
    if run.dir is not None and run.dir.is_dir():
        (run.dir / "stop").touch()
    return True


def steer(run_id: str, text: str) -> tuple[str, str | None]:
    """Give a running run one more message from the researcher: ("steered", id) (Claude reads it as soon as the tools
    it is running finish; the run's steer and user events carry the id) or ("restart", None) (Codex: its turn stops
    and the session continues with the message)."""
    run = _RUNS.get(run_id)
    text = (text or "").strip()
    if not run or run.status != "running":
        raise ValueError("this run has ended")
    if not text:
        raise ValueError("the message is empty")
    spec = run.spec
    if run.steerable and run.dir is not None:
        inbox = run.dir / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns()}-{uuid.uuid4().hex[:6]}"
        tmp = inbox / f"{name}.tmp"
        tmp.write_text(json.dumps({"id": name, "text": text}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, inbox / f"{name}.json")
        return "steered", name
    from . import queue
    queue.add(spec.project_id, spec.panel, text, front=True, now=True)
    cancel(run_id)
    return "restart", None


def stop_all(grace: float = 3.0) -> None:
    """Server shutdown. A CLI run is left going (its supervisor is a process of its own; the next server picks it up
    with recover()); only the fake agent, which runs in this process, is stopped."""
    for run in list(_RUNS.values()):
        if run.status == "running" and run.dir is None:
            run.cancel_requested = True


def recover() -> int:
    """Follow every run a previous server started and did not see end (startup). Returns how many."""
    root = runs_root()
    if not root.is_dir():
        return 0
    found = 0
    for d in sorted(root.iterdir()):
        meta = read_json(d / "meta.json", None)
        if not isinstance(meta, dict) or meta.get("finalized") or meta.get("run_id") in _RUNS:
            continue
        try:
            spec = RunSpec(**meta["spec"])
        except (KeyError, TypeError):
            continue
        run = Run(spec=spec, id=meta["run_id"], started=meta.get("started") or time.time())
        run.dir, run.session_id = d, meta.get("session_id") or spec.session_id
        _register(run)
        threading.Thread(target=_detached, args=(run, True), daemon=True, name=f"run-{run.id}").start()
        found += 1
    _prune(root)
    return found


# ------------------------------------------------------------------ the end of a run (both kinds)

def _complete(run: Run) -> None:
    from . import sessions
    spec = run.spec
    ok = run.error is None and not run.cancel_requested
    run.finished = time.time()
    if run.session_id and not spec.ephemeral and spec.provider != "fake":
        try:
            sessions.set_session_id(spec.project_id, spec.panel, spec.provider, run.session_id)
        except Exception:  # noqa: BLE001
            pass
    status = "cancelled" if run.cancel_requested else ("done" if ok else "error")
    if not spec.ephemeral:            # the messages Claude read while it answered come before the answer
        sent_at = {e.get("id"): e.get("at") for e in run.events if e.get("type") == "steer"}
        for e in run.events:
            if e.get("type") == "user" and e.get("id"):
                _transcript(spec, "user", e.get("text", ""), run.id, session_id=run.session_id, steer=True,
                            ts=sent_at.get(e["id"]))
    if not spec.ephemeral and (run.text or status != "done"):
        _transcript(spec, "assistant", run.text, run.id, session_id=run.session_id,
                    status=None if status == "done" else status)
    if run.dir is not None:                   # recorded before anyone hears it ended: a restart never records it twice
        _save_meta(run, finalized=True)
    with run._cond:
        run.status = status
        run.events.append({"type": "done", "ok": ok, "text": run.text, "session_id": run.session_id,
                           "duration_ms": int((run.finished - run.started) * 1000), "cancelled": run.cancel_requested})
        run._cond.notify_all()
    if not spec.ephemeral:
        # The conversation shows runs started from any view (a figure edit, a code explanation): tell it to reload.
        try:
            from ..events import hub
            hub.publish(spec.project_id, "agent", {"run_id": run.id, "status": run.status, "purpose": spec.purpose})
        except Exception:  # noqa: BLE001 — an event failure must not fail the run
            pass
    for hook in FINISH_HOOKS:
        try:
            hook(run)
        except Exception:  # noqa: BLE001 — a hook must not fail the run
            log.exception("a run's finish hook failed")


def _transcript(spec: RunSpec, role: str, text: str, run_id: str, session_id: str | None = None,
                status: str | None = None, steer: bool = False, ts: str | None = None) -> None:
    from ..projects import research_dir
    entry = {"ts": ts or now_iso(), "panel": spec.panel, "provider": spec.provider, "session_id": session_id or spec.session_id,
             "role": role, "text": text, "run_id": run_id, "purpose": spec.purpose}
    if status:
        entry["status"] = status          # cancelled | error: the answer was cut short
    if steer:
        entry["steer"] = True             # sent into a running turn
    try:
        append_jsonl(research_dir(spec.project_id) / "context" / "transcripts" / f"{spec.panel}.jsonl", entry)
    except Exception:  # noqa: BLE001 — a transcript failure must not fail the run
        pass


# ------------------------------------------------------------------ the fake agent (in this process)

def _execute(run: Run) -> None:
    from . import sessions
    spec = run.spec
    lock = sessions.session_lock(spec.provider, None if spec.ephemeral else spec.session_id)
    with lock or contextlib.nullcontext():
        run.emit(_start_event(run))
        try:
            if not run.cancel_requested:      # cancelled while it waited for the session
                _run_fake(run)
        except Exception as e:  # noqa: BLE001 — every failure must reach the client as an event
            run.error = str(e)
            run.emit({"type": "error", "message": str(e)})
    _complete(run)


def _run_fake(run: Run) -> None:
    spec = run.spec
    responder = FAKE_RESPONDERS.get(spec.purpose)
    answer = responder(spec) if responder else (
        f"(fake {spec.purpose} agent) I received {len(spec.prompt)} characters in panel `{spec.panel}`.\n\n"
        f"Start of the request:\n\n> {spec.prompt[:240].strip()}")
    if not spec.ephemeral:
        run.session_id = spec.session_id or f"fake-{uuid.uuid4()}"
        run.emit({"type": "session", "session_id": run.session_id})
    run.emit({"type": "thinking"})
    for i in range(0, len(answer), 48):
        if run.cancel_requested:
            return
        chunk = answer[i:i + 48]
        run.text += chunk
        run.emit({"type": "text", "delta": chunk})
        time.sleep(0.01)
    run.emit({"type": "usage", "input": len(spec.prompt) // 4, "output": len(answer) // 4, "cache_read": 0, "cost": 0})


# ------------------------------------------------------------------ CLI runs (durable, followed from their folder)

def runs_root() -> Path:
    return config.LOCAL_DIR / "runs"


def run_dir(run_id: str) -> Path:
    return runs_root() / run_id


def _save_meta(run: Run, finalized: bool = False) -> None:
    assert run.dir is not None
    write_json(run.dir / "meta.json", {"run_id": run.id, "spec": asdict(run.spec), "started": run.started,
                                       "session_id": run.session_id, "finalized": finalized})


def _detached(run: Run, recovered: bool) -> None:
    from . import sessions
    spec = run.spec
    lock = sessions.session_lock(spec.provider, None if spec.ephemeral else spec.session_id)
    with lock or contextlib.nullcontext():
        run.emit(_start_event(run))
        try:
            if not recovered:
                if run.cancel_requested:      # stopped while it waited for the session: never started
                    _complete(run)
                    return
                _spawn(run)
            _follow(run)
        except Exception as e:  # noqa: BLE001 — every failure must reach the client as an event
            run.error = run.error or str(e)
            run.emit({"type": "error", "message": str(e)})
        _complete(run)


def _spawn(run: Run) -> None:
    spec, d = run.spec, run.dir
    assert d is not None
    d.mkdir(parents=True, exist_ok=True)
    cmd = build_command(spec, str(d))
    write_json(d / "spec.json", {"cmd": cmd, "cwd": spec.cwd, "input": "stream-json" if spec.provider == "claude" else "text",
                                 "prompt": _prompt_for(spec), "timeout_s": spec.timeout_s})
    _save_meta(run)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SERVER_DIR), env.get("PYTHONPATH")) if p)
    with open(d / "supervisor.log", "ab") as out:
        run.supervisor = subprocess.Popen([sys.executable, "-m", "research_deck.agents.supervise", str(d)], cwd=str(d),
                                          env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                          start_new_session=True, close_fds=True)


def _supervisor_alive(run: Run) -> bool:
    if run.supervisor is not None:              # started by this server: poll() also reaps it
        return run.supervisor.poll() is None
    assert run.dir is not None
    try:
        pid = int((run.dir / "pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _follow(run: Run) -> None:
    """Parse the CLI's output as the supervisor writes it, until the supervisor says the CLI ended."""
    d = run.dir
    assert d is not None
    parser: ClaudeParser | CodexParser = ClaudeParser(run) if run.spec.provider == "claude" else CodexParser(run)
    out, offset, buf = d / "out.jsonl", 0, ""
    started, gone_since = time.monotonic(), None
    while True:
        if run.cancel_requested and not (d / "stop").exists():
            (d / "stop").touch()
        data = ""
        try:
            with open(out, encoding="utf-8") as f:
                f.seek(offset)
                data = f.read()
                offset = f.tell()
        except FileNotFoundError:
            pass
        if data:
            buf += data
            *lines, buf = buf.split("\n")
            for line in lines:
                _feed(parser, line)
            continue
        exit_info = read_json(d / "exit.json", None)
        if isinstance(exit_info, dict):
            # The supervisor writes exit.json after the last line: read what came between our read and this check.
            try:
                with open(out, encoding="utf-8") as f:
                    f.seek(offset)
                    buf += f.read()
            except FileNotFoundError:
                pass
            *lines, buf = buf.split("\n")
            for line in lines:
                _feed(parser, line)
            break
        if _supervisor_alive(run):
            gone_since = None
        elif time.monotonic() - started > 5:
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since > 2:
                exit_info = {"code": None, "lost": True}
                break
        time.sleep(0.2)
    _feed(parser, buf)
    if run.supervisor is not None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            run.supervisor.wait(5)
    if exit_info.get("stopped"):
        run.cancel_requested = True
    elif exit_info.get("timed_out"):
        run.error = f"timed out after {run.spec.timeout_s}s"
        run.emit({"type": "error", "message": run.error})
    elif exit_info.get("lost"):
        run.error = "the agent stopped without finishing (its supervisor ended unexpectedly)"
        run.emit({"type": "error", "message": run.error})
    if not run.cancel_requested and run.error is None:
        if not parser.finished:
            tail = _tail(d / "err.log")
            run.error = parser.failure or tail or f"{run.spec.provider} exited with code {exit_info.get('code')}"
            run.emit({"type": "error", "message": run.error})
        elif parser.failure:
            run.error = parser.failure
            run.emit({"type": "error", "message": parser.failure})
    _requeue_unread(run)


def _feed(parser: ClaudeParser | CodexParser, line: str) -> None:
    line = line.strip()
    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if isinstance(event, dict):
        parser.feed(event)


def _tail(path: Path, limit: int = 1500) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[-limit:]
    except OSError:
        return ""


def _requeue_unread(run: Run) -> None:
    """Messages steered in that Claude never read go first in the conversation's queue, in the order they were sent:
    those still in the inbox (the CLI had stopped reading), and, when the run was stopped, those handed over but
    dropped by the interrupt. They start next when the answer finished, and wait for the researcher when it was
    stopped. (A finished run read everything it was handed: Claude answers every message before it ends.)"""
    assert run.dir is not None
    left = sorted((run.dir / "inbox").glob("*.json")) if (run.dir / "inbox").is_dir() else []
    texts: list[str] = []
    if run.cancel_requested:
        held = {f.stem for f in left}
        read = {e.get("id") for e in run.events if e.get("type") == "user" and e.get("id")}
        texts += [e.get("text", "") for e in run.events
                  if e.get("type") == "steer" and e.get("id") not in read and e.get("id") not in held]
    for f in left:
        texts.append((read_json(f, None) or {}).get("text") or "")
        f.unlink(missing_ok=True)
    if run.spec.ephemeral:
        return
    from . import queue
    for text in reversed([t for t in texts if t.strip()]):
        queue.add(run.spec.project_id, run.spec.panel, text, front=True)


def _prune(root: Path) -> None:
    done = []
    for d in root.iterdir():
        meta = read_json(d / "meta.json", None)
        if isinstance(meta, dict) and meta.get("finalized"):
            done.append((meta.get("started") or 0, d))
    for _, d in sorted(done)[: max(0, len(done) - MAX_RUNS_KEPT)]:
        shutil.rmtree(d, ignore_errors=True)


def _mcp_server_def(spec: RunSpec) -> dict:
    return {"command": sys.executable, "args": ["-m", "research_deck.mcp_server", "--project", spec.project_id],
            "env": {"PYTHONPATH": str(config.APP_ROOT / "server"), "RD_URL": f"http://{config.HOST}:{config.PORT}",
                    "RD_LOCAL_DIR": str(config.LOCAL_DIR),
                    # the MCP server reads the agent token from RD_LOCAL_DIR and sends this identity (actors.py)
                    "RD_ACTOR": f"agent:{spec.provider}:{(spec.session_id or spec.panel)[:12]}"}}


def build_command(spec: RunSpec, tmpdir: str) -> list[str]:
    if spec.provider == "claude":
        if not config.CLAUDE_CLI:
            raise RuntimeError("Claude Code CLI not found (set RD_CLAUDE_CLI)")
        # --restricted: no code-running tools or WebFetch, file tools confined to the project folder, and the
        # project's own .claude/settings.json (hooks) and the user's settings are not loaded. --strict-mcp-config:
        # only the research-deck MCP server. Together they make "read" and "write" real boundaries.
        # --input-format stream-json: the supervisor writes the prompt, steering messages and the interrupt on stdin;
        # --replay-user-messages echoes the messages back, so they appear in the stream where Claude read them.
        cmd = [config.CLAUDE_CLI, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--replay-user-messages", "--verbose", "--include-partial-messages",
               "--restricted", "--strict-mcp-config", "--model", spec.model, "--effort", spec.effort]
        if spec.ephemeral:
            cmd += ["--no-session-persistence"]
        elif spec.session_id:
            from .sessions import valid_session_id
            if not valid_session_id(spec.session_id):
                raise RuntimeError(f"refusing an invalid session id: {spec.session_id!r}")
            cmd += ["--resume", spec.session_id]
        if spec.fast:
            cmd += ["--settings", json.dumps({"fastMode": True})]
        if not spec.tools:
            cmd += ["--tools", ""]
        else:
            allowed = WRITE_TOOLS if spec.permission == "write" else READ_TOOLS
            denied = NEVER_TOOLS + ([] if spec.permission == "write" else ["Edit", "Write", "MultiEdit", "NotebookEdit"])
            cmd += ["--permission-mode", "acceptEdits" if spec.permission == "write" else "default",
                    "--allowedTools", ",".join(allowed), "--disallowedTools", ",".join(denied)]
            if spec.mcp:
                path = Path(tmpdir) / "mcp.json"
                path.write_text(json.dumps({"mcpServers": {"research-deck": _mcp_server_def(spec)}}), encoding="utf-8")
                cmd += ["--mcp-config", str(path)]
        if spec.system:
            cmd += ["--append-system-prompt", spec.system]
        return cmd

    if spec.provider == "codex":
        if not config.CODEX_CLI:
            raise RuntimeError("Codex CLI not found (set RD_CODEX_CLI)")
        # A tool-less run (review passes, summaries) is always read-only, whatever the panel's permission.
        sandbox = "workspace-write" if spec.permission == "write" and spec.tools else "read-only"
        # --ignore-user-config: the user's MCP servers, notify hook and plugins stay out of dashboard runs (they would
        # run outside the sandbox with approvals off); auth still comes from CODEX_HOME.
        common = ["--json", "--skip-git-repo-check", "--ignore-user-config", "-m", spec.model,
                  "-c", f"model_reasoning_effort={json.dumps(spec.effort)}",
                  "-c", f'service_tier="{"priority" if spec.fast else "default"}"',
                  "-c", 'approval_policy="never"']
        if spec.tools and spec.mcp:
            m = _mcp_server_def(spec)
            env = "{" + ", ".join(f"{k} = {json.dumps(v)}" for k, v in m["env"].items()) + "}"
            common += ["-c", f"mcp_servers.research_deck.command={json.dumps(m['command'])}",
                       "-c", f"mcp_servers.research_deck.args={json.dumps(m['args'])}",
                       "-c", f"mcp_servers.research_deck.env={env}",
                       # exec has no one to ask; the server itself enforces agent permissions (proposals, no locks)
                       "-c", 'mcp_servers.research_deck.default_tools_approval_mode="approve"']
        if spec.session_id and not spec.ephemeral:
            from .sessions import valid_session_id
            if not valid_session_id(spec.session_id):
                raise RuntimeError(f"refusing an invalid session id: {spec.session_id!r}")
            return [config.CODEX_CLI, "exec", "resume", *common, "-c", f'sandbox_mode="{sandbox}"', spec.session_id, "-"]
        return [config.CODEX_CLI, "exec", *common, "--sandbox", sandbox, *(["--ephemeral"] if spec.ephemeral else []), "-"]

    raise RuntimeError(f"unknown provider: {spec.provider}")


def _prompt_for(spec: RunSpec) -> str:
    # Codex exec has no flag for an appended system prompt; it reads the instructions at the head of the turn.
    if spec.provider == "codex" and spec.system:
        return f"<instructions>\n{spec.system}\n</instructions>\n\n{spec.prompt}"
    return spec.prompt


# ------------------------------------------------------------------ stream parsers

def _user_text(message: dict) -> str | None:
    """The text of a user message the CLI echoed back (--replay-user-messages); None for tool results."""
    content = (message or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(isinstance(b, dict) and b.get("type") == "text" for b in content):
        return "".join(b.get("text", "") for b in content)
    return None


class ClaudeParser:
    def __init__(self, run: Run):
        self.run, self.finished, self.failure, self.streamed, self.last_beat = run, False, None, False, 0.0
        self.prompt = _prompt_for(run.spec).strip()   # echoed back when Claude reads it, like every message
        self.prompt_echoed = False
        self.sent: list[dict] = []   # steered messages handed to Claude: {"id", "text", "read"}
        self.prior = ""              # the answers of the turns already finished in this run
        self.after_result = False

    def text(self, delta: str) -> None:
        if delta:
            if self.after_result:        # a new turn (a message that arrived after the last one ended)
                self.after_result = False
                if self.run.text:
                    self.run.text += "\n\n"
                    self.run.emit({"type": "text", "delta": "\n\n"})
            self.run.text += delta
            self.run.emit({"type": "text", "delta": delta})

    def feed(self, e: dict) -> None:
        kind = e.get("type")
        if kind == "system" and e.get("subtype") == "init":
            sid = e.get("session_id")
            if sid and not self.run.spec.ephemeral:
                self.run.session_id = sid
                self.run.emit({"type": "session", "session_id": sid})
        elif kind == "rd_sent":                      # the supervisor handed Claude a steered message
            self.sent.append({"id": e.get("id"), "text": (e.get("text") or "").strip(), "read": False})
            self.run.emit({"type": "steer", "id": e.get("id"), "text": e.get("text") or "", "at": e.get("at")})
        elif kind == "user" and e.get("isReplay") and not e.get("isSynthetic"):
            # Claude's echo of a message it read (tool results and the CLI's own user-role content are not echoes)
            text = (_user_text(e.get("message") or {}) or "").strip()
            if not text:
                return
            if not self.prompt_echoed and text == self.prompt:
                self.prompt_echoed = True
                return
            match = next((m for m in self.sent if not m["read"] and m["text"] == text), None)
            if match:
                match["read"] = True
                self.run.emit({"type": "user", "id": match["id"], "text": text})
        elif kind == "stream_event":
            inner = e.get("event") or {}
            delta = inner.get("delta") or {}
            if delta.get("type") == "text_delta":
                self.streamed = True
                self.text(delta.get("text", ""))
            elif delta.get("type") == "thinking_delta" and time.monotonic() - self.last_beat > 1:
                self.last_beat = time.monotonic()
                self.run.emit({"type": "thinking"})
        elif kind == "assistant":
            for block in (e.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    self.run.emit({"type": "tool", "name": block.get("name", "tool"), "detail": _short(block.get("input"))})
                elif block.get("type") == "text" and not self.streamed:
                    self.text(block.get("text", ""))
        elif kind == "result":
            self.finished = True
            u = e.get("usage") or {}
            self.run.emit({"type": "usage", "input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                           "cache_read": u.get("cache_read_input_tokens", 0), "cost": e.get("total_cost_usd")})
            if e.get("session_id") and not self.run.spec.ephemeral:
                self.run.session_id = e["session_id"]
            if e.get("is_error") and not self.run.cancel_requested:
                self.failure = e.get("result") or "Claude did not answer"
            elif e.get("result"):
                self.run.text = (self.prior + "\n\n" if self.prior else "") + e["result"]
            self.prior = self.run.text
            self.streamed = False
            self.after_result = True


class CodexParser:
    def __init__(self, run: Run):
        self.run, self.finished, self.failure = run, False, None

    def feed(self, e: dict) -> None:
        kind = e.get("type")
        if kind == "thread.started":
            sid = e.get("thread_id")
            if sid and not self.run.spec.ephemeral:
                self.run.session_id = sid
                self.run.emit({"type": "session", "session_id": sid})
        elif kind in ("item.started", "item.completed"):
            item = e.get("item") or {}
            t = item.get("type")
            if kind == "item.completed" and t == "agent_message":
                text = item.get("text", "")
                if self.run.text:
                    text = "\n\n" + text
                self.run.text += text
                self.run.emit({"type": "text", "delta": text})
            elif t == "reasoning":
                self.run.emit({"type": "thinking", "text": (item.get("text") or "")[:400] if kind == "item.completed" else None})
            elif kind == "item.started" and t == "command_execution":
                self.run.emit({"type": "tool", "name": "shell", "detail": _short(item.get("command"))})
            elif kind == "item.completed" and t == "file_change":
                paths = [c.get("path") for c in item.get("changes") or []]
                self.run.emit({"type": "tool", "name": "edit", "detail": ", ".join(p for p in paths if p)})
            elif kind == "item.started" and t == "mcp_tool_call":
                self.run.emit({"type": "tool", "name": f"{item.get('server')}.{item.get('tool')}", "detail": _short(item.get("arguments"))})
            elif kind == "item.started" and t == "web_search":
                self.run.emit({"type": "tool", "name": "web_search", "detail": _short(item.get("query"))})
        elif kind == "turn.completed":
            self.finished = True
            u = e.get("usage") or {}
            self.run.emit({"type": "usage", "input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                           "cache_read": u.get("cached_input_tokens", 0), "cost": None})
        elif kind in ("turn.failed", "error"):
            err = e.get("error") or e
            self.failure = err.get("message") if isinstance(err, dict) else str(err)


def _short(value, limit: int = 160) -> str:
    if value is None:
        return ""
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return s if len(s) <= limit else s[: limit - 1] + "…"
