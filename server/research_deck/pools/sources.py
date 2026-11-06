"""Reading a pool: each source type returns one rd-pool/1 document (protocol.py).

manual    the machines written in the definition; no live data
local     this machine: nvidia-smi when it is there, the load average and memory
command   a local program, run from its argument list without a shell, that prints one rd-pool/1 document on stdout and
          exits 0 (timeout from the definition). It gets RD_POOL_ID and, when the pool names a credential, RD_POOL_SECRET.
http      GET an https address (or plain http on this machine) that returns the document; the credential goes as
          Authorization: Bearer. Redirects are not followed.

Credentials are names: keychain:<service> (read with macOS `security find-generic-password -s <service> -w`) or
env:<VARIABLE>. The secret is handed to that one command or request and never written anywhere.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import protocol, store

MAX_OUTPUT = 2 * 1024 * 1024


class SourceError(Exception):
    """Reading failed: the message says why, in words the researcher can act on."""


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_credential(ref: str | None) -> str | None:
    if not ref:
        return None
    kind, _, name = ref.partition(":")
    if kind == "env":
        value = os.environ.get(name)
        if not value:
            raise SourceError(f"the environment variable {name} is not set")
        return value
    if kind == "keychain":
        if sys.platform != "darwin":
            raise SourceError("keychain: credentials need macOS; use env:<VARIABLE> here")
        try:
            p = subprocess.run(["security", "find-generic-password", "-s", name, "-w"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SourceError(f"could not read the keychain item {name}: {e}") from e
        if p.returncode != 0 or not p.stdout.strip():
            raise SourceError(f"no keychain item {name} (add it with: security add-generic-password -s {name} -a $USER -w)")
        return p.stdout.strip()
    raise SourceError(f"unknown credential kind: {kind}")


def parse_text(text: str) -> tuple[dict, list[str]]:
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise SourceError(f"the output is not JSON: {e}") from e
    try:
        return protocol.normalize(doc)
    except ValueError as e:
        raise SourceError(str(e)) from e


def read(pool: dict) -> tuple[dict, list[str], str]:
    """(the normalized document, warnings, the raw text) for one definition; SourceError when it cannot be read."""
    src = pool["source"]
    kind = src["type"]
    if kind == "manual":
        doc = {"protocol": protocol.PROTOCOL, "as_of": now_iso(), "nodes": src.get("inventory", {}).get("nodes") or [],
               "capabilities": ["inventory"]}
        raw = json.dumps(doc, ensure_ascii=False, indent=1)
        norm, warnings = protocol.normalize(doc)
        return norm, warnings, raw
    if kind == "local":
        raw = json.dumps(local_doc(), ensure_ascii=False, indent=1)
        norm, warnings = parse_text(raw)
        return norm, warnings, raw
    secret = resolve_credential(pool.get("credential"))
    if kind == "command":
        argv = [os.path.expanduser(a) if a.startswith("~/") else a for a in src["run"]]
        env = {**os.environ, "RD_POOL_ID": pool["id"], **({"RD_POOL_SECRET": secret} if secret else {})}
        cwd = store.pools_dir()
        cwd.mkdir(parents=True, exist_ok=True)
        try:
            p = subprocess.run(argv, capture_output=True, timeout=src.get("timeout", 30), env=env, cwd=str(cwd))
        except FileNotFoundError as e:
            raise SourceError(f"no such program: {argv[0]}") from e
        except subprocess.TimeoutExpired as e:
            raise SourceError(f"the command did not finish within {src.get('timeout', 30)} s") from e
        except OSError as e:
            raise SourceError(f"could not run {argv[0]}: {e}") from e
        err = p.stderr.decode("utf-8", errors="replace").strip()[-600:]
        if p.returncode != 0:
            raise SourceError(f"the command exited {p.returncode}" + (f": {err}" if err else ""))
        if len(p.stdout) > MAX_OUTPUT:
            raise SourceError("the output is larger than 2 MB")
        raw = p.stdout.decode("utf-8", errors="replace")
        norm, warnings = parse_text(raw)
        return norm, warnings, raw
    if kind == "http":
        url = store.check_url(src["url"])
        headers = {"Accept": "application/json", "User-Agent": "research-deck-pools/1"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        try:
            r = httpx.get(url, headers=headers, timeout=src.get("timeout", 30), follow_redirects=False)
        except httpx.HTTPError as e:
            raise SourceError(f"could not reach {url}: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise SourceError(f"{url} answered {r.status_code}")
        if len(r.content) > MAX_OUTPUT:
            raise SourceError("the answer is larger than 2 MB")
        raw = r.text
        norm, warnings = parse_text(raw)
        return norm, warnings, raw
    raise SourceError(f"unknown source type: {kind}")


# ---------------------------------------------------------------- this machine

NVIDIA_QUERY = "index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw"


def _float(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None                                # "[N/A]", "[Not Supported]"


def parse_nvidia_smi(text: str) -> list[dict]:
    """GPUs from `nvidia-smi --query-gpu=<NVIDIA_QUERY> --format=csv,noheader,nounits`."""
    gpus = []
    for line in text.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 7 or not parts[1]:
            continue
        util = _float(parts[4])
        gpus.append({"model": parts[1], "count": 1, "mem_total_mib": _float(parts[2]), "mem_used_mib": _float(parts[3]),
                     "util": None if util is None else util / 100, "temp_c": _float(parts[5]), "power_w": _float(parts[6])})
    return gpus


def _ram_used() -> float | None:
    try:
        if sys.platform.startswith("linux"):
            info = dict(re.findall(r"^(\w+):\s+(\d+)", Path("/proc/meminfo").read_text(), re.M))
            total, avail = float(info["MemTotal"]), float(info["MemAvailable"])
            return 1 - avail / total
        if sys.platform == "darwin":
            total = float(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout)
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = float(re.search(r"page size of (\d+)", vm).group(1))
            free = sum(float(re.search(rf"{k}:\s+(\d+)", vm).group(1)) for k in ("Pages free", "Pages inactive", "Pages speculative"))
            return max(0.0, min(1.0, 1 - free * page / total))
    except (OSError, ValueError, KeyError, AttributeError, subprocess.TimeoutExpired):
        return None
    return None


def local_doc() -> dict:
    gpus: list[dict] = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            p = subprocess.run([smi, f"--query-gpu={NVIDIA_QUERY}", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                gpus = parse_nvidia_smi(p.stdout)
        except (OSError, subprocess.TimeoutExpired):
            gpus = []
    try:
        cpu = min(1.0, os.getloadavg()[0] / (os.cpu_count() or 1))
    except OSError:
        cpu = None
    host = socket.gethostname().split(".")[0] or "this machine"
    return {"protocol": protocol.PROTOCOL, "as_of": now_iso(),
            "nodes": [{"id": "local", "label": host, "status": "online", "gpus": gpus, "cpu": cpu, "ram": _ram_used()}],
            "capabilities": ["inventory", "telemetry"]}
