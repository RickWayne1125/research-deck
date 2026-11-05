"""A run's log for the terminal view: GET …/experiments/{eid}/logs/stream (Server-Sent Events) and …/logs/raw.

GET …/logs (records.read_logs) pages complete lines, which suits agents and the record's tail; the terminal
(web/src/panels/experiments/LogTerminal.tsx) wants the raw text instead — ANSI escapes, carriage-return progress
bars and all — as the file grows.

  stream  ?offset=  < 0 (the default): from the tail, the last TAIL_BYTES cut at a line start; ≥ 0: from that byte.
          Last-Event-ID (EventSource's own reconnect) wins over ?offset=, so a reconnect resumes where it stopped.
          retry: RETRY_MS, then the events
            meta    {source: file|none, live, path?, missing?, size, start, truncated_before}; sent again when
                    the file appears or disappears, or the record's log moves (after a reset)
            data    {data, offset}   id = offset = the byte offset after `data`, always at a character boundary
            reset   {offset: 0}      id 0; the file shrank or was replaced (rotation, truncation): clear, start over
            eof     {offset, status} the run is not live and everything was sent; the stream ends
          and ": keep-alive" comments every KEEPALIVE_S while nothing else is sent. While the record is live
          (queued / running) the file is polled every POLL_S. The stream also
          ends, without eof, when the client goes away or the server shuts down; EventSource then reconnects.
  raw     the whole log as text/plain (an attachment named <eid>.log), at most RAW_MAX_BYTES: a longer log is cut to
          its end at a line start, under a one-line note that says so.

Bytes are decoded as UTF-8 incrementally, so a multi-byte character is never split between two events (an invalid
byte becomes U+FFFD); memory stays within CHUNK_BYTES per event and TICK_BYTES per poll. Paths go through
util.safe_join.
"""
from __future__ import annotations

import asyncio
import codecs
import errno
import json
import logging
import os
import signal
import stat
import threading
import time
from pathlib import Path
from typing import AsyncIterator, Awaitable, BinaryIO, Callable

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..projects import project_root
from ..util import rel_to, safe_join
from . import records

log = logging.getLogger("research_deck.experiments.logstream")

POLL_S = 0.5
KEEPALIVE_S = 15.0
RETRY_MS = 2000
TAIL_BYTES = 256 * 1024
CHUNK_BYTES = 64 * 1024          # the most text one data event carries
TICK_BYTES = 1024 * 1024         # the most one poll reads before the record's status is looked at again
RAW_MAX_BYTES = 20 * 1024 * 1024
RAW_CUT_WINDOW = 1024 * 1024     # where a cut raw download looks for its first line start
# Followed while the run may still write. "unknown" (a Deck job that lost contact) is not: its stream would stay open
# for as long as the operator takes; it ends with eof and the client reconnects when the record changes.
LIVE = frozenset({"queued", "running"})

Event = tuple[str, dict, int | None]       # (event name, data, id)

_STOP = threading.Event()


def stop_streams() -> None:
    """Make every open log stream end at its next poll (tests; a server that embeds the app and stops it)."""
    _STOP.set()


def shutting_down() -> bool:
    if _STOP.is_set():
        return True
    # uvicorn (≥ 0.29) serves with its Server.handle_exit installed as the SIGINT/SIGTERM handler, and `should_exit`
    # turns on at the first signal — while uvicorn still waits (timeout_graceful_shutdown) for open responses to end.
    server = getattr(signal.getsignal(signal.SIGTERM), "__self__", None)
    return getattr(server, "should_exit", False) is True


async def _idle(seconds: float) -> None:
    """The wait between two polls once everything was sent (tests replace it to change the file in between)."""
    await asyncio.sleep(seconds)


def _event(name: str, data: dict, id_: int | None = None) -> str:
    head = f"id: {id_}\n" if id_ is not None else ""
    return f"{head}event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def start_offset(offset: int, last_event_id: str | None) -> int:
    """Where a stream starts: after the last data event the client saw (its id), else at ?offset=."""
    try:
        resume = int((last_event_id or "").strip())
    except ValueError:
        return offset
    return resume if resume >= 0 else offset


# ------------------------------------------------------------------ where the log is

def _source(pid: str, rec: dict) -> dict:
    """{"kind": "file", "path", "rel"} | {"kind": "none"}; 400 for a path outside the project."""
    if rec.get("logs"):
        root = project_root(pid)
        target = safe_join(root, rec["logs"])
        return {"kind": "file", "path": target, "rel": rel_to(root, target)}
    return {"kind": "none"}


def _source_key(rec: dict) -> tuple:
    return (rec.get("logs"),)


