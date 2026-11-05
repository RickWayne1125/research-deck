"""The op engine (docs/DAG.md §2.7, §3): every mutation — human, Codex, Claude or system — is a list of ops applied
atomically by these reducers. Impact previews run the same reducers on a copy (`Txn(dry=True)`).

Permissions: humans may do everything the transition table allows (a locked node answers 409 until unlocked);
agents act directly only when the whole batch is "safe" (§2.7), otherwise the batch becomes one proposal; human-only ops
from an agent are refused with 403 {"message": "open a proposal"}.
"""
from __future__ import annotations

import copy
import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from ..actors import is_human
from ..util import now_iso, safe_join, write_text_atomic
from . import stages
from .evaluate import RunIndex, State, build, check_run, current, invalidate
from .fp import cell_id, fp_json, parse_cell, quantize, show, spec_fp
from .model import (
    ABANDON_REASONS,
    DEAD,
    KIND_STAGE,
    PREVIEW_ONLY,
    PURPOSE_STAGE,
    SOFT,
    TRANSITIONS,
    agent_mode,
    authored_fp,
    edge_key,
    edges,
    facet_value,
    input_cycle,
    is_action,
    normalize_facet,
    parse_addr,
    ref_id,
    spec_of,
    validate_node,
)
from .resolve import Resolver, check_rev, git_text, yaml_set_text
from .store import DagStore, safe_name


class OpError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.message = status, message
        self.payload = {"message": message, **extra}


def is_privileged(actor: str) -> bool:
    return is_human(actor) or actor == "system" or actor.startswith("system:")


def short_head(root) -> str | None:
    out = git_text(root, "rev-parse", "--short=7", "HEAD")
    return out.strip() if out else None


def bound_nodes(nodes: dict, path: str, key: str) -> list[dict]:
    """Nodes with a bound facet on this config file whose key overlaps `key` (same leaf, a parent or a child)."""
    out = []
    for n in nodes.values():
        for f in (n.get("facets") or {}).values():
            if isinstance(f, dict) and f.get("type") == "bound":
                bpath, _, bkey = str(f.get("bind")).partition("#")
                if bpath == path and (bkey == key or key.startswith(bkey + ".") or bkey.startswith(key + ".") or not bkey):
                    out.append(n)
                    break
    return out


