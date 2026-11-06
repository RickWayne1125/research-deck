"""Queueing reruns (docs/DAG.md §2.7 "queue runs", §7 POST /runs/queue).

The researcher queues any cells (cloud or not) with an explicit confirmation. An agent may queue on its own only when
the node kind is allowed (policy.agent_auto_run.kinds), no cell is blocked by "implement first" (impl_lag), and every
platform allows it:

- a platform that is a resource pool (pools/): the project uses the pool, and the pool's budget gives agents GPU-hours
  (budget.agent_gpu_hours_per_day, per project and day; 0 or unset: never), which the agents' estimated GPU-hours
  queued there today (UTC) stay within;
- any other platform: the project's policy lists it, within its daily budget —

    policy:
      agent_auto_run: {max_gpu_hours_per_day: 8, platforms: [workstation], kinds: [experiment, figure]}

Anything else is refused with the reason, so the agent asks the researcher.

Queueing creates experiment records (status "queued") that carry the DAG node and cell. Nothing in Research Deck
dispatches them to compute: they wait in the Experiments view until the researcher (or a scheduler of their own) runs
them and records the result.
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..actors import is_human
from .evaluate import current
from .gates import plan as rerun_plan
from .model import is_action, spec_of, title_of
from .ops import OpError
from .store import DagStore

MAX_CELLS = 200


def _agent_queued_today(store: DagStore) -> list[dict]:
    today = datetime.now(UTC).date().isoformat()
    return [e for e in store.events() if e.get("op") == "runs_queued" and str(e.get("by", "")).startswith("agent:")
            and str(e.get("at", "")).startswith(today)]


def agent_gpu_hours_today(store: DagStore) -> float:
    return sum(float(e.get("gpu_h") or 0) for e in _agent_queued_today(store))


def agent_gpu_hours_by_platform_today(store: DagStore) -> dict[str, float]:
    """The agents' GPU-hours queued today (UTC) by platform (lowercase). An older event that queued on several
    platforms at once, without a breakdown, counts in full against each (over-counting is the safe side of a budget)."""
    out: dict[str, float] = {}
    for e in _agent_queued_today(store):
        by = e.get("gpu_h_by_platform")
        if isinstance(by, dict):
            items = [(str(k), float(v or 0)) for k, v in by.items()]
        else:
            p = e.get("platform")
            names = [p] if isinstance(p, str) else [str(x) for x in p] if isinstance(p, list) else []
            items = [(n, float(e.get("gpu_h") or 0)) for n in names]
        for name, h in items:
            out[name.lower()] = out.get(name.lower(), 0.0) + h
    return out


def agent_problems(store: DagStore, pid: str, wanted: list[dict], kinds: set, policy: dict) -> list[str]:
    """Why an agent may not queue these cells by itself (empty: it may)."""
    from ..pools import service as pool_service
    from ..pools import store as pool_store
    pools = {p["id"]: p for p in pool_store.load_all()}
    sel = pool_service.selection(pid)
    want: dict[str, float] = {}
    for w in wanted:
        want[w["platform"]] = want.get(w["platform"], 0.0) + w["est_gpu_h"]
    used = agent_gpu_hours_by_platform_today(store)
    problems = []
    others = sorted(p for p in want if p.lower() not in pools)
    for name in sorted(p for p in want if p.lower() in pools):
        pool = pools[name.lower()]
        limit = float(pool["budget"].get("agent_gpu_hours_per_day") or 0)
        have = used.get(pool["id"], 0.0)
        if sel is not None and pool["id"] not in sel:
            problems.append(f"this project does not use the resource pool {name}")
        elif limit <= 0:
            problems.append(f"agents may not queue on {name}: its budget gives agents no GPU-hours")
        elif have + want[name] > limit + 1e-9:
            problems.append(f"over {name}'s daily budget for agents: {have:.2f} + {want[name]:.2f} > {limit:.2f} GPU-h")
    if others:
        allowed = set(policy.get("platforms") or [])
        budget = float(policy.get("max_gpu_hours_per_day") or 0)
        have = sum(h for p, h in used.items() if p not in pools)
        asked = sum(want[p] for p in others)
        if not set(others) <= allowed:
            problems.append(f"agents may queue only on {sorted(allowed) or 'no platform'} (asked: {others})")
        if have + asked > budget + 1e-9:
            problems.append(f"over the agents' daily budget: {have:.2f} + {asked:.2f} > {budget:.2f} GPU-h")
    if not kinds <= set(policy.get("kinds") or ["experiment", "figure"]):
        problems.append(f"agents may queue only {policy.get('kinds')}")
    blocked = [f"{w['node']}[{w['cell']}]" for w in wanted if w["blocked"]]
    if blocked:
        problems.append("implement first (code does not match the design yet): " + ", ".join(blocked))
    return problems


def queue(store: DagStore, pid: str, cells: list[dict], platform: str | None, actor: str, confirm: bool) -> dict:
    if not isinstance(cells, list) or not cells or len(cells) > MAX_CELLS:
        raise OpError(400, f"cells: 1–{MAX_CELLS} {{node, cell}} items")
    st = current(store)
    estimates = {(i["node"], i["cell"]): i for wave in rerun_plan(st, conditional=True)["waves"] for i in wave}
    wanted, kinds = [], set()
    for c in cells:
        nid, cid = str((c or {}).get("node") or ""), str((c or {}).get("cell") or "_")
        n = st.nodes.get(nid)
        if not n or not is_action(n) or st.E[nid].archived:
            raise OpError(404, f"not a live action node: {nid}")
        if cid not in st.E[nid].cells:
            raise OpError(404, f"{nid} has no cell {cid}")
        item = estimates.get((nid, cid)) or {"est_gpu_h": st.E[nid].cells[cid].gpu_h, "blocked": None}
        wanted.append({"node": nid, "cell": cid, "title": title_of(n), "est_gpu_h": float(item.get("est_gpu_h") or 0),
                       "blocked": item.get("blocked"), "platform": platform or spec_of(n).get("platform"), "spec": spec_of(n)})
        kinds.add(n.get("kind"))
    platforms = {w["platform"] for w in wanted}
    if None in platforms:
        raise OpError(400, "no platform: pass one, or set spec.platform on the node")
    gpu_h = round(sum(w["est_gpu_h"] for w in wanted), 4)

    policy = (st.cfg.get("policy") or {}).get("agent_auto_run") or {}
    if is_human(actor):
        if not confirm:
            raise OpError(409, "confirm the queue (confirm: true)", gpu_h=gpu_h, cells=len(wanted))
    else:
        problems = agent_problems(store, pid, wanted, kinds, policy)
        if problems:
            raise OpError(403, "ask the researcher to queue these runs: " + "; ".join(problems), problems=problems)

    from ..experiments import records
    created = []
    for w in wanted:
        spec = w["spec"]
        rec = records.create_record(pid, {
            "title": f"{w['title']} [{w['cell']}]" if w["cell"] != "_" else w["title"],
            "node_id": w["node"], "cell": w["cell"], "command": spec.get("command"),
            "target": {"platform": w["platform"], "node": "", "gpus": int(spec.get("gpus") or 0)},
            "config": {"est_gpu_h": w["est_gpu_h"], "queued_by": actor},
        }, actor)
        records.patch_record(pid, rec["id"], {"status": "queued"}, actor)
        created.append(rec["id"])
    with store.locked():
        by_platform: dict[str, float] = {}
        for w in wanted:
            by_platform[w["platform"]] = round(by_platform.get(w["platform"], 0.0) + w["est_gpu_h"], 4)
        store.append_events([{"by": actor, "op": "runs_queued", "platform": sorted(platforms)[0] if len(platforms) == 1 else sorted(platforms),
                              "cells": [{"node": w["node"], "cell": w["cell"]} for w in wanted], "gpu_h": gpu_h,
                              "gpu_h_by_platform": by_platform,
                              "experiments": created, "summary": f"queued {len(wanted)} cell(s), {gpu_h:.2f} GPU-h"}])
    return {"experiments": created, "gpu_h": gpu_h, "dispatched": False,
            "note": "queued in the Experiments view; Research Deck does not dispatch runs to compute"}
