"""Coder workspaces as resource-pool machines: the Coder CLI's sign-in, which ssh to a workspace needs.

`coder config-ssh` routes `ssh <agent>.<workspace>.<owner>.coder` (or `coder.<workspace>`) through
`coder --global-config <folder> ssh --stdio`. With --global-config the CLI keeps its session in <folder>/session and
ignores the macOS keyring, which is where a plain `coder login` puts it: after such a login, ssh to a workspace still
says "You are signed out". Research Deck signs in to the folder ssh reads (found with `ssh -G <host>`):
`coder --global-config <folder> login <url>`. The token, which the researcher copies from <url>/cli-auth, goes to the
CLI's own prompt on stdin, never onto a command line (the CLI refuses CODER_SESSION_TOKEN for a login), and the CLI
runs with no browser opener on its PATH, so nothing opens on this computer. The CLI writes the session (mode 0600);
Research Deck keeps nothing.

Hosts the Coder VS Code extension manages (`coder-vscode.…`) use the extension's own folder: they are left to it.

A pool read never starts a stopped workspace: pool commands run with CODER_SSH_DISABLE_AUTOSTART=true.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

# What the Coder CLI prints when it has no valid session (whoami, ssh --stdio, …).
_SIGNED_OUT = re.compile(r"signed out or your session has expired|try logging in using 'coder login'", re.I)
# Host names `coder config-ssh` sets up: <agent>.<workspace>.<owner>.coder (hostname suffix) or coder.<workspace>
# (host prefix).
_HOST = re.compile(r"^(?:[A-Za-z0-9_-]+\.)+coder$|^coder\.[A-Za-z0-9_.-]+$")
NO_OPENER = "/nonexistent/research-deck-no-browser"     # PATH for `coder login`: no `open`/`xdg-open` to find
TIMEOUT = 20


def signed_out(text: str) -> bool:
    return bool(_SIGNED_OUT.search(text or ""))


def host_in(argv: list[str]) -> str | None:
    """The Coder workspace host a pool command reaches over ssh, if it names one (user@ is dropped)."""
    for a in argv:
        h = a.rsplit("@", 1)[-1]
        if _HOST.match(h):
            return h
    return None


def cli() -> str | None:
    found = shutil.which("coder")
    if found:
        return found
    for p in ("/usr/local/bin/coder", "/opt/homebrew/bin/coder", str(Path.home() / ".local/bin/coder")):
        if os.access(p, os.X_OK):
            return p
    return None


def default_folder() -> Path:
    """The CLI's own default: CODER_CONFIG_DIR, else the OS's config folder for coderv2."""
    if os.environ.get("CODER_CONFIG_DIR"):
        return Path(os.environ["CODER_CONFIG_DIR"]).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "coderv2"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "coderv2"


def proxy_of(ssh_g: str) -> tuple[str, Path] | None:
    """(the coder binary, its --global-config folder) from `ssh -G <host>` output, when ssh goes through coder."""
    for line in ssh_g.splitlines():
        if not line.lower().startswith("proxycommand "):
            continue
        try:
            argv = shlex.split(line.split(" ", 1)[1])
        except ValueError:
            return None
        if argv and "coder" in Path(argv[0]).name and "--global-config" in argv[:-1]:
            return argv[0], Path(argv[argv.index("--global-config") + 1])
    return None


def locate(host: str | None = None) -> dict:
    """Which CLI and folder ssh to `host` uses ({cli, folder, managed}); the CLI's defaults without a host."""
    if host:
        try:
            p = subprocess.run(["ssh", "-G", host], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
            found = proxy_of(p.stdout)
        except (OSError, subprocess.TimeoutExpired):
            found = None
        if found:
            binary, folder = found
            managed = "vscode" if "coder.coder-remote" in str(folder) else None
            return {"cli": binary, "folder": folder, "managed": managed}
    return {"cli": cli(), "folder": default_folder(), "managed": None}


def _env(extra: dict | None = None) -> dict:
    # A token or URL in the server's own environment would override the folder's session: leave both out.
    env = {k: v for k, v in os.environ.items() if k not in ("CODER_SESSION_TOKEN", "CODER_URL")}
    return {**env, **(extra or {})}


def _tail(text: str, n: int = 300) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return " ".join(lines[-3:])[-n:]


def status(host: str | None = None) -> dict:
    """{installed, cli, folder, managed, host, url, signed_in, user, error}: whether ssh to Coder workspaces can work."""
    where = locate(host)
    folder: Path = where["folder"]
    try:
        url = (folder / "url").read_text(encoding="utf-8").strip() or None
    except OSError:
        url = None
    out = {"installed": bool(where["cli"]), "cli": where["cli"], "folder": str(folder), "managed": where["managed"],
           "host": host, "url": url, "signed_in": False, "user": None, "error": None}
    if not where["cli"]:
        return out
    try:
        p = subprocess.run([where["cli"], "--global-config", str(folder), "whoami", "-o", "json"], capture_output=True,
                           text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL, env=_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        out["error"] = f"coder whoami: {e}"
        return out
    if p.returncode == 0:
        try:
            me = json.loads(p.stdout)
            me = me[0] if isinstance(me, list) and me else me
            out.update(signed_in=True, user=me.get("username"), url=me.get("url") or url)
        except (ValueError, AttributeError):
            out.update(signed_in=True)
    elif not signed_out(p.stderr + p.stdout):
        out["error"] = _tail(p.stderr or p.stdout) or f"coder whoami exited {p.returncode}"
    return out


def check_url(url: str) -> str:
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or any(c.isspace() for c in url):
        raise ValueError("the Coder deployment's address, like https://coder.example.com")
    return url.rstrip("/")


def login(url: str, token: str, host: str | None = None) -> dict:
    """Sign the CLI in, in the folder ssh to `host` reads; the status afterwards. ValueError with a reason."""
    url = check_url(url)
    token = (token or "").strip()
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise ValueError(f"paste the session token that {url}/cli-auth shows")
    where = locate(host)
    if where["managed"] == "vscode":
        raise ValueError("this host belongs to the Coder VS Code extension: sign in from VS Code")
    if not where["cli"]:
        raise ValueError("the Coder CLI is not installed on this computer")
    folder: Path = where["folder"]
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        p = subprocess.run([where["cli"], "--global-config", str(folder), "login", url], input=token + "\n",
                           capture_output=True, text=True, timeout=60, env=_env({"PATH": NO_OPENER}),
                           cwd=str(folder))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"coder login: {e}") from e
    said = (p.stdout + "\n" + p.stderr).replace(token, "…")
    if p.returncode != 0:
        if "not a valid token" in said:
            raise ValueError(f"Coder did not accept the token: copy a new one from {url}/cli-auth")
        raise ValueError(f"coder login failed: {_tail(said)}")
    return status(host)
