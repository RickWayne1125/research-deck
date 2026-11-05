"""Outline routes (docs/API.md § Outline).

GET    /api/projects/{pid}/outline                 the outline as the page shows it (outline/model.py)
POST   /api/projects/{pid}/outline/ops             {ops: [outline op…], lang?}: applied in one batch (agents: proposals)
POST   /api/projects/{pid}/outline/init            {template, lang?, structure?}: a new outline from a template
POST   /api/projects/{pid}/outline/structure       {text, template, lang?, agent?}: a structured draft (nothing written)
POST   /api/projects/{pid}/outline/save-template   {id, name}: the project's sections as a user template
POST   /api/projects/{pid}/outline/extract         {name, content_base64}: the text of an uploaded PDF outline
GET    /api/projects/{pid}/tasks                   the tasks as stored
POST   /api/projects/{pid}/tasks                   {type, title, items, status?, note?, assignee?, links?}
PATCH  /api/projects/{pid}/tasks/{tid}             any of those fields
DELETE /api/projects/{pid}/tasks/{tid}
GET    /api/outline/templates                      every template; GET /api/outline/templates/{id} one
PUT    /api/outline/templates/{id}                 save a user template; DELETE removes a user template
Changing the outline, tasks or templates is the researcher's (403 for agents), except outline ops, which an agent
submits as proposals, and tasks, which an agent adds as suggestions (status "sugg") for the researcher to take.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import actors
from ..agents import runner
from ..events import hub
from . import model, service, structure, templates
from . import tasks as task_store

router = APIRouter(tags=["outline"])
runner.register_fake("outline-structure", structure.fake_answer)


def _human(request: Request) -> str:
    actor = actors.actor_of(request)
    if not actors.is_human(actor):
        raise HTTPException(403, "only the researcher changes this")
    return actor


@router.get("/api/projects/{pid}/outline")
def get_outline(pid: str, lang: str = "zh"):
    return model.build(pid, "en" if lang == "en" else "zh")


class OpsBody(BaseModel):
    ops: list[dict]
    lang: str = "zh"


@router.post("/api/projects/{pid}/outline/ops")
def post_ops(pid: str, body: OpsBody, request: Request):
    return service.apply(pid, body.ops, actors.actor_of(request), "en" if body.lang == "en" else "zh")


class InitBody(BaseModel):
    template: str = "systems"
    lang: str = "zh"
    structure: dict | None = None


@router.post("/api/projects/{pid}/outline/init")
def post_init(pid: str, body: InitBody, request: Request):
    return service.init(pid, body.template, _human(request), "en" if body.lang == "en" else "zh", body.structure)


class StructureBody(BaseModel):
    text: str
    template: str = "systems"
    lang: str = "zh"
    agent: bool = True


@router.post("/api/projects/{pid}/outline/structure")
def post_structure(pid: str, body: StructureBody, request: Request):
    _human(request)
    if not body.text.strip():
        raise HTTPException(400, "paste or upload the outline first")
    return structure.tidy(pid, body.text, templates.get(body.template), "en" if body.lang == "en" else "zh", body.agent)


class SaveTemplateBody(BaseModel):
    id: str
    name: str


@router.post("/api/projects/{pid}/outline/save-template")
def post_save_template(pid: str, body: SaveTemplateBody, request: Request):
    _human(request)
    return service.save_as_template(pid, body.id, body.name)


class ExtractBody(BaseModel):
    name: str
    content_base64: str


@router.post("/api/projects/{pid}/outline/extract")
def post_extract(pid: str, body: ExtractBody, request: Request):
    """A PDF's text, for the outline box (the page reads .md, .tex and .txt itself)."""
    import base64
    import binascii

    from ..start.create import MAX_UPLOAD, pdf_text
    _human(request)
    if not body.name.lower().endswith(".pdf"):
        raise HTTPException(400, "only a .pdf needs extracting")
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "the file is not valid base64")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"files up to {MAX_UPLOAD // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "this .pdf is not a PDF")
    text = pdf_text(data)
    if not text:
        raise HTTPException(422, "this PDF has no text layer")
    return {"text": text}


# ---------------------------------------------------------------- tasks

@router.get("/api/projects/{pid}/tasks")
def get_tasks(pid: str):
    return task_store.load(pid)


@router.post("/api/projects/{pid}/tasks")
def post_task(pid: str, body: dict, request: Request):
    actor = actors.actor_of(request)
    data = dict(body)
    if not actors.is_human(actor):
        data["status"] = "sugg"                   # an agent suggests; the researcher takes it
    t = task_store.create(pid, data, actor)
    hub.publish(pid, "outline", {"task": t["id"]})
    return t


@router.patch("/api/projects/{pid}/tasks/{tid}")
def patch_task(pid: str, tid: str, body: dict, request: Request):
    _human(request)
    t = task_store.update(pid, tid, body)
    hub.publish(pid, "outline", {"task": tid})
    return t


@router.delete("/api/projects/{pid}/tasks/{tid}")
def delete_task(pid: str, tid: str, request: Request):
    _human(request)
    task_store.remove(pid, tid)
    hub.publish(pid, "outline", {"task": tid})
    return {"ok": True}


# ---------------------------------------------------------------- templates

@router.get("/api/outline/templates")
def list_templates():
    return templates.all_templates()


@router.get("/api/outline/templates/{tid}")
def get_template(tid: str):
    return templates.get(tid)


@router.put("/api/outline/templates/{tid}")
def put_template(tid: str, body: dict, request: Request):
    _human(request)
    return templates.save({**body, "id": tid})


@router.delete("/api/outline/templates/{tid}")
def delete_template(tid: str, request: Request):
    _human(request)
    return {"ok": templates.remove(tid)}
