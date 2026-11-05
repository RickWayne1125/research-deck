"""AI figure edits: the prompt sent to the visualization panel's agent, and the fake answer used under RD_FAKE_AGENT=1.

The agent gets the figure's kind, file, the current source (the editor's unsaved buffer when given), a summary of the
style tokens and the instruction, and must answer with the COMPLETE new source in ONE fenced block (```python or
```xml) followed by a one-paragraph change note. The client diffs it against the current source; nothing is written
until the researcher accepts.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

from ..agents import runner
from ..agents.api import RunBody, spec_for
from ..projects import project_root, research_dir
from ..util import safe_join
from . import figures, style

MAX_SOURCE_CHARS = 200_000
DATA_PREVIEW_LINES = 12
FENCE = {"matplotlib": "python", "drawio": "xml"}

KIND_RULES = {
    "matplotlib": (
        "Keep using the style helper (`import _rdstyle as rd`, `rd.figure()`, `rd.series_style(i)` / `rd.error_style(i)`, "
        "`rd.legend(ax)`, `rd.save(fig)`): it sets the font, size, colors and output path. Read values from the data "
        "files; never hard-code or invent measurements. Keep native error bars. The script must stay runnable as "
        "`python <file>` from the project root."
    ),
    "drawio": (
        "Return a complete, uncompressed draw.io document (<mxfile> with <diagram><mxGraphModel>…, or a bare "
        "<mxGraphModel>). Keep existing cell ids and geometry the instruction does not touch; use native cells and "
        "connectors (no embedded images of the whole graph), fontFamily=Helvetica and ONE fontSize everywhere, positions "
        "on the 8 px grid, the role colors below."
    ),
}


def build_prompt(pid: str, entry: dict, source: str, instruction: str) -> str:
    kind = entry["kind"]
    lang = FENCE[kind]
    tok = style.tokens(research_dir(pid))
    root = project_root(pid)
    lines = [
        "Edit one figure of this research project (Research Deck, Visualization panel).",
        "",
        f"Figure: \"{entry.get('title')}\" (id {entry['id']}, kind {figures.KIND_LABELS[kind]}), file {entry.get('source')}"
        + (f", linked DAG node {entry['node_id']}" if entry.get("node_id") else ""),
    ]
    data_blocks = []
    for rel in entry.get("data") or []:
        try:
            path = safe_join(root, rel)
            head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:DATA_PREVIEW_LINES]
        except (OSError, HTTPException):
            continue
        data_blocks.append(f"<data path=\"{rel}\" first-lines=\"{len(head)}\">\n" + "\n".join(head) + "\n</data>")
    if data_blocks:
        lines += ["", "Data files (first lines only; the script reads the full files):", *data_blocks]
    lines += [
        "", "<style>", "The project's figure style (the house style and .research/style.json):",
        style.summary(tok), "</style>",
        "", "<instruction>", instruction.strip(), "</instruction>",
        "", f"<current-source path=\"{entry.get('source')}\">", f"```{lang}", source.rstrip("\n"), "```", "</current-source>",
        "",
        f"Answer with the COMPLETE new file content in ONE fenced ```{lang} block (no other code blocks, no diff, no "
        "ellipses or placeholders), followed by ONE short paragraph that says what changed. Change only what the "
        "instruction asks for and keep the style above. " + KIND_RULES[kind],
    ]
    return "\n".join(lines)


def start_edit(pid: str, fid: str, instruction: str, source: str | None) -> dict:
    entry = figures.get_entry(pid, fid)
    kind = entry.get("kind")
    if kind not in FENCE:
        raise HTTPException(400, f"AI edits work on draw.io and matplotlib sources, not {figures.KIND_LABELS.get(kind, kind)} documents")
    if not instruction.strip():
        raise HTTPException(400, "describe the change")
    if source is None:
        path = figures.source_path(pid, entry)
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise HTTPException(404, f"no such file: {entry.get('source')}")
        except UnicodeDecodeError:
            raise HTTPException(415, "the figure source is not text")
    if len(source) > MAX_SOURCE_CHARS:
        raise HTTPException(413, f"the figure source is too large for an AI edit ({len(source)} characters)")
    body = RunBody(panel="visualization", purpose="figure",
                   prompt=f"[{figures.KIND_LABELS[kind]} · {entry.get('title')}] {instruction.strip()}",
                   context={"file": entry.get("source")})
    spec = spec_for(pid, body, tools=False, prompt=build_prompt(pid, entry, source, instruction))
    run = runner.start(spec)
    s = run.spec
    return {"run_id": run.id, "provider": s.provider, "model": s.model, "effort": s.effort, "fast": s.fast,
            "session_id": s.session_id}


# ---------------------------------------------------------------- RD_FAKE_AGENT=1

_SOURCE_RE = re.compile(r"<current-source[^>]*>\n```(\w+)\n([\s\S]*?)\n```\n</current-source>")
_INSTRUCTION_RE = re.compile(r"<instruction>\n([\s\S]*?)\n</instruction>")


def fake_figure_answer(spec: runner.RunSpec) -> str:
    """A deterministic edit: the same source with a marker comment naming the instruction, then a change note."""
    m = _SOURCE_RE.search(spec.prompt)
    instruction = (_INSTRUCTION_RE.search(spec.prompt) or [None, "edit"])[1].strip().replace("\n", " ")
    if not m:
        return "(fake figure agent) I could not find the figure source in the request."
    lang, source = m.group(1), m.group(2)
    if lang == "xml":
        note = instruction.replace("--", "—")
        marker = f"<!-- fake edit: {note} -->"
        new = source.replace("</mxGraphModel>", f"  {marker}\n    </mxGraphModel>", 1) if "</mxGraphModel>" in source else f"{source}\n{marker}"
    else:
        new = f"{source.rstrip()}\n# fake edit: {instruction}\n"
    return (f"```{lang}\n{new.rstrip()}\n```\n\nChanged: {instruction}. "
            "(Fake agent: a marker comment was added; no model was called.)")


runner.register_fake("figure", fake_figure_answer)
