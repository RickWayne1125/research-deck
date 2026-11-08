"""Secrets Research Deck obtains itself: the Docmost sign-in it captures and the key the Zotero desktop app grants.

They live in files under ~/.research-deck/secrets/ (folder 0700, files 0600, written atomically). They are never put
in settings.json, never sent to the browser and never logged. Credentials the researcher brings (a zotero.org API key)
stay in the macOS Keychain and are named in the settings instead (pools/sources.resolve_credential).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import config


def path(*parts: str) -> Path:
    """A path under the secrets folder, which is created (0700) on first use."""
    base = config.LOCAL_DIR / "secrets"
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    target = base.joinpath(*parts)
    if base.resolve() not in target.resolve().parents:
        raise ValueError(f"not a secrets path: {'/'.join(parts)}")
    return target


def private_dir(*parts: str) -> Path:
    """A folder under the secrets folder (0700), for example a browser profile."""
    d = path(*parts)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def read_json(*parts: str) -> Any:
    try:
        return json.loads(path(*parts).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(data: Any, *parts: str) -> None:
    target = path(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)   # mkstemp creates the file 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def delete(*parts: str) -> None:
    target = path(*parts)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)
