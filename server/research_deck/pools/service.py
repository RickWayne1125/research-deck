"""Pools as the rest of Research Deck sees them.

reads     A pool is read when its last attempt is older than source.every, in a background thread so a page never waits
          on a slow source (this machine is read on the spot the first time; a manual pool has nothing to read). A
          failed read keeps the last good document and says why beside it. The cache is store.py's; a cached read whose
          source or credential has since changed is dropped (signature).
views     platform_view() is one pool in the Experiments › Resources shape (ExPlatform, web/src/panels/experiments/
          api.ts) with the pool's own facts under "pool": state, source, error, capabilities, prices, budget,
          credential. snapshot(pid) is GET /api/resources: every pool, whether this project uses it, and the platform
          names the project's records and map use that no pool answers to.
prices    The definition's prices (what the researcher wrote) first, then the source's; the most specific match wins.
          A machine of one's own (local, home, lab) with no price is not billed. A cluster or cloud with no price is
          unknown (None), never 0. Pricer estimates many cells at once (run plan, impact preview); a platform with no
          pool falls back to the map's env probe (usd_per_gpu_hour).
budgets   How many GPU-hours the agents queued today, per platform, for the budget meters and dag/queue.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

from . import sources, store

log = logging.getLogger("research_deck.pools")

UNBILLED = ("local", "home", "lab")        # kinds that cost nothing unless a price says otherwise
CREDENTIAL_SOON_DAYS = 30
NAMES_TTL_S = 60
BACKGROUND = os.environ.get("RD_POOLS_SYNC") != "1"      # tests read synchronously

_LOCK = threading.Lock()
_READING: set[str] = set()
_NAMES: dict[str, tuple[float, list[str]]] = {}


def _time(iso: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def age_s(iso: Any) -> float | None:
    dt = _time(iso) if iso else None
    return None if dt is None else max(0.0, (datetime.now(UTC) - dt).total_seconds())


def signature(pool: dict) -> str:
    """What a cached read depends on: the source (not how often or how long it is read) and the credential."""
    src = {k: v for k, v in pool["source"].items() if k not in ("every", "timeout")}
    return hashlib.sha256(json.dumps([src, pool.get("credential")], sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- reading

def cached(pool: dict) -> dict:
    rec = store.read_cache(pool["id"])
    return rec if isinstance(rec, dict) and rec.get("sig") == signature(pool) else {}


def read_now(pool: dict, keep: bool = True) -> dict:
    """Read one pool now: {sig, doc, read_at, tried_at, warnings, duration_s, error}. When the read fails the last good
    document stays, with the error beside it. keep=False writes nothing."""
    started, tried_at, sig = time.monotonic(), sources.now_iso(), signature(pool)
    try:
        doc, warnings, _raw = sources.read(pool)
        rec = {"sig": sig, "doc": doc, "read_at": tried_at, "tried_at": tried_at, "warnings": warnings[:30], "error": None}
    except sources.SourceError as e:
        rec = {**(cached(pool) if keep else {}), "sig": sig, "tried_at": tried_at, "error": str(e)[:800]}
    except Exception as e:  # noqa: BLE001 — a broken adapter must not take the page down
        log.exception("reading the pool %s failed", pool["id"])
        rec = {**(cached(pool) if keep else {}), "sig": sig, "tried_at": tried_at, "error": f"{e.__class__.__name__}: {e}"[:800]}
    rec["duration_s"] = round(time.monotonic() - started, 2)
    if keep and pool["source"]["type"] != "manual" and store.exists(pool["id"]):     # not for a pool removed meanwhile
        store.write_cache(pool["id"], rec)
    return rec


def record(pool: dict) -> dict:
    """The pool's last read; a manual pool is read on the spot (there is nothing to wait for)."""
    return read_now(pool, keep=False) if pool["source"]["type"] == "manual" else cached(pool)


def _due(pool: dict, rec: dict) -> bool:
    if pool["source"]["type"] == "manual":
        return False
    age = age_s(rec.get("tried_at"))
    return age is None or age >= pool["source"]["every"]


def _read_and_release(pool: dict) -> None:
    try:
        read_now(pool)
    finally:
        with _LOCK:
            _READING.discard(pool["id"])


