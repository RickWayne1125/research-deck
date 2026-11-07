"""Pool definitions, one YAML file each in ~/.research-deck/pools/<id>.yaml, and the last read of each pool in
~/.research-deck/pools/.cache/<id>.json. A removed pool's file moves to pools/.trash/.

id: jetstream2                 the platform name experiment records (target.platform) and the map (spec.platform) use
                               (lowercase letters, digits, - _ and .)
label: Jetstream2
kind: cloud                    local | home | lab | cluster | cloud
names: [Jetstream2 g3.large]   other platform names it answers to: records that describe the machine instead of naming
                               it. Every name, and the id, is matched ignoring case and extra spaces (name_key), and
                               belongs to one pool (settle_names).
source:
  type: command                manual | local | command | http
  run: [rd-pool-openstack, --cloud, js2]       command: an argument list, run without a shell
  url: https://…               http: https, or a loopback address
  every: 600                   seconds between reads (manual: none)
  timeout: 30                  seconds
  inventory: {nodes: […]}      manual: the machines, as rd-pool/1 nodes
credential: keychain:js2-reader      or env:VAR — a name only; the secret stays in the keychain or the environment
prices: [{item: node_hour, match: {flavor: g3.large}, amount: 64, unit: SU}]   override what the source says
budget:
  agent_gpu_hours_per_day: 8   agents may queue here on their own, this many GPU-hours a day per project (0: never)
  month: {amount: 20000, unit: SU}
note: …
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from .. import config
from ..util import loads_yaml, read_json, read_yaml, write_json, write_yaml
from . import protocol

log = logging.getLogger("research_deck.pools")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,40}$")
CRED_RE = re.compile(r"^(keychain|env):[A-Za-z0-9._-]{1,100}$")
SOURCE_TYPES = ("manual", "local", "command", "http")
DEFAULT_EVERY = {"local": 10, "command": 600, "http": 60}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
NAME_MAX = 300
NAMES_MAX = 100


def name_key(name: Any) -> str:
    """How platform names are compared: ignoring case and extra spaces ("8× RTX A6000" is "8×  rtx a6000")."""
    return " ".join(str(name or "").split()).lower()


def pools_dir() -> Path:
    return config.LOCAL_DIR / "pools"


def _path(pid: str) -> Path:
    if not ID_RE.match(pid or "") or ".." in pid:
        raise HTTPException(404, f"no such pool: {pid}")
    return pools_dir() / f"{pid}.yaml"


def check_url(url: str) -> str:
    """An http source's address: https anywhere, or plain http on this machine only."""
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    if u.scheme == "https" and host:
        return url
    if u.scheme == "http" and host in LOOPBACK:
        return url
    raise ValueError("source.url must be https://…, or http:// on 127.0.0.1, localhost or [::1]")


