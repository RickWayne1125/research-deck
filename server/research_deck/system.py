"""Health and environment: which CLIs and figure apps exist on this machine."""
from __future__ import annotations

import subprocess
from functools import lru_cache

from fastapi import APIRouter, Request

from . import __version__, config

router = APIRouter(prefix="/api/system", tags=["system"])


@lru_cache(maxsize=4)
def _cli_version(path: str | None) -> str | None:
    if not path:
        return None
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


@router.get("/health")
def health(request: Request):
    from .app import is_tailnet_request
    via_tailnet = is_tailnet_request(request)
    return {
        "request": {"via": "tailnet" if via_tailnet else "local", "login": request.headers.get("tailscale-user-login") if via_tailnet else None},
        "tailnet": {"host": config.TAILNET_HOST, "https_port": config.TAILNET_PORT if config.TAILNET_HOST else None,
                    "url": (f"https://{config.TAILNET_HOST}" + ("" if config.TAILNET_PORT == 443 else f":{config.TAILNET_PORT}")) if config.TAILNET_HOST else None},
        "ok": True,
        "version": __version__,
        "fake_agent": config.FAKE_AGENT,
        "clis": {
            "claude": {"path": config.CLAUDE_CLI, "version": _cli_version(config.CLAUDE_CLI), "ok": bool(config.CLAUDE_CLI)},
            "codex": {"path": config.CODEX_CLI, "version": _cli_version(config.CODEX_CLI), "ok": bool(config.CODEX_CLI)},
        },
        "apps": {name: {"path": config.app_path(name), "installed": bool(config.app_path(name))} for name in config.APPS},
    }
