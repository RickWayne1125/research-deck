"""A run's log for the terminal view (experiments/logstream.py): GET …/logs/stream (SSE) and GET …/logs/raw.

The stream's wait between two polls (logstream._idle) runs a script instead of sleeping: each time the stream has
sent everything the file held, the next step changes the file or the record. Every test therefore sees the same
sequence of polls, and a stream that never ends fails the test instead of hanging it.
"""
from __future__ import annotations

import json

import pytest

from research_deck.experiments import logstream, records


@pytest.fixture(autouse=True)
def fresh():
    logstream._STOP.clear()
    yield
    logstream._STOP.clear()


@pytest.fixture
def script(monkeypatch):
    """Steps run one per idle wait of the stream, in order; `script.waits` counts the waits."""
    class Script(list):
        waits = 0

    steps = Script()

    async def idle(seconds: float) -> None:
        steps.waits += 1
        if steps:
            steps.pop(0)()
        elif steps.waits > 100:
            raise AssertionError("the stream did not end")

    monkeypatch.setattr(logstream, "_idle", idle)
    return steps


def url(pid: str, eid: str, rest: str = "") -> str:
    return f"/api/projects/{pid}/experiments/{eid}/logs{rest}"


def record(client, pid: str, **changes) -> str:
    e = client.post(f"/api/projects/{pid}/experiments", json={"title": "run"}).json()
    if changes:
        r = client.patch(f"/api/projects/{pid}/experiments/{e['id']}", json=changes)
        assert r.status_code == 200, r.text
    return e["id"]


def parse(body: str) -> list[tuple[str, dict | None, str | None]]:
    """The SSE frames as (event, data, id); `retry:` as ("retry", None, ms) and comments as (":", None, text)."""
    out = []
    for frame in body.split("\n\n"):
        if not frame:
            continue
        if frame.startswith(":"):
            out.append((":", None, frame[1:].strip()))
            continue
        fields = dict(line.split(": ", 1) for line in frame.split("\n"))
        if "event" in fields:
            out.append((fields["event"], json.loads(fields["data"]), fields.get("id")))
        else:
            out.append(("retry", None, fields.get("retry")))
    return out


def stream(client, pid: str, eid: str, **kw) -> list:
    r = client.get(url(pid, eid, "/stream"), **kw)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream") and r.headers["cache-control"] == "no-cache"
    return parse(r.text)


def texts(events) -> list[str]:
    return [d["data"] for e, d, _ in events if e == "data"]


def names(events) -> list[str]:
    return [e for e, _, _ in events if e not in ("retry", ":")]


# ------------------------------------------------------------------ the stream

def test_a_finished_log_is_sent_raw_and_ends_with_eof(client, project, script):
    pid, root = project
    raw = b"\x1b[32mok\x1b[0m step 1\r\nloss 0.9\r10%|#    |\r100%|#####|\n"
    (root / "run.log").write_bytes(raw)
    eid = record(client, pid, logs="run.log", status="succeeded")
    ev = stream(client, pid, eid)
    assert ev[0] == ("retry", None, str(logstream.RETRY_MS))
    assert ev[1] == ("meta", {"source": "file", "live": False, "path": "run.log", "missing": False, "size": len(raw),
                              "start": 0, "truncated_before": False}, None)
    assert "".join(texts(ev)) == raw.decode()                # escapes and carriage returns as written
    assert ev[-2][1]["offset"] == len(raw) and ev[-2][2] == str(len(raw))   # id = the next byte offset
    assert ev[-1] == ("eof", {"offset": len(raw), "status": "succeeded"}, None)
    assert script.waits == 0                                 # nothing to wait for


def test_a_running_log_is_followed_until_the_run_ends(client, project, script):
    pid, root = project
    log = root / "logs" / "train.log"
    log.parent.mkdir()
    log.write_text("epoch 1\n")
    eid = record(client, pid, logs="logs/train.log", status="running")

    def append(text):
        def step():
            with log.open("a") as f:
                f.write(text)
        return step

    def last_lines_then_done():
        append("epoch 3\n")()                                # written before the status changes
        records.patch_record(pid, eid, {"status": "succeeded"})

    script += [append("epoch 2 lo"), append("ss=0.4\n"), lambda: None, last_lines_then_done]
    ev = stream(client, pid, eid)
    assert ev[1][1]["live"] is True
    assert texts(ev) == ["epoch 1\n", "epoch 2 lo", "ss=0.4\n", "epoch 3\n"]     # a partial line is sent as it is
    assert [d["offset"] for e, d, _ in ev if e == "data"] == [8, 18, 25, 33]
    assert ev[-1] == ("eof", {"offset": 33, "status": "succeeded"}, None)
    assert script.waits == 4


