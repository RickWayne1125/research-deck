"""The project's documents: .tex and .md files under the paper dir (project.yaml `paper.dir`), docs/ and notes/.

Titles come from \\title{...} (else the first \\section) in LaTeX and the first `# heading` (else front matter
`title:`) in Markdown; word counts skip LaTeX commands, comments and Markdown code, and count each CJK character
as one word.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from ..projects import IGNORED_DIRS, MAX_FILE_BYTES, RESEARCH_DIR, project_config, project_root
from ..util import rel_to, safe_join

DOC_KINDS = {".tex": "tex", ".md": "md", ".markdown": "md"}
EXTRA_DIRS = ("docs", "notes")
MAX_DOCS = 400

_LATIN_WORD = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_TEX_COMMENT = re.compile(r"(?<!\\)%.*")
# Commands whose argument is a key or a path, not prose.
_TEX_KEYED = re.compile(r"\\(?:cite[a-zA-Z]*|[cC]?ref|eqref|autoref|label|includegraphics|input|include|bibliography[a-z]*|"
                        r"usepackage|documentclass|begin|end|url|href)\*?(?:\[[^\]]*\])*\{[^}]*\}")
_TEX_COMMAND = re.compile(r"\\[a-zA-Z@]+\*?")


def doc_kind(path: str | Path) -> str | None:
    return DOC_KINDS.get(Path(str(path)).suffix.lower())


def word_count(text: str, kind: str) -> int:
    if kind == "tex":
        t = _TEX_COMMENT.sub(" ", text)
        t = _TEX_KEYED.sub(" ", t)
        t = _TEX_COMMAND.sub(" ", t)
    else:
        t = re.sub(r"\A---\s*\n.*?\n---\s*\n", " ", text, flags=re.S)     # YAML front matter
        t = re.sub(r"```.*?```", " ", t, flags=re.S)
        t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
        t = re.sub(r"\]\([^)]*\)", "]", t)   # link targets
    return len(_LATIN_WORD.findall(t)) + len(_CJK.findall(t))


def _braced(text: str, start: int) -> str | None:
    """The content of the brace group opening at text[start] == '{' (nested braces kept)."""
    if start >= len(text) or text[start] != "{":
        return None
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c == "\\":          # an escaped brace (\{ \}) does not count
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    return None


def _plain_tex(s: str) -> str:
    s = re.sub(r"\\(?:thanks|footnote|label)\{[^}]*\}", "", s)
    s = s.replace("\\\\", " ").replace("~", " ")
    s = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def title_of(text: str, kind: str, fallback: str) -> str:
    if kind == "tex":
        body = _TEX_COMMENT.sub("", text)
        for pattern in (r"\\title(?:\[[^\]]*\])?\s*(?=\{)", r"\\(?:chapter|section)\*?(?:\[[^\]]*\])?\s*(?=\{)"):
            m = re.search(pattern, body)
            if m:
                inner = _braced(body, m.end())
                if inner and _plain_tex(inner):
                    return _plain_tex(inner)[:160]
        return fallback
    m = re.search(r"^#\s+(.+?)\s*#*\s*$", text, re.M)
    if m:
        return m.group(1).strip()[:160]
    fm = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if fm:
        t = re.search(r"^title:\s*['\"]?(.+?)['\"]?\s*$", fm.group(1), re.M)
        if t:
            return t.group(1).strip()[:160]
    return fallback


def doc_dirs(pid: str) -> list[str]:
    cfg = project_config(pid)
    paper_dir = str((cfg.get("paper") or {}).get("dir") or "paper").strip("/") or "paper"
    out: list[str] = []
    for d in (paper_dir, *EXTRA_DIRS):
        if d not in out:
            out.append(d)
    return out


def _walk(base: Path):
    try:
        entries = sorted(base.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
    except OSError:
        return
    for p in entries:
        if p.name in IGNORED_DIRS or p.name.startswith(".") or p.name == RESEARCH_DIR:
            continue
        try:
            if p.is_symlink():          # a linked folder may loop or point outside the project
                continue
            if p.is_dir():
                yield from _walk(p)
            elif doc_kind(p):
                yield p
        except OSError:
            continue


def doc_files(pid: str) -> list[str]:
    """Project-relative paths of the documents, the paper's main file first."""
    root = project_root(pid)
    cfg = project_config(pid)
    main = str((cfg.get("paper") or {}).get("main") or "")
    seen: list[str] = []
    if main and doc_kind(main) and (root / main).is_file():
        seen.append(rel_to(root, root / main))
    for d in doc_dirs(pid):
        base = root / d
        if not base.is_dir():
            continue
        for p in _walk(base):
            rel = rel_to(root, p)
            if rel not in seen:
                seen.append(rel)
            if len(seen) >= MAX_DOCS:
                return seen
    return seen


def resolve_doc(pid: str, rel: str) -> tuple[Path, str]:
    """The absolute path and its normalized project-relative form; 400 unless it is a .tex/.md inside the project."""
    root = project_root(pid)
    target = safe_join(root, rel)
    if not doc_kind(target):
        raise HTTPException(400, f"not a .tex or .md document: {rel}")
    return target, rel_to(root, target)


def read_doc(pid: str, rel: str) -> tuple[str, str]:
    """(normalized path, text) of an existing document."""
    target, norm = resolve_doc(pid, rel)
    if not target.is_file():
        raise HTTPException(404, f"no such document: {rel}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(413, "document too large")
    try:
        return norm, target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "not a UTF-8 text file")


def describe(pid: str, rel: str, claims: list[dict] | None = None) -> dict | None:
    """A WritingDoc for one path, or None when it cannot be read."""
    root = project_root(pid)
    p = root / rel
    kind = doc_kind(p)
    try:
        if not kind or p.stat().st_size > MAX_FILE_BYTES:
            return None
        text = p.read_text(encoding="utf-8")
        mtime = p.stat().st_mtime
    except (OSError, UnicodeDecodeError):
        return None
    claims = claims or []
    stale = sum(1 for c in claims if c.get("freshness") not in (None, "fresh"))
    return {"path": rel, "title": title_of(text, kind, p.stem), "kind": kind, "words": word_count(text, kind),
            "updated_at": mtime, "claims": len(claims), "stale_claims": stale}
