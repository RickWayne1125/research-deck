"""A project's notes kept in sync with a Docmost page: one way, notes → Docmost, never overwriting an edit made there.

project.yaml  docmost: {page, slug_id, space, space_slug, title}        the bound page
.research/docmost.json  {"notes": {"notes/idea.md": {page, slug_id, title, pushed, remote, base, state, at, error,
                         conflict: {remote, at}}}, "last": {at, pushed, conflicts, errors}}

Every Markdown file under notes/ (hidden folders left out) is a child page of the bound page. Its title is the note's
first "# " heading (taken out of the pushed text, since Docmost shows the title above the page) or else its file name.
A sync pushes each note whose title or text changed since its last push:
  - a note without a page: create it under the bound page
  - otherwise read the page as Markdown first. If it differs from what the last push left there, the page was edited
    in Docmost: the note stops at "conflict", with Docmost's text kept for review, and nothing is pushed. Otherwise
    the page's content is replaced by the note.
After a push the page is read back as Docmost renders it ("base"); the next comparison is against that.
Review: "push" replaces the page with the note (once the researcher has merged what they want from Docmost's
version into it), "take" writes Docmost's version into the note. A note deleted from notes/ leaves its page in place
("removed"); a page deleted in Docmost is "missing" until the researcher recreates it or forgets it.
The background scan syncs every bound project each SCAN_SECONDS while a sign-in is saved; a note saved in the last
QUIET_SECONDS waits for the next round.
"""
from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from pathlib import Path

from .. import projects
from ..events import hub
from ..util import now_iso, read_json, read_yaml, safe_join, sha256_text, write_json, write_text_atomic, write_yaml
from . import client as dm
from . import session

log = logging.getLogger("research_deck")

NOTES_DIR = "notes"
SCAN_SECONDS = 60.0
QUIET_SECONDS = 10.0
BACKGROUND = True                     # tests turn the scan off
ACTIONS = ("push", "take", "recreate", "forget")

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()
_RUNNING: set[str] = set()


def _lock(pid: str) -> threading.Lock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(pid, threading.Lock())


def binding(pid: str) -> dict | None:
    b = projects.project_config(pid).get("docmost")
    return b if isinstance(b, dict) and b.get("page") else None


def _state_path(pid: str) -> Path:
    return projects.research_dir(pid) / "docmost.json"


def _load(pid: str) -> dict:
    data = read_json(_state_path(pid), {}) or {}
    data.setdefault("notes", {})
    return data


def _save(pid: str, st: dict) -> None:
    write_json(_state_path(pid), st)


# ---------------------------------------------------------------- notes

def note_paths(pid: str) -> list[str]:
    root = projects.project_root(pid)
    base = root / NOTES_DIR
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.rglob("*.md")):
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or p.is_symlink() or not p.is_file():
            continue
        out.append(rel.as_posix())
    return out


H1 = re.compile(r"^#\s+(.+?)\s*#*\s*$")


def split_title(text: str, rel: str) -> tuple[str, str]:
    """The page title (the note's first heading, or its file name) and the text to push (without that heading)."""
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = H1.match(line)
        if m:
            return m.group(1).strip()[:250], "\n".join(lines[i + 1:]).strip("\n") + "\n"
        break
    return (Path(rel).stem.replace("-", " ").replace("_", " ").strip() or rel)[:250], text


def _norm(md: str) -> str:
    return "\n".join(line.rstrip() for line in (md or "").replace("\r\n", "\n").strip().split("\n"))


def _sha(md: str) -> str:
    return sha256_text(_norm(md))


def _note_sha(title: str, body: str) -> str:
    return sha256_text(title + "\n" + _norm(body))


# ---------------------------------------------------------------- binding and status

def bind(pid: str, link: str) -> dict:
    ref = dm.page_ref(link)                                  # ValueError: not a page link
    info = dm.Client().page(ref)
    if not info.get("id"):
        raise dm.DocmostError("Docmost returned no page for this link", 404)
    space = info.get("space") if isinstance(info.get("space"), dict) else {}
    b = {"page": info["id"], "slug_id": info.get("slugId"), "space": info.get("spaceId") or space.get("id"),
         "space_slug": space.get("slug"), "title": info.get("title") or ""}
    old = binding(pid)
    projects.patch_config(pid, {"docmost": b})
    if not old or old.get("page") != b["page"]:
        _save(pid, {"notes": {}})                            # another page: its child pages start afresh
    hub.publish(pid, "docmost", {"bound": b["page"]})
    return status(pid)


