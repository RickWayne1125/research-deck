"""Computed gates (docs/DAG.md §1), the four lenses (§8) and rerun waves (§7 /runs/plan).

Gates are checklists over the live evaluation, not nodes; thresholds come from config.yaml; advisory unless
gates.blocking. A human passing a gate logs `gate_passed` and snapshots `gate-Gk`; a passed gate that later loses a
check shows passed_degraded.
"""
from __future__ import annotations

from typing import Any

from ..actors import is_human
from .evaluate import State, current
from .model import DEAD, edges, facet_value, is_action, rank, ref_id, spec_of, title_of
from .ops import OpError, make_snapshot
from .stages import OUTLINE_KINDS

GATES = [
    ("G1", "S1", "Worth pursuing", "值得做"), ("G2", "S2", "The issue is real", "问题真实存在"),
    ("G3", "S3", "Go / no-go", "做不做"), ("G4", "S4", "Commit to an approach", "选定方案"),
    ("G5", "S5", "Design frozen", "设计冻结"), ("G6", "S6", "Claims hold", "论点成立"), ("G7", "W", "Submission", "投稿就绪"),
]
CONFIRMED = {"confirmed", "locked"}


def _chk(key: str, en: str, zh: str, ok: bool, value: Any = None, target: Any = None, items: list[str] | None = None) -> dict:
    return {"key": key, "label": en, "zh": zh, "ok": bool(ok), "value": value, "target": target, "items": items or []}


def _live(st: State, kind: str) -> list[dict]:
    return [n for n in st.nodes.values() if n.get("kind") == kind and n.get("status") not in DEAD]


def _purpose(n: dict) -> str | None:
    return n.get("purpose") or facet_value(n, "purpose")


def _fresh(st: State, nid: str) -> bool:
    ev = st.E.get(nid)
    return bool(ev) and ev.level == "fresh"


def _evidence_nodes(n: dict) -> list[str]:
    return [i for e in edges(n, "evidence") if (i := ref_id(e.get("to")))]


