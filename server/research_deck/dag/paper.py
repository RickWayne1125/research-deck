"""The paper side of the DAG (docs/DAG.md §1 W, §6): tex anchors → section nodes and describes edges; number macros.

In a .tex file under paper.root:
    % rd:sec sec.design            a section node owns the region up to `% rd:end`
    % rd:describes claim.ttft-2x   (or \\rdref{claim.ttft-2x}) a describes edge from that section
    \\rdTtftSpeedupMax              a claim binding's macro: also a describes edge to that claim
`paper/generated/rdvalues.tex` holds one \\newcommand per binding with a macro, from the ACTUAL value of the selected
runs; a binding whose node is not fresh is wrapped in \\rdstale{…} (red in draft mode).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..util import write_text_atomic
from .evaluate import State, current
from .model import DEAD, edges, facet_value, title_of
from .ops import apply_ops
from .resolve import END_RE, SEC_RE

DESCRIBES_RE = re.compile(r"%\s*rd:describes\s+(\S+)|\\rdref\{([^}]+)\}")
MACRO_RE = re.compile(r"\\(rd[A-Za-z]+)")


def tex_files(st: State) -> list[str]:
    root = str((st.cfg.get("paper") or {}).get("root") or "paper").strip("/")
    return sorted(p for p in st.R.tree().files if p.startswith(root + "/") and p.endswith(".tex")
                  and not p.endswith("rdvalues.tex"))


def macro_owners(st: State) -> dict[str, str]:
    out = {}
    for n in st.nodes.values():
        for b in (facet_value(n, "bindings") or {}).values():
            if isinstance(b, dict) and b.get("macro"):
                out[str(b["macro"]).lstrip("\\")] = n["id"]
    return out


def anchors(st: State) -> dict[str, dict]:
    """{section id: {file, line, targets: set of addresses, lines: {address: first line naming it}}} from every tex
    file."""
    owners, out = macro_owners(st), {}
    for path in tex_files(st):
        text = (st.R.tree().read(path) or b"").decode("utf-8", errors="replace")
        cur = None
        for i, line in enumerate(text.splitlines(), 1):
            if (m := SEC_RE.match(line)):
                cur = out.setdefault(m.group(1), {"file": path, "line": i, "targets": set(), "lines": {}})
                continue
            if END_RE.match(line):
                cur = None
                continue
            if cur is None:
                continue
            for a, b in DESCRIBES_RE.findall(line):
                target = a or b
                addr = target if target.startswith("node:") else f"node:{target}"
                cur["targets"].add(addr)
                cur["lines"].setdefault(addr, i)
            for macro in MACRO_RE.findall(line):
                if macro in owners:
                    cur["targets"].add(f"node:{owners[macro]}")
                    cur["lines"].setdefault(f"node:{owners[macro]}", i)
    return out


def sync(store, actor: str = "system:paper") -> dict:
    """Section nodes and their describes edges follow the anchors; then regenerate the macros."""
    st = current(store)
    ops, added, removed = [], [], []
    for sid, a in sorted(anchors(st).items()):
        if not sid.startswith("sec."):
            continue
        n = st.nodes.get(sid)
        want = {t for t in a["targets"] if t.split(":", 1)[1].split("#")[0] in st.nodes}
        if n is None:
            ops.append({"op": "create", "node": {"id": sid, "kind": "section", "stage": "W", "status": "active",
                                                 "title": {"en": sid.split(".", 1)[1].replace("-", " ").capitalize()},
                                                 "facets": {"file": {"type": "json", "value": a["file"]}, "text": {"type": "derived"}},
                                                 "edges": [{"type": "describes", "to": t} for t in sorted(want)]}})
            added += [f"{sid} → {t}" for t in sorted(want)]
            continue
        if n.get("status") in DEAD:
            continue
        have = {e["to"] for e in edges(n, "describes")}
        if facet_value(n, "file") != a["file"]:
            ops.append({"op": "edit", "node": sid, "set": {"file": {"type": "json", "value": a["file"]}}, "editorial": True})
        for t in sorted(want - have):
            ops.append({"op": "link", "node": sid, "edge": {"type": "describes", "to": t}})
            added.append(f"{sid} → {t}")
        for t in sorted(have - want):
            ops.append({"op": "unlink", "node": sid, "edge": f"describes:{t}"})
            removed.append(f"{sid} → {t}")
    if ops:
        apply_ops(store, ops, actor)
    macros = write_macros(store)
    return {"sections": sorted(anchors(current(store))), "edges_added": added, "edges_removed": removed, "macros": macros}


def macro_lines(st: State) -> list[tuple[str, str, str]]:
    """[(macro, value text, comment)] for every live binding with a macro."""
    out = []
    for n in sorted(st.nodes.values(), key=lambda x: x["id"]):
        ev = st.E[n["id"]]
        if ev.archived:
            continue
        for name, b in sorted((facet_value(n, "bindings") or {}).items()):
            if not isinstance(b, dict) or not b.get("macro"):
                continue
            v = ev.values.get(name)
            try:
                text = str(b.get("fmt") or "{:.3g}").format(v) if v is not None else "??"
            except (ValueError, IndexError, KeyError):
                text = str(v)
            if ev.level != "fresh":
                text = f"\\rdstale{{{text}}}"
            out.append((str(b["macro"]).lstrip("\\"), text, f"{n['id']} {name}; {ev.level}"))
    return out


def write_macros(store) -> int:
    st = current(store)
    lines = macro_lines(st)
    rel = str((st.cfg.get("paper") or {}).get("macros") or "paper/generated/rdvalues.tex")
    body = ["% generated by research-deck dag; do not edit", "\\providecommand{\\rdstale}[1]{#1}"]
    body += [f"\\newcommand{{\\{m}}}{{{t}}}   % {c}" for m, t, c in lines]
    target = Path(store.root) / rel
    text = "\n".join(body) + "\n"
    if not target.exists() or target.read_text(encoding="utf-8") != text:
        write_text_atomic(target, text)
    return len(lines)


def claims_for_doc(st: State, path: str) -> list[dict]:
    """Claim and section nodes tied to one paper file, with their freshness and actual values."""
    data = st.R.tree().read(path)
    text = data.decode("utf-8", errors="replace") if data is not None else ""
    lines = text.splitlines()
    owners = macro_owners(st)
    by_macro: dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        for m in MACRO_RE.findall(line):
            by_macro.setdefault(m, i)
    secs = {sid: a for sid, a in anchors(st).items() if a["file"] == path}
    picked: dict[str, int | None] = {}
    for sid, a in secs.items():
        if sid in st.nodes:
            picked[sid] = a["line"]
        for t in a["targets"]:
            tid = t.split(":", 1)[1].split("#")[0]
            if st.nodes.get(tid, {}).get("kind") == "claim":
                at = (a.get("lines") or {}).get(t)                   # the line that names it (a % rd:describes marker)
                picked[tid] = min(x for x in (picked.get(tid), at) if x is not None) if at or picked.get(tid) else None
    for macro, nid in owners.items():
        if macro in by_macro and st.nodes.get(nid, {}).get("kind") == "claim":
            picked[nid] = min(by_macro[macro], picked.get(nid) or by_macro[macro])
    out = []
    for nid, line in picked.items():
        n, ev = st.nodes[nid], st.E[nid]
        claim_text = str(facet_value(n, "text") or "")
        if line is None:
            line = next((i for i, x in enumerate(lines, 1) if claim_text and claim_text[:40] in x), None)
        out.append({"id": nid, "label": title_of(n), "text": claim_text, "line": line, "kind": n.get("kind"),
                    "evidence": sorted({e["to"][5:].split("#")[0] for e in edges(n, "evidence", "describes") if e["to"].startswith("node:")}),
                    "freshness": ev.level, "values": dict(ev.values)})
    return sorted(out, key=lambda x: (x["line"] or 10**9, x["id"]))
