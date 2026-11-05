"""Paths, ports and the CLIs Research Deck talks to. Everything can be overridden through RD_* environment variables."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]          # research-deck/
# Machine-local state lives outside the repository: the project registry, tokens and the user's own defaults.
# The repository holds no project information; each project keeps its state in <project>/.research/.
LOCAL_DIR = Path(os.environ.get("RD_LOCAL_DIR") or Path.home() / ".research-deck")
REGISTRY_FILE = LOCAL_DIR / "projects.json"
SETTINGS_FILE = LOCAL_DIR / "settings.json"
WEB_DIST = APP_ROOT / "web" / "dist"
# The demo project is materialized from demo/minimal into LOCAL_DIR/demo/toycache on first start (research_deck/demo.py).
# RD_NO_DEMO=1 turns that off; tests/conftest.py switches it off for every test but tests/test_demo.py.
DEMO_ENABLED = os.environ.get("RD_NO_DEMO") != "1"

HOST = os.environ.get("RD_HOST", "127.0.0.1")
PORT = int(os.environ.get("RD_PORT", "8765"))
# Pages allowed to call mutating endpoints (the built app and the Vite dev server).
DEV = os.environ.get("RD_DEV") == "1"     # the Vite dev server (scripts/dev.sh --vite) sets it
ALLOWED_ORIGINS = {
    f"http://{HOST}:{PORT}", f"http://localhost:{PORT}",
    *(("http://127.0.0.1:5173", "http://localhost:5173") if DEV else ()),
    *filter(None, os.environ.get("RD_EXTRA_ORIGINS", "").split(",")),
}
# Host headers accepted (DNS rebinding: a page on attacker.example resolving to 127.0.0.1 must not read the API).
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "::1", "[::1]", "testserver"]
# Every mutating /api request carries this header. A cross-origin page cannot add it without a CORS preflight,
# which this server never grants.
REQUEST_HEADER = "x-rd-request"

HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or HOME / ".codex")
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude")


def _first_existing(*candidates: str | Path | None) -> str | None:
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


CLAUDE_CLI = os.environ.get("RD_CLAUDE_CLI") or shutil.which("claude") or _first_existing(HOME / ".local/bin/claude")
CODEX_CLI = os.environ.get("RD_CODEX_CLI") or shutil.which("codex") or _first_existing(
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex", "/Applications/Codex.app/Contents/Resources/codex")

# RD_FAKE_AGENT=1 answers every agent request with tests/fake_agent.py instead of a real CLI (tests, offline demos).
FAKE_AGENT = os.environ.get("RD_FAKE_AGENT") == "1"


PYTHON_FOR_FIGURES = os.environ.get("RD_FIGURE_PYTHON") or str(APP_ROOT / ".venv" / "bin" / "python")

APPS = {
    "drawio": ["/Applications/draw.io.app"],
    "omnigraffle": ["/Applications/OmniGraffle 7.app", "/Applications/OmniGraffle.app", "/Applications/Setapp/OmniGraffle 7.app"],
    "datagraph": ["/Applications/DataGraph.app", "/Applications/Setapp/DataGraph.app"],
}
DATAGRAPH_CLI = "/Applications/DataGraph.app/Contents/Library/dgraph"


def app_path(name: str) -> str | None:
    return _first_existing(*APPS.get(name, []))


_SETTINGS_CACHE: tuple[float, dict] = (-1.0, {})


def user_settings() -> dict:
    """The user's own defaults (~/.research-deck/settings.json), layered over the repository's neutral defaults:
    {"agent_defaults": {"claude": {"model", "effort"}, "codex": {"model", "effort"}},
     "dag_defaults": <partial dag/config.yaml applied to every project before its own config.yaml>}"""
    global _SETTINGS_CACHE
    try:
        mtime = SETTINGS_FILE.stat().st_mtime
    except OSError:
        return {}
    if mtime != _SETTINGS_CACHE[0]:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _SETTINGS_CACHE = (mtime, data if isinstance(data, dict) else {})
    return _SETTINGS_CACHE[1]


# ------------------------------------------------------------------ tailnet access (optional, machine-local)
# settings.json {"tailnet": {"host": "<machine>.<tailnet>.ts.net", "https_port": 8765, "owners": ["you@example.com"]}}
# lets `tailscale serve --https=<port> http://127.0.0.1:<PORT>` publish the dashboard on the tailnet (never Funnel).
# The server still listens on loopback only; requests that arrive through Serve must carry a Tailscale-User-Login
# of one of the owners (app.py), so tagged devices and other tailnet users are refused.
_TAILNET = user_settings().get("tailnet") or {}
TAILNET_HOST: str | None = (_TAILNET.get("host") or "").rstrip(".") or None
TAILNET_PORT = int(_TAILNET.get("https_port") or 443)
TAILNET_OWNERS = {str(o).lower() for o in _TAILNET.get("owners") or []}
if TAILNET_HOST:
    ALLOWED_HOSTS.append(TAILNET_HOST)
    ALLOWED_ORIGINS.add(f"https://{TAILNET_HOST}" + ("" if TAILNET_PORT == 443 else f":{TAILNET_PORT}"))
