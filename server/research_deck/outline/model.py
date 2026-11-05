"""The outline as the outline page shows it: sections in paper order, each a chain of numbered items, their tasks,
evidence and writing, branches (forks), and what the current phase still lacks. Read-only; outline/ops.py writes.

On the map (one copy, no separate outline file):
  section  sec.<key>   facets: order (int; only sections with one belong to the outline; paper sync also makes
                       sections, from the .tex anchors), phase (idea|insight|design|evaluation|summary), role (prose),
                       chain, chain_notes
  claim    claim.<id>  an item. facets: text (prose), chain (its sub-items), chain_notes, fork ({directions: [ids],
                       chosen: id|null}), derived (true: argued, needs no task), summary_of ([item ids]: a summary
                       section's item follows the items it sums up), condition (prose)
  chain        [[id], [id, id], …]: steps in order; a step with several ids is a group of parallel items
  chain_notes  {"<step index>": "…"}: what a parallel group is ("two components"); without one, "together lead to
               the next item"
Edges of an item (evidence, basis, cites) point at what backs it: experiment outputs, findings, designs, references.

Numbers: sections 1…n in order; items <section>.<i>, sub-items <item>.<j>; a fork's directions are "direction 1, 2…"
of the fork item, and each direction numbers its own sub-items under the fork item's number.

An item holds when it is derived or all its tasks are done (or, without tasks, all its evidence is confirmed), and
its live sub-items hold; a fork holds when its chosen direction does; a summary item holds when the items it sums up
do. Phases: an item is in its section's phase; a task in the earliest phase of the items it serves; under the stage
rules a task of a phase the project has not reached waits ("locked").
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..dag import stages
from ..dag.model import DEAD, edges, facet_value, ref_id, title_of
from ..projects import research_dir
from ..util import read_json, write_json
from . import tasks as task_store
from .templates import DEFAULT_PHASES, PHASES

PHASE_INDEX = {p: i for i, p in enumerate(PHASES)}
SEVERITY = ("blocked", "choose", "doing", "todo", "locked", "needs_tasks", "pending")
LOOSE_KINDS = ("finding", "experiment", "figure")


def meta_path(pid: str):
    return research_dir(pid) / "outline" / "meta.json"


def meta(pid: str) -> dict:
    m = read_json(meta_path(pid), None) or {}
    phases = {p: (m.get("phases") or {}).get(p) or DEFAULT_PHASES[p] for p in PHASES}
    return {"template": m.get("template"), "phases": phases}


def save_meta(pid: str, template: str | None, phases: dict | None) -> None:
    p = meta_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json(p, {"template": template, "phases": phases or DEFAULT_PHASES})


def chain_of(n: dict) -> list[list[str]]:
    v = facet_value(n, "chain") or []
    return [[i for i in step if isinstance(i, str)] for step in v if isinstance(step, list)] if isinstance(v, list) else []


def fork_of(n: dict) -> dict | None:
    v = facet_value(n, "fork")
    if not isinstance(v, dict) or not isinstance(v.get("directions"), list):
        return None
    return {"directions": [d for d in v["directions"] if isinstance(d, str)], "chosen": v.get("chosen")}


def outline_sections(st) -> list[dict]:
    secs = [n for n in st.nodes.values() if n.get("kind") == "section" and isinstance(facet_value(n, "order"), int)
            and n.get("status") not in DEAD]
    return sorted(secs, key=lambda n: (facet_value(n, "order"), n["id"]))


def _worst(states: list[str]) -> str | None:
    for s in SEVERITY:
        if s in states:
            return s
    return None


class Builder:
    def __init__(self, pid: str, st, project_step: int, mode: str, surveys: dict | None, lang: str):
        self.pid, self.st, self.project_step, self.mode, self.lang = pid, st, project_step, mode, lang
        self.nodes = st.nodes if st is not None else {}
        self.tasks = task_store.load(pid)
        self.surveys = surveys or {}
        self.items: dict[str, dict] = {}            # id -> record (structure first, then state)
        self.phase_of: dict[str, int | None] = {}
        self.written: dict[str, list[dict]] = defaultdict(list)
        for n in self.nodes.values():
            if n.get("kind") == "section" and n.get("status") not in DEAD:
                for e in edges(n, "describes"):
                    if (t := ref_id(e.get("to"))):
                        self.written[t].append({"section": n["id"], "file": facet_value(n, "file")})
        self.open_props = [p for p in (st.store.proposals() if st is not None else []) if p.get("state") in ("open", "needs_rebase")]

    # ------------------------------------------------------------ structure
    def walk_chain(self, chain: list[list[str]], prefix: str, phase: int | None, depth: int, section: str, parent: str,
                   notes: dict) -> list[dict]:
        steps, n = [], 0
        for si, step in enumerate(chain):
            ids = [i for i in step if i in self.nodes and i not in self.items]
            if not ids:
                continue
            recs = []
            for i in ids:
                n += 1
                recs.append(self.walk_item(i, f"{prefix}.{n}", phase, depth, section, parent))
            steps.append({"items": recs, "note": (notes or {}).get(str(si))})
        return steps

    def walk_item(self, nid: str, num: str, phase: int | None, depth: int, section: str, parent: str,
                  direction: int | None = None) -> dict:
        node = self.nodes[nid]
        rec = {"id": nid, "num": num, "depth": depth, "section": section, "parent": parent, "direction": direction,
               "text": facet_value(node, "text") or title_of(node), "status": node.get("status"),
               "derived": bool(facet_value(node, "derived")), "condition": facet_value(node, "condition") or "",
               "summary_of": [i for i in facet_value(node, "summary_of") or [] if isinstance(i, str)]}
        self.items[nid] = rec
        self.phase_of[nid] = phase
        rec["children"] = self.walk_chain(chain_of(node), num, phase, depth + 1, section, nid,
                                          facet_value(node, "chain_notes") or {})
        fork = fork_of(node)
        if fork:
            dirs = []
            for k, d in enumerate(x for x in fork["directions"] if x in self.nodes and x not in self.items):
                dirs.append(self.walk_item(d, num, phase, depth + 1, section, nid, direction=k + 1))
            rec["fork"] = {"directions": dirs, "chosen": fork["chosen"] if fork["chosen"] in self.items else None}
        else:
            rec["fork"] = None
        return rec

    # ------------------------------------------------------------ tasks
    def task_phase(self, t: dict) -> int | None:
        ph = [self.phase_of[i] for i in t.get("items") or [] if i in self.phase_of and self.phase_of[i] is not None]
        return min(ph) if ph else None

    def task_records(self) -> list[dict]:
        out = []
        for t in self.tasks:
            status, note = task_store.effective(t, self.st, self.surveys)
            phase = self.task_phase(t)
            live = [i for i in t.get("items") or [] if i in self.items and self.items[i]["status"] not in DEAD]
            locked = (self.mode != "free" and phase is not None and phase > self.project_step and status == "todo")
            out.append({**t, "status": "locked" if locked else status, "set_status": t.get("status"), "note": note,
                        "phase": PHASES[phase] if phase is not None else None,
                        "nums": [self.items[i]["num"] for i in t.get("items") or [] if i in self.items],
                        "abandoned": bool(t.get("items")) and not live})
        return out

    # ------------------------------------------------------------ state
    def evidence(self, nid: str) -> list[dict]:
        node, out = self.nodes[nid], []
        for e in edges(node, "evidence", "basis", "cites"):
            t = ref_id(e.get("to"))
            m = self.nodes.get(t) if t else None
            if not m or t in self.items:
                continue
            ev = self.st.E.get(t) if self.st is not None else None
            out.append({"id": t, "kind": m.get("kind"), "rel": e.get("type"), "title": title_of(m), "status": m.get("status"),
                        "level": ev.level if ev is not None else None})
        return out

    def settle(self, rec: dict, task_by_item: dict[str, list[dict]]) -> str:
        kids = [r for step in rec["children"] for r in step["items"]]
        for k in kids:
            self.settle(k, task_by_item)
        if rec["fork"]:
            for d in rec["fork"]["directions"]:
                self.settle(d, task_by_item)
        rec["tasks"] = [t["id"] for t in task_by_item.get(rec["id"], []) if t["status"] != "sugg"]
        rec["suggested"] = [t["id"] for t in task_by_item.get(rec["id"], []) if t["status"] == "sugg"]
        rec["evidence"] = self.evidence(rec["id"])
        rec["written"] = self.written.get(rec["id"], [])
        rec["proposals"] = [p["id"] for p in self.open_props if any(
            (o.get("node") == rec["id"]) or (isinstance(o.get("node"), dict) and o["node"].get("id") == rec["id"]) for o in p.get("ops") or [])]
        live_kids = [k for k in kids if k["state"] not in ("abandoned", "proposed")]
        rec["kids"] = {"total": len(live_kids), "holds": sum(k["state"] == "holds" for k in live_kids)}
        if rec["status"] in DEAD:
            rec["state"] = "abandoned"
            return rec["state"]
        own = self.own_state(rec, task_by_item)
        if own == "holds" and live_kids and rec["kids"]["holds"] < len(live_kids):
            # its own part is done: it is under way, unless something below is stuck or waits for a choice
            below = _worst([k["state"] for k in live_kids])
            own = below if below in ("blocked", "choose") else "doing"
        rec["state"] = "proposed" if rec["status"] == "proposed" else own
        return rec["state"]

    def own_state(self, rec: dict, task_by_item: dict[str, list[dict]]) -> str:
        if rec["summary_of"]:
            targets = [self.items[i] for i in rec["summary_of"] if i in self.items]
            return "holds" if targets and all(t.get("state") == "holds" for t in targets) else "pending"
        if rec["fork"]:
            live = [d for d in rec["fork"]["directions"] if d["state"] != "abandoned"]
            chosen = next((d for d in live if d["id"] == rec["fork"]["chosen"]), None)
            if chosen:
                return chosen["state"]
            return "choose" if live else "needs_tasks"
        if rec["derived"]:
            return "holds"
        ts = [t for t in task_by_item.get(rec["id"], []) if t["status"] != "sugg"]
        if not ts:
            ev = [e for e in rec["evidence"] if e["status"] not in DEAD]
            if not ev:
                return "needs_tasks"
            return "holds" if all(e["status"] in ("confirmed", "locked") for e in ev) else "todo"
        states = [t["status"] for t in ts]
        if all(s == "done" for s in states):
            return "holds"
        return _worst(states) or "todo"

    # ------------------------------------------------------------ the whole outline
    def build(self, phases: dict, template: str | None) -> dict:
        sections = []
        secs = outline_sections(self.st) if self.st is not None else []
        for k, s in enumerate(secs, 1):
            ph = facet_value(s, "phase")
            phase = PHASE_INDEX.get(ph) if ph in PHASE_INDEX else None
            steps = self.walk_chain(chain_of(s), str(k), phase, 0, s["id"], s["id"], facet_value(s, "chain_notes") or {})
            sections.append({"id": s["id"], "num": str(k), "title": s.get("title") or {}, "role": facet_value(s, "role") or "",
                             "phase": ph if ph in PHASE_INDEX or ph == "summary" else "summary", "status": s.get("status"),
                             "items": steps})
        task_recs = self.task_records()
        by_item: dict[str, list[dict]] = defaultdict(list)
        for t in task_recs:
            for i in t.get("items") or []:
                by_item[i].append(t)
        # summary items follow other items: settle the body first
        for sec in sorted(sections, key=lambda s: s["phase"] == "summary"):
            for step in sec["items"]:
                for rec in step["items"]:
                    self.settle(rec, by_item)
        for sec in sections:
            tops = [r for step in sec["items"] for r in step["items"] if r["state"] not in ("abandoned", "proposed")]
            sec["counts"] = {"items": len(tops), "holds": sum(r["state"] == "holds" for r in tops)}
        return {"has_outline": bool(sections), "template": template, "phases": phases,
                "project_phase": PHASES[min(self.project_step, len(PHASES) - 1)], "stage_mode": self.mode,
                "sections": sections, "groups": self.groups(sections, task_recs), "tasks": task_recs,
                "counts": self.counts(task_recs), "pending": self.pending(task_recs), "loose": self.loose(task_recs)}

    def groups(self, sections: list[dict], task_recs: list[dict]) -> list[dict]:
        out = []
        for key in (*PHASES, "summary"):
            secs = [s for s in sections if s["phase"] == key]
            if not secs:
                continue
            tops = [r for s in secs for step in s["items"] for r in step["items"] if r["state"] not in ("abandoned", "proposed")]
            idx = PHASE_INDEX.get(key)
            ts = [t for t in task_recs if t.get("phase") == key and t["status"] != "sugg" and not t["abandoned"]]
            state = "summary" if idx is None else "done" if idx < self.project_step else "current" if idx == self.project_step else "later"
            out.append({"phase": key, "sections": [s["id"] for s in secs], "state": state,
                        "items": len(tops), "holds": sum(r["state"] == "holds" for r in tops),
                        "tasks": len(ts), "tasks_done": sum(t["status"] == "done" for t in ts),
                        "missing": [r["num"] for r in tops if r["state"] != "holds"]})
        return out

    def counts(self, task_recs: list[dict]) -> dict:
        live = [t for t in task_recs if t["status"] != "sugg" and not t["abandoned"]]
        c = {k: sum((t["status"] in ("todo", "locked")) if k == "todo" else (t["status"] == k) for t in live)
             for k in ("done", "doing", "todo", "blocked")}
        return {**c, "total": len(live), "abandoned": sum(t["abandoned"] for t in task_recs if t["status"] != "sugg"),
                "suggested": sum(t["status"] == "sugg" for t in task_recs)}

    def pending(self, task_recs: list[dict]) -> list[dict]:
        out = []
        for rec in self.items.values():
            if rec.get("state") == "choose":
                out.append({"kind": "fork", "item": rec["id"], "num": rec["num"], "text": rec["text"]})
            elif rec.get("state") == "proposed" and rec["direction"] is None:
                out.append({"kind": "proposed_item", "item": rec["id"], "num": rec["num"], "text": rec["text"]})
        for t in task_recs:
            if t["status"] == "blocked" and not t["abandoned"]:
                out.append({"kind": "blocked_task", "task": t["id"], "title": t["title"], "note": t["note"], "nums": t["nums"]})
            elif t["status"] == "sugg":
                out.append({"kind": "suggested_task", "task": t["id"], "title": t["title"], "nums": t["nums"]})
        for p in self.open_props:
            out.append({"kind": "proposal", "proposal": p["id"], "title": p.get("title") or p["id"]})
        return out

    def loose(self, task_recs: list[dict]) -> list[dict]:
        linked = {e["id"] for r in self.items.values() for e in r.get("evidence") or []}
        linked |= {(t.get("links") or {}).get("node") for t in task_recs}
        out = []
        for n in self.nodes.values():
            if n.get("kind") not in LOOSE_KINDS or n["id"] in linked or n.get("status") in DEAD:
                continue
            # a result: a confirmed finding or figure, or an experiment that has run
            ran = n.get("kind") == "experiment" and bool(self.st.runs.by_node.get(n["id"]))
            if ran or n.get("status") in ("confirmed", "locked"):
                out.append({"id": n["id"], "kind": n["kind"], "title": title_of(n), "status": n["status"]})
        return sorted(out, key=lambda x: x["id"])


def build(pid: str, lang: str = "zh") -> dict:
    """The outline of a project (an empty one when it has none yet, or no map)."""
    from ..dag.evaluate import current
    from ..dag.service import store_for
    m = meta(pid)
    try:
        store = store_for(pid)
        st = current(store) if (store.root / store.state / "dag").exists() else None
        step, mode = stages.project_step(store), stages.mode(store.config())
    except Exception:  # noqa: BLE001 — a project without a usable map has an empty outline
        st, step, mode = None, 0, "strict"
    surveys = {}
    try:
        d = research_dir(pid) / "survey"
        for p in d.glob("sv-*.json") if d.is_dir() else []:
            s = read_json(p, None)
            if isinstance(s, dict) and s.get("id"):
                surveys[s["id"]] = s
    except OSError:
        pass
    return Builder(pid, st, step, mode, surveys, lang).build(m["phases"], m["template"])
