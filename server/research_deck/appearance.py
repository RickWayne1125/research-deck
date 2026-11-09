"""Appearance (Settings → Appearance): the Radix Themes theme and the background behind the dashboard, kept with the
user's other machine-local defaults in ~/.research-deck/settings.json, and an uploaded background picture in
~/.research-deck/backgrounds/. Nothing here touches a project.

    {"appearance": {"theme": "radix-red" | "radix-indigo" | "radix-teal" | "custom",
                    "custom": {"accent": <Radix accent>, "radius": "none" | "small" | "medium" | "large" | "full",
                               "background": "radix" | "ribbons" | "gradient" | "glow" | "plain" | "image"},
                    "blur": 0–100,                 # the picture's blur, in % of 40 px
                    "image": "<sha>.<ext>"}}       # the uploaded picture, a file in backgrounds/

The three Radix themes carry their own accent, gray, radius and background (radix-ui.com's art in their palette);
"custom" uses `custom` (its gray follows the accent, as Radix Themes' "auto" gray does; "radix" is the same art in the
accent). Light or dark is chosen per browser; the rest is read on every page load (GET), so all the user's browsers
agree.

GET    /api/settings/appearance          the settings, defaults filled in, `image` a URL or null
PATCH  /api/settings/appearance          {theme?, custom?: {accent?, radius?, background?}, blur?}; null resets a key
PUT    /api/settings/appearance/image    {name, content_base64}: PNG, JPEG, WebP, GIF or AVIF up to 15 MB; the
                                         theme becomes custom with this picture as the background
DELETE /api/settings/appearance/image    forgets the picture (a picture background falls back to the ribbons)
GET    /api/settings/appearance/image    the picture (?v= its version, so it can be cached for good)
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import actors, config
from .util import write_json

router = APIRouter(tags=["appearance"])

THEMES = ("radix-red", "radix-indigo", "radix-teal", "custom")
ACCENTS = ("gray", "gold", "bronze", "brown", "yellow", "amber", "orange", "tomato", "red", "ruby", "crimson", "pink",
           "plum", "purple", "violet", "iris", "indigo", "blue", "cyan", "teal", "jade", "green", "grass", "lime",
           "mint", "sky")
RADII = ("none", "small", "medium", "large", "full")
BACKGROUNDS = ("radix", "ribbons", "gradient", "glow", "plain", "image")
DEFAULTS: dict[str, Any] = {
    "theme": "radix-red",
    "custom": {"accent": "red", "radius": "large", "background": "ribbons"},
    "blur": 40,
}
MAX_IMAGE = 15 * 1024 * 1024
# what a picture's first bytes say it is (the name's extension is not trusted; SVG is refused, it can carry script)
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png", "image/png"), (b"\xff\xd8\xff", "jpg", "image/jpeg"),
          (b"GIF87a", "gif", "image/gif"), (b"GIF89a", "gif", "image/gif"))
_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "avif": "image/avif"}


def backgrounds_dir() -> Path:
    return config.LOCAL_DIR / "backgrounds"


def _raw() -> dict:
    try:
        data = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _mine() -> dict:
    """The appearance block of settings.json as written (a copy; anything but an object counts as empty)."""
    mine = _raw().get("appearance")
    return dict(mine) if isinstance(mine, dict) else {}


def _write(appearance: dict) -> None:
    data = _raw()
    if appearance:
        data["appearance"] = appearance
    else:
        data.pop("appearance", None)
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(config.SETTINGS_FILE, data)
    config._SETTINGS_CACHE = (-1.0, {})


def _image_file(mine: dict) -> Path | None:
    name = mine.get("image")
    if not isinstance(name, str) or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = backgrounds_dir() / name
    return path if path.is_file() else None


def current() -> dict:
    """The effective settings: the user's choices over the defaults, anything unknown dropped."""
    mine = config.user_settings().get("appearance") or {}
    mine = mine if isinstance(mine, dict) else {}
    out = copy.deepcopy(DEFAULTS)
    if mine.get("theme") in THEMES:
        out["theme"] = mine["theme"]
    custom = mine.get("custom") if isinstance(mine.get("custom"), dict) else {}
    if custom.get("accent") in ACCENTS:
        out["custom"]["accent"] = custom["accent"]
    if custom.get("radius") in RADII:
        out["custom"]["radius"] = custom["radius"]
    if custom.get("background") in BACKGROUNDS:
        out["custom"]["background"] = custom["background"]
    blur = mine.get("blur")
    if isinstance(blur, int) and not isinstance(blur, bool) and 0 <= blur <= 100:
        out["blur"] = blur
    image = _image_file(mine)
    out["image"] = f"/api/settings/appearance/image?v={image.stem}" if image else None
    if out["custom"]["background"] == "image" and not image:
        out["custom"]["background"] = "ribbons"
    return out


