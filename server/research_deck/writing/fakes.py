"""Deterministic answers for the five review passes under RD_FAKE_AGENT=1 (tests and the offline demo).

They read the numbered document, the glossary and the DAG claims from the prompt, exactly as a real agent would,
and answer in the same JSON-lines contract:
  typo          teh → the, doubled words (the the), recieve → receive
  terminology   KV-cache vs KV cache, pre-fetcher vs prefetcher, and every glossary "avoid" form
  wording       in order to → to, a large number of → many, utilize → use
  consistency   a multiplier that disagrees with a DAG claim's value or with the document's other mentions (1.6× vs 1.7×)
  logic         overclaims (always, never, eliminates, guarantees) and claims whose DAG evidence is not fresh
"""
from __future__ import annotations

import json
import re

from ..agents import runner

_DOC = re.compile(r'<document[^>]*>\n(.*?)\n</document>', re.S)
_LINE = re.compile(r"^\s*(\d+)\| ?(.*)$")
_CLAIMS = re.compile(r"<claims>\n(.*?)\n</claims>", re.S)
_GLOSSARY_ROW = re.compile(r'^- preferred: "([^"]+)"(?:; avoid: (.*?))?(?:; note: .*)?$', re.M)
_MULTIPLIER = re.compile(r"(\d+(?:\.\d+)?)(\s*)(×|\$\\times\$|\\times|x)(?![A-Za-z0-9])")

REASONS = {
    "zh": {
        "teh": "拼写错误：应为 the。", "double": "重复了一个词。", "recieve": "拼写错误：i 与 e 的顺序（receive）。",
        "term": "同一术语出现两种写法，全文统一为“{to}”。", "wording": "更直接的说法，意思不变。",
        "number": "与{src}的数值 {to} 不一致。", "src_claim": " DAG 论点 {id} ", "src_doc": "文中其他位置",
        "overclaim": "措辞强于证据（“{word}”）；收窄说法，或给出支撑它的结果。",
        "unsupported": "这一论点的证据（{id}）状态为“{level}”，需复核或重跑后再下结论。",
        "summary": "找到 {n} 处问题。",
    },
    "en": {
        "teh": "Misspelling of “the”.", "double": "A word is repeated.", "recieve": "Misspelling: i before e here (receive).",
        "term": "The same term is written two ways; use “{to}” throughout.", "wording": "A more direct way to say the same thing.",
        "number": "Disagrees with the value {to} in {src}.", "src_claim": "DAG claim {id}", "src_doc": "the rest of the document",
        "overclaim": "Stronger than the evidence (“{word}”); narrow the wording or point to the result that supports it.",
        "unsupported": "This claim's evidence ({id}) is “{level}”; review or rerun it before stating the result.",
        "summary": "Found {n} issue(s).",
    },
}
TERM_PAIRS = [("KV cache", ["KV-cache"]), ("prefetcher", ["pre-fetcher"])]
WORDING = [(r"\bin order to\b", lambda m: "to"), (r"\ba large number of\b", lambda m: "many"),
           (r"\butiliz(e|es|ed|ing)\b", lambda m: "us" + m.group(1))]


class _Doc:
    """The numbered lines of the prompt's document, joined back into text with a line index."""

    def __init__(self, prompt: str):
        m = _DOC.search(prompt)
        self.lines: list[tuple[int, str]] = []
        for raw in (m.group(1).split("\n") if m else []):
            lm = _LINE.match(raw)
            if lm:
                self.lines.append((int(lm.group(1)), lm.group(2)))
        self.text = "\n".join(t for _, t in self.lines)
        self.starts, pos = [], 0
        for _, t in self.lines:
            self.starts.append(pos)
            pos += len(t) + 1
        self.lang = "zh" if "Simplified Chinese" in prompt else "en"

    def line_at(self, offset: int) -> int:
        i = 0
        while i + 1 < len(self.starts) and self.starts[i + 1] <= offset:
            i += 1
        return self.lines[i][0] if self.lines else 1

    def finding(self, kind: str, start: int, end: int, replacement: str | None, reason: str, confidence: float, **extra) -> dict:
        return {"kind": kind, "line": self.line_at(start), "quote": self.text[start:end],
                "before": self.text[max(0, start - 15):start], "replacement": replacement, "reason": reason,
                "confidence": confidence, **extra}


def _case_like(src: str, word: str) -> str:
    return word[:1].upper() + word[1:] if src[:1].isupper() and word[:1].islower() else word


def _answer(findings: list[dict], lang: str) -> str:
    lines = [json.dumps(f, ensure_ascii=False) for f in findings]
    lines.append(json.dumps({"done": True, "summary": REASONS[lang]["summary"].format(n=len(findings))}, ensure_ascii=False))
    return "\n".join(lines)


def _claims(prompt: str) -> list[dict]:
    m = _CLAIMS.search(prompt)
    out = []
    for line in (m.group(1).splitlines() if m else []):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def typo(spec: runner.RunSpec) -> str:
    d = _Doc(spec.prompt)
    R = REASONS[d.lang]
    out = []
    for m in re.finditer(r"\bteh\b", d.text, re.I):
        out.append(d.finding("typo", m.start(), m.end(), _case_like(m.group(0), "the"), R["teh"], 0.95))
    for m in re.finditer(r"\b(the|a|an|of|to|in|is|and)\s+\1\b", d.text, re.I):
        out.append(d.finding("typo", m.start(), m.end(), m.group(1), R["double"], 0.92))
    for m in re.finditer(r"\b([Rr])eciev(e|es|ed|er|ers|ing)\b", d.text):
        out.append(d.finding("typo", m.start(), m.end(), f"{m.group(1)}eceiv{m.group(2)}", R["recieve"], 0.95))
    return _answer(out, d.lang)