class Txn:
    """One atomic batch over a copy of the graph. commit() writes heads, history lines, files, runs and events."""

    def __init__(self, store: DagStore, actor: str, *, state: State | None = None, dry: bool = False,
                 via: str | None = None, proposer: str | None = None):
        self.store, self.actor, self.dry, self.via, self.proposer = store, actor, dry, via, proposer
        self.state = state or current(store)
        self.nodes: dict[str, dict] = copy.deepcopy(self.state.nodes)
        self.touched: dict[str, list[str]] = {}       # id -> op names (one history line per node per batch)
        self.reverts: dict[str, str] = {}
        self.unlocked: dict[str, dict] = {}
        self.dirty: set[str] = set()                   # node YAML changed without a new version (selected runs)
        self.deleted: set[str] = set()
        self.files: dict[str, bytes] = {}              # config edits: path -> new content
        self.run_writes: dict[str, dict] = {}
        self.events: list[dict] = []
        self.lock_hits: list[dict] = []
        self.edited: list[tuple[str, str, str]] = []   # (node, facet, op): edits drive the predicted code impact
        self.tags: list[tuple[str, str]] = []
        self._eval: tuple[int, State] | None = None
        self._version = 0

    # helpers ---------------------------------------------------------------
    def node(self, nid: Any) -> dict:
        n = self.nodes.get(nid) if isinstance(nid, str) else None
        if n is None:
            raise OpError(404, f"unknown node: {nid}")
        return n

    def touch(self, nid: str, op: str) -> None:
        self.touched.setdefault(nid, [])
        if op not in self.touched[nid]:
            self.touched[nid].append(op)
        self._version += 1

    def event(self, **ev: Any) -> None:
        self.events.append({"by": self.actor, **({"via": self.via} if self.via else {}), **ev})

    def evaluation(self) -> State:
        """An evaluation over the batch so far (preconditions such as 'fresh' see the earlier ops)."""
        if self._eval is None or self._eval[0] != self._version:
            if not self._version and not self.files and not self.run_writes:
                st = self.state
            else:
                st = build(self.store, nodes=self.nodes, repo=self.state.repo, files=self.files or None, runs=self.runs())
            self._eval = (self._version, st)
        return self._eval[1]

    def runs(self) -> RunIndex:
        if not self.run_writes:
            return self.state.runs
        return RunIndex([self.run_writes.get(r["id"], r) for r in self.state.runs.by_id.values()])

    def current_fp(self, e: dict) -> Any:
        """What `seen` should become for this edge now: facet fp for soft edges, output table fp for evidence."""
        a = parse_addr(e["to"])
        if a.out:
            ev = self.evaluation().E.get(a.id)
            return ev.out_fp(a.out, a.sel) if ev else None
        st = self.evaluation()
        R = Resolver(st.repo, self.nodes, st.cfg, self.store, files=self.files or None, runs_by_id=st.runs.by_id)
        R.E = st.E
        return R.node_fp(e["to"], pin=e.get("pin"))

    def guard_locked(self, n: dict, kind: str) -> None:
        if n.get("status") != "locked" or n["id"] in self.unlocked:
            return
        self.lock_hits.append({"node": n["id"], "kind": kind, "requires": f"unlock:{n['id']}"})
        if not self.dry:
            raise OpError(409, f"{n['id']} is locked: unlock it first", requires=[f"unlock:{n['id']}"])

    # stage-by-stage progression (stages.py) ----------------------------------
    def stage_mode(self) -> str:
        return stages.mode(self.state.cfg)

    def check_stage(self, n: dict) -> None:
        """A node may be written in its step only once the project has reached that step (strict). The outline's
        sections and items are the story, written from the start: the stage rules govern their evidence."""
        if self.stage_mode() != "strict" or n.get("kind") in stages.OUTLINE_KINDS:
            return
        step, now = stages.node_step(n), stages.project_step(self.store)
        if step > now:
            raise OpError(409, f"{n['id']}: {stages.label(step)} has not started; draft it once {stages.label(step - 1)} "
                               f"passes its checks", reason="stage_locked", step=stages.STEP_IDS[step])

    def check_parent(self, n: dict, e: dict, *, confirmed: bool) -> None:
        """A failed node grows no new branch; with `confirmed`, a parent from an earlier step must be confirmed."""
        mode = self.stage_mode()
        if mode == "free":
            return
        a = parse_addr(str(e.get("to") or ""))
        t = self.nodes.get(a.id) if a.scheme == "node" else None
        if t is None or t["id"] == n["id"]:
            return
        if t.get("status") in DEAD:
            raise OpError(409, f"{t['id']} is {t.get('status')}: a failed node grows no new branch",
                          reason="dead_parent", node=t["id"])
        if confirmed and n.get("kind") not in stages.OUTLINE_KINDS and stages.node_step(t) < stages.node_step(n) \
                and t.get("status") not in ("confirmed", "locked"):
            raise OpError(409, f"{t['id']} is not confirmed: a node of {stages.label(stages.node_step(n))} rests only on "
                               f"confirmed nodes of the steps before", reason="unconfirmed_parent", node=t["id"])

    def check_graph(self, n: dict) -> None:
        errs = validate_node(n)
        if errs:
            raise OpError(400, "; ".join(errs))
        if edges(n, "input") and (cyc := input_cycle(self.nodes)):
            raise OpError(400, "input edges would form a cycle: " + " → ".join(cyc))

    # ops ---------------------------------------------------------------------
    def apply(self, op: dict) -> None:
        kind = op.get("op") if isinstance(op, dict) else None
        if kind in PREVIEW_ONLY:
            raise OpError(400, f"{kind} is a preview-only op")
        fn = getattr(self, f"op_{kind}", None) if isinstance(kind, str) else None
        if fn is None:
            raise OpError(400, f"unknown op: {kind}")
        try:
            fn(op)
        except (KeyError, TypeError, ValueError) as e:
            raise OpError(400, f"{kind}: {e}") from e

    def op_create(self, op: dict) -> None:
        raw = op.get("node")
        if not isinstance(raw, dict):
            raise OpError(400, "create needs a node")
        n = copy.deepcopy(raw)
        nid = n.get("id")
        if nid in self.nodes:
            raise OpError(409, f"node exists: {nid}")
        status = n.get("status") or "proposed"
        if status not in ("proposed", "active"):
            raise OpError(400, "nodes are created as proposed or active")
        if status == "active" and not is_privileged(self.actor) and not self.dry:
            raise OpError(403, "open a proposal")
        if isinstance(n.get("title"), str):
            n["title"] = {"en": n["title"]}
        n.setdefault("title", {"en": nid})
        purpose = n.get("purpose") or facet_value(n, "purpose")
        n.setdefault("stage", PURPOSE_STAGE.get(purpose, "S6") if n.get("kind") == "experiment" else KIND_STAGE.get(n.get("kind"), "S0"))
        n["status"] = status
        n["facets"] = {k: normalize_facet(v) for k, v in (n.get("facets") or {}).items()}
        n["edges"] = [dict(e) for e in n.get("edges") or []]
        n.pop("head", None)
        n.pop("lock", None)
        n["created"] = {"by": self.proposer or self.actor, "at": now_iso(), **({"via": self.via} if self.via else {})}
        self.check_graph(n)
        self.check_stage(n)
        for e in n["edges"]:
            self.check_parent(n, e, confirmed=self.stage_mode() == "strict")
        self.nodes[nid] = n
        self._version += 1
        for e in n["edges"]:
            if e["type"] in SOFT | {"evidence"} and not e.get("seen") and not e["to"].startswith("run:"):
                e["seen"] = show(self.current_fp(e))
        self.check_graph(n)
        self.touch(nid, "create")
        self.event(op="create", node=nid, kind=n.get("kind"), status=status)

    def op_edit(self, op: dict) -> None:
        n = self.node(op.get("node"))
        if op.get("base_vid") and op["base_vid"] != (n.get("head") or {}).get("vid"):
            raise OpError(409, "base_vid mismatch: the node changed", head=(n.get("head") or {}).get("vid"))
        self.guard_locked(n, "edit_locked")
        facets, changed = n.setdefault("facets", {}), []
        for k, v in (op.get("set") or {}).items():
            new = normalize_facet(v, facets.get(k))
            if new != facets.get(k):
                facets[k], changed = new, changed + [k]
        for k in op.get("unset") or []:
            if facets.pop(k, None) is not None:
                changed.append(k)
        for meta in ("title", "notes", "stage", "alt_group", "purpose"):
            if meta in op:
                n[meta] = {"en": op[meta]} if meta == "title" and isinstance(op[meta], str) else op[meta]
        self.check_graph(n)
        if "stage" in op:
            self.check_stage(n)
        if changed and not op.get("editorial") and n.get("status") == "confirmed" and is_privileged(self.actor):
            n["status"] = "active"                     # a real human edit demotes confirmed → active
        self.edited += [(n["id"], k, "edit") for k in changed]
        self.touch(n["id"], "edit")
        self._version += 1
        if op.get("editorial") and changed:            # auto-attest direct soft dependents of the edited facets
            for m in self.nodes.values():
                hit = False
                for e in edges(m, *SOFT):
                    a = parse_addr(e["to"])
                    if a.id == n["id"] and (a.facet is None or a.facet in changed) and not e.get("pin"):
                        e["seen"], hit = show(self.current_fp(e)), True
                if hit:
                    self.touch(m["id"], "attest")
        self.event(op="edit", node=n["id"], facets=changed, editorial=bool(op.get("editorial")))

    def op_config_edit(self, op: dict) -> None:
        path, key = str(op["file"]), str(op["key"])
        target = safe_join(self.store.root, path)
        rel = target.relative_to(self.store.root.resolve()).as_posix()
        parts = rel.split("/")
        if rel.startswith(".research/") or any(p.startswith(".") for p in parts) or not rel.endswith((".yaml", ".yml")):
            # never .git/, .claude/, .github/ …, and never a file Python, git or a CI could execute
            raise OpError(400, "config_edit only writes YAML config files outside dot-folders")
        old = self.files.get(rel)
        if old is None:
            try:
                old = target.read_bytes()
            except FileNotFoundError:
                old = b""
        for n in bound_nodes(self.nodes, rel, key):
            self.guard_locked(n, "config_bound_locked")
        self.files[rel] = yaml_set_text(old.decode("utf-8"), key, op.get("value")).encode("utf-8")
        self._version += 1
        self.event(op="config_edit", file=rel, key=key, value=op.get("value"))

    def op_link(self, op: dict) -> None:
        n = self.node(op.get("node"))
        e = dict(op.get("edge") or {})
        self.guard_locked(n, "edit_locked")
        self.check_parent(n, e, confirmed=self.stage_mode() == "strict")
        n["edges"] = [x for x in edges(n) if edge_key(x) != edge_key(e)] + [e]
        self.check_graph(n)
        self._version += 1
        if e.get("type") in SOFT | {"evidence"} and not e.get("seen") and not str(e.get("to")).startswith("run:"):
            e["seen"] = show(self.current_fp(e))
        self.touch(n["id"], "link")
        self.event(op="link", node=n["id"], edge=edge_key(e))

    def op_unlink(self, op: dict) -> None:
        n = self.node(op.get("node"))
        key = op.get("edge") if isinstance(op.get("edge"), str) else edge_key(op.get("edge") or {})
        self.guard_locked(n, "edit_locked")
        before = len(n.get("edges") or [])
        n["edges"] = [x for x in edges(n) if edge_key(x) != key]
        if len(n["edges"]) == before:
            raise OpError(404, f"no edge {key} on {n['id']}")
        self.touch(n["id"], "unlink")
        self.event(op="unlink", node=n["id"], edge=key)

    def op_attest(self, op: dict) -> None:
        n = self.node(op.get("node"))
        if n.get("status") == "locked" and n["id"] not in self.unlocked:
            self.lock_hits.append({"node": n["id"], "kind": "attest_locked"})
        want = op.get("edges")
        done = []
        for e in edges(n, *SOFT, "evidence"):
            if (want is None or edge_key(e) in want) and not e["to"].startswith("run:"):
                e["seen"] = show(self.current_fp(e))
                done.append(edge_key(e))
        if want and set(want) - set(done):
            raise OpError(404, f"no such edges on {n['id']}: {sorted(set(want) - set(done))}")
        self.touch(n["id"], "attest")
        self._version += 1
        self.event(op="attest", node=n["id"], edges=done)

    def op_set_status(self, op: dict) -> None:
        n = self.node(op.get("node"))
        frm, to, reason = n.get("status"), op.get("to"), op.get("reason")
        if to == "locked" or frm == "locked":
            raise OpError(400, "use the lock / unlock ops")
        if to not in TRANSITIONS.get(frm, set()):
            raise OpError(409, f"{frm} → {to} is not allowed")
        revive = frm in DEAD and to == "active"
        if (to in DEAD or revive) and not reason:
            raise OpError(400, f"{'revive' if revive else to} needs a reason")
        if to in ("active", "confirmed") and self.stage_mode() != "free":
            # A node takes effect only in a step that has started, on confirmed parents from the steps before.
            step, now = stages.node_step(n), stages.project_step(self.store)
            if step > now and n.get("kind") not in stages.OUTLINE_KINDS:
                raise OpError(409, f"{n['id']} waits for {stages.label(step)} to start", reason="stage_locked",
                              step=stages.STEP_IDS[step])
            for e in edges(n):
                self.check_parent(n, e, confirmed=True)
        verdict: dict[str, Any] = {"status": to, "reason": reason, "by": self.actor, "at": now_iso()}
        if to == "confirmed":
            problems = self.confirm_problems(n)
            if problems:
                raise OpError(409, "cannot confirm: " + "; ".join(problems), problems=problems)
        elif to == "refuted":
            for addr in op.get("evidence") or []:
                if not any(e["to"] == addr for e in edges(n, "evidence")):
                    n.setdefault("edges", []).append({"type": "evidence", "to": addr, "polarity": "refutes"})
            if not edges(n, "evidence"):
                raise OpError(400, "refute needs at least one evidence edge")
            self.freeze_evidence(n)
            verdict["evidence"] = [e["to"] for e in edges(n, "evidence")]
        elif to == "abandoned":
            cat = reason if reason in ABANDON_REASONS else "other"
            verdict.update(kind=cat, note=op.get("note") or (None if cat == reason else reason))
        elif to == "superseded":
            succ = self.nodes.get(op.get("superseded_by") or "")
            if not succ or succ.get("status") in DEAD or succ["id"] == n["id"]:
                raise OpError(400, "superseded_by must name a live node")
            n["superseded_by"] = succ["id"]
        if revive:
            n.pop("superseded_by", None)
        n["status"] = to
        n["verdict"] = {k: v for k, v in verdict.items() if v is not None}
        self.touch(n["id"], "set_status")
        self._version += 1
        self.event(op="set_status", node=n["id"], **{"from": frm}, to=to, reason=reason)
        if is_privileged(self.actor):
            kind = "revive" if revive else {"confirmed": "confirm", "refuted": "refute", "abandoned": "abandon",
                                            "superseded": "supersede"}.get(to, to)
            self.event(op="decision", kind=kind, node=n["id"], reason=reason, evidence=verdict.get("evidence"),
                       proposer=self.proposer, approver=self.actor)

    def confirm_problems(self, n: dict) -> list[str]:
        st = self.evaluation()
        ev = st.E[n["id"]]
        out = [] if ev.level == "fresh" else [f"level is {ev.level}"]
        bad_edges = {r.get("edge") for r in ev.reasons if r["level"] in ("broken", "pending", "orphaned")}
        kind = n.get("kind")
        if kind in ("finding", "claim"):
            ok = [e for e in edges(n, "evidence") if e.get("polarity", "supports") == "supports"
                  and (e.get("predicate") or e.get("kill_if")) and edge_key(e) not in bad_edges]
            if not ok:
                out.append("needs a supports evidence edge whose predicate holds")
        elif kind == "solution":
            ups = [self.nodes.get(ref_id(e.get("to")) or "", {}) for e in edges(n, "evidence")]
            validate = any(u.get("purpose") == "validate" or facet_value(u, "purpose") == "validate" for u in ups)
            frozen = any(e["to"].startswith("run:") for e in edges(n, "evidence"))
            theory = any(facet_value(self.nodes.get(ref_id(e.get("to")) or "", {}), "role") == "theory" for e in edges(n, "cites", "basis"))
            if not (validate or frozen or theory):
                out.append("needs validate evidence or a theory reference")
        elif kind == "decision":
            choice = facet_value(n, "choice")
            if not choice:
                out.append("needs a choice")
            else:
                group = (self.nodes.get(choice) or {}).get("alt_group")
                rejected = {r.get("node") for r in facet_value(n, "rejected") or [] if isinstance(r, dict) and r.get("reason")}
                missing = [s for s, m in self.nodes.items() if group and m.get("alt_group") == group and s != choice and s not in rejected]
                if missing:
                    out.append("needs a reason for each rejected sibling: " + ", ".join(sorted(missing)))
        if n.get("alt_group"):
            others = [s for s, m in self.nodes.items() if s != n["id"] and m.get("alt_group") == n["alt_group"]
                      and m.get("status") in ("confirmed", "locked") and m.get("kind") == n.get("kind")]
            if others:
                out.append(f"{others[0]} is already confirmed in {n['alt_group']}")
        return out

    def freeze_evidence(self, n: dict) -> None:
        """Refutation: node: evidence becomes immutable run: addresses of the runs each cell currently uses."""
        st = self.evaluation()
        out = []
        for e in edges(n):
            a = parse_addr(e["to"]) if e.get("type") == "evidence" else None
            ev = st.E.get(a.id) if a and a.scheme == "node" and a.out else None
            rows = ev.rows(a.out, a.sel) if ev else None
            runs = [ev.cells[cid].run for cid, *_ in rows or [] if ev.cells.get(cid) and ev.cells[cid].run]
            if not runs:
                out.append(e)
                continue
            for r in runs:
                to = f"run:{r['id']}#out.{a.out}"
                if not any(x["to"] == to for x in out):
                    o = ((r.get("outputs") or {}).get(a.out) or {})
                    out.append({**e, "to": to, "frozen_from": e["to"], "seen": o.get("fp")})
        n["edges"] = out

    def op_rollback(self, op: dict) -> None:
        n = self.node(op.get("node"))
        target = next((v for v in self.store.history(n["id"]) if v.get("vid") == op.get("to_vid")), None)
        if target is None:
            raise OpError(404, f"no version {op.get('to_vid')} of {n['id']}")
        self.guard_locked(n, "edit_locked")
        mode = op.get("edges", False)
        if mode != "only":
            n["facets"] = copy.deepcopy(target.get("facets") or {})
            self.edited += [(n["id"], k, "rollback") for k in set(n["facets"]) | set(target.get("facets") or {})]
        if mode:
            n["edges"] = copy.deepcopy(target.get("edges") or [])
        self.check_graph(n)
        self.reverts[n["id"]] = target["vid"]
        self.touch(n["id"], "rollback")
        self.event(op="rollback", node=n["id"], to_vid=target["vid"], edges=mode)
        if is_privileged(self.actor):
            self.event(op="decision", kind="rollback", node=n["id"], reason=op.get("reason"), proposer=self.proposer,
                       approver=self.actor)

    def op_restore_snapshot(self, op: dict) -> None:
        snap = self.store.snapshot(str(op.get("name")))
        if not snap:
            raise OpError(404, f"no snapshot {op.get('name')}")
        for nid, vid in (snap.get("nodes") or {}).items():
            n = self.nodes.get(nid)
            if n and (n.get("head") or {}).get("vid") != vid:
                self.op_rollback({"op": "rollback", "node": nid, "to_vid": vid, "edges": True})
        for key, rid in (snap.get("runs") or {}).items():
            nid, _, cell = key.rpartition("/")
            if nid in self.nodes and rid in self.state.runs.by_id:
                self.nodes[nid].setdefault("selected", {})[cell] = rid
                self.dirty.add(nid)
        self.event(op="restore_snapshot", name=snap.get("name"))

    def op_lock(self, op: dict) -> None:
        n = self.node(op.get("node"))
        if n.get("status") != "confirmed":
            raise OpError(409, f"only confirmed nodes can be locked ({n['id']} is {n.get('status')})")
        ev = self.evaluation().E[n["id"]]
        if ev.level != "fresh":
            raise OpError(409, f"{n['id']} is {ev.level}: a lock needs a fresh node")
        head = n.get("head") or {}
        n["status"] = "locked"
        n["lock"] = {"by": self.actor, "at": now_iso(), "vid": head.get("vid"), "fp": head.get("fp"),
                     "edges_seen": {edge_key(e): e.get("seen") for e in edges(n) if e.get("seen")},
                     "runs": {cid: c.run["id"] for cid, c in ev.cells.items() if c.run},
                     "tag": f"rd/lock/{n['id']}/r{int(head.get('rev') or 0) + 1}", "reason": op.get("reason")}
        self.tags.append((n["lock"]["tag"], op.get("reason") or "lock"))
        self.touch(n["id"], "lock")
        self.event(op="lock", node=n["id"], reason=op.get("reason"))
        self.event(op="decision", kind="lock", node=n["id"], reason=op.get("reason"), proposer=self.proposer, approver=self.actor)

    def op_unlock(self, op: dict) -> None:
        n = self.node(op.get("node"))
        if n.get("status") != "locked":
            raise OpError(409, f"{n['id']} is not locked")
        if not op.get("reason"):
            raise OpError(400, "unlock needs a reason")
        self.unlocked[n["id"]] = n.get("lock") or {}
        n["status"], n["lock"] = "confirmed", None
        self.touch(n["id"], "unlock")
        self._version += 1
        self.event(op="unlock", node=n["id"], reason=op["reason"])
        self.event(op="decision", kind="unlock", node=n["id"], reason=op["reason"], proposer=self.proposer, approver=self.actor)

    def op_select_run(self, op: dict) -> None:
        n, cell, rid = self.node(op.get("node")), str(op.get("cell") or "_"), op.get("run")
        sel = n.setdefault("selected", {})
        if rid is None:
            sel.pop(cell, None)
        else:
            run = self.state.runs.by_id.get(rid)
            if not run or run.get("node") != n["id"] or (run.get("cell") or "_") != cell:
                raise OpError(404, f"run {rid} is not a run of {n['id']}[{cell}]")
            if run.get("excluded") or run.get("state", "succeeded") != "succeeded" or check_run(self.evaluation(), run):
                raise OpError(409, "an invalid run can never be selected")
            sel[cell] = rid
        self.dirty.add(n["id"])
        self._version += 1
        self.event(op="select_run", node=n["id"], cell=cell, run=rid)

    def op_exclude_run(self, op: dict) -> None:
        run = self.run_writes.get(op.get("run")) or self.state.runs.by_id.get(op.get("run"))
        if not run:
            raise OpError(404, f"unknown run {op.get('run')}")
        if not op.get("reason"):
            raise OpError(400, "exclude needs a reason")
        rec = copy.deepcopy(run)
        rec["excluded"] = {"by": self.actor, "reason": op["reason"], "at": now_iso()}
        self.run_writes[rec["id"]] = rec
        self._version += 1
        self.event(op="exclude_run", node=rec.get("node"), cell=rec.get("cell"), run=rec["id"], reason=op["reason"])

    def op_delete(self, op: dict) -> None:
        n = self.node(op.get("node"))
        if n.get("status") != "proposed":
            raise OpError(409, "only proposed nodes can be deleted; abandon it instead")
        deps = [m["id"] for m in self.nodes.values() for e in edges(m) if ref_id(e.get("to")) == n["id"] and m["id"] != n["id"]]
        if deps or self.state.runs.by_node.get(n["id"]):
            raise OpError(409, f"{n['id']} has dependents or runs; abandon it instead", dependents=deps)
        del self.nodes[n["id"]]
        self.touched.pop(n["id"], None)
        self.deleted.add(n["id"])
        self._version += 1
        self.event(op="delete", node=n["id"])

    # commit -------------------------------------------------------------------
    def commit(self) -> list[dict]:
        at, git = now_iso(), short_head(self.store.root)
        for nid, opnames in self.touched.items():
            n = self.nodes[nid]
            prev = n.get("head") or {}
            fp = authored_fp(n)
            parent = prev.get("vid")
            edges_digest = fp_json(n.get("edges") or [])
            vid = "v-" + hashlib.sha256(f"{parent}|{fp}|{edges_digest}|{n['status']}|{at}|{self.actor}".encode()).hexdigest()[:8]
            n["head"] = {"rev": int(prev.get("rev") or 0) + 1, "vid": vid, "fp": fp}
            n["updated"] = {"by": self.actor, "at": at, **({"via": self.via} if self.via else {})}
            line = {"vid": vid, "rev": n["head"]["rev"], "parent": parent, "fp": fp, "facets": n.get("facets") or {},
                    "edges": n.get("edges") or [], "status": n["status"], "by": self.actor, "at": at, "git": git,
                    "op": "+".join(opnames), "via": self.via}
            if nid in self.reverts:
                line["reverts"] = self.reverts[nid]
            if "create" in opnames or "edit" in opnames:
                line["meta"] = {k: n.get(k) for k in ("kind", "stage", "title", "purpose", "alt_group", "notes") if n.get(k) is not None}
            if n.get("lock"):
                line["lock"] = n["lock"]
            if nid in self.unlocked:
                line["unlocked"] = self.unlocked[nid]
            for e in reversed(self.events):
                if e.get("node") == nid and "vid" not in e and e.get("op") != "decision":
                    e["vid"] = vid
                    break
            self.store.append_history(nid, line)
            self.store.write_node(n)
        for nid in self.dirty - set(self.touched) - self.deleted:
            self.store.write_node(self.nodes[nid])
        for nid in self.deleted:
            self.store.delete_node(nid)
        for rel, data in self.files.items():
            write_text_atomic(safe_join(self.store.root, rel), data.decode("utf-8"))
        for rec in self.run_writes.values():
            self.store.write_run(rec)
        for tag, msg in self.tags:          # best effort: a lock is valid without its git tag
            if git and not git_text(self.store.root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}"):
                git_text(self.store.root, "tag", "-a", tag, "-m", msg, "HEAD")
        return self.store.append_events(self.events) if self.events else []


