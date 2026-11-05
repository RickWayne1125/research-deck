"""The finding contract shared by every pass.

An agent answers with JSON lines (or one fenced json array, or {"findings": [...]}) of
  {kind, quote, before, replacement, reason, confidence, line, related?, evidence_node?}
and a closing {"done": true, "summary": "..."}. Each finding is checked against the text that was reviewed:
the quote must occur in it (`before` and `line` pick the occurrence when it occurs more than once; whitespace is
compared loosely), the replacement must differ from the quote, and the same change at the same place is kept once.
The stored `quote` and `before` are copied from the text itself, so the editor can find the place exactly.

`fp` (pass | quote | replacement) is the dismissal key: rejecting a suggestion keeps every later check from
proposing the same change again, wherever it would be.
"""
from __future__ import annotations

import hashlib
import json
import re

KINDS = {
    "typo": ("typo", "grammar", "punctuation", "latex", "math"),
    "terminology": ("term", "acronym"),
    "wording": ("wording",),
    "consistency": ("number", "notation", "claim", "reference", "term"),
    "logic": ("unsupported", "leap", "gap", "order", "overclaim"),
}
DEFAULT_KIND = {"typo": "typo", "terminology": "term", "wording": "wording", "consistency": "number", "logic": "unsupported"}
# Passes whose findings may carry no replacement (a question for the author rather than an edit).
ADVISORY_PASSES = ("consistency", "logic")
MAX_QUOTE = {"typo": 300, "terminology": 200, "wording": 700, "consistency": 400, "logic": 700}
MIN_CONFIDENCE = 0.3
BEFORE_CHARS = 20
_NODE_ID = re.compile(r"^[a-z]+\.[A-Za-z0-9_.\-]+$")
_LINE_PREFIX = re.compile(r"^\s*\d+[|:]\s?")


def fingerprint(pass_: str, quote: str, replacement: str | None) -> str:
    return hashlib.sha256(f"{pass_}|{quote}|{replacement or ''}".encode()).hexdigest()[:16]


# ------------------------------------------------------------------ parsing

def _objects_in(value) -> list[dict]:
    if isinstance(value, dict):
        if isinstance(value.get("findings"), list):
            return [v for v in value["findings"] if isinstance(v, dict)] + ([value] if value.get("done") else [])
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def parse_answer(text: str) -> tuple[list[dict], str | None]:
    """(raw findings, the closing summary) from an agent's answer in any of the accepted shapes."""
    text = text or ""
    objects: list[dict] = []
    fences = re.findall(r"```(?:json|jsonl)?[^\n]*\n(.*?)```", text, re.S)
    for chunk in [*fences, text]:
        s = chunk.strip()
        try:
            objects = _objects_in(json.loads(s))
        except (json.JSONDecodeError, ValueError):
            objects = []
        if not objects:
            # JSON lines: every line that parses as an object
            for line in s.splitlines():
                line = line.strip().rstrip(",")
                if line.startswith("{") and line.endswith("}"):
                    try:
                        objects.extend(_objects_in(json.loads(line)))
                    except (json.JSONDecodeError, ValueError):
                        continue
        if not objects:
            # a bare array somewhere inside prose
            start, end = s.find("["), s.rfind("]")
            if 0 <= start < end:
                try:
                    objects = _objects_in(json.loads(s[start:end + 1]))
                except (json.JSONDecodeError, ValueError):
                    objects = []
        if objects:
            break
    summary = next((str(o.get("summary") or "") for o in objects if o.get("done")), None)
    return [o for o in objects if not o.get("done") and "quote" in o], summary or None


# ------------------------------------------------------------------ locating a quote

def _loose(s: str) -> tuple[str, list[int]]:
    """s with whitespace runs collapsed to one space, and the index in s of each kept character."""
    out: list[str] = []
    index: list[int] = []
    prev_space = False
    for i, c in enumerate(s):
        if c.isspace():
            if prev_space:
                continue
            out.append(" ")
            prev_space = True
        else:
            out.append(c)
            prev_space = False
        index.append(i)
    return "".join(out), index


