"""Check a resource pool, or what a pool adapter prints, against rd-pool/1.

    python -m research_deck.pools list                     the pools on this machine and their last read
    python -m research_deck.pools check <id>               read the pool once (nothing is saved) and say what is missing,
                                                           wrong or in the wrong unit
    python -m research_deck.pools check --file out.json    the same for a document an adapter printed (- reads stdin)

Exit status: 0 a valid rd-pool/1 document, 1 valid with warnings, 2 unreadable or not rd-pool/1.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fastapi import HTTPException

from . import protocol, service, sources, store


def describe(doc: dict) -> list[str]:
    nodes = doc["nodes"]
    gpus: dict[str, int] = {}
    for n in nodes:
        for g in n["gpus"]:
            gpus[g["model"]] = gpus.get(g["model"], 0) + g["count"]
    lines = [f"machines   {len(nodes)} ({sum(1 for n in nodes if n['status'] == 'online')} online)"
             + (f" · GPUs: {', '.join(f'{m} × {c}' for m, c in gpus.items())}" if gpus else " · no GPUs"),
             f"reads      {', '.join(doc['capabilities']) or 'nothing'}"]
    for q in doc["quota"]:
        lines.append(f"quota      {q['name']}: {q['used'] if q['used'] is not None else '?'} / "
                     f"{q['limit'] if q['limit'] is not None else 'limit unknown'} {q['unit'] or ''}".rstrip())
    if doc["spend"]:
        s = doc["spend"]
        lines.append(f"spend      {s['amount'] if s['amount'] is not None else '?'} {s['unit']} ({s['kind']}"
                     + (f", since {s['since']}" if s["since"] else "") + ")")
    for p in doc["prices"]:
        match = ", ".join(f"{k}={v}" for k, v in p["match"].items()) or "everything"
        lines.append(f"price      {p['amount']:g} {p['unit']} per {p['item'].replace('_', '-')} ({match})")
    if doc["credential"]["expires_at"]:
        lines.append(f"credential expires {doc['credential']['expires_at']}")
    return lines


def check(doc: dict, warnings: list[str], out=None) -> int:
    out = out or sys.stdout
    print(f"{protocol.PROTOCOL} ✓  as_of {doc['as_of'] or '(missing)'}", file=out)
    for line in describe(doc):
        print("  " + line, file=out)
    for w in warnings:
        print(f"  warning: {w}", file=out)
    return 1 if warnings else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research_deck.pools", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="the pools on this machine and their last read")
    c = sub.add_parser("check", help="read a pool once, or check a document, against rd-pool/1")
    c.add_argument("id", nargs="?", help="a pool id (see list)")
    c.add_argument("--file", help="a document an adapter printed; - reads stdin")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        errors: list[dict] = []
        for p in store.load_all(errors):
            rec = service.cached(p)
            last = rec.get("read_at") or "never read"
            err = f" · last read failed: {rec['error']}" if rec.get("error") else ""
            print(f"{p['id']:<20} {p['label']:<24} {p['kind']:<8} {p['source']['type']:<8} {last}{err}")
        for e in errors:
            print(f"{e['file']}: does not validate: {e['error']}")
        print(f"({store.pools_dir()})")
        return 0

    if bool(args.id) == bool(args.file):
        ap.error("check takes a pool id or --file, one of them")
    try:
        if args.file:
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            doc, warnings = sources.parse_text(text)
        else:
            doc, warnings, _raw = sources.read(store.get(args.id))
    except (sources.SourceError, OSError) as e:
        print(f"not readable: {e}", file=sys.stderr)
        return 2
    except HTTPException as e:
        print(e.detail, file=sys.stderr)
        return 2
    return check(doc, warnings)


if __name__ == "__main__":
    sys.exit(main())
