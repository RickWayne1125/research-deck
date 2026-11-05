"""The DAG for other packages (docs/DAG.md §11): every function takes a project id, never raises for a project
without a DAG (it returns empty results) and is cheap thanks to the evaluation cache. The routes in api.py use the same
builders, so GET /dag/graph and service.graph(pid) return the same JSON.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import projects
from ..events import hub
from .evaluate import State, build, current
from .model import DEAD, authored_fp, edges, facet_value, input_cycle, is_action, parse_addr, ref_id, title_of, validate_node, warnings_for
from .resolve import Repo, Tree, check_rev, git_text
from . import stages
from .store import DagStore, at_commit

log = logging.getLogger("research_deck.dag")


def store_for(pid: str) -> DagStore:
    return DagStore(projects.project_root(pid), state=projects.project_state(pid))


def publish(pid: str, store: DagStore, changed: list[str] | set[str]) -> None:
    try:
        hub.publish(pid, "dag", {"digest": current(store).digest, "changed": sorted({c for c in changed if c})})
    except Exception:  # noqa: BLE001 — a failed notification never fails the change
        log.exception("dag publish failed")


# ---------------------------------------------------------------- JSON builders shared with api.py

def run_summary(r: dict) -> dict:
    return {"id": r.get("id"), "node": r.get("node"), "cell": r.get("cell") or "_", "state": r.get("state", "succeeded"),
            "by": r.get("by") or "system", "platform": r.get("platform"), "started": r.get("started"), "ended": r.get("ended"),
            "gpu_hours": r.get("gpu_hours"), "trace_quality": r.get("trace_quality"), "excluded": r.get("excluded"),
            "outputs": {k: {"value": o.get("value"), "unit": o.get("unit"), "cutoff": bool(o.get("cutoff"))}
                        for k, o in (r.get("outputs") or {}).items() if isinstance(o, dict)},
            "experiment": r.get("experiment"), "git": r.get("git"),
            "footprint": sorted(a[5:] for a in (r.get("trace") or {}) if a.startswith("code:"))}


def node_json(n: dict) -> dict:
    out = dict(n)
    out.setdefault("head", {"rev": 0, "vid": "", "fp": ""})
    out.setdefault("facets", {})
    out.setdefault("edges", [])
    out.setdefault("title", {"en": n.get("id")})
    return out


def graph_json(st: State, *, dead: bool = True, at: str | None = None) -> dict:
    from .gates import lenses
    nodes = [node_json(n) for _, n in sorted(st.nodes.items()) if dead or n.get("status") not in DEAD]
    ev = st.eval_json()
    return {"nodes": nodes, "eval": {n["id"]: ev[n["id"]] for n in nodes}, "lenses": lenses(st), "digest": st.digest, "at": at,
            "stage_mode": stages.mode(st.cfg)}


def versions(st: State, nid: str) -> list[dict]:
    lines = st.store.history(nid)
    by_vid = {v.get("vid"): v for v in lines}
    out = []
    for v in lines:
        prev = (by_vid.get(v.get("parent")) or {}).get("facets") or {}
        cur = v.get("facets") or {}
        diff = [{"facet": k, "from": (prev.get(k) or {}).get("value", prev.get(k)), "to": (cur.get(k) or {}).get("value", cur.get(k))}
                for k in sorted(set(prev) | set(cur)) if prev.get(k) != cur.get(k)]
        out.append({**{k: v.get(k) for k in ("vid", "rev", "parent", "reverts", "fp", "facets", "edges", "status", "by", "at",
                                             "git", "op", "via")}, "diff": diff})
    return out


def node_detail(st: State, nid: str, history_limit: int = 20) -> dict | None:
    n = st.nodes.get(nid)
    if n is None:
        return None
    runs: dict[str, list[dict]] = {}
    for (node, cell), rs in st.runs.by_cell.items():
        if node == nid:
            runs[cell] = [run_summary(r) for r in rs]
    deps = sorted({(m["id"], e["type"]) for m in st.nodes.values() for e in edges(m)
                   if ref_id(e.get("to")) == nid and m["id"] != nid})
    return {**node_json(n), "eval": st.E[nid].json(), "history": versions(st, nid)[-history_limit:][::-1], "runs": runs,
            "dependents": [{"id": i, "edge": t} for i, t in deps]}


def _when(st: State, addr: str) -> str:
    """' in 9d21e77' for a committed code change, ' in the working tree' for a dirty one."""
    if not addr.startswith("code:") or not st.repo.is_git:
        return ""
    path = addr[5:]
    if st.R.tree().files.get(path, "") is None:
        return " in the working tree"
    sha = git_text(st.repo.root, "log", "-1", "--format=%h", "--", path)
    return f" in {sha.strip()}" if sha and sha.strip() else ""


def explain(st: State, nid: str, cell: str | None = None) -> list[dict]:
    """Plain-language root-cause chains: why each non-fresh cell, and each node-level reason."""
    ev = st.E.get(nid)
    if ev is None:
        return []
    short = lambda v: (str(v)[:6] + "…" + str(v)[-2:]) if isinstance(v, str) and len(v) > 12 else str(v)   # noqa: E731
    out = []
    for cid, c in sorted(ev.cells.items()):
        if (cell and cid != cell) or (not cell and c.level == "fresh"):
            continue
        steps = [{"addr": w.get("addr") or "", "from": w.get("from"), "to": w.get("to"), "note": w.get("note")} for w in c.why]
        if c.level == "fresh":
            text = f"fresh through run {(c.run or {}).get('id')}" + (" (an older run, reused)" if c.reused else "")
        elif not steps or not steps[0]["addr"]:
            text = f"{c.level}: " + (steps[0]["note"] if steps else "no run")
        else:
            s0 = steps[0]
            text = f"{c.level} because {s0['addr']} changed {short(s0['from'])}→{short(s0['to'])}{_when(st, s0['addr'])}"
            if s0.get("note"):
                text = f"{c.level} because {s0['addr']}: {s0['note']}"
            if len(steps) > 1:
                text += f" (+{len(steps) - 1} more)"
        if c.impl_lag:
            text += "; results reflect code that no longer matches the design (implement first)"
        out.append({"cell": cid, "level": c.level, "steps": steps, "text": text})
    if not cell:
        for r in ev.reasons:
            if r["level"] == "fresh" and r.get("note") != "drift":
                continue
            what = r.get("edge") or r.get("addr") or ""
            detail = r.get("note") or (f"{short(r.get('from'))}→{short(r.get('to'))}" if r.get("to") else "")
            out.append({"cell": None, "level": r["level"], "steps": [{"addr": what, "from": r.get("from"), "to": r.get("to"), "note": r.get("note")}],
                        "text": f"{r['level']} because {what}" + (f": {detail}" if detail else "")})
    return out


def past_state(store: DagStore, at: str) -> State:
    """A read-only evaluation of the DAG at `snap:<name>` or a git commit, with code resolved at that commit."""
    if at.startswith("snap:"):
        snap = store.snapshot(at[5:])
        if not snap:
            raise KeyError(f"no snapshot {at[5:]}")
        nodes = {}
        for nid, vid in (snap.get("nodes") or {}).items():
            lines = store.history(nid)
            v = next((x for x in lines if x.get("vid") == vid), None)
            if not v:
                continue
            meta: dict = {}
            for x in lines:
                meta.update(x.get("meta") or {})
                if x is v:
                    break
            nodes[nid] = {"id": nid, **meta, "status": v.get("status"), "head": {"rev": v.get("rev"), "vid": vid, "fp": v.get("fp")},
                          "facets": v.get("facets") or {}, "edges": v.get("edges") or [], "lock": v.get("lock"),
                          "selected": {k.rpartition("/")[2]: r for k, r in (snap.get("runs") or {}).items() if k.rpartition("/")[0] == nid}}
        rev = snap.get("git")
        st = build(store, nodes=nodes, repo=PinnedRepo(store.root, rev) if rev else None)
        st.digest = snap.get("eval_digest") or ""
        return st
    rev = check_rev(at)
    past = at_commit(store.root, rev, store.state)
    st = build(past, repo=PinnedRepo(store.root, rev))
    st.digest = f"at:{rev}"
    return st


class PinnedRepo(Repo):
    """A repo whose 'worktree' is the tree of one commit (time travel)."""

    def __init__(self, root: Path, rev: str):
        super().__init__(root, None)
        self.rev = check_rev(rev)

    def tree(self, ref: str = "worktree") -> Tree:
        return super().tree(f"commit:{self.rev}" if ref == "worktree" else ref)


# ---------------------------------------------------------------- the §11 interface

def _state(pid: str) -> State | None:
    try:
        store = store_for(pid)
    except Exception:  # noqa: BLE001 — unknown project / missing folder
        return None
    if not store.exists:
        return None
    try:
        return current(store)
    except Exception:  # noqa: BLE001
        log.exception("dag evaluation failed for %s", pid)
        return None


def _empty_lenses() -> dict:
    return {"tried": {"count": 0, "dead": 0, "runs": 0, "items": []}, "confirmed": {"count": 0, "shaky": 0, "items": []},
            "revise": {"count": 0, "items": []},
            "rerun": {"count": 0, "gpu_h": 0, "blocked": 0, "conditional": 0, "reused_cells": 0, "reused_gpu_h": 0, "items": []}}


def graph(pid: str) -> dict:
    st = _state(pid)
    if st:
        return graph_json(st)
    try:
        mode = stages.mode(store_for(pid).config())
    except Exception:  # noqa: BLE001 — an unknown project: empty results, never an error (module docstring)
        mode = stages.mode({})
    return {"nodes": [], "eval": {}, "lenses": _empty_lenses(), "digest": "", "at": None, "stage_mode": mode}


def node(pid: str, node_id: str) -> dict | None:
    st = _state(pid)
    return node_detail(st, node_id) if st else None


def get_node(pid: str, node_id: str) -> dict | None:
    """A compact view for other panels: {id, label, title, kind, status, freshness}."""
    st = _state(pid)
    n = st.nodes.get(node_id) if st else None
    if not n:
        return None
    return {"id": node_id, "label": title_of(n), "title": n.get("title"), "kind": n.get("kind"), "status": n.get("status"),
            "freshness": st.E[node_id].level}


def lenses(pid: str) -> dict:
    from .gates import lenses as compute
    st = _state(pid)
    return compute(st) if st else _empty_lenses()


def recent_events(pid: str, limit: int = 50) -> list[dict]:
    st = _state(pid)
    return st.store.events()[-limit:][::-1] if st else []


def experiment_freshness(pid: str, node_id: str, run_id: str | None = None, cell: str | None = None) -> dict:
    out = {"freshness": "unknown", "level": None, "reasons": [], "cell": cell, "footprint": [], "run": run_id}
    st = _state(pid)
    n = st.nodes.get(node_id or "") if st else None
    if not st or not n or not is_action(n):
        return out
    ev = st.E[node_id]
    run = st.runs.by_id.get(run_id) if run_id else None
    if run is not None:
        cell = run.get("cell") or "_"
    if cell is None and len(ev.cells) == 1:
        cell = next(iter(ev.cells))
    c = ev.cells.get(cell) if cell else None
    if c is None:                                # the node as a whole
        if ev.archived or not ev.cells:
            return out
        levels = {x.level for x in ev.cells.values()}
        out.update(level=ev.level, reasons=[w.get("note") or w.get("addr") for x in ev.cells.values() for w in x.why][:10],
                   freshness="fresh" if levels == {"fresh"} else "stale" if levels & {"stale", "pending", "orphaned"} else "unknown")
        return out
    run = run or c.run
    if run is None:
        out.update(level=c.level, cell=cell, reasons=["no run"])
        return out
    from .evaluate import check_run
    mm = check_run(st, run)
    state = "excluded" if run.get("excluded") else run.get("state", "succeeded")
    if c.run and c.run.get("id") == run.get("id") and c.level == "fresh":
        fresh = "fresh"
    elif not mm and state == "succeeded":
        fresh = "reusable"
    elif state != "succeeded" or not run.get("trace"):
        fresh = "unknown"                        # a failed, running or excluded run holds no valid result to be stale
    else:
        fresh = "stale"
    out.update(freshness=fresh, level=c.level, cell=cell, run=run.get("id"),
               reasons=([f"run {state}"] if state != "succeeded" else [])
               + [f"{m.get('addr')}: {m.get('note') or 'changed'}" for m in mm][:10],
               footprint=sorted(a[5:] for a in (run.get("trace") or {}) if a.startswith("code:")))
    return out


def nodes_by_commit(pid: str) -> dict[str, list[str]]:
    st = _state(pid)
    if not st:
        return {}
    out: dict[str, set[str]] = {}
    for nid in st.store.history_ids():
        for v in st.store.history(nid):
            if v.get("git"):
                out.setdefault(str(v["git"])[:7], set()).add(nid)
    for r in st.runs.by_id.values():
        head = (r.get("git") or {}).get("head")
        if head:
            out.setdefault(str(head)[:7], set()).add(r["node"])
    return {k: sorted(v) for k, v in out.items()}


def design_components(pid: str) -> list[dict]:
    st = _state(pid)
    if not st:
        return []
    out = []
    for n in sorted(st.nodes.values(), key=lambda x: x["id"]):
        if n.get("kind") != "module" or n.get("status") in DEAD:
            continue
        impl = [e["to"][5:] for e in edges(n, "implements")]
        desc = n.get("notes") or (f"implements {', '.join(impl)}" if impl else "")
        out.append({"id": n["id"], "label": title_of(n), "node_id": n["id"], "paths": list(facet_value(n, "globs") or []),
                    "description": desc})
    return out


def claims_for_doc(pid: str, path: str) -> list[dict]:
    st = _state(pid)
    if not st:
        return []
    from .paper import claims_for_doc as build_claims
    try:
        return build_claims(st, path)
    except Exception:  # noqa: BLE001
        log.exception("claims_for_doc failed")
        return []


def brief_data(pid: str) -> dict:
    st = _state(pid)
    if not st:
        return {"stage": None, "lenses": {}, "revise": [], "rerun": [], "confirmed": [], "attempts": [], "open_proposals": [], "gates": []}
    from .gates import compute, lenses as compute_lenses
    L = compute_lenses(st)
    order = ("S0", "S1", "S2", "S3", "S4", "S5", "S6")
    stages = [n.get("stage") for n in st.nodes.values() if n.get("status") not in DEAD and n.get("stage") in order]
    reason = lambda i: next((r.get("note") or r.get("edge") for r in st.E[i].reasons if r["level"] != "fresh"), None)   # noqa: E731
    attempts: dict[str, dict] = {}
    for n in st.nodes.values():
        g = n.get("alt_group")
        if g:
            a = attempts.setdefault(g, {"alt_group": g, "tried": 0, "chosen": None, "dead": []})
            a["tried"] += 1
            if n.get("status") in ("confirmed", "locked"):
                a["chosen"] = n["id"]
            if n.get("status") in DEAD:
                a["dead"].append({"id": n["id"], "status": n["status"], "reason": (n.get("verdict") or {}).get("reason")})
    return {
        "stage": max(stages, key=order.index) if stages else None,
        "lenses": {k: v["count"] for k, v in L.items()},
        "revise": [{"id": i["id"], "title": title_of(st.nodes[i["id"]]), "level": st.E[i["id"]].level, "reason": reason(i["id"])}
                   for i in L["revise"]["items"][:10]],
        "rerun": [{"id": i["id"], "title": title_of(st.nodes[i["id"]]), "cells": i.get("cells"), "note": i.get("note")}
                  for i in L["rerun"]["items"][:10]],
        "confirmed": [{"id": n["id"], "kind": n.get("kind"), "title": title_of(n), "text": facet_value(n, "text") or facet_value(n, "statement")}
                      for n in sorted(st.nodes.values(), key=lambda x: x["id"])
                      if n.get("status") in ("confirmed", "locked") and st.E[n["id"]].level == "fresh"
                      and n.get("kind") in ("claim", "finding", "gap", "decision", "problem")],
        "attempts": sorted(attempts.values(), key=lambda a: a["alt_group"]),
        "open_proposals": [{"id": p.get("id"), "title": p.get("title"), "by": p.get("by"), "requires": p.get("requires")}
                           for p in st.store.proposals() if p.get("state") == "open"],
        "gates": [{"gate": g["gate"], "state": g["state"]} for g in compute(st)],
    }


def check(st: State) -> dict:
    """`dag check`: schema, input cycles, dangling edges, unsealed YAML, history forks, alt_group, paper anchors, locks."""
    from .paper import anchors
    nodes = st.nodes
    dangling = []
    for i, n in sorted(nodes.items()):
        for e in edges(n):
            try:
                a = parse_addr(e.get("to", ""))
            except ValueError:
                continue
            if (a.scheme == "node" and a.id not in nodes) or (a.scheme == "run" and a.id not in st.runs.by_id):
                dangling.append(f"{i} → {e['to']}")
    groups: dict[tuple, list[str]] = {}
    for i, n in nodes.items():
        if n.get("alt_group") and n.get("status") in ("confirmed", "locked"):
            groups.setdefault((n["alt_group"], n.get("kind")), []).append(i)
    try:
        found = anchors(st)
    except Exception:  # noqa: BLE001
        found = {}
    anchor_issues = [f"% rd:sec {s}: no such node" for s in found if s not in nodes]
    anchor_issues += [f"{i}: no % rd:sec anchor" for i, n in nodes.items() if n.get("kind") == "section"
                      and n.get("status") not in DEAD and i not in found]
    locks = [i for i, n in nodes.items() if n.get("status") == "locked" and (
        (n.get("lock") or {}).get("fp") != authored_fp(n)
        or (n.get("lock") or {}).get("edges_seen", {}) != {f"{e.get('type')}:{e.get('to')}": e.get("seen") for e in edges(n) if e.get("seen")})]
    beliefs = {i: n for i, n in nodes.items() if not is_action(n)}
    cycles = [c for c in (input_cycle(nodes), input_cycle(beliefs, ("basis",))) if c]
    return {"schema": [f"{i}: {e}" for i, n in sorted(nodes.items()) for e in validate_node(n)],
            "cycles": cycles, "dangling": dangling,
            "unsealed": sorted(i for i, ev in st.E.items() if "unsealed" in ev.flags),
            "conflicts": sorted(i for i, ev in st.E.items() if "conflict" in ev.flags),
            "alt_group": [f"{g}: {', '.join(sorted(ids))} confirmed" for (g, _), ids in groups.items() if len(ids) > 1],
            "anchors": anchor_issues, "locks": locks,
            "warnings": [w for n in nodes.values() for w in warnings_for(n, nodes)]}


def record_run(pid: str, record: dict, actor: str = "system") -> dict:
    """Same as POST /dag/runs (raises ops.OpError for an invalid record)."""
    from .ops import record_run as rec
    store = store_for(pid)
    out = rec(store, record, actor)
    publish(pid, store, [record.get("node")] + list(out.get("eval_delta") or {}))
    return out


__all__ = ["graph", "node", "get_node", "lenses", "recent_events", "experiment_freshness", "nodes_by_commit",
           "design_components", "claims_for_doc", "brief_data", "record_run", "check", "explain", "past_state"]
