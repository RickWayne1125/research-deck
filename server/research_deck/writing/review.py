"""Run the revision pipeline over one document and record the ReviewResult.

start() writes the review (status running, every chosen pass pending), snapshots the document once ("before
check", skipped when unchanged) and runs the passes in the fixed order in a worker thread. Each pass is one
ephemeral, tool-less request on the writing panel's backend (agents.api.spec_for + runner.run_blocking), at the
pass's effort clamped to what the bound model supports. After each pass the validated findings are appended, the
file is saved and topic "writing" is published, so the editor tints findings as they arrive. One failing pass does
not stop the others; cancel() stops the running request and skips the rest.
"""
from __future__ import annotations

import logging
import threading
import time

from fastapi import HTTPException

from ..agents import catalog, runner, sessions
from ..agents.api import RunBody, spec_for
from ..events import hub
from ..util import new_id, now_iso, sha256_text
from . import context, docs, prompts, store, versions
from .findings import Validator, parse_answer

log = logging.getLogger("research_deck.writing")
MAX_REVIEW_CHARS = 160_000
EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")

# review_id -> {"cancel": bool, "run_id": str | None}; only reviews running in this process
_ACTIVE: dict[str, dict] = {}
_ACTIVE_LOCK = threading.Lock()


def effort_for(pid: str, pass_: str, words: int) -> str:
    """The pass's effort, clamped to the writing panel's model: the strongest supported effort not above the wanted
    one (or the weakest it has, when all are above)."""
    wanted = prompts.EFFORT[pass_]
    if pass_ == "typo" and words < prompts.SHORT_TYPO_WORDS:
        wanted = "low"
    b = sessions.get_binding(pid, "writing")
    info = catalog.model_info(b["provider"], b["model"]) or {}
    efforts = [e for e in info.get("efforts") or [] if e in EFFORT_ORDER]
    if efforts and wanted not in efforts:
        rank = EFFORT_ORDER.index(wanted)
        below = [e for e in efforts if EFFORT_ORDER.index(e) <= rank]
        wanted = max(below, key=EFFORT_ORDER.index) if below else min(efforts, key=EFFORT_ORDER.index)
    return catalog.normalize(b["provider"], b["model"], wanted, b.get("fast"))[1]


def _publish(pid: str, review: dict, **extra) -> None:
    counts = {}
    for f in review.get("findings") or []:
        counts[f["pass"]] = counts.get(f["pass"], 0) + 1
    hub.publish(pid, "writing", {"kind": "review", "review_id": review["review_id"], "path": review["path"],
                                 "status": review["status"], "progress": review["progress"], "counts": counts, **extra})


def _order(passes: list[str] | None) -> list[str]:
    chosen = set(passes or prompts.PIPELINE)
    bad = chosen - set(prompts.PIPELINE)
    if bad:
        raise HTTPException(400, f"unknown pass: {', '.join(sorted(bad))}")
    return [p for p in prompts.PIPELINE if p in chosen]


def start(pid: str, path: str, passes: list[str] | None = None, text: str | None = None,
          range_: dict | None = None, lang: str | None = None, actor: str | None = None) -> dict:
    order = _order(passes)
    if not order:
        raise HTTPException(400, "choose at least one pass")
    if text is None:
        path, text = docs.read_doc(pid, path)
    else:
        path = docs.resolve_doc(pid, path)[1]
    lines = text.split("\n")
    scope = None
    if range_:
        a, b = int(range_.get("start_line") or 1), int(range_.get("end_line") or len(lines))
        a, b = max(1, min(a, b)), min(len(lines), max(a, b))
        scope = (a, b)
    # Cut a very long document at a line boundary; the prompt says where.
    truncated_at = None
    if len(text) > MAX_REVIEW_CHARS:
        used, n = 0, 0
        while n < len(lines) and used + len(lines[n]) + 1 <= MAX_REVIEW_CHARS:
            used += len(lines[n]) + 1
            n += 1
        truncated_at = max(1, n)
    review = {
        "review_id": new_id("rv-"), "path": path, "passes": order, "findings": [], "status": "running",
        "progress": {p: "pending" for p in order}, "created_at": now_iso(), "created_ns": time.time_ns(), "finished_at": None,
        "lang": "en" if lang == "en" else "zh", "range": {"start_line": scope[0], "end_line": scope[1]} if scope else None,
        "base_sha": sha256_text(text), "words": docs.word_count(text, docs.doc_kind(path) or "md"),
        "summaries": {}, "pass_errors": {}, "agents": {}, "truncated_at": truncated_at, "by": actor,
    }
    store.save_review(pid, review)
    store.prune_reviews(pid)
    try:
        versions.snapshot(pid, path, "before check", auto=True)
    except HTTPException:
        pass                                  # an unsaved new document has no file to snapshot yet
    with _ACTIVE_LOCK:
        _ACTIVE[review["review_id"]] = {"cancel": False, "run_id": None}
    _publish(pid, review)
    threading.Thread(target=_work, args=(pid, review["review_id"], text, scope, truncated_at), daemon=True,
                     name=f"review-{review['review_id']}").start()
    return review


