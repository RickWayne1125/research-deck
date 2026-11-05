"""In-process publish/subscribe for live updates, streamed to the browser as Server-Sent Events.

Topics: "dag" (nodes/edges/events changed), "file" (a project file was written), "sessions" (bindings changed),
"experiments", "figures", "writing". Agent runs stream on their own endpoint (agents/runner.py).
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse


class Hub:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, project_id: str, topic: str, payload: Any = None) -> None:
        """Safe to call from any thread."""
        msg = {"topic": topic, "project": project_id, "payload": payload}
        for key in (project_id, "*"):
            for q in list(self._subs.get(key, ())):
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(q.put_nowait, msg)
                else:
                    q.put_nowait(msg)

    def open(self, project_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[project_id].add(q)
        return q

    def close(self, project_id: str, q: asyncio.Queue) -> None:
        self._subs[project_id].discard(q)


hub = Hub()
router = APIRouter()


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/api/events")
async def events(request: Request, project: str = Query("*")):
    async def gen():
        q = hub.open(project)
        try:
            yield sse("hello", {"project": project})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Waiting on the queue (not on an async generator) keeps a timeout from ending the stream.
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield sse(msg["topic"], msg)
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            hub.close(project, q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
