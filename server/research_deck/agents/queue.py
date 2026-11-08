"""Messages a conversation holds until its running answer ends (queued from the dock while the agent works).

~/.research-deck/queues/<project>--<panel>.json  {"items": [{"id", "text", "context", "at", "now"}]}

Machine-local, like the runs they wait for, so a reload or a redeploy keeps them. When a chat run ends (the finish
hook in agents/api.py): if it finished, the first item starts next; if it was stopped, only an item marked "now" does
(a message steered into a Codex run, which has to stop first). An error leaves the queue to the researcher.
Every change is published (topic "queue", {"panel", "items"}), so every open page shows the same queue.
"""
from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

from .. import config
from ..util import now_iso, read_json, write_json

_LOCK = threading.Lock()
MAX_ITEMS = 50


def _path(pid: str, panel: str) -> Path:
    safe = lambda s: re.sub(r"[^A-Za-z0-9_.-]", "_", s)[:80]  # noqa: E731
    return config.LOCAL_DIR / "queues" / f"{safe(pid)}--{safe(panel)}.json"


def _load(pid: str, panel: str) -> list[dict]:
    data = read_json(_path(pid, panel), {}) or {}
    return [i for i in data.get("items") or [] if isinstance(i, dict) and i.get("id") and i.get("text")]


def _save(pid: str, panel: str, items: list[dict]) -> None:
    path = _path(pid, panel)
    if items:
        write_json(path, {"items": items})
    else:
        path.unlink(missing_ok=True)
    try:
        from ..events import hub
        hub.publish(pid, "queue", {"panel": panel, "items": items})
    except Exception:  # noqa: BLE001 — an event failure must not lose the message
        pass


def items(pid: str, panel: str) -> list[dict]:
    with _LOCK:
        return _load(pid, panel)


def add(pid: str, panel: str, text: str, context: dict | None = None, *, front: bool = False, now: bool = False) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("the message is empty")
    item = {"id": uuid.uuid4().hex[:10], "text": text, "context": context or None, "at": now_iso(), "now": now}
    with _LOCK:
        cur = _load(pid, panel)
        if len(cur) >= MAX_ITEMS:
            raise ValueError(f"at most {MAX_ITEMS} messages can wait")
        _save(pid, panel, [item, *cur] if front else [*cur, item])
    return item


def remove(pid: str, panel: str, item_id: str) -> dict | None:
    with _LOCK:
        cur = _load(pid, panel)
        hit = next((i for i in cur if i["id"] == item_id), None)
        if hit:
            _save(pid, panel, [i for i in cur if i["id"] != item_id])
        return hit


def pop_first(pid: str, panel: str, *, now_only: bool = False) -> dict | None:
    with _LOCK:
        cur = _load(pid, panel)
        if not cur or (now_only and not cur[0].get("now")):
            return None
        _save(pid, panel, cur[1:])
        return cur[0]