def test_a_multibyte_character_is_never_split(client, project, script, monkeypatch):
    pid, root = project
    text = "loss ↓ 0.31 · 日本語 ✓\n"
    raw = text.encode()
    cut = raw.index("↓".encode()) + 1                        # inside the arrow's three bytes
    log = root / "run.log"
    log.write_bytes(raw[:cut])
    eid = record(client, pid, logs="run.log", status="running")

    def rest():
        with log.open("ab") as f:
            f.write(raw[cut:])
        records.patch_record(pid, eid, {"status": "succeeded"})

    script.append(rest)
    ev = stream(client, pid, eid)
    assert texts(ev) == ["loss ", "↓ 0.31 · 日本語 ✓\n"]
    assert [d["offset"] for e, d, _ in ev if e == "data"] == [5, len(raw)]   # the first stops before the arrow

    # across reads of a finished log: every event ends on a character boundary; an offset inside a character (`cut`)
    # starts at the next one
    monkeypatch.setattr(logstream, "CHUNK_BYTES", 4)
    for offset, expected in ((0, text), (cut, text[text.index("↓") + 1:])):
        ev = stream(client, pid, eid, params={"offset": offset})
        assert "".join(texts(ev)) == expected and len(texts(ev)) > 5
        for _, d, _ in (e for e in ev if e[0] == "data"):
            raw[: d["offset"]].decode()                      # raises if an offset splits a character

    # a log that ends inside a character, once the run is over: U+FFFD, then eof (nothing waits for the rest)
    log.write_bytes("done é".encode()[:-1])
    ev = stream(client, pid, eid)
    assert "".join(texts(ev)) == "done �" and ev[-1][0] == "eof"


def test_truncation_and_rotation_start_over_with_reset(client, project, script):
    pid, root = project
    log = root / "run.log"
    log.write_text("old 1\nold 2\n")
    eid = record(client, pid, logs="run.log", status="running")

    def truncate():
        log.write_text("new\n")                              # the same file, shorter

    def rotate():
        log.rename(root / "run.log.1")
        log.write_text("rotated, and longer than the old file was\n")   # another file at the path

    script += [truncate, rotate, lambda: records.patch_record(pid, eid, {"status": "failed"})]
    ev = stream(client, pid, eid)
    assert names(ev) == ["meta", "data", "reset", "data", "reset", "data", "eof"]
    resets = [(d, i) for e, d, i in ev if e == "reset"]
    assert resets == [({"offset": 0}, "0"), ({"offset": 0}, "0")]     # id 0: a reconnect resumes the new file
    assert texts(ev) == ["old 1\nold 2\n", "new\n", "rotated, and longer than the old file was\n"]
    assert ev[-1][1] == {"offset": log.stat().st_size, "status": "failed"}


def test_a_missing_log(client, project, script):
    pid, root = project
    eid = record(client, pid, logs="logs/later.log", status="succeeded")
    ev = stream(client, pid, eid)
    assert names(ev) == ["meta", "eof"]
    assert ev[1][1]["missing"] is True and ev[1][1]["path"] == "logs/later.log"

    # while the run is queued the stream waits for the file to appear
    queued = record(client, pid, logs="logs/later.log", status="queued")

    def create():
        (root / "logs").mkdir()
        (root / "logs" / "later.log").write_text("started\n")

    script += [lambda: None, create, lambda: records.patch_record(pid, queued, {"status": "succeeded"})]
    ev = stream(client, pid, queued)
    assert [d["missing"] for e, d, _ in ev if e == "meta"] == [True, False]
    assert texts(ev) == ["started\n"] and ev[-1][0] == "eof"

    # a record without a log, an unknown one, and a log path outside the project
    assert stream(client, pid, record(client, pid))[1:] == [("meta", {"source": "none", "live": False}, None),
                                                            ("eof", {"offset": 0, "status": "planned"}, None)]
    assert client.get(url(pid, "nope", "/stream")).status_code == 404
    outside = record(client, pid)
    path = records.records_dir(pid) / f"{outside}.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "logs": "../outside.log"}))
    assert client.get(url(pid, outside, "/stream")).status_code == 400


