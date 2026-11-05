"""Visualization routes (docs/API.md § Visualization): style tokens, the figure registry, rendering, previews, AI edits
and the native apps.

Besides the documented routes this package adds:
  PUT    /api/projects/{pid}/style            partial {active_palette?, font?, series?, roles?}; null removes a key
  GET    /api/projects/{pid}/figures/discover unregistered figure files in the figures/paper folders
  GET    /api/projects/{pid}/figures/{fid}    one Figure
  DELETE /api/projects/{pid}/figures/{fid}    forget a figure (its files stay on disk)
"""
from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..events import hub
from ..projects import project_root, research_dir
from ..util import rel_to, safe_join, write_json
from . import agent, figures, native, render, style

router = APIRouter(tags=["viz"])

MAX_PREVIEW_BYTES = 16 * 1024 * 1024
# Previews are shown in <img>; if one is opened directly, nothing in it may run.
PREVIEW_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:",
}


# ---------------------------------------------------------------- style

@router.get("/api/style")
def get_style(project: str | None = Query(None)):
    return style.tokens(research_dir(project) if project else None)


class StyleChange(BaseModel):
    active_palette: str | None = None
    font: dict | None = None
    series: list[str] | None = None
    roles: dict | None = None


@router.put("/api/projects/{pid}/style")
def put_style(pid: str, body: dict):
    """Merge a partial override into .research/style.json (a key set to null is removed), regenerate the helper."""
    change = StyleChange.model_validate(body)   # validates the shape; `body` keeps explicit nulls
    rd = research_dir(pid)
    current = style.load_override(rd)
    ids = {p["id"] for p in style.builtin_tokens()["palettes"]}
    for key in ("active_palette", "font", "series", "roles"):
        if key not in body:
            continue
        value = getattr(change, key)
        if value is None:
            current.pop(key, None)
        elif key == "active_palette":
            if value not in ids:
                raise HTTPException(400, f"unknown palette: {value}")
            current[key] = value
        elif key == "series":
            bad = [s for s in value if not style.HEX.match(s)]
            if bad:
                raise HTTPException(400, f"not a #RRGGBB color: {', '.join(bad)}")
            current[key] = [s.upper() for s in value]
        elif key == "font":
            merged = {**(current.get("font") or {}), **value}
            current[key] = {k: v for k, v in merged.items() if v is not None}
        else:
            current[key] = value
    write_json(style.override_path(rd), current)
    tok = style.tokens(rd)
    figures.ensure_helper(pid, tok)
    hub.publish(pid, "figures", {"action": "style", "active_palette": tok["active_palette"]})
    return tok


# ---------------------------------------------------------------- registry

class NewFigure(BaseModel):
    kind: str
    title: str = ""
    node_id: str | None = None
    caption: str | None = None
    source: str | None = None     # register an existing file instead of creating one from a template


class FigurePatch(BaseModel):
    title: str | None = None
    caption: str | None = None
    node_id: str | None = None
    source: str | None = None
    data: list[str] | None = None


@router.get("/api/projects/{pid}/figures")
def list_figures(pid: str):
    return figures.list_views(pid)


@router.get("/api/projects/{pid}/figures/discover")
def discover_figures(pid: str):
    return figures.discover(pid)


@router.post("/api/projects/{pid}/figures")
def create_figure(pid: str, body: NewFigure):
    entry = figures.create(pid, kind=body.kind, title=body.title, node_id=body.node_id, source=body.source,
                           caption=body.caption)
    hub.publish(pid, "figures", {"id": entry["id"], "action": "created"})
    return figures.view(pid, entry)


@router.get("/api/projects/{pid}/figures/{fid}")
def get_figure(pid: str, fid: str):
    return figures.view(pid, figures.get_entry(pid, fid))


@router.patch("/api/projects/{pid}/figures/{fid}")
def patch_figure(pid: str, fid: str, body: dict):
    patch = FigurePatch.model_validate(body)
    root = project_root(pid)
    changes: dict = {}
    for key in ("title", "caption", "node_id"):
        if key in body:
            value = getattr(patch, key)
            changes[key] = (value or "").strip() or (None if key == "node_id" else "")
    if "title" in changes and not changes["title"]:
        raise HTTPException(400, "a figure needs a title")
    if patch.source is not None:
        target = safe_join(root, patch.source)
        if not target.exists():
            raise HTTPException(404, f"no such file: {patch.source}")
        changes["source"] = rel_to(root, target)
    if patch.data is not None:
        changes["data"] = [rel_to(root, safe_join(root, rel)) for rel in patch.data if rel.strip()]
    entry = figures.update_entry(pid, fid, changes)
    hub.publish(pid, "figures", {"id": fid, "action": "updated"})
    return figures.view(pid, entry)


