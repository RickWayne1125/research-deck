"""Evaluation (docs/DAG.md §4.5): pure — reads files and caches, writes nothing — and cached by digest.

Pass 1  action cells, topological over input edges: newest valid run per cell (verifying traces), else unbuilt /
        stale / pending / orphaned with the first run's mismatches as the why.
Pass 2  evidence of live beliefs: predicates re-checked against ACTUAL values every time (a cutoff keeps the fp, it
        cannot hide a threshold crossing); bindings and stated numbers.
Pass 3  soft edges (basis, implements, describes) and cites; for actions only a ring, cells untouched; not transitive.
Pass 4  flags: impl_lag, shaky, lock_alert, unsealed, behind_head, conflict, reused, cutoff, drift, trace_quality.
"""
from __future__ import annotations

import itertools
import re
import statistics
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .fp import MISSING, UNKNOWN, H, canon, fp_json, fp_table, glob_match, show, spec_fp
from .model import (
    DEAD,
    SOFT,
    authored_fp,
    edge_key,
    edges,
    facet_value,
    is_action,
    parse_addr,
    parse_sel,
    rank,
    ref_id,
    sel_matches,
    spec_of,
    worst,
)
from .resolve import NOPROBE, Repo, Resolver, digest
from .store import DagStore

OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b,
       "==": lambda a, b: a == b}
_DERIVE_RE = re.compile(r"^\s*(ratio|diff|sum|pct)\(\s*([\w.-]+)(?:\[([^\]]*)\])?\s*,\s*([\w.-]+)(?:\[([^\]]*)\])?\s*\)"
                        r"\s*(?:by\s+([\w.,\s-]+))?\s*$")


# ---------------------------------------------------------------- runs

def run_order(r: dict) -> tuple:
    return (r.get("recorded_at") or r.get("ended") or r.get("started") or "", r.get("id") or "")


class RunIndex:
    def __init__(self, runs: list[dict]):
        self.by_id: dict[str, dict] = {}
        self.by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.by_node: dict[str, list[dict]] = defaultdict(list)
        for r in runs:
            if not r.get("id") or not r.get("node"):
                continue
            self.by_id[r["id"]] = r
            self.by_cell[(r["node"], r.get("cell") or "_")].append(r)
            self.by_node[r["node"]].append(r)
        for lst in (*self.by_cell.values(), *self.by_node.values()):
            lst.sort(key=run_order, reverse=True)

    def all(self, node: str, cell: str) -> list[dict]:
        return self.by_cell.get((node, cell), [])

    def usable(self, node: str, cell: str) -> list[dict]:
        """Succeeded, not excluded, newest first: the only runs that take part in reuse."""
        return [r for r in self.all(node, cell) if r.get("state", "succeeded") == "succeeded" and not r.get("excluded")]


def expand_cells(n: dict) -> list[tuple[str, dict]]:
    from .fp import cell_id
    sweep = spec_of(n).get("sweep") or {}
    if not isinstance(sweep, dict) or not sweep:
        return [("_", {})]
    keys = sorted(sweep)
    cells = [dict(zip(keys, combo)) for combo in itertools.product(*(sweep[k] if isinstance(sweep[k], list) else [sweep[k]] for k in keys))]
    return sorted(((cell_id(c), c) for c in cells), key=lambda x: x[0])


def est_gpu_h(n: dict, cell: str, idx: RunIndex) -> float:
    """Median GPU-h of the cell's last 3 successful runs, else the node's median, else spec.est_hours × gpus."""
    def med(rs: list[dict], limit: int | None) -> float | None:
        vals = [float(r["gpu_hours"]) for r in rs if r.get("state", "succeeded") == "succeeded"
                and isinstance(r.get("gpu_hours"), (int, float))][:limit]
        return statistics.median(vals) if vals else None
    v = med(idx.all(n["id"], cell), 3)
    if v is None:
        v = med(idx.by_node.get(n["id"], []), None)
    if v is None:
        s = spec_of(n)
        v = float(s.get("est_hours") or 0) * float(s.get("gpus") or 1)
    return round(v, 4)