def test_the_tail_starts_at_a_line_and_offsets_resume(client, project, monkeypatch):
    monkeypatch.setattr(logstream, "TAIL_BYTES", 64)
    pid, root = project
    lines = [f"line {i:03d}\n" for i in range(40)]             # 9 bytes each
    whole = "".join(lines)
    (root / "big.log").write_text(whole)
    eid = record(client, pid, logs="big.log", status="succeeded")
    ev = stream(client, pid, eid)
    meta = ev[1][1]
    assert meta["truncated_before"] is True and meta["start"] == 297      # 360 - 64 = 296, the next line starts at 297
    assert "".join(texts(ev)) == whole[297:]
    # a byte offset; EventSource's Last-Event-ID wins over the URL's offset
    assert texts(stream(client, pid, eid, params={"offset": 351})) == ["line 039\n"]
    assert texts(stream(client, pid, eid, params={"offset": 0}, headers={"Last-Event-ID": "342"})) == ["line 038\nline 039\n"]
    # an offset past the end (the file shrank since): start over
    ev = stream(client, pid, eid, params={"offset": 10_000})
    assert names(ev)[:2] == ["meta", "reset"] and "".join(texts(ev)) == whole

    # a tail without any newline (one long progress line) starts after a carriage return, else at a character
    bar = "x" * 100 + "".join(f"\r{i}%" for i in range(100))
    (root / "big.log").write_text(bar)
    got = "".join(texts(stream(client, pid, eid)))
    assert bar.endswith(got) and bar[-len(got) - 1] == "\r" and len(got) < 64
    (root / "big.log").write_text("日本語" * 30)
    assert "".join(texts(stream(client, pid, eid))) == "日本語" * 7       # the last 63 bytes that are whole characters


def test_keepalives_and_server_shutdown(client, project, script, monkeypatch):
    monkeypatch.setattr(logstream, "KEEPALIVE_S", 0)
    pid, root = project
    (root / "run.log").write_text("x\n")
    eid = record(client, pid, logs="run.log", status="running")
    script += [lambda: None, logstream.stop_streams]
    ev = stream(client, pid, eid)
    assert (":", None, "keep-alive") in ev
    assert "eof" not in names(ev)                              # ended by the shutdown, not by the run


def test_shutdown_follows_uvicorns_exit_flag(monkeypatch):
    class Server:                                              # uvicorn installs Server.handle_exit for SIGTERM
        should_exit = False

        def handle_exit(self, sig, frame):
            self.should_exit = True

    server = Server()
    monkeypatch.setattr(logstream.signal, "getsignal", lambda sig: server.handle_exit)
    assert logstream.shutting_down() is False
    server.handle_exit(15, None)
    assert logstream.shutting_down() is True


# ------------------------------------------------------------------ download and line pages

def test_the_raw_log_downloads_whole_or_its_end(client, project, monkeypatch):
    pid, root = project
    raw = b"\x1b[1mbold\x1b[0m\nline 2\r50%\r100%\n\xff\n"
    (root / "run.log").write_bytes(raw)
    eid = record(client, pid, logs="run.log", status="succeeded")
    r = client.get(url(pid, eid, "/raw"))
    assert r.status_code == 200 and r.content == raw                    # the bytes as they are
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="{eid}.log"'

    monkeypatch.setattr(logstream, "RAW_MAX_BYTES", 50)
    lines = "".join(f"row {i:02d}\n" for i in range(20))                 # 7 bytes each, 140 in all
    (root / "run.log").write_text(lines)
    note, rest = client.get(url(pid, eid, "/raw")).text.split("\n", 1)
    assert note.startswith("[research-deck] run.log holds 140 B; this download is its last 49 B (from byte 91)")
    assert rest == lines[91:] and rest.startswith("row 13")

    missing = record(client, pid, logs="nope.log", status="succeeded")
    r = client.get(url(pid, missing, "/raw"))
    assert r.status_code == 404 and r.json()["detail"]["reason"] == "missing"
    r = client.get(url(pid, record(client, pid), "/raw"))
    assert r.status_code == 404 and r.json()["detail"]["reason"] == "none"


def test_the_line_pages_show_what_a_terminal_shows(client, project):
    pid, root = project
    (root / "run.log").write_text("\x1b[33mWARNING\x1b[0m slow\n\x1b]0;title\x07step\r\x1b[2K50%\r\x1b[32m100%\x1b[0m\n")
    eid = record(client, pid, logs="run.log", status="succeeded")
    assert client.get(url(pid, eid)).json()["lines"] == ["WARNING slow", "100%"]
    assert client.get(f"/api/projects/{pid}/experiments/{eid}").json()["logs_tail"] == ["WARNING slow", "100%"]