def _names(raw: Any, pid: str) -> list[str]:
    """The other platform names a pool answers to, spaces tidied; a repeat, or the id itself, is dropped."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("names: a list of the other platform names this pool answers to")
    out, seen = [], {name_key(pid)}
    for n in raw:
        s = " ".join(str(n).split()) if isinstance(n, (str, int, float)) and not isinstance(n, bool) else ""
        if not s or len(s) > NAME_MAX:
            raise ValueError(f"names: each one a platform name of 1–{NAME_MAX} characters")
        if name_key(s) not in seen:
            seen.add(name_key(s))
            out.append(s)
    if len(out) > NAMES_MAX:
        raise ValueError(f"names: at most {NAMES_MAX}")
    return out


def validate(data: Any) -> dict:
    """A clean definition, or ValueError saying what is wrong."""
    if not isinstance(data, dict):
        raise ValueError("a pool definition is a mapping")
    pid = str(data.get("id") or "")
    if not ID_RE.match(pid) or ".." in pid:
        raise ValueError("id: lowercase letters, digits, - _ and ., starting with a letter or digit, at most 41 characters")
    src = data.get("source") if isinstance(data.get("source"), dict) else {}
    kind_src = src.get("type")
    if kind_src not in SOURCE_TYPES:
        raise ValueError(f"source.type must be one of {', '.join(SOURCE_TYPES)}")
    source: dict[str, Any] = {"type": kind_src}
    if kind_src == "command":
        run = src.get("run")
        if not isinstance(run, list) or not run or len(run) > 32 or not all(isinstance(a, str) and a and len(a) <= 500 for a in run):
            raise ValueError("source.run: a list of 1–32 arguments (the program first)")
        source["run"] = list(run)
    if kind_src == "http":
        source["url"] = check_url(str(src.get("url") or ""))
    if kind_src == "manual":
        warnings: list[str] = []
        inv = src.get("inventory") if isinstance(src.get("inventory"), dict) else {}
        nodes = [x for k, n in enumerate(inv.get("nodes") or []) if (x := protocol.node(n, f"inventory.nodes[{k}]", warnings))]
        if warnings:
            raise ValueError("; ".join(warnings[:3]))
        source["inventory"] = {"nodes": nodes}
    if kind_src != "manual":
        every = src.get("every", DEFAULT_EVERY[kind_src])
        if not isinstance(every, int) or isinstance(every, bool) or not 10 <= every <= 86400:
            raise ValueError("source.every: seconds between reads, 10–86400")
        source["every"] = every
        timeout = src.get("timeout", 30)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
            raise ValueError("source.timeout: 1–120 seconds")
        source["timeout"] = timeout
    cred = data.get("credential") or None
    if cred is not None and (not isinstance(cred, str) or not CRED_RE.match(cred)):
        raise ValueError("credential: keychain:<name> or env:<VARIABLE>")
    warnings = []
    prices = [x for k, p in enumerate(data.get("prices") or []) if (x := protocol.price(p, f"prices[{k}]", warnings))]
    if warnings:
        raise ValueError("; ".join(warnings[:3]))
    b = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    budget: dict[str, Any] = {}
    agent = b.get("agent_gpu_hours_per_day")
    if agent is not None:
        if isinstance(agent, bool) or not isinstance(agent, (int, float)) or agent < 0:
            raise ValueError("budget.agent_gpu_hours_per_day: a number >= 0")
        budget["agent_gpu_hours_per_day"] = float(agent)
    month = b.get("month")
    if month:
        if not isinstance(month, dict) or isinstance(month.get("amount"), bool) or not isinstance(month.get("amount"), (int, float)) \
                or month["amount"] < 0 or not str(month.get("unit") or "").strip():
            raise ValueError("budget.month: {amount: >= 0, unit}")
        budget["month"] = {"amount": float(month["amount"]), "unit": str(month["unit"]).strip()[:20]}
    kind = data.get("kind") or ("local" if kind_src == "local" else "cluster")
    if kind not in protocol.KINDS:
        raise ValueError(f"kind must be one of {', '.join(protocol.KINDS)}")
    label = str(data.get("label") or pid).strip()[:80] or pid
    names = _names(data.get("names"), pid)
    out = {"id": pid, "label": label, "kind": kind, **({"names": names} if names else {}), "source": source,
           "credential": cred, "prices": prices, "budget": budget}
    if str(data.get("note") or "").strip():
        out["note"] = str(data["note"]).strip()[:300]
    return out


def load_all(errors: list[dict] | None = None, clashes: list[dict] | None = None) -> list[dict]:
    """Every pool that validates, by label. A broken file is skipped (and listed in errors, when given), not fatal; a
    platform name two pools claim is kept by one of them (settle_names; listed in clashes, when given)."""
    d = pools_dir()
    out = []
    for p in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        try:
            pool = validate(read_yaml(p, None))
            if pool["id"] != p.stem:
                raise ValueError(f"its id is {pool['id']}, but the file is named {p.name}")
        except Exception as e:  # noqa: BLE001 — YAML, OS and validation errors alike
            log.warning("skipping the pool file %s: %s", p.name, e)
            if errors is not None:
                errors.append({"file": p.name, "error": str(e)[:300]})
            continue
        out.append(pool)
    settle_names(out, clashes)
    return sorted(out, key=lambda x: (x["label"].lower(), x["id"]))


def settle_names(pools: list[dict], clashes: list[dict] | None = None) -> None:
    """A platform name belongs to one pool: a pool's id beats another pool's name for it, and of two pools that list
    the same name, the first by id keeps it. The other copy is dropped (and listed in clashes, when given). Saving
    refuses a clash (save); this settles files written by hand."""
    ids = {name_key(p["id"]): p["id"] for p in pools}
    claimed: dict[str, str] = {}
    for p in sorted(pools, key=lambda x: x["id"]):
        keep = []
        for n in p.get("names") or []:
            owner = ids.get(name_key(n)) or claimed.get(name_key(n))
            if owner and owner != p["id"]:
                if clashes is not None:
                    clashes.append({"name": n, "pool": p["id"], "owner": owner})
                continue
            claimed[name_key(n)] = p["id"]
            keep.append(n)
        if keep:
            p["names"] = keep
        else:
            p.pop("names", None)


def exists(pid: str) -> bool:
    try:
        return _path(pid).is_file()
    except HTTPException:
        return False


def text(pid: str) -> str:
    """The pool's file as written (what to copy to someone else: it holds no secrets)."""
    return _path(pid).read_text(encoding="utf-8")


def parse(source: str) -> dict:
    """A definition from YAML (or JSON) text, validated; ValueError says what is wrong."""
    if len(source) > 200_000:
        raise ValueError("the file is larger than 200 KB")
    try:
        data = loads_yaml(source)
    except Exception as e:  # noqa: BLE001 — any YAML error
        raise ValueError(f"not YAML: {e}") from e
    return validate(data)


def get(pid: str) -> dict:
    path = _path(pid)
    if not path.is_file():
        raise HTTPException(404, f"no such pool: {pid}")
    try:
        return validate(read_yaml(path, None))
    except ValueError as e:
        raise HTTPException(422, f"{path.name} does not validate: {e}") from e


def save(data: dict) -> dict:
    """Write a definition (create or replace). 409 when its id or one of its names is already another pool's."""
    try:
        pool = validate(data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    taken: dict[str, str] = {}
    for p in load_all():
        if p["id"] != pool["id"]:
            for n in [p["id"], *p.get("names", [])]:
                taken.setdefault(name_key(n), p["id"])
    for n in [pool["id"], *pool.get("names", [])]:
        if name_key(n) in taken:
            raise HTTPException(409, f"the platform name «{n}» already belongs to the pool {taken[name_key(n)]}; "
                                     "take it out there first")
    pools_dir().mkdir(parents=True, exist_ok=True)
    write_yaml(_path(pool["id"]), pool)
    return pool


def remove(pid: str) -> Path:
    path = _path(pid)
    if not path.is_file():
        raise HTTPException(404, f"no such pool: {pid}")
    trash = pools_dir() / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{pid}-{time.strftime('%Y%m%d-%H%M%S')}.yaml"
    path.rename(dest)
    cache_path(pid).unlink(missing_ok=True)
    return dest


def cache_path(pid: str) -> Path:
    return pools_dir() / ".cache" / f"{pid}.json"


def read_cache(pid: str) -> dict:
    return read_json(cache_path(pid), None) or {}


def write_cache(pid: str, data: dict) -> None:
    path = cache_path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, data)
