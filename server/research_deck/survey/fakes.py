"""Deterministic survey answers under RD_FAKE_AGENT=1 (tests and offline demos): queries from the idea's words, the
first candidates picked in order (two competitors, a baseline, the rest related), and a short survey."""
from __future__ import annotations

import json
import re

from ..agents import runner

_CAND = re.compile(r"^\[(\d+)\] (.+?) \(", re.M)


def _frame(spec: runner.RunSpec) -> str:
    idea = re.search(r"<idea>\n(.*?)\n</idea>", spec.prompt, re.S)
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", idea.group(1) if idea else "")[:12] or ["research"]
    queries = [" ".join(words[i:i + 3]) for i in range(0, min(len(words), 12), 3)][:4]
    return "```json\n" + json.dumps({
        "title": "Fake problem title", "summary": "Fake one-line summary.", "queries": queries,
        "problem": {"statement": "Fake statement.", "scope": "Fake scope.", "metric": "throughput", "threshold": "2x",
                    "direction": "higher", "kill_criteria": "Fake kill criteria."}}) + "\n```"


def _select(spec: runner.RunSpec) -> str:
    want = re.search(r"Pick the (\d+) candidates", spec.prompt)
    n = int(want.group(1)) if want else 5
    found = _CAND.findall(spec.prompt)[:n]
    roles = ["competitor", "competitor", "baseline"]
    picked = [{"i": int(i), "role": roles[k] if k < len(roles) else "related", "takeaway": f"Fake takeaway of {t}.",
               "delta": "Fake delta.", "closes_gap": False} for k, (i, t) in enumerate(found)]
    cites = " ".join(f"[{p['i']}]" for p in picked)
    return ("```json\n" + json.dumps({"selected": picked}) + "\n```\n\n```markdown\n## Existing work\n"
            f"Fake survey citing {cites}.\n```")


def register() -> None:
    runner.register_fake("survey-frame", _frame)
    runner.register_fake("survey-select", _select)
