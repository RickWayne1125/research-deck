#!/usr/bin/env python3
"""rd-pool/1 for one machine you can reach over ssh: its NVIDIA GPUs (nvidia-smi), load, memory and GPU processes.

    python3 rd_pool_ssh.py gpu-box [--id gpu-box] [--label "GPU box"]

Use it as a resource pool's command source in Research Deck (Settings › Resource pools › Add › Command):
[python3, /path/to/rd_pool_ssh.py, gpu-box]. ssh runs in batch mode, so it never asks for a password: set up a key or
an ssh-agent for the host first (ssh gpu-box true should work without prompting). It prints one rd-pool/1 document
and exits 0; when it cannot read the machine it exits 1 with the reason on stderr, which Research Deck shows as the
read error while it keeps the last good reading. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime

NVIDIA_QUERY = "index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw"
REMOTE = "\necho '@@'\n".join([
    f"nvidia-smi --query-gpu={NVIDIA_QUERY} --format=csv,noheader,nounits 2>/dev/null",
    "cat /proc/loadavg 2>/dev/null || sysctl -n vm.loadavg 2>/dev/null",
    "nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null",
    "grep -E '^(MemTotal|MemAvailable):' /proc/meminfo 2>/dev/null",
    "nvidia-smi --query-compute-apps=process_name --format=csv,noheader 2>/dev/null",
])


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None                         # [N/A], [Not Supported]


def parse(out: str, node_id: str, label: str) -> dict:
    """The rd-pool/1 document for what the remote commands printed (sections separated by @@ lines)."""
    parts = (out.split("@@\n") + [""] * 5)[:5]
    smi, load, ncpu, mem, apps = (p.strip() for p in parts)
    gpus = []
    for line in smi.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) >= 7 and f[1]:
            util = _num(f[4])
            gpus.append({"model": f[1], "count": 1, "mem_total_mib": _num(f[2]), "mem_used_mib": _num(f[3]),
                         "util": None if util is None else util / 100, "temp_c": _num(f[5]), "power_w": _num(f[6])})
    cpu = None
    first = load.replace("{", " ").split()
    cores = _num(ncpu.split()[0]) if ncpu.split() else None
    if first and cores:
        avg = _num(first[0])
        cpu = None if avg is None else max(0.0, min(1.0, avg / cores))
    ram = None
    kb = {k.rstrip(":"): _num(v) for k, v, *_ in (line.split() for line in mem.splitlines() if len(line.split()) >= 2)}
    if kb.get("MemTotal") and kb.get("MemAvailable") is not None:
        ram = max(0.0, min(1.0, 1 - kb["MemAvailable"] / kb["MemTotal"]))
    running = sorted({a.strip().rsplit("/", 1)[-1] for a in apps.splitlines() if a.strip()})[:20]
    return {"protocol": "rd-pool/1", "as_of": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "nodes": [{"id": node_id, "label": label, "status": "online", "gpus": gpus, "cpu": cpu, "ram": ram,
                       "running": running}],
            "capabilities": ["inventory", "telemetry"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="rd-pool/1 for one machine over ssh")
    ap.add_argument("host", help="what you would pass to ssh (a Host from ~/.ssh/config, or user@host)")
    ap.add_argument("--id", help="the machine's id in the document (default: the host)")
    ap.add_argument("--label", help="its label (default: the id)")
    ap.add_argument("--timeout", type=int, default=20, help="seconds for the ssh call")
    args = ap.parse_args(argv)
    # The script goes to sh on stdin, whatever the login shell over there is.
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host, "sh", "-s"]
    try:
        p = subprocess.run(cmd, input=REMOTE + "\n", capture_output=True, text=True, timeout=args.timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"ssh {args.host}: {e}", file=sys.stderr)
        return 1
    if p.returncode == 255:                 # ssh's own failure: unreachable, refused, no key
        print(f"ssh {args.host}: {p.stderr.strip()[-400:] or 'connection failed'}", file=sys.stderr)
        return 1
    node_id = args.id or args.host.split("@")[-1]
    print(json.dumps(parse(p.stdout, node_id, args.label or node_id)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