def refresh_due(pools: list[dict]) -> None:
    """Start a read of every pool whose last attempt is older than its interval (at most one read per pool at a time)."""
    for pool in pools:
        rec = cached(pool)
        if not _due(pool, rec):
            continue
        with _LOCK:
            if pool["id"] in _READING:
                continue
            _READING.add(pool["id"])
        if not BACKGROUND or (pool["source"]["type"] == "local" and not rec):
            _read_and_release(pool)
        else:
            threading.Thread(target=_read_and_release, args=(pool,), name=f"rd-pool-{pool['id']}", daemon=True).start()


def refresh(pool: dict) -> dict:
    """Read now, whatever the interval (the 刷新 button)."""
    with _LOCK:
        _READING.add(pool["id"])
    try:
        return read_now(pool)
    finally:
        with _LOCK:
            _READING.discard(pool["id"])


def reading(pid: str) -> bool:
    with _LOCK:
        return pid in _READING


def test(data: Any) -> dict:
    """Read a definition once without saving anything: the wizard's 测试. ValueError when the definition is invalid."""
    pool = store.validate(data)
    started, at = time.monotonic(), sources.now_iso()
    try:
        doc, warnings, raw = sources.read(pool)
    except sources.SourceError as e:
        return {"ok": False, "error": str(e)[:800], "duration_s": round(time.monotonic() - started, 2)}
    rec = {"doc": doc, "read_at": at, "tried_at": at, "warnings": warnings, "error": None}
    return {"ok": True, "duration_s": round(time.monotonic() - started, 2), "warnings": warnings, "doc": doc,
            "raw": raw[:20000], "raw_truncated": len(raw) > 20000, "platform": platform_view(pool, rec)}


# ---------------------------------------------------------------- prices

def rules(pool: dict, doc: dict | None) -> list[dict]:
    """The pool's price rules: the definition's before the source's."""
    return [{**r, "from": "definition"} for r in pool.get("prices") or []] + \
           [{**r, "from": "source"} for r in (doc or {}).get("prices") or []]


def _applies(rule: dict, ctx: dict) -> bool:
    return all(str(ctx.get(k) or "").lower() == str(v).lower() for k, v in rule["match"].items())


def best_rule(all_rules: list[dict], ctx: dict) -> dict | None:
    """The definition before the source, then the most specific match, then the order written."""
    hits = [(i, r) for i, r in enumerate(all_rules) if _applies(r, ctx)]
    return min(hits, key=lambda x: (x[1]["from"] != "definition", -len(x[1]["match"]), x[0]))[1] if hits else None


def _per_gpu_hour(pool: dict, rule: dict | None, gpus: int | None) -> dict:
    """{state: known | free | unknown, amount (per GPU-hour), unit, item, rule_amount, from, why}."""
    if rule is None:
        if pool["kind"] in UNBILLED:
            return {"state": "free", "amount": 0.0, "unit": None, "item": None, "rule_amount": None, "from": None, "why": None}
        return {"state": "unknown", "amount": None, "unit": None, "item": None, "rule_amount": None, "from": None, "why": "no price"}
    base = {"unit": rule["unit"], "item": rule["item"], "rule_amount": rule["amount"], "from": rule["from"], "why": None}
    if rule["item"] == "gpu_hour":
        return {"state": "known", "amount": rule["amount"], **base}
    if gpus:
        return {"state": "known", "amount": rule["amount"] / gpus, **base}
    return {"state": "unknown", "amount": None, **base, "why": "priced per machine, and its GPU count is unknown"}


def _gpus(n: dict) -> int:
    return sum(g["count"] for g in n["gpus"])


def node_price(pool: dict, doc: dict | None, n: dict, gpu: str | None = None) -> dict:
    ctx = {"gpu": gpu or (n["gpus"][0]["model"] if n["gpus"] else None), "flavor": n.get("flavor"), "node": n["id"]}
    return _per_gpu_hour(pool, best_rule(rules(pool, doc), ctx), _gpus(n))


def rate(pool: dict, doc: dict | None, gpu: str | None = None, node: str | None = None) -> dict:
    """What one GPU-hour costs on this pool, on that GPU model or machine when given. state "varies" when the matching
    machines are priced differently (the estimate is then unknown until the run names one)."""
    g, m = (gpu or "").lower(), (node or "").lower()
    nodes = [n for n in (doc or {}).get("nodes") or [] if n["gpus"]
             and (not m or m in (n["id"].lower(), n["label"].lower()))
             and (not g or any(x["model"].lower() == g for x in n["gpus"]))]
    if not nodes:
        return _per_gpu_hour(pool, best_rule(rules(pool, doc), {"gpu": gpu, "node": node}), None)
    prices = [node_price(pool, doc, n, gpu) for n in nodes]
    distinct = {(p["state"], None if p["amount"] is None else round(p["amount"], 9), p["unit"]) for p in prices}
    if len(distinct) == 1:
        return prices[0]
    known = sorted({(p["amount"], p["unit"]) for p in prices if p["amount"] is not None}, key=lambda x: (str(x[1]), x[0]))
    return {"state": "varies", "amount": None, "unit": None, "item": None, "rule_amount": None, "from": None,
            "why": "the machines are priced differently: name the machine or the GPU",
            "options": [{"amount": a, "unit": u} for a, u in known][:8]}


