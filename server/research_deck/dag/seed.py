"""Helpers to build a DAG by script (demo projects, tests): nodes, statuses, env probes and run records whose traces
list exactly the files / config keys / env keys a cell read. Everything goes through the op engine and record_run,
so the result is what the dashboard would have produced (history lines, vids, events).

    from research_deck.dag import seed
    s = seed.store(root)
    seed.env(s, "workstation", {"gpu_model": "GPU-24GB"}, usd_per_gpu_hour=0)
    seed.add(s, "design.sched", "design", title="Lookahead scheduler", status="confirmed",
             facets={"preemption": "None.", "chunk": {"type": "bound", "bind": "configs/sched.yaml#sched.chunk"}})
    seed.record(s, "exp.e2e", {"system": "ours", "rate": 8}, reads=["bench/e2e.py", "src/x/policy.py"],
                cfg_keys=["system", "rate", "sched.chunk.max"], outputs={"ttft_p99": 182.4}, gpu_hours=0.4)

    with seed.clock("2026-10-05T14:00:00Z") as clk:    # reproducible files: timestamps, vids and run times pinned
        seed.add(s, ...)
        clk.set("2026-10-05T15:00:00Z")

research_deck/demo.py builds the demo project's DAG with these helpers.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import util
from ..util import write_json
from . import ops as _ops
from . import store as _store
from .evaluate import current
from .fp import MISSING, cell_id, fp_file, fp_json, git_blob_sha, parse_cell, spec_fp
from .model import edges, facet_value, parse_addr, spec_of
from .ops import apply_ops, record_run
from .resolve import fp_dir, git_bytes
from .store import DagStore

HUMAN = "human:seed"
_CLOCK_LOCK = threading.Lock()


class Clock:
    """The time a scripted story is at; set() moves it."""

    def __init__(self, at: str):
        self.at, self.owner = at, threading.get_ident()

    def set(self, at: str) -> None:
        self.at = at

    def dt(self) -> datetime:
        return datetime.fromisoformat(self.at.replace("Z", "+00:00"))


@contextmanager
def clock(at: str) -> Iterator[Clock]:
    """Pin the engine's clock (op, event, verdict and run-record timestamps, and with them the vids) to `at` for the
    calling thread, so a scripted DAG is reproducible byte for byte. Other threads keep the real time."""
    c = Clock(at)
    real_now_iso = util.now_iso

    def now_iso() -> str:
        return c.at if threading.get_ident() == c.owner else real_now_iso()

    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if threading.get_ident() != c.owner:
                return datetime.now(tz)
            v = c.dt()
            return v.astimezone(tz) if tz else v.replace(tzinfo=None)

    with _CLOCK_LOCK:
        saved = (_ops.now_iso, _store.now_iso, _ops.datetime)
        _ops.now_iso = _store.now_iso = now_iso
        _ops.datetime = PinnedDatetime
        try:
            yield c
        finally:
            _ops.now_iso, _store.now_iso, _ops.datetime = saved


def store(root: str | Path) -> DagStore:
    s = DagStore(Path(root).resolve())
    s.ensure()
    return s


def apply(s: DagStore, ops: list[dict], actor: str = HUMAN) -> list[dict]:
    return apply_ops(s, ops, actor)[1]


def add(s: DagStore, nid: str, kind: str, *, title: str | dict | None = None, status: str = "active", stage: str | None = None,
        facets: dict | None = None, edges: list[dict] | None = None, alt_group: str | None = None, purpose: str | None = None,
        notes: str | None = None, reason: str | None = None, actor: str = HUMAN, **extra: Any) -> dict:
    """Create a node (proposed or active), then walk it to `status` (confirmed, locked, refuted, abandoned, …)."""
    node = {"id": nid, "kind": kind, "title": title if isinstance(title, dict) else {"en": title or nid},
            "status": "proposed" if status == "proposed" else "active", "facets": facets or {}, "edges": edges or [], **extra}
    for k, v in (("stage", stage), ("alt_group", alt_group), ("purpose", purpose), ("notes", notes)):
        if v is not None:
            node[k] = v
    apply(s, [{"op": "create", "node": node}], actor)
    if status in ("confirmed", "locked"):
        set_status(s, nid, "confirmed", reason or "seed", actor=actor)
    if status == "locked":
        lock(s, nid, reason or "seed", actor=actor)
    if status in ("refuted", "abandoned", "superseded"):
        set_status(s, nid, status, reason or "seed", actor=actor)
    return current(s).nodes[nid]


def set_status(s: DagStore, nid: str, to: str, reason: str | None = None, actor: str = HUMAN, **kw: Any) -> list[dict]:
    return apply(s, [{"op": "set_status", "node": nid, "to": to, "reason": reason, **kw}], actor)


def lock(s: DagStore, nid: str, reason: str = "seed", actor: str = HUMAN) -> list[dict]:
    return apply(s, [{"op": "lock", "node": nid, "reason": reason}], actor)


def link(s: DagStore, nid: str, edge: dict, actor: str = HUMAN) -> list[dict]:
    return apply(s, [{"op": "link", "node": nid, "edge": edge}], actor)


def edit(s: DagStore, nid: str, set: dict, actor: str = HUMAN, **kw: Any) -> list[dict]:
    return apply(s, [{"op": "edit", "node": nid, "set": set, **kw}], actor)


def env(s: DagStore, platform: str, key: dict, pkgs: dict | None = None, usd_per_gpu_hour: float = 0.0, via: str = "seed") -> None:
    """envs/<platform>.json: the probe every env: trace item of a run on that target is checked against."""
    write_json(s.dir / "envs" / f"{platform}.json", {"platform": platform, "via": via, "key": key, "pkgs": pkgs or {},
                                                    "usd_per_gpu_hour": usd_per_gpu_hour})


def trace_for(s: DagStore, nid: str, cell: dict | str, *, reads: Iterable[str] = (), cfg_keys: Iterable[str] | None = None,
              env_keys: Iterable[str] | None = None, dirs: Iterable[str] = (), datasets: Iterable[str] | None = None,
              commit: str | None = None, cfg_values: dict | None = None) -> dict:
    """A trace that fingerprints each item as the resolver does now (code at `commit` when given)."""
    st = current(s)
    n = st.nodes[nid]
    values = parse_cell(cell) if isinstance(cell, str) else dict(cell)
    T: dict[str, dict] = {}
    for path in reads:
        if commit:
            data = git_bytes(s.root, "cat-file", "blob", f"{commit}:{path}")
        else:
            p = s.root / path
            data = p.read_bytes() if p.is_file() else None
        T[f"code:{path}"] = {"fp": fp_file(path, data), "blob": git_blob_sha(data)[:12]} if data is not None else {"fp": MISSING}
    for d in dirs:
        T[f"dir:{d}"] = {"fp": fp_dir(st.R.tree().names(d))}
    for k in (list(values) if cfg_keys is None else cfg_keys):
        if cfg_values and k in cfg_values:
            T[f"cfg:{k}"] = {"fp": fp_json(cfg_values[k]), "v": cfg_values[k]}
        else:
            T[f"cfg:{k}"] = {"fp": st.R.cfg_fp(k, n, values)}
    probe = s.env_probe(spec_of(n).get("platform") or "") or {}
    for k in (list(probe.get("key") or {}) if env_keys is None else env_keys):
        v = (probe.get("pkgs") or {}).get(k[4:]) if k.startswith("pkg:") else (probe.get("key") or {}).get(k)
        if v is not None:
            T[f"env:{k}"] = {"fp": fp_json(v), "v": v}
    for ds in (spec_of(n).get("datasets") or [] if datasets is None else datasets):
        T[f"data:{ds}"] = {"fp": st.R.data_fp(ds)}
    for e in edges(n, "input"):
        a = parse_addr(e["to"])
        T[e["to"]] = {"fp": str(st.R.node_fp(e["to"]) if a.out else st.R.data_fp(a.id))}
    return T


def record(s: DagStore, nid: str, cell: dict | str, *, reads: Iterable[str] = (), cfg_keys: Iterable[str] | None = None,
           outputs: dict | None = None, env_keys: Iterable[str] | None = None, dirs: Iterable[str] = (), commit: str | None = None,
           platform: str | None = None, gpu_hours: float | None = None, run_id: str | None = None, started: str | None = None,
           ended: str | None = None, state: str = "succeeded", by: str = "system", experiment: str | None = None,
           cfg_values: dict | None = None) -> dict:
    """Record one run of a cell whose trace lists exactly `reads` (files), `cfg_keys` and env keys; returns record_run's result."""
    values = parse_cell(cell) if isinstance(cell, str) else dict(cell)
    head = git_bytes(s.root, "rev-parse", "--short=7", commit or "HEAD")
    rec = {"node": nid, "cell": cell_id(values), "state": state, "by": by, "started": started, "ended": ended,
           "gpu_hours": gpu_hours, "platform": platform or spec_of(current(s).nodes[nid]).get("platform"),
           "trace": trace_for(s, nid, values, reads=reads, cfg_keys=cfg_keys, env_keys=env_keys, dirs=dirs, commit=commit,
                              cfg_values=cfg_values),
           "outputs": {k: (v if isinstance(v, dict) else {"value": v}) for k, v in (outputs or {}).items()},
           "git": {"head": head.decode().strip() if head else None, "snapshot": None, "dirty": False},
           "trace_quality": "traced", "experiment": experiment}
    if run_id:
        rec["id"] = run_id
    return record_run(s, {k: v for k, v in rec.items() if v is not None}, by)


