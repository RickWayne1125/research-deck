#!/usr/bin/env python3
"""A stand-in for `claude -p --input-format stream-json --output-format stream-json …`, for tests and for trying the
conversation offline (RD_CLAUDE_CLI=tests/fake_claude.py). Standard library only.

It reads JSON lines on stdin and answers each user message in a turn of its own, in RD_FAKE_CLAUDE_PIECES pieces
(default 6) RD_FAKE_CLAUDE_STEP seconds apart (default 0.05), with one tool call halfway. A message that arrives while
a turn runs is read at its next step, as Claude reads a steering message once its tools finish: the answer goes on
with "(read: …)"; one still unread when the turn ends starts a turn of its own. An interrupt control request ends the
turn at once and drops what was not read. With --replay-user-messages each user message is echoed back (isReplay)
when it is read, as Claude does. --resume <id> keeps that session id. It ends at EOF.
"""
import json
import os
import select
import sys
import time
import uuid


def out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def text_of(msg: dict) -> str:
    content = (msg.get("message") or {}).get("content")
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def main() -> int:
    if sys.argv[1:] == ["--version"]:
        print("2.1.290 (Claude Code) [stand-in]")
        return 0
    args = sys.argv[1:]
    sid = args[args.index("--resume") + 1] if "--resume" in args else str(uuid.uuid4())
    replay = "--replay-user-messages" in args
    step = float(os.environ.get("RD_FAKE_CLAUDE_STEP", "0.05"))
    pieces = int(os.environ.get("RD_FAKE_CLAUDE_PIECES", "6"))
    out({"type": "system", "subtype": "init", "session_id": sid})
    state = {"buf": "", "eof": False}

    def read(timeout: float) -> list[dict]:
        if state["eof"]:
            return []
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return []
        chunk = os.read(sys.stdin.fileno(), 65536).decode()
        if not chunk:
            state["eof"] = True
            return []
        state["buf"] += chunk
        *lines, state["buf"] = state["buf"].split("\n")
        return [json.loads(line) for line in lines if line.strip()]

    pending: list[str] = []
    while True:
        for m in read(0.3 if not pending else 0):
            if m.get("type") == "user":
                pending.append(text_of(m))
        if not pending:
            if state["eof"]:
                return 0
            continue
        prompt = pending.pop(0)
        if replay:
            out({"type": "user", "message": {"role": "user", "content": prompt}, "session_id": sid, "isReplay": True})
        answer, steered, interrupted = [], [], False
        for i in range(pieces):
            for m in read(0):
                if m.get("type") == "control_request" and (m.get("request") or {}).get("subtype") == "interrupt":
                    interrupted = True
                elif m.get("type") == "user":
                    steered.append(text_of(m))
            if interrupted:
                break
            if steered and replay:      # read at this step: echoed now (a tool result is a user message, not an echo)
                out({"type": "user", "message": {"role": "user", "content": steered[0]}, "session_id": sid, "isReplay": True})
            piece = f"(read: {steered.pop(0)}) " if steered else f"piece {i + 1} "
            out({"type": "stream_event", "event": {"type": "content_block_delta",
                                                    "delta": {"type": "text_delta", "text": piece}}})
            answer.append(piece)
            if i == pieces // 2:
                out({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "notes/idea.md"}}]}})
                out({"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "the notes"}]}, "session_id": sid})
            time.sleep(step)
        out({"type": "result", "subtype": "error_during_execution" if interrupted else "success",
             "is_error": interrupted, "result": "".join(answer).strip(), "session_id": sid,
             "usage": {"input_tokens": 10, "output_tokens": 20}, "total_cost_usd": 0})
        if interrupted:
            pending.clear()             # cancel_queued: what was not read is dropped
        else:
            pending[:0] = steered       # not read in this turn: each starts a turn of its own


if __name__ == "__main__":
    sys.exit(main())
