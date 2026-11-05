"""Create a project from an idea: its folder, the idea's files, the registry entry, then the survey.

  folder   where the project goes. Missing: <Settings → New projects → folder>/<the name as a folder name>, made
           unique with -2, -3 …. A folder that exists is used as it is (and registered unless it is a project).
  idea     the idea as text; file: an uploaded .md, .txt or .pdf (at most MAX_UPLOAD bytes), kept as it is in notes/,
           its text added to the idea (a PDF's through pypdf)
It writes notes/idea.md (notes/idea-2.md … when one exists), runs git init when Settings say so and the folder is not
in a repository yet, and in a folder it created, a .gitignore that keeps the downloaded PDFs out of git.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from fastapi import HTTPException

from .. import projects
from ..util import write_text_atomic
from . import settings

log = logging.getLogger("research_deck.start")

MAX_UPLOAD = 20 * 1024 * 1024
MAX_IDEA_CHARS = 100_000
PDF_PAGES = 40
UPLOAD_TYPES = (".md", ".txt", ".pdf")


def folder_name(name: str) -> str:
    """A folder name from the project's name: letters (any script) and digits, words joined by '-'."""
    s = unicodedata.normalize("NFC", name or "").strip().lower()
    s = re.sub(r"[^\w-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-_.")
    return s[:60] or "project"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while (cand := path.with_name(f"{path.name}-{n}")).exists():
        n += 1
    return cand


def _free(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while (cand := path.with_name(f"{path.stem}-{n}{path.suffix}")).exists():
        n += 1
    return cand


def upload_name(name: str) -> str:
    base = Path((name or "").replace("\\", "/")).name
    stem, suffix = Path(base).stem, Path(base).suffix.lower()
    if suffix not in UPLOAD_TYPES:
        raise HTTPException(400, f"upload a {', '.join(UPLOAD_TYPES)} file")
    stem = re.sub(r"[^\w.-]+", "-", unicodedata.normalize("NFC", stem)).strip("-.") or "idea"
    if f"{stem}{suffix}" == "idea.md":
        stem = "idea-upload"
    return f"{stem[:80]}{suffix}"


def pdf_text(data: bytes) -> str:
    """The text of the first PDF_PAGES pages ('' when the PDF has no text layer or cannot be read)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:PDF_PAGES]:
            parts.append(page.extract_text() or "")
            if sum(map(len, parts)) > MAX_IDEA_CHARS:
                break
        return re.sub(r"[ \t]+\n", "\n", "\n\n".join(parts)).strip()[:MAX_IDEA_CHARS]
    except Exception:  # noqa: BLE001 — an unreadable PDF is kept; the idea then needs text
        log.info("could not read the uploaded PDF", exc_info=True)
        return ""


def _decode(file: dict) -> tuple[str, bytes, str]:
    name = upload_name(file.get("name") or "")
    try:
        data = base64.b64decode(file.get("content_base64") or "", validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "the file is not valid base64")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"files up to {MAX_UPLOAD // (1024 * 1024)} MB")
    if name.endswith(".pdf"):
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "this .pdf is not a PDF")
        text = pdf_text(data)
    else:
        text = data.decode("utf-8", errors="replace")[:MAX_IDEA_CHARS]
    return name, data, text


def _in_git(path: Path) -> bool:
    git = shutil.which("git")
    if not git:
        return True                       # no git: nothing to initialize
    r = subprocess.run([git, "-C", str(path), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def target_folder(name: str, folder: str | None, cfg: dict) -> tuple[Path, bool]:
    """(the project's folder, whether it has to be created)."""
    if folder and folder.strip():
        root = settings.expand(folder.strip())
        if not root.is_absolute():
            raise HTTPException(400, "give the folder as a full path (or one starting with ~)")
        root = root.resolve()
        if root == Path(root.anchor) or root == Path.home().resolve():
            raise HTTPException(400, "choose a folder for the project, not the top of the disk or your home folder")
        if root.exists() and not root.is_dir():
            raise HTTPException(400, f"not a folder: {root}")
        return root, not root.exists()
    base = settings.expand(cfg["dir"])
    if not base.is_absolute():
        raise HTTPException(400, f"the default folder is not a full path: {cfg['dir']} (Settings → New projects)")
    return _unique(base.resolve() / folder_name(name)), True


def create(name: str, idea: str, file: dict | None, folder: str | None, survey: dict | None, actor: str) -> dict:
    from ..survey import job
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise HTTPException(400, "the project needs a name (at most 120 characters)")
    idea = (idea or "").strip()[:MAX_IDEA_CHARS]
    upload = _decode(file) if file else None
    file_text = upload[2].strip() if upload else ""
    if not idea and not file_text:
        raise HTTPException(400, "write the idea, or upload a file with text in it" +
                            (" (this PDF has no text layer)" if upload and upload[0].endswith(".pdf") else ""))
    cfg = settings.new_projects()
    root, new_folder = target_folder(name, folder, cfg)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"could not create {root}: {e.strerror or e}")

    notes = root / "notes"
    notes.mkdir(exist_ok=True)
    kept = None
    if upload:
        kept = _free(notes / upload[0])
        kept.write_bytes(upload[1])
    zh = len(re.findall(r"[一-鿿]", idea + file_text)) >= 6
    parts = [f"# {name}", ""]
    if idea:
        parts += [idea, ""]
    if kept:
        label = "上传的文件" if zh else "Uploaded file"
        parts += [f"> {label}: [{kept.name}]({kept.name})", ""]
        if file_text:
            parts += [file_text, ""]
    idea_path = _free(notes / "idea.md")
    write_text_atomic(idea_path, "\n".join(parts).rstrip() + "\n")

    papers = cfg["survey"]["papers_dir"]
    if new_folder and not (root / ".gitignore").exists():
        write_text_atomic(root / ".gitignore", f"# downloaded papers (the survey fetches them again)\n{papers}/*.pdf\n")
    if cfg["git_init"] and not _in_git(root):
        r = subprocess.run([shutil.which("git") or "git", "init", "-q"], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            log.warning("git init in %s failed: %s", root, r.stderr.strip())

    summary = projects.add_project(projects.AddProject(root=str(root), name=name, kind="research"))
    pid = summary["id"]
    rel = idea_path.relative_to(root).as_posix()
    out = {"project": summary, "root": str(root), "created": new_folder, "idea_file": rel,
           "upload": kept.relative_to(root).as_posix() if kept else None, "survey": None}
    opts = survey or {}
    if opts.get("enabled", True):
        text = "\n\n".join(t for t in (idea, file_text) if t)
        unread = kept.name if kept and not file_text else None
        out["survey"] = job.start(pid, text, idea_file=rel, unread=unread, count=opts.get("count"),
                                  download_pdfs=opts.get("download_pdfs"), actor=actor)
    return out
