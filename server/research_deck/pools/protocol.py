"""rd-pool/1: one JSON document that says what a pool has, what runs on it, how much of its quota is used, what was spent
and what things cost. Every source (sources.py) returns one; normalize() turns whatever arrived into a clean one and
says what was wrong with it.

{
  "protocol": "rd-pool/1",                       required
  "as_of": "2026-11-05T22:10:41Z",                when it was read (UTC)
  "nodes": [{"id", "label", "status": "online|offline|unknown", "state": "running|stopped|…", "flavor",
             "gpus": [{"model", "count", "mem_total_mib", "mem_used_mib", "util": 0–1, "temp_c", "power_w"}],
             "cpu": 0–1, "ram": 0–1, "running": ["job"], "queued": 1}],
  "quota": [{"name", "used", "limit", "unit"}],
  "spend": {"amount", "unit", "since", "as_of", "kind": "billed|estimate"},
  "prices": [{"item": "gpu_hour|node_hour", "match": {"gpu"|"flavor"|"node": "…"}, "amount", "unit"}],
  "credential": {"expires_at"},
  "capabilities": ["inventory", "telemetry", "quota", "spend", "prices"]
}

Unknown is null, never 0. Units are explicit: money as a currency code (USD, CNY), quota in its own unit (SU, credits),
memory in MiB, temperature in °C, power in W, utilization 0–1. Fields this version does not know are ignored.
"""
from __future__ import annotations

from typing import Any

PROTOCOL = "rd-pool/1"
KINDS = ("local", "home", "lab", "cluster", "cloud")
CAPABILITIES = ("inventory", "telemetry", "quota", "spend", "prices")
PRICE_ITEMS = ("gpu_hour", "node_hour")
MATCH_KEYS = ("gpu", "flavor", "node")
NODE_STATUS = ("online", "offline", "unknown")
SPEND_KINDS = ("billed", "estimate")
MAX_NODES = 500
MAX_GPUS = 64
MAX_TEXT = 200


def _text(v: Any, limit: int = MAX_TEXT) -> str | None:
    return str(v).strip()[:limit] if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip() else None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if v == v else None          # NaN is unknown


def _frac(v: Any, what: str, warnings: list[str]) -> float | None:
    """A 0–1 share; a percentage (1 < v <= 100) is taken as one, with a warning."""
    x = _num(v)
    if x is None:
        return None
    if 1 < x <= 100:
        warnings.append(f"{what} looks like a percentage ({x:g}); read as {x / 100:g}")
        x /= 100
    return min(1.0, max(0.0, x))


def _gpu(g: Any, where: str, warnings: list[str]) -> dict | None:
    if not isinstance(g, dict):
        warnings.append(f"{where}: not an object")
        return None
    model = _text(g.get("model") or g.get("name"))
    if not model:
        warnings.append(f"{where}: no model")
        return None
    count = g.get("count", 1)
    count = int(count) if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 1
    return {"model": model, "count": min(count, MAX_GPUS), "mem_total_mib": _num(g.get("mem_total_mib")),
            "mem_used_mib": _num(g.get("mem_used_mib")), "util": _frac(g.get("util"), f"{where}.util", warnings),
            "temp_c": _num(g.get("temp_c")), "power_w": _num(g.get("power_w"))}


def node(n: Any, where: str, warnings: list[str]) -> dict | None:
    """One node (also what a manual pool's inventory holds)."""
    if not isinstance(n, dict):
        warnings.append(f"{where}: not an object")
        return None
    nid = _text(n.get("id"), 120)
    if not nid:
        warnings.append(f"{where}: no id")
        return None
    status = n.get("status") if n.get("status") in NODE_STATUS else "unknown"
    gpus = [x for k, g in enumerate((n.get("gpus") or [])[:MAX_GPUS]) if (x := _gpu(g, f"{where}.gpus[{k}]", warnings))]
    running = [s for r in n.get("running") or [] if (s := _text(r, 120))][:50] if isinstance(n.get("running"), list) else []
    queued = n.get("queued")
    return {"id": nid, "label": _text(n.get("label"), 120) or nid, "status": status, "state": _text(n.get("state"), 40),
            "flavor": _text(n.get("flavor"), 80), "gpus": gpus, "cpu": _frac(n.get("cpu"), f"{where}.cpu", warnings), "ram": _frac(n.get("ram"), f"{where}.ram", warnings),
            "running": running, "queued": queued if isinstance(queued, int) and not isinstance(queued, bool) and queued >= 0 else None}


