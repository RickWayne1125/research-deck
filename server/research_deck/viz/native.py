"""Open and export figures through the native apps when they are installed on this Mac.

  open      `open -a <app> <file>` for draw.io desktop, OmniGraffle and DataGraph
  export    DataGraph:   dgraph -script <file> -output <file>.pdf   (+ a PNG preview, -dpi 200)
            OmniGraffle: AppleScript through osascript: open the document, save copies as PDF and PNG, close it
            draw.io:     the desktop app's CLI (draw.io --export --format pdf|png)
            matplotlib:  the script itself, writing <script>.pdf (render.export_pdf)
Nothing here blocks the event loop: the routes are plain `def` endpoints (FastAPI runs them in a worker thread).
Paths reach osascript as arguments (`on run argv`), never spliced into the script text.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

from fastapi import HTTPException

from .. import config
from ..events import hub
from ..projects import project_root
from ..util import rel_to, run_killable
from . import figures, render

APP_LABELS = {"drawio": "draw.io", "omnigraffle": "OmniGraffle", "datagraph": "DataGraph"}
EXPORT_TIMEOUT_S = 180

OMNIGRAFFLE_EXPORT = """
on run argv
    set srcPath to item 1 of argv
    set pdfPath to item 2 of argv
    set pngPath to item 3 of argv
    set appName to item 4 of argv
    tell application appName
        set theDoc to open (POSIX file srcPath)
        delay 0.5
        save theDoc in (POSIX file pdfPath)
        save theDoc in (POSIX file pngPath)
        close theDoc saving no
    end tell
end run
"""


def _not_installed(app_key: str) -> HTTPException:
    return HTTPException(409, {"message": f"{APP_LABELS.get(app_key, app_key)} is not installed on this Mac", "app": app_key})


def _run(cmd: list[str], timeout: int = EXPORT_TIMEOUT_S) -> tuple[bool, str]:
    try:
        proc = run_killable(cmd, timeout=timeout)
        return proc.returncode == 0, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout} s"
    except OSError as e:
        return False, str(e)


def open_native(pid: str, fid: str) -> dict:
    entry = figures.get_entry(pid, fid)
    app_key = figures.NATIVE_APP.get(entry.get("kind"))
    if not app_key:
        raise HTTPException(409, {"message": "matplotlib figures are edited here; there is no native app to open", "app": None})
    app = config.app_path(app_key)
    if not app:
        raise _not_installed(app_key)
    path = figures.source_path(pid, entry)
    if not path.exists():
        raise HTTPException(404, f"no such file: {entry.get('source')}")
    ok, out = _run(["open", "-a", app, str(path)], timeout=20)
    if not ok:
        raise HTTPException(502, {"message": f"could not open {APP_LABELS[app_key]}: {out}", "app": app_key})
    return {"ok": True, "app": app_key, "path": app}


def _install_preview(pid: str, fid: str, png: Path) -> None:
    previews = figures.previews_dir(pid)
    for ext in figures.PREVIEW_EXTS:
        (previews / f"{fid}{ext}").unlink(missing_ok=True)
    os.replace(png, previews / f"{fid}.png")


def export_native(pid: str, fid: str) -> dict:
    entry = figures.get_entry(pid, fid)
    kind = entry.get("kind")
    if kind == "matplotlib":
        return render.export_pdf(pid, fid)
    app_key = figures.NATIVE_APP.get(kind)
    root = project_root(pid)
    src = figures.source_path(pid, entry)
    if not src.exists():
        raise HTTPException(404, f"no such file: {entry.get('source')}")
    pdf = src.with_suffix(".pdf")
    png = figures.previews_dir(pid) / f".{fid}.{uuid.uuid4().hex[:8]}.png"
    sig = figures.signature(pid, entry)

    if kind == "datagraph":
        cli = config.DATAGRAPH_CLI
        if not cli or not Path(cli).exists():
            raise _not_installed("datagraph")
        ok, log = _run([cli, "-script", str(src), "-output", str(pdf)])
        if ok:
            ok_png, log_png = _run([cli, "-script", str(src), "-output", str(png), "-dpi", "200"])
            log = "\n".join(filter(None, [log, log_png]))
    elif kind == "omnigraffle":
        app = config.app_path("omnigraffle")
        if not app:
            raise _not_installed("omnigraffle")
        ok, log = _run(["osascript", "-e", OMNIGRAFFLE_EXPORT, str(src), str(pdf), str(png), Path(app).stem])
    elif kind == "drawio":
        app = config.app_path("drawio")
        if not app:
            raise HTTPException(409, {"message": "draw.io desktop is not installed; the preview is exported from the web "
                                                 "editor when you save", "app": "drawio"})
        binary = str(Path(app) / "Contents" / "MacOS" / "draw.io")
        ok, log = _run([binary, "--export", "--format", "pdf", "--crop", "--output", str(pdf), str(src)])
        if ok:
            _run([binary, "--export", "--format", "png", "--scale", "2", "--output", str(png), str(src)])
    else:
        raise HTTPException(400, f"unknown figure kind: {kind}")

    # A zero exit code alone is not proof: check the files exist.
    if not ok or not pdf.exists():
        png.unlink(missing_ok=True)
        raise HTTPException(502, {"message": f"{APP_LABELS.get(app_key, kind)} export failed", "log": log[-4000:]})
    outputs = [rel_to(root, pdf)]
    if png.exists():
        _install_preview(pid, fid, png)
        figures.record_render(pid, fid, ok=True, sig=sig)
    hub.publish(pid, "figures", {"id": fid, "action": "export"})
    return {"ok": True, "app": app_key, "outputs": outputs, "log": log[-4000:], "preview": figures.preview_url(pid, fid)}