def _work(pid: str, review_id: str, text: str, scope: tuple[int, int] | None, truncated_at: int | None) -> None:
    review = store.load_review(pid, review_id)
    state = _ACTIVE.get(review_id) or {}
    path, kind, lang = review["path"], docs.doc_kind(review["path"]) or "md", review["lang"]
    lines = text.split("\n")[: truncated_at or None]
    claims = context.claims_for(pid, path)
    validator = Validator(text, scope=scope, dismissed={d["fp"] for d in store.load_dismissed(pid)},
                          node_ids={c["id"] for c in claims})
    glossary = store.load_glossary(pid)["terms"]
    experiments: list[dict] | None = None
    words = review.get("words") or 0
    if scope:
        words = docs.word_count("\n".join(lines[scope[0] - 1:scope[1]]), kind)
    try:
        for pass_ in review["passes"]:
            if state.get("cancel"):
                break
            store.update_review(pid, review_id, lambda r: r["progress"].__setitem__(pass_, "running"))
            _publish(pid, store.load_review(pid, review_id), current=pass_)
            if pass_ == "consistency" and experiments is None:
                experiments = context.experiments_for(pid)
            dismissed = [d for d in store.load_dismissed(pid) if d.get("pass") == pass_]
            dismissed.sort(key=lambda d: d.get("path") == path)        # this document's last, so they survive the cut
            prompt = prompts.build(pass_, path=path, kind=kind, lines=lines, scope=scope, lang=lang, glossary=glossary,
                                   rules=store.rules_for(pid, pass_), dismissed=dismissed, claims=claims,
                                   experiments=experiments, truncated_at=truncated_at)
            body = RunBody(panel="writing", prompt=prompt, purpose=f"review-{pass_}", ephemeral=True,
                           effort=effort_for(pid, pass_, words))
            spec = spec_for(pid, body, system=prompts.SYSTEM, tools=False)
            spec.timeout_s = prompts.TIMEOUT_S[pass_]
            run = runner.start(spec)
            state["run_id"] = run.id
            hung = not run.wait(spec.timeout_s + 30)
            if hung:                          # the runner's own timeout should have ended it; make sure
                runner.cancel(run.id)
                run.wait(10)
            state["run_id"] = None
            agent = {"provider": spec.provider, "model": spec.model, "effort": spec.effort, "run_id": run.id}
            if state.get("cancel"):
                store.update_review(pid, review_id, lambda r: (r["progress"].__setitem__(pass_, "error"),
                                                               r["pass_errors"].__setitem__(pass_, "cancelled")))
                break
            if run.status != "done":
                message = (f"timed out after {spec.timeout_s}s" if hung else run.error) or "the agent did not answer"
                store.update_review(pid, review_id, lambda r: (r["progress"].__setitem__(pass_, "error"),
                                                               r["pass_errors"].__setitem__(pass_, message[:500]),
                                                               r["agents"].__setitem__(pass_, agent)))
                _publish(pid, store.load_review(pid, review_id), current=pass_)
                continue
            raw, summary = parse_answer(run.text)
            found = [f for f in (validator.check(pass_, item) for item in raw) if f]
            if not raw and summary is None and run.text.strip():
                log.info("review %s pass %s: no findings parsed from the answer", review_id, pass_)

            def finish(r: dict) -> None:
                r["findings"].extend(found)
                r["progress"][pass_] = "done"
                r["agents"][pass_] = {**agent, "raw": len(raw), "kept": len(found)}
                if summary:
                    r["summaries"][pass_] = summary[:400]
            store.update_review(pid, review_id, finish)
            _publish(pid, store.load_review(pid, review_id), current=pass_)
    except Exception as e:  # noqa: BLE001 — the review must end in a recorded state
        log.exception("review %s failed", review_id)
        store.update_review(pid, review_id, lambda r: r.__setitem__("error", str(e)[:500]))
    finally:
        with _ACTIVE_LOCK:
            cancelled = bool(_ACTIVE.pop(review_id, {}).get("cancel"))

        def close(r: dict) -> None:
            for p, s in r["progress"].items():
                if s in ("pending", "running"):
                    r["progress"][p] = "error"
                    r["pass_errors"].setdefault(p, "cancelled" if cancelled else "not run")
            ok = any(s == "done" for s in r["progress"].values())
            r["status"] = "done" if ok and not r.get("error") else "error"
            if cancelled:
                r["cancelled"] = True
            if r["status"] == "error" and not r.get("error"):
                r["error"] = "; ".join(f"{p}: {m}" for p, m in r["pass_errors"].items()) or "no pass finished"
            r["finished_at"] = now_iso()
        final = store.update_review(pid, review_id, close)
        if final:
            _publish(pid, final)