class Pricer:
    """Estimates for many cells at once: each pool and its last read are loaded once."""

    def __init__(self) -> None:
        self.pools = {p["id"]: p for p in store.load_all()}
        self._docs: dict[str, dict | None] = {}

    def pool(self, platform: str | None) -> dict | None:
        return self.pools.get(str(platform or "").strip().lower())

    def doc(self, pool: dict) -> dict | None:
        if pool["id"] not in self._docs:
            self._docs[pool["id"]] = record(pool).get("doc")
        return self._docs[pool["id"]]

    def estimate(self, platform: str | None, gpu_h: float | None, *, gpu: str | None = None, node: str | None = None,
                 probe: dict | None = None) -> dict:
        """The cost of gpu_h GPU-hours on a platform: {state, amount, unit, rate, item, rule_amount, pool, from, why}."""
        pool = self.pool(platform)
        if pool:
            r = rate(pool, self.doc(pool), gpu, node)
            out = {"state": r["state"], "rate": r["amount"], "unit": r["unit"], "item": r["item"], "rule_amount": r["rule_amount"],
                   "pool": pool["id"], "from": r["from"], "why": r["why"]}
        else:
            usd = (probe or {}).get("usd_per_gpu_hour")
            if isinstance(usd, (int, float)) and not isinstance(usd, bool) and usd >= 0:
                out = {"state": "known" if usd > 0 else "free", "rate": float(usd), "unit": "USD" if usd > 0 else None,
                       "item": "gpu_hour", "rule_amount": float(usd), "pool": None, "from": "env probe", "why": None}
            else:
                out = {"state": "unknown", "rate": None, "unit": None, "item": None, "rule_amount": None, "pool": None,
                       "from": None, "why": "no resource pool for this platform" if platform else "no platform"}
        if gpu_h is None and out["state"] != "free":
            out["why"] = out["why"] or "the duration is unknown"
        out["amount"] = None if out["rate"] is None or gpu_h is None else round(float(gpu_h) * out["rate"], 4)
        return out


def totals(estimates: list[tuple[dict, float | None]]) -> dict:
    """{"cost": {unit: amount}, "unpriced": {"cells", "gpu_h"}} over (estimate, gpu_h) pairs; units are never added
    together, and an unknown price is left out (and counted), never taken as 0."""
    cost: dict[str, float] = {}
    cells, gpu_h = 0, 0.0
    for est, h in estimates:
        if est["state"] == "free":
            continue
        if est["amount"] is None or not est["unit"]:
            cells += 1
            gpu_h += float(h or 0)
            continue
        cost[est["unit"]] = cost.get(est["unit"], 0.0) + est["amount"]
    return {"cost": {u: round(a, 4) for u, a in sorted(cost.items())}, "unpriced": {"cells": cells, "gpu_h": round(gpu_h, 4)}}


def limit_warnings(pricer: Pricer, priced: list[tuple[dict, float | None]]) -> list[dict]:
    """Where these runs would go past what a pool has left, in the same unit: a quota the source reads (limit − used),
    or the month's budget (less the spend the source reads, when it is in that unit). The run plan shows them before
    anything is queued; nothing is refused for it."""
    need: dict[tuple[str, str], float] = {}
    for est, _h in priced:
        if est.get("pool") and est["amount"] is not None and est["unit"]:
            need[(est["pool"], est["unit"])] = need.get((est["pool"], est["unit"]), 0.0) + est["amount"]
    out = []
    for (pid, unit), amount in sorted(need.items()):
        pool = pricer.pools[pid]
        doc = pricer.doc(pool) or {}
        for q in doc.get("quota") or []:
            if q["unit"] == unit and q["limit"] is not None and q["used"] is not None and amount > q["limit"] - q["used"]:
                out.append({"pool": pid, "unit": unit, "need": round(amount, 4), "left": round(q["limit"] - q["used"], 4),
                            "what": "quota", "name": q["name"]})
        month = pool["budget"].get("month")
        if month and month["unit"] == unit:
            spend = doc.get("spend")
            used = spend["amount"] if spend and spend["unit"] == unit and spend["amount"] is not None else None
            left = month["amount"] - (used or 0.0)
            if amount > left:
                out.append({"pool": pid, "unit": unit, "need": round(amount, 4), "left": round(left, 4), "what": "month",
                            "name": None, "spent_known": used is not None})
    return out