def numbers(values: list) -> list[float]:
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            out.append(v)
        elif isinstance(v, (list, tuple)):
            out.extend(numbers(list(v)))
    return out


def aggregate(values: list, agg: str | None) -> float | None:
    nums = numbers(values)
    if not nums:
        return None
    if agg == "min":
        return min(nums)
    if agg == "max":
        return max(nums)
    if len(nums) == 1:
        return nums[0]
    return statistics.fmean(nums)


def holds(pred: dict, values: list) -> bool:
    nums = numbers(values)
    if not nums:
        return False
    cmp, rhs, agg = OPS[pred["op"]], pred["rhs"], pred["agg"]
    if agg in ("all", "any"):
        res = [cmp(v, rhs) for v in nums]
        return all(res) if agg == "all" else any(res)
    return cmp(aggregate(nums, agg), rhs)


def pred_text(p: dict | None) -> str | None:
    return f"{p['agg']} {p['op']} {p['rhs']}" if p else None


def off_tol(stated: float, v: float, tol: dict) -> bool:
    if "abs" in (tol or {}):
        return abs(stated - v) > float(tol["abs"])
    return abs(stated - v) > float((tol or {}).get("rel", 0.03)) * max(abs(v), 1e-12)


# ---------------------------------------------------------------- per-node evaluation records

@dataclass
class CellE:
    level: str
    run: dict | None = None
    reused: bool = False
    cutoff: bool = False
    impl_lag: bool = False
    provisional: bool = False
    why: list[dict] = field(default_factory=list)
    gpu_h: float | None = None
    platform: str | None = None
    values: dict = field(default_factory=dict)
    selection_invalid: bool = False

    def json(self) -> dict:
        out = {"level": self.level, "run": (self.run or {}).get("id"), "reused": self.reused, "why": self.why,
               "gpu_h": self.gpu_h, "platform": self.platform}
        if self.cutoff:
            out["cutoff"] = True
        if self.impl_lag:
            out["impl_lag"] = True
        if self.provisional:
            out["provisional"] = True
        return out


class NodeE:
    def __init__(self, node: dict):
        self.node, self.id = node, node["id"]
        self.archived = node.get("status") in DEAD
        self.action = is_action(node)
        self.level: str | None = None if self.archived else "fresh"
        self.reasons: list[dict] = []
        self.flags: set[str] = set()
        self.shaky: set[str] = set()
        self.cells: dict[str, CellE] = {}
        self.cell_values: dict[str, dict] = {}
        self.tables: dict[str, dict[str, tuple[Any, Any, bool]]] = {}
        self.values: dict[str, float | None] = {}

    def add(self, level: str, *, ring: bool = False, **reason: Any) -> None:
        """Record a reason; for an action a soft-edge reason is a ring only (its level is the max over its cells)."""
        self.reasons.append({"level": level, **{k: show(v) if k in ("from", "to") else v for k, v in reason.items() if v is not None}})
        if ring and self.action:
            self.flags.add("review_ring")
        elif rank(level) > rank(self.level):
            self.level = level

    def has_reason(self, edge_type: str) -> bool:
        return any(str(r.get("edge", "")).startswith(edge_type + ":") and r["level"] != "fresh" for r in self.reasons)

    def rows(self, name: str | None, sel: str | None) -> list[tuple[str, Any, Any, bool]] | None:
        t = self.tables.get(name or "")
        if t is None:
            return None
        want = parse_sel(sel)
        return [(cid, v, fp, ok) for cid, (v, fp, ok) in sorted(t.items()) if sel_matches(want, self.cell_values.get(cid, {}))]

    def out_fp(self, name: str | None, sel: str | None) -> Any:
        rows = self.rows(name, sel)
        if not rows:
            return MISSING
        if any(fp is UNKNOWN for _, _, fp, _ in rows):
            return UNKNOWN
        return fp_table((cid, fp) for cid, _, fp, _ in rows)

    def tainted(self, name: str | None, sel: str | None) -> bool:
        rows = self.rows(name, sel)
        return bool(rows) and not all(ok for *_, ok in rows)

    def json(self) -> dict:
        out: dict[str, Any] = {"level": self.level, "archived": self.archived, "reasons": self.reasons,
                               "flags": sorted(self.flags), "shaky": sorted(self.shaky)}
        if self.action and not self.archived:
            out["cells"] = {cid: c.json() for cid, c in self.cells.items()}
        if self.values:
            out["values"] = self.values
        return out