# ---------------------------------------------------------------- applying, proposals, snapshots

def apply_ops(store: DagStore, ops: list[dict], actor: str, *, via: str | None = None, proposer: str | None = None,
              extra_events: list[dict] | None = None) -> tuple[Txn, list[dict]]:
    if not isinstance(ops, list) or not ops:
        raise OpError(400, "ops must be a non-empty list")
    store.ensure()
    with store.locked():
        invalidate(store)
        t = Txn(store, actor, state=current(store), via=via, proposer=proposer)
        for op in ops:
            t.apply(op)
        t.events += extra_events or []
        events = t.commit()
    invalidate(store)
    return t, events


def eval_delta(before: State, after: State) -> dict[str, dict]:
    old, new = before.eval_json(), after.eval_json()
    return {i: v for i, v in new.items() if old.get(i) != v}


def impact_signature(imp: dict | None) -> tuple:
    if not imp:
        return ()
    cats = ("rerun", "conditional", "reused", "revived", "review", "orphaned", "broken", "lock", "already_tried")
    return tuple((c, tuple(sorted((i.get("node"), tuple(i.get("cells") or ()), i.get("edge") or "", i.get("kind") or "")
                                  for i in imp.get(c) or []))) for c in cats)


def submit(store: DagStore, ops: list[dict], actor: str, *, base_digest: str | None = None, rationale: str | None = None,
           title: str | None = None) -> dict:
    """POST /ops: apply directly (humans; agents under the safe rule) or turn the batch into one proposal."""
    from .impact import impact  # noqa: PLC0415 — impact imports this module
    if not isinstance(ops, list) or not ops:
        raise OpError(400, "ops must be a non-empty list")
    before = current(store)
    if base_digest and base_digest != before.digest:
        raise OpError(409, "the DAG changed since your preview", digest=before.digest)
    imp = impact(store, {"ops": ops}, actor=actor)
    if not is_privileged(actor):
        modes = agent_modes(store, ops, before.nodes, actor)
        if any(m == "never" for m, _ in modes):
            raise OpError(403, "open a proposal", reasons=[w for m, w in modes if m == "never"])
        status_change = any(op.get("op") == "set_status" and (before.nodes.get(op.get("node") or "") or {}).get("status")
                            in ("confirmed", "locked") for op in ops)
        if imp.get("errors"):                   # replay the reducers to raise the first error with its status
            dry = Txn(store, actor, state=before, dry=True)
            for op in ops:
                dry.apply(op)
            raise OpError(400, "; ".join(imp["errors"]))
        if any(m != "direct" for m, _ in modes) or imp["lock"] or status_change:
            return {"applied": False, "proposal": create_proposal(store, title or rationale or summarize(ops), rationale, ops, actor, imp)}
    summary = {k: imp["summary"][k] for k in ("rerun", "reused", "review")} | {"reused_gpu_h": imp["summary"]["gpu_h"]["reused"]}
    _, events = apply_ops(store, ops, actor, extra_events=[{"op": "applied", "impact": summary, "summary": summarize(ops)}])
    return {"applied": True, "events": events, "eval_delta": eval_delta(before, current(store))}