# ---------------------------------------------------------------- projects: which pools, which names, the agents' usage

def selection(pid: str) -> list[str] | None:
    """The pools this project uses (project.yaml resources.pools); None = all of them."""
    from .. import projects
    cfg = projects.project_config(pid)
    res = cfg.get("resources") if isinstance(cfg.get("resources"), dict) else {}
    sel = res.get("pools")
    return sorted({str(x).strip().lower() for x in sel if str(x).strip()}) if isinstance(sel, list) else None


def set_selection(pid: str, ids: list[str] | None) -> list[str] | None:
    from .. import projects
    from ..events import hub
    from ..util import read_yaml, write_yaml
    path = projects.research_dir(pid) / "project.yaml"
    cfg = read_yaml(path, {}) or {}
    res = dict(cfg.get("resources")) if isinstance(cfg.get("resources"), dict) else {}
    if ids is None:
        res.pop("pools", None)
    else:
        res["pools"] = sorted({str(x).strip().lower() for x in ids if str(x).strip()})
    if res:
        cfg["resources"] = res
    else:
        cfg.pop("resources", None)
    write_yaml(path, cfg)
    hub.publish(pid, "project", {"config": cfg})
    return selection(pid)


def platform_names(pid: str) -> list[str]:
    """The platform names the project uses: its records' target.platform and its map's spec.platform (cached 60 s)."""
    now = time.monotonic()
    hit = _NAMES.get(pid)
    if hit and now - hit[0] < NAMES_TTL_S:
        return hit[1]
    names: set[str] = set()
    try:
        from ..experiments import records
        names |= records.target_platforms(pid)
    except Exception:  # noqa: BLE001 — a project without records
        log.debug("no records for %s", pid, exc_info=True)
    try:
        from ..dag.evaluate import current
        from ..dag.model import spec_of
        from ..dag.service import store_for
        names |= {p for n in current(store_for(pid)).nodes.values() if (p := str(spec_of(n).get("platform") or "").strip())}
    except Exception:  # noqa: BLE001 — a project without a map
        log.debug("no map for %s", pid, exc_info=True)
    out = sorted(names, key=str.lower)
    _NAMES[pid] = (now, out)
    return out


def unmatched(pid: str, pools: list[dict]) -> list[str]:
    ids = {p["id"] for p in pools}
    return [n for n in platform_names(pid) if n.lower() not in ids]


def agent_usage_today(pid: str) -> dict[str, float]:
    """GPU-hours the agents queued today (UTC) in this project, by platform (lowercase)."""
    try:
        from ..dag.queue import agent_gpu_hours_by_platform_today
        from ..dag.service import store_for
        return agent_gpu_hours_by_platform_today(store_for(pid))
    except Exception:  # noqa: BLE001 — a project without a map has queued nothing
        log.debug("no agent usage for %s", pid, exc_info=True)
        return {}


# ---------------------------------------------------------------- views

def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 1)


def _quota_text(q: dict) -> str:
    def fmt(v):
        return "?" if v is None else f"{v:g}"
    return f"{fmt(q['current'])} / {fmt(q['limit'])}" + (f" {q['unit']}" if q["unit"] and q["unit"] != "count" else "")


def credential_view(pool: dict, doc: dict | None) -> dict | None:
    ref = pool.get("credential")
    expires = ((doc or {}).get("credential") or {}).get("expires_at")
    if not ref and not expires:
        return None
    dt = _time(expires) if expires else None
    days = None if dt is None else (dt - datetime.now(UTC)).total_seconds() / 86400
    state = None if days is None else "expired" if days <= 0 else "soon" if days <= CREDENTIAL_SOON_DAYS else "ok"
    return {"ref": ref, "expires_at": expires, "days_left": None if days is None else round(days, 1), "state": state}