@router.delete("/api/projects/{pid}/figures/{fid}")
def delete_figure(pid: str, fid: str):
    figures.remove_entry(pid, fid)
    hub.publish(pid, "figures", {"id": fid, "action": "removed"})
    return {"ok": True}


# ---------------------------------------------------------------- rendering and previews

class RenderBody(BaseModel):
    source: str | None = None


@router.post("/api/projects/{pid}/figures/{fid}/render")
def render_figure(pid: str, fid: str, body: RenderBody | None = None):
    return render.render(pid, fid, (body.source if body else None))


class PreviewBody(BaseModel):
    svg: str | None = None
    png_base64: str | None = None


_SCRIPT_RE = re.compile(r"<script\b[\s\S]*?</script\s*>|<script\b[^>]*/>", re.I)


def _decode_svg(svg: str) -> str:
    """Accept SVG text or the data URI draw.io's export hands back."""
    s = svg.strip()
    if s.startswith("data:image/svg+xml;base64,"):
        try:
            s = base64.b64decode(s.split(",", 1)[1]).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise HTTPException(400, "not a valid SVG data URI")
    elif s.startswith("data:image/svg+xml"):
        s = unquote(s.split(",", 1)[1] if "," in s else "")
    if "<svg" not in s:
        raise HTTPException(400, "not an SVG document")
    # draw.io exports light-dark() colors with `color-scheme: light dark`; a paper figure's preview stays light.
    s = re.sub(r"color-scheme:\s*light\s+dark", "color-scheme: light", s, count=1)
    return _SCRIPT_RE.sub("", s)


@router.put("/api/projects/{pid}/figures/{fid}/preview")
def put_preview(pid: str, fid: str, body: PreviewBody):
    entry = figures.get_entry(pid, fid)
    previews = figures.previews_dir(pid)
    if body.svg:
        data = _decode_svg(body.svg).encode("utf-8")
        ext = ".svg"
    elif body.png_base64:
        b64 = body.png_base64.split(",", 1)[1] if body.png_base64.startswith("data:") else body.png_base64
        try:
            data = base64.b64decode(b64, validate=False)
        except binascii.Error:
            raise HTTPException(400, "png_base64 is not base64")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(400, "not a PNG image")
        ext = ".png"
    else:
        raise HTTPException(400, "send svg or png_base64")
    if len(data) > MAX_PREVIEW_BYTES:
        raise HTTPException(413, "preview too large")
    tmp = previews / f".{fid}.upload{ext}"
    tmp.write_bytes(data)
    for other in figures.PREVIEW_EXTS:
        (previews / f"{fid}{other}").unlink(missing_ok=True)
    tmp.replace(previews / f"{fid}{ext}")
    figures.record_render(pid, fid, ok=True, sig=figures.signature(pid, entry))
    hub.publish(pid, "figures", {"id": fid, "action": "preview"})
    return figures.view(pid, entry)


@router.get("/api/projects/{pid}/figures/{fid}/preview")
def get_preview(pid: str, fid: str):
    figures.get_entry(pid, fid)
    path = figures.preview_file(pid, fid)
    if not path:
        raise HTTPException(404, "no preview yet")
    media = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    return FileResponse(path, media_type=media, headers=PREVIEW_HEADERS)


# ---------------------------------------------------------------- AI edits and native apps

class AiEditBody(BaseModel):
    instruction: str
    source: str | None = None


@router.post("/api/projects/{pid}/figures/{fid}/ai-edit")
def ai_edit(pid: str, fid: str, body: AiEditBody):
    return agent.start_edit(pid, fid, body.instruction, body.source)


@router.post("/api/projects/{pid}/figures/{fid}/open-native")
def open_native(pid: str, fid: str):
    return native.open_native(pid, fid)


@router.post("/api/projects/{pid}/figures/{fid}/export-native")
def export_native(pid: str, fid: str):
    return native.export_native(pid, fid)
