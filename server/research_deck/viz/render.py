"""Render a matplotlib figure script to an SVG preview in a subprocess.

The script runs with config.PYTHON_FOR_FIGURES, cwd = project root, MPLBACKEND=Agg and RD_FIG_OUT = the preview path,
for at most 60 s. Unsaved code (the editor's buffer) is written to a hidden copy next to the original so relative
paths and `import _rdstyle` behave exactly as they do for the saved file. A failed render keeps the last good preview.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import HTTPException

from .. import config
from ..events import hub
from ..projects import project_root
from ..util import rel_to, run_killable
from . import figures

TIMEOUT_S = 60
MAX_LOG = 20000

# Runs the script like `python script.py` (its folder first on sys.path), then saves the current figure if the script
# did not write RD_FIG_OUT itself (e.g. it ends with plt.show(), which is a no-op under Agg).
BOOTSTRAP = r"""
import os, runpy, sys
script = sys.argv[1]
out = os.environ["RD_FIG_OUT"]
sys.argv = [script]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
runpy.run_path(script, run_name="__main__")
if not os.path.exists(out):
    import matplotlib.pyplot as plt
    if plt.get_fignums():
        plt.gcf().savefig(out)
        print("[research-deck] the script did not save to RD_FIG_OUT; saved the current figure instead", file=sys.stderr)
"""

_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
# Frames of the bootstrap above (`python -c` and runpy) say nothing about the researcher's script.
_BOOT_FRAME = re.compile(r'^\s*File "(?:<string>|<frozen runpy>|[^"]*[/\\]runpy\.py)", line \d+, in .*\n', re.M)


def _clean_traceback(log: str) -> str:
    return _BOOT_FRAME.sub("", log)


def run_script(root: Path, script: Path, out: Path, timeout: int = TIMEOUT_S) -> tuple[bool, str, int]:
    """Run script (inside root) so that it writes out. Returns (ok, log, duration_ms)."""
    python = config.PYTHON_FOR_FIGURES
    if not python or not Path(python).exists():
        return False, f"Python for figures not found: {python} (set RD_FIGURE_PYTHON)", 0
    env = {**os.environ, "MPLBACKEND": "Agg", "RD_FIG_OUT": str(out), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    started = time.monotonic()
    try:
        proc = run_killable([python, "-c", BOOTSTRAP, rel_to(root, script)], cwd=root, env=env, timeout=timeout)
        log = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
        if ok and not out.exists():
            ok, log = False, log + "\n[research-deck] the script finished without drawing a figure (call rd.save(fig))."
        elif not ok:
            log = log.rstrip() + f"\n[research-deck] exit code {proc.returncode}"
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"") + (e.stderr or b"")
        log = (partial.decode("utf-8", "replace") if isinstance(partial, bytes) else str(partial))
        ok, log = False, log + f"\n[research-deck] stopped after {timeout} s"
    except OSError as e:
        ok, log = False, f"[research-deck] could not start {python}: {e}"
    return ok, log[-MAX_LOG:], int((time.monotonic() - started) * 1000)


def render(pid: str, fid: str, source: str | None = None) -> dict:
    """RenderResult {ok, preview, log, duration_ms} for a matplotlib figure; source = unsaved script text."""
    entry = figures.get_entry(pid, fid)
    if entry.get("kind") != "matplotlib":
        raise HTTPException(400, f"only matplotlib figures render on the server (this one is {entry.get('kind')})")
    root = project_root(pid)
    script = figures.source_path(pid, entry)
    if source is None and not script.is_file():
        raise HTTPException(404, f"no such file: {entry.get('source')}")
    if not script.parent.is_dir():
        raise HTTPException(404, f"the folder of {entry.get('source')} is missing")
    figures.ensure_helper(pid)   # a project cloned without the generated helper still renders

    with _locks[f"{pid}:{fid}"]:
        token = uuid.uuid4().hex[:8]
        previews = figures.previews_dir(pid)
        out = previews / f".{fid}.{token}.svg"
        temp = script.with_name(f".{script.stem}.rd-preview-{token}.py") if source is not None else None
        try:
            if temp is not None:
                temp.write_text(source, encoding="utf-8")
            ok, log, ms = run_script(root, temp or script, out)
            if temp is not None:
                # Point tracebacks at the file the researcher is editing, not the hidden copy.
                log = log.replace(str(temp), str(script)).replace(temp.name, script.name)
            log = _clean_traceback(log)
            sig = figures.signature(pid, entry, source_text=source)
            if ok:
                for ext in figures.PREVIEW_EXTS:
                    (previews / f"{fid}{ext}").unlink(missing_ok=True)
                os.replace(out, previews / f"{fid}.svg")
            figures.record_render(pid, fid, ok=ok, sig=sig, duration_ms=ms, log=log)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
            out.unlink(missing_ok=True)
    hub.publish(pid, "figures", {"id": fid, "action": "render", "ok": ok})
    return {"ok": ok, "preview": figures.preview_url(pid, fid) if ok else None, "log": log, "duration_ms": ms}


def export_pdf(pid: str, fid: str) -> dict:
    """Write the paper PDF next to a matplotlib script (figures/<name>.pdf) from the saved script."""
    entry = figures.get_entry(pid, fid)
    root = project_root(pid)
    script = figures.source_path(pid, entry)
    if not script.is_file():
        raise HTTPException(404, f"no such file: {entry.get('source')}")
    figures.ensure_helper(pid)
    target = script.with_suffix(".pdf")
    tmp = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}.pdf")
    try:
        ok, log, ms = run_script(root, script, tmp)
        if ok:
            os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    if not ok:
        raise HTTPException(422, {"message": "the script failed; see the log", "log": log})
    return {"ok": True, "app": "matplotlib", "outputs": [rel_to(root, target)], "log": log, "duration_ms": ms}