def summarize(ops: list[dict]) -> str:
    parts = [f"{o.get('op')} {o.get('node') if isinstance(o.get('node'), str) else (o.get('node') or {}).get('id') or o.get('key') or ''}".strip()
             for o in ops[:4]]
    return ", ".join(parts) + (f" (+{len(ops) - 4})" if len(ops) > 4 else "")


def create_proposal(store: DagStore, title: str, rationale: str | None, ops: list[dict], actor: str, imp: dict | None = None,
                    code: dict | None = None) -> dict:
    from .impact import impact  # noqa: PLC0415
    if not isinstance(ops, list) or not ops:
        raise OpError(400, "ops must be a non-empty list")
    imp = imp or impact(store, {"ops": ops, **({"code": code} if code else {})}, actor=actor)
    requires = sorted({i["requires"] for i in imp.get("lock") or [] if i.get("requires")}
                      | {f"unlock:{o.get('node')}" for o in ops if o.get("op") == "unlock"})
    store.ensure()
    with store.locked():
        prop = {"id": store.next_proposal_id(), "by": actor, "at": now_iso(), "state": "open", "title": title or summarize(ops),
                "rationale": rationale, "ops": ops, "requires": requires, "base_digest": imp["base_digest"], "impact": imp,
                "decided": None, **({"code": code} if code else {})}
        store.write_proposal(prop)
        store.append_events([{"by": actor, "op": "proposal_opened", "proposal": prop["id"], "summary": prop["title"]}])
    invalidate(store)
    return prop


