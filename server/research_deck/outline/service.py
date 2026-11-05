"""Writing the outline: apply outline ops (outline/ops.py) as one batch of map ops, create an outline from a template
(with the items of a structured draft), and keep the tasks pointing at the right items. Every change publishes topic
"outline" (and "dag", through the map)."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..actors import is_human
from ..dag import ops as dag_ops
from ..dag.evaluate import current
from ..dag.service import publish, store_for
from ..events import hub
from ..util import slugify
from . import model, templates
from . import tasks as task_store
from .ops import OutlineError, Plan


def _fail(e: Exception) -> HTTPException:
    if isinstance(e, OutlineError):
        return HTTPException(e.status, e.message)
    if isinstance(e, dag_ops.OpError):
        return HTTPException(e.status, e.payload)
    raise e


# What an agent may do to the outline at once: add items (they come in as proposed, dashed). Rewording, moving,
# removing, forking and choosing become a proposal the researcher approves, so their words never change unseen.
AGENT_DIRECT = {"add_item", "add_direction", "set_note", "attach_item", "link"}


def _commit(pid: str, plan: Plan, actor: str, title: str, kinds: set[str] | None = None) -> dict:
    store = store_for(pid)
    ops = plan.dag_ops()
    result: dict[str, Any] = {"applied": True, "created": list(plan.created), "last": plan.last_created}
    if ops:
        try:
            if is_human(actor):
                _, events = dag_ops.apply_ops(store, ops, actor)
                result["events"] = len(events)
            elif kinds is not None and not kinds <= AGENT_DIRECT:
                prop = dag_ops.create_proposal(store, title, None, ops, actor)
                result.update(applied=False, proposal=prop["id"], created=[])
                plan.retarget = {}
            else:
                res = dag_ops.submit(store, ops, actor, title=title)
                result["applied"] = bool(res.get("applied"))
                result["proposal"] = (res.get("proposal") or {}).get("id")
        except dag_ops.OpError as e:
            raise _fail(e)
        publish(pid, store, set(plan.created) | {o.get("node") for o in ops if isinstance(o.get("node"), str)})
    for old, new in plan.retarget.items():
        for t in task_store.load(pid):
            if old in (t.get("items") or []):
                task_store.update(pid, t["id"], {"items": [new if i == old else i for i in t["items"]]})
    hub.publish(pid, "outline", {"changed": result["created"]})
    return result


def apply(pid: str, ops: list[dict], actor: str, lang: str = "zh") -> dict:
    if not isinstance(ops, list) or not ops:
        raise HTTPException(400, "ops must be a non-empty list")
    store = store_for(pid)
    store.ensure()
    plan = Plan(current(store).nodes, is_human(actor), lang)
    try:
        for op in ops:
            plan.apply(op)
    except OutlineError as e:
        raise _fail(e)
    return _commit(pid, plan, actor, title="Outline: " + ", ".join(str(o.get("op")) for o in ops[:4]),
                   kinds={str(o.get("op")) for o in ops})


def _add_items(plan: Plan, parent: str, steps: list, notes: dict | None = None) -> None:
    """Items of a structured draft under `parent`: steps of {text, children, derived} (a step: one item or a list)."""
    for step in steps or []:
        group = step if isinstance(step, list) else [step]
        first = None
        for spec in group:
            if not isinstance(spec, dict) or not str(spec.get("text") or "").strip():
                continue
            at = {"parallel": first} if first else None
            plan.op_add_item({"parent": parent, "text": spec["text"], "derived": spec.get("derived"), **({"at": at} if at else {})})
            nid = plan.last_created
            first = first or nid
            if spec.get("children"):
                _add_items(plan, nid, spec["children"], spec.get("notes"))
    for k, v in (notes or {}).items():
        plan.op_set_note({"parent": parent, "step": int(k), "text": v})


def init(pid: str, template_id: str, actor: str, lang: str = "zh", structure: dict | None = None) -> dict:
    """A new outline from a template; `structure` ({sections: [{key?, title, role?, items, notes?}]}) fills in items."""
    t = templates.get(template_id)
    store = store_for(pid)
    store.ensure()
    st = current(store)
    if model.outline_sections(st):
        raise HTTPException(409, "this project already has an outline")
    plan = Plan(st.nodes, is_human(actor), lang)
    by_key: dict[str, str] = {}
    try:
        for s in t["sections"]:
            plan.op_add_section({"key": s["key"], "title": s["title"], "role": s["role"].get(lang) or s["role"]["en"],
                                 "phase": s["phase"]})
            by_key[s["key"]] = plan.last_section
        last = None
        for spec in (structure or {}).get("sections") or []:
            key = spec.get("key")
            sid = by_key.get(key) if key else None
            if sid is None:
                title = str(spec.get("title") or "").strip()
                match = next((k for k, s in ((s["key"], s) for s in t["sections"])
                              if title and title.lower() in (s["title"]["zh"].lower(), s["title"]["en"].lower())), None)
                sid = by_key.get(match) if match else None
            if sid is None:
                plan.op_add_section({"key": slugify(str(spec.get("title") or ""), "")[:40].strip("-"),
                                     "title": spec.get("title") or "…", "role": spec.get("role") or "",
                                     "phase": spec.get("phase") if spec.get("phase") in templates.SECTION_PHASES else "insight",
                                     "after": last})
                sid = plan.last_section
            last = sid
            _add_items(plan, sid, spec.get("items") or [], spec.get("notes"))
    except OutlineError as e:
        raise _fail(e)
    model.save_meta(pid, t["id"], t["phases"])
    return _commit(pid, plan, actor, title=f"Outline from template {t['id']}")


def save_as_template(pid: str, tid: str, name: str, lang: str = "zh") -> dict:
    """The project's sections (titles, roles, phases) as a user template."""
    st = current(store_for(pid))
    secs = model.outline_sections(st)
    if not secs:
        raise HTTPException(409, "this project has no outline yet")
    from ..dag.model import facet_value
    sections = []
    for s in secs:
        key = s["id"].split(".", 1)[1]
        title = s.get("title") or {}
        sections.append({"key": key[:40], "title": {"zh": title.get("zh") or title.get("en") or key, "en": title.get("en") or title.get("zh") or key},
                         "role": facet_value(s, "role") or "", "phase": facet_value(s, "phase") or "insight"})
    m = model.meta(pid)
    return templates.save({"id": tid, "name": name, "description": name, "phases": m["phases"], "sections": sections})