# ---------------------------------------------------------------- pass helpers

def _toposort(actions: list[dict]) -> list[dict]:
    ids = {n["id"]: n for n in actions}
    deps = {n["id"]: {ref_id(e.get("to")) for e in edges(n, "input")} & ids.keys() for n in actions}
    out, done = [], set()
    while len(out) < len(actions):
        ready = sorted(i for i in ids if i not in done and deps[i] <= done)
        if not ready:                           # a cycle (refused on write): evaluate the rest anyway
            ready = sorted(i for i in ids if i not in done)
        for i in ready:
            done.add(i)
            out.append(ids[i])
    return out


def mismatches(run: dict, n: dict, cell: dict, sfp: str, R: Resolver, E: dict[str, NodeE]) -> list[dict]:
    """Shake-style verifying trace: every recorded fp against the current value in the cell's context."""
    mm: list[dict] = []
    if run.get("spec_fp") and run["spec_fp"] != sfp:
        mm.append({"kind": "changed", "addr": "spec", "from": run["spec_fp"], "to": sfp, "note": "spec changed"})
    trace = run.get("trace") or {}
    spec = spec_of(n)
    has_env, platform_ok = False, True
    for addr, item in trace.items():
        rec = item.get("fp") if isinstance(item, dict) else item
        if addr.startswith("node:"):
            try:
                a = parse_addr(addr)
            except ValueError:
                continue
            up = E.get(a.id)
            if up is None or up.archived:
                mm.append({"kind": "upstream_dead", "addr": addr, "from": rec, "to": None, "note": "upstream dead or missing"})
                continue
            if a.out and up.tainted(a.out, a.sel):
                mm.append({"kind": "upstream_pending", "addr": addr, "from": rec, "to": None, "note": "upstream not fresh"})
                continue
        cur = R.get(addr, n, cell)
        if cur is NOPROBE:                      # the target platform never probed this key: only the platform can differ
            has_env = True
            continue
        if addr.startswith("env:"):
            has_env = True
        if cur != rec:
            mm.append({"kind": "changed", "addr": addr, "from": rec, "to": show(cur)})
    target, ran_on = spec.get("platform"), run.get("platform")
    if target and ran_on and target != ran_on and (not has_env or R.store is None or R.store.env_probe(target) is None):
        platform_ok = False
    if not platform_ok:
        mm.append({"kind": "changed", "addr": "env:platform", "from": fp_json(ran_on), "to": fp_json(target),
                   "note": f"ran on {ran_on}, target {target}"})
    for e in edges(n, "input"):                 # inputs added after the run
        if e["to"] in trace:
            continue
        a = parse_addr(e["to"])
        up = E.get(a.id)
        if up is None or up.archived:
            mm.append({"kind": "upstream_dead", "addr": e["to"], "from": None, "to": None, "note": "upstream dead or missing"})
        elif a.out and up.tainted(a.out, a.sel):
            mm.append({"kind": "upstream_pending", "addr": e["to"], "from": None, "to": None, "note": "upstream not fresh"})
        else:
            mm.append({"kind": "changed", "addr": e["to"], "from": None, "to": show(R.get(e["to"], n, cell)), "note": "input added"})
    return mm