def approve(store: DagStore, pid: str, actor: str, indices: list[int] | None = None) -> dict:
    from .impact import impact  # noqa: PLC0415
    if not is_human(actor):
        raise OpError(403, "open a proposal")
    prop = store.proposal(pid)
    if not prop:
        raise OpError(404, f"unknown proposal {pid}")
    if prop.get("state") not in ("open", "needs_rebase"):
        raise OpError(409, f"proposal is {prop.get('state')}")
    ops = [prop["ops"][i] for i in indices] if indices else list(prop["ops"])
    before = current(store)
    new = impact(store, {"ops": ops, **({"code": prop["code"]} if prop.get("code") else {})}, actor=actor)
    if new["base_digest"] != prop.get("base_digest") and impact_signature(new) != impact_signature(prop.get("impact")):
        prop.update(state="needs_rebase", impact=new, base_digest=new["base_digest"])
        with store.locked():
            store.write_proposal(prop)
        raise OpError(409, "needs_rebase", impact=new, proposal=prop)
    pre = [{"op": "unlock", "node": r.split(":", 1)[1], "reason": f"approved {pid}"} for r in prop.get("requires") or []
           if r.startswith("unlock:") and (before.nodes.get(r.split(":", 1)[1]) or {}).get("status") == "locked"
           and not any(o.get("op") == "unlock" and o.get("node") == r.split(":", 1)[1] for o in ops)]
    summary = {k: new["summary"][k] for k in ("rerun", "reused", "review")} | {"reused_gpu_h": new["summary"]["gpu_h"]["reused"]}
    _, events = apply_ops(store, pre + ops, actor, via=pid, proposer=prop.get("by"),
                          extra_events=[{"op": "applied", "impact": summary, "summary": prop.get("title")},
                                        {"op": "proposal_applied", "proposal": pid}])
    prop.update(state="applied", decided={"by": actor, "at": now_iso()}, impact=new)
    with store.locked():
        store.write_proposal(prop)
    return {"applied": True, "events": events, "eval_delta": eval_delta(before, current(store)), "proposal": prop}


