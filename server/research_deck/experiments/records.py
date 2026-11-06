"""Experiment records: `.research/experiments/<id>.json`, plus what the research DAG says about each one.

A record is one run that was or will be made: title, the DAG node it belongs to (an `exp.*` id, optionally a sweep
`cell`), target, config, command, code commit and footprint, dataset / env, metrics, times, the log path, artifacts
and, once the DAG has a run record for it, `run_id` (docs/DAG.md §11 "Experiment records ↔ runs").

The derived fields — `freshness`, `stale_reasons`, the run's traced footprint — come from
`dag.service.experiment_freshness` on every read and are never stored (docs/DAG.md §2.5, §7). Without the DAG package,
or for a record with no node, freshness is "unknown".

Other packages use the functions here directly (the DAG's /runs/queue creates planned records through `create_record`).
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..events import hub
from ..projects import project_root, research_dir
from ..util import now_iso, read_json, rel_to, safe_join, slugify, write_json

log = logging.getLogger("research_deck.experiments")

STATUSES = ("planned", "queued", "running", "succeeded", "failed", "cancelled", "unknown")
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
LIVE = frozenset({"queued", "running", "unknown"})          # the log may still grow
FRESHNESS = ("fresh", "stale", "reusable", "unknown")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
# Computed on read; dropped from incoming patches and never written to disk.
DERIVED = frozenset({"freshness", "stale_reasons", "dag_level", "dag_cell", "logs_tail"})

LOG_PAGE_BYTES = 256 * 1024
LOG_TAIL_BYTES = 64 * 1024
TAIL_LINES = 40


# ------------------------------------------------------------------ validation

def _check_time(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("expected an ISO 8601 timestamp")
    return v


class Target(BaseModel):
    model_config = ConfigDict(extra="allow")
    platform: str = Field("", max_length=80)
    node: str = Field("", max_length=120)
    gpus: int = Field(0, ge=0, le=4096)
    gpu_type: str | None = Field(None, max_length=120)


class Code(BaseModel):
    model_config = ConfigDict(extra="allow")
    commit: str | None = Field(None, max_length=64)
    footprint: list[str] = Field(default_factory=list, max_length=5000)


Metric = int | float | str


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    node_id: str | None = Field(None, max_length=120)
    cell: str | None = Field(None, max_length=400)
    config: dict[str, Any] = Field(default_factory=dict)
    target: Target = Field(default_factory=Target)
    command: str | None = Field(None, max_length=4000)
    code: Code | None = None
    dataset: str | None = Field(None, max_length=200)
    env: str | None = Field(None, max_length=400)
    notes: str | None = Field(None, max_length=8000)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str | None) -> str | None:
        if v is not None and not ID_RE.match(v):
            raise ValueError("id: letters, digits, '.', '_' and '-' only (max 80)")
        return v


class PatchBody(BaseModel):
    """Every field optional; `target` and `code` merge into the stored ones, everything else replaces."""
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, min_length=1, max_length=200)
    node_id: str | None = Field(None, max_length=120)
    cell: str | None = Field(None, max_length=400)
    status: Literal["planned", "queued", "running", "succeeded", "failed", "cancelled", "unknown"] | None = None
    target: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    code: dict[str, Any] | None = None
    dataset: str | None = Field(None, max_length=200)
    env: str | None = Field(None, max_length=400)
    metrics: dict[str, Metric] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    job_id: str | None = Field(None, max_length=120)      # an outside scheduler's id for the run, if any (informational)
    logs: str | None = Field(None, max_length=1000)
    artifacts: list[str] | None = Field(None, max_length=1000)
    command: str | None = Field(None, max_length=4000)
    progress: float | None = Field(None, ge=0, le=1)
    run_id: str | None = Field(None, max_length=120)
    notes: str | None = Field(None, max_length=8000)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _times(cls, v: str | None) -> str | None:
        return _check_time(v)


def _http_validation(e: ValidationError) -> HTTPException:
    errs = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
    return HTTPException(422, {"message": "; ".join(errs)})


# ------------------------------------------------------------------ storage

def records_dir(pid: str) -> Path:
    d = research_dir(pid) / "experiments"
    d.mkdir(exist_ok=True)
    return d


def _path(pid: str, eid: str) -> Path:
    if not ID_RE.match(eid or ""):
        raise HTTPException(404, f"unknown experiment: {eid}")
    return safe_join(records_dir(pid), f"{eid}.json")


def _normalize(raw: dict, eid: str) -> dict:
    """Fill the fields every client relies on; keep anything else the record carries."""
    rec = {k: v for k, v in raw.items() if k not in DERIVED}
    rec["id"] = eid
    rec.setdefault("node_id", None)
    rec["title"] = str(rec.get("title") or eid)
    if rec.get("status") not in STATUSES:
        rec["status"] = "unknown"
    target = rec.get("target") if isinstance(rec.get("target"), dict) else {}
    rec["target"] = {"platform": "", "node": "", "gpus": 0, **target}
    code = rec.get("code") if isinstance(rec.get("code"), dict) else {}
    rec["code"] = {"commit": None, "footprint": [], **code}
    for key, empty in (("config", {}), ("metrics", {}), ("artifacts", [])):
        if not isinstance(rec.get(key), type(empty)):
            rec[key] = empty
    for key in ("cell", "dataset", "env", "started_at", "finished_at", "job_id", "logs", "command", "progress", "run_id"):
        rec.setdefault(key, None)
    return rec


def _load(pid: str, eid: str) -> dict:
    path = _path(pid, eid)
    try:
        raw = read_json(path, None)
    except ValueError as e:
        raise HTTPException(500, f"experiment record {eid} is not valid JSON: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(404, f"unknown experiment: {eid}")
    return _normalize(raw, eid)


FIELD_ORDER = ("id", "node_id", "cell", "title", "status", "target", "config", "command", "code", "dataset", "env",
               "metrics", "started_at", "finished_at", "progress", "job_id", "run_id", "logs", "artifacts")


def _save(pid: str, rec: dict) -> None:
    """Fields in a stable order (git diffs stay readable), derived ones never."""
    known = {k: rec[k] for k in FIELD_ORDER if k in rec}
    rest = {k: v for k, v in rec.items() if k not in known and k not in DERIVED}
    write_json(_path(pid, rec["id"]), {**known, **rest})


def _all_raw(pid: str) -> list[dict]:
    out = []
    for path in sorted(records_dir(pid).glob("*.json")):
        eid = path.stem
        if not ID_RE.match(eid):
            continue
        try:
            raw = read_json(path, None)
        except ValueError:
            log.warning("skipping experiment record %s: not valid JSON", path)
            continue
        if isinstance(raw, dict):
            out.append(_normalize(raw, eid))
    return out


def _sort_key(rec: dict) -> str:
    created = rec.get("created") if isinstance(rec.get("created"), dict) else {}
    return str(rec.get("started_at") or created.get("at") or rec.get("finished_at") or "")


def _new_id(pid: str, title: str, node_id: str | None = None) -> str:
    # A Chinese title slugs to nothing; the node id ("exp.ablation-chunk") then names the record.
    node = (node_id or "").removeprefix("exp.")
    base = (slugify(title, "") or slugify(node, "") or "exp")[:40].strip("-") or "exp"
    while True:
        eid = f"{base}-{secrets.token_hex(2)}"
        if not _path(pid, eid).exists():
            return eid


def _check_paths(pid: str, rec: dict) -> None:
    """Project-relative paths coming from a request must stay inside the project."""
    if rec.get("logs"):
        safe_join(project_root(pid), rec["logs"])


# ------------------------------------------------------------------ derived fields

def _dag_service():
    """The DAG's service module (docs/DAG.md §11), or None while that package is missing or broken."""
    try:
        from ..dag import service
        return service
    except Exception:  # noqa: BLE001 — experiments stay usable without the DAG
        return None


