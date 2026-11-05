"""Replay the synthetic trace through one eviction policy and print its hit rate.

    python -m toycache.sim --config configs/base.yaml [--config configs/lookahead.yaml] [--set policy=lfu]
"""
import argparse
import importlib

import yaml

from .trace import make_trace


def merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        base[k] = merge(base.get(k, {}), v) if isinstance(v, dict) else v
    return base


def load_config(paths: list[str], sets: list[str]) -> dict:
    cfg: dict = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            merge(cfg, yaml.safe_load(f) or {})
    for item in sets:                      # --set key.sub=value
        key, _, raw = item.partition("=")
        *parents, leaf = key.split(".")
        node = cfg
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = yaml.safe_load(raw)
    return cfg


def run(cfg: dict) -> dict:
    t = cfg["trace"]
    trace = make_trace(t["length"], t["blocks"], t["skew"], t["drift_every"], t["seed"])
    name = cfg["policy"]
    params = cfg.get(name) or {}           # e.g. lookahead: {window: 8}
    cache = importlib.import_module(f"toycache.{name}").POLICY(cfg["cache"]["capacity_blocks"], **params)
    window = int(params.get("window", 0))
    hits = sum(cache.access(b, trace[i + 1:i + 1 + window]) for i, b in enumerate(trace))
    return {"policy": name, "capacity_blocks": cache.capacity, "hit_rate": round(hits / len(trace), 3)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", action="append", required=True)
    ap.add_argument("--set", action="append", default=[])
    args = ap.parse_args(argv)
    print(run(load_config(args.config, args.set)))


if __name__ == "__main__":
    main()
