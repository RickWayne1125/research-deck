"""The outline as a Markdown file in the project: notes/outline.md, or project.yaml `outline: {file: …}`. It is kept
in step with the outline on the map, both ways (docs/API.md § Outline file).

The file. Everything before the first "## " heading is the researcher's own and stays as it is.

    ## 2 Background and Motivation <!-- rd:sec sec.motivation -->     a section: its number, title and tag
    > The bottleneck is real                                           its role: ">" lines right under the heading
    - **2.1** Loading waits 58% of the time. <!-- rd:item claim.i1a2b3c4d -->     an item: number, text, tag
      - **2.1.1** Measured on two models. <!-- rd:item … -->           a sub-item, indented under its item
    > ‖ two measurements                                               names the parallel group that starts below it
    - **2.2** Layer-wise prediction hits 61%. <!-- rd:item … -->
    - **2.3** ‖ Adjacent tokens share experts. <!-- rd:item … -->      "‖": in parallel with the item before (one step)
    - **2.4** Which eviction policy? <!-- rd:item … -->
      - ↳ Direction 1 (chosen): lookahead <!-- rd:item … -->            a direction of a branch
        - **2.4.1** … <!-- rd:item … -->                               the direction's own items

Every other line under a section is an item too: one line, one item. "(derived)" at the end of an item marks one
that is argued and needs no task; "(proposed)" one an agent proposed. The numbers are Research Deck's.

Map → file (sync: after every change to the map, and when the outline or the documents are read): the file is
written again from the outline. If it changed since Research Deck last wrote or read it (another editor, an agent's
own file tools), those edits are imported first, as an agent's: they become one proposal, and the file shows the
outline as it is until the researcher accepts it.

File → map (saved: the file was saved through PUT …/file): the edits since the last sync become one batch of outline
changes. It is a three-way diff: from the text last synced to the saved text, applied to the map as it is now. It
covers:
  - text and "(derived)";
  - new items and sections (a line without a tag; the editor tags new lines before it saves, so a line keeps its item
    from one save to the next);
  - removed items, abandoned with what was under them except what moved elsewhere, and removed sections;
  - moves, indents, parallel groups and their notes, and the order of the sections;
  - revivals: the tag of an abandoned item or section that comes back revives it.
Branches are made, chosen and given up on the outline page; here only their text and items change. The researcher's
saves apply at once and keep the text as typed, with the numbers brought up to date. An agent's become a proposal.

.research/outline/file.json  {path, sha, text, digest, lang, error, warnings}: the text last synced (the base of the
next diff) and what the last save could not apply.
"""
from __future__ import annotations

import logging
import re
import textwrap
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..actors import is_human
from ..dag.model import DEAD, edges, facet_value, title_of
from ..events import hub
from ..projects import project_config, project_root, research_dir
from ..util import read_json, safe_join, sha256_text, slugify, write_json, write_text_atomic
from .ops import OutlineError, Plan, new_item_id

log = logging.getLogger("research_deck")

DEFAULT_FILE = "notes/outline.md"
IGNORE_LINE = "outline/file.json"
OUTSIDE = "agent:unknown"          # who edits the file outside Research Deck, as far as the map can tell
REASON = "removed from the outline file"

SEC_HEAD = re.compile(r"^ {0,3}##(?:[ \t]+(.*?))?[ \t]*$")
TAG = re.compile(r"[ \t]*<!--\s*rd:(sec|item)\s+([^\s>]+?)\s*-->")
SEC_ID = re.compile(r"^sec\.[A-Za-z0-9][A-Za-z0-9._-]*$")
ITEM_ID = re.compile(r"^claim\.[A-Za-z0-9][A-Za-z0-9._-]*$")
NUM_SEC = re.compile(r"^(?:§\s*)?\d+(?:\.\d+)*\.?\s+")
NUM_ITEM = re.compile(r"^\*\*\d+(?:\.\d+)*\*\*\s*")
BULLET = re.compile(r"^(?:[-*+]|\d+[.)])(?:[ \t]+|$)")     # a bare "-" being typed is no item yet
QUOTE = re.compile(r"^>[ \t]?(.*)$")
PAR = re.compile(r"^[‖∥][ \t]*")
DIRECTION = re.compile(r"^↳[ \t]*(?:(?:direction|方向)[ \t]*\d*[ \t]*)?(?:[(（][ \t]*(?:chosen|选定|已选)[ \t]*[)）][ \t]*)?[:：]?[ \t]*",
                       re.I)
TAG_END = re.compile(r"[ \t]*[(（][ \t]*(derived|推导|proposed|agent 提议|提议)[ \t]*[)）][ \t]*$", re.I)
DERIVED_WORDS = {"derived", "推导"}

