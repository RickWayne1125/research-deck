"""What each backend offers: models, reasoning efforts and whether a fast tier exists.

Claude's list is fixed here (Claude Code accepts these ids with --model and --effort; fast mode is the `fastMode`
setting, passed per run with --settings). Codex's list is read from ~/.codex/models_cache.json, which the Codex app
keeps current; its fast tier is service_tier="priority". The defaults follow the user's own configuration.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .. import config
from ..util import read_json

CLAUDE_MODELS = [
    {"id": "claude-opus-5-5", "label": "Opus 5.5", "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "xhigh",
     "fast": True, "fast_label": "Fast mode", "description": "Most capable"},
    {"id": "claude-fable-5-1", "label": "Fable 5.1", "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high",
     "fast": False, "description": "Claude 5 family"},
    {"id": "claude-sonnet-5-5", "label": "Sonnet 5.5", "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "high",
     "fast": False, "description": "Faster; good for routine checks"},
    {"id": "claude-haiku-5-5", "label": "Haiku 5.5", "efforts": ["low", "medium", "high"], "default_effort": "low",
     "fast": False, "description": "Quickest; completions and typo passes"},
]
_CLAUDE_BASE = {"model": "claude-opus-5-5", "effort": "high"}


def claude_default() -> dict:
    return {**_CLAUDE_BASE, **((config.user_settings().get("agent_defaults") or {}).get("claude") or {})}

FALLBACK_CODEX_MODELS = [
    {"id": "gpt-6-astra", "label": "gpt-6-astra", "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"], "default_effort": "xhigh", "fast": True, "fast_label": "Fast"},
    {"id": "gpt-6.1-sol", "label": "gpt-6.1-sol", "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"], "default_effort": "xhigh", "fast": True, "fast_label": "Fast"},
]


def _codex_config_value(key: str) -> str | None:
    try:
        text = (config.CODEX_HOME / "config.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else None


@lru_cache(maxsize=1)
def codex_models() -> list[dict]:
    data = read_json(config.CODEX_HOME / "models_cache.json", None) or {}
    out = []
    for m in data.get("models", []):
        if m.get("visibility") == "none" or not m.get("slug"):
            continue
        tiers = m.get("service_tiers") or []
        fast = next((t for t in tiers if t.get("id") == "priority"), None)
        out.append({
            "id": m["slug"], "label": m.get("display_name") or m["slug"],
            "efforts": [e.get("effort") for e in m.get("supported_reasoning_levels") or [] if e.get("effort")],
            "default_effort": m.get("default_reasoning_level") or "high",
            "fast": bool(fast), "fast_label": (fast or {}).get("name"), "description": (fast or {}).get("description") or m.get("description") or "",
        })
    return out or FALLBACK_CODEX_MODELS


def codex_default() -> dict:
    models = codex_models()
    model = _codex_config_value("model") or models[0]["id"]
    # The model the user's Codex config uses; effort "high" unless the user's settings.json says otherwise.
    return {"model": model, "effort": "high", **((config.user_settings().get("agent_defaults") or {}).get("codex") or {})}


def model_info(provider: str, model: str) -> dict | None:
    models = CLAUDE_MODELS if provider == "claude" else codex_models()
    return next((m for m in models if m["id"] == model), None)


def normalize(provider: str, model: str | None, effort: str | None, fast: bool | None) -> tuple[str, str, bool]:
    """A model the backend knows, an effort it supports and fast only where a fast tier exists."""
    default = claude_default() if provider == "claude" else codex_default()
    info = model_info(provider, model or "") or model_info(provider, default["model"])
    model = info["id"] if info else (model or default["model"])
    efforts = (info or {}).get("efforts") or ["low", "medium", "high", "xhigh", "max"]
    if effort not in efforts:
        effort = default["effort"] if default["effort"] in efforts else (info or {}).get("default_effort", efforts[-1])
    return model, effort, bool(fast) and bool((info or {}).get("fast"))


def catalog() -> dict:
    from ..system import _cli_version
    return {"providers": [
        {"id": "claude", "label": "Claude Code", "available": bool(config.CLAUDE_CLI), "cli_path": config.CLAUDE_CLI,
         "version": _cli_version(config.CLAUDE_CLI), "models": CLAUDE_MODELS, "default_model": claude_default()["model"]},
        {"id": "codex", "label": "Codex", "available": bool(config.CODEX_CLI), "cli_path": config.CODEX_CLI,
         "version": _cli_version(config.CODEX_CLI), "models": codex_models(), "default_model": codex_default()["model"]},
    ]}
