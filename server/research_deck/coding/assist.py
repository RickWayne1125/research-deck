"""Code review and code explanation through the coding panel's bound agent.

Both go through agents.api.spec_for (the panel's backend, model, effort, fast) and runner.start, always read-only.
  review    one-shot (ephemeral) run over a unified diff; the agent may read surrounding files; the answer is one
            fenced json block {"findings": [{file, line, severity, title, body, suggestion}]}
  explain   a run in the coding session (so follow-up questions in the dock have it) over a numbered snippet plus
            what the architecture says about the file; the answer is markdown
RD_FAKE_AGENT=1 answers both deterministically (registered below).
"""
from __future__ import annotations

import json
import re

from fastapi import HTTPException

from ..agents import runner
from ..agents.api import RunBody, spec_for
from ..projects import MAX_FILE_BYTES, project_root
from ..util import safe_join
from . import architecture, git

MAX_REVIEW_CHARS = 150_000          # diff text sent to the reviewer; the rest is listed by name
MAX_EXPLAIN_LINES = 400
REVIEW_EXCLUDE = (".research",)     # dashboard state (DAG, transcripts) is not code; reviewed only when asked by path

FENCE_LANGS = {".py": "python", ".ts": "ts", ".tsx": "tsx", ".js": "js", ".jsx": "jsx", ".mjs": "js", ".json": "json",
               ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".md": "markdown", ".tex": "latex", ".sh": "bash",
               ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".cu": "cuda", ".rs": "rust", ".go": "go"}


def _language_rule(lang: str | None) -> str:
    if lang == "zh":
        return "Write in Simplified Chinese (简体中文); keep code, identifiers, paths and technical terms as they are."
    return "Write in English."