def _reason_text(r: Any) -> str:
    if isinstance(r, str):
        return r
    if isinstance(r, dict):
        if r.get("note"):
            return str(r["note"])
        if r.get("addr"):
            frm, to = r.get("from"), r.get("to")
            return f"{r['addr']} changed" + (f" ({frm} → {to})" if frm or to else "")
        if r.get("level"):
            return str(r["level"])
    return str(r)


def _freshness(pid: str, rec: dict, svc) -> dict:
    """{freshness, reasons, level, cell, footprint} for one record; "unknown" when the DAG cannot say."""
    unknown = {"freshness": "unknown", "reasons": [], "level": None, "cell": None, "footprint": []}
    if svc is None or not rec.get("node_id"):
        return unknown
    try:
        try:
            f = svc.experiment_freshness(pid, rec["node_id"], run_id=rec.get("run_id"), cell=rec.get("cell"))
        except TypeError:  # an older service without the `cell` parameter
            f = svc.experiment_freshness(pid, rec["node_id"], run_id=rec.get("run_id"))
    except Exception as e:  # noqa: BLE001
        log.warning("experiment_freshness(%s, %s) failed: %s", pid, rec.get("node_id"), e)
        return unknown
    if not isinstance(f, dict):
        return unknown
    fresh = f.get("freshness") if f.get("freshness") in FRESHNESS else "unknown"
    return {"freshness": fresh, "reasons": [_reason_text(r) for r in f.get("reasons") or []],
            "level": f.get("level"), "cell": f.get("cell"), "footprint": [str(p) for p in f.get("footprint") or []]}