def exec_spec(s: DagStore, nid: str) -> dict:
    """spec.json for `python -m research_deck.dag.rd_exec --spec spec.json …` (the context a host cannot know)."""
    st = current(s)
    n = st.nodes[nid]
    datasets = {}
    for ds in spec_of(n).get("datasets") or []:
        dn = st.nodes.get(ds) or {}
        datasets[ds] = {"path": facet_value(dn, "path") or f"{(st.cfg.get('datasets_roots') or {}).get('local', 'data/').rstrip('/')}/{ds.split('.', 1)[-1]}",
                        "version": st.R.data_fp(ds)}
    return {"node": nid, "spec": spec_of(n), "outputs": facet_value(n, "outputs") or {},
            "spec_fp": spec_fp(spec_of(n)),
            "context": {"ignore_keys": (st.cfg.get("config") or {}).get("ignore_keys") or [],
                        "env_keys": (st.cfg.get("env") or {}).get("key") or [],
                        "code_roots": (st.cfg.get("code") or {}).get("roots") or [],
                        "datasets": datasets,
                        "modules": [{"id": m["id"], "globs": facet_value(m, "globs") or [], "opaque": bool(facet_value(m, "opaque"))}
                                    for m in st.nodes.values() if m.get("kind") == "module"],
                        "inputs": {e["to"]: str(st.R.node_fp(e["to"])) for e in edges(n, "input")}}}
