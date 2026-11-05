"""The survey's two agent requests and the parsing of their answers.

frame   the idea → a title and one-line summary, 4–6 English search queries, and the problem node's fields
        (statement, scope, success metric and threshold, kill criteria) in the idea's language
select  the idea, the problem and the ranked candidates (title, year, venue, citations, abstract) → the papers to keep,
        each with a role (competitor, baseline, related, background), a takeaway, how it differs from the idea and
        whether it already closes the gap; then the survey itself in Markdown, citing papers as [n]
Both are one-shot requests without tools: the agent answers from the prompt alone.
"""
from __future__ import annotations

import json
import re
from typing import Any

SYSTEM = ("You help a researcher start a research project from an idea. Answer with exactly the fenced blocks asked "
          "for and nothing else. Never invent papers, numbers or results that are not in the prompt.")
ROLES = ("competitor", "baseline", "related", "background")
_FENCE = re.compile(r"```([A-Za-z]*)[^\n]*\n(.*?)```", re.S)


def language(text: str) -> str:
    return "zh" if len(re.findall(r"[一-鿿]", text)) >= 6 else "en"


def frame(name: str, idea: str, attachment: str | None) -> str:
    lang = "Chinese" if language(idea) == "zh" else "English"
    note = f"\nThe researcher also attached {attachment}; its text is not included here.\n" if attachment else ""
    return f"""Project name: {name}

<idea>
{idea.strip()[:12000]}
</idea>
{note}
Read the idea and answer with ONE ```json block:
{{"title": "<one-line title of the research problem>",
  "summary": "<one sentence: what the project wants to show>",
  "queries": ["<4 to 6 short English search queries for existing work, from specific to broad>"],
  "problem": {{"statement": "<the problem: on which workloads / models / hardware, which metric falls short, why it matters>",
              "scope": "<what is in and out of scope>",
              "metric": "<the target metric>", "threshold": "<the success threshold, as stated or implied>",
              "direction": "higher|lower",
              "kill_criteria": "<the results that would make the researcher stop>"}}}}
Write title, summary and the problem's text fields in {lang}; the queries in English. Where the idea does not say
something, write what is missing instead of inventing it."""


def select(name: str, idea: str, problem: dict, candidates: list[dict], count: int) -> str:
    lang = "Chinese" if language(idea) == "zh" else "English"
    lines = []
    for i, p in enumerate(candidates, 1):
        meta = ", ".join(x for x in (str(p.get("year") or ""), p.get("venue") or "",
                                    f"{p['citations']} citations" if p.get("citations") else "") if x)
        lines.append(f"[{i}] {p.get('title')} ({meta})\n{(p.get('abstract') or 'no abstract')[:700]}")
    listing = "\n\n".join(lines)
    return f"""Project: {name}

<idea>
{idea.strip()[:6000]}
</idea>

<problem>
{json.dumps(problem, ensure_ascii=False)}
</problem>

<candidates>
{listing}
</candidates>

Pick the {count} candidates most relevant to this idea (fewer if fewer are relevant). Answer with TWO fenced blocks.

1. A ```json block: {{"selected": [{{"i": <candidate number>, "role": "competitor|baseline|related|background",
   "takeaway": "<what the paper does and finds, 1-2 sentences>", "delta": "<how the idea differs from it>",
   "closes_gap": <true if it already solves what the idea wants>}}]}}
   competitor = solves the same problem in another way; baseline = a system the idea must be compared against;
   related = same area, different problem; background = what the idea builds on. Mark every competitor with a
   delta. Judge from the abstracts only.

2. A ```markdown block: the survey, in {lang}, with these sections: the problem in two sentences; existing work,
   grouped into 2-4 approaches, each paper cited as [n] with its candidate number; the gaps the idea could fill
   (as questions to check, not claims); the baselines to reproduce first. No title line."""


def blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).lower(), m.group(2)) for m in _FENCE.finditer(text or "")]


def parse_json(text: str) -> Any:
    for lang, body in blocks(text):
        if lang in ("json", ""):
            try:
                return json.loads(body)
            except ValueError:
                continue
    s = (text or "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except ValueError:
            return None
    return None


def parse_frame(text: str) -> dict | None:
    data = parse_json(text)
    if not isinstance(data, dict):
        return None
    queries = [str(q).strip() for q in data.get("queries") or [] if str(q).strip()][:6]
    if not queries:
        return None
    problem = data.get("problem") if isinstance(data.get("problem"), dict) else {}
    return {"title": str(data.get("title") or "").strip(), "summary": str(data.get("summary") or "").strip(),
            "queries": queries, "problem": {k: str(problem.get(k) or "").strip() for k in
                                           ("statement", "scope", "metric", "threshold", "direction", "kill_criteria")}}


def parse_select(text: str, n_candidates: int) -> tuple[list[dict], str]:
    data = parse_json(text)
    picked, seen = [], set()
    for item in (data or {}).get("selected") or [] if isinstance(data, dict) else []:
        try:
            i = int(item.get("i"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 1 <= i <= n_candidates or i in seen:
            continue
        seen.add(i)
        role = item.get("role") if item.get("role") in ROLES else "related"
        picked.append({"i": i, "role": role, "takeaway": str(item.get("takeaway") or "").strip(),
                       "delta": str(item.get("delta") or "").strip(), "closes_gap": bool(item.get("closes_gap"))})
    survey = next((body.strip() for lang, body in blocks(text) if lang in ("markdown", "md")), "")
    return picked, survey