def unbind(pid: str) -> dict:
    path = projects.research_dir(pid) / "project.yaml"
    cfg = read_yaml(path, {}) or {}
    if cfg.pop("docmost", None) is not None:
        write_yaml(path, cfg)
        hub.publish(pid, "project", {"config": cfg})
    _state_path(pid).unlink(missing_ok=True)
    hub.publish(pid, "docmost", {"bound": None})
    return status(pid)


def status(pid: str) -> dict:
    b = binding(pid)
    st = _load(pid)
    known = st["notes"]
    root = projects.project_root(pid)
    paths = note_paths(pid)
    space_slug = (b or {}).get("space_slug")
    notes = []
    for rel in paths:
        n = known.get(rel) or {}
        try:
            title, body = split_title((root / rel).read_text(encoding="utf-8", errors="replace"), rel)
        except OSError:
            continue
        state = n.get("state") or "pending"
        if state == "synced" and n.get("pushed") != _note_sha(title, body):
            state = "pending"
        notes.append({"path": rel, "title": title, "state": state, "at": n.get("at"), "error": n.get("error"),
                      "url": dm.page_url(n["slug_id"], title, space_slug) if n.get("slug_id") else None})
    for rel, n in known.items():
        if rel not in paths and n.get("page"):
            notes.append({"path": rel, "title": n.get("title") or rel, "state": "removed", "at": n.get("at"),
                          "error": None, "url": dm.page_url(n["slug_id"], n.get("title") or "", space_slug) if n.get("slug_id") else None})
    return {"binding": {**b, "url": dm.page_url(b.get("slug_id") or "", b.get("title") or "", space_slug)} if b else None,
            "site": dm.site(), "signed_in": bool(dm.session()), "running": pid in _RUNNING, "last": st.get("last"),
            "notes": notes}


# ---------------------------------------------------------------- sync

def sync(pid: str, only: set[str] | None = None, force: frozenset[str] | set[str] = frozenset(),
         client: dm.Client | None = None, quiet_after: float = 0.0) -> dict:
    """Push the notes that changed (see the module docstring). Raises SignInNeeded when Docmost wants a new sign-in."""
    b = binding(pid)
    if not b:
        raise dm.DocmostError("this project is not bound to a Docmost page", 404)
    lock = _lock(pid)
    if not lock.acquire(blocking=False):                   # one sync of a project at a time
        return status(pid)
    _RUNNING.add(pid)
    hub.publish(pid, "docmost", {"running": True})
    try:
        c = client or dm.Client()
        st = _load(pid)
        root = projects.project_root(pid)
        paths = note_paths(pid)
        counts = {"pushed": 0, "conflicts": 0, "errors": 0}
        for rel in paths:
            if only is not None and rel not in only:
                continue
            f = root / rel
            if quiet_after and time.time() - f.stat().st_mtime < quiet_after:
                continue                                    # still being written: next round
            title, body = split_title(f.read_text(encoding="utf-8", errors="replace"), rel)
            sha = _note_sha(title, body)
            n = st["notes"].setdefault(rel, {})
            if n.get("state") in ("conflict", "missing") and rel not in force:
                continue
            if n.get("state") == "synced" and n.get("pushed") == sha:
                continue
            try:
                if not n.get("page") or n.get("state") == "missing":
                    made = c.create_page(b["space"], b["page"], title, body)
                    if not made.get("id"):
                        raise dm.DocmostError("Docmost created no page")
                    n.update(page=made["id"], slug_id=made.get("slugId"))
                else:
                    try:
                        remote_now = c.page(n["page"], markdown=True).get("content") or ""
                    except dm.SignInNeeded:
                        raise
                    except dm.DocmostError as e:
                        if e.status != 404:
                            raise
                        n.update(state="missing", error="the page was deleted in Docmost")
                        continue
                    if _sha(remote_now) != n.get("remote") and rel not in force:
                        n.update(state="conflict", conflict={"remote": remote_now, "at": now_iso()}, error=None)
                        counts["conflicts"] += 1
                        continue
                    c.update_page(n["page"], title, body)
                after = c.page(n["page"], markdown=True)
                remote = after.get("content") or ""
                n.update(title=title, pushed=sha, remote=_sha(remote), base=remote, state="synced", at=now_iso(),
                         error=None, conflict=None)
                if after.get("slugId"):
                    n["slug_id"] = after["slugId"]
                counts["pushed"] += 1
            except dm.SignInNeeded:
                raise
            except dm.DocmostError as e:
                n.update(state="error", error=str(e))
                counts["errors"] += 1
            finally:
                _save(pid, st)
        for rel, n in st["notes"].items():
            if rel not in paths and n.get("page"):
                n["state"] = "removed"
        st["last"] = {"at": now_iso(), **counts}
        _save(pid, st)
        return status(pid)
    finally:
        _RUNNING.discard(pid)
        lock.release()
        hub.publish(pid, "docmost", {"running": False})


