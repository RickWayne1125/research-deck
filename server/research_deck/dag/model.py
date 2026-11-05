"""Node kinds, addresses, the status transition table and the agent permission matrix (docs/DAG.md §2).

Nodes stay plain dicts (the YAML shape of §6, the JSON shape of web/src/dag-types.ts); this module validates them.
"""
from __future__ import annotations

import re
from typing import Any, NamedTuple

from .fp import fmt_value, fp_json

KIND_PREFIX = {
    "problem": "prob", "reference": "ref", "dataset": "data", "experiment": "exp", "finding": "find", "gap": "gap",
    "solution": "sol", "decision": "dec", "design": "design", "module": "mod", "figure": "fig", "claim": "claim",
    "section": "sec",
}
KIND_STAGE = {"problem": "S0", "reference": "S1", "dataset": "S1", "finding": "S2", "gap": "S3", "solution": "S4",
              "decision": "S4", "design": "S5", "module": "S5", "claim": "S4", "section": "W", "figure": "S6"}
PURPOSE_STAGE = {"reproduce": "S1", "profile": "S2", "analysis": "S2", "oracle": "S3", "validate": "S4", "microbench": "S5",
                 "eval": "S6", "ablation": "S6", "sensitivity": "S6", "overhead": "S6"}
STAGES = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "W")
STATUSES = ("proposed", "active", "confirmed", "locked", "refuted", "abandoned", "superseded")
DEAD = {"refuted", "abandoned", "superseded"}
LIVE_EDITABLE = {"proposed", "active"}
EDGE_TYPES = ("input", "evidence", "basis", "implements", "describes", "cites")
SOFT = {"basis", "implements", "describes"}
FACET_TYPES = {"prose", "text", "json", "bound", "artifact", "derived"}
ABANDON_REASONS = {"infeasible", "dominated", "no_headroom", "competitor_closed_gap", "out_of_scope", "cost", "time", "other"}
LEVEL = {"fresh": 0, "review": 1, "orphaned": 2, "pending": 3, "unbuilt": 4, "stale": 4, "broken": 5}
PRED_AGG = {"min", "max", "mean", "all", "any"}
PRED_OP = {">=", "<=", ">", "<", "=="}

