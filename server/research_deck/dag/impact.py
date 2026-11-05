"""Impact preview (docs/DAG.md §5): evaluate twice — before and over an overlay — and classify every cell and node.

The overlay comes from the ops (applied by the same reducers in dry-run mode), a code diff (exact file overlay of
both sides), config edits (exact), and predictions: a design edit with no code yet marks the files of the modules that
implement the edited facet UNKNOWN, as does `touch_code`. Precision is "predicted" as soon as anything is UNKNOWN.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .evaluate import NodeE, State, build, current, pred_text
from .fp import MISSING, UNKNOWN, fp_json, glob_match, show
from .model import DEAD, SOFT, agent_mode, edge_key, edges, facet_value, parse_addr, rank, ref_id, spec_of
from .ops import OpError, Txn, bound_nodes, is_privileged
from .resolve import code_patch, flatten, load_yaml

CATEGORIES = ("rerun", "conditional", "reused", "revived", "review", "orphaned", "broken", "lock", "already_tried",
              "suggest_restore")


def family(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else "/".join(parts[:-1]) or parts[0]


def _age(run: dict) -> str | None:
    at = run.get("ended") or run.get("started") or run.get("recorded_at")
    try:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(str(at).replace("Z", "+00:00"))).days
    except (TypeError, ValueError):
        return None
    return f"{days}d"


def _usd(st: State, platform: str | None, gpu_h: float) -> float:
    probe = st.store.env_probe(platform) if platform else None
    return round(gpu_h * float((probe or {}).get("usd_per_gpu_hour") or 0), 2)


def _margin(pred: dict | None, value: float | None) -> float | None:
    if not pred or value is None:
        return None
    return round(value - pred["rhs"] if pred["op"] in (">=", ">") else pred["rhs"] - value if pred["op"] in ("<=", "<") else 0.0, 6)


def impact(store, body: dict, actor: str = "human:preview") -> dict:
    s0 = current(store)
    ops = [o for o in body.get("ops") or [] if isinstance(o, dict)]
    code = body.get("code") or None
    touch = list(body.get("touch_code") or [])
    errors: list[str] = []
    requires: list[str] = []

    # 1. G1 = the ops applied by the same reducers, dry-run; permission failures become requires_human
    t = Txn(store, actor, state=s0, dry=True)
    for op in ops:
        kind = op.get("op")
        if kind == "touch_code":
            touch += list(op.get("globs") or [])
            continue
        if kind == "code":
            code = {k: v for k, v in op.items() if k != "op"} or code
            continue
        if not is_privileged(actor):
            bn = bound_nodes(t.nodes, str(op.get("file")), str(op.get("key"))) if kind == "config_edit" else None
            mode, why = agent_mode(op, t.nodes, actor, bn)
            if mode != "direct":
                requires.append(why)
        try:
            t.apply(op)
        except OpError as e:
            errors.append(f"{kind}: {e.message}")
    for hit in t.lock_hits:
        if hit.get("requires"):
            requires.append(f"{hit['kind'].replace('_', ' ')} {hit['node']}")

    # 2. the overlay patch
    patched: list[dict] = []
    ignored: list[dict] = []
    files_from: dict = {}
    files_to: dict = {}
    if code:
        try:
            files_from, files_to, patched, ignored = code_patch(s0.repo, code)
        except ValueError as e:
            errors.append(f"code: {e}")
    cfg_fams: set[str] = set()
    for rel, data in t.files.items():              # config edits (after any code diff)
        before = files_to.get(rel) if rel in files_to else s0.R.tree().read(rel)
        old, new = flatten(load_yaml(before) or {}), flatten(load_yaml(data) or {})
        for k in sorted(set(old) | set(new)):
            if old.get(k, MISSING) != new.get(k, MISSING):
                patched.append({"addr": f"cfg:{k}", "from": fp_json(old[k]) if k in old else MISSING,
                                "to": fp_json(new[k]) if k in new else MISSING, "via": rel})
                cfg_fams.add(k.split(".")[0])
        files_from.setdefault(rel, before)
        files_to[rel] = data
    for rel in list(files_to):                     # config files changed by a code diff: their keys too
        if rel not in t.files and rel.endswith((".yaml", ".yml")):
            old, new = flatten(load_yaml(files_from.get(rel)) or {}), flatten(load_yaml(files_to[rel]) or {})
            cfg_fams |= {k.split(".")[0] for k in set(old) | set(new) if old.get(k, MISSING) != new.get(k, MISSING)}
    predicted: dict[str, Any] = {}
    origins: dict[str, list] = {}                  # code glob -> why-path prefix
    for nid, facet, how in dict.fromkeys(t.edited):
        n0, n1 = s0.nodes.get(nid), t.nodes.get(nid)
        f0 = ((n0 or {}).get("facets") or {}).get(facet)
        f1 = ((n1 or {}).get("facets") or {}).get(facet)
        if f0 == f1:
            continue
        fp0 = s0.R.facet_fp(n0, facet, f0) if n0 and f0 else MISSING
        fp1 = s0.R.facet_fp(n1, facet, f1) if n1 and f1 else MISSING
        patched.append({"addr": f"node:{nid}#{facet}", "from": show(fp0), "to": show(fp1)})
        if code is None and how == "edit" and (f1 or {}).get("type") in ("prose", "text", "json"):
            for m in t.nodes.values():
                if m.get("kind") == "module" and m.get("status") not in DEAD and any(
                        str(e.get("to")) == f"node:{nid}#{facet}" for e in edges(m, "implements")):
                    for g in facet_value(m, "globs") or []:
                        predicted[f"code:{g}"] = UNKNOWN
                        origins[g] = [f"node:{nid}#{facet}", "implements", m["id"], "glob"]
                        nfiles = len([p for p in s0.R.tree().files if glob_match(p, g)])
                        patched.append({"addr": f"code:{g}", "from": f"{nfiles} files", "to": "UNKNOWN",
                                        "via": f"{m['id']} implements {nid}#{facet}"})
    for g in touch:
        predicted[f"code:{g}"] = UNKNOWN
        origins.setdefault(g, ["touch_code"])
        patched.append({"addr": f"code:{g}", "from": None, "to": "UNKNOWN", "via": "touch_code"})

    # 3. E0 and E1
    s0e = s0 if not files_from else build(store, nodes=s0.nodes, repo=s0.repo, files=files_from, runs=s0.runs)
    s1 = build(store, nodes=t.nodes, repo=s0.repo, files=files_to or None, predicted=predicted or None, runs=t.runs())
    E0, E1 = s0e.E, s1.E
    out: dict[str, Any] = {c: [] for c in CATEGORIES}
    gpu = {"rerun": 0.0, "conditional_worst": 0.0, "reused": 0.0, "full_campaign": 0.0}
    usd = 0.0
    why_paths: dict[str, list[str]] = {}
    code_paths = [p["addr"][5:] for p in patched if p["addr"].startswith("code:")]
    code_fams = {family(p.rstrip("*").rstrip("/") or p) for p in code_paths}
    changed_nodes = {i for i in set(t.nodes) | set(s0.nodes) if (t.nodes.get(i) or {}).get("facets") != (s0.nodes.get(i) or {}).get("facets")
                     or (t.nodes.get(i) or {}).get("edges") != (s0.nodes.get(i) or {}).get("edges")}
    dependents: dict[str, set[str]] = defaultdict(set)
    for n in t.nodes.values():
        for e in edges(n):
            if (up_id := ref_id(e.get("to"))):
                dependents[up_id].add(n["id"])
    downstream, stack = set(), list(changed_nodes)
    while stack:
        for d in dependents.get(stack.pop(), ()):
            if d not in downstream:
                downstream.add(d)
                stack.append(d)

    def why_path(addr: str) -> list[str]:
        loc = addr.split(":", 1)[1] if ":" in addr else addr
        for g, prefix in origins.items():
            if addr.startswith("code:") and glob_match(loc, g):
                return [*prefix, addr, "trace"]
        if addr.startswith("cfg:"):
            for n in t.nodes.values():
                for name, f in (n.get("facets") or {}).items():
                    if isinstance(f, dict) and f.get("type") == "bound" and loc.startswith(str(f.get("bind")).partition("#")[2]):
                        return [f"node:{n['id']}#{name}", "bind", addr, "trace"]
        return [addr, "trace"]

    # 4. classify action cells
    for nid, ev1 in sorted(E1.items()):
        if not ev1.action or ev1.archived:
            continue
        ev0: NodeE | None = E0.get(nid)
        n = t.nodes[nid]
        platform = spec_of(n).get("platform")
        groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for cid, c1 in ev1.cells.items():
            gpu["full_campaign"] += c1.gpu_h or 0
            c0 = ev0.cells.get(cid) if ev0 and not ev0.archived else None
            if c0 is None:
                continue
            l0, l1 = c0.level, c1.level
            if l0 in ("fresh", "pending") and l1 in ("stale", "unbuilt"):
                groups["rerun"]["cells"].append(cid)
                groups["rerun"]["why"] += [w for w in c1.why if w.get("addr")]
                groups["rerun"]["lag"].append(c1.impl_lag)
                gpu["rerun"] += c1.gpu_h or 0
                usd += _usd(s0, platform, c1.gpu_h or 0)
                first = next((w["addr"] for w in c1.why if w.get("addr")), None)
                if first:
                    why_paths[f"{nid}[{cid}]"] = why_path(first)
            elif l0 == "fresh" and l1 == "pending":
                groups["conditional"]["cells"].append(cid)
                gpu["conditional_worst"] += c1.gpu_h or 0
            elif l1 == "fresh" and (l0 != "fresh" or (c0.run or {}).get("id") != (c1.run or {}).get("id")):
                # not fresh → fresh, or an older run verifies again and becomes the selected one (§9 steps 5, 7)
                groups["revived"]["cells"].append(cid)
                groups["revived"]["runs"].append(c1.run)
            elif l0 == "fresh" and l1 == "fresh":
                groups["fresh"]["cells"].append(cid)
        for cat in ("rerun", "conditional"):
            if groups[cat]["cells"]:
                uniq = list({(w["addr"], w.get("from"), w.get("to")): {"addr": w["addr"], "from": w.get("from"), "to": w.get("to")}
                             for w in groups[cat].get("why", [])}.values())[:12]
                item = {"node": nid, "cells": groups[cat]["cells"], "platform": platform,
                        "est_gpu_h": round(sum(ev1.cells[c].gpu_h or 0 for c in groups[cat]["cells"]), 4)}
                if cat == "rerun":
                    item.update(why=uniq, impl_lag=any(groups[cat]["lag"]))
                out[cat].append(item)
        for cid, run in zip(groups["revived"]["cells"], groups["revived"]["runs"]):
            out["revived"].append({"node": nid, "cells": [cid], "run": run["id"], "age": _age(run),
                                   "est_gpu_h": ev1.cells[cid].gpu_h})
        near_node = nid in downstream or bool(groups["rerun"]["cells"] or groups["conditional"]["cells"] or groups["revived"]["cells"])
        reasons: dict[str, list[str]] = defaultdict(list)
        for cid in groups["fresh"]["cells"]:
            c1 = ev1.cells[cid]
            trace = (c1.run or {}).get("trace") or {}
            codes = [a[5:] for a in trace if a.startswith("code:")]
            cfgs = [a[4:] for a in trace if a.startswith("cfg:")]
            code_near = any(family(p) in code_fams for p in codes)
            cfg_near = any(k.split(".")[0] in cfg_fams for k in cfgs)
            if not (near_node or code_near or cfg_near):
                continue
            overrides = [k for k in ev1.cell_values.get(cid, {}) if k.split(".")[0] in cfg_fams]
            if overrides:
                reason = f"cell overrides {', '.join(overrides)}"
            elif cfg_fams and not any(k.split(".")[0] in cfg_fams for k in cfgs) and not code_paths:
                reason = f"never read {', '.join(sorted(f + '.*' for f in cfg_fams))}"
            elif code_paths:
                hit = sum(1 for p in codes if any(glob_match(p, g) for g in code_paths))
                fams = sorted({family(p) for p in codes if family(p) in code_fams})
                reason = (f"trace has {hit} of {len(code_paths)} changed files" if all("*" not in g for g in code_paths)
                          else f"trace has no {', '.join(code_paths)} file") + (f" ({', '.join(fams)})" if fams else "")
            else:
                reason = "inputs unchanged"
            reasons[reason].append(cid)
            gpu["reused"] += c1.gpu_h or 0
        for reason, cells in reasons.items():
            out["reused"].append({"node": nid, "cells": cells, "reason": reason,
                                  "est_gpu_h": round(sum(ev1.cells[c].gpu_h or 0 for c in cells), 4)})

    # 5. beliefs: conditional, revived, and reasons new in E1
    for nid, ev1 in sorted(E1.items()):
        if ev1.archived:
            continue
        ev0 = E0.get(nid)
        l0 = ev0.level if ev0 and not ev0.archived else None
        if not ev1.action and l0 == "fresh" and ev1.level == "pending":
            for r in (r for r in ev1.reasons if r["level"] == "pending"):
                e = next((x for x in edges(t.nodes[nid]) if edge_key(x) == r.get("edge")), {})
                pred = e.get("predicate") or e.get("kill_if")
                out["conditional"].append({"node": nid, "via": [parse_addr(e["to"]).id] if e else [], "edge": r.get("edge"),
                                           "predicate": pred_text(pred), "current": r.get("value"), "margin": _margin(pred, r.get("value"))})
        if not ev1.action and l0 not in (None, "fresh") and ev1.level == "fresh":
            out["revived"].append({"node": nid, "note": f"{l0} → fresh"})
        old = {(r["level"], r.get("edge"), r.get("addr"), r.get("note")) for r in (ev0.reasons if ev0 else [])}
        for r in ev1.reasons:
            if r["level"] in ("review", "orphaned", "broken") and (r["level"], r.get("edge"), r.get("addr"), r.get("note")) not in old:
                item = {"node": nid, "edge": r.get("edge"), "note": r.get("note")}
                if r["level"] == "review" and r.get("note") and "→" in str(r.get("note")):
                    item["diff"] = r["note"]
                if r["level"] == "broken":
                    e = next((x for x in edges(t.nodes[nid]) if edge_key(x) == r.get("edge")), {})
                    item.update(predicate=pred_text(e.get("predicate") or e.get("kill_if")), current=r.get("value"))
                out[r["level"]].append(item)
                up = parse_addr(r["edge"].split(":", 1)[1]) if r.get("edge") and ":" in r["edge"] else None
                if up and up.scheme == "node":
                    why_paths.setdefault(nid, [str(up), r["edge"].split(":", 1)[0], nid])

    # 6. locks, already_tried, rollback closure, gates
    out["lock"] = [dict(h) for h in t.lock_hits]
    for nid, n in t.nodes.items():
        if n.get("status") == "locked" and nid in E0 and rank(E1[nid].level) > rank(E0[nid].level) \
                and not any(h["node"] == nid for h in out["lock"]):
            out["lock"].append({"node": nid, "kind": "level_rise", "note": f"{E0[nid].level} → {E1[nid].level}"})
    revived_runs = {i["run"] for i in out["revived"] if i.get("run")}
    for n in t.nodes.values():
        if n.get("status") not in DEAD:
            continue
        for e in edges(n, "evidence"):
            a = parse_addr(e["to"])
            if a.scheme == "run" and a.id in revived_runs:
                o = ((s1.runs.by_id.get(a.id) or {}).get("outputs") or {}).get(a.out or "") or {}
                verdict = n.get("verdict") or {}
                cond = f"kill_if met ({a.out} {o.get('value')})" if e.get("kill_if") else f"{a.out} {o.get('value')}"
                out["already_tried"].append({"node": n["id"], "run": a.id, "reason": verdict.get("reason"),
                                             "kind": n.get("status"), "note": f"{n['id']} {n.get('status')}, {cond}"})
    for item in out["review"]:
        nid = item["node"]
        n = t.nodes.get(nid)
        if not n or any(s["node"] == nid for s in out["suggest_restore"]):
            continue
        for v in reversed(store.history(nid)[:-1]):
            seen_edges = [e for e in v.get("edges") or [] if e.get("seen") and e.get("type") in SOFT]
            if not seen_edges or v.get("edges") == n.get("edges"):
                continue
            if all(s1.R.node_fp(e["to"], pin=e.get("pin")) == e["seen"] for e in seen_edges):
                out["suggest_restore"].append({"node": nid, "note": f"restore {nid} edges from r{v.get('rev')}",
                                               "op": {"op": "rollback", "node": nid, "to_vid": v["vid"], "edges": "only"}})
                break
    try:
        from .gates import compute as gates_of   # noqa: PLC0415
        g0 = {g["gate"]: g["state"] for g in gates_of(s0e)}
        gates = [{"gate": g["gate"], "from": g0.get(g["gate"]), "to": g["state"]} for g in gates_of(s1) if g0.get(g["gate"]) != g["state"]]
    except Exception:  # noqa: BLE001 — gates are advisory; a preview must not fail on them
        gates = []

    distinct = lambda cat: len({i["node"] for i in out[cat]})   # noqa: E731
    summary = {"rerun": sum(len(i["cells"]) for i in out["rerun"]),
               "conditional": sum(len(i.get("cells") or [1]) for i in out["conditional"]),
               "reused": sum(len(i["cells"]) for i in out["reused"]),
               "revived": sum(len(i.get("cells") or [1]) for i in out["revived"]),
               "review": distinct("review"), "orphaned": distinct("orphaned"), "broken": distinct("broken"),
               "lock": len(out["lock"]), "gpu_h": {k: round(v, 4) for k, v in gpu.items()}, "usd": {"rerun": round(usd, 2)}}
    requires += [f"{h['kind'].replace('_', ' ')} {h['node']}" for h in out["lock"] if h["kind"] == "level_rise"]
    return {"base_digest": s0.digest, "precision": "predicted" if predicted else "exact",
            "patched": [{k: show(v) for k, v in p.items()} for p in patched], "ignored": ignored, "summary": summary,
            **out, "gates": gates, "requires_human": {"value": bool(requires), "reasons": list(dict.fromkeys(requires))},
            "why_paths": why_paths, "errors": errors}