def price(p: Any, where: str, warnings: list[str]) -> dict | None:
    """One price rule (also what a pool definition's prices hold)."""
    if not isinstance(p, dict):
        warnings.append(f"{where}: not an object")
        return None
    item, amount, unit = p.get("item"), _num(p.get("amount")), _text(p.get("unit"), 20)
    if item not in PRICE_ITEMS:
        warnings.append(f"{where}: item must be one of {', '.join(PRICE_ITEMS)}")
        return None
    if amount is None or amount < 0 or not unit:
        warnings.append(f"{where}: needs an amount (>= 0) and a unit")
        return None
    match = {k: v for k, raw in (p.get("match") or {}).items() if k in MATCH_KEYS and (v := _text(raw, 120))} \
        if isinstance(p.get("match"), dict) else {}
    return {"item": item, "match": match, "amount": amount, "unit": unit}


def normalize(doc: Any) -> tuple[dict, list[str]]:
    """A clean rd-pool/1 document and the warnings about the input; ValueError when it is not one at all."""
    if not isinstance(doc, dict):
        raise ValueError("an rd-pool document is a JSON object")
    proto = str(doc.get("protocol") or "")
    if proto != PROTOCOL:
        raise ValueError(f'protocol must be "{PROTOCOL}" (got {proto or "nothing"})')
    warnings: list[str] = []
    as_of = _text(doc.get("as_of"), 40)
    if not as_of:
        warnings.append("as_of is missing: the time of the read is used")
    nodes_in = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    if len(nodes_in) > MAX_NODES:
        warnings.append(f"{len(nodes_in)} nodes: only the first {MAX_NODES} are kept")
    nodes = [x for k, n in enumerate(nodes_in[:MAX_NODES]) if (x := node(n, f"nodes[{k}]", warnings))]
    quota = []
    for k, q in enumerate(doc.get("quota") or [] if isinstance(doc.get("quota"), list) else []):
        name = _text(q.get("name"), 80) if isinstance(q, dict) else None
        if not name:
            warnings.append(f"quota[{k}]: no name")
            continue
        limit = _num(q.get("limit"))
        if limit is None:
            warnings.append(f"quota[{k}] has no limit: shown as limit unknown, not as no limit")
        quota.append({"name": name, "used": _num(q.get("used")), "limit": limit, "unit": _text(q.get("unit"), 20)})
    spend = None
    s = doc.get("spend")
    if isinstance(s, dict):
        if _text(s.get("unit"), 20):
            spend = {"amount": _num(s.get("amount")), "unit": _text(s.get("unit"), 20), "since": _text(s.get("since"), 40),
                     "as_of": _text(s.get("as_of"), 40), "kind": s.get("kind") if s.get("kind") in SPEND_KINDS else "estimate"}
        else:
            warnings.append("spend has no unit: left out")
    prices = [x for k, p in enumerate(doc.get("prices") or [] if isinstance(doc.get("prices"), list) else [])
              if (x := price(p, f"prices[{k}]", warnings))]
    cred = doc.get("credential") if isinstance(doc.get("credential"), dict) else {}
    caps = [c for c in doc.get("capabilities") or [] if c in CAPABILITIES] if isinstance(doc.get("capabilities"), list) else []
    if not caps:                                    # what the document shows it can tell
        caps = [c for c, has in (("inventory", bool(nodes)), ("telemetry", any(g["util"] is not None for n in nodes for g in n["gpus"])
                                  or any(n["cpu"] is not None for n in nodes)), ("quota", bool(quota)), ("spend", spend is not None),
                                 ("prices", bool(prices))) if has]
    return ({"protocol": PROTOCOL, "as_of": as_of, "nodes": nodes, "quota": quota, "spend": spend, "prices": prices,
             "credential": {"expires_at": _text(cred.get("expires_at"), 40)}, "capabilities": caps}, warnings)