def _derive(expr: str, tables: dict, cell_values: dict) -> dict:
    """`ratio|diff|sum|pct(A[sel], B[sel]) [by k,…]`: one value per cell of the operand without a selector (B when
    both or neither have one), the other operand matched on the `by` keys (default: every key it does not select).
    The fp comes from the operands' ANCHOR fps, so a cutoff carries through; the value from the actual numbers."""
    m = _DERIVE_RE.match(expr or "")
    if not m:
        return {}
    fn, an, asel, bn, bsel, by = m.groups()
    sides = {"a": (tables.get(an) or {}, parse_sel(asel)), "b": (tables.get(bn) or {}, parse_sel(bsel))}
    lead = "a" if not sides["a"][1] and sides["b"][1] else "b"
    other = "b" if lead == "a" else "a"
    (L, lsel), (O, osel) = sides[lead], sides[other]
    keys_by = [k.strip() for k in by.split(",") if k.strip()] if by else None
    out = {}
    for cid, row in L.items():
        vals = cell_values.get(cid, {})
        if not sel_matches(lsel, vals):
            continue
        keys = keys_by or [k for k in vals if k not in osel]
        hits = [oid for oid in O if sel_matches(osel, cell_values.get(oid, {}))
                and all(str(cell_values[oid].get(k)) == str(vals.get(k)) for k in keys)]
        if len(hits) != 1:
            out[cid] = (None, MISSING, False)
            continue
        (av, afp, aok), (bv, bfp, bok) = (row, O[hits[0]]) if lead == "a" else (O[hits[0]], row)
        value = None
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            value = (av / bv if bv else None) if fn == "ratio" else av - bv if fn == "diff" else av + bv if fn == "sum" \
                else ((av - bv) / bv * 100 if bv else None)
        fp = UNKNOWN if UNKNOWN in (afp, bfp) else H("s", canon([fn, show(afp), show(bfp)]))
        out[cid] = (value, fp, aok and bok)
    return out


def _build_tables(ev: NodeE) -> None:
    outs = facet_value(ev.node, "outputs") or {}
    names = {k for k, v in outs.items() if not (isinstance(v, dict) and v.get("derive"))}
    for c in ev.cells.values():
        names |= set(((c.run or {}).get("outputs") or {}).keys())
    for name in names:
        t = {}
        for cid, c in ev.cells.items():
            o = ((c.run or {}).get("outputs") or {}).get(name)
            ok = c.level == "fresh"
            t[cid] = (o.get("value"), o.get("fp", MISSING), ok) if isinstance(o, dict) else (None, MISSING, ok and c.run is not None)
        ev.tables[name] = t
    for name, spec in outs.items():
        if isinstance(spec, dict) and spec.get("derive"):
            ev.tables[name] = _derive(spec["derive"], ev.tables, ev.cell_values)


def addr_values(addr: str, E: dict[str, NodeE], runs: RunIndex) -> tuple[list, bool]:
    """Actual values behind an evidence/binding address, and whether they are provisional."""
    try:
        a = parse_addr(addr)
    except ValueError:
        return [], True
    if a.scheme == "run":
        o = ((runs.by_id.get(a.id) or {}).get("outputs") or {}).get(a.out or "")
        return ([o.get("value")] if isinstance(o, dict) else []), False
    ev = E.get(a.id)
    rows = ev.rows(a.out, a.sel) if ev and a.out else None
    if not rows:
        return [], True
    return [v for _, v, _, _ in rows], not all(ok for *_, ok in rows)


def _seen_value(R: Resolver, addr: str, seen: str | None) -> Any:
    """The upstream facet value that had fingerprint `seen` (from its history), for review diffs."""
    a = parse_addr(addr)
    if not a.facet or not seen or not R.store:
        return None
    for v in reversed(R.store.history(a.id)):
        f = (v.get("facets") or {}).get(a.facet)
        if isinstance(f, dict) and f.get("type") in ("prose", "text", "json") and fp_json(f.get("value"), f["type"]) == seen:
            return f.get("value")
    return None


def facet_diff(R: Resolver, nodes: dict, addr: str, seen: str | None) -> str | None:
    a = parse_addr(addr)
    up = nodes.get(a.id) or {}
    f = (up.get("facets") or {}).get(a.facet or "") or {}
    if f.get("type") not in ("prose", "text", "json"):
        return None
    old = _seen_value(R, addr, seen)
    clip = lambda v: (s if len(s := str(v)) <= 80 else s[:79] + "…")   # noqa: E731
    return f"{clip(old) if old is not None else '?'} → {clip(f.get('value'))}"


# ---------------------------------------------------------------- the evaluation

