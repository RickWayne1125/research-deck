"""A run's supervisor: a process of its own that starts the agent CLI, keeps the CLI's stdin, writes everything the CLI
prints into the run's folder, delivers steering messages and the stop request, and ends with the CLI. It runs in a
session of its own, so a server restart or a redeploy leaves the run going; the server follows the folder (runner.py).

    python -m research_deck.agents.supervise <run folder>

The folder (runner.run_dir):
  spec.json   {"cmd": [...], "cwd", "input": "text" | "stream-json", "prompt", "timeout_s"}
  pid         the supervisor's pid
  out.jsonl   the CLI's stdout, line by line, as printed
  err.log     the CLI's stderr
  inbox/      messages for the running turn, <time>-<id>.json {"id", "text"}; each is moved to inbox/sent/ once
              written to the CLI (stream-json only: Claude reads it as soon as the tools it is running finish).
              Before writing one, the supervisor adds {"type": "rd_sent", "id", "text", "at"} to out.jsonl, so the line
              always comes before Claude's echo of the message (--replay-user-messages: printed once Claude reads it)
  stop        present: stop the run. stream-json: an interrupt request, then stdin closed; otherwise SIGINT. Then
              SIGTERM after STOP_GRACE seconds and SIGKILL after twice that.
  exit.json   written last: {"code", "stopped", "timed_out", "at"}

In stream-json mode stdin stays open while the CLI works. Once a turn's result is in, nothing waits in the inbox, no
message went in after that result and the CLI has printed nothing for QUIET seconds, stdin is closed and the CLI ends.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

POLL = 0.2
QUIET = 1.5
STOP_GRACE = 6.0


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


class Supervisor:
    def __init__(self, folder: Path):
        self.dir = folder
        self.spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
        self.stream = self.spec.get("input") == "stream-json"
        self.lock = threading.Lock()
        self.last_output = time.monotonic()
        self.results = 0
        self.sent_after_result = False
        self.stdin_open = True
        self.stopping_since: float | None = None
        self.signalled = 0
        self.timed_out = False
        self.drained = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.out = None
        self.out_lock = threading.Lock()          # whole lines: the reader thread and deliver() both write out.jsonl

    # ------------------------------------------------------------ the CLI

    def write_out(self, line: str) -> None:
        with self.out_lock:
            self.out.write(line if line.endswith("\n") else line + "\n")
            self.out.flush()

    def send(self, message: dict) -> bool:
        if not self.stdin_open or not self.proc or not self.proc.stdin:
            return False
        try:
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, ValueError, OSError):
            self.stdin_open = False
            return False

    def close_stdin(self) -> None:
        if self.stdin_open and self.proc and self.proc.stdin:
            self.stdin_open = False
            try:
                self.proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

    def read(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self.write_out(line)
            with self.lock:
                self.last_output = time.monotonic()
                try:
                    kind = json.loads(line).get("type")
                except (ValueError, AttributeError):
                    kind = None
                if kind == "result":
                    self.results += 1
                    self.sent_after_result = False
        self.drained.set()

    def signal_cli(self, sig: int) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    # ------------------------------------------------------------ the loop

    def start(self) -> int:
        (self.dir / "pid").write_text(str(os.getpid()), encoding="utf-8")
        (self.dir / "inbox" / "sent").mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)               # a nested Claude Code must not think it runs inside another one
        self.out = open(self.dir / "out.jsonl", "a", encoding="utf-8")   # noqa: SIM115 — open for the run's life
        with open(self.dir / "err.log", "a", encoding="utf-8") as err:
            try:
                self.proc = subprocess.Popen(self.spec["cmd"], cwd=self.spec["cwd"], env=env, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8",
                                             bufsize=1, start_new_session=True)
            except OSError as e:
                err.write(f"could not start {self.spec['cmd'][0]}: {e}\n")
                err.flush()
                self.finish(127)
                return 127
            threading.Thread(target=self.read, daemon=True).start()
            prompt = self.spec.get("prompt") or ""
            if self.stream:
                self.send(_user_message(prompt))
            else:
                try:
                    assert self.proc.stdin
                    self.proc.stdin.write(prompt)
                except (BrokenPipeError, OSError):
                    pass
                self.close_stdin()
            deadline = time.monotonic() + float(self.spec.get("timeout_s") or 1800)
            while self.proc.poll() is None:
                time.sleep(POLL)
                if (self.dir / "stop").exists():
                    self.stop()
                elif self.stopping_since is None and time.monotonic() > deadline:
                    self.timed_out = True
                    self.stop()
                self.deliver()
                self.maybe_close()
                self.escalate()
            self.drained.wait(5)
            code = self.proc.returncode
        self.finish(code)
        self.out.close()
        return code

    def deliver(self) -> None:
        if not self.stream or not self.stdin_open or self.stopping_since is not None:
            return
        for f in sorted((self.dir / "inbox").glob("*.json")):
            try:
                msg = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            text = msg.get("text") or ""
            # The mark goes first: Claude cannot echo a message before it has it. A failed write leaves the message in
            # the inbox, where the server finds it when the run ends.
            self.write_out(json.dumps({"type": "rd_sent", "id": msg.get("id") or f.stem, "text": text, "at": _now()},
                                      ensure_ascii=False))
            if self.send(_user_message(text)):
                with self.lock:
                    self.sent_after_result = True
                os.replace(f, self.dir / "inbox" / "sent" / f.name)

    def maybe_close(self) -> None:
        if not self.stream or not self.stdin_open or self.stopping_since is not None:
            return
        with self.lock:
            quiet = time.monotonic() - self.last_output > QUIET
            done = self.results > 0 and not self.sent_after_result
        if done and quiet and not any((self.dir / "inbox").glob("*.json")):
            self.close_stdin()

    def stop(self) -> None:
        if self.stopping_since is not None:
            return
        self.stopping_since = time.monotonic()
        if self.stream and self.stdin_open:
            self.send({"type": "control_request", "request_id": uuid.uuid4().hex,
                       "request": {"subtype": "interrupt", "cancel_queued": True}})
            self.close_stdin()
        else:
            self.signal_cli(signal.SIGINT)

    def escalate(self) -> None:
        if self.stopping_since is None:
            return
        waited = time.monotonic() - self.stopping_since
        if waited > STOP_GRACE and self.signalled == 0:
            self.signalled = 1
            self.signal_cli(signal.SIGINT if self.stream else signal.SIGTERM)
        elif waited > 2 * STOP_GRACE and self.signalled == 1:
            self.signalled = 2
            self.signal_cli(signal.SIGTERM if self.stream else signal.SIGKILL)
        elif waited > 3 * STOP_GRACE and self.signalled == 2:
            self.signalled = 3
            self.signal_cli(signal.SIGKILL)

    def finish(self, code: int) -> None:
        _write_json(self.dir / "exit.json", {"code": code, "stopped": self.stopping_since is not None and not self.timed_out,
                                             "timed_out": self.timed_out, "at": _now()})


def _user_message(text: str) -> dict:
    # With a uuid, Claude accounts for the message: it echoes it back when it reads it (--replay-user-messages).
    return {"type": "user", "message": {"role": "user", "content": text}, "parent_tool_use_id": None,
            "uuid": str(uuid.uuid4())}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m research_deck.agents.supervise <run folder>", file=sys.stderr)
        return 2
    sup = Supervisor(Path(args[0]))
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: sup.stop())          # asked to end: stop the run the same way
    return sup.start()


if __name__ == "__main__":
    sys.exit(main())