def compute(st: State) -> list[dict]:
    g = st.cfg.get("gates") or {}
    passed = {}
    for ev in st.store.events():
        if ev.get("op") == "gate_passed":
            passed[ev.get("gate")] = {"by": ev.get("by"), "at": ev.get("at"), "snapshot": ev.get("snapshot")}
    refs, exps = _live(st, "reference"), _live(st, "experiment")
    checks: dict[str, list[dict]] = {}

    c1 = g.get("G1") or {}
    probs = [n["id"] for n in _live(st, "problem") if n["status"] in CONFIRMED]
    comps = [n["id"] for n in refs if facet_value(n, "role") == "competitor" and str(facet_value(n, "delta") or "").strip()]
    repro, bad = [n for n in exps if _purpose(n) == "reproduce"], []
    explained = {i for f in _live(st, "finding") for e in edges(f) if (i := ref_id(e.get("to")))}
    for n in repro:
        within = True
        for name, spec in (facet_value(n, "outputs") or {}).items():
            exp_v = spec.get("expected") if isinstance(spec, dict) else None
            for _, v, _, _ in (st.E[n["id"]].rows(name, None) or []) if exp_v else []:
                if isinstance(v, (int, float)) and abs(v - exp_v) > float((g.get("G2") or {}).get("baseline_repro_tol", 0.1)) * abs(exp_v):
                    within = False
        if not ((_fresh(st, n["id"]) and within) or n["id"] in explained):
            bad.append(n["id"])
    checks["G1"] = [
        _chk("problem_confirmed", "Problem confirmed", "问题已确认", bool(probs), len(probs), 1, probs),
        _chk("references", "References", "参考文献数", len(refs) >= c1.get("min_refs", 5), len(refs), c1.get("min_refs", 5)),
        _chk("competitors", "Competitors with a delta", "有差异说明的竞品", len(comps) >= 2, len(comps), 2, comps),
    ]
    # Reproducing the baselines is the first experiment, so it belongs to Motivation & insight (G2), not to Idea: the
    # first step is framing and the survey of existing work.
    baselines = _chk("baselines_reproduced", "Baselines reproduced", "基线已复现", bool(repro) and not bad,
                     len(repro) - len(bad), len(repro), bad)

    c2 = g.get("G2") or {}
    good = []
    for f in _live(st, "finding"):
        if f["status"] not in CONFIRMED or not _fresh(st, f["id"]):
            continue
        workloads, reps = set(), []
        for up in _evidence_nodes(f):
            un = st.nodes.get(up)
            if not un:
                continue
            ov = (spec_of(un).get("overrides") or {}).get("workload")
            for cid, cell in st.E[up].cells.items():
                workloads.add(str(st.E[up].cell_values.get(cid, {}).get("workload", ov)))
                reps += [int(o.get("n")) for o in ((cell.run or {}).get("outputs") or {}).values() if isinstance(o, dict) and o.get("n")]
            reps = reps or [int(spec_of(un).get("replicates") or 1)]
        if len(workloads - {"None"}) >= c2.get("min_workloads", 2) and reps and min(reps) >= c2.get("min_replicates", 3):
            good.append(f["id"])
    checks["G2"] = [baselines,
                    _chk("finding_replicated", "Confirmed finding on enough workloads and replicates", "已确认且多负载、多次复现的发现",
                         bool(good), len(good), 1, good)]

    c3 = g.get("G3") or {}
    gaps = [n["id"] for n in _live(st, "gap") if n["status"] in CONFIRMED
            and float((facet_value(n, "headroom") or {}).get("ratio") or 0) >= float(c3.get("min_headroom", 1.3))]
    closed = [n["id"] for n in refs if facet_value(n, "closes_gap")]
    checks["G3"] = [_chk("gap_headroom", "Confirmed gap with enough headroom", "有足够空间的已确认差距", bool(gaps), len(gaps), c3.get("min_headroom", 1.3), gaps),
                    _chk("not_closed", "No competitor closes the gap", "没有竞品已填补该差距", not closed, len(closed), 0, closed)]

    c4 = g.get("G4") or {}
    decisions = [n for n in _live(st, "decision") if n["status"] == "locked"]
    groups: dict[str, list[dict]] = {}
    for n in st.nodes.values():
        if n.get("kind") == "solution" and n.get("alt_group"):
            groups.setdefault(n["alt_group"], []).append(n)
    tried = max((sum(1 for s in sibs if s.get("status") in CONFIRMED | DEAD) for sibs in groups.values()), default=0)
    chosen = [facet_value(d, "choice") for d in decisions if facet_value(d, "choice")]
    validated, captured = [], None
    for sid in chosen:
        s = st.nodes.get(sid) or {}
        ups = [u for u in _evidence_nodes(s) if _purpose(st.nodes.get(u) or {}) == "validate" and _fresh(st, u)]
        if ups:
            validated.append(sid)
        cap = (st.E.get(sid).values if st.E.get(sid) else {}).get("captured")
        captured = cap if cap is not None else captured
    min_cap = float(c4.get("min_captured", 0.5))
    checks["G4"] = [
        _chk("decision_locked", "Decision locked", "决策已锁定", bool(decisions), len(decisions), 1, [d["id"] for d in decisions]),
        _chk("alternatives", "Alternatives tried, each with a verdict", "已尝试且有结论的备选方案", tried >= c4.get("min_alternatives", 2),
             tried, c4.get("min_alternatives", 2)),
        _chk("validated", "Chosen solution validated", "所选方案已验证", bool(validated) and (captured is None or captured >= min_cap),
             captured, min_cap, validated),
        _chk("claims_drafted", "Claims drafted", "论点已起草", bool(_live(st, "claim")), len(_live(st, "claim")), 1),
    ]

    c5 = g.get("G5") or {}
    designs = _live(st, "design")
    lag = [m["id"] for m in _live(st, "module") if st.E[m["id"]].has_reason("implements")]
    micro = [n for n in exps if _purpose(n) == "microbench"]
    checks["G5"] = [
        _chk("design_frozen", "Design confirmed or locked", "设计已确认或锁定", bool(designs) and all(d["status"] in CONFIRMED for d in designs),
             sum(d["status"] in CONFIRMED for d in designs), len(designs), [d["id"] for d in designs if d["status"] not in CONFIRMED]),
        _chk("implements_current", "No module lags its design", "实现与设计一致", not lag, len(lag), 0, lag),
        _chk("microbench_fresh", "Microbenchmarks fresh", "微基准为最新", bool(micro) and all(_fresh(st, m["id"]) for m in micro),
             sum(_fresh(st, m["id"]) for m in micro), len(micro), [m["id"] for m in micro if not _fresh(st, m["id"])]),
    ]
    _ = c5

    claims, figs = _live(st, "claim"), _live(st, "figure")
    bad_claims = [c["id"] for c in claims if not _fresh(st, c["id"])]
    bad_figs = [f["id"] for f in figs if not _fresh(st, f["id"])]
    closure_bad, seen_ids, stack = set(), set(), [u for c in claims for u in _evidence_nodes(c)]
    while stack:
        i = stack.pop()
        if i in seen_ids or i not in st.E:
            continue
        seen_ids.add(i)
        if any(c.level in ("stale", "unbuilt") for c in st.E[i].cells.values()):
            closure_bad.add(i)
        stack += [u for e in edges(st.nodes[i], "input") if (u := ref_id(e.get("to")))]
    checks["G6"] = [
        _chk("claims_fresh", "Every live claim holds and is fresh", "所有论点成立且为最新", bool(claims) and not bad_claims,
             len(claims) - len(bad_claims), len(claims), bad_claims),
        _chk("figures_fresh", "Every figure fresh", "所有图为最新", not bad_figs, len(figs) - len(bad_figs), len(figs), bad_figs),
        _chk("closure_built", "No stale or unbuilt cell behind any claim", "论点证据链中无需重跑或未运行的实验", not closure_bad,
             len(closure_bad), 0, sorted(closure_bad)),
    ]

    g6_ok = all(c["ok"] for c in checks["G6"])
    sections = [s["id"] for s in _live(st, "section") if st.E[s["id"]].level not in ("fresh", None)]
    submit = [s.get("name") for s in st.store.snapshots() if str(s.get("name", "")).startswith("submit-")]
    unlocked = [n["id"] for n in [*claims, *figs, *designs] if n["status"] != "locked"]
    checks["G7"] = [
        _chk("g6", "G6 holds", "G6 通过", g6_ok),
        _chk("sections_current", "No section in review", "无待复核章节", not sections, len(sections), 0, sections),
        _chk("submit_snapshot", "Submission snapshot", "投稿快照", bool(submit), len(submit), 1, submit),
        _chk("all_locked", "Claims, figures and design locked", "论点、图与设计已锁定", not unlocked, len(unlocked), 0, unlocked),
    ]

    out = []
    for gate, after, en, zh in GATES:
        ok = all(c["ok"] for c in checks[gate])
        p = passed.get(gate)
        state = ("passed" if ok else "passed_degraded") if p else ("open" if ok else "failing")
        out.append({"gate": gate, "after": after, "title": {"en": en, "zh": zh}, "state": state, "checks": checks[gate], "passed": p})
    return out