def evaluate(nodes: dict[str, dict], runs: RunIndex, R: Resolver, cfg: dict, store: DagStore | None = None) -> dict[str, NodeE]:
    E = {i: NodeE(n) for i, n in nodes.items()}
    R.E = E
    R.runs_by_id = runs.by_id

    # Pass 1 — action cells, topological over input edges
    for n in _toposort([n for n in nodes.values() if is_action(n)]):
        ev = E[n["id"]]
        if ev.archived:
            continue
        sfp, spec = spec_fp(spec_of(n)), spec_of(n)
        for cid, cv in expand_cells(n):
            ev.cell_values[cid] = cv
            usable = runs.usable(n["id"], cid)
            sel_id = (n.get("selected") or {}).get(cid)
            chosen = next((r for r in usable if r["id"] == sel_id), None) if sel_id else None
            order = [chosen, *(r for r in usable if r is not chosen)] if chosen else usable
            hit, first = None, None
            for r in order:
                mm = mismatches(r, n, cv, sfp, R, E)
                if not mm:
                    hit = r
                    break
                first = first or (r, mm)
            gpu, platform = est_gpu_h(n, cid, runs), spec.get("platform")
            if hit:
                c = CellE("fresh", hit, reused=hit is not usable[0], gpu_h=gpu, platform=platform or hit.get("platform"),
                          cutoff=any(isinstance(o, dict) and o.get("cutoff") for o in (hit.get("outputs") or {}).values()),
                          selection_invalid=bool(sel_id) and hit is not chosen)
            elif not usable:
                others = Counter("excluded" if r.get("excluded") else r.get("state", "succeeded") for r in runs.all(n["id"], cid))
                runs_note = ", ".join(f"{k} {s}" for s, k in sorted(others.items()))       # e.g. "1 failed, 1 running"
                c = CellE("unbuilt", gpu_h=gpu, platform=platform,
                          why=[{"level": "unbuilt", "note": "no succeeded run" + (f" ({runs_note})" if others else "")}])
            else:
                r, mm = first
                kinds = {m["kind"] for m in mm}
                lvl = "orphaned" if "upstream_dead" in kinds else "pending" if kinds == {"upstream_pending"} else "stale"
                c = CellE(lvl, r, provisional=True, gpu_h=gpu, platform=platform or r.get("platform"),
                          why=[{"level": lvl, **{k: v for k, v in m.items() if k != "kind" and v is not None}} for m in mm])
            if c.selection_invalid:
                c.why.append({"level": "fresh", "note": f"selected run {sel_id} no longer valid; using {hit['id']}"})
            ev.cells[cid] = c
        _build_tables(ev)
        ev.level = worst(c.level for c in ev.cells.values()) if ev.cells else "fresh"

    # Pass 2 — evidence of live beliefs (beliefs are sinks of the hard graph: any order)
    default_tol = (cfg.get("outputs") or {}).get("default_tol") or {"rel": 0.03}
    for n in nodes.values():
        ev = E[n["id"]]
        if ev.archived or ev.action:
            continue
        for e in edges(n, "evidence"):
            k, pred, kill = edge_key(e), e.get("predicate"), e.get("kill_if")
            try:
                a = parse_addr(e["to"])
            except ValueError:
                ev.add("orphaned", edge=k, note="bad address")
                continue
            if a.scheme == "run":                   # frozen: never changes; still checked against its values
                run = runs.by_id.get(a.id)
                if run is None:
                    ev.add("orphaned", edge=k, addr=e["to"], note="evidence run missing")
                    continue
                if run.get("excluded"):
                    ev.add("review", edge=k, addr=e["to"], note="evidence run excluded")
                vals, provisional, cur = addr_values(e["to"], E, runs)[0], False, None
            else:
                up = E.get(a.id)
                if up is None or up.archived:
                    ev.add("orphaned", edge=k, addr=e["to"], note="upstream " + ("missing" if up is None else up.node.get("status")))
                    continue
                rows = up.rows(a.out, a.sel)
                if not rows:
                    ev.add("orphaned", edge=k, addr=e["to"], note="no such output or cell")
                    continue
                vals = [v for _, v, _, _ in rows]
                provisional = not all(ok for *_, ok in rows)
                cur = None if provisional else up.out_fp(a.out, a.sel)
            shown = aggregate(vals, (pred or kill or {}).get("agg"))
            ev.values[k] = shown
            if provisional:
                ev.add("pending", edge=k, addr=e["to"], value=shown, note="upstream not fresh")
                continue
            if pred or kill:                        # checked EVERY time: a cutoff cannot hide a crossing
                ok = holds(pred, vals) if pred else not holds(kill, vals)
                if not ok:
                    ev.add("broken", edge=k, addr=e["to"], value=shown,
                           note=f"{pred_text(pred)} fails" if pred else f"kill_if {pred_text(kill)} met")
                elif a.scheme == "node" and cur != e.get("seen"):
                    ev.flags.add("drift")
                    ev.reasons.append({"level": "fresh", "edge": k, "from": e.get("seen"), "to": show(cur), "value": shown, "note": "drift"})
            elif a.scheme == "node" and cur != e.get("seen"):
                ev.add("review", edge=k, addr=e["to"], **{"from": e.get("seen"), "to": cur}, value=shown, note="evidence moved")
        for name, b in (facet_value(n, "bindings") or {}).items():
            if not isinstance(b, dict) or not b.get("from"):
                continue
            vals, _ = addr_values(b["from"], E, runs)
            v = aggregate(vals, b.get("agg"))
            ev.values[name] = v
            stated = b.get("stated")
            if isinstance(stated, (int, float)) and v is not None and off_tol(float(stated), v, b.get("tol") or default_tol):
                ev.add("review", addr=b["from"], value=v, note=f"text says {stated}, evidence {round(v, 4)}")

    # Pass 3 — soft edges and dead upstreams (actions: ring only); cites
    for n in nodes.values():
        ev = E[n["id"]]
        if ev.archived:
            continue
        for e in edges(n, *SOFT):
            k = edge_key(e)
            try:
                a = parse_addr(e["to"])
            except ValueError:
                continue
            up = nodes.get(a.id)
            if up is None or up.get("status") in DEAD:
                ev.add("orphaned", ring=True, edge=k, addr=e["to"], note="upstream " + ((up or {}).get("status") or "missing"))
                continue
            cur = R.node_fp(e["to"], pin=e.get("pin"))
            if cur != e.get("seen"):
                ev.add("review", ring=True, edge=k, addr=e["to"], **{"from": e.get("seen"), "to": cur},
                       note=facet_diff(R, nodes, e["to"], e.get("seen")) if cur is not UNKNOWN else "predicted")
            elif E[a.id].level == "broken":
                ev.add("review", ring=True, edge=k, addr=e["to"], note="upstream broken")
        for e in edges(n, "cites"):
            up = nodes.get(ref_id(e.get("to")) or "")
            if up is not None and up.get("status") in DEAD:
                ev.add("review", ring=True, edge=edge_key(e), addr=e["to"], note="cited reference retracted")

    # Pass 4 — flags (never change levels)
    lagging = [m for m in nodes.values() if m.get("kind") == "module" and E[m["id"]].has_reason("implements")]
    lag_globs = [g for m in lagging for g in (facet_value(m, "globs") or [])]
    heads = {i: (n.get("head") or {}).get("vid") for i, n in nodes.items()}
    forks = _forks(store) if store else set()
    for n in nodes.values():
        ev = E[n["id"]]
        if ev.action and not ev.archived:
            for c in ev.cells.values():
                code = [a[5:] for a in ((c.run or {}).get("trace") or {}) if a.startswith("code:")]
                c.impl_lag = bool(c.run) and any(glob_match(p, g) for p in code for g in lag_globs)
                if c.impl_lag:
                    ev.flags.add("impl_lag")
                if c.reused:
                    ev.flags.add("reused")
                if c.cutoff:
                    ev.flags.add("cutoff")
                if c.run and (c.run.get("trace_quality") or "traced") != "traced":
                    ev.flags.add("trace_quality")
        if n.get("status") == "locked" and rank(ev.level) > rank("fresh"):
            ev.flags.add("lock_alert")
        if (n.get("head") or {}).get("fp") and authored_fp(n) != n["head"]["fp"]:
            ev.flags.add("unsealed")
        if any(e.get("pin") and e["pin"] != heads.get(ref_id(e.get("to"))) for e in edges(n) if ref_id(e.get("to"))):
            ev.flags.add("behind_head")
        if n["id"] in forks:
            ev.flags.add("conflict")
    dependents: dict[str, set[str]] = defaultdict(set)
    for n in nodes.values():
        for e in edges(n, *SOFT, "evidence"):
            if (up_id := ref_id(e.get("to"))):
                dependents[up_id].add(n["id"])
    for root in (i for i, ev in E.items() if not ev.archived and (rank(ev.level) >= rank("review") or "review_ring" in ev.flags)):
        stack, seen = [root], {root}
        while stack:
            for d in dependents.get(stack.pop(), ()):
                if d not in seen:
                    seen.add(d)
                    stack.append(d)
                    if not E[d].archived:
                        E[d].shaky.add(root)
    for ev in E.values():
        ev.shaky.discard(ev.id)
        if ev.shaky:
            ev.flags.add("shaky")
    return E


