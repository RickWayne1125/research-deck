"""Experiments and resources routes (docs/API.md § Experiments and resources).

Records are read and written here. Nothing in this package submits, cancels or dispatches a run: a queued run waits
as a record until something outside Research Deck runs it. Resources are labeled demo data (demo.py).

Besides the documented routes, a run's log is served for the terminal view (logstream.py):
  GET …/experiments/{eid}/logs/stream?offset=   SSE of the raw log text as it grows (events meta, data {data, offset},
                                                reset, notice, eof; Last-Event-ID resumes); offset < 0 = the tail
  GET …/experiments/{eid}/logs/raw              the whole log as a text/plain attachment, at most its last 20 MB
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ..actors import actor_of
from . import demo, logstream, records

router = APIRouter(tags=["experiments"])
P = "/api/projects/{pid}/experiments"


@router.get(P)
def list_experiments(pid: str):
    return records.list_records(pid)


@router.post(P)
def create_experiment(pid: str, body: records.CreateBody, request: Request):
    return records.create_record(pid, body, actor_of(request))


@router.get(P + "/{eid}")
def get_experiment(pid: str, eid: str):
    return records.get_record(pid, eid)


@router.patch(P + "/{eid}")
def patch_experiment(pid: str, eid: str, body: dict, request: Request):
    return records.patch_record(pid, eid, body, actor_of(request))


@router.get(P + "/{eid}/logs")
def experiment_logs(pid: str, eid: str, offset: int = Query(0, description="byte offset; negative = the tail")):
    rec = records.get_record(pid, eid, tail=False)
    return records.read_logs(pid, rec, offset)


@router.get(P + "/{eid}/logs/stream")
def experiment_log_stream(pid: str, eid: str, request: Request,
                          offset: int = Query(-1, description="byte offset; negative = the tail")):
    start = logstream.start_offset(offset, request.headers.get("last-event-id"))
    return logstream.stream_response(pid, eid, start, request.is_disconnected)


@router.get(P + "/{eid}/logs/raw")
def experiment_log_raw(pid: str, eid: str):
    return logstream.raw_response(pid, eid)


@router.get("/api/resources")
def get_resources():
    """The compute the Experiments view shows: labeled demo data (source "demo"); see demo.py for the shape."""
    return demo.resources()
