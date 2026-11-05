"""Demo resources for the Resources tab: three made-up platforms (a workstation, a lab server, a cloud allocation).

Every value is invented and flagged: `source: "demo"` on the snapshot and `demo: true` on every platform, node and
cost. Unknown stays unknown (None), never 0. Telemetry moves a little with time so the auto-refresh is visible,
deterministically (no randomness). The shape is `Resources` (docs/API.md); a real source would return the same.
"""
from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _wave(t: float, period: float, lo: float, hi: float, phase: float = 0.0) -> float:
    return round(lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * t / period + phase)), 1)


def resources(now: float | None = None) -> dict:
    t = time.time() if now is None else now
    at = datetime.fromtimestamp(t, tz=UTC)

    unknown_gpu = lambda name, mem_total: {"name": name, "util": None, "mem_used": None, "mem_total": mem_total,  # noqa: E731
                                           "temp": None, "power": None, "mem_unit": "MiB", "demo": True}

    workstation = {
        "id": "demo-workstation", "label": "workstation", "status": "online", "demo": True, "agent": True,
        "cpu": _wave(t, 97, 22, 41), "ram": _wave(t, 230, 55, 63, 1.0),
        "gpus": [{"name": "GPU-24GB", "util": _wave(t, 37, 84, 97), "mem_used": round(_wave(t, 120, 19800, 21400)),
                  "mem_total": 24576, "temp": _wave(t, 61, 66, 73, 0.5), "power": _wave(t, 43, 280, 340, 0.3),
                  "mem_unit": "MiB", "demo": True}],
        "running": ["lookahead"], "queued": 1,
        "telemetry_at": _iso(at - timedelta(seconds=4)), "telemetry_age_s": 4, "stale": False,
        "note": "a machine of your own with a telemetry agent", "note_key": "ex.demo.note.workstation",
    }
    lab = {
        "id": "demo-lab", "label": "lab-server-01", "status": "online", "demo": True,
        "inventory_only": True, "state": "running",
        "gpus": [unknown_gpu("GPU-48GB", 49152)], "running": [], "telemetry_at": None,
        "note": "inventory only: no agent, so no GPU telemetry", "note_key": "ex.demo.note.labnode",
    }
    cloud_nodes = [
        {"id": f"demo-cloud-{i}", "label": f"cloud-gpu-0{i}", "status": "online" if i < 3 else "offline", "demo": True,
         "inventory_only": True, "state": "running" if i < 3 else "stopped",
         "gpus": [unknown_gpu("GPU-80GB", 81920)], "running": [], "telemetry_at": None,
         "note": "inventory only: no agent, so no GPU telemetry", "note_key": "ex.demo.note.labnode"}
        for i in (1, 2, 3)
    ]
    platforms = [
        {"id": "workstation", "label": "Workstation", "kind": "home", "status": "ok", "demo": True, "nodes": [workstation],
         "quota": None, "quota_items": [], "cost": None,
         "note": "own hardware: not billed", "note_key": "ex.demo.note.home"},
        {"id": "lab", "label": "Lab server", "kind": "lab", "status": "ok", "demo": True, "nodes": [lab],
         "quota": {"GPU request": "1 × 48 GiB"}, "quota_items": [{"name": "GPU request", "current": None, "limit": "1 × 48 GiB", "unit": ""}],
         "quota_note": "free capacity is unknown", "quota_note_key": "ex.demo.quota.lab", "cost": None,
         "note": "shared by the lab; read-only inventory", "note_key": "ex.demo.note.lab"},
        {"id": "cloud", "label": "Cloud allocation", "kind": "cloud", "status": "ok", "demo": True, "nodes": cloud_nodes,
         "quota": {"instances": "3 / 10", "vCPUs": "48 / 256"},
         "quota_items": [{"name": "instances", "current": 3, "limit": 10, "unit": "count"},
                         {"name": "vCPUs", "current": 48, "limit": 256, "unit": "count"}],
         "cost": {"amount": 420.0, "currency": "USD", "as_of": _iso(at - timedelta(hours=14)), "estimate": True,
                  "metric": "estimated_since_tracking", "source": "hourly estimate × observed running time (not billed usage)",
                  "source_key": "ex.r.estimateSource", "demo": True},
         "note": "read-only inventory and quota", "note_key": "ex.demo.note.cloud"},
    ]
    return {"source": "demo", "demo": True, "as_of": _iso(at), "platforms": platforms, "alerts": []}