WORDS = {
    "en": {"derived": " (derived)", "proposed": " (proposed)", "direction": "Direction {n}", "chosen": " (chosen)",
           "title": "Outline: {name}",
           "help": ("Research Deck keeps this file and the outline page in step: what you change here changes the "
                    "outline, and changes made on the outline page are written back here. One line is one item; indent "
                    "a line to put it under the one above. Keep the rd: tag at the end of each line: it ties the line "
                    "to its item (a new line gets one when it is saved). \"‖\" puts an item in parallel with the one "
                    "before it and \"> ‖ …\" names that group; \"↳\" starts a direction of a branch; \"(derived)\" "
                    "marks an item that is argued rather than measured. Tasks, evidence and branches are managed on the "
                    "outline page. Edits made outside Research Deck become a proposal.")},
    "zh": {"derived": "（推导）", "proposed": "（Agent 提议）", "direction": "方向 {n}", "chosen": "（选定）",
           "title": "提纲：{name}",
           "help": ("Research Deck 让这个文件和提纲页保持一致：这里的改动会改到提纲，提纲页上的改动也会写回这里。"
                    "一行是一个条目，缩进一行就放到上一行的条目下面。保留每行末尾的 rd: 标记，它把这一行和条目对应起来"
                    "（新写的行保存时会自动加上）。“‖” 表示和上一条并列，“> ‖ …” 写这组并列条目是什么；“↳” 开始一个分叉方向；"
                    "“（推导）” 表示这一条靠论证、不需要实验。任务、证据和分叉在提纲页上管理。在 Research Deck 之外改这个文件，"
                    "改动会变成待批准的提议。")},
}

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_TLS = threading.local()


