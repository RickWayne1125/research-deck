"""Routes of the research DAG (docs/DAG.md §7), all under /api/projects/{pid}/dag. Every mutation logs its actor
(actors.actor_of) in log.jsonl and publishes topic "dag" {digest, changed}."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..actors import actor_of, is_human
from . import gates, paper
from .evaluate import current
from .impact import impact as compute_impact
from .ops import (OpError, apply_ops, approve, create_proposal, make_snapshot, record_run, reject, restore_proposal,
                  submit)
from .service import explain, graph_json, node_detail, node_json, past_state, publish, run_summary, store_for, versions
from .service import check as check_dag

router = APIRouter(prefix="/api/projects/{pid}/dag", tags=["dag"])


def _fail(e: OpError) -> HTTPException:
    return HTTPException(e.status, e.payload)


def _human(request: Request) -> str:
    actor = actor_of(request)
    if not is_human(actor):
        raise HTTPException(403, {"message": "open a proposal"})
    return actor


def _changed(events: list[dict], delta: dict | None = None) -> set[str]:
    return {e.get("node") for e in events if e.get("node")} | set(delta or {})


def _apply(pid: str, ops: list[dict], actor: str) -> tuple[dict, list[dict]]:
    store = store_for(pid)
    try:
        t, events = apply_ops(store, ops, actor)
    except OpError as e:
        raise _fail(e)
    publish(pid, store, _changed(events))
    return t.nodes, events


# ---------------------------------------------------------------- reading

@router.get("/graph")
def get_graph(pid: str, at: str | None = None, lens: str | None = None, dead: int = Query(1)):
    store = store_for(pid)
    if at:
        try:
            st = past_state(store, at)
        except (KeyError, ValueError) as e:
            raise HTTPException(404, {"message": str(e)})
        return graph_json(st, dead=bool(dead), at=at)
    return graph_json(current(store), dead=bool(dead))


@router.get("/nodes/{nid}")
def get_node(pid: str, nid: str):
    out = node_detail(current(store_for(pid)), nid)
    if out is None:
        raise HTTPException(404, {"message": f"unknown node: {nid}"})
    return out


@router.get("/nodes/{nid}/explain")
def get_explain(pid: str, nid: str, cell: str | None = None):
    st = current(store_for(pid))
    if nid not in st.nodes:
        raise HTTPException(404, {"message": f"unknown node: {nid}"})
    return explain(st, nid, cell)


@router.get("/nodes/{nid}/history")
def get_history(pid: str, nid: str):
    return versions(current(store_for(pid)), nid)[::-1]


@router.get("/lenses")
def get_lenses(pid: str):
    return gates.lenses(current(store_for(pid)))


@router.get("/timeline")
def get_timeline(pid: str, since: str | None = None, node: str | None = None, actor: str | None = None, limit: int = Query(500, le=5000)):
    out = []
    for ev in store_for(pid).events():
        if since and str(ev.get("e" if since.startswith("e-") else "at", "")) < since:
            continue
        if node and ev.get("node") != node:
            continue
        if actor and not str(ev.get("by", "")).startswith(actor):
            continue
        out.append(ev)
    return out[-limit:]


@router.get("/runs")
def get_runs(pid: str, node: str | None = None, cell: str | None = None):
    st = current(store_for(pid))
    runs = [r for r in st.runs.by_id.values() if (not node or r["node"] == node) and (not cell or (r.get("cell") or "_") == cell)]
    from .evaluate import run_order
    return [run_summary(r) for r in sorted(runs, key=run_order, reverse=True)]


@router.get("/proposals")
def get_proposals(pid: str, state: str | None = None):
    props = store_for(pid).proposals()
    return sorted((p for p in props if not state or p.get("state") == state), key=lambda p: p.get("id", ""), reverse=True)


@router.get("/snapshots")
def get_snapshots(pid: str):
    return sorted(store_for(pid).snapshots(), key=lambda s: s.get("at") or "", reverse=True)


@router.get("/gates")
def get_gates(pid: str):
    return gates.compute(current(store_for(pid)))


@router.get("/check")
def get_check(pid: str):
    return check_dag(current(store_for(pid)))


# ---------------------------------------------------------------- changing

@router.post("/ops")
def post_ops(pid: str, request: Request, body: dict = Body(...)):
    store, actor = store_for(pid), actor_of(request)
    try:
        out = submit(store, body.get("ops"), actor, base_digest=body.get("base_digest"), rationale=body.get("rationale"),
                     title=body.get("title"))
    except OpError as e:
        raise _fail(e)
    if not out["applied"]:
        publish(pid, store, [])
        return JSONResponse(out, status_code=202)
    publish(pid, store, _changed(out["events"], out.get("eval_delta")))
    return out


@router.post("/impact")
def post_impact(pid: str, request: Request, body: dict = Body(...)):
    try:
        return compute_impact(store_for(pid), body, actor=actor_of(request))
    except OpError as e:
        raise _fail(e)


@router.post("/proposals")
def post_proposal(pid: str, request: Request, body: dict = Body(...)):
    store = store_for(pid)
    try:
        prop = create_proposal(store, body.get("title") or "", body.get("rationale"), body.get("ops"), actor_of(request),
                               code=body.get("code"))
    except OpError as e:
        raise _fail(e)
    publish(pid, store, [])
    return prop


@router.post("/proposals/{prop_id}/approve")
def post_approve(pid: str, prop_id: str, request: Request, body: dict = Body(default={})):
    store, actor = store_for(pid), _human(request)
    try:
        out = approve(store, prop_id, actor, body.get("ops"))
    except OpError as e:
        raise _fail(e)
    publish(pid, store, _changed(out["events"], out.get("eval_delta")))
    return out


@router.post("/proposals/{prop_id}/reject")
def post_reject(pid: str, prop_id: str, request: Request, body: dict = Body(default={})):
    store = store_for(pid)
    try:
        prop = reject(store, prop_id, _human(request), body.get("reason"))
    except OpError as e:
        raise _fail(e)
    publish(pid, store, [])
    return prop


@router.post("/nodes/{nid}/lock")
def post_lock(pid: str, nid: str, request: Request, body: dict = Body(default={})):
    nodes, _ = _apply(pid, [{"op": "lock", "node": nid, "reason": body.get("reason")}], _human(request))
    return node_json(nodes[nid])


@router.post("/nodes/{nid}/unlock")
def post_unlock(pid: str, nid: str, request: Request, body: dict = Body(default={})):
    nodes, _ = _apply(pid, [{"op": "unlock", "node": nid, "reason": body.get("reason")}], _human(request))
    return node_json(nodes[nid])


@router.post("/runs")
def post_run(pid: str, request: Request, body: dict = Body(...)):
    # Runs are evidence: the researcher (or the system, in-process via service.record_run) records them, agents never.
    actor = _human(request)
    store = store_for(pid)
    try:
        out = record_run(store, body, actor)
    except OpError as e:
        raise _fail(e)
    publish(pid, store, {body.get("node")} | set(out.get("eval_delta") or {}))
    return out


@router.post("/runs/plan")
def post_plan(pid: str, body: dict = Body(default={})):
    return gates.plan(current(store_for(pid)), body.get("targets"), bool(body.get("conditional")))


@router.post("/runs/queue")
def post_queue(pid: str, request: Request, body: dict = Body(default={})):
    """Queue cells as experiment records: the researcher with confirm, an agent within policy.agent_auto_run."""
    from .queue import queue
    store = store_for(pid)
    try:
        out = queue(store, pid, body.get("cells") or [], body.get("platform"), actor_of(request), bool(body.get("confirm")))
    except OpError as e:
        raise _fail(e)
    publish(pid, store, [c.get("node") for c in body.get("cells") or [] if isinstance(c, dict)])
    return out


@router.post("/runs/{run_id}/exclude")
def post_exclude(pid: str, run_id: str, request: Request, body: dict = Body(default={})):
    _apply(pid, [{"op": "exclude_run", "run": run_id, "reason": body.get("reason")}], _human(request))
    st = current(store_for(pid))
    return run_summary(st.runs.by_id[run_id])


@router.post("/cells/select")
def post_select(pid: str, request: Request, body: dict = Body(...)):
    nid, cell = body.get("node"), body.get("cell") or "_"
    _apply(pid, [{"op": "select_run", "node": nid, "cell": cell, "run": body.get("run_id")}], _human(request))
    st = current(store_for(pid))
    c = st.E[nid].cells.get(cell) if nid in st.E else None
    return c.json() if c else None


@router.post("/snapshots")
def post_snapshot(pid: str, request: Request, body: dict = Body(...)):
    store = store_for(pid)
    name = str(body.get("name") or "")
    if name.startswith("gate-"):
        raise HTTPException(400, {"message": "gate-* snapshots are made by passing the gate"})
    try:
        snap = make_snapshot(store, name, actor_of(request), body.get("note"))
    except ValueError as e:
        raise HTTPException(400, {"message": str(e)})
    except OpError as e:
        raise _fail(e)
    publish(pid, store, [])
    return snap


@router.post("/snapshots/{name}/restore")
def post_restore(pid: str, name: str, request: Request):
    store = store_for(pid)
    try:
        prop = restore_proposal(store, name, actor_of(request))
    except (OpError, ValueError) as e:
        raise _fail(e) if isinstance(e, OpError) else HTTPException(400, {"message": str(e)})
    publish(pid, store, [])
    return prop


@router.post("/gates/{gate}/pass")
def post_gate(pid: str, gate: str, request: Request, body: dict = Body(default={})):
    store = store_for(pid)
    try:
        snap = gates.pass_gate(store, gate, _human(request), body.get("note"))
    except OpError as e:
        raise _fail(e)
    publish(pid, store, [])
    return snap


@router.post("/paper/sync")
def post_paper_sync(pid: str, request: Request):
    store = store_for(pid)
    try:
        out = paper.sync(store, "system:paper")
    except OpError as e:
        raise _fail(e)
    store.ensure()
    with store.locked():
        store.append_events([{"by": actor_of(request), "op": "paper_sync", "summary": f"{len(out['edges_added'])} added, "
                              f"{len(out['edges_removed'])} removed, {out['macros']} macros"}])
    publish(pid, store, out["sections"])
    return out
