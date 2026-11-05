"""Queueing reruns (docs/DAG.md §2.7 "queue runs", §7 POST /runs/queue).

The researcher queues any cells (cloud or not) with an explicit confirmation. An agent may queue on its own only when
the project's policy allows it:

    policy:
      agent_auto_run: {max_gpu_hours_per_day: 8, platforms: [workstation], kinds: [experiment, figure]}

— the platform is listed, the node kind is allowed, no cell is blocked by "implement first" (impl_lag), and the agents'
estimated GPU-hours queued today (UTC) stay within the budget. Anything else is refused with the reason, so the agent
asks the researcher.

Queueing creates experiment records (status "queued") that carry the DAG node and cell. Nothing in Research Deck
dispatches them to compute: they wait in the Experiments view until the researcher (or a scheduler of their own) runs
them and records the result.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..actors import is_human
from .evaluate import current
from .gates import plan as rerun_plan
from .model import is_action, spec_of, title_of
from .ops import OpError
from .store import DagStore

MAX_CELLS = 200


def agent_gpu_hours_today(store: DagStore) -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for e in store.events():
        if e.get("op") == "runs_queued" and str(e.get("by", "")).startswith("agent:") and str(e.get("at", "")).startswith(today):
            total += float(e.get("gpu_h") or 0)
    return total


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
        allowed = set(policy.get("platforms") or [])
        budget = float(policy.get("max_gpu_hours_per_day") or 0)
        used = agent_gpu_hours_today(store)
        problems = []
        if not platforms <= allowed:
            problems.append(f"agents may queue only on {sorted(allowed) or 'no platform'} (asked: {sorted(platforms)})")
        if not kinds <= set(policy.get("kinds") or ["experiment", "figure"]):
            problems.append(f"agents may queue only {policy.get('kinds')}")
        blocked = [f"{w['node']}[{w['cell']}]" for w in wanted if w["blocked"]]
        if blocked:
            problems.append("implement first (code does not match the design yet): " + ", ".join(blocked))
        if used + gpu_h > budget + 1e-9:
            problems.append(f"over the agents' daily budget: {used:.2f} + {gpu_h:.2f} > {budget:.2f} GPU-h")
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
        store.append_events([{"by": actor, "op": "runs_queued", "platform": sorted(platforms)[0] if len(platforms) == 1 else sorted(platforms),
                              "cells": [{"node": w["node"], "cell": w["cell"]} for w in wanted], "gpu_h": gpu_h,
                              "experiments": created, "summary": f"queued {len(wanted)} cell(s), {gpu_h:.2f} GPU-h"}])
    return {"experiments": created, "gpu_h": gpu_h, "dispatched": False,
            "note": "queued in the Experiments view; Research Deck does not dispatch runs to compute"}