def _fence(text: str) -> str:
    """A backtick fence longer than any backtick run inside text, so the block cannot end early."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _range_label(requested_from: str | None, raw: git.RawDiff) -> str:
    if raw.to and not requested_from:
        return f"the changes of commit {raw.to}"
    if raw.to:
        return f"{raw.frm} → {raw.to}"
    base = raw.frm or "the empty tree (no commits yet)"
    return f"the working tree vs {base} (uncommitted changes, untracked files included)"


# ------------------------------------------------------------------ review

def _fit_diff(text: str, files: list[dict], budget: int) -> tuple[str, list[dict], bool]:
    """Whole file diffs while they fit the budget; returns (diff text, files left out, a file cut part-way)."""
    chunks = [c for c in re.split(r"(?m)^(?=diff --git )", text) if c.startswith("diff --git ")]
    shown: list[str] = []
    used, cut = 0, False
    omitted: list[dict] = []
    for i, chunk in enumerate(chunks):
        if used + len(chunk) <= budget:
            shown.append(chunk)
            used += len(chunk)
            continue
        room = budget - used
        if room > 4000 and not cut:        # worth showing the head of this file rather than nothing
            head = chunk[:room]
            head = head[: head.rfind("\n") + 1]
            shown.append(head + "[... the rest of this file's diff is omitted ...]\n")
            used, cut = budget, True
            continue
        if i < len(files):
            omitted.append(files[i])
    return "".join(shown), omitted, cut


def start_review(pid: str, frm: str | None = None, to: str | None = None, paths: list[str] | None = None,
                 focus: dict | None = None, lang: str | None = None, *, repo: str | None = None) -> dict:
    from . import repos
    folder, prefix = repos.resolve(pid, repo)
    paths = [repos.strip(prefix, p_) for p_ in paths] if paths else None
    if focus and focus.get("path") and prefix:
        focus = {**focus, "path": repos.strip(prefix, focus["path"])}
    repo_obj = git.require_repo(folder)
    raw = git.raw_diff(repo_obj, frm, to, paths or None, exclude=() if paths else REVIEW_EXCLUDE)
    files, _ = git.parse_diff(raw.text)
    if not files:
        raise HTTPException(400, "nothing to review: this range has no changes")
    shown, omitted, cut = _fit_diff(raw.text, files, MAX_REVIEW_CHARS)
    label = _range_label(frm, raw)
    listing = "\n".join(
        f"- {f['status']} {f['path']}" + (f" (from {f['old_path']})" if f.get("old_path") else "")
        + (" (binary)" if f.get("binary") else f" (+{f['additions']} −{f['deletions']})") for f in files)
    notes = []
    if prefix:
        notes.append(f"This diff is of the repository in {prefix.rstrip('/')}/: its paths (a/…, b/…) are relative to "
                     f"that folder; from the project folder, read them as {prefix}<path>.")
    if omitted:
        notes.append(f"The diff is truncated: {len(files) - len(omitted)} of {len(files)} files are shown below. Read the "
                     "others directly when they matter: " + ", ".join(f["path"] for f in omitted[:40])
                     + (" …" if len(omitted) > 40 else "") + ".")
    elif cut or raw.truncated:
        notes.append("The diff is truncated; read the changed files directly where the diff stops.")
    focus_text = ""
    if focus and focus.get("path"):
        where = f" lines {focus.get('start_line')}–{focus.get('end_line')}" if focus.get("start_line") else ""
        focus_text = (f"Focus on {focus['path']}{where} (line numbers of the new version). Mention other code only "
                      "where these lines break it or depend on it.\n")
    fence = _fence(shown)
    prompt = (
        f"Review a code change in this research project: {label}.\n\n"
        "Look for correctness problems first: wrong results, crashes, broken invariants, off-by-one, shape or dtype "
        "errors, races, resource leaks, numerical instability, silent data corruption, and changes that contradict the "
        "system design or the experiments that depend on this code. Then design and performance problems that matter. "
        "Do not report style, formatting or naming nits. Read surrounding code with your tools when the diff alone is "
        "not enough (you cannot run git or shell commands, and the working tree may hold later edits than this diff). "
        "Do not modify any file.\n"
        f"{focus_text}{_language_rule(lang)}\n\n"
        "Answer with exactly one fenced ```json block and nothing after it:\n"
        '{"findings": [{"file": "<project-relative path, the new side of the diff>", "line": <line in the new version, '
        'or null>, "severity": "high|medium|low|info", "title": "<one line>", "body": "<what is wrong and when it '
        'bites>", "suggestion": "<the concrete fix, or null>"}]}\n'
        "Severity: high = wrong results, a crash or data loss; medium = a likely bug or a real performance or design "
        "cost; low = a minor risk; info = worth knowing, no change needed. Order findings by severity. "
        'Return {"findings": []} if the change looks right.\n\n'
        f"Changed files ({len(files)}):\n{listing}\n\n"
        + ("\n".join(notes) + "\n\n" if notes else "")
        + f"{fence}diff\n{shown}{fence}\n"
    )
    body = RunBody(panel="coding", purpose="code-review", prompt=f"Code review: {label}", ephemeral=True, permission="read")
    run = runner.start(spec_for(pid, body, tools=True, prompt=prompt))
    s = run.spec
    return {"run_id": run.id, "provider": s.provider, "model": s.model, "effort": s.effort, "fast": s.fast,
            "session_id": s.session_id, "files": len(files), "truncated": bool(omitted or cut or raw.truncated),
            "from": raw.frm, "to": raw.to}


# ------------------------------------------------------------------ explain

def _read_source(pid: str, rel: str, rev: str | None, repo: str | None = None) -> str:
    root = project_root(pid)
    if rev:
        from . import repos
        folder, prefix = repos.resolve(pid, repo)
        return git.show(folder, rev, repos.strip(prefix, rel))["content"]
    target = safe_join(root, rel)
    if not target.is_file():
        raise HTTPException(404, f"no such file: {rel}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(413, "file too large to explain here")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "not a text file")


def _architecture_note(pid: str, rel: str) -> str:
    try:
        ctx = architecture.module_context(pid, rel)
    except Exception:  # noqa: BLE001 — the explanation works without it
        return ""
    if not ctx:
        return ""
    lines = [f"Module {ctx['module']['label']} ({ctx['module']['kind']}, {ctx['module']['loc']} lines of code)."]
    if ctx["component"]:
        c = ctx["component"]
        lines.append(f"Component: {c['label']}" + (f" (DAG node {c['node_id']})" if c.get("node_id") else "")
                     + (f" — {c['description']}" if c.get("description") else ""))
    if ctx["imports"]:
        lines.append("Imports: " + ", ".join(ctx["imports"][:20]))
    if ctx["imported_by"]:
        lines.append("Imported by: " + ", ".join(ctx["imported_by"][:20]))
    return "Architecture context (from the dashboard's import graph):\n" + "\n".join(lines) + "\n\n"


def start_explain(pid: str, path: str, start_line: int = 1, end_line: int | None = None, rev: str | None = None,
                  lang: str | None = None, *, repo: str | None = None) -> dict:
    root = project_root(pid)
    rel = git.project_rel(root, path)
    lines = _read_source(pid, rel, rev, repo).splitlines()
    if not lines:
        raise HTTPException(400, f"{rel} is empty")
    start = max(1, int(start_line or 1))
    if start > len(lines):
        raise HTTPException(400, f"{rel} has only {len(lines)} lines")
    end = max(start, min(len(lines), int(end_line or len(lines))))
    whole = start == 1 and end == len(lines)
    last = min(end, start + MAX_EXPLAIN_LINES - 1)
    width = len(str(last))
    snippet = "\n".join(f"{n:>{width}}  {lines[n - 1]}" for n in range(start, last + 1))
    fence = _fence(snippet)
    lang_tag = FENCE_LANGS.get("." + rel.rsplit(".", 1)[-1].lower(), "") if "." in rel else ""
    what = f"the file `{rel}`" if whole else f"lines {start}–{end} of `{rel}`"
    at = f" at revision {rev}" if rev else ""
    more = (f"\nOnly lines {start}–{last} are shown; read the rest of the file with your tools.\n" if last < end else "")
    prompt = (
        f"Explain {what}{at} to the researcher.\n\n"
        "Write markdown with three short sections:\n"
        "1. **What it does**: purpose, inputs and outputs, the key steps (cite line numbers).\n"
        "2. **How it fits**: where it sits in the system: what calls it, what it relies on, which component or design "
        "decision it implements. Read neighbouring files with your tools when that helps.\n"
        "3. **Pitfalls**: edge cases, invariants a change could break, performance or numerical traps.\n"
        f"Be concrete and brief; do not restate the code line by line. Do not modify any file. {_language_rule(lang)}\n\n"
        f"{_architecture_note(pid, rel)}"
        f"{fence}{lang_tag}\n{snippet}\n{fence}\n{more}"
    )
    body = RunBody(panel="coding", purpose="code-explain", prompt=f"Explain {rel}:{start}-{end}{at}", permission="read")
    run = runner.start(spec_for(pid, body, tools=True, prompt=prompt))
    s = run.spec
    return {"run_id": run.id, "provider": s.provider, "model": s.model, "effort": s.effort, "fast": s.fast,
            "session_id": s.session_id, "path": rel, "start_line": start, "end_line": end}


# ------------------------------------------------------------------ fake answers (RD_FAKE_AGENT=1)

def _fake_review(spec: runner.RunSpec) -> str:
    findings = []
    for m in re.finditer(r"^\+\+\+ b/([^\t\n]+)\n@@ -\d+(?:,\d+)? \+(\d+)", spec.prompt, re.M):
        path, line = m.group(1), int(m.group(2))
        if not findings:
            findings.append({"file": path, "line": line, "severity": "medium",
                             "title": "Check the boundary case of the new code",
                             "body": "(fake reviewer) The changed block assumes a non-empty input; an empty batch would "
                                     "reach the division below with a zero denominator.",
                             "suggestion": "Return early when the input is empty, or guard the denominator."})
        elif len(findings) == 1:
            findings.append({"file": path, "line": line, "severity": "info", "title": "Behaviour change worth a test",
                             "body": "(fake reviewer) This file changes observable behaviour; no test covers it yet.",
                             "suggestion": None})
    return f"Reviewed the change (fake reviewer).\n\n```json\n{json.dumps({'findings': findings}, indent=2)}\n```\n"


def _fake_explain(spec: runner.RunSpec) -> str:
    m = re.search(r"Explain (?:the file |lines (\d+)–(\d+) of )`([^`]+)`", spec.prompt)
    path = m.group(3) if m else "the file"
    where = f"lines {m.group(1)}–{m.group(2)} of `{path}`" if m and m.group(1) else f"`{path}`"
    if "简体中文" in spec.prompt:
        return (f"**作用**：（示例回答）{where} 负责读取输入、做一次变换并返回结果。\n\n"
                "**在系统中的位置**：被上层模块调用，依赖同一组件内的工具函数。\n\n"
                "**注意事项**：空输入和边界值需要单独处理；修改时保持返回值的形状不变。\n")
    return (f"**What it does**: (fake explainer) {where} reads its input, applies one transformation and returns it.\n\n"
            "**How it fits**: called by the module above it; relies on helpers in the same component.\n\n"
            "**Pitfalls**: empty inputs and boundary values need their own handling; keep the output shape stable.\n")


runner.register_fake("code-review", _fake_review)
runner.register_fake("code-explain", _fake_explain)
