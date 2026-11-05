"""python -m research_deck.dag check|eval|preview --project <root> [--staged | --diff A..B | --worktree]

  check    schema, cycles, dangling edges, unsealed YAML, forks, locks (exit 1 when anything is wrong)
  eval     the four lenses and every node that is not fresh
  preview  the impact of a code change (default: staged), as JSON — the same function as POST /dag/impact
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evaluate import current
from .gates import lenses
from .impact import impact
from .service import check
from .store import DagStore


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research_deck.dag")
    ap.add_argument("command", choices=["check", "eval", "preview"])
    ap.add_argument("--project", default=".", help="project root (the folder holding .research/)")
    ap.add_argument("--state", default=".research", help="the project's state folder under the root (.research or .research-<slug>)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true")
    g.add_argument("--diff", metavar="A..B")
    g.add_argument("--worktree", action="store_true")
    args = ap.parse_args(argv)
    store = DagStore(Path(args.project).resolve(), state=args.state)
    if not store.exists:
        print(f"no DAG under {store.dir}", file=sys.stderr)
        return 2
    st = current(store)
    if args.command == "check":
        report = check(st)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if any(v for k, v in report.items() if k != "warnings") else 0
    if args.command == "eval":
        L = lenses(st)
        print(f"digest {st.digest}  " + "  ".join(f"{k} {v['count']}" for k, v in L.items()))
        for nid, ev in sorted(st.E.items()):
            if ev.level not in ("fresh", None):
                why = next((r.get("note") or r.get("edge") for r in ev.reasons if r["level"] != "fresh"), "")
                cells = [f"{c}={x.level}" for c, x in ev.cells.items() if x.level != "fresh"]
                print(f"  {ev.level:9} {nid}  {why or ''} {' '.join(cells[:6])}".rstrip())
        return 0
    code = {"diff": args.diff} if args.diff else {"worktree": True} if args.worktree else {"staged": True}
    print(json.dumps(impact(store, {"code": code}), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
