"""The survey pipeline, one worker thread per survey, and its state.

Steps (each pending → running → done | error | skipped):
  frame     one tool-less agent request: a title, a one-line summary, search queries and the problem's fields
  search    every chosen source in its own thread, each query in turn; the results merged and ranked (sources.merge)
  select    one tool-less agent request over the best MAX_CANDIDATES abstracts: which papers to keep, each one's role,
            takeaway and how the idea differs, and the survey text
  download  the open-access PDF of each kept paper into <papers_dir>/<bibkey>.pdf (fetch.fetch_pdf); the rest keep
            their link and BibTeX only
  draft     a proposed problem node (unless the map has a live one) and a proposed reference node per kept paper,
            submitted as the agent. Nothing is confirmed, and no experiment node is created: the survey runs nothing
  write     <papers_dir>/references.bib (new keys appended), <papers_dir>/index.md and notes/survey.md (an existing
            file is never overwritten; a numbered name is used instead), a message in the project conversation and a
            note both backends read on their next turn

State: .research/survey/<id>.json; the newest file is the project's survey. Every change is published on topic
"survey". cancel() stops the agent request that is running (or the download after the current file) and skips the
rest.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .. import projects
from ..agents import catalog, runner, sessions, transcript
from ..agents.api import RunBody, spec_for
from ..agents.context import pending_path
from ..events import hub
from ..util import now_iso, read_json, safe_join, slugify, write_json, write_text_atomic
from . import bib, fetch, prompts, sources

log = logging.getLogger("research_deck.survey")

STEPS = ("frame", "search", "select", "download", "draft", "write")
PER_QUERY = 12                      # results asked of each source for each query
MAX_CANDIDATES = 40                 # abstracts the agent reads
TIMEOUT_S = {"frame": 300, "select": 900}
EFFORT = {"frame": "medium", "select": "high"}
ID_RE = re.compile(r"^sv-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")

# survey id -> {"pid", "cancel", "run_id", "stop"}: the surveys running in this process (stop: an Event that ends its
# waits and downloads early, fetch.bind_stop)
_ACTIVE: dict[str, dict] = {}
_LOCK = threading.Lock()
_FILE_LOCK = threading.Lock()       # the job's writes and the interrupted-check's read-check-write never interleave


class Stop(Exception):
    """The survey ends here: cancelled, or a step that the rest depends on failed."""


# ---------------------------------------------------------------- state

def _dir(pid: str) -> Path:
    return projects.research_dir(pid) / "survey"


def _path(pid: str, sid: str) -> Path:
    if not ID_RE.match(sid or ""):
        raise HTTPException(404, f"no such survey: {sid}")
    return _dir(pid) / f"{sid}.json"


def _recover(pid: str, s: dict) -> dict:
    """A survey that says it is running but is not running in this process was cut off by a restart. Checked again
    under the file lock: a job saves its final state before it leaves _ACTIVE, so a finished survey is never taken
    for an interrupted one."""
    if s.get("status") != "running" or s["id"] in _ACTIVE:
        return s
    with _FILE_LOCK:
        s = read_json(_path(pid, s["id"]), None) or s
        if s.get("status") == "running" and s["id"] not in _ACTIVE:
            s["status"], s["error"], s["finished_at"] = "error", "interrupted: the server stopped during the survey", now_iso()
            for k, v in s["steps"].items():
                if v in ("pending", "running"):
                    s["steps"][k] = "skipped"
            write_json(_path(pid, s["id"]), s)
    return s


def get(pid: str, sid: str) -> dict:
    s = read_json(_path(pid, sid), None)
    if not s:
        raise HTTPException(404, f"no such survey: {sid}")
    return _recover(pid, s)


def latest(pid: str) -> dict | None:
    d = _dir(pid)
    names = sorted(p.stem for p in d.glob("sv-*.json") if ID_RE.match(p.stem)) if d.is_dir() else []
    return get(pid, names[-1]) if names else None


def running(pid: str) -> str | None:
    with _LOCK:
        return next((sid for sid, a in _ACTIVE.items() if a["pid"] == pid and not a.get("done")), None)


# ---------------------------------------------------------------- start / cancel

def start(pid: str, idea: str, *, idea_file: str | None = None, unread: str | None = None, count: int | None = None,
          download_pdfs: bool | None = None, source_list: list[str] | None = None, actor: str | None = None) -> dict:
    """Start a survey of `idea` (the idea's text; idea_file is where it is kept, unread names an attachment whose
    text could not be read). Defaults come from Settings → New projects."""
    from ..start import settings as new_settings
    if not (idea or "").strip():
        raise HTTPException(400, "the idea is empty: write it in notes/idea.md or pass it")
    cfg = new_settings.new_projects()["survey"]
    chosen = [s for s in (source_list if source_list is not None else cfg["sources"]) if s in sources.SEARCH]
    if not chosen:
        raise HTTPException(400, "choose at least one source")
    count = int(count or cfg["count"])
    if not 1 <= count <= 60:
        raise HTTPException(400, "count must be between 1 and 60")
    papers_dir = cfg["papers_dir"]
    safe_join(projects.project_root(pid), papers_dir)            # refuses a folder outside the project
    with _LOCK:
        if any(a["pid"] == pid and not a.get("done") for a in _ACTIVE.values()):
            raise HTTPException(409, "a survey is already running in this project")
        # sortable ids: the second, then a sequence number within it (latest() takes the last name)
        _dir(pid).mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        sid = f"sv-{stamp}-{len(list(_dir(pid).glob(f'sv-{stamp}-*.json'))) + 1:04x}"
        _ACTIVE[sid] = {"pid": pid, "cancel": False, "run_id": None, "stop": threading.Event()}
    s = {"id": sid, "status": "running", "step": "frame", "steps": dict.fromkeys(STEPS, "pending"),
         "created_at": now_iso(), "finished_at": None, "by": actor, "error": None, "warnings": [],
         "idea_file": idea_file, "lang": prompts.language(idea),
         "options": {"sources": chosen, "count": count, "download_pdfs": cfg["download_pdfs"] if download_pdfs is None
                     else bool(download_pdfs), "papers_dir": papers_dir},
         "title": None, "summary": None, "queries": [], "search": None, "candidates": 0, "papers": [], "nodes": [],
         "files": {}, "agent": None}
    job = Job(pid, s)
    job.save()
    threading.Thread(target=job.run, args=(idea, unread), daemon=True, name=f"survey-{sid}").start()
    return s


def cancel(pid: str) -> bool:
    with _LOCK:
        sid = next((k for k, a in _ACTIVE.items() if a["pid"] == pid and not a.get("done")), None)
        if not sid:
            return False
        _ACTIVE[sid]["cancel"] = True
        _ACTIVE[sid]["stop"].set()
        run_id = _ACTIVE[sid]["run_id"]
    if run_id:
        runner.cancel(run_id)
    return True


# ---------------------------------------------------------------- the pipeline

class Job:
    def __init__(self, pid: str, state: dict):
        self.pid, self.s = pid, state
        self.root = projects.project_root(pid)
        self.name = projects.project_config(pid).get("name") or self.root.name

    @property
    def active(self) -> dict:
        return _ACTIVE.get(self.s["id"]) or {}

    def save(self) -> None:
        with _FILE_LOCK:
            write_json(_path(self.pid, self.s["id"]), self.s)
        hub.publish(self.pid, "survey", self.s)

    def check(self) -> None:
        if self.active.get("cancel"):
            raise Stop("cancelled")

    def step(self, name: str, fn: Callable[[], Any]) -> Any:
        self.check()
        self.s["step"], self.s["steps"][name] = name, "running"
        self.save()
        try:
            out = fn()
        except Stop:
            self.s["steps"][name] = "skipped" if self.active.get("cancel") else "error"
            raise
        except Exception as e:  # noqa: BLE001 — every failure ends in a recorded state
            log.exception("survey %s: step %s failed", self.s["id"], name)
            self.s["steps"][name] = "error"
            raise Stop(f"{name}: {_short(e)}") from e
        self.s["steps"][name] = "done"
        self.save()
        return out

    def warn(self, text: str) -> None:
        self.s["warnings"].append(text)

    def run(self, idea: str, unread: str | None) -> None:
        fetch.bind_stop(self.active.get("stop"))
        try:
            framed = self.step("frame", lambda: self.frame(idea, unread))
            found = self.step("search", lambda: self.search(framed["queries"]))
            survey_md = self.step("select", lambda: self.select(idea, framed["problem"], found))
            if self.s["options"]["download_pdfs"]:
                self.step("download", self.download)
            else:
                self.s["steps"]["download"] = "skipped"
            self.step("draft", lambda: self.draft(framed))
            self.step("write", lambda: self.write(framed, survey_md))
            self.s["status"] = "done"
        except Stop as e:
            cancelled = bool(self.active.get("cancel"))
            self.s["status"] = "cancelled" if cancelled else "error"
            self.s["error"] = None if cancelled else str(e)
        except Exception as e:  # noqa: BLE001
            log.exception("survey %s failed", self.s["id"])
            self.s["status"], self.s["error"] = "error", _short(e)
        finally:
            for k, v in self.s["steps"].items():
                if v in ("pending", "running"):
                    self.s["steps"][k] = "skipped"
            self.s["finished_at"] = now_iso()
            self.active["done"] = True        # a new survey may start from here on
            self.save()                       # the final state first, then leave _ACTIVE (see _recover)
            with _LOCK:
                _ACTIVE.pop(self.s["id"], None)

    # ------------------------------------------------------------ agent requests

    def ask(self, step: str, prompt: str) -> str:
        b = sessions.get_binding(self.pid)
        body = RunBody(panel="project", prompt=prompt, purpose=f"survey-{step}", ephemeral=True,
                       effort=catalog.clamp_effort(b["provider"], b["model"], EFFORT[step]))
        spec = spec_for(self.pid, body, system=prompts.SYSTEM, tools=False)
        spec.timeout_s = TIMEOUT_S[step]
        run = runner.start(spec)
        self.active["run_id"] = run.id
        self.s["agent"] = {"provider": spec.provider, "model": spec.model, "effort": spec.effort}
        hung = not run.wait(spec.timeout_s + 30)
        if hung:                              # the runner's own timeout should have ended it; make sure
            runner.cancel(run.id)
            run.wait(10)
        self.active["run_id"] = None
        self.check()
        if run.status != "done":
            raise Stop(f"{step}: " + ((f"timed out after {spec.timeout_s}s" if hung else run.error) or "the agent did not answer"))
        return run.text

    def frame(self, idea: str, unread: str | None) -> dict:
        framed = prompts.parse_frame(self.ask("frame", prompts.frame(self.name, idea, unread)))
        if not framed:
            raise Stop("frame: the agent's answer had no search queries")
        self.s.update(title=framed["title"] or self.name, summary=framed["summary"], queries=framed["queries"])
        if framed["summary"] and not projects.project_config(self.pid).get("summary"):
            projects.patch_config(self.pid, {"summary": framed["summary"]})     # the line under the project's name
        return framed

    def search(self, queries: list[str]) -> list[dict]:
        chosen = self.s["options"]["sources"]
        stats = {src: {"found": 0, "failed": 0, "error": None} for src in chosen}
        results: list[tuple[int, int, int, str, dict]] = []
        lock = threading.Lock()

        def one(si: int, src: str) -> None:
            fetch.bind_stop(self.active.get("stop"))
            for qi, q in enumerate(queries):
                if self.active.get("cancel"):
                    return
                try:
                    found = sources.SEARCH[src](q, PER_QUERY)
                except Exception as e:  # noqa: BLE001 — network, HTTP status or parse error: count it, go on
                    with lock:
                        stats[src]["failed"] += 1
                        stats[src]["error"] = fetch.describe(e)
                    continue
                with lock:
                    results.extend((si, qi, rank, src, p) for rank, p in enumerate(found))
                    stats[src]["found"] += len(found)

        threads = [threading.Thread(target=one, args=(i, src), daemon=True) for i, src in enumerate(chosen)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.check()
        results.sort(key=lambda r: r[:3])     # the same answers merge the same way, whichever thread was first
        merged = sources.merge([(src, rank, p) for _, _, rank, src, p in results])
        self.s["search"] = {"sources": stats, "found": len(merged)}
        if not merged:
            errors = "; ".join(f"{sources.LABELS.get(k, k)}: {v['error']}" for k, v in stats.items() if v["error"])
            raise Stop("search: no papers found" + (f" ({errors})" if errors else ""))
        return merged                         # a source that failed shows in search.sources (the UI says so)

    def select(self, idea: str, problem: dict, merged: list[dict]) -> str:
        cands = merged[:MAX_CANDIDATES]
        self.s["candidates"] = len(cands)
        count = self.s["options"]["count"]
        answer = self.ask("select", prompts.select(self.name, idea, problem, cands, count))
        picked, survey_md = prompts.parse_select(answer, len(cands))
        if not picked:
            self.warn("the agent picked no papers; the best-ranked ones are kept, unclassified")
            picked = [{"i": i + 1, "role": "related", "takeaway": "", "delta": "", "closes_gap": False}
                      for i in range(min(count, len(cands)))]
        known = self.known_refs()
        taken = set(known.values()) | self.bib_keys()
        papers = []
        for item in picked[:count]:
            c = cands[item["i"] - 1]
            existing = known.get(sources.key(c)) or known.get("t:" + sources.norm_title(c.get("title") or ""))
            k = existing or bib.bibkey(c, taken)
            wants_pdf = bool(c.get("pdf_url")) and self.s["options"]["download_pdfs"]
            papers.append({
                "n": item["i"], "key": k, "title": c.get("title"), "authors": (c.get("authors") or [])[:12],
                "year": c.get("year"), "venue": c.get("venue"), "doi": c.get("doi"), "arxiv": c.get("arxiv"),
                "url": c.get("url"), "pdf_url": c.get("pdf_url"), "citations": c.get("citations"),
                "sources": c.get("sources"), "role": item["role"], "takeaway": item["takeaway"] or _first_sentence(c.get("abstract")),
                "delta": item["delta"], "closes_gap": item["closes_gap"], "status": "pending" if wants_pdf else "link",
                "file": None, "node": f"ref.{existing}" if existing else None, "existing": bool(existing)})
        self.s["papers"] = papers
        self._cands = cands
        return survey_md

    # ------------------------------------------------------------ files and map

    def papers_dir(self) -> Path:
        return safe_join(self.root, self.s["options"]["papers_dir"])

    def bib_path(self) -> Path:
        return self.papers_dir() / "references.bib"

    def bib_keys(self) -> set[str]:
        try:
            return set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", self.bib_path().read_text(encoding="utf-8")))
        except OSError:
            return set()

    def known_refs(self) -> dict[str, str]:
        """Paper key (sources.key) → bibkey of the live reference nodes already on the map."""
        from ..dag.evaluate import current
        from ..dag.model import DEAD, facet_value, title_of
        from ..dag.service import store_for
        out: dict[str, str] = {}
        try:
            nodes = current(store_for(self.pid)).nodes
        except Exception:  # noqa: BLE001 — a project without a DAG yet
            return out
        for n in nodes.values():
            if n.get("kind") != "reference" or n.get("status") in DEAD:
                continue
            c = facet_value(n, "citation")
            c = c if isinstance(c, dict) else {}
            k = n["id"].split(".", 1)[1]
            title = title_of(n)
            out[sources.key({"arxiv": c.get("arxiv"), "doi": c.get("doi"), "title": title})] = k
            out["t:" + sources.norm_title(title)] = k
        return out

    def download(self) -> None:
        pdir = self.papers_dir()
        pdir.mkdir(parents=True, exist_ok=True)
        for p in self.s["papers"]:
            self.check()
            if p["status"] != "pending":
                continue
            dest = pdir / f"{p['key']}.pdf"
            rel = dest.relative_to(self.root).as_posix()
            if dest.exists():
                p.update(status="done", file=rel)
                continue
            p["status"] = "running"
            self.save()
            try:
                p["size"] = fetch.fetch_pdf(p["pdf_url"], dest)
                p.update(status="done", file=rel)
            except Exception as e:  # noqa: BLE001 — one paper's failure is recorded and the rest go on
                p.update(status="failed", error=fetch.describe(e))
            self.save()

    def draft(self, framed: dict) -> None:
        from ..dag import ops as dag_ops
        from ..dag.evaluate import current
        from ..dag.model import DEAD
        from ..dag.service import publish, store_for
        store = store_for(self.pid)
        store.ensure()
        nodes = current(store).nodes
        new: list[dict] = []
        if not any(n.get("kind") == "problem" and n.get("status") not in DEAD for n in nodes.values()):
            prob = self.problem_node(framed, set(nodes))
            if prob:
                new.append(prob)
        for p in self.s["papers"]:
            if p["existing"]:
                continue
            nid = f"ref.{p['key']}"
            if nid in nodes:
                p["node"] = nid
                continue
            new.append(self.reference_node(p))
            p["node"] = nid
        if not new:
            return
        provider = (self.s.get("agent") or {}).get("provider") or "agent"
        try:
            res = dag_ops.submit(store, [{"op": "create", "node": n} for n in new], f"agent:{provider}:survey",
                                 title="Early survey: problem and references",
                                 rationale=f"Drafted by the early survey ({self.s['id']}) from the abstracts; nothing was run.")
        except dag_ops.OpError as e:
            raise Stop(f"draft: {e}") from e
        self.s["nodes"] = [n["id"] for n in new]
        if not res.get("applied"):
            self.s["proposal"] = (res.get("proposal") or {}).get("id")
        publish(self.pid, store, self.s["nodes"])

    def problem_node(self, framed: dict, taken: set[str]) -> dict | None:
        pr = framed.get("problem") or {}
        if not any(pr.values()):
            return None
        slug = slugify(framed.get("title") or "", "")
        slug = re.sub(r"[^a-z0-9-]", "", slug)[:40].strip("-") or "main"
        nid, n = f"prob.{slug}", 2
        while nid in taken:
            nid, n = f"prob.{slug}-{n}", n + 1
        facets: dict[str, Any] = {}
        for k in ("statement", "scope", "kill_criteria"):
            if pr.get(k):
                facets[k] = pr[k]
        if pr.get("metric"):
            success = {"metric": pr["metric"], "threshold": _number(pr.get("threshold")),
                       "direction": pr.get("direction") if pr.get("direction") in ("higher", "lower") else "higher"}
            facets["success"] = {"type": "json", "value": success}
        title = framed.get("title") or self.name
        return {"id": nid, "kind": "problem", "status": "proposed", "title": {self.s["lang"]: title}, "facets": facets,
                "notes": f"Drafted by the early survey from {self.s.get('idea_file') or 'the idea'}."}

    def reference_node(self, p: dict) -> dict:
        citation = {k: v for k, v in {"bibkey": p["key"], "authors": _authors(p["authors"]), "year": p["year"],
                                      "venue": p["venue"], "doi": p["doi"], "arxiv": p["arxiv"], "url": p["url"],
                                      "pdf": p.get("file")}.items() if v}
        facets: dict[str, Any] = {"citation": {"type": "json", "value": citation},
                                  "role": {"type": "json", "value": p["role"]}}
        if p["takeaway"]:
            facets["takeaway"] = p["takeaway"]
        if p["delta"]:
            facets["delta"] = p["delta"]
        if p["closes_gap"]:
            facets["closes_gap"] = {"type": "json", "value": True}
        return {"id": f"ref.{p['key']}", "kind": "reference", "status": "proposed", "title": {"en": p["title"]},
                "facets": facets}

    def write(self, framed: dict, survey_md: str) -> None:
        zh = self.s["lang"] == "zh"
        pdir = self.papers_dir()
        pdir.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        # references.bib: new keys appended, the file's other entries left as they are
        have = self.bib_keys()
        entries = [bib.entry(self._paper(p), p["key"]) for p in self.s["papers"] if p["key"] not in have]
        if entries:
            path = self.bib_path()
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            write_text_atomic(path, old + ("\n" if old and not old.endswith("\n") else "") + ("\n" if old else "") + "\n".join(entries))
        files["bib"] = self.bib_path().relative_to(self.root).as_posix()
        index = _free(pdir / "index.md")
        write_text_atomic(index, self.index_md(zh, index.parent))
        files["index"] = index.relative_to(self.root).as_posix()
        notes = self.root / "notes"
        notes.mkdir(exist_ok=True)
        survey = _free(notes / "survey.md")
        write_text_atomic(survey, self.survey_md(zh, framed, survey_md, survey.parent))
        files["survey"] = survey.relative_to(self.root).as_posix()
        self.s["files"] = files
        for rel in files.values():
            hub.publish(self.pid, "file", {"path": rel})
        self.tell_conversation(zh)

    def _paper(self, p: dict) -> dict:
        return {k: p.get(k) for k in ("title", "authors", "year", "venue", "doi", "arxiv", "url")}

    def _link(self, p: dict, base: Path) -> str:
        if p.get("file"):
            return f"[PDF]({os.path.relpath(self.root / p['file'], base)})"
        return f"[link]({p['url']})" if p.get("url") else ""

    def index_md(self, zh: bool, base: Path) -> str:
        head = ("| 键 | 论文 | 年份 | 出处 | 角色 | 文件 |", "|---|---|---|---|---|---|") if zh else \
               ("| Key | Paper | Year | Venue | Role | File |", "|---|---|---|---|---|---|")
        rows = [f"| `{p['key']}` | {_cell(p['title'])} | {p.get('year') or ''} | {_cell(p.get('venue') or '')} | "
                f"{_role(p['role'], zh)} | {self._link(p, base)} |" for p in self.s["papers"]]
        title = "# 论文" if zh else "# Papers"
        note = (f"前期调研 {self.s['id']} 保留的论文。BibTeX 在 `references.bib`。" if zh else
                f"Papers kept by the early survey {self.s['id']}. BibTeX in `references.bib`.")
        return "\n".join([title, "", note, "", *head, *rows, ""])

    def survey_md(self, zh: bool, framed: dict, body: str, base: Path) -> str:
        by_n = {p["n"]: p for p in self.s["papers"]}
        cands = getattr(self, "_cands", [])

        def cite(m: re.Match) -> str:
            nums: list[int] = []
            for part in re.split(r"\s*,\s*", m.group(1)):
                a, _, b = part.partition("-") if "-" in part else part.partition("–")
                if b and a.isdigit() and b.isdigit() and int(b) - int(a) < 20:
                    nums += list(range(int(a), int(b) + 1))
                elif a.isdigit():
                    nums.append(int(a))
            out = []
            for i in nums:
                if i in by_n:
                    out.append(f"@{by_n[i]['key']}")
                elif 1 <= i <= len(cands):
                    c = cands[i - 1]
                    out.append(f"{c.get('title')}, {c.get('year') or 'n.d.'}")
            return "[" + "; ".join(out) + "]" if out else m.group(0)

        body = re.sub(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]", cite, body or "").strip()
        opts = self.s["options"]
        src = ", ".join(sources.LABELS.get(s, s) for s in opts["sources"])
        idea = self.s.get("idea_file") or ("想法" if zh else "the idea")
        if zh:
            lines = [f"# 前期调研：{framed.get('title') or self.name}", "",
                     f"> {date.today().isoformat()} 由 Research Deck 根据 `{idea}` 生成。检索了 {src}，"
                     f"读的是摘要，没有运行任何实验。下面的判断都需要你核实。", ""]
        else:
            lines = [f"# Early survey: {framed.get('title') or self.name}", "",
                     f"> Generated by Research Deck on {date.today().isoformat()} from `{idea}`. It searched {src} and "
                     "read the abstracts only; nothing was run. Check every judgement below.", ""]
        if body:
            lines += [body, ""]
        lines += ["## 论文" if zh else "## Papers", "",
                  "| 键 | 论文 | 角色 | 和想法的差异 | 文件 |" if zh else "| Key | Paper | Role | How the idea differs | File |",
                  "|---|---|---|---|---|"]
        for p in self.s["papers"]:
            gap = (" **（可能已经解决了这个问题）**" if zh else " **(may already close the gap)**") if p["closes_gap"] else ""
            lines.append(f"| `{p['key']}` | {_cell(p['title'])} ({p.get('year') or 'n.d.'}) | {_role(p['role'], zh)} | "
                         f"{_cell(p['delta'])}{gap} | {self._link(p, base)} |")
        lines += ["", "## 检索词" if zh else "## Search queries", ""] + [f"- `{q}`" for q in self.s["queries"]] + [""]
        return "\n".join(lines)

    def tell_conversation(self, zh: bool) -> None:
        papers = self.s["papers"]
        pdfs = sum(1 for p in papers if p["status"] == "done")
        links = sum(1 for p in papers if p["status"] in ("link", "failed"))
        files = self.s["files"]
        nodes = self.s["nodes"]
        if zh:
            text = (f"前期调研完成：检索到 {self.s['search']['found']} 篇候选，保留 {len(papers)} 篇，"
                    f"{pdfs} 篇 PDF 存到了 `{self.s['options']['papers_dir']}/`，{links} 篇只存链接和 BibTeX。"
                    f"综述在 `{files.get('survey')}`。地图上起草了 {len(nodes)} 个节点（问题和文献），都是提议，等你确认；"
                    "没有运行任何实验。")
        else:
            text = (f"The early survey is done: {self.s['search']['found']} candidates found, {len(papers)} kept, "
                    f"{pdfs} PDFs saved in `{self.s['options']['papers_dir']}/`, {links} with a link and BibTeX only. "
                    f"The survey is in `{files.get('survey')}`. It drafted {len(nodes)} nodes (the problem and the "
                    "references) as proposals for you to confirm; nothing was run.")
        provider = (self.s.get("agent") or {}).get("provider") or "claude"
        try:
            transcript.append(self.pid, "project", {"provider": provider, "session_id": None, "role": "assistant",
                                                    "text": text, "run_id": None, "purpose": "survey"})
            hub.publish(self.pid, "agent", {"run_id": None, "status": "done", "purpose": "survey"})
        except OSError:
            log.exception("survey %s: could not write the conversation", self.s["id"])
        note = (f"Research Deck ran the early survey ({self.s['id']}) outside this conversation. Queries: "
                + "; ".join(self.s["queries"]) + f". It kept {len(papers)} papers ({pdfs} PDFs in "
                f"{self.s['options']['papers_dir']}/, BibTeX in {files.get('bib')}), wrote {files.get('survey')} and "
                f"drafted these proposed nodes: {', '.join(nodes) or 'none'}. They are unconfirmed and no experiment was run.")
        for prov in sessions.PROVIDERS:
            path = pending_path(self.pid, "project", prov)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                old = path.read_text(encoding="utf-8") if path.exists() else ""
                write_text_atomic(path, (old.rstrip() + "\n\n" if old.strip() else "") + note + "\n")
            except OSError:
                log.exception("survey %s: could not leave the note for %s", self.s["id"], prov)


# ---------------------------------------------------------------- helpers

def _short(e: BaseException | str, limit: int = 300) -> str:
    s = str(e) or e.__class__.__name__
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _first_sentence(text: str | None) -> str:
    t = (text or "").strip()
    m = re.match(r"(.{40,400}?[.!?])(\s|$)", t)
    return m.group(1) if m else t[:300]


def _number(v: Any) -> Any:
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v or None


def _authors(names: list[str]) -> str:
    names = [n for n in names or [] if n]
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")


def _cell(s: str | None) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


ROLE_ZH = {"competitor": "竞品", "baseline": "基线", "related": "相关", "background": "背景"}


def _role(role: str, zh: bool) -> str:
    return ROLE_ZH.get(role, role) if zh else role


def _free(path: Path) -> Path:
    """`path`, or path-2, path-3 … when a file of that name exists (the survey never overwrites a file)."""
    if not path.exists():
        return path
    n = 2
    while (cand := path.with_name(f"{path.stem}-{n}{path.suffix}")).exists():
        n += 1
    return cand
