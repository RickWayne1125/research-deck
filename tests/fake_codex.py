#!/usr/bin/env python3
"""A stand-in for `codex exec [resume <id>] --json … -`, for tests. Standard library only.

It reads the prompt from stdin, prints thread.started (the resumed id, or a new one), then RD_FAKE_CODEX_PIECES
agent messages (default 4) RD_FAKE_CODEX_STEP seconds apart (default 0.05) and turn.completed. SIGINT ends it at once,
as Ctrl-C ends a Codex turn.
"""
import json
import os
import signal
import sys
import time
import uuid


def out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    if sys.argv[1:] == ["--version"]:
        print("codex-cli 0.166.0 [stand-in]")
        return 0
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    args = sys.argv[1:]
    sid = args[-2] if "resume" in args else str(uuid.uuid4())     # `exec resume … <id> -`: the id comes before "-"
    prompt = sys.stdin.read()
    step = float(os.environ.get("RD_FAKE_CODEX_STEP", "0.05"))
    pieces = int(os.environ.get("RD_FAKE_CODEX_PIECES", "4"))
    out({"type": "thread.started", "thread_id": sid})
    for i in range(pieces):
        out({"type": "item.completed", "item": {"type": "agent_message", "text": f"codex {i + 1} on: {prompt.strip()[-40:]}"}})
        time.sleep(step)
    out({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 7}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