def _derive(pid: str, rec: dict, svc) -> dict:
    rec = dict(rec)
    f = _freshness(pid, rec, svc)
    rec["freshness"] = f["freshness"]
    rec["stale_reasons"] = f["reasons"]
    rec["dag_level"] = f["level"]
    if f["cell"] and not rec.get("cell"):
        rec["dag_cell"] = f["cell"]
    if f["footprint"]:
        # The run's trace is the truth about what it read (docs/DAG.md §7); the declared list is kept alongside.
        code = dict(rec["code"])
        if code.get("footprint") and code["footprint"] != f["footprint"]:
            code["declared_footprint"] = code["footprint"]
        code["footprint"] = f["footprint"]
        code["footprint_source"] = "trace"
        rec["code"] = code
    return rec


# ------------------------------------------------------------------ public functions

def list_records(pid: str) -> list[dict]:
    svc = _dag_service()
    recs = [_derive(pid, r, svc) for r in _all_raw(pid)]
    return sorted(recs, key=lambda r: (_sort_key(r), r["id"]), reverse=True)


def target_platforms(pid: str) -> set[str]:
    """Every platform name the project's records run on (target.platform), read from the stored records only."""
    return {p for r in _all_raw(pid) if (p := str(((r.get("target") or {}).get("platform")) or "").strip())}


def get_state(pid: str, eid: str) -> dict:
    """The stored record without the DAG-derived fields: cheap enough to poll (the log stream reads it every poll to
    know whether the run is still live)."""
    return _load(pid, eid)


def get_record(pid: str, eid: str, *, tail: bool = True) -> dict:
    rec = _derive(pid, _load(pid, eid), _dag_service())
    if tail:
        try:
            rec["logs_tail"] = read_logs(pid, rec, -1)["lines"][-TAIL_LINES:]
        except HTTPException:
            rec["logs_tail"] = []
    return rec


def create_record(pid: str, body: CreateBody | dict, actor: str = "system") -> dict:
    if isinstance(body, dict):
        try:
            body = CreateBody.model_validate(body)
        except ValidationError as e:
            raise _http_validation(e)
    eid = body.id or _new_id(pid, body.title, body.node_id)
    if _path(pid, eid).exists():
        raise HTTPException(409, {"message": f"experiment {eid} already exists"})
    stamp = {"by": actor, "at": now_iso()}
    rec = _normalize({
        **body.model_dump(exclude={"id", "target", "code"}, exclude_none=True),
        "status": "planned",
        "target": body.target.model_dump(exclude_none=True),
        "code": body.code.model_dump() if body.code else {"commit": None, "footprint": []},
        "created": stamp, "updated": stamp,
    }, eid)
    _check_paths(pid, rec)
    _save(pid, rec)
    hub.publish(pid, "experiments", {"id": eid, "change": "created", "status": rec["status"]})
    return get_record(pid, eid)


