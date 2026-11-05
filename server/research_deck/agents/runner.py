"""Run Claude Code or Codex headless inside a project folder and stream normalized events.

Every panel goes through start(RunSpec): chat in the agent dock, writing review passes, code review and explanation,
figure edits, handoff summaries. A run resumes the panel's bound session unless it is ephemeral (one-shot checks).

Normalized events (also the SSE payloads, see web/src/types.ts AgentEvent):
  start {provider, model, effort, fast, session_id, purpose}
  session {session_id}            the backend assigned or confirmed a session id
  text {delta}                    assistant text (Claude: token deltas; Codex: whole messages)
  thinking {text?}                a heartbeat while the model reasons
  tool {name, detail}             a tool call, shell command, file change or MCP call
  usage {input, output, cache_read, cost}
  error {message}
  done {ok, text, session_id, duration_ms, cancelled?}

Commands (flags verified against Claude Code 2.1.290 and codex-cli 0.166):
  claude -p --output-format stream-json --verbose --include-partial-messages --model M --effort E
         [--resume SID | --no-session-persistence] [--settings {"fastMode":true}] [--permission-mode ...]
         [--allowedTools ...] [--disallowedTools ...] [--mcp-config FILE] [--append-system-prompt S]      prompt on stdin
  codex exec [resume SID] --json --skip-git-repo-check -m M -c model_reasoning_effort="E"
         -c service_tier="priority|default" -c approval_policy="never" (--sandbox X | -c sandbox_mode="X")
         [-c mcp_servers.research_deck.*] [--ephemeral] -                                              prompt on stdin
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..util import append_jsonl, now_iso

READ_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "mcp__research-deck"]
WRITE_TOOLS = READ_TOOLS + ["Edit", "Write", "MultiEdit", "NotebookEdit"]
NEVER_TOOLS = ["Bash"]          # v1: agents driven from the dashboard do not run shell commands
MAX_RUNS_KEPT = 200


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
    process: subprocess.Popen | None = None
    cancel_requested: bool = False
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

    def summary(self) -> dict:
        s = self.spec
        return {"run_id": self.id, "status": self.status, "provider": s.provider, "model": s.model, "effort": s.effort,
                "fast": s.fast, "panel": s.panel, "purpose": s.purpose, "session_id": self.session_id or s.session_id,
                "started": self.started, "finished": self.finished, "error": self.error}


_RUNS: dict[str, Run] = {}
_RUNS_LOCK = threading.Lock()
# purpose -> fn(spec) -> answer text, for RD_FAKE_AGENT=1 (tests, offline demos). Modules register their own.
FAKE_RESPONDERS: dict[str, Callable[[RunSpec], str]] = {}


def register_fake(purpose: str, fn: Callable[[RunSpec], str]) -> None:
    FAKE_RESPONDERS[purpose] = fn


def get(run_id: str) -> Run | None:
    return _RUNS.get(run_id)


def all_runs() -> list[Run]:
    return list(_RUNS.values())


def start(spec: RunSpec) -> Run:
    if config.FAKE_AGENT:
        spec.provider = "fake"
    run = Run(spec=spec)
    run.session_id = spec.session_id
    with _RUNS_LOCK:
        _RUNS[run.id] = run
        if len(_RUNS) > MAX_RUNS_KEPT:
            for old in sorted(_RUNS.values(), key=lambda r: r.started)[: len(_RUNS) - MAX_RUNS_KEPT]:
                if old.status != "running":
                    _RUNS.pop(old.id, None)
    threading.Thread(target=_execute, args=(run,), daemon=True, name=f"run-{run.id}").start()
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
    _kill(run.process)
    return True


def stop_all(grace: float = 3.0) -> None:
    """Server shutdown: TERM every agent's process group, wait, then KILL what is left (synchronously — the daemon
    threads that normally escalate die with the server)."""
    procs = []
    for run in list(_RUNS.values()):
        if run.status == "running":
            run.cancel_requested = True
            if run.process and run.process.poll() is None:
                procs.append(run.process)
                try:
                    os.killpg(run.process.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
    deadline = time.time() + grace
    for proc in procs:
        try:
            proc.wait(max(0.0, deadline - time.time()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


# ------------------------------------------------------------------ execution

def _execute(run: Run) -> None:
    from . import sessions
    spec = run.spec
    lock = sessions.session_lock(spec.provider, None if spec.ephemeral else spec.session_id)
    if not spec.ephemeral:
        _transcript(spec, "user", spec.user_text or spec.prompt, run.id)
    with lock or contextlib.nullcontext():
        run.emit({"type": "start", "provider": spec.provider, "model": spec.model, "effort": spec.effort,
                  "fast": spec.fast, "session_id": spec.session_id, "purpose": spec.purpose})
        try:
            if run.cancel_requested:          # cancelled while it waited for the session
                pass
            elif spec.provider == "fake":
                _run_fake(run)
            else:
                _run_cli(run)
        except Exception as e:  # noqa: BLE001 — every failure must reach the client as an event
            run.error = str(e)
            run.emit({"type": "error", "message": str(e)})
    ok = run.error is None and not run.cancel_requested
    run.finished = time.time()
    if run.session_id and not spec.ephemeral and spec.provider != "fake":
        try:
            sessions.set_session_id(spec.project_id, spec.panel, spec.provider, run.session_id)
        except Exception:  # noqa: BLE001
            pass
    if not spec.ephemeral and run.text:
        _transcript(spec, "assistant", run.text, run.id, session_id=run.session_id)
    with run._cond:
        run.status = "cancelled" if run.cancel_requested else ("done" if ok else "error")
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


def _transcript(spec: RunSpec, role: str, text: str, run_id: str, session_id: str | None = None) -> None:
    from ..projects import research_dir
    try:
        append_jsonl(research_dir(spec.project_id) / "context" / "transcripts" / f"{spec.panel}.jsonl", {
            "ts": now_iso(), "panel": spec.panel, "provider": spec.provider, "session_id": session_id or spec.session_id,
            "role": role, "text": text, "run_id": run_id, "purpose": spec.purpose})
    except Exception:  # noqa: BLE001 — a transcript failure must not fail the run
        pass


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
        cmd = [config.CLAUDE_CLI, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
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


def _run_cli(run: Run) -> None:
    spec = run.spec
    with tempfile.TemporaryDirectory(prefix="rd-run-") as tmpdir:
        cmd = build_command(spec, tmpdir)
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)  # a nested Claude Code must not think it runs inside this one
        proc = subprocess.Popen(cmd, cwd=spec.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", env=env, start_new_session=True, bufsize=1)
        run.process = proc
        if run.cancel_requested:              # cancel() ran between Popen and the assignment above
            _kill(proc)
        errors: list[str] = []
        threading.Thread(target=lambda: errors.extend(proc.stderr), daemon=True).start()
        timer = threading.Timer(spec.timeout_s, lambda: (setattr(run, "error", f"timed out after {spec.timeout_s}s"), _kill(proc)))
        timer.daemon = True
        timer.start()
        try:
            try:
                proc.stdin.write(_prompt_for(spec))
                proc.stdin.close()
            except BrokenPipeError:
                pass
            parser = ClaudeParser(run) if spec.provider == "claude" else CodexParser(run)
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                parser.feed(event)
            code = proc.wait()
        finally:
            timer.cancel()
        if run.cancel_requested:
            return
        if run.error is None and not parser.finished:
            tail = "".join(errors[-20:]).strip()
            run.error = parser.failure or (tail[-1500:] if tail else f"{spec.provider} exited with code {code}")
            run.emit({"type": "error", "message": run.error})
        elif parser.failure and run.error is None:
            run.error = parser.failure
            run.emit({"type": "error", "message": parser.failure})


def _kill(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    def hard():
        time.sleep(3)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    threading.Thread(target=hard, daemon=True).start()


# ------------------------------------------------------------------ stream parsers

class ClaudeParser:
    def __init__(self, run: Run):
        self.run, self.finished, self.failure, self.streamed, self.last_beat = run, False, None, False, 0.0

    def text(self, delta: str) -> None:
        if delta:
            self.run.text += delta
            self.run.emit({"type": "text", "delta": delta})

    def feed(self, e: dict) -> None:
        kind = e.get("type")
        if kind == "system" and e.get("subtype") == "init":
            sid = e.get("session_id")
            if sid and not self.run.spec.ephemeral:
                self.run.session_id = sid
                self.run.emit({"type": "session", "session_id": sid})
        elif kind == "stream_event":
            inner = e.get("event") or {}
            delta = inner.get("delta") or {}
            if delta.get("type") == "text_delta":
                self.streamed = True
                self.text(delta.get("text", ""))
            elif delta.get("type") == "thinking_delta" and time.monotonic() - self.last_beat > 1:
                self.last_beat = time.monotonic()
                self.run.emit({"type": "thinking"})
            elif inner.get("type") == "content_block_stop" and self.streamed and self.run.text and not self.run.text.endswith("\n"):
                pass
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
            if e.get("is_error"):
                self.failure = e.get("result") or "Claude did not answer"
            elif e.get("result"):
                self.run.text = e["result"]


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
