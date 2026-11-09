"""Writing routes (docs/API.md § Writing): documents, the revision pipeline and its findings, glossary, learned rules,
versions and the DAG claims bound to a document.

Besides the documented routes, three conveniences for the panel:
  GET  /writing/reviews?path=                     recent reviews of a document (summaries, newest first)
  POST /writing/review/{review_id}/cancel         stop a running review (the running pass is cancelled)
  POST /writing/findings/{review_id}              {ids, status} decide several findings at once (Fix typos)
A finding's status may also be set back to "open" (undo of an accept or a reject).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..actors import actor_of
from ..events import hub
from ..outline import doc as outline_doc
from . import context, docs, fakes, review, store, versions

router = APIRouter(prefix="/api/projects/{pid}/writing", tags=["writing"])
fakes.register()

Status = Literal["accepted", "rejected", "open"]


# ------------------------------------------------------------------ documents

@router.get("/docs")
def list_docs(pid: str):
    outline_doc.sync(pid)                       # the outline file is there and up to date
    out = []
    for rel in docs.doc_files(pid):
        d = docs.describe(pid, rel, context.claims_for(pid, rel))
        if d:
            out.append(d)
    return out


@router.get("/claims")
def get_claims(pid: str, path: str = Query(...)):
    norm = docs.resolve_doc(pid, path)[1]
    return {"claims": context.claims_for(pid, norm)}


# ------------------------------------------------------------------ reviews

class ReviewRange(BaseModel):
    start_line: int = Field(1, ge=1)
    end_line: int = Field(1, ge=1)


class ReviewBody(BaseModel):
    path: str
    passes: list[str] | None = None      # default: all five, always run in the fixed order
    text: str | None = None              # the editor's text (unsaved changes included); default: the file
    range: ReviewRange | None = None     # check only these lines (the selection)
    lang: str | None = None              # the UI language the reasons are written in (zh | en)


@router.post("/review")
def start_review(pid: str, body: ReviewBody, request: Request):
    return review.start(pid, body.path, body.passes, body.text, body.range.model_dump() if body.range else None,
                        body.lang, actor=actor_of(request))


@router.get("/reviews")
def list_reviews(pid: str, path: str | None = Query(None), limit: int = Query(10, ge=1, le=100)):
    norm = docs.resolve_doc(pid, path)[1] if path else None
    return [review.summary(r) for r in store.list_reviews(pid, norm, limit)]


@router.get("/review/{review_id}")
def get_review(pid: str, review_id: str):
    return review.get(pid, review_id)


@router.post("/review/{review_id}/cancel")
def cancel_review(pid: str, review_id: str):
    return review.cancel(pid, review_id)


class Decision(BaseModel):
    status: Status
    reason: str | None = None


class Decisions(BaseModel):
    ids: list[str]
    status: Status


@router.post("/findings/{review_id}/{finding_id}")
def decide(pid: str, review_id: str, finding_id: str, body: Decision, request: Request):
    return review.decide(pid, review_id, [finding_id], body.status, body.reason, actor_of(request))[0]


@router.post("/findings/{review_id}")
def decide_many(pid: str, review_id: str, body: Decisions, request: Request):
    return review.decide(pid, review_id, list(dict.fromkeys(body.ids)), body.status, None, actor_of(request))


# ------------------------------------------------------------------ glossary and learned rules

class Term(BaseModel):
    term: str = ""
    preferred: str = ""
    avoid: list[str] = []
    note: str | None = ""


class Glossary(BaseModel):
    terms: list[Term]


@router.get("/glossary")
def get_glossary(pid: str):
    return store.load_glossary(pid)


@router.put("/glossary")
def put_glossary(pid: str, body: Glossary):
    out = store.save_glossary(pid, [t.model_dump() for t in body.terms])
    hub.publish(pid, "writing", {"kind": "glossary", "count": len(out["terms"])})
    return out


class Rule(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    id: str | None = None
    pass_: str = Field("all", alias="pass")
    text: str
    on: bool = True
    created_at: str | None = None


class Rules(BaseModel):
    rules: list[Rule]


@router.get("/rules")
def get_rules(pid: str):
    return store.load_rules(pid)


@router.put("/rules")
def put_rules(pid: str, body: Rules):
    out = store.save_rules(pid, [r.model_dump(by_alias=True) for r in body.rules])
    hub.publish(pid, "writing", {"kind": "rules", "count": len(out["rules"])})
    return out


# ------------------------------------------------------------------ versions

class SnapshotBody(BaseModel):
    path: str
    label: str | None = None


@router.get("/versions")
def list_versions(pid: str, path: str = Query(...)):
    return versions.list_versions(pid, path)


@router.post("/versions")
def make_snapshot(pid: str, body: SnapshotBody):
    v = versions.snapshot(pid, body.path, body.label)
    hub.publish(pid, "writing", {"kind": "versions", "path": docs.resolve_doc(pid, body.path)[1]})
    return v


@router.get("/versions/{version_id}")
def get_version(pid: str, version_id: str, path: str = Query(...)):
    return {"content": versions.version_content(pid, path, version_id)}