def reject(store: DagStore, pid: str, actor: str, reason: str | None) -> dict:
    if not is_human(actor):
        raise OpError(403, "open a proposal")
    prop = store.proposal(pid)
    if not prop:
        raise OpError(404, f"unknown proposal {pid}")
    if prop.get("state") not in ("open", "needs_rebase"):
        raise OpError(409, f"proposal is {prop.get('state')}")
    prop.update(state="rejected", decided={"by": actor, "at": now_iso(), "reason": reason})
    with store.locked():
        store.write_proposal(prop)
        store.append_events([{"by": actor, "op": "proposal_rejected", "proposal": pid, "reason": reason},
                             {"by": actor, "op": "decision", "kind": "reject", "proposal": pid, "reason": reason,
                              "proposer": prop.get("by"), "approver": actor}])
    invalidate(store)
    return prop


def agent_modes(store: DagStore, ops: list[dict], nodes: dict, actor: str) -> list[tuple[str, str]]:
    """agent_mode for each op, judged against the state as the batch evolves: a node an agent creates in the same
    batch starts as proposed and owned by it, and each direct status change it makes is seen by the next op. So a
    batch [create, set active, set confirmed] still turns the confirmation into a proposal (docs/DAG.md §2.7)."""
    sim = copy.deepcopy(nodes)
    modes = []
    for op in ops:
        kind = op.get("op")
        if kind == "config_edit":
            rel, key = str(op.get("file")), str(op.get("key"))
            mode = agent_mode(op, sim, actor, bound_nodes(sim, rel, key))
            if mode[0] == "direct":
                try:
                    target = safe_join(store.root, rel)
                except Exception:   # noqa: BLE001 — the reducer reports the bad path
                    target = None
                live = [n for n in bound_nodes(sim, rel, key) if n.get("status") not in DEAD]
                if not (target and target.is_file() and target.suffix in (".yaml", ".yml") and live):
                    mode = ("proposal", f"config_edit of {rel}: agents edit only existing YAML keys bound by a live node")
        else:
            mode = agent_mode(op, sim, actor)
        modes.append(mode)
        if kind == "create" and isinstance(op.get("node"), dict) and op["node"].get("id"):
            new = copy.deepcopy(op["node"])
            new.setdefault("status", "proposed")
            new["created"] = {"by": actor}
            sim[new["id"]] = new
        elif kind == "set_status" and mode[0] == "direct" and op.get("node") in sim:
            sim[op["node"]]["status"] = op.get("to")
    return modes