def _forks(store: DagStore) -> set[str]:
    """Nodes whose history has two versions sharing a parent (a fork after a merge)."""
    out = set()
    for nid in store.history_ids():
        parents = [v.get("parent") for v in store.history(nid) if v.get("parent")]
        if len(parents) != len(set(parents)):
            out.add(nid)
    return out


# ---------------------------------------------------------------- cached state

@dataclass
class State:
    store: DagStore
    repo: Repo
    cfg: dict
    nodes: dict[str, dict]
    runs: RunIndex
    R: Resolver
    E: dict[str, NodeE]
    digest: str
    sig: tuple = ()

    def eval_json(self) -> dict[str, dict]:
        return {i: ev.json() for i, ev in self.E.items()}


_CACHE: dict[str, State] = {}
_CACHE_LOCK = threading.Lock()


def build(store: DagStore, *, nodes: dict | None = None, repo: Repo | None = None, files: dict | None = None,
          predicted: dict | None = None, runs: RunIndex | None = None) -> State:
    """An uncached evaluation, optionally over an overlay graph / file patch / predicted fps (impact previews)."""
    repo = repo or Repo(store.root, store.dir / ".cache" if store.exists and not store.readonly else None)
    cfg = store.config()
    nodes = store.nodes() if nodes is None else nodes
    runs = runs or RunIndex(store.runs())
    R = Resolver(repo, nodes, cfg, store, files=files, predicted=predicted, runs_by_id=runs.by_id)
    E = evaluate(nodes, runs, R, cfg, store)
    return State(store, repo, cfg, nodes, runs, R, E, digest="")


def current(store: DagStore) -> State:
    """The evaluation of the DAG as it is now, cached by (DAG files, code state, env probes) — `base_digest`."""
    key = f"{store.root}|{store.at or ''}"
    repo = Repo(store.root, store.dir / ".cache" if store.exists and not store.readonly else None)
    sig = store.signature()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    nodes = hit.nodes if hit and hit.sig == sig else store.nodes()
    d = digest(store, repo, nodes)
    if hit and hit.digest == d:
        return hit
    st = build(store, nodes=nodes, repo=repo)
    st.digest, st.sig = d, sig
    with _CACHE_LOCK:
        _CACHE[key] = st
    return st


def invalidate(store: DagStore) -> None:
    with _CACHE_LOCK:
        _CACHE.pop(f"{store.root}|{store.at or ''}", None)


def check_run(st: State, run: dict) -> list[dict]:
    """Mismatches of one run against the current state (empty = valid)."""
    n = st.nodes.get(run.get("node", ""))
    if not n:
        return [{"kind": "upstream_dead", "addr": f"node:{run.get('node')}", "note": "node missing"}]
    from .fp import parse_cell
    return mismatches(run, n, parse_cell(run.get("cell") or "_"), spec_fp(spec_of(n)), st.R, st.E)

