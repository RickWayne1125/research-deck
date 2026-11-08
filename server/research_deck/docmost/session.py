"""Starting and watching the sign-in window, preparing what it needs, and a quiet renewal when Docmost asks to sign in
again.

Two windows do the same job, with the same arguments, exit codes and output:
  native      macOS: login.swift, a Mac window with the system's WebKit. It is built once with `xcrun swiftc` (Xcode or
              its Command Line Tools) into ~/.research-deck/bin/ and needs nothing downloaded.
  playwright  other systems, or where the native one cannot be built: login.py, Chromium through Playwright (the
              optional extra research-deck[docmost], and its browser, about 150 MB, installed once from Settings).
The window opens on the computer that runs Research Deck, even when the dashboard is used from another device.
One sign-in runs at a time; its progress is in status()["login"] (phase "build" while the native one is being built).
"""
from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .. import config, vault
from ..util import now_iso
from . import client

log = logging.getLogger("research_deck")

NATIVE_SOURCE = Path(__file__).with_name("login.swift")
NO_HELPER = ("there is no sign-in window on this computer yet: on a Mac, install Xcode's Command Line Tools "
             "(xcode-select --install); elsewhere, pip install 'research-deck[docmost]'")
EXIT_MESSAGES = {
    2: "Playwright is not installed here: pip install 'research-deck[docmost]'",
    3: "the sign-in window was closed before Docmost knew who you are",
    4: "no sign-in within the time allowed",
    5: "the sign-in browser is not installed yet: install it first",
    6: "the site could not be opened: check its address",
}
LOGIN_TIMEOUT = 300.0
QUIET_TIMEOUT = 25.0
QUIET_EVERY = 600.0             # a quiet renewal is tried at most this often (seconds)

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"login": {"state": "idle", "message": ""}, "install": {"state": "idle", "message": ""},
                          "last_quiet": 0.0}


def playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def native_binary() -> Path:
    """Where the native window is built: one binary per version of login.swift and of this Mac."""
    digest = hashlib.sha256(NATIVE_SOURCE.read_bytes() + platform.machine().encode()
                            + platform.mac_ver()[0].encode()).hexdigest()[:12]
    return config.LOCAL_DIR / "bin" / f"docmost-login-{digest}"


def native_possible() -> bool:
    return sys.platform == "darwin" and NATIVE_SOURCE.is_file() and \
        (native_binary().exists() or shutil.which("xcrun") is not None)


def helper() -> str | None:
    """The sign-in window this computer uses: "native", "playwright", or None when neither can run."""
    if native_possible():
        return "native"
    if playwright_installed():
        return "playwright"
    return None


def build_native() -> Path:
    """Build login.swift once (a few seconds); later calls return the binary."""
    target = native_binary()
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        p = subprocess.run(["xcrun", "swiftc", "-O", "-o", str(tmp), str(NATIVE_SOURCE)], capture_output=True,
                           text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"the sign-in window could not be built: {e}") from e
    if p.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        tail = ((p.stderr or p.stdout or "").strip().splitlines() or ["swiftc failed"])[-1]
        raise RuntimeError(f"the sign-in window could not be built ({tail[:200]}); "
                           "install Xcode's Command Line Tools: xcode-select --install")
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)
    return target


def status() -> dict:
    sess = client.session()
    return {"url": client.site(), "signed_in": bool(sess), "user": (sess or {}).get("user"), "at": (sess or {}).get("at"),
            "login": dict(_STATE["login"]), "install": dict(_STATE["install"]), "playwright": playwright_installed(),
            "helper": helper()}


def _command(kind: str, url: str, out: Path, headless: bool, timeout: float) -> list[str]:
    tail = ["--url", url, "--out", str(out), "--timeout", str(timeout)] + (["--headless"] if headless else [])
    if kind == "native":
        return [str(build_native()), *tail]
    profile = vault.private_dir("docmost", "profile")
    return [sys.executable, "-m", "research_deck.docmost.login", "--profile", str(profile), *tail]