def pass_gate(store, gate: str, actor: str, note: str | None = None) -> dict:
    if not is_human(actor):
        raise OpError(403, "open a proposal")
    st = current(store)
    status = next((g for g in compute(st) if g["gate"] == gate), None)
    if status is None:
        raise OpError(404, f"unknown gate {gate}")
    failing = [c["label"] for c in status["checks"] if not c["ok"]]
    if failing and (st.cfg.get("gates") or {}).get("blocking"):
        raise OpError(409, "gate checks fail: " + ", ".join(failing), failing=failing)
    snap = make_snapshot(store, f"gate-{gate}", actor, note or f"{gate} passed", overwrite=True)
    with store.locked():
        store.append_events([{"by": actor, "op": "gate_passed", "gate": gate, "snapshot": snap["name"], "failing": failing, "summary": note},
                             {"by": actor, "op": "decision", "kind": "gate_pass", "gate": gate, "reason": note, "approver": actor}])
    return snap


# ---------------------------------------------------------------- lenses

def lenses(st: State) -> dict:
    tried, confirmed, revise, rerun = [], [], [], []
    total_runs = len(st.runs.by_id)
    dead = 0
    gpu = 0.0
    blocked = conditional = count = 0
    for nid, n in sorted(st.nodes.items()):
        ev = st.E[nid]
        nruns = len(st.runs.by_node.get(nid, []))
        attempt = n.get("kind") not in OUTLINE_KINDS   # the paper's sections and items are not attempts
        if ev.archived and attempt:
            dead += 1
        v = n.get("verdict") or {}                 # every attempt, dead ones included, with its verdict or run count
        if attempt:
            tried.append({"id": nid, "note": v.get("reason") or (f"{nruns} runs" if is_action(n) else n.get("status"))})
        if ev.archived:
            continue
        if n.get("status") in CONFIRMED and ev.level == "fresh":
            confirmed.append({"id": nid, **({"note": "via " + ", ".join(sorted(ev.shaky)[:3])} if ev.shaky else {})})
        if rank(ev.level) in (rank("review"), rank("orphaned"), rank("broken")) or "lock_alert" in ev.flags or "review_ring" in ev.flags:
            r = next((r for r in ev.reasons if r["level"] != "fresh"), {})
            revise.append({"id": nid, "note": r.get("note") or r.get("edge") or ev.level})
        if ev.action:
            run_c = [cid for cid, c in ev.cells.items() if c.level in ("stale", "unbuilt") and not c.impl_lag]
            lag_c = [cid for cid, c in ev.cells.items() if c.impl_lag]
            pend_c = [cid for cid, c in ev.cells.items() if c.level == "pending" and not c.impl_lag]
            if run_c:
                rerun.append({"id": nid, "cells": run_c, "note": "rerun"})
                gpu += sum(ev.cells[c].gpu_h or 0 for c in run_c)
            if lag_c:
                rerun.append({"id": nid, "cells": lag_c, "note": "blocked: implement first"})
            if pend_c:
                rerun.append({"id": nid, "cells": pend_c, "note": "conditional"})
            count += len(run_c) + len(lag_c)
            blocked += len(lag_c)
            conditional += len(pend_c)
    last = next((e.get("impact") for e in reversed(st.store.events()) if e.get("op") == "applied" and e.get("impact")), None) or {}
    reused_cells = last.get("reused", 0)
    return {
        "tried": {"count": len(tried), "dead": dead, "runs": total_runs, "items": tried},
        "confirmed": {"count": len(confirmed), "shaky": sum(1 for i in confirmed if i.get("note")), "items": confirmed},
        "revise": {"count": len(revise), "items": revise},
        "rerun": {"count": count, "gpu_h": round(gpu, 4), "blocked": blocked, "conditional": conditional,
                  "reused_cells": int(reused_cells), "reused_gpu_h": round(float(last.get("reused_gpu_h") or 0), 4), "items": rerun},
    }


