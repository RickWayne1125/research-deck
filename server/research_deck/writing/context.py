"""What the writing panel reads from the other slices, each lazily and never fatally:

  claims_for(pid, path)   the DAG's claim/section nodes bound to a document (dag.service.claims_for_doc,
                          docs/DAG.md §11); [] when the DAG engine is missing or fails
  experiments_for(pid)    recorded experiment results for the consistency pass: the experiments package when it
                          offers a listing function, otherwise the documented records in .research/experiments/*.json
"""
from __future__ import annotations

import importlib
import logging

from ..projects import research_dir
from ..util import read_json

log = logging.getLogger("research_deck.writing")
_ROOT = __package__.rsplit(".", 1)[0]          # research_deck
FRESHNESS = ("fresh", "review", "orphaned", "pending", "unbuilt", "stale", "broken")


def _module(name: str):
    try:
        return importlib.import_module(f"{_ROOT}.{name}")
    except Exception:  # noqa: BLE001 — another slice may not exist yet or may fail to import
        return None


def _int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def claims_for(pid: str, path: str) -> list[dict]:
    service = _module("dag.service")
    fn = getattr(service, "claims_for_doc", None) if service else None
    if not callable(fn):
        return []
    try:
        items = fn(pid, path) or []
    except Exception as e:  # noqa: BLE001
        log.warning("claims_for_doc(%s, %s) failed: %s", pid, path, e)
        return []
    out = []
    for c in items:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        fresh = c.get("freshness")
        out.append({
            "id": str(c["id"]), "label": str(c.get("label") or c["id"]), "text": str(c.get("text") or ""),
            "line": _int(c.get("line")), "evidence": [str(e) for e in c.get("evidence") or []],
            "freshness": fresh if fresh in FRESHNESS else None, "values": c.get("values") or {},
            **({"kind": c["kind"]} if c.get("kind") else {}),
        })
    return out


def _experiment_rows(items) -> list[dict]:
    rows = []
    for e in items or []:
        if not isinstance(e, dict) or not e.get("metrics"):
            continue
        rows.append({k: e.get(k) for k in ("id", "node_id", "title", "status", "freshness", "metrics", "dataset")
                     if e.get(k) not in (None, "", [], {})})
    return rows


def experiments_for(pid: str) -> list[dict]:
    for name in ("experiments.service", "experiments.store", "experiments.records"):
        mod = _module(name)
        for fn_name in ("list_experiments", "all_experiments", "experiments"):
            fn = getattr(mod, fn_name, None) if mod else None
            if callable(fn):
                try:
                    return _experiment_rows(fn(pid))[:40]
                except Exception as e:  # noqa: BLE001 — fall through to the records on disk
                    log.debug("%s.%s(%s) failed: %s", name, fn_name, pid, e)
    d = research_dir(pid) / "experiments"
    records = [read_json(f, None) for f in sorted(d.glob("*.json"))] if d.is_dir() else []
    return _experiment_rows(records)[:40]