def update(change: dict) -> dict:
    """Write the allowed keys of `change`; None (or a missing nested key's None) puts that key back to its default."""
    if not isinstance(change, dict):
        raise ValueError("send an object")
    mine = _mine()
    if "theme" in change:
        if change["theme"] is None:
            mine.pop("theme", None)
        elif change["theme"] not in THEMES:
            raise ValueError(f"theme must be one of {', '.join(THEMES)}")
        else:
            mine["theme"] = change["theme"]
    if "custom" in change:
        if change["custom"] is None:
            mine.pop("custom", None)
        elif not isinstance(change["custom"], dict):
            raise ValueError("custom must be an object")
        else:
            custom = dict(mine.get("custom") or {})
            for key, allowed in (("accent", ACCENTS), ("radius", RADII), ("background", BACKGROUNDS)):
                if key not in change["custom"]:
                    continue
                value = change["custom"][key]
                if value is None:
                    custom.pop(key, None)
                elif value not in allowed:
                    raise ValueError(f"{key} must be one of {', '.join(allowed)}")
                else:
                    custom[key] = value
            if custom.get("background") == "image" and not _image_file(mine):
                raise ValueError("upload a picture first")
            mine["custom"] = custom
    if "blur" in change:
        blur = change["blur"]
        if blur is None:
            mine.pop("blur", None)
        elif not isinstance(blur, int) or isinstance(blur, bool) or not 0 <= blur <= 100:
            raise ValueError("blur must be a whole number from 0 to 100")
        else:
            mine["blur"] = blur
    _write(mine)
    return current()


def sniff(data: bytes) -> tuple[str, str] | None:
    """(extension, media type) of a PNG, JPEG, GIF, WebP or AVIF picture, from its first bytes; None otherwise."""
    for magic, ext, media in _MAGIC:
        if data.startswith(magic):
            return ext, media
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "avif", "image/avif"
    return None


def save_image(content: bytes) -> dict:
    """Keep `content` as the background picture (replacing the one before) and make it the background."""
    if not content:
        raise ValueError("the picture is empty")
    if len(content) > MAX_IMAGE:
        raise ValueError("the picture is larger than 15 MB")
    kind = sniff(content)
    if not kind:
        raise ValueError("not a picture: use PNG, JPEG, WebP, GIF or AVIF")
    folder = backgrounds_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{hashlib.sha256(content).hexdigest()[:16]}.{kind[0]}"
    target = folder / name
    tmp = folder / f".{name}.part"
    tmp.write_bytes(content)
    tmp.replace(target)
    for old in folder.iterdir():
        if old.name != name and old.is_file():
            old.unlink(missing_ok=True)
    mine = _mine()
    mine["image"] = name
    mine["theme"] = "custom"
    mine["custom"] = {**(mine.get("custom") or {}), "background": "image"}
    _write(mine)
    return current()


def remove_image() -> dict:
    mine = _mine()
    path = _image_file(mine)
    if path:
        path.unlink(missing_ok=True)
    mine.pop("image", None)
    custom = dict(mine.get("custom") or {})
    if custom.get("background") == "image":
        custom["background"] = "ribbons"
        mine["custom"] = custom
    _write(mine)
    return current()


def _human(request: Request) -> None:
    if not actors.is_human(actors.actor_of(request)):
        raise HTTPException(403, "only the researcher changes this")


class Picture(BaseModel):
    name: str = ""
    content_base64: str


@router.get("/api/settings/appearance")
def get_appearance():
    return current()


@router.patch("/api/settings/appearance")
def patch_appearance(body: dict, request: Request):
    _human(request)
    try:
        return update(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/settings/appearance/image")
def put_image(body: Picture, request: Request):
    _human(request)
    if len(body.content_base64) > MAX_IMAGE * 4 // 3 + 8:
        raise HTTPException(413, "the picture is larger than 15 MB")
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "content_base64 is not base64")
    try:
        return save_image(content)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/settings/appearance/image")
def delete_image(request: Request):
    _human(request)
    return remove_image()


@router.get("/api/settings/appearance/image")
def get_image(v: str = ""):
    mine = config.user_settings().get("appearance") or {}
    path = _image_file(mine if isinstance(mine, dict) else {})
    if not path:
        raise HTTPException(404, "no background picture")
    media = _TYPES.get(path.suffix.lstrip("."), "application/octet-stream")
    cache = "private, max-age=31536000, immutable" if v == path.stem else "no-cache"
    return FileResponse(path, media_type=media, headers={
        "Cache-Control": cache, "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