def _run_helper(headless: bool, timeout: float) -> tuple[int, str]:
    url = client.site()
    if not url:
        return 6, "set the address of your Docmost site first"
    kind = helper()
    if kind is None:
        return 2, NO_HELPER
    out = vault.private_dir("docmost") / "login-out.json"       # the folder the window writes into (0700)
    out.unlink(missing_ok=True)
    try:
        if kind == "native" and not native_binary().exists() and not headless:
            _STATE["login"] = {**_STATE["login"], "phase": "build"}
        cmd = _command(kind, url, out, headless, timeout)
    except RuntimeError as e:                       # the native window could not be built: Playwright, if it is here
        if not playwright_installed():
            return 7, str(e)
        cmd = _command("playwright", url, out, headless, timeout)
    if not headless:
        _STATE["login"] = {**_STATE["login"], "phase": "window"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        return 4, EXIT_MESSAGES[4]
    except OSError as e:
        return 6, f"the sign-in window did not start: {e}"
    if p.returncode == 0:
        data = vault.read_json("docmost", "login-out.json")
        out.unlink(missing_ok=True)
        if not isinstance(data, dict) or not data.get("cookies"):
            return 6, "the sign-in window returned nothing"
        client.save_session(data)
        user = data.get("user") or {}
        return 0, f"signed in as {user.get('name') or user.get('email') or 'you'}"
    detail = (p.stderr or "").strip().splitlines()[-1:] if p.stderr else []
    return p.returncode, EXIT_MESSAGES.get(p.returncode) or (detail[0] if detail else f"the sign-in ended ({p.returncode})")


def start_login() -> dict:
    """Open the sign-in window; it reports back in status()["login"]."""
    if not client.site():
        raise ValueError("set the address of your Docmost site first")
    with _LOCK:
        if _STATE["login"]["state"] == "waiting":
            return status()
        first = "build" if helper() == "native" and not native_binary().exists() else "window"
        _STATE["login"] = {"state": "waiting", "message": "sign in in the window that opened", "since": now_iso(),
                           "phase": first}

    def run() -> None:
        code, msg = _run_helper(headless=False, timeout=LOGIN_TIMEOUT)
        _STATE["login"] = {"state": "done" if code == 0 else "error", "message": msg, "code": code}

    threading.Thread(target=run, name="rd-docmost-login", daemon=True).start()
    return status()


def renew_quietly() -> bool:
    """Try the window's saved sign-in without showing it (an SSO session that is still valid); at most once per
    QUIET_EVERY."""
    now = time.monotonic()
    with _LOCK:
        if _STATE["login"]["state"] == "waiting" or now - _STATE["last_quiet"] < QUIET_EVERY or helper() is None:
            return False
        _STATE["last_quiet"] = now
    code, _ = _run_helper(headless=True, timeout=QUIET_TIMEOUT)
    return code == 0


def sign_out() -> dict:
    """Forget the sign-in, and what each window kept of the site (its cookies and other website data)."""
    client.forget_session()
    vault.delete("docmost", "profile")
    if sys.platform == "darwin" and NATIVE_SOURCE.is_file() and native_binary().exists():
        try:
            subprocess.run([str(native_binary()), "--clear"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("docmost: the sign-in window's data was not cleared: %s", e)
    _STATE["login"] = {"state": "idle", "message": ""}
    return status()


def install_browser() -> dict:
    """Download Playwright's Chromium (about 150 MB, once) for the sign-in window."""
    if not playwright_installed():
        raise ValueError(EXIT_MESSAGES[2])
    with _LOCK:
        if _STATE["install"]["state"] == "running":
            return status()
        _STATE["install"] = {"state": "running", "message": "downloading Chromium (about 150 MB)"}

    def run() -> None:
        try:
            p = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True,
                               text=True, timeout=1800)
            ok = p.returncode == 0
            tail = ((p.stderr or p.stdout or "").strip().splitlines() or [""])[-1]
            _STATE["install"] = {"state": "done" if ok else "error", "message": "installed" if ok else tail[:300]}
        except (OSError, subprocess.TimeoutExpired) as e:
            _STATE["install"] = {"state": "error", "message": str(e)[:300]}

    threading.Thread(target=run, name="rd-docmost-browser", daemon=True).start()
    return status()