def node_view(pool: dict, doc: dict, n: dict, age: float | None, stale_after: float | None) -> dict:
    telemetry = n["cpu"] is not None or n["ram"] is not None or any(
        g["util"] is not None or g["mem_used_mib"] is not None for g in n["gpus"])
    gpus = [{"name": g["model"], "util": _pct(g["util"]), "mem_used": g["mem_used_mib"], "mem_total": g["mem_total_mib"],
             "temp": g["temp_c"], "power": g["power_w"], "mem_unit": "MiB"} for g in n["gpus"] for _ in range(g["count"])]
    price = node_price(pool, doc, n)
    return {"id": n["id"], "label": n["label"], "status": n["status"], "state": n["state"], "flavor": n.get("flavor"),
            "gpus": gpus, "cpu": _pct(n["cpu"]), "ram": _pct(n["ram"]), "running": n["running"], "queued": n["queued"],
            "telemetry_at": doc.get("as_of") if telemetry else None,
            "telemetry_age_s": round(age) if telemetry and age is not None else None,
            "stale": bool(telemetry and stale_after and age is not None and age > stale_after), "inventory_only": not telemetry,
            "price": {k: price[k] for k in ("state", "amount", "unit", "item", "rule_amount", "from")}}


def platform_view(pool: dict, rec: dict, *, here: bool = True, agent_used: float | None = None) -> dict:
    doc, src = rec.get("doc"), pool["source"]
    stale_after = None if src["type"] == "manual" else max(60, 3 * src["every"])
    age = age_s((doc or {}).get("as_of") or rec.get("read_at"))
    if not doc:
        state = "failed" if rec.get("error") else "reading"
    elif rec.get("error"):
        state = "failed"                    # showing the last good read
    elif stale_after and age is not None and age > stale_after:
        state = "stale"
    else:
        state = "ok"
    nodes = [node_view(pool, doc, n, age, stale_after) for n in (doc or {}).get("nodes") or []]
    quota_items = [{"name": q["name"], "current": q["used"], "limit": q["limit"], "unit": q["unit"] or ""}
                   for q in (doc or {}).get("quota") or []]
    spend = (doc or {}).get("spend")
    cost = None if not spend else {
        "amount": spend["amount"], "currency": spend["unit"], "as_of": spend.get("as_of") or doc.get("as_of"),
        "estimate": spend["kind"] != "billed", "since": spend.get("since"), "metric": "spend_to_date"}
    r = rate(pool, doc)
    return {
        "id": pool["id"], "label": pool["label"], "kind": pool["kind"],
        "status": {"ok": "ok", "stale": "degraded", "failed": "degraded", "reading": "unknown"}[state],
        "nodes": nodes, "quota": {q["name"]: _quota_text(q) for q in quota_items} or None, "quota_items": quota_items,
        "cost": cost, "note": pool.get("note"), "checked_at": rec.get("read_at"), "provider_kind": src["type"],
        "pool": {
            "state": state, "here": here, "source": {k: v for k, v in src.items() if k != "inventory"},
            "read_at": rec.get("read_at"), "age_s": None if age is None else round(age), "tried_at": rec.get("tried_at"),
            "error": rec.get("error"), "warnings": rec.get("warnings") or [], "duration_s": rec.get("duration_s"),
            "reading": reading(pool["id"]), "capabilities": (doc or {}).get("capabilities") or [],
            "credential": credential_view(pool, doc), "billed": pool["kind"] not in UNBILLED,
            "prices": rules(pool, doc), "rate": r,
            "budget": {"agent_gpu_hours_per_day": pool["budget"].get("agent_gpu_hours_per_day"), "agent_used_today": agent_used,
                       "month": pool["budget"].get("month")},
        },
    }


def view(pool: dict, pid: str | None = None, *, sel: list[str] | None = None, usage: dict[str, float] | None = None) -> dict:
    """One pool for the pages: the definition and its platform view, for a project when given."""
    if pid and usage is None:
        usage = agent_usage_today(pid)
        sel = selection(pid)
    here = sel is None or pool["id"] in sel
    return {"def": pool, "platform": platform_view(pool, record(pool), here=here,
                                                   agent_used=(usage or {}).get(pool["id"], 0.0) if pid else None)}


def snapshot(pid: str | None = None) -> dict:
    """GET /api/resources: every pool as a platform, read in the background when due."""
    pools = store.load_all()
    refresh_due(pools)
    sel = selection(pid) if pid else None
    usage = agent_usage_today(pid) if pid else {}
    platforms = [view(p, pid, sel=sel, usage=usage)["platform"] for p in pools]
    return {"source": "pools", "as_of": sources.now_iso(), "platforms": platforms, "alerts": [],
            "selection": sel, "unmatched": unmatched(pid, pools) if pid else []}
