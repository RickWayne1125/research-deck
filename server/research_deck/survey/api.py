"""Survey routes (docs/API.md § Survey).

GET  /api/projects/{pid}/survey          the project's latest survey, or null
POST /api/projects/{pid}/survey          start one: {idea?, count?, download_pdfs?, sources?}; the idea defaults to
                                         notes/idea.md
POST /api/projects/{pid}/survey/cancel   stop the running one
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import actors, projects
from . import fakes, job

router = APIRouter(tags=["survey"])
fakes.register()


@router.get("/api/projects/{pid}/survey")
def get_survey(pid: str):
    return job.latest(pid)


class StartSurvey(BaseModel):
    idea: str | None = None
    count: int | None = None
    download_pdfs: bool | None = None
    sources: list[str] | None = None


@router.post("/api/projects/{pid}/survey")
def start_survey(pid: str, body: StartSurvey, request: Request):
    actor = actors.actor_of(request)
    if not actors.is_human(actor):           # the survey reaches the network: only the researcher starts it
        raise HTTPException(403, "only the researcher starts a survey")
    idea, idea_file = body.idea, None
    if not (idea or "").strip():
        path = projects.project_root(pid) / "notes" / "idea.md"
        if not path.is_file():
            raise HTTPException(400, "no idea to survey: write notes/idea.md or pass the idea")
        idea, idea_file = path.read_text(encoding="utf-8", errors="replace"), "notes/idea.md"
    return job.start(pid, idea, idea_file=idea_file, count=body.count, download_pdfs=body.download_pdfs,
                     source_list=body.sources, actor=actor)


@router.post("/api/projects/{pid}/survey/cancel")
def cancel_survey(pid: str):
    return {"ok": job.cancel(pid)}
