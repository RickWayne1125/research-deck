"""The writing panel's state under <project>/.research/writing/ (docs/API.md § On-disk formats).

  glossary.yaml        {"terms": [{"term", "preferred", "avoid": [], "note"}]}
  rules.json           {"rules": LearnedRule[]}: what later checks follow; a rejection with a reason adds one
  dismissed.json       {"version": 1, "items": [{"fp", "pass", "path", "quote", "replacement", "at"}]}: rejected
                       suggestions, so no check proposes the same change again
  reviews/<id>.json    ReviewResult
"""
from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ..projects import research_dir
from ..util import new_id, now_iso, read_json, read_yaml, write_json, write_yaml

PASSES = ("typo", "terminology", "wording", "consistency", "logic")
RULE_PASSES = (*PASSES, "all")
MAX_DISMISSED = 600
MAX_RULES = 400
MAX_REVIEWS = 200

_lock = threading.RLock()
_review_locks: dict[str, threading.RLock] = defaultdict(threading.RLock)


def writing_dir(pid: str) -> Path:
    d = research_dir(pid) / "writing"
    d.mkdir(exist_ok=True)
    return d


# ------------------------------------------------------------------ glossary

def _clean_term(t: dict) -> dict | None:
    term = str(t.get("term") or "").strip()
    preferred = str(t.get("preferred") or "").strip() or term
    if not term and not preferred:
        return None
    avoid = t.get("avoid") or []
    if isinstance(avoid, str):
        avoid = avoid.split(",")
    avoid = [a.strip() for a in avoid if str(a).strip() and str(a).strip() != preferred]
    return {"term": term or preferred, "preferred": preferred, "avoid": list(dict.fromkeys(avoid)),
            "note": str(t.get("note") or "").strip()}


def load_glossary(pid: str) -> dict:
    data = read_yaml(writing_dir(pid) / "glossary.yaml", None) or {}
    terms = [c for c in (_clean_term(t) for t in data.get("terms") or [] if isinstance(t, dict)) if c]
    return {"terms": terms}


def save_glossary(pid: str, terms: list[dict]) -> dict:
    clean = [c for c in (_clean_term(t) for t in terms) if c]
    with _lock:
        write_yaml(writing_dir(pid) / "glossary.yaml", {"terms": clean})
    return {"terms": clean}


# ------------------------------------------------------------------ learned rules

def _clean_rule(r: dict) -> dict | None:
    text = str(r.get("text") or "").strip()
    if not text:
        return None
    p = r.get("pass") if r.get("pass") in RULE_PASSES else "all"
    out = {"id": str(r.get("id") or new_id("rule-")), "pass": p, "text": text[:1000], "on": r.get("on", True) is not False,
           "created_at": str(r.get("created_at") or now_iso())}
    for key in ("example", "source", "by"):
        if r.get(key):
            out[key] = r[key]
    return out


def load_rules(pid: str) -> dict:
    data = read_json(writing_dir(pid) / "rules.json", None) or {}
    return {"rules": [c for c in (_clean_rule(r) for r in data.get("rules") or [] if isinstance(r, dict)) if c]}


def save_rules(pid: str, rules: list[dict]) -> dict:
    clean = [c for c in (_clean_rule(r) for r in rules) if c][-MAX_RULES:]
    with _lock:
        write_json(writing_dir(pid) / "rules.json", {"rules": clean})
    return {"rules": clean}


def add_rule(pid: str, pass_: str, text: str, *, example: dict | None = None, source: dict | None = None,
             by: str | None = None) -> dict:
    with _lock:
        rules = load_rules(pid)["rules"]
        rule = _clean_rule({"pass": pass_, "text": text, "example": example, "source": source, "by": by})
        rules.append(rule)
        save_rules(pid, rules)
    return rule


def rules_for(pid: str, pass_: str) -> list[dict]:
    return [r for r in load_rules(pid)["rules"] if r["on"] and r["pass"] in (pass_, "all")]


# ------------------------------------------------------------------ dismissed suggestions

def load_dismissed(pid: str) -> list[dict]:
    data = read_json(writing_dir(pid) / "dismissed.json", None) or {}
    return [d for d in data.get("items") or [] if isinstance(d, dict) and d.get("fp")]


def dismiss(pid: str, finding: dict, path: str) -> None:
    with _lock:
        items = [d for d in load_dismissed(pid) if d["fp"] != finding.get("fp")]
        items.append({"fp": finding.get("fp"), "pass": finding.get("pass"), "path": path, "quote": finding.get("quote", "")[:300],
                      "replacement": (finding.get("replacement") or "")[:300], "at": now_iso()})
        write_json(writing_dir(pid) / "dismissed.json", {"version": 1, "items": items[-MAX_DISMISSED:]})


def undismiss(pid: str, fp: str) -> None:
    with _lock:
        items = load_dismissed(pid)
        kept = [d for d in items if d["fp"] != fp]
        if len(kept) != len(items):
            write_json(writing_dir(pid) / "dismissed.json", {"version": 1, "items": kept})


# ------------------------------------------------------------------ reviews

def _review_file(pid: str, review_id: str) -> Path:
    safe = "".join(c for c in review_id if c.isalnum() or c in "-_")
    return writing_dir(pid) / "reviews" / f"{safe}.json"


def load_review(pid: str, review_id: str) -> dict | None:
    return read_json(_review_file(pid, review_id), None)


def save_review(pid: str, review: dict) -> None:
    with _review_locks[review["review_id"]]:
        write_json(_review_file(pid, review["review_id"]), review)


@contextmanager
def editing_review(pid: str, review_id: str) -> Iterator[dict | None]:
    """Read-modify-write one review under its lock (the worker and accept/reject requests share the file)."""
    with _review_locks[review_id]:
        review = load_review(pid, review_id)
        yield review
        if review is not None:
            write_json(_review_file(pid, review_id), review)


def update_review(pid: str, review_id: str, fn: Callable[[dict], None]) -> dict | None:
    with editing_review(pid, review_id) as review:
        if review is not None:
            fn(review)
        return review


def list_reviews(pid: str, path: str | None = None, limit: int = 20) -> list[dict]:
    d = writing_dir(pid) / "reviews"
    if not d.is_dir():
        return []
    out = []
    for f in d.glob("*.json"):
        r = read_json(f, None)
        if isinstance(r, dict) and r.get("review_id") and (not path or r.get("path") == path):
            out.append(r)
    out.sort(key=lambda r: (str(r.get("created_at") or ""), r.get("created_ns") or 0), reverse=True)
    return out[:limit]


def prune_reviews(pid: str, keep: int = MAX_REVIEWS) -> None:
    """Keep the newest `keep` finished reviews; findings of old reviews are history the panel no longer shows."""
    reviews = list_reviews(pid, limit=10_000)
    for r in reviews[keep:]:
        if r.get("status") != "running":
            _review_file(pid, r["review_id"]).unlink(missing_ok=True)
