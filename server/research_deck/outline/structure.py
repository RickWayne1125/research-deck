"""From an outline as the researcher wrote it to sections and items (a draft the researcher confirms before anything is
written to the map).

parse()    by the text's own structure: numbered lines, Markdown headings or \\section{…} start sections; bullets and
           indentation give items and their sub-items; "4 实现：…" puts the text after the colon in as an item, and
           "；" / "; " split it into several. Every item is its own step (nothing is parallel).
tidy()     one tool-less agent request on top: keeps the researcher's wording, maps the sections to the template,
           splits an item that says two things, and groups parallel items (with what the group is). Falls back to
           parse() when the agent is not available or its answer does not parse.

A draft: {"sections": [{"key": "<template key>|null", "title": "…", "items": [<step>…], "notes": {"<step>": "…"}}],
          "changes": ["…what the tidy-up changed…"]}; a step is an item or a list of parallel items; an item is
          {"text": "…", "children": [<step>…], "notes": {…}}.
"""
from __future__ import annotations

import json
import re
from typing import Any

SECTION_RE = re.compile(r"^\s*(?:#{1,3}\s+|§\s*)?(\d{1,2})(?:\.(?!\d))?[\s、.:：)）]+(.+)$")
HEADING_RE = re.compile(r"^\s*#{1,3}\s+(.+)$")
TEX_RE = re.compile(r"^\s*\\(?:sub)?section\*?\{(.+?)\}")
BULLET_RE = re.compile(r"^(\s*)(?:[-*•·+]|\d+[.)、]|[a-z][.)])\s+(.*)$")
SPLIT_RE = re.compile(r"\s*[；;]\s*")
MAX_ITEMS = 400


def _indent(s: str) -> int:
    return len(s.replace("\t", "    "))


def parse(text: str) -> dict:
    sections: list[dict] = []
    stack: list[tuple[int, list]] = []          # (indent, steps list) of the open items
    count = 0

    def add(target: list, t: str) -> dict:
        nonlocal count
        count += 1
        item = {"text": t.strip(), "children": []}
        target.append(item)
        return item

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip() or count >= MAX_ITEMS:
            continue
        b = BULLET_RE.match(line)
        if b and sections:
            ind, body = _indent(b.group(1)), b.group(2).strip()
            if not body:
                continue
            while stack and stack[-1][0] >= ind:
                stack.pop()
            target = stack[-1][1] if stack else sections[-1]["items"]
            item = add(target, body)
            stack.append((ind, item["children"]))
            continue
        m = SECTION_RE.match(line) or None
        h = HEADING_RE.match(line) if not m else None
        t = TEX_RE.match(line) if not (m or h) else None
        if (m or h or t) and _indent(line) - _indent(line.lstrip()) <= 1 and not b:
            title = (m.group(2) if m else h.group(1) if h else t.group(1)).strip()
            rest = ""
            for sep in ("：", ": "):
                if sep in title:
                    title, rest = title.split(sep, 1)
                    break
            sections.append({"key": None, "title": title.strip().rstrip("：:"), "items": []})
            stack = []
            for part in SPLIT_RE.split(rest.strip()) if rest.strip() else []:
                if part:
                    add(sections[-1]["items"], part)
            continue
        if sections:                              # a plain line under a section: an item of it
            add(sections[-1]["items"], line.strip())
            stack = []
    return {"sections": sections, "changes": []}


def match_template(draft: dict, template: dict) -> dict:
    """Give each draft section the key of the template section it names (by title, either language)."""
    names = {}
    for s in template["sections"]:
        for t in (s["title"]["zh"], s["title"]["en"]):
            names[re.sub(r"\s+", "", t.lower())] = s["key"]
    for sec in draft["sections"]:
        if not sec.get("key"):
            sec["key"] = names.get(re.sub(r"\s+", "", str(sec.get("title") or "").lower()))
    return draft


SYSTEM = ("You help a researcher turn their paper outline into a logic chain per section. Keep their wording; never "
          "invent claims, numbers or results. Answer with one ```json block and nothing else.")