def make_snapshot(store: DagStore, name: str, actor: str, note: str | None = None, *, tag: bool = True,
                  overwrite: bool = False) -> dict:
    """overwrite: only pass_gate (human) may replace an existing snapshot (re-passing a gate)."""
    safe_name(name, "snapshot name")
    if (store.dir / "snapshots" / f"{name}.yaml").exists() and not overwrite:
        raise OpError(409, f"snapshot {name} exists")
    st = current(store)
    snap = {"name": name, "at": now_iso(), "by": actor, "git": short_head(store.root),
            "nodes": {i: (n.get("head") or {}).get("vid") for i, n in sorted(st.nodes.items()) if n.get("head")},
            "runs": {f"{i}/{cid}": c.run["id"] for i, ev in sorted(st.E.items()) for cid, c in ev.cells.items()
                     if c.run and c.level == "fresh"},
            "eval_digest": st.digest, "note": note}
    store.ensure()
    with store.locked():
        store.write_snapshot(snap)
        store.append_events([{"by": actor, "op": "snapshot", "name": name, "summary": note}])
        if tag and snap["git"]:
            git_text(store.root, "tag", *(["-f"] if overwrite else []), "-a", f"rd/snap/{name}", "-m", note or name, "HEAD")
    invalidate(store)
    return snap