ID_RE = re.compile(r"^(" + "|".join(sorted(set(KIND_PREFIX.values()))) + r")\.[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
SCHEMES = ("node", "run", "code", "dir", "cfg", "data", "env")
_LOC_RE = re.compile(r"^([^#\[]+?)(?:#([^\[]+))?(?:\[(.*)\])?$")


def rank(level: str | None) -> tuple[int, int]:
    """Total order on levels; stale outranks unbuilt at the same numeric level."""
    if level is None:
        return (-1, 0)
    return (LEVEL[level], 1 if level == "stale" else 0)


def worst(levels) -> str:
    return max(levels, key=rank, default="fresh")


# ---------------------------------------------------------------- addresses

class Addr(NamedTuple):
    scheme: str
    id: str                   # node id, run id, repo path, dotted key, dataset id or env key
    facet: str | None = None  # "out.ttft_p99", "preemption"
    sel: str | None = None    # "system=ours,rate=8"

    @property
    def out(self) -> str | None:
        return self.facet[4:] if self.facet and self.facet.startswith("out.") else None

    def __str__(self) -> str:
        s = f"{self.scheme}:{self.id}"
        if self.facet:
            s += f"#{self.facet}"
        if self.sel:
            s += f"[{self.sel}]"
        return s


def parse_addr(s: str) -> Addr:
    scheme, sep, rest = (s or "").partition(":")
    if not sep or not rest or scheme not in SCHEMES:
        raise ValueError(f"not an address: {s!r}")
    if scheme not in ("node", "run"):      # trace addresses: everything after the scheme is the locator
        return Addr(scheme, rest)
    m = _LOC_RE.match(rest)
    if not m:
        raise ValueError(f"not an address: {s!r}")
    return Addr(scheme, *m.groups())


def ref_id(to: Any) -> str | None:
    """The node id behind a node: address, or None (never raises: hand-edited YAML must not break an evaluation)."""
    if not isinstance(to, str) or not to.startswith("node:"):
        return None
    try:
        return parse_addr(to).id
    except ValueError:
        return None


def parse_sel(sel: str | None) -> dict[str, str]:
    out = {}
    for part in (sel or "").split(","):
        if part.strip():
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
    return out


def sel_matches(sel: dict[str, str], values: dict) -> bool:
    return all(k in values and fmt_value(values[k]) == v for k, v in sel.items() if v != "*")


def edge_key(e: dict) -> str:
    return f"{e.get('type')}:{e.get('to')}"


# ---------------------------------------------------------------- node helpers

def facet_value(node: dict, name: str, default: Any = None) -> Any:
    f = (node.get("facets") or {}).get(name)
    if not isinstance(f, dict):
        return default
    return f.get("value", default)


def is_action(node: dict) -> bool:
    """Experiments, and figures that are scripted (they have a spec); drawn figures are beliefs."""
    return node.get("kind") == "experiment" or (node.get("kind") == "figure" and "spec" in (node.get("facets") or {}))


def spec_of(node: dict) -> dict:
    s = facet_value(node, "spec") or {}
    return s if isinstance(s, dict) else {}


def edges(node: dict, *types: str) -> list[dict]:
    es = [e for e in node.get("edges") or [] if isinstance(e, dict)]
    return [e for e in es if e.get("type") in types] if types else es


def title_of(node: dict) -> str:
    t = node.get("title") or {}
    return (t.get("en") or t.get("zh") or node.get("id", "")) if isinstance(t, dict) else str(t)


def normalize_facet(value: Any, existing: dict | None = None) -> dict:
    """A facet from an op: an explicit {type, value|bind}, or a bare value (keeps the existing type; str → prose)."""
    if isinstance(value, dict) and value.get("type") in FACET_TYPES:
        return {k: v for k, v in value.items() if k in ("type", "value", "bind", "path")}
    t = (existing or {}).get("type")
    if t == "bound":
        return {"type": "bound", "bind": value["bind"] if isinstance(value, dict) else str(value)}
    if t in (None, "derived"):
        t = "prose" if isinstance(value, str) else "json"
    return {"type": t, "value": value}


def facet_authored_fp(f: dict) -> str:
    """What the author wrote (bound → its bind, not the config value): head.fp, history and rollback identity."""
    t = f.get("type")
    if t in ("prose", "text", "json"):
        return fp_json(f.get("value"), t)
    if t == "bound":
        return fp_json({"bind": f.get("bind")})
    if t == "artifact":
        return fp_json({"artifact": f.get("value") or f.get("path")})
    return fp_json({"derived": True})


def authored_fp(node: dict) -> str:
    """fp_node over authored facets; status, title and notes never count."""
    return fp_json(sorted((k, facet_authored_fp(f)) for k, f in (node.get("facets") or {}).items() if isinstance(f, dict)))


# ---------------------------------------------------------------- validation

def validate_node(n: dict) -> list[str]:
    errs: list[str] = []
    nid, kind = n.get("id"), n.get("kind")
    if not isinstance(nid, str) or not ID_RE.match(nid):
        errs.append(f"bad id {nid!r}: use <prefix>.<slug> with a prefix in {sorted(set(KIND_PREFIX.values()))}")
    if kind not in KIND_PREFIX:
        errs.append(f"unknown kind {kind!r}")
    elif isinstance(nid, str) and not nid.startswith(KIND_PREFIX[kind] + "."):
        errs.append(f"{kind} ids start with {KIND_PREFIX[kind]}.")
    if n.get("stage") not in STAGES:
        errs.append(f"bad stage {n.get('stage')!r}")
    if n.get("status") not in STATUSES:
        errs.append(f"bad status {n.get('status')!r}")
    for name, f in (n.get("facets") or {}).items():
        if not isinstance(f, dict) or f.get("type") not in FACET_TYPES:
            errs.append(f"facet {name}: needs a type in {sorted(FACET_TYPES)}")
        elif f["type"] == "bound" and "#" not in str(f.get("bind") or ""):
            errs.append(f"facet {name}: bound facets need bind: 'file#dotted.key'")
    action = is_action(n)
    seen_keys = set()
    for e in n.get("edges") or []:
        if not isinstance(e, dict) or e.get("type") not in EDGE_TYPES:
            errs.append(f"bad edge {e!r}")
            continue
        try:
            a = parse_addr(e.get("to", ""))
        except ValueError as ex:
            errs.append(str(ex))
            continue
        k = edge_key(e)
        if k in seen_keys:
            errs.append(f"duplicate edge {k}")
        seen_keys.add(k)
        t = e["type"]
        if t == "input" and not action:
            errs.append(f"{k}: only actions have input edges")
        if t == "input" and not (a.scheme == "node" and (a.out or a.id.startswith("data."))):
            errs.append(f"{k}: input edges point at an action output or a dataset")
        if t == "evidence" and not (a.scheme == "run" or a.out):
            errs.append(f"{k}: evidence points at node:<action>#out.<name> or run:<id>#out.<name>")
        if t != "evidence" and a.scheme != "node":
            errs.append(f"{k}: {t} edges point at node: addresses")
        for p in ("predicate", "kill_if"):
            if e.get(p) is not None:
                pr = e[p]
                if not (isinstance(pr, dict) and pr.get("agg") in PRED_AGG and pr.get("op") in PRED_OP
                        and isinstance(pr.get("rhs"), (int, float))):
                    errs.append(f"{k}: {p} must be {{agg, op, rhs}}")
    if action:
        sweep = spec_of(n).get("sweep") or {}
        if not isinstance(sweep, dict) or not all(isinstance(v, list) and v for v in sweep.values()):
            errs.append("spec.sweep must map keys to non-empty lists")
    return errs


def warnings_for(n: dict, nodes: dict) -> list[str]:
    out = []
    for e in edges(n, "implements"):
        try:
            a = parse_addr(e.get("to", ""))
        except ValueError:
            continue
        up = nodes.get(a.id)
        if up and ((up.get("facets") or {}).get(a.facet or "") or {}).get("type") == "bound":
            out.append(f"{n['id']}: implements points at bound facet {e['to']} (knobs are realized by config)")
    if n.get("kind") == "claim":
        text = str(facet_value(n, "text") or "")
        if re.search(r"(?<![{\w.])\d+(?:\.\d+)?\s*(?:x|×|%)", re.sub(r"\{\{[^}]*\}\}", "", text)):
            out.append(f"{n['id']}: raw number in claim text outside {{{{…}}}}")
    return out


def input_cycle(nodes: dict, types: tuple[str, ...] = ("input",)) -> list[str] | None:
    """A cycle over edges of these types (input: enforced on write; basis among beliefs: a `dag check` sanity check)."""
    graph = {i: [r for e in edges(n, *types) if (r := ref_id(e.get("to")))] for i, n in nodes.items()}
    color: dict[str, int] = {}
    stack: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = 1
        stack.append(u)
        for v in graph.get(u, ()):
            if color.get(v) == 1:
                return stack[stack.index(v):] + [v]
            if v in graph and not color.get(v):
                found = dfs(v)
                if found:
                    return found
        stack.pop()
        color[u] = 2
        return None

    for u in graph:
        if not color.get(u):
            found = dfs(u)
            if found:
                return found
    return None


# ---------------------------------------------------------------- permissions (§2.7)

HUMAN_ONLY = {"lock", "select_run", "exclude_run"}            # agents: 403 "open a proposal"
PROPOSAL_ONLY = {"unlock", "restore_snapshot"}                 # agents: always a proposal
PREVIEW_ONLY = {"touch_code", "code"}


def agent_mode(op: dict, nodes: dict, actor: str, bound_nodes: list[dict] | None = None) -> tuple[str, str]:
    """('direct' | 'proposal' | 'never', why) for an agent's op. Humans are checked by the reducers themselves."""
    kind = op.get("op")
    if kind in HUMAN_ONLY:
        return "never", f"{kind} is human-only"
    if kind in PROPOSAL_ONLY:
        return "proposal", f"{kind} needs a human"
    node = nodes.get(op["node"]) if isinstance(op.get("node"), str) else None
    status = (node or {}).get("status")
    own = bool(node) and (node.get("created") or {}).get("by") == actor
    if kind == "create":
        st = (op.get("node") or {}).get("status", "proposed") if isinstance(op.get("node"), dict) else "proposed"
        return ("direct", "") if st == "proposed" else ("proposal", "agents create proposed nodes")
    if node is None:
        return "direct", ""      # the reducer reports the missing node
    if kind in ("edit", "link", "unlink", "attest", "rollback"):
        if kind == "edit" and op.get("editorial"):    # auto-attest of dependents follows the attest rule
            frozen = [m["id"] for m in nodes.values() if m.get("status") not in LIVE_EDITABLE and any(
                e.get("type") in SOFT and str(e.get("to", "")).split("#")[0] == f"node:{node['id']}" for e in m.get("edges") or [])]
            if frozen:
                return "proposal", f"editorial edit re-attests {', '.join(sorted(frozen))}"
        if status in LIVE_EDITABLE:
            return "direct", ""
        return "proposal", f"{kind} of {status} {node['id']}"
    if kind == "config_edit":
        frozen = [n["id"] for n in bound_nodes or [] if n.get("status") not in LIVE_EDITABLE]
        return ("proposal", f"key bound by {', '.join(frozen)}") if frozen else ("direct", "")
    if kind == "set_status":
        to = op.get("to")
        if status == "proposed" and to == "active":
            return "direct", ""
        if status == "proposed" and to in ("refuted", "abandoned") and own:
            return "direct", ""
        return "proposal", f"{status} → {to} of {node['id']}"
    if kind == "delete":
        return ("direct", "") if status == "proposed" and own else ("proposal", f"delete of {node['id']}")
    return "proposal", f"unknown op {kind}"


TRANSITIONS = {
    "proposed": {"active", "refuted", "abandoned", "superseded"},
    "active": {"confirmed", "refuted", "abandoned", "superseded"},
    "confirmed": {"active", "abandoned", "superseded"},          # → locked only through the lock op
    "locked": set(),                                             # → confirmed only through unlock
    "refuted": {"active"}, "abandoned": {"active"}, "superseded": {"active"},
}