def _continuations(head: bytes) -> int:
    """How many UTF-8 continuation bytes (10xxxxxx) `head` starts with, at most 3: the bytes before the next character."""
    n = 0
    while n < min(len(head), 3) and head[n] & 0xC0 == 0x80:
        n += 1
    return n


def _line_start(f: BinaryIO, start: int, end: int, window: int) -> int:
    """The first line start at or after `start` (a carriage return counts: progress bars rewrite their line) within
    `window` bytes and before `end`; else the first character boundary at or after `start`."""
    if start <= 0:
        return 0
    f.seek(start - 1)
    buf = f.read(min(window, end - start) + 1)       # buf[0] is the byte before `start`
    head = buf[: end - start]                        # a separator that is the last byte opens no line to show
    for sep in (b"\n", b"\r"):
        i = head.find(sep)
        if i >= 0:
            return start + i
    return start + _continuations(buf[1:4])


def _decoder() -> codecs.IncrementalDecoder:
    return codecs.getincrementaldecoder("utf-8")(errors="replace")


class FileTail:
    """A log file read from a byte offset as it grows; rotation and truncation start it over (a reset event)."""

    def __init__(self, path: Path, want: int):
        self.path, self.want = path, want
        self.pos = 0                                  # the next byte to read
        self.start = 0                                # where reading began (after the tail cut)
        self.size = 0
        self.ident: tuple[int, int] | None = None     # (st_dev, st_ino) of the file being read
        self.decoder = _decoder()
        self.missing = True
        self.truncated_before = False
        self.error: str | None = None

    @property
    def offset(self) -> int:
        """Where a new stream resumes: after the last whole character sent (the decoder holds a partial one)."""
        return self.pos - len(self.decoder.getstate()[0])

    def _first_position(self, f: BinaryIO, size: int) -> int:
        if self.want >= 0:
            if self.want > size:                      # the file shrank since the client's offset
                return 0
            f.seek(self.want)
            return self.want + _continuations(f.read(3))
        start = max(0, size - TAIL_BYTES)
        self.truncated_before = start > 0
        return _line_start(f, start, size, TAIL_BYTES)

    def poll(self, *, final: bool) -> tuple[list[Event], bool]:
        """(events, caught_up): what the file holds beyond what was sent, at most TICK_BYTES. `final` (the run is
        over) also flushes a character the file ends in the middle of, as U+FFFD."""
        out: list[Event] = []
        try:
            if not stat.S_ISREG(self.path.stat().st_mode):    # a FIFO would block the open; a directory is no log
                raise IsADirectoryError(errno.EISDIR, "not a regular file")
            f = self.path.open("rb")
        except (FileNotFoundError, NotADirectoryError):
            self.missing = True                       # not written yet, or between a rotation's rename and create
            return out, True
        except OSError as e:
            if str(e) != self.error:
                out.append(("notice", {"message": f"cannot read the log: {e.strerror or e}"}, None))
            self.error = str(e)
            return out, True
        caught_up = False
        with f:
            st = os.fstat(f.fileno())
            self.missing, self.size, self.error = False, st.st_size, None
            ident = (st.st_dev, st.st_ino)
            if self.ident is None:
                self.ident = ident
                if self.want > st.st_size:
                    out.append(("reset", {"offset": 0}, 0))
                self.pos = self.start = self._first_position(f, st.st_size)
            elif ident != self.ident or st.st_size < self.pos:
                self.ident, self.pos, self.start, self.decoder = ident, 0, 0, _decoder()
                self.truncated_before = False
                out.append(("reset", {"offset": 0}, 0))
            f.seek(self.pos)
            budget = TICK_BYTES
            while budget > 0:
                ask = min(CHUNK_BYTES, budget)
                data = f.read(ask)
                budget -= len(data)
                self.pos += len(data)
                text = self.decoder.decode(data) if data else ""
                if text:
                    out.append(("data", {"data": text, "offset": self.offset}, self.offset))
                if len(data) < ask:                   # a short read of a regular file: its end
                    caught_up = True
                    break
        if caught_up and final:
            rest = self.decoder.decode(b"", final=True)
            if rest:
                out.append(("data", {"data": rest, "offset": self.pos}, self.pos))
        return out, caught_up


def _tail(src: dict, want: int) -> FileTail | None:
    return FileTail(src["path"], want) if src["kind"] == "file" else None


# ------------------------------------------------------------------ the stream