def conflict_view(pid: str, rel: str) -> dict:
    """What changed in Docmost since the last push (a diff), Docmost's text now, and the note."""
    n = _load(pid)["notes"].get(rel) or {}
    conflict = n.get("conflict")
    if not conflict:
        raise dm.DocmostError("this note has no conflict to review", 404)
    base, remote = n.get("base") or "", conflict.get("remote") or ""
    diff = list(difflib.unified_diff(base.split("\n"), remote.split("\n"), lineterm="", n=3))[2:]
    lines = [{"kind": "@" if d.startswith("@@") else d[:1] if d[:1] in "+-" else " ", "text": d[1:] if d[:1] in "+- " else d}
             for d in diff]
    note = (projects.project_root(pid) / rel).read_text(encoding="utf-8", errors="replace") \
        if (projects.project_root(pid) / rel).is_file() else ""
    b = binding(pid) or {}
    return {"path": rel, "title": n.get("title"), "at": conflict.get("at"), "diff": lines, "remote": remote, "note": note,
            "url": dm.page_url(n.get("slug_id") or "", n.get("title") or "", b.get("space_slug"))}


def resolve(pid: str, rel: str, action: str) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"action is one of {', '.join(ACTIONS)}")
    st = _load(pid)
    n = st["notes"].get(rel)
    if not n:
        raise dm.DocmostError("this note has no page in Docmost yet", 404)
    if action == "forget":
        st["notes"].pop(rel)
        _save(pid, st)
        return status(pid)
    if action in ("push", "recreate"):
        return sync(pid, only={rel}, force={rel})
    # take: Docmost's version becomes the note
    remote = (n.get("conflict") or {}).get("remote")
    if remote is None:
        remote = dm.Client().page(n["page"], markdown=True).get("content") or ""
    path = safe_join(projects.project_root(pid), rel)
    current = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    title, body = split_title(current, rel)
    text = (f"# {title}\n\n" if body != current else "") + remote.strip() + "\n"
    write_text_atomic(path, text)
    title, body = split_title(text, rel)
    n.update(title=title, pushed=_note_sha(title, body), remote=_sha(remote), base=remote, state="synced",
             conflict=None, error=None, at=now_iso())
    _save(pid, st)
    hub.publish(pid, "file", {"path": rel})
    hub.publish(pid, "docmost", {"resolved": rel})
    return status(pid)


# ---------------------------------------------------------------- the background scan

_SCANNER: threading.Thread | None = None


def start_scanner() -> None:
    global _SCANNER
    if not BACKGROUND or (_SCANNER and _SCANNER.is_alive()):
        return
    _SCANNER = threading.Thread(target=_scan_forever, name="rd-docmost-sync", daemon=True)
    _SCANNER.start()


def _scan_forever() -> None:
    while True:
        time.sleep(SCAN_SECONDS)
        try:
            scan_once()
        except Exception:  # noqa: BLE001 — the scan must keep running
            log.exception("docmost: the background sync failed")


def scan_once() -> None:
    if not dm.session():
        return
    for p in projects.list_projects():
        pid = p["id"]
        try:
            if not binding(pid):
                continue
            sync(pid, quiet_after=QUIET_SECONDS)
        except dm.SignInNeeded:
            if not session.renew_quietly():
                dm.forget_session()                     # Settings → Docmost now says "sign in"; the scan waits
                hub.publish(pid, "docmost", {"signed_in": False})
            return
        except Exception as e:  # noqa: BLE001 — one project's failure does not stop the others
            log.warning("docmost: syncing %s failed: %s", pid, e)