def patch_record(pid: str, eid: str, changes: dict, actor: str = "system") -> dict:
    rec = _load(pid, eid)
    incoming = {k: v for k, v in (changes or {}).items() if k not in DERIVED and k != "id"}
    try:
        body = PatchBody.model_validate(incoming)
    except ValidationError as e:
        raise _http_validation(e)
    upd = body.model_dump(exclude_unset=True)
    try:
        if "target" in upd:
            upd["target"] = Target.model_validate({**rec["target"], **(upd["target"] or {})}).model_dump(exclude_none=True)
        if "code" in upd:
            upd["code"] = Code.model_validate({**rec["code"], **(upd["code"] or {})}).model_dump()
    except ValidationError as e:
        raise _http_validation(e)
    if upd.get("title") is None:
        upd.pop("title", None)
    rec.update(upd)
    # Times follow the status unless the caller set them.
    if upd.get("status") == "running" and not rec.get("started_at"):
        rec["started_at"] = now_iso()
    if upd.get("status") in TERMINAL and not rec.get("finished_at"):
        rec["finished_at"] = now_iso()
    if upd.get("status") == "succeeded" and rec.get("progress") is not None and "progress" not in upd:
        rec["progress"] = 1.0
    rec["updated"] = {"by": actor, "at": now_iso()}
    _check_paths(pid, rec)
    _save(pid, rec)
    hub.publish(pid, "experiments", {"id": eid, "change": "updated", "status": rec["status"], "fields": sorted(upd)})
    return get_record(pid, eid)


# ------------------------------------------------------------------ logs

# Terminal control sequences: CSI (colors, cursor moves, erase), OSC (titles, links) ended by BEL or ST, charset
# designations and the other two-byte escapes. A terminal shows none of them.
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()*+][0-9A-Za-z]|[@-Z\\-_])")


def _split_lines(text: str) -> list[str]:
    """Lines as a terminal would show them: escape sequences (colors) are dropped and a carriage return (progress
    bars) overwrites the line. The raw text, escapes included, is what logstream.py streams to the terminal view."""
    if "\x1b" in text:
        text = ANSI_RE.sub("", text)
    return [line.rsplit("\r", 1)[-1] if "\r" in line else line for line in text.split("\n")]


def terminal_lines(text: str) -> list[str]:
    """`text` as the lines a terminal would show (see _split_lines); a final newline does not open another line."""
    if "\x1b" in text:
        text = ANSI_RE.sub("", text)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line.rsplit("\r", 1)[-1] for line in lines]


def read_logs(pid: str, rec: dict, offset: int = 0) -> dict:
    """One page of the run's log. `offset` is a byte offset (≥ 0) or < 0 for the tail; `next` is the offset to pass back.

    Only complete lines are returned while the run may still be writing, so a poll never shows half a line twice.
    """
    if rec.get("logs"):
        root = project_root(pid)
        target = safe_join(root, rec["logs"])
        if target.is_file():
            return _read_file_page(target, rel_to(root, target), offset, still_writing=rec.get("status") in LIVE)
        return {"lines": [], "next": 0, "size": 0, "eof": True, "source": "file", "path": rec["logs"], "missing": True}
    return {"lines": [], "next": 0, "size": 0, "eof": True, "source": "none"}


def _read_file_page(target: Path, rel: str, offset: int, *, still_writing: bool) -> dict:
    size = target.stat().st_size
    reset = False
    if offset < 0:
        start = max(0, size - LOG_TAIL_BYTES)
    elif offset > size:            # the file was truncated or rotated: start over
        start, reset = 0, True
    else:
        start = offset
    with target.open("rb") as f:
        f.seek(start)
        data = f.read(LOG_PAGE_BYTES if offset >= 0 else LOG_TAIL_BYTES)
    truncated_before = offset < 0 and start > 0
    if truncated_before:           # a tail that starts mid-line drops the partial first line
        cut = data.find(b"\n")
        data, start = (data[cut + 1:], start + cut + 1) if cut >= 0 else (b"", start + len(data))
    end = start + len(data)
    if still_writing and data and not data.endswith(b"\n") and end >= size:
        cut = data.rfind(b"\n")
        data = data[: cut + 1] if cut >= 0 else b""
        end = start + len(data)
    text = data.decode("utf-8", errors="replace")
    if text.endswith("\n"):
        text = text[:-1]
    lines = _split_lines(text) if text or data else []
    return {"lines": lines, "next": end, "size": size, "eof": end >= size, "source": "file", "path": rel,
            "truncated_before": truncated_before, "reset": reset}