def _lock(pid: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(pid, threading.RLock())


def _quiet() -> set[str]:
    """Projects whose outline file this thread is writing to the map: the sync its own change starts waits for it."""
    q = getattr(_TLS, "quiet", None)
    if q is None:
        q = _TLS.quiet = set()
    return q


# ---------------------------------------------------------------- the text

@dataclass
class Line:
    """An item line: its tag, text and flags, where it is, and what the file puts under it."""
    id: str | None
    text: str
    line: int
    indent: int
    derived: bool = False
    parallel: bool = False
    direction: bool = False
    note: str | None = None                    # names the parallel group this item starts
    children: list[Line] = field(default_factory=list)
    directions: list[Line] = field(default_factory=list)


@dataclass
class Sec:
    id: str | None
    title: str
    role: str
    line: int
    items: list[Line] = field(default_factory=list)


@dataclass
class Doc:
    preamble: str
    sections: list[Sec]


def _indent(raw: str) -> int:
    n = 0
    for c in raw:
        if c == " ":
            n += 1
        elif c == "\t":
            n += 4 - n % 4
        else:
            break
    return n


def _take(body: str, kind: str) -> tuple[str, str | None]:
    """The text without its rd: tags, and the id of the first tag of this kind."""
    found = None
    for m in TAG.finditer(body):
        if m.group(1) == kind and found is None:
            found = m.group(2)
    return TAG.sub("", body), found


def parse(text: str) -> Doc:
    pre: list[str] = []
    sections: list[Sec] = []
    sec: Sec | None = None
    stack: list[Line] = []
    notes: dict[int, str] = {}
    for no, raw in enumerate((text or "").replace("\r\n", "\n").split("\n"), 1):
        h = SEC_HEAD.match(raw)
        if h:
            body, sid = _take(h.group(1) or "", "sec")
            title = NUM_SEC.sub("", body.strip(), count=1).strip()
            if title or sid:
                sec = Sec(sid, title, "", no)
                sections.append(sec)
                stack, notes = [], {}
                continue
        if sec is None:
            pre.append(raw)
            continue
        if not raw.strip():
            continue
        ind, body = _indent(raw), raw.strip()
        q = QUOTE.match(body)
        if q:
            inner = q.group(1).strip()
            if PAR.match(inner):
                notes[ind] = PAR.sub("", inner, count=1).strip()
                continue
            if not sec.items:
                sec.role = f"{sec.role}\n{inner}" if sec.role else inner
                continue
            body = inner
        body, iid = _take(body, "item")
        body = BULLET.sub("", body.strip(), count=1)
        is_dir = body.startswith("↳")
        if is_dir:
            body = DIRECTION.sub("", body, count=1)
        body = NUM_ITEM.sub("", body, count=1)
        par = bool(PAR.match(body))
        body = PAR.sub("", body, count=1)
        derived = False
        while (m := TAG_END.search(body)) and m.start() > 0:
            derived = derived or m.group(1).lower() in DERIVED_WORDS
            body = body[:m.start()]
        body = body.strip()
        if not body and not iid:
            continue
        it = Line(iid, body, no, ind, derived, par)
        while stack and stack[-1].indent >= ind:
            stack.pop()
        parent = stack[-1] if stack else None
        if is_dir and parent is not None:
            it.direction = True
            parent.directions.append(it)
        else:
            siblings = parent.children if parent is not None else sec.items
            if not (it.parallel and siblings):
                it.note = notes.get(ind)
            notes = {k: v for k, v in notes.items() if k < ind}
            siblings.append(it)
        stack.append(it)
    return Doc("\n".join(pre), sections)


def walk(items: list[Line]):
    for it in items:
        yield it
        yield from walk(it.children)
        for d in it.directions:
            yield d
            yield from walk(d.children)


def steps_of(items: list[Line]) -> tuple[list[list[str]], dict[str, str]]:
    """A list of items as a chain: an item marked ‖ joins the step before it; a note names the step its item starts."""
    steps: list[list[str]] = []
    notes: dict[str, str] = {}
    for it in items:
        if it.parallel and steps:
            steps[-1].append(it.id)
        else:
            steps.append([it.id])
            if it.note:
                notes[str(len(steps) - 1)] = it.note
    return steps, notes


def _index(doc: Doc) -> dict[str, tuple[Line, str, str]]:
    """id -> (line, parent id, "chain" | "fork") for every tagged item of the file (the first line naming it)."""
    out: dict[str, tuple[Line, str, str]] = {}

    def go(items: list[Line], parent: str) -> None:
        for it in items:
            if it.id and it.id not in out:
                out[it.id] = (it, parent, "chain")
            go(it.children, it.id or "")
            for d in it.directions:
                if d.id and d.id not in out:
                    out[d.id] = (d, it.id or "", "fork")
                go(d.children, d.id or "")
    for s in doc.sections:
        go(s.items, s.id or "")
    return out


def _kids(doc: Doc) -> dict[str, list[Line]]:
    """parent id -> the items the file puts under it, in order (sections, items and directions)."""
    out: dict[str, list[Line]] = {}

    def go(parent: str, items: list[Line]) -> None:
        out.setdefault(parent, []).extend(items)
        for it in items:
            if it.id:
                go(it.id, it.children)
                for d in it.directions:
                    if d.id:
                        go(d.id, d.children)
    for s in doc.sections:
        if s.id:
            go(s.id, s.items)
    return out


def _same(a: str | None, b: str | None) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


def _bi(v: Any, lang: str) -> str:
    if isinstance(v, dict):
        return str(v.get(lang) or v.get("en") or v.get("zh") or "")
    return str(v or "")


def raw_text(n: dict) -> str:
    """An item's own text (the {{name}} bindings left as they are written)."""
    t = facet_value(n, "text")
    return t if isinstance(t, str) and t.strip() else title_of(n)


# ---------------------------------------------------------------- writing it

def _live(rec: dict) -> bool:
    return rec.get("status") not in DEAD and rec.get("state") != "abandoned"


def _tags(rec: dict, derived: bool, lang: str) -> str:
    w = WORDS[lang]
    return (w["derived"] if derived else "") + (w["proposed"] if rec.get("status") == "proposed" else "")


def _item_line(indent: str, rec: dict, text: str, derived: bool, parallel: bool, lang: str) -> str:
    return f"{indent}- **{rec['num']}** {'‖ ' if parallel else ''}{_one_line(text)}{_tags(rec, derived, lang)} <!-- rd:item {rec['id']} -->"


def _dir_line(indent: str, rec: dict, text: str, derived: bool, chosen: bool, lang: str) -> str:
    w = WORDS[lang]
    label = w["direction"].format(n=rec.get("direction") or "") + (w["chosen"] if chosen else "")
    return f"{indent}- ↳ {label}: {_one_line(text)}{_tags(rec, derived, lang)} <!-- rd:item {rec['id']} -->"


def _sec_line(sec: dict, title: str) -> str:
    return f"## {sec['num']} {_one_line(title) or sec['id']} <!-- rd:sec {sec['id']} -->"


def preamble_for(name: str, lang: str) -> str:
    w = WORDS[lang]
    help_text = textwrap.fill(w["help"], 112, break_long_words=False, break_on_hyphens=False) if lang == "en" else w["help"]
    return f"# {w['title'].format(name=name)}\n\n<!-- {help_text} -->\n"


def render(o: dict, nodes: dict, lang: str, preamble: str) -> str:
    """The outline (outline/model.py build) as the file, after `preamble`."""
    out = [preamble.rstrip("\n")]

    def text_of(rec: dict) -> str:
        n = nodes.get(rec["id"])
        return raw_text(n) if n else rec.get("text") or ""

    def steps(body: list[str], ss: list[dict], indent: str) -> None:
        for st in ss:
            live = [r for r in st.get("items") or [] if _live(r)]
            if not live:
                continue
            if st.get("note"):
                body.append(f"{indent}> ‖ {_one_line(st['note'])}")
            for k, r in enumerate(live):
                body.append(_item_line(indent, r, text_of(r), bool(r.get("derived")), k > 0, lang))
                steps(body, r.get("children") or [], indent + "  ")
                fork = r.get("fork") or {}
                for d in fork.get("directions") or []:
                    if _live(d):
                        body.append(_dir_line(indent + "  ", d, text_of(d), bool(d.get("derived")),
                                              fork.get("chosen") == d["id"], lang))
                        steps(body, d.get("children") or [], indent + "    ")

    for s in o.get("sections") or []:
        out += ["", _sec_line(s, _bi(s.get("title"), lang))]
        role = [ln.strip() for ln in (s.get("role") or "").splitlines() if ln.strip()]
        if role:
            out += [""] + [f"> {ln}" for ln in role]
        body: list[str] = []
        steps(body, s.get("items") or [], "")
        if body:
            out += [""] + body
    return "\n".join(out).strip("\n") + "\n"


def _numbers(o: dict) -> tuple[dict[str, str], dict[str, dict]]:
    """Section numbers by id, and every item record by id (its number, direction and fork)."""
    secs = {s["id"]: s["num"] for s in o.get("sections") or []}
    items: dict[str, dict] = {}

    def go(ss: list[dict], parent: dict | None) -> None:
        for st in ss:
            for r in st.get("items") or []:
                items[r["id"]] = {**r, "_parent": parent}
                go(r.get("children") or [], r)
                for d in (r.get("fork") or {}).get("directions") or []:
                    items[d["id"]] = {**d, "_parent": r}
                    go(d.get("children") or [], d)
    for s in o.get("sections") or []:
        go(s.get("items") or [], None)
    return secs, items


def renumber(text: str, doc: Doc, o: dict, lang: str) -> str:
    """The saved text with each tagged line's number (and a new line's tag) brought up to date; everything else as
    typed."""
    secs, items = _numbers(o)
    lines = (text or "").replace("\r\n", "\n").split("\n")
    for s in doc.sections:
        if s.id in secs:
            lines[s.line - 1] = _sec_line({"num": secs[s.id], "id": s.id}, s.title)
        for it in walk(s.items):
            rec = items.get(it.id or "")
            if rec is None or not _live(rec):
                continue
            raw = lines[it.line - 1]
            indent = raw[:len(raw) - len(raw.lstrip(" \t"))]
            if it.direction and rec.get("direction"):
                fork = (rec.get("_parent") or {}).get("fork") or {}
                lines[it.line - 1] = _dir_line(indent, rec, it.text, it.derived, fork.get("chosen") == it.id, lang)
            elif not it.direction:
                lines[it.line - 1] = _item_line(indent, rec, it.text, it.derived, it.parallel, lang)
    return "\n".join(lines)


# ---------------------------------------------------------------- the edits, onto the map

def _new_section_id(title: str, taken: set[str]) -> str:
    base = "sec." + (slugify(title, "")[:40].strip("-") or f"s{uuid.uuid4().hex[:6]}")
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    return sid


def tag_new_lines(doc: Doc, nodes: dict) -> bool:
    """Give each line without a usable tag (or repeating one) an id. True when any line got one."""
    seen: set[str] = set()
    changed = False
    for s in doc.sections:
        if not s.id or s.id in seen or not SEC_ID.match(s.id):
            s.id = _new_section_id(s.title, seen | set(nodes))
            changed = True
        seen.add(s.id)
        for it in walk(s.items):
            if not it.id or it.id in seen or not ITEM_ID.match(it.id):
                nid = new_item_id()
                while nid in nodes or nid in seen:
                    nid = new_item_id()
                it.id = nid
                changed = True
            seen.add(it.id)
    return changed


def _phase_near(plan: Plan, doc: Doc, k: int) -> str:
    for j in [*range(k - 1, -1, -1), *range(k + 1, len(doc.sections))]:
        n = plan.created.get(doc.sections[j].id or "") or plan.nodes.get(doc.sections[j].id or "")
        ph = facet_value(n, "phase") if n else None
        if ph and ph != "summary":
            return str(ph)
    return "insight"


class Apply:
    """The researcher's edits to the file (base → new), as changes to a Plan of the map as it is now."""

    def __init__(self, plan: Plan, base: Doc, new: Doc, lang: str):
        self.plan, self.base, self.new, self.lang = plan, base, new, lang
        self.warnings: list[str] = []
        self.parents = plan.parents()                   # on the map, before any change
        self.changed: set[str] = set()                  # parents whose chain the file sets

    def node(self, nid: str | None) -> dict | None:
        return (self.plan.created.get(nid) or self.plan.nodes.get(nid)) if nid else None

    def dead(self, nid: str) -> bool:
        n = self.node(nid)
        return n is None or self.plan.is_dead(nid)

    def locked(self, nid: str) -> bool:
        n = self.node(nid)
        return bool(n) and n.get("status") == "locked"

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def run(self) -> list[str]:
        self.prepare()
        self.sections()
        self.items()
        self.place()
        self.remove()
        self.check_tree()
        return self.warnings

    # ------------------------------------------------------------ what the lines mean on this map
    def prepare(self) -> None:
        """Lines whose tag the map cannot take are left out; an item keeps its kind (a direction stays a direction);
        a new "↳" line is a direction only under an item that branches."""
        for s in self.new.sections:
            self._prepare(s.items)

    def _prepare(self, items: list[Line]) -> None:
        keep: list[Line] = []
        for it in items:
            n = self.node(it.id)
            if n is None and not it.text:
                continue
            if n is not None and n.get("kind") != "claim":
                self.warn(f"{it.id} is not an outline item: the line was left out")
                continue
            if n is not None and n.get("status") in DEAD and not self._can_revive(n):
                self.warn(f"{it.id} rests on something abandoned and cannot come back: the line was left out")
                continue
            if self.parents.get(it.id or "", ("", ""))[1] == "fork":
                it.direction = True            # a direction written as an item: it stays a direction of its fork
            keep.append(it)
            moved: list[Line] = []
            dirs: list[Line] = []
            for d in it.directions:
                dn = self.node(d.id)
                if dn is None and not d.text:
                    continue
                is_dir = self.parents.get(d.id or "", ("", ""))[1] == "fork" if dn is not None else bool(self.plan.fork(it.id)) if self.node(it.id) else False
                if is_dir:
                    dirs.append(d)
                else:
                    d.direction = False
                    moved.append(d)
                    if dn is None:
                        self.warn(f"“↳ {d.text[:40]}”: a direction goes under an item that branches; it became a sub-item")
            it.directions = dirs
            it.children.extend(moved)
            self._prepare(it.children)
            for d in it.directions:
                self._prepare(d.children)
        items[:] = keep

    def _can_revive(self, n: dict) -> bool:
        for e in edges(n):
            to = str(e.get("to") or "")
            t = self.plan.nodes.get(to.split(":", 1)[1].split("#")[0]) if to.startswith("node:") else None
            if t is not None and t.get("status") in DEAD:
                return False
        return True

    # ------------------------------------------------------------ sections
    def sections(self) -> None:
        plan, base = self.plan, {s.id: s for s in self.base.sections}
        for k, s in enumerate(self.new.sections):
            n = self.node(s.id)
            prev = self.new.sections[k - 1].id if k else None
            if n is None or (n.get("status") not in DEAD and facet_value(n, "order") is None):
                # new, or a section paper sync made from a % rd:sec anchor (the outline adopts it)
                plan.op_add_section({"key": s.id[4:], "title": s.title or s.id[4:], "role": s.role,
                                     "phase": _phase_near(plan, self.new, k), "after": prev})
                continue
            if n.get("status") in DEAD:
                plan.revive(s.id, "back in the outline file")
            ref = base.get(s.id)
            if not _same(s.title, ref.title if ref else _bi(n.get("title"), self.lang)) and s.title:
                plan.op_edit_section({"section": s.id, "title": s.title})
            if not _same(s.role, ref.role if ref else facet_value(n, "role") or ""):
                plan.op_edit_section({"section": s.id, "role": s.role})
        in_new = [s.id for s in self.new.sections]
        in_base = [s.id for s in self.base.sections]
        self.gone_secs = [sid for sid in in_base if sid not in in_new and self.node(sid) is not None
                          and not self.dead(sid) and facet_value(self.node(sid), "order") is not None]
        if [i for i in in_new if i in base] != [i for i in in_base if i in in_new] or any(i not in base for i in in_new):
            on_map = [s["id"] for s in plan.sections()]
            final = list(in_new)
            for i, sid in enumerate(on_map):
                if sid in final or sid in self.gone_secs:
                    continue
                before = next((x for x in reversed(on_map[:i]) if x in final), None)
                final.insert(final.index(before) + 1 if before else 0, sid)
            plan.renumber([sid for sid in final if self.node(sid) is not None])

    # ------------------------------------------------------------ items: new, revived, reworded
    def items(self) -> None:
        plan = self.plan
        b_idx = _index(self.base)
        for iid, (ln, parent, how) in _index(self.new).items():
            n = self.node(iid)
            if n is None:
                if how == "fork":
                    f = plan.fork(parent)
                    if f is not None:
                        f["directions"].append(plan.make_item(ln.text, iid, ln.derived))
                else:
                    plan.make_item(ln.text, iid, ln.derived)
                continue
            if n.get("status") in DEAD:
                plan.revive(iid, "back in the outline file")
            ref = b_idx.get(iid)
            text = ref[0].text if ref else raw_text(n)
            derived = ref[0].derived if ref else bool(facet_value(n, "derived"))
            edit: dict[str, Any] = {}
            if ln.text and not _same(ln.text, text):
                edit["text"] = ln.text
            if ln.derived != derived:
                edit["derived"] = ln.derived
            if edit:
                if self.locked(iid):
                    self.warn(f"{iid} is locked: unlock it on the map to change it")
                else:
                    plan.op_edit_item({"item": iid, **edit})

    # ------------------------------------------------------------ items: where they sit
    def place(self) -> None:
        plan = self.plan
        n_kids, b_kids = _kids(self.new), _kids(self.base)
        n_idx, b_idx = _index(self.new), _index(self.base)
        present = set(n_idx) | {s.id for s in self.new.sections}
        removed = {i for i, (_, _, how) in b_idx.items() if i not in present and how == "chain"
                   and i in self.parents and not self.dead(i)}
        for i, (ln, _, how) in b_idx.items():
            if how == "fork" and i not in present:
                self.warn(f"“↳ {ln.text[:40]}”: directions are given up on the outline page; it stays")
                for x in walk(ln.children):
                    removed.discard(x.id)
        for i in sorted(removed):
            if self.locked(i):
                self.warn(f"{i} is locked: unlock it on the map to remove it")
                removed.discard(i)
        self.present, self.removed = present, removed
        new_parent = {i: p for i, (_, p, how) in n_idx.items() if how == "chain"}
        pinned = {i for i, (ln, _, _) in n_idx.items() if ln.direction}     # directions keep their place
        for p in sorted(set(n_kids) | {p for p in b_kids if p in present}):
            if self.node(p) is None or (p in removed):
                continue
            listed = [it for it in n_kids.get(p, []) if it.id and it.id not in pinned]
            new_steps, new_notes = steps_of(listed)
            fresh = p not in b_kids or self.node(p) is plan.created.get(p) or p in plan.revived
            if not fresh:
                old = [it for it in b_kids[p] if it.id and it.id not in pinned]
                if steps_of(old) == (new_steps, new_notes) and not any(it.id not in b_idx for it in listed):
                    continue
            chain, notes = self._merge(p, new_steps, new_notes)
            if self.locked(p) and chain != plan.chain(p):
                self.warn(f"{p} is locked: its items stay where they are")
                continue
            plan.chains[p], plan.notes[p] = chain, notes
            self.changed.add(p)
        # an item the file puts somewhere else leaves a chain the file did not set
        for i, p in new_parent.items():
            old = self.parents.get(i)
            if old and old[1] == "chain" and old[0] != p and old[0] not in self.changed:
                self._drop(old[0], i)

    def _merge(self, p: str, steps: list[list[str]], notes: dict[str, str]) -> tuple[list[list[str]], dict[str, str]]:
        """The file's chain for p, with what the file does not show kept where it was: abandoned items, and items
        added on the map since the last sync."""
        out = [list(s) for s in steps]
        keyed = {int(k): v for k, v in notes.items()}
        placed = {i for s in out for i in s}
        flat = [i for st in self.plan.chain(p) for i in st]
        for k, i in enumerate(flat):
            if i in placed or i in self.present or i in self.removed:
                continue
            before = next((x for x in reversed(flat[:k]) if x in placed), None)
            at = next((j + 1 for j, s in enumerate(out) if before in s), 0) if before else 0
            out.insert(at, [i])
            keyed = {(j + 1 if j >= at else j): v for j, v in keyed.items()}
            placed.add(i)
        return out, {str(k): v for k, v in sorted(keyed.items())}

    def _drop(self, parent: str, item: str) -> None:
        chain = self.plan.chain(parent)
        for si, step in enumerate(chain):
            if item in step:
                step.remove(item)
                if not step:
                    del chain[si]
                    self.plan.shift_notes(parent, si, -1)
                return

    # ------------------------------------------------------------ removed items and sections
    def remove(self) -> None:
        plan = self.plan
        for i in sorted(self.removed):
            old = self.parents.get(i)
            if old and old[0] not in self.changed:
                self._drop(old[0], i)
            self._kill_under(i)
        for sid in self.gone_secs:
            if self.locked(sid):
                self.warn(f"{sid} is locked: unlock it on the map to remove it")
                continue
            for step in plan.chain(sid):
                for i in step:
                    if i not in self.present:
                        self._kill_under(i)
            plan.chains[sid] = [[i for i in st if i not in self.present] for st in plan.chain(sid)]
            plan.chains[sid] = [st for st in plan.chains[sid] if st]
            plan.kill(sid, "out_of_scope", REASON)

    def _kill_under(self, root: str) -> None:
        """Abandon root and what is under it, except what the file keeps elsewhere; the chains of what is abandoned
        let go of what moved, so every live item has one place."""
        todo = [root]
        while todo:
            x = todo.pop()
            if x in self.present and x != root:
                continue
            n = self.node(x)
            if n is None or n.get("kind") != "claim":
                continue
            kids = [i for st in self.plan.chain(x) for i in st]
            dirs = list((self.plan.fork(x) or {}).get("directions") or [])
            if any(i in self.present for i in kids):
                chain = [[i for i in st if i not in self.present] for st in self.plan.chain(x)]
                self.plan.chains[x] = [st for st in chain if st]
            if self.locked(x):
                self.warn(f"{x} is locked: it stays")
                continue
            self.plan.kill(x, "out_of_scope", REASON)
            todo.extend(kids + dirs)

    def check_tree(self) -> None:
        """Every live item has one place, and nothing is under itself."""
        seen: set[str] = set()

        def go(nid: str, path: tuple[str, ...]) -> None:
            if nid in path:
                raise OutlineError(409, f"{nid} would end up under itself")
            if nid in seen:
                return
            seen.add(nid)
            if self.node(nid) is None:
                return
            for st in self.plan.chain(nid):
                for c in st:
                    go(c, path + (nid,))
            for d in (self.plan.fork(nid) or {}).get("directions") or []:
                go(d, path + (nid,))
        for s in self.plan.sections():
            go(s["id"], ())


# ---------------------------------------------------------------- the state and the file

def _lang(pid: str) -> str:
    return "zh" if str(project_config(pid).get("language") or "").lower().startswith("zh") else "en"


def _state_path(pid: str) -> Path:
    return research_dir(pid) / "outline" / "file.json"


def _load(pid: str) -> dict:
    s = read_json(_state_path(pid), None)
    return s if isinstance(s, dict) else {}


def _save(pid: str, state: dict) -> None:
    p = _state_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json(p, state)
    ignore = research_dir(pid) / ".gitignore"          # the state is this machine's: keep it out of the project's git
    try:
        text = ignore.read_text(encoding="utf-8") if ignore.is_file() else None
        if text is not None and IGNORE_LINE not in text.splitlines():
            write_text_atomic(ignore, text + ("" if text.endswith("\n") or not text else "\n") + IGNORE_LINE + "\n")
    except OSError:
        pass


def _configured(pid: str) -> str | None:
    v = (project_config(pid).get("outline") or {})
    f = v.get("file") if isinstance(v, dict) else None
    return str(f).strip().lstrip("/") if isinstance(f, str) and f.strip() else None


def _ours(text: str) -> bool:
    return bool(re.search(r"<!--\s*rd:(?:sec|item)\s", text or ""))


def file_path(pid: str, state: dict | None = None) -> str:
    """Where the outline file is: project.yaml outline.file, else where it was put, else notes/outline.md (or the
    next free name, when a file of the researcher's own already has that name)."""
    if (p := _configured(pid)):
        return p
    state = _load(pid) if state is None else state
    if state.get("path"):
        return str(state["path"])
    root = project_root(pid)
    stem, n = DEFAULT_FILE[:-3], 2
    rel = DEFAULT_FILE
    while (root / rel).is_file() and not _ours((root / rel).read_text(encoding="utf-8", errors="replace")):
        rel, n = f"{stem}-{n}.md", n + 1
    return rel


def is_outline_file(pid: str, rel: str) -> bool:
    try:
        return rel.strip("/") == file_path(pid)
    except HTTPException:
        return False


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None


def _map(pid: str):
    from ..dag.evaluate import current
    from ..dag.service import store_for
    store = store_for(pid)
    if not (store.root / store.state / "dag").exists():
        return store, None
    return store, current(store)


def _commit(pid: str, plan: Plan, actor: str, what: str) -> dict:
    from . import service
    q = _quiet()
    q.add(pid)
    try:
        return service._commit(pid, plan, actor, title=f"Outline file: {what}", kinds=None if is_human(actor) else {"file"})
    finally:
        q.discard(pid)


def _import(pid: str, st, base_text: str, new: Doc, actor: str, lang: str) -> list[str]:
    """Edits to the file (base_text → new, its lines tagged) as changes to the map, as `actor`: applied for the
    researcher, one proposal for anyone else."""
    plan = Plan(st.nodes, is_human(actor), lang)
    warnings = Apply(plan, parse(base_text), new, lang).run()
    ops = plan.dag_ops()
    if ops:
        _commit(pid, plan, actor, f"{len(ops)} change{'s' if len(ops) != 1 else ''}")
    return warnings


def _write(pid: str, rel: str, target: Path, disk: str | None, st, lang: str, warnings: list[str]) -> dict:
    """The file written again from the map (its preamble kept), and the state that says so."""
    from . import model
    pre = parse(disk).preamble if disk is not None else ""
    preamble = pre if pre.strip() else preamble_for(str(project_config(pid).get("name") or pid), lang)
    text = render(model.build(pid, lang), st.nodes, lang, preamble)
    if text != disk:
        write_text_atomic(target, text)
        hub.publish(pid, "file", {"path": rel, "sha": sha256_text(text)})
    state = {"path": rel, "sha": sha256_text(text), "text": text, "digest": st.digest, "lang": lang,
             "error": None, "warnings": warnings}
    _save(pid, state)
    return state


def sync(pid: str) -> dict | None:
    """Map → file: write the file from the outline when either changed (importing edits made outside first). The
    state, or None when the project has no outline (then there is no file)."""
    if pid in _quiet():
        return None
    with _lock(pid):
        try:
            from . import model
            store, st = _map(pid)
            if st is None or not model.outline_sections(st):
                return None
            state = _load(pid)
            rel = file_path(pid, state)
            target = safe_join(project_root(pid), rel)
            disk = _read(target)
            lang = _lang(pid)
            same = disk is not None and sha256_text(disk) == state.get("sha")
            if same and state.get("error"):
                return state                    # the researcher's last save could not be applied: keep their text
            warnings = state.get("warnings") or []
            if disk is not None and not same and (state.get("text") is not None or _ours(disk)):
                base = state.get("text")
                if base is None:
                    base = render(model.build(pid, lang), st.nodes, lang, parse(disk).preamble)
                new = parse(disk)
                tag_new_lines(new, st.nodes)
                store.ensure()
                try:
                    warnings = _import(pid, st, base, new, OUTSIDE, lang)
                except Exception as e:  # noqa: BLE001 — what cannot be imported is reported, not lost
                    warnings = [f"edits made outside Research Deck could not be read: {_why(e)}"]
                    log.warning("outline file of %s: %s", pid, _why(e))
                store, st = _map(pid)
            elif same and state.get("digest") == st.digest and state.get("lang") == lang and state.get("path") == rel:
                return state
            return _write(pid, rel, target, disk, st, lang, warnings)
        except HTTPException:
            return None
        except Exception:  # noqa: BLE001 — the file never breaks the outline or the map
            log.exception("outline file sync failed for %s", pid)
            return None


def _why(e: Exception) -> str:
    if isinstance(e, HTTPException):
        d = e.detail
        return str(d.get("message") or d) if isinstance(d, dict) else str(d)
    if isinstance(e, OutlineError):
        return e.message
    return str(e)


def saved(pid: str, rel: str, content: str, actor: str) -> dict | None:
    """File → map, after PUT …/file wrote the outline file: {"content": the file as it is now, "outline": {applied,
    proposal?, warnings, error?}}. None for any other file."""
    if pid in _quiet() or not is_outline_file(pid, rel):
        return None
    from . import model
    with _lock(pid):
        store, st = _map(pid)
        if st is None:
            return None
        store.ensure()
        state = _load(pid)
        lang = _lang(pid)
        target = safe_join(project_root(pid), rel)
        base = state.get("text")
        if base is None:
            base = render(model.build(pid, lang), st.nodes, lang, parse(content).preamble) if model.outline_sections(st) else ""
        new = parse(content)
        tag_new_lines(new, st.nodes)
        try:
            warnings = _import(pid, st, base, new, actor, lang)
        except Exception as e:  # noqa: BLE001 — what could not be applied is reported with the save
            error = _why(e)
            if not isinstance(e, (HTTPException, OutlineError)):
                log.exception("outline file of %s", pid)
            # the text stays as saved (it is on disk) and the base as it was, so the next save tries again
            _save(pid, {**state, "path": rel, "sha": sha256_text(content), "text": base, "error": error, "warnings": []})
            return {"content": content, "outline": {"applied": False, "error": error, "warnings": []}}
        store, st = _map(pid)
        if not is_human(actor):
            # an agent's edits wait in a proposal; the file shows the outline as it is
            state = _write(pid, rel, target, content, st, lang, warnings)
            return {"content": state["text"], "outline": {"applied": False, "proposal": True, "warnings": warnings}}
        text = renumber(content, new, model.build(pid, lang), lang)
        if text != content:
            write_text_atomic(target, text)
        _save(pid, {"path": rel, "sha": sha256_text(text), "text": text, "digest": st.digest, "lang": lang,
                    "error": None, "warnings": warnings})
        return {"content": text, "outline": {"applied": True, "warnings": warnings}}


def write_in(root: Path, name: str, lang: str = "en", state: str = ".research") -> str | None:
    """The outline file of a project folder that is not registered yet (the demo while it is built), as the first
    sync would write it; its path, or None without an outline."""
    from ..dag.evaluate import current
    from ..dag.store import DagStore
    from . import model
    st = current(DagStore(Path(root).resolve(), state=state))
    if not model.outline_sections(st):
        return None
    o = model.Builder("", st, 0, "free", {}, lang, tasks=[]).build({}, None)
    write_text_atomic(Path(root) / DEFAULT_FILE, render(o, st.nodes, lang, preamble_for(name, lang)))
    return DEFAULT_FILE


def info(pid: str) -> dict | None:
    """What the page shows about the file: where it is, and what the last save could not apply."""
    state = _load(pid)
    if not state.get("path"):
        return None
    return {"path": state["path"], "error": state.get("error"), "warnings": state.get("warnings") or []}