def restore_proposal(store: DagStore, name: str, actor: str) -> dict:
    snap = store.snapshot(name)
    if not snap:
        raise OpError(404, f"no snapshot {name}")
    head = short_head(store.root)
    code = {"diff": f"HEAD..{check_rev(snap['git'])}"} if snap.get("git") and head and snap["git"] != head else None
    title = f"Restore snapshot {name}" + (f" (code: git revert to {snap['git']})" if code else "")
    return create_proposal(store, title, f"restore {name}", [{"op": "restore_snapshot", "name": name}], actor, code=code)


# ---------------------------------------------------------------- recording runs (§4.6)

def _within(a: Any, v: Any, tol: dict) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(v, (list, tuple)):
        return len(a) == len(v) and all(_within(x, y, tol) for x, y in zip(a, v))
    if isinstance(a, bool) or isinstance(v, bool) or not isinstance(a, (int, float)) or not isinstance(v, (int, float)):
        return a == v
    if "abs" in (tol or {}):
        return abs(v - a) <= float(tol["abs"])
    return abs(v - a) <= float((tol or {}).get("rel", 0.03)) * abs(a)


def new_run_id() -> str:
    return datetime.now(UTC).strftime("r-%Y%m%d-%H%M-") + secrets.token_hex(2)


def record_run(store: DagStore, record: dict, actor: str = "system") -> dict:
    """Store a terminal run record with its output fps through the anchor-based cutoff (§4.6); the caller publishes."""
    if not isinstance(record, dict):
        raise OpError(400, "a run record is an object")
    store.ensure()
    with store.locked():                       # the anchor is what consumers saw: read it under the lock
        st = current(store)
        n = st.nodes.get(record.get("node") or "")
        if not n or not is_action(n):
            raise OpError(404, f"unknown action node: {record.get('node')}")
        cell = record.get("cell")
        if isinstance(cell, dict) or cell is None:
            cell = cell_id(cell or record.get("cell_values") or {})
        cell = cell_id(parse_cell(str(cell)))
        rec = copy.deepcopy(record)
        rec.update(node=n["id"], cell=cell)
        if not rec.get("id"):                  # r-YYYYMMDD-HHMM-xxxx; retried until unique
            rec["id"] = next(i for i in iter(new_run_id, None) if i not in st.runs.by_id)
        rec["id"] = safe_name(rec["id"], "run id")
        if rec["id"] in st.runs.by_id:
            raise OpError(409, f"run {rec['id']} exists (runs are immutable)")
        rec.setdefault("state", "succeeded")
        if actor != "system" or not rec.get("by"):
            rec["by"] = actor              # never a caller-chosen identity
        rec.setdefault("fp_algo", "rd/1")
        rec.setdefault("platform", spec_of(n).get("platform"))
        rec.setdefault("spec_fp", spec_fp(spec_of(n)))
        rec.setdefault("node_vid", (n.get("head") or {}).get("vid"))
        rec["trace"] = {a: (i if isinstance(i, dict) else {"fp": i}) for a, i in (rec.get("trace") or {}).items()}
        rec.setdefault("trace_quality", "traced" if rec["trace"] else "coarse")
        rec["recorded_at"] = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        specs, out_cfg = facet_value(n, "outputs") or {}, st.cfg.get("outputs") or {}
        ev_cell = st.E[n["id"]].cells.get(cell)
        prev = (ev_cell.run if ev_cell and ev_cell.run else None) or next(iter(st.runs.usable(n["id"], cell)), None)
        cutoff: dict[str, bool] = {}
        outs = {}
        for name, o in (rec.get("outputs") or {}).items():
            o = dict(o) if isinstance(o, dict) else {"value": o}
            tol = (specs.get(name) or {}).get("tol") if isinstance(specs.get(name), dict) else None
            tol = tol or out_cfg.get("default_tol") or {"rel": 0.03}
            a = ((prev or {}).get("outputs") or {}).get(name) if rec["state"] == "succeeded" else None
            if isinstance(a, dict) and "anchor" in a and a.get("fp") and _within(a["anchor"], o.get("value"), tol):
                o.update(fp=a["fp"], anchor=a["anchor"], cutoff=True)     # compared to the ANCHOR: drift stays bounded
            else:
                o.update(fp=fp_json(quantize(o.get("value"), int(out_cfg.get("sig", 4)))), anchor=o.get("value"), cutoff=False)
            cutoff[name] = o["cutoff"]
            outs[name] = o
        rec["outputs"] = outs
        store.write_run(rec)
        store.append_events([{"by": actor, "op": "run_recorded", "node": n["id"], "cell": cell, "run": rec["id"],
                              "state": rec["state"], "cutoff": any(cutoff.values()), "experiment": rec.get("experiment")}])
    invalidate(store)
    return {"run_id": rec["id"], "cutoff": cutoff, "eval_delta": eval_delta(st, current(store))}


__all__ = ["OpError", "Txn", "apply_ops", "submit", "create_proposal", "approve", "reject", "make_snapshot",
           "restore_proposal", "record_run"]
