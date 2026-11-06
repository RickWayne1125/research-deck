#!/usr/bin/env python3
"""rd-pool/1 for a Slurm cluster: its nodes, their GPUs (GRES), CPU load, memory and running jobs, read over ssh
from a login node with sinfo and squeue. Inventory and load only: Slurm does not report GPU utilization.

    python3 rd_pool_slurm.py login-node [--partition gpu] [--user]

Use it as a resource pool's command source in Research Deck: [python3, /path/to/rd_pool_slurm.py, login-node,
--partition, gpu]. ssh runs in batch mode (set up a key or an ssh-agent first); pass --local to run sinfo and squeue
on this machine instead. --user lists only your own jobs. Prints one rd-pool/1 document and exits 0; exits 1 with the
reason on stderr when it cannot read the cluster. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime

SINFO = "sinfo -N -h -o '%N|%T|%G|%c|%O|%m|%e|%P'"
SQUEUE = "squeue -h -t RUNNING -o '%N|%j'"
ONLINE = ("idle", "mixed", "allocated", "completing", "reserved", "planned")
OFFLINE = ("down", "drained", "draining", "fail", "failing", "inval", "not_responding", "powered_down", "power_down")


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None                         # N/A


def hostnames(nodelist: str) -> list[str]:
    """Expand a Slurm host list: gpu[01-03,07],cpu5 → gpu01 gpu02 gpu03 gpu07 cpu5."""
    out, depth, cur = [], 0, ""
    for ch in nodelist.strip():            # split on the commas outside brackets
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        depth += {"[": 1, "]": -1}.get(ch, 0)
        cur += ch
    out.append(cur)
    names = []
    for item in filter(None, out):
        m = re.fullmatch(r"(.*?)\[([^\]]+)\](.*)", item)
        if not m:
            names.append(item)
            continue
        prefix, ranges, suffix = m.groups()
        for r in ranges.split(","):
            lo, _, hi = r.partition("-")
            if hi and lo.isdigit() and hi.isdigit():
                names += [f"{prefix}{str(i).zfill(len(lo))}{suffix}" for i in range(int(lo), int(hi) + 1)][:4096]
            else:
                names.append(f"{prefix}{r}{suffix}")
    return names


def gres_gpus(gres: str) -> list[dict]:
    """GPUs from a GRES string: gpu:a100:4(S:0-1),gpu:2 → A100 × 4, GPU × 2."""
    gpus = []
    for part in gres.split(","):
        fields = part.split("(")[0].split(":")
        if fields[0] != "gpu" or len(fields) < 2:
            continue
        count = int(fields[-1]) if fields[-1].isdigit() else 1
        model = fields[1] if len(fields) >= 3 else "GPU"
        gpus.append({"model": model, "count": count, "mem_total_mib": None, "mem_used_mib": None, "util": None})
    return gpus


def parse(sinfo: str, squeue: str) -> dict:
    nodes: dict[str, dict] = {}
    for line in sinfo.splitlines():
        f = line.strip().split("|")
        if len(f) < 8 or not f[0]:
            continue
        name, state, gres, cpus, load, mem, free, part = f[:8]
        if name in nodes:                   # one line per partition the node is in
            nodes[name]["partitions"].append(part.rstrip("*"))
            continue
        base = state.rstrip("*~#!%$@^-+").lower()
        status = "online" if base in ONLINE else "offline" if base in OFFLINE else "unknown"
        c, ld, m, fr = _num(cpus), _num(load), _num(mem), _num(free)
        nodes[name] = {"id": name, "label": name, "status": status, "state": base, "gpus": gres_gpus(gres),
                       "cpu": None if not c or ld is None else max(0.0, min(1.0, ld / c)),
                       "ram": None if not m or fr is None else max(0.0, min(1.0, 1 - fr / m)),
                       "running": [], "partitions": [part.rstrip("*")]}
    for line in squeue.splitlines():
        nodelist, _, job = line.strip().partition("|")
        for host in hostnames(nodelist):
            if host in nodes and len(nodes[host]["running"]) < 50:
                nodes[host]["running"].append(job or "job")
    for n in nodes.values():
        n["flavor"] = n.pop("partitions")[0]     # the (first) partition, for prices matched by flavor
    return {"protocol": "rd-pool/1", "as_of": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "nodes": list(nodes.values()), "capabilities": ["inventory", "telemetry"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="rd-pool/1 for a Slurm cluster")
    ap.add_argument("host", nargs="?", help="the login node, as you would pass it to ssh")
    ap.add_argument("--local", action="store_true", help="run sinfo and squeue here instead of over ssh")
    ap.add_argument("--partition", help="only this partition (or a comma-separated list)")
    ap.add_argument("--user", action="store_true", help="only your own running jobs")
    ap.add_argument("--timeout", type=int, default=25)
    args = ap.parse_args(argv)
    if bool(args.host) == args.local:
        ap.error("give the login node, or --local")
    sinfo, squeue = SINFO, SQUEUE
    if args.partition:
        sinfo += f" -p {shlex.quote(args.partition)}"
        squeue += f" -p {shlex.quote(args.partition)}"
    if args.user:
        squeue += " --me"
    script = f"{sinfo}\necho '@@'\n{squeue}\n"          # to sh on stdin, whatever the login shell over there is
    cmd = ["sh", "-s"] if args.local else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host, "sh", "-s"]
    try:
        p = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=args.timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"{'sinfo' if args.local else 'ssh ' + args.host}: {e}", file=sys.stderr)
        return 1
    if p.returncode != 0 or "@@" not in p.stdout:
        print((p.stderr.strip() or f"exit {p.returncode}")[-400:], file=sys.stderr)
        return 1
    a, _, b = p.stdout.partition("@@\n")
    print(json.dumps(parse(a, b)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
