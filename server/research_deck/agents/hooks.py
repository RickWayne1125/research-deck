"""Synchronous listeners on the event hub, for server-side reactions to a topic (the brief follows "dag" changes).

events.hub only offers async subscribers (the browser's SSE streams). on_topic() wraps hub.publish once so every
published message is also handed to the registered functions, in the publisher's thread. Listeners must return
quickly (start a timer or a thread) and never raise; a failing listener is logged and ignored.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from ..events import hub

log = logging.getLogger("research_deck.agents")
Listener = Callable[[str, str, Any], None]       # fn(project_id, topic, payload)

_listeners: dict[str, list[Listener]] = defaultdict(list)
_install_lock = threading.Lock()
_installed = False


def _install() -> None:
    global _installed
    with _install_lock:
        if _installed:
            return
        original = hub.publish

        def publish(project_id: str, topic: str, payload: Any = None) -> None:
            original(project_id, topic, payload)
            for fn in list(_listeners.get(topic, ())):
                try:
                    fn(project_id, topic, payload)
                except Exception:  # noqa: BLE001 — a listener must never break the publisher
                    log.exception("hub listener for %s failed", topic)

        hub.publish = publish  # type: ignore[method-assign]
        _installed = True


def on_topic(topics: tuple[str, ...] | list[str], fn: Listener) -> None:
    """Call fn(project_id, topic, payload) after each publish on one of the topics (idempotent per fn and topic)."""
    _install()
    for topic in topics:
        if fn not in _listeners[topic]:
            _listeners[topic].append(fn)