def _form_hits(text: str, form: str) -> list[re.Match]:
    return list(re.finditer(rf"(?<![\w-]){re.escape(form)}(s?)(?![\w-])", text, re.I))


def terminology(spec: runner.RunSpec) -> str:
    d = _Doc(spec.prompt)
    R = REASONS[d.lang]
    pairs = [(p, list(v)) for p, v in TERM_PAIRS]
    glossary = {}
    for m in _GLOSSARY_ROW.finditer(spec.prompt):
        glossary[m.group(1).lower()] = (m.group(1), re.findall(r'"([^"]+)"', m.group(2) or ""))
    for preferred, avoid in glossary.values():
        pairs = [(p, v) for p, v in pairs if p.lower() != preferred.lower() and preferred.lower() not in (x.lower() for x in v)]
        pairs.append((preferred, avoid))
    out = []
    for preferred, variants in pairs:
        forms = [preferred, *variants]
        hits = {f: _form_hits(d.text, f) for f in forms}
        if preferred.lower() in glossary:
            convention = preferred
        else:
            used = [f for f in forms if hits[f]]
            if len(used) < 2:
                continue
            convention = max(used, key=lambda f: (len(hits[f]), f == preferred))
        if not hits[convention] and convention != preferred:
            continue
        example = hits[convention][0] if hits[convention] else None
        for f in forms:
            if f == convention:
                continue
            for m in hits[f]:
                related = [{"line": d.line_at(example.start()), "quote": example.group(0)}] if example else []
                out.append(d.finding("term", m.start(), m.end(), _case_like(m.group(0), convention) + m.group(1),
                                     R["term"].format(to=convention), 0.85, related=related))
    return _answer(out, d.lang)


def wording(spec: runner.RunSpec) -> str:
    d = _Doc(spec.prompt)
    out = []
    for pattern, fix in WORDING:
        for m in re.finditer(pattern, d.text, re.I):
            out.append(d.finding("wording", m.start(), m.end(), _case_like(m.group(0), fix(m)), REASONS[d.lang]["wording"], 0.7))
    return _answer(out, d.lang)


def _fmt(v: float) -> str:
    return f"{v:g}"


def consistency(spec: runner.RunSpec) -> str:
    d = _Doc(spec.prompt)
    R = REASONS[d.lang]
    mentions = [(float(m.group(1)), m) for m in _MULTIPLIER.finditer(d.text)]
    truths: dict[float, str] = {}
    for c in _claims(spec.prompt):
        for v in (c.get("values") or {}).values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                truths.setdefault(float(v), c.get("id", ""))
    out = []
    for v, m in mentions:
        near = [t for t in truths if t != v and abs(v - t) <= 0.1 * abs(t)]
        if near:
            t = min(near, key=lambda t: abs(t - v))
            src = R["src_claim"].format(id=truths[t])
            out.append(d.finding("number", m.start(1), m.end(1), _fmt(t), R["number"].format(to=_fmt(t), src=src), 0.88,
                                 evidence_node=truths[t]))
    if not truths:
        counts: dict[float, list[re.Match]] = {}
        for v, m in mentions:
            counts.setdefault(v, []).append(m)
        values = list(counts)
        for i, v in enumerate(values):
            for w in values[:i]:
                if abs(v - w) <= 0.15 * max(abs(v), abs(w)):
                    # the more frequent value is the convention; on a tie, the one stated first
                    keep, odd = (w, v) if len(counts[w]) >= len(counts[v]) else (v, w)
                    ref = counts[keep][0]
                    for m in counts[odd]:
                        out.append(d.finding("number", m.start(1), m.end(1), _fmt(keep),
                                             R["number"].format(to=_fmt(keep), src=R["src_doc"]), 0.72,
                                             related=[{"line": d.line_at(ref.start()), "quote": ref.group(0)}]))
    return _answer(out, d.lang)


def logic(spec: runner.RunSpec) -> str:
    d = _Doc(spec.prompt)
    R = REASONS[d.lang]
    out = []
    for m in re.finditer(r"\b(always|never|eliminates?|guarantees?)\b", d.text, re.I):
        out.append(d.finding("overclaim", m.start(), m.end(), None, R["overclaim"].format(word=m.group(0)), 0.55))
    numbers = {n: i for i, (n, _) in enumerate(d.lines)}
    for c in _claims(spec.prompt):
        level, line = c.get("freshness"), c.get("line")
        if level in (None, "fresh") or line not in numbers:
            continue
        i = numbers[line]
        while i < len(d.lines) and (not d.lines[i][1].strip() or d.lines[i][1].lstrip().startswith("%")):
            i += 1
        if i >= len(d.lines):
            continue
        text = d.lines[i][1]
        lead = len(text) - len(text.lstrip())
        rest = text[lead:]
        end = re.search(r"[.!?](?=\s|$)|[。！？]", rest)      # a sentence ends at punctuation, not inside "1.6"
        sentence = (rest[:end.end()] if end else rest)[:200].rstrip()
        if not sentence:
            continue
        start = d.starts[i] + lead
        out.append(d.finding("unsupported", start, start + len(sentence), None,
                             R["unsupported"].format(id=c.get("id"), level=level), 0.75, evidence_node=c.get("id")))
    return _answer(out, d.lang)


RESPONDERS = {"typo": typo, "terminology": terminology, "wording": wording, "consistency": consistency, "logic": logic}


def register() -> None:
    for name, fn in RESPONDERS.items():
        runner.register_fake(f"review-{name}", fn)
