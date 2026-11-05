"""Outline operations, turned into map operations (create / edit / set_status / delete on section and claim nodes)
and applied in one batch, so a failed batch changes nothing.

    {"op": "add_section", "title": "…", "role": "…", "phase": "insight", "after": "sec.…"|null}
    {"op": "edit_section", "section": "sec.…", "title"?, "role"?, "phase"?}
    {"op": "move_section", "section": "sec.…", "to": 2}                      0-based position among the sections
    {"op": "remove_section", "section": "sec.…"}                             abandons it and its items
    {"op": "add_item", "parent": "sec.…|claim.…", "text": "…", "at"?: {"after": id} | {"parallel": id} | {"first": true},
     "derived"?, "condition"?, "id"?}                                       without "at": a new last step
    {"op": "edit_item", "item": "claim.…", "text"?, "derived"?, "condition"?, "summary_of"?}
    {"op": "move_item", "item": "claim.…", "how": "up|down|indent|outdent|join|split"}
    {"op": "remove_item", "item": "claim.…"}                                 abandons it and what is under it
    {"op": "set_note", "parent": id, "step": 1, "text": "…"}                  what a parallel group is
    {"op": "fork", "item": "claim.…", "question"?: "…", "directions": ["…", "…"]}
                         the item becomes a branch point; its sub-items move to direction 1
    {"op": "add_direction", "item": "claim.…", "text": "…"}
    {"op": "choose_direction", "item": "claim.…", "direction": "claim.…"}    the other live directions are abandoned
    {"op": "abandon_direction", "item": "claim.…", "direction": "claim.…", "reason": "…"}
Items and sections are made "active" by people and "proposed" by agents (ops.submit turns an agent's edits of active
nodes into proposals, as everywhere on the map). Nothing is deleted: a removed item is abandoned, so its history stays
and the tasks that served only it drop out of the counts.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

from ..dag.model import ABANDON_REASONS, DEAD, facet_value
from .model import chain_of, fork_of
from .templates import SECTION_PHASES


class OutlineError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def new_item_id() -> str:
    return f"claim.i{uuid.uuid4().hex[:8]}"


def _json(v: Any) -> dict:
    return {"type": "json", "value": v}


class Plan:
    """The outline as it will be after the ops so far: chains, forks, new nodes and status changes, kept locally and
    written out as map ops at the end."""

    def __init__(self, nodes: dict[str, dict], actor_is_human: bool, lang: str = "zh"):
        self.nodes, self.human, self.lang = nodes, actor_is_human, lang
        self.chains: dict[str, list[list[str]]] = {}
        self.notes: dict[str, dict] = {}
        self.forks: dict[str, dict] = {}
        self.created: dict[str, dict] = {}
        self.edits: dict[str, dict] = {}       # node -> {facet: value} or meta (title)
        self.statuses: list[dict] = []
        self.retarget: dict[str, str] = {}     # tasks of item -> item (a fork moves them to direction 1)
        self.removed: set[str] = set()
        self.last_created: str | None = None
        self.last_section: str | None = None

    # ------------------------------------------------------------ reading through the local changes
    def node(self, nid: str) -> dict:
        n = self.created.get(nid) or self.nodes.get(nid)
        if n is None:
            raise OutlineError(404, f"no such node: {nid}")
        return n

    def chain(self, nid: str) -> list[list[str]]:
        if nid not in self.chains:
            self.chains[nid] = copy.deepcopy(chain_of(self.node(nid)))
        return self.chains[nid]

    def note_map(self, nid: str) -> dict:
        if nid not in self.notes:
            self.notes[nid] = dict(facet_value(self.node(nid), "chain_notes") or {})
        return self.notes[nid]

    def fork(self, nid: str) -> dict | None:
        if nid not in self.forks:
            f = fork_of(self.node(nid))
            self.forks[nid] = copy.deepcopy(f) if f else None
        return self.forks[nid]

    def parents(self) -> dict[str, tuple[str, str]]:
        """child -> (parent, "chain" | "fork") over every node with a chain or a fork, local changes included."""
        out = {}
        ids = set(self.nodes) | set(self.created)
        for pid in ids:
            n = self.node(pid)
            if n.get("kind") not in ("section", "claim"):
                continue
            for step in (self.chains[pid] if pid in self.chains else chain_of(n)):
                for c in step:
                    out[c] = (pid, "chain")
            f = self.forks[pid] if pid in self.forks else fork_of(n)
            for d in (f or {}).get("directions") or []:
                out[d] = (pid, "fork")
        return out

    def locate(self, item: str) -> tuple[str, int, int]:
        par = self.parents().get(item)
        if not par or par[1] != "chain":
            raise OutlineError(404, f"{item} is not in a chain of the outline")
        chain = self.chain(par[0])
        for si, step in enumerate(chain):
            if item in step:
                return par[0], si, step.index(item)
        raise OutlineError(404, f"{item} is not in a chain of the outline")

    def subtree(self, item: str) -> list[str]:
        out, todo = [], [item]
        while todo:
            x = todo.pop()
            if x in out:
                continue
            out.append(x)
            for step in self.chain(x) if self.node(x).get("kind") == "claim" else []:
                todo.extend(step)
            todo.extend((self.fork(x) or {}).get("directions") or [])
        return out

    # ------------------------------------------------------------ helpers
    def set_facet(self, nid: str, name: str, value: Any) -> None:
        if nid in self.created:
            self.created[nid].setdefault("facets", {})[name] = value
        else:
            self.edits.setdefault(nid, {})[name] = value

    def make_item(self, text: str, nid: str | None = None, derived: bool = False, condition: str = "") -> str:
        text = (text or "").strip()
        if not text:
            raise OutlineError(400, "an item needs text")
        nid = nid or new_item_id()
        if nid in self.nodes or nid in self.created:
            raise OutlineError(409, f"node exists: {nid}")
        facets: dict[str, Any] = {"text": {"type": "prose", "value": text}}
        if derived:
            facets["derived"] = _json(True)
        if condition:
            facets["condition"] = {"type": "prose", "value": condition}
        self.created[nid] = {"id": nid, "kind": "claim", "status": "active" if self.human else "proposed",
                             "title": {self.lang: text[:80]}, "facets": facets, "edges": []}
        return nid

    def drop_from_parent(self, item: str) -> tuple[str, int]:
        parent, si, _ = self.locate(item)
        chain = self.chain(parent)
        chain[si].remove(item)
        if not chain[si]:
            del chain[si]
            self.shift_notes(parent, si, -1)
        return parent, si

    def shift_notes(self, parent: str, at: int, delta: int) -> None:
        notes = self.note_map(parent)
        moved = {}
        for k, v in notes.items():
            i = int(k)
            if delta < 0 and i == at:
                continue
            moved[str(i + delta if i >= at else i)] = v
        self.notes[parent] = moved

    def abandon(self, nid: str, reason: str, note: str) -> None:
        n = self.node(nid)
        if nid in self.created:
            del self.created[nid]
            return
        if n.get("status") in DEAD:
            return
        if n.get("status") == "locked":
            raise OutlineError(409, f"{nid} is locked: unlock it first")
        self.statuses.append({"op": "set_status", "node": nid, "to": "abandoned", "reason": reason, "note": note})
        self.removed.add(nid)

    # ------------------------------------------------------------ the ops
    def apply(self, op: dict) -> None:
        kind = op.get("op")
        fn = getattr(self, f"op_{kind}", None) if isinstance(kind, str) else None
        if fn is None:
            raise OutlineError(400, f"unknown outline op: {kind}")
        fn(op)

    def sections(self) -> list[dict]:
        secs = [self.node(i) for i in set(self.nodes) | set(self.created)]
        secs = [s for s in secs if s.get("kind") == "section" and s.get("status") not in DEAD
                and isinstance(self.order_of(s), int) and s["id"] not in self.removed]
        return sorted(secs, key=lambda s: (self.order_of(s), s["id"]))

    def order_of(self, s: dict) -> Any:
        e = self.edits.get(s["id"], {})
        return e["order"]["value"] if "order" in e else facet_value(s, "order")

    def renumber(self, ordered: list[str]) -> None:
        for k, sid in enumerate(ordered):
            if self.order_of(self.node(sid)) != k:
                self.set_facet(sid, "order", _json(k))

    def op_add_section(self, op: dict) -> None:
        phase = op.get("phase") or "insight"
        if phase not in SECTION_PHASES:
            raise OutlineError(400, f"phase must be one of {', '.join(SECTION_PHASES)}")
        key = str(op.get("key") or "").strip() or f"s{uuid.uuid4().hex[:6]}"
        title = op.get("title") or key
        title = title if isinstance(title, dict) else {self.lang: str(title).strip()}
        sid = f"sec.{key}"
        old = self.nodes.get(sid)
        if old is not None and old.get("status") not in DEAD and facet_value(old, "order") is None:
            # a section paper sync made from a % rd:sec anchor: the outline adopts it, so the text stays bound to it
            for k, v in (("role", {"type": "prose", "value": str(op.get("role") or "")}), ("phase", _json(phase)),
                         ("order", _json(0)), ("chain", _json([]))):
                self.set_facet(sid, k, v)
            self.edits[sid]["__title"] = title
        else:
            n = 2
            while sid in self.nodes or sid in self.created:
                sid, n = f"sec.{key}-{n}", n + 1
            self.created[sid] = {"id": sid, "kind": "section", "stage": "W", "status": "active" if self.human else "proposed",
                                 "title": title, "facets": {"role": {"type": "prose", "value": str(op.get("role") or "")},
                                                            "phase": _json(phase), "order": _json(0), "chain": _json([])},
                                 "edges": []}
        self.last_section = sid
        ordered = [s["id"] for s in self.sections() if s["id"] != sid]
        at = ordered.index(op["after"]) + 1 if op.get("after") in ordered else len(ordered)
        ordered.insert(at, sid)
        self.renumber(ordered)

    def op_edit_section(self, op: dict) -> None:
        sid = op.get("section")
        s = self.node(sid)
        if s.get("kind") != "section":
            raise OutlineError(400, f"{sid} is not a section")
        if "title" in op:
            t = op["title"]
            self.edits.setdefault(sid, {})["__title"] = t if isinstance(t, dict) else {**(s.get("title") or {}), self.lang: str(t).strip()}
        if "role" in op:
            self.set_facet(sid, "role", {"type": "prose", "value": str(op["role"] or "")})
        if "phase" in op:
            if op["phase"] not in SECTION_PHASES:
                raise OutlineError(400, f"phase must be one of {', '.join(SECTION_PHASES)}")
            self.set_facet(sid, "phase", _json(op["phase"]))

    def op_move_section(self, op: dict) -> None:
        ordered = [s["id"] for s in self.sections()]
        sid = op.get("section")
        if sid not in ordered:
            raise OutlineError(404, f"{sid} is not a section of the outline")
        ordered.remove(sid)
        ordered.insert(max(0, min(int(op.get("to") or 0), len(ordered))), sid)
        self.renumber(ordered)

    def op_remove_section(self, op: dict) -> None:
        sid = op.get("section")
        if self.node(sid).get("kind") != "section":
            raise OutlineError(400, f"{sid} is not a section")
        for step in self.chain(sid):
            for item in step:
                for x in self.subtree(item):
                    self.abandon(x, "out_of_scope", "removed from the outline")
        self.abandon(sid, "out_of_scope", "removed from the outline")

    def op_add_item(self, op: dict) -> None:
        parent = op.get("parent")
        p = self.node(parent)
        if p.get("kind") not in ("section", "claim"):
            raise OutlineError(400, "items go under a section or another item")
        nid = self.make_item(op.get("text"), op.get("id"), bool(op.get("derived")), str(op.get("condition") or ""))
        at = op.get("at") or {}
        chain = self.chain(parent)
        if at.get("parallel") or at.get("after"):
            ref = at.get("parallel") or at.get("after")
            par, si, pos = self.locate(ref)
            if par != parent:
                raise OutlineError(400, f"{ref} is not under {parent}")
            if at.get("parallel"):
                chain[si].insert(pos + 1, nid)
            else:
                chain.insert(si + 1, [nid])
                self.shift_notes(parent, si + 1, +1)
        elif at.get("first"):
            chain.insert(0, [nid])
            self.shift_notes(parent, 0, +1)
        else:
            chain.append([nid])
        self.last_created = nid

    def op_edit_item(self, op: dict) -> None:
        nid = op.get("item")
        n = self.node(nid)
        if n.get("kind") != "claim":
            raise OutlineError(400, f"{nid} is not an item")
        if "text" in op:
            text = str(op["text"] or "").strip()
            if not text:
                raise OutlineError(400, "an item needs text")
            self.set_facet(nid, "text", {"type": "prose", "value": text})
            self.edits.setdefault(nid, {})["__title"] = {self.lang: text[:80]}
        if "derived" in op:
            self.set_facet(nid, "derived", _json(bool(op["derived"])))
        if "condition" in op:
            self.set_facet(nid, "condition", {"type": "prose", "value": str(op["condition"] or "")})
        if "summary_of" in op:
            ids = [i for i in op["summary_of"] or [] if isinstance(i, str)]
            self.set_facet(nid, "summary_of", _json(ids))

    def op_move_item(self, op: dict) -> None:
        item, how = op.get("item"), op.get("how")
        parent, si, pos = self.locate(item)
        chain = self.chain(parent)
        if how in ("up", "down"):
            d = -1 if how == "up" else 1
            step = chain[si]
            if len(step) > 1 and 0 <= pos + d < len(step):
                step[pos], step[pos + d] = step[pos + d], step[pos]
            elif 0 <= si + d < len(chain) and len(step) == 1:
                chain[si], chain[si + d] = chain[si + d], chain[si]
                notes = self.note_map(parent)
                a, b = notes.get(str(si)), notes.get(str(si + d))
                for k, v in ((str(si), b), (str(si + d), a)):
                    if v is None:
                        notes.pop(k, None)
                    else:
                        notes[k] = v
        elif how == "indent":
            prev = chain[si][pos - 1] if pos > 0 else (chain[si - 1][-1] if si > 0 else None)
            if prev is None:
                raise OutlineError(409, "the first item cannot go under another one")
            self.drop_from_parent(item)
            self.chain(prev).append([item])
        elif how == "outdent":
            if self.node(parent).get("kind") != "claim":
                raise OutlineError(409, "an item directly under a section cannot move up a level")
            gp, gsi, _ = self.locate(parent)
            self.drop_from_parent(item)
            self.chain(gp).insert(gsi + 1, [item])
            self.shift_notes(gp, gsi + 1, +1)
        elif how == "join":
            if si == 0:
                raise OutlineError(409, "the first step has no step before it to join")
            chain[si].remove(item)
            chain[si - 1].append(item)
            if not chain[si]:
                del chain[si]
                self.shift_notes(parent, si, -1)
        elif how == "split":
            if len(chain[si]) < 2:
                return
            chain[si].remove(item)
            chain.insert(si + 1, [item])
            self.shift_notes(parent, si + 1, +1)
        else:
            raise OutlineError(400, "how: up, down, indent, outdent, join or split")

    def op_remove_item(self, op: dict) -> None:
        item = op.get("item")
        par = self.parents().get(item)
        for x in self.subtree(item):
            self.abandon(x, "out_of_scope", "removed from the outline")
        if par and par[1] == "chain":
            self.drop_from_parent(item)
        elif par and par[1] == "fork":
            f = self.fork(par[0])
            f["directions"] = [d for d in f["directions"] if d != item]
            if f.get("chosen") == item:
                f["chosen"] = None

    def op_set_note(self, op: dict) -> None:
        parent, step = op.get("parent"), int(op.get("step") or 0)
        notes = self.note_map(parent)
        text = str(op.get("text") or "").strip()
        if text:
            notes[str(step)] = text[:80]
        else:
            notes.pop(str(step), None)

    def op_fork(self, op: dict) -> None:
        item = op.get("item")
        if self.node(item).get("kind") != "claim":
            raise OutlineError(400, f"{item} is not an item")
        if self.fork(item):
            raise OutlineError(409, f"{item} already branches; add a direction instead")
        texts = [t for t in op.get("directions") or [] if str(t).strip()]
        if len(texts) < 2:
            raise OutlineError(400, "a fork needs at least two directions")
        dirs = [self.make_item(t) for t in texts]
        # what the item held so far was the first direction: its sub-items and tasks move there
        kids = self.chain(item)
        if kids:
            self.chains[dirs[0]] = kids
            self.chains[item] = []
        self.retarget[item] = dirs[0]
        self.forks[item] = {"directions": dirs, "chosen": None}
        if op.get("question"):
            self.op_edit_item({"item": item, "text": op["question"]})

    def op_add_direction(self, op: dict) -> None:
        f = self.fork(op.get("item"))
        if not f:
            raise OutlineError(409, f"{op.get('item')} does not branch; fork it first")
        f["directions"].append(self.make_item(op.get("text")))

    def op_choose_direction(self, op: dict) -> None:
        item, chosen = op.get("item"), op.get("direction")
        f = self.fork(item)
        if not f or chosen not in f["directions"]:
            raise OutlineError(400, f"{chosen} is not a direction of {item}")
        if self.node(chosen).get("status") in DEAD:
            raise OutlineError(409, f"{chosen} was abandoned")
        f["chosen"] = chosen
        for d in f["directions"]:
            if d == chosen or self.node(d).get("status") in DEAD:
                continue
            for x in self.subtree(d):
                if x not in self.created and self.node(x).get("status") not in DEAD:
                    self.statuses.append({"op": "set_status", "node": x, "to": "abandoned", "reason": "dominated",
                                          "note": f"another direction was chosen ({chosen})"})

    def op_abandon_direction(self, op: dict) -> None:
        item, d = op.get("item"), op.get("direction")
        f = self.fork(item)
        if not f or d not in f["directions"]:
            raise OutlineError(400, f"{d} is not a direction of {item}")
        reason = op.get("reason") or "other"
        cat = reason if reason in ABANDON_REASONS else "other"
        for x in self.subtree(d):
            if x in self.created:
                continue
            if self.node(x).get("status") not in DEAD:
                self.statuses.append({"op": "set_status", "node": x, "to": "abandoned", "reason": cat,
                                      "note": None if cat == reason else str(reason)[:300]})
        if f.get("chosen") == d:
            f["chosen"] = None

    # ------------------------------------------------------------ out
    def dag_ops(self) -> list[dict]:
        ops: list[dict] = [{"op": "create", "node": n} for n in self.created.values()]
        touched = set(self.edits) | set(self.chains) | set(self.notes) | set(self.forks)
        for nid in sorted(touched):
            if nid in self.created:
                n = self.created[nid]
                if nid in self.chains:
                    n["facets"]["chain"] = _json(self.chains[nid])
                if self.notes.get(nid):
                    n["facets"]["chain_notes"] = _json(self.notes[nid])
                if self.forks.get(nid):
                    n["facets"]["fork"] = _json(self.forks[nid])
                for k, v in self.edits.get(nid, {}).items():
                    if k == "__title":
                        n["title"] = v
                    else:
                        n["facets"][k] = v
                continue
            if nid in self.removed:
                continue
            base = self.nodes[nid]
            sets: dict[str, Any] = {}
            meta: dict[str, Any] = {}
            if nid in self.chains and self.chains[nid] != chain_of(base):
                sets["chain"] = _json(self.chains[nid])
            if nid in self.notes and self.notes[nid] != (facet_value(base, "chain_notes") or {}):
                sets["chain_notes"] = _json(self.notes[nid])
            if nid in self.forks and self.forks[nid] != fork_of(base):
                sets["fork"] = _json(self.forks[nid])
            for k, v in self.edits.get(nid, {}).items():
                if k == "__title":
                    meta["title"] = v
                else:
                    sets[k] = v
            if not sets and not meta:
                continue
            structural = set(sets) <= {"chain", "chain_notes", "fork", "order", "phase", "role", "summary_of", "derived", "condition"}
            ops.append({"op": "edit", "node": nid, "set": sets, **meta, **({"editorial": True} if structural and not meta else {})})
        ops += self.statuses
        return ops
