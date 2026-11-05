"""New-project routes (docs/API.md § New projects).

GET   /api/settings/new-projects   the effective settings for new projects (Settings → New projects)
PATCH /api/settings/new-projects   {dir?, git_init?, survey?: {sources?, count?, download_pdfs?, papers_dir?}, stage_mode?}
POST  /api/projects/new            {name, idea?, file?: {name, content_base64}, folder?, survey?: {enabled, count?,
                                    download_pdfs?}} → {project, root, created, idea_file, upload, survey}
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import actors
from . import create, settings

router = APIRouter(tags=["start"])


def _human(request: Request) -> str:
    actor = actors.actor_of(request)
    if not actors.is_human(actor):
        raise HTTPException(403, "only the researcher changes this")
    return actor


@router.get("/api/settings/new-projects")
def get_settings():
    return settings.new_projects()


@router.patch("/api/settings/new-projects")
def patch_settings(body: dict, request: Request):
    _human(request)
    try:
        return settings.update(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Upload(BaseModel):
    name: str
    content_base64: str


class SurveyOptions(BaseModel):
    enabled: bool = True
    count: int | None = None
    download_pdfs: bool | None = None


class NewProject(BaseModel):
    name: str
    idea: str = ""
    file: Upload | None = None
    folder: str | None = None
    survey: SurveyOptions = SurveyOptions()


@router.post("/api/projects/new")
def new_project(body: NewProject, request: Request):
    actor = _human(request)
    return create.create(body.name, body.idea, body.file.model_dump() if body.file else None, body.folder,
                         body.survey.model_dump(), actor)