def prompt(text: str, template: dict, lang: str) -> str:
    secs = "\n".join(f"- {s['key']}: {s['title']['en']} / {s['title']['zh']} — {s['role']['en']}" for s in template["sections"])
    language = "Chinese" if lang == "zh" else "English"
    return f"""The template's sections:
{secs}

<outline>
{text.strip()[:12000]}
</outline>

Turn the outline into sections of items. Rules:
- Keep the researcher's words. Only restructure: split an item that says two things into two, merge nothing.
- Map each section to a template key when it is that section; otherwise key null with the researcher's title.
- In each section the items are steps in order: each item follows from the ones before. Items that are parallel (they
  together lead to the next item, or are siblings such as two components or three comparisons) form one step, a list;
  say what such a group is in notes, keyed by the step's index (0-based), e.g. {{"1": "two components"}}.
- Indented items stay sub-items (children) of the item above them.
- In changes, list in {language} what you restructured, one short line each (nothing when you changed nothing).
Answer with ONE ```json block:
{{"sections": [{{"key": "<template key>|null", "title": "<title>", "items": [<step>...], "notes": {{}}}}], "changes": ["..."]}}
where a step is either an item {{"text": "...", "children": [<step>...]}} or a list of such items."""


def _clean_steps(steps: Any, depth: int = 0) -> list:
    out = []
    for step in steps if isinstance(steps, list) else []:
        group = step if isinstance(step, list) else [step]
        items = []
        for it in group:
            if isinstance(it, dict) and str(it.get("text") or "").strip():
                items.append({"text": str(it["text"]).strip()[:600],
                              "children": _clean_steps(it.get("children"), depth + 1) if depth < 6 else []})
        if items:
            out.append(items if len(items) > 1 else items[0])
    return out


def parse_answer(answer: str, template: dict) -> dict | None:
    from ..survey.prompts import parse_json
    data = parse_json(answer)
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        return None
    keys = {s["key"] for s in template["sections"]}
    sections = []
    for s in data["sections"]:
        if not isinstance(s, dict):
            continue
        notes = s.get("notes") if isinstance(s.get("notes"), dict) else {}
        sections.append({"key": s.get("key") if s.get("key") in keys else None, "title": str(s.get("title") or "").strip()[:120],
                         "items": _clean_steps(s.get("items")),
                         "notes": {str(k): str(v)[:80] for k, v in notes.items() if str(k).isdigit()}})
    if not any(s["items"] for s in sections):
        return None
    return {"sections": sections, "changes": [str(c)[:200] for c in data.get("changes") or [] if str(c).strip()][:12]}


def tidy(pid: str, text: str, template: dict, lang: str, use_agent: bool = True) -> dict:
    """The structured draft: the agent's when it answers, else the text's own structure."""
    base = match_template(parse(text), template)
    if not use_agent:
        return {**base, "by": "parse"}
    from ..agents import catalog, runner, sessions
    from ..agents.api import RunBody, spec_for
    try:
        b = sessions.get_binding(pid)
        body = RunBody(panel="project", prompt=prompt(text, template, lang), purpose="outline-structure", ephemeral=True,
                       effort=catalog.clamp_effort(b["provider"], b["model"], "medium"))
        spec = spec_for(pid, body, system=SYSTEM, tools=False)
        spec.timeout_s = 300
        run = runner.run_blocking(spec, timeout=330)
        draft = parse_answer(run.text, template) if run.status == "done" else None
    except Exception:  # noqa: BLE001 — the text's own structure is always there
        draft = None
    if draft is None:
        return {**base, "by": "parse"}
    return {**match_template(draft, template), "by": "agent"}


def fake_answer(spec) -> str:
    """RD_FAKE_AGENT: the text's own structure, as the agent's answer."""
    m = re.search(r"<outline>\n(.*?)\n</outline>", spec.prompt, re.S)
    draft = parse(m.group(1) if m else "")
    return "```json\n" + json.dumps({**draft, "changes": ["(fake) kept the structure as written"]}, ensure_ascii=False) + "\n```"