def plan(st: State, targets: list[str] | None = None, conditional: bool = False) -> dict:
    """Rerun waves: wave k holds the cells whose upstream actions have nothing left to run before wave k."""
    want = {"stale", "unbuilt"} | ({"pending"} if conditional else set())
    needing: dict[str, list[str]] = {}
    for nid, ev in st.E.items():
        if ev.action and not ev.archived and (not targets or nid in targets):
            cells = [cid for cid, c in ev.cells.items() if c.level in want]
            if cells:
                needing[nid] = cells
    depth: dict[str, int] = {}

    def d(nid: str, trail: frozenset = frozenset()) -> int:
        if nid in depth:
            return depth[nid]
        ups = [u for e in edges(st.nodes[nid], "input") if (u := ref_id(e.get("to")))]
        ups = [u for u in ups if u in needing and u not in trail]
        depth[nid] = 1 + max((d(u, trail | {nid}) for u in ups), default=-1)
        return depth[nid]

    waves: list[list[dict]] = []
    gpu = usd = 0.0
    for nid in sorted(needing, key=lambda i: (d(i), i)):
        ev, platform = st.E[nid], spec_of(st.nodes[nid]).get("platform")
        probe = st.store.env_probe(platform) if platform else None
        while len(waves) <= d(nid):
            waves.append([])
        for cid in needing[nid]:
            c = ev.cells[cid]
            waves[d(nid)].append({"node": nid, "cell": cid, "est_gpu_h": c.gpu_h, "platform": platform,
                                  "blocked": "impl_lag" if c.impl_lag else None, "title": title_of(st.nodes[nid])})
            gpu += c.gpu_h or 0
            usd += (c.gpu_h or 0) * float((probe or {}).get("usd_per_gpu_hour") or 0)
    return {"waves": waves, "gpu_h": round(gpu, 4), "usd": round(usd, 2)}


# The project's coarse stage (project.yaml `stage`) and the gates that close each one (docs/DAG.md §1).
COARSE_STAGES = ["idea", "motivation", "insight", "design", "evaluation", "writing"]
GATES_CLOSING = {"idea": ["G1"], "motivation": ["G2", "G3"], "insight": ["G4"], "design": ["G5"], "evaluation": ["G6"],
                 "writing": ["G7"]}


def stage_blockers(store, from_stage: str, to_stage: str) -> list[str]:
    """With blocking gates, the gates that must be passed before the project may move from from_stage to to_stage
    (every gate closing a stage before to_stage). Moving back, or advisory gates, never block."""
    if to_stage not in COARSE_STAGES:
        return []
    st = current(store)
    if not (st.cfg.get("gates") or {}).get("blocking"):
        return []
    start = COARSE_STAGES.index(from_stage) if from_stage in COARSE_STAGES else 0
    target = COARSE_STAGES.index(to_stage)
    if target <= start:
        return []
    needed = [g for s in COARSE_STAGES[:target] for g in GATES_CLOSING[s]]
    state = {g["gate"]: g.get("state") for g in compute(st)}
    return [g for g in needed if state.get(g) != "passed"]
