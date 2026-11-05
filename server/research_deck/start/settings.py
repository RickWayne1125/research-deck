"""Settings for new projects, kept with the user's other machine-local defaults in ~/.research-deck/settings.json:

    {"new_projects": {"dir": "~/Research", "git_init": true,
                      "survey": {"sources": ["arxiv", "semantic_scholar", "openalex"], "count": 15,
                                 "download_pdfs": true, "papers_dir": "papers"}},
     "dag_defaults": {"stages": {"mode": "strict"}}}

The default folder depends on the system (macOS ~/Research, Linux ~/research, Windows %USERPROFILE%\\Research).
update() writes only these keys and keeps everything else in the file as it is.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from .. import config
from ..util import write_json

SOURCES = ("arxiv", "semantic_scholar", "openalex")
STAGE_MODES = ("strict", "ahead", "free")
DEFAULTS: dict[str, Any] = {
    "git_init": True,
    "survey": {"sources": list(SOURCES), "count": 15, "download_pdfs": True, "papers_dir": "papers"},
}


def default_dir(platform: str | None = None) -> str:
    """The folder new projects go to when the user has not chosen one, as the user would type it."""
    p = platform or sys.platform
    if p.startswith("win"):
        return "%USERPROFILE%\\Research"
    if p == "darwin":
        return "~/Research"
    return "~/research"


def expand(path: str) -> Path:
    """~ and %USERPROFILE% (and other environment variables) expanded."""
    import os
    return Path(os.path.expandvars(os.path.expanduser(path)))


def _raw() -> dict:
    try:
        data = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def new_projects() -> dict:
    """The effective settings for new projects (defaults filled in) plus where the default folder points to now."""
    mine = config.user_settings().get("new_projects") or {}
    out = copy.deepcopy(DEFAULTS)
    out["dir"] = str(mine.get("dir") or "") or default_dir()
    if isinstance(mine.get("git_init"), bool):
        out["git_init"] = mine["git_init"]
    survey = mine.get("survey") or {}
    if isinstance(survey.get("sources"), list):
        out["survey"]["sources"] = [s for s in survey["sources"] if s in SOURCES]
    if isinstance(survey.get("count"), int) and 1 <= survey["count"] <= 60:
        out["survey"]["count"] = survey["count"]
    if isinstance(survey.get("download_pdfs"), bool):
        out["survey"]["download_pdfs"] = survey["download_pdfs"]
    if isinstance(survey.get("papers_dir"), str) and _ok_rel(survey["papers_dir"]):
        out["survey"]["papers_dir"] = survey["papers_dir"].strip("/")
    stages = ((config.user_settings().get("dag_defaults") or {}).get("stages") or {}).get("mode")
    out["stage_mode"] = stages if stages in STAGE_MODES else "strict"
    out["default_dir"] = default_dir()
    out["dir_expanded"] = str(expand(out["dir"]))
    return out


def _ok_rel(p: str) -> bool:
    p = p.strip().strip("/")
    return bool(p) and not p.startswith(".") and ".." not in p.split("/") and "\\" not in p and len(p) <= 80


def update(change: dict) -> dict:
    """Write the allowed keys of `change` ({dir?, git_init?, survey?: {...}, stage_mode?}); None resets a key."""
    data = _raw()
    mine = dict(data.get("new_projects") or {})
    if "dir" in change:
        d = change["dir"]
        if d in (None, ""):
            mine.pop("dir", None)
        elif not isinstance(d, str) or len(d) > 400:
            raise ValueError("dir must be a path")
        else:
            mine["dir"] = d.strip()
    if "git_init" in change:
        if not isinstance(change["git_init"], bool):
            raise ValueError("git_init must be true or false")
        mine["git_init"] = change["git_init"]
    if isinstance(change.get("survey"), dict):
        survey = dict(mine.get("survey") or {})
        s = change["survey"]
        if "sources" in s:
            if not isinstance(s["sources"], list) or any(x not in SOURCES for x in s["sources"]):
                raise ValueError(f"sources must be some of {', '.join(SOURCES)}")
            survey["sources"] = list(s["sources"])
        if "count" in s:
            if not isinstance(s["count"], int) or not 1 <= s["count"] <= 60:
                raise ValueError("count must be between 1 and 60")
            survey["count"] = s["count"]
        if "download_pdfs" in s:
            if not isinstance(s["download_pdfs"], bool):
                raise ValueError("download_pdfs must be true or false")
            survey["download_pdfs"] = s["download_pdfs"]
        if "papers_dir" in s:
            if not isinstance(s["papers_dir"], str) or not _ok_rel(s["papers_dir"]):
                raise ValueError("papers_dir must be a folder inside the project, e.g. papers")
            survey["papers_dir"] = s["papers_dir"].strip().strip("/")
        mine["survey"] = survey
    data["new_projects"] = mine
    if "stage_mode" in change:
        if change["stage_mode"] not in STAGE_MODES:
            raise ValueError(f"stage_mode must be one of {', '.join(STAGE_MODES)}")
        dag = dict(data.get("dag_defaults") or {})
        dag["stages"] = {**(dag.get("stages") or {}), "mode": change["stage_mode"]}
        data["dag_defaults"] = dag
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(config.SETTINGS_FILE, data)
    config._SETTINGS_CACHE = (-1.0, {})
    return new_projects()