class LogStream:
    """One client's stream of one record's log (see the module docstring)."""

    def __init__(self, pid: str, eid: str, rec: dict, offset: int):
        self.pid, self.eid = pid, eid
        self.status = rec["status"]
        self.key = _source_key(rec)
        self.src = _source(pid, rec)
        self.tail = _tail(self.src, offset)

    @classmethod
    def open(cls, pid: str, eid: str, offset: int) -> "LogStream":
        """404 (project, experiment) and 400 (a log path outside the project) are raised here, before the response."""
        return cls(pid, eid, records.get_state(pid, eid), offset)

    def meta(self, live: bool) -> dict:
        m: dict = {"source": self.src["kind"], "live": live}
        if self.src["kind"] == "file":
            m.update(path=self.src["rel"], missing=self.tail.missing)
        if self.tail is not None:
            m.update(size=self.tail.size, start=self.tail.start, truncated_before=self.tail.truncated_before)
        return m

    def _tick(self) -> tuple[list[Event], bool, bool]:
        """(events, caught_up, live): the record's status first, then what is new in its log, so a run's last
        lines, written before its status changed, are sent before eof."""
        try:
            rec: dict | None = records.get_state(self.pid, self.eid)
        except HTTPException:
            rec = None                                # the record was removed: finish what was there
        moved = False
        if rec is not None:
            self.status = rec["status"]
            if _source_key(rec) != self.key:          # the record's log moved: show the new one from its tail
                self.key, moved = _source_key(rec), True
                try:
                    self.src = _source(self.pid, rec)
                except HTTPException:
                    self.src = {"kind": "none"}
                self.tail = _tail(self.src, -1)
        live = rec is not None and self.status in LIVE
        polled, caught_up = self.tail.poll(final=not live) if self.tail else ([], True)
        if moved:
            polled = [("reset", {"offset": 0}, 0), ("meta", self.meta(live), None), *polled]
        return polled, caught_up, live

    async def events(self, is_disconnected: Callable[[], Awaitable[bool]]) -> AsyncIterator[str]:
        yield f"retry: {RETRY_MS}\n\n"
        evs, caught_up, live = await asyncio.to_thread(self._tick)
        shown = self.meta(live)
        yield _event("meta", shown)
        last = time.monotonic()
        while True:
            for name, data, id_ in evs:
                yield _event(name, data, id_)
                last = time.monotonic()
                if name == "meta":
                    shown = data
            meta = self.meta(live)
            if (meta["source"], meta.get("path"), meta.get("missing")) != (shown["source"], shown.get("path"), shown.get("missing")):
                shown = meta
                yield _event("meta", meta)
            if not live and caught_up:
                yield _event("eof", {"offset": self.tail.offset if self.tail else 0, "status": self.status})
                return
            if caught_up:
                await _idle(POLL_S)
                if time.monotonic() - last >= KEEPALIVE_S:
                    yield ": keep-alive\n\n"
                    last = time.monotonic()
            if shutting_down() or await is_disconnected():
                return
            evs, caught_up, live = await asyncio.to_thread(self._tick)


def stream_response(pid: str, eid: str, offset: int, is_disconnected: Callable[[], Awaitable[bool]]) -> StreamingResponse:
    stream = LogStream.open(pid, eid, offset)
    return StreamingResponse(stream.events(is_disconnected), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ download

def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _note(what: str, size: int, start: int) -> bytes:
    return (f"[research-deck] {what} holds {_size(size)}; this download is its last {_size(size - start)} "
            f"(from byte {start}). Older lines are not included.\n").encode()


def raw_response(pid: str, eid: str) -> StreamingResponse:
    rec = records.get_state(pid, eid)
    src = _source(pid, rec)
    headers = {"Content-Disposition": f'attachment; filename="{eid}.log"', "Cache-Control": "no-store",
               "X-Content-Type-Options": "nosniff"}
    if src["kind"] == "file":
        body = _raw_file(src["path"], src["rel"])
    else:
        raise HTTPException(404, {"message": "this experiment has no log", "reason": "none"})
    return StreamingResponse(body, media_type="text/plain; charset=utf-8", headers=headers)


def _raw_file(path: Path, rel: str):
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise HTTPException(404, {"message": f"{rel} is not a regular file", "reason": "missing"})
        with path.open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            start = _line_start(f, size - RAW_MAX_BYTES, size, RAW_CUT_WINDOW) if size > RAW_MAX_BYTES else 0
    except (FileNotFoundError, NotADirectoryError):
        raise HTTPException(404, {"message": f"log file {rel} does not exist", "reason": "missing"})

    def body():
        if start:
            yield _note(rel, size, start)
        with path.open("rb") as f:
            f.seek(start)
            left = size - start                       # what the file held when the download began
            while left > 0:
                chunk = f.read(min(CHUNK_BYTES, left))
                if not chunk:
                    return
                left -= len(chunk)
                yield chunk
    return body()