def _common_tail(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _occurrences(text: str, quote: str) -> list[tuple[int, int]]:
    hits, i = [], text.find(quote)
    while i >= 0:
        hits.append((i, i + len(quote)))
        i = text.find(quote, i + 1)
    if hits:
        return hits
    lt, index = _loose(text)
    lq = _loose(quote)[0].strip()
    if not lq:
        return []
    i = lt.find(lq)
    while i >= 0:
        hits.append((index[i], index[i + len(lq) - 1] + 1))
        i = lt.find(lq, i + 1)
    return hits


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def locate(text: str, quote: str, before: str = "", line: int | None = None) -> tuple[int, int] | None:
    """(start, end) of the quote in text; where it occurs more than once, the place whose preceding text ends like
    `before`, then the one nearest `line`."""
    if not quote:
        return None
    hits = _occurrences(text, quote)
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    want = _loose(before or "")[0][-60:]

    def score(h: tuple[int, int]) -> tuple[int, int]:
        tail = _common_tail(_loose(text[max(0, h[0] - 80):h[0]])[0], want) if want else 0
        dist = abs(line_of(text, h[0]) - line) if line else 0
        return (-tail, dist)

    return min(hits, key=score)


# ------------------------------------------------------------------ validation

def _confidence(value) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.6
    if c > 1 and c <= 100:      # a percentage
        c /= 100
    return max(0.0, min(1.0, c))


def _line(value) -> int | None:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


class Validator:
    """Validates the raw findings of one review (all passes), numbering and de-duplicating them."""

    def __init__(self, text: str, *, scope: tuple[int, int] | None = None, dismissed: set[str] | None = None,
                 node_ids: set[str] | None = None):
        self.text = text
        self.scope = scope
        self.dismissed = dismissed or set()
        self.node_ids = node_ids or set()
        self.seen: set[tuple] = set()
        self.count = 0
        self.dropped: dict[str, int] = {}

    def _drop(self, why: str) -> None:
        self.dropped[why] = self.dropped.get(why, 0) + 1

    def check(self, pass_: str, raw: dict) -> dict | None:
        text = self.text
        quote = raw.get("quote")
        quote = "" if quote is None else str(quote)
        if not quote.strip():
            return self._drop("empty quote")
        if len(quote) > MAX_QUOTE.get(pass_, 500):
            return self._drop("quote too long")
        replacement = raw.get("replacement")
        if replacement is not None:
            replacement = str(replacement)
        if replacement is None and pass_ not in ADVISORY_PASSES:
            return self._drop("no replacement")
        if replacement is not None and replacement == quote:
            return self._drop("replacement equals quote")
        confidence = _confidence(raw.get("confidence"))
        if confidence < MIN_CONFIDENCE:
            return self._drop("low confidence")
        hint = _line(raw.get("line"))
        before = str(raw.get("before") or "")
        at = locate(text, quote, before, hint)
        if at is None and _LINE_PREFIX.match(quote):       # the agent copied the line-number prefix
            quote = _LINE_PREFIX.sub("", quote)
            at = locate(text, quote, before, hint)
        if at is None:
            return self._drop("quote not found")
        start, end = at
        quote = text[start:end]
        if replacement is not None and replacement == quote:
            return self._drop("replacement equals quote")
        line = line_of(text, start)
        if self.scope and not (self.scope[0] <= line <= self.scope[1]):
            return self._drop("outside the range")
        fp = fingerprint(pass_, quote, replacement)
        if fp in self.dismissed:
            return self._drop("dismissed before")
        if (fp, start) in self.seen or (quote, start, replacement) in self.seen:
            return self._drop("duplicate")
        self.seen.update({(fp, start), (quote, start, replacement)})
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in KINDS.get(pass_, ()):
            kind = DEFAULT_KIND.get(pass_, "wording")
        related = []
        for r in raw.get("related") or []:
            q = str((r or {}).get("quote") or "") if isinstance(r, dict) else str(r or "")
            pos = locate(text, q, "", _line((r or {}).get("line")) if isinstance(r, dict) else None) if q else None
            if pos and pos[0] != start:
                related.append({"quote": text[pos[0]:pos[1]], "line": line_of(text, pos[0])})
        node = raw.get("evidence_node")
        node = str(node) if node and (str(node) in self.node_ids or _NODE_ID.match(str(node))) else None
        self.count += 1
        return {
            "id": f"{pass_[:3]}-{self.count}", "pass": pass_, "kind": kind, "quote": quote,
            "before": text[max(0, start - BEFORE_CHARS):start], "replacement": replacement,
            "reason": str(raw.get("reason") or "").strip()[:600], "confidence": round(confidence, 2),
            "line": line, "related": related[:6], "status": "open", "evidence_node": node, "fp": fp, "offset": start,
        }
