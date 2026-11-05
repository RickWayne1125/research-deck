"""python -m research_deck.dag.rd_exec --spec spec.json [--cell '{"rate": 8}'] [--root .] [--out rd_run.json] -- cmd ...

Runs the command `replicates` times under the tracer, extracts the outputs and writes the run record (rd_run.json),
which the experiments slice (or you) POSTs to /api/projects/<pid>/dag/runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .trace import git, run_job


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("usage: python -m research_deck.dag.rd_exec --spec spec.json [--cell JSON] -- command ...", file=sys.stderr)
        return 2
    i = argv.index("--")
    ap = argparse.ArgumentParser(prog="rd_exec")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--cell", default="{}")
    ap.add_argument("--root", default=None, help="project root (default: the git top level, else the current folder)")
    ap.add_argument("--out", default="rd_run.json")
    ap.add_argument("--replicates", type=int, default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--platform", default=None)
    args = ap.parse_args(argv[:i])
    command = argv[i + 1:]
    if not command:
        ap.error("no command after --")
    if args.root:
        root = Path(args.root)
    else:
        top = git(Path.cwd(), "rev-parse", "--show-toplevel")
        root = Path(top.decode().strip()) if top else Path.cwd()
    spec_doc = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    rec = run_job(spec_doc, json.loads(args.cell or "{}"), command, root, replicates=args.replicates, run_id=args.run_id,
                  platform=args.platform)
    Path(args.out).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"rd_exec: {rec['state']} {rec['id']} cell={rec['cell']} trace={len(rec['trace'])} items ({rec['trace_quality']})"
          f" -> {args.out}", file=sys.stderr)
    return 0 if rec["state"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