def get(pid: str, review_id: str) -> dict:
    review = store.load_review(pid, review_id)
    if not review:
        raise HTTPException(404, f"no such review: {review_id}")
    if review.get("status") == "running" and review_id not in _ACTIVE:
        # The server restarted while it ran.
        def interrupted(r: dict) -> None:
            r["status"] = "error" if not any(s == "done" for s in r["progress"].values()) else "done"
            r["error"] = "interrupted (the server restarted)"
            for p, s in r["progress"].items():
                if s in ("pending", "running"):
                    r["progress"][p] = "error"
            r["finished_at"] = r.get("finished_at") or now_iso()
        review = store.update_review(pid, review_id, interrupted)
    return review


def cancel(pid: str, review_id: str) -> dict:
    review = get(pid, review_id)
    with _ACTIVE_LOCK:
        state = _ACTIVE.get(review_id)
        if state:
            state["cancel"] = True
            if state.get("run_id"):
                runner.cancel(state["run_id"])
    return review


def summary(review: dict) -> dict:
    """A review without its findings, for listings."""
    counts: dict[str, dict[str, int]] = {}
    for f in review.get("findings") or []:
        c = counts.setdefault(f["pass"], {"open": 0, "accepted": 0, "rejected": 0})
        c[f.get("status", "open")] = c.get(f.get("status", "open"), 0) + 1
    keys = ("review_id", "path", "passes", "status", "progress", "created_at", "finished_at", "range", "error", "cancelled")
    return {**{k: review.get(k) for k in keys}, "counts": counts}


def decide(pid: str, review_id: str, ids: list[str], status: str, reason: str | None = None, actor: str | None = None) -> list[dict]:
    """Accept, reject or reopen findings. A rejection dismisses the suggestion for later checks; with a reason it
    also becomes a learned rule of that pass."""
    if status not in ("accepted", "rejected", "open"):
        raise HTTPException(400, f"bad status: {status}")
    reason = (reason or "").strip()
    changed: list[dict] = []
    with store.editing_review(pid, review_id) as review:
        if review is None:
            raise HTTPException(404, f"no such review: {review_id}")
        by_id = {f["id"]: f for f in review["findings"]}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise HTTPException(404, f"no such finding: {', '.join(missing)}")
        for fid in ids:
            f = by_id[fid]
            previous = f.get("status")
            f["status"] = status
            f["decided_at"] = now_iso()
            f["decided_by"] = actor
            if status == "rejected":
                store.dismiss(pid, f, review["path"])
                if reason:
                    f["reject_reason"] = reason[:500]
                    rule = store.add_rule(pid, f["pass"], reason, by=actor,
                                          example={"kind": f["kind"], "quote": f["quote"][:300], "replacement": (f.get("replacement") or "")[:300]},
                                          source={"review_id": review_id, "finding_id": fid, "path": review["path"]})
                    f["rule_id"] = rule["id"]
            elif previous == "rejected":
                store.undismiss(pid, f["fp"])
            changed.append(dict(f))
    hub.publish(pid, "writing", {"kind": "finding", "review_id": review_id, "path": review["path"],
                                 "ids": ids, "status": status, "rule": bool(reason and status == "rejected")})
    return changed
