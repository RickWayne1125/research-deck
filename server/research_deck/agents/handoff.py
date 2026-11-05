"""Handing the project conversation from one backend to the other (Claude Code <-> Codex) without losing the thread.

handoff(pid, panel, to, smart):
  1. gathers the conversation's dashboard transcript since its last handoff;
  2. summarizes it — smart: the OUTGOING backend writes the summary (one ephemeral run, no tools, a quick model:
     Sonnet 5.5 at low effort, or the bound Codex model at low effort); otherwise (or if that run fails) a
     deterministic extraction: what was being worked on, decisions, open questions, files touched;
  3. writes .research/context/handoffs/<ts>-<panel>-<from>-to-<to>.md with the summary, the last few exchanges
     (trimmed) and an excerpt of the project brief;
  4. queues the note at context.pending_path(...) — context.compose_prompt prepends it, once, as a <handoff> block
     to the next prompt sent to that backend (an undelivered earlier note is kept and the new one appended);
  5. switches the active backend and appends a "handoff" line to the transcript.

leave_note(...) is the MCP tool rd_handoff_note: an agent leaves a note for the other backend.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import HTTPException

from ..projects import project_root, research_dir
from ..util import rel_to, safe_join, write_text_atomic
from . import brief, context, runner, sessions, transcript

log = logging.getLogger("research_deck.agents")

LABELS = {"claude": "Claude Code", "codex": "Codex", "fake": "Fake agent"}
QUICK = {"claude": ("claude-sonnet-5-5", "low"), "codex": (None, "low")}   # None: the panel's bound Codex model
SMART_TIMEOUT_S = 240
TRANSCRIPT_CHARS = 30_000       # what the outgoing agent sees of the transcript (the newest part)
LAST_EXCHANGES = 4
BRIEF_EXCERPT_CHARS = 4000
NOTE_MAX_CHARS = 20_000

PATH_RE = re.compile(
    r"(?<![\w/.-])((?:[\w.-]+/)*[\w-][\w.-]*\.(?:py|pyi|tex|md|bib|ya?ml|json|toml|csv|tsv|tsx?|jsx?|sh|ipynb|cpp|cc|c|h|hpp|cu|"
    r"rs|go|txt|drawio|svg|pdf|png|ini|cfg))(?![\w/])")
NODE_RE = re.compile(r"\b(?:prob|ref|data|exp|find|gap|sol|dec|design|mod|fig|claim|sec)\.[a-z0-9][a-z0-9-]*\b")
DECISION_RE = re.compile(
    r"\b(?:decided|decision|we(?:'ll| will) (?:go with|use|keep|switch)|let's (?:go with|use|keep)|chose|agreed|going with|"
    r"settled on)\b|决定|确定用|选定|选择了|采用|就用|改为|改成|确认了", re.I)
QUESTION_START_RE = re.compile(r"^(?:TODO|FIXME|open question|question|unclear|待定|待确认|待办|问题[:：]|疑问)", re.I)


def _other(provider: str) -> str:
    return "codex" if provider == "claude" else "claude"


def _file_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _trim(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = int(limit * 0.75)
    return text[:head].rstrip() + " … " + text[-(limit - head - 3):].lstrip()


def _defuse(text: str) -> str:
    """The note goes inside one <handoff> block; a literal tag in it must not open or close another."""
    return re.sub(r"<(/?)handoff>", r"‹\1handoff›", text, flags=re.I)


def _prose_lines(text: str):
    """Lines of a message outside fenced code blocks, with list markers stripped."""
    fenced = False
    for raw in (text or "").splitlines():
        if raw.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", raw).strip()
        if line:
            yield line


def _uniq(items, limit: int) -> list:
    out, seen = [], set()
    for x in items:
        key = x.lower() if isinstance(x, str) else x
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ deterministic summary

def extract(pid: str, messages: list[dict]) -> dict:
    """What a quick read of the transcript can tell without a model."""
    root = project_root(pid)
    users = [m for m in messages if m.get("role") == "user"]
    working = []
    if users:
        working.append(_trim(users[0].get("text", ""), 300))
        if len(users) > 1:
            working.append(_trim(users[-1].get("text", ""), 300))
    decisions, questions, paths, nodes = [], [], [], []
    for i, m in enumerate(messages):
        text = m.get("text", "")
        recent = i >= len(messages) - 6
        for line in _prose_lines(text):
            if DECISION_RE.search(line):
                decisions.append(_trim(line, 220))
            if recent and (line.endswith(("?", "？")) or QUESTION_START_RE.match(line)):
                questions.append(_trim(line, 220))
        paths += PATH_RE.findall(text)
        nodes += NODE_RE.findall(text)
    files = []
    for rel in _uniq(paths, 60):
        try:
            if safe_join(root, rel).exists():
                files.append(rel)
        except HTTPException:
            continue
    return {"working": working, "decisions": _uniq(decisions, 8), "questions": _uniq(questions, 6),
            "files": _uniq(files, 15), "nodes": _uniq(nodes, 12), "count": len(messages)}


def render_extracted(x: dict) -> str:
    if not x["count"]:
        return "Nothing new in this panel since the last handoff."
    def bullets(items, empty="—", code=False):
        return [f"- `{i}`" if code else f"- {i}" for i in items] or [f"- {empty}"]
    out = ["### What we were working on", *bullets(x["working"])]
    if x["nodes"]:
        out.append("- DAG nodes mentioned: " + ", ".join(f"`{n}`" for n in x["nodes"]))
    out += ["", "### Decisions", *bullets(x["decisions"], "none stated explicitly"),
            "", "### Open questions", *bullets(x["questions"], "none stated explicitly"),
            "", "### Files touched or mentioned", *bullets(x["files"], "none", code=True)]
    return "\n".join(out)


# ------------------------------------------------------------------ smart summary (the outgoing agent)

SMART_SYSTEM = ("You write handoff notes between two coding agents working for the same researcher in Research Deck. "
                "Answer from the transcript alone; do not use tools.")


def _transcript_text(messages: list[dict], provider: str) -> str:
    lines = []
    for m in messages:
        who = "researcher" if m.get("role") == "user" else LABELS.get(m.get("provider") or provider, "assistant")
        lines.append(f"[{who}] {m.get('text', '').strip()}")
    text = "\n\n".join(lines)
    return text if len(text) <= TRANSCRIPT_CHARS else "…\n" + text[-TRANSCRIPT_CHARS:]


def smart_prompt(panel: str, frm: str, to: str, messages: list[dict]) -> str:
    return "\n".join([
        f"The researcher is moving the {panel} panel of Research Deck from {LABELS[frm]} (you) to {LABELS[to]}, "
        f"which has not seen this conversation. Write the handoff note {LABELS[to]} will read first.",
        "",
        "Use exactly these Markdown sections, each a few short bullets:",
        "### What we were working on", "### Decisions", "### Open questions", "### Files touched", "### Next step",
        "",
        "Keep identifiers, file paths, numbers and DAG node ids exactly as written. At most about 250 words. "
        "Write in the language the researcher uses. Do not invent anything the transcript does not say.",
        "",
        f"<transcript panel=\"{panel}\">", _transcript_text(messages, frm), "</transcript>",
    ])


def _smart_summary(pid: str, panel: str, frm: str, to: str, messages: list[dict]) -> tuple[str | None, str | None, str | None]:
    """(summary, written_by, error) from one ephemeral run on the outgoing backend."""
    from .api import RunBody, spec_for   # api imports this module
    model, effort = QUICK.get(frm, (None, "low"))
    body = RunBody(panel=panel, prompt=smart_prompt(panel, frm, to, messages), purpose="handoff", ephemeral=True,
                   provider=frm, model=model, effort=effort, fast=False, permission="read")
    try:
        spec = spec_for(pid, body, system=SMART_SYSTEM, tools=False)
        spec.mcp = False
        spec.timeout_s = SMART_TIMEOUT_S
        run = runner.run_blocking(spec, timeout=SMART_TIMEOUT_S + 15)
    except Exception as e:  # noqa: BLE001 — fall back to the extracted summary
        return None, None, str(e)
    if run.status == "running":
        runner.cancel(run.id)
        return None, None, f"the summary run timed out after {SMART_TIMEOUT_S}s"
    text = (run.text or "").strip()
    if run.status != "done" or not text:
        return None, None, run.error or "the outgoing agent gave no summary"
    return text, f"{LABELS.get(frm, frm)} ({spec.model}, {spec.effort} effort)", None


def _fake_handoff(spec: runner.RunSpec) -> str:
    """RD_FAKE_AGENT answer: a fixed-shape summary built from the transcript in the prompt."""
    m = re.search(r"<transcript[^>]*>\n([\s\S]*?)\n</transcript>", spec.prompt)
    body = m.group(1) if m else ""
    count = len(re.findall(r"(?:^|\n\n)\[[^\]\n]+\] ", body))
    first = re.search(r"(?:^|\n\n)\[researcher\] ([^\n]*)", body)
    return "\n".join([
        "### What we were working on", f"- (fake summary of {count} messages) {(first.group(1) if first else '—')[:160]}",
        "", "### Decisions", "- none recorded", "", "### Open questions", "- none", "",
        "### Files touched", "- none", "", "### Next step", "- continue from the last message",
    ])


runner.register_fake("handoff", _fake_handoff)


# ------------------------------------------------------------------ the note

def _excerpt_brief(markdown: str | None) -> str:
    if not markdown:
        return "_No brief available._"
    lines = [ln for ln in markdown.splitlines() if not ln.startswith(brief.STAMP_PREFIX)]
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = "\n".join(("#" + ln) if ln.startswith("## ") else ln for ln in lines).strip()
    return _trim(body, BRIEF_EXCERPT_CHARS) if len(body) > BRIEF_EXCERPT_CHARS else body


def _quote(text: str) -> str:
    return "\n".join("> " + ln if ln.strip() else ">" for ln in text.splitlines())


def _session_desc(s: dict) -> str:
    sid = (s.get("session_id") or "")[:8]
    return (f"session `{sid}`" if sid else "no session yet") + f" ({s.get('model')}, {s.get('effort')} effort)"


def compose_note(*, panel: str, frm: str, to: str, ts: str, entry: dict, messages: list[dict], summary: str,
                 written_by: str | None, brief_markdown: str | None) -> str:
    to_sid = (entry[to].get("session_id") or "")[:8]
    out = [
        f"# Handoff: {panel} panel, {LABELS[frm]} → {LABELS[to]}", "",
        f"- When: {ts}",
        f"- From: {LABELS[frm]}, {_session_desc(entry[frm])}",
        f"- To: {LABELS[to]}, " + (f"resuming session `{to_sid}`" if to_sid else "a new session"),
        f"- Messages since the last handoff: {len(messages)}",
        f"- Summary: {'written by ' + written_by if written_by else 'extracted from the dashboard transcript'}",
        "", "## Summary", "", summary.strip(), "",
    ]
    last = messages[-LAST_EXCHANGES:]
    if last:
        out += ["## Last exchanges", ""]
        for m in last:
            who = "Researcher" if m.get("role") == "user" else LABELS.get(m.get("provider") or frm, "Agent")
            out += [f"**{who}** · {m.get('ts', '')}", _quote(_trim(m.get("text", ""), 700)), ""]
    out += ["## Project brief (excerpt)", "", _excerpt_brief(brief_markdown), "",
            "Full brief: `.research/context/BRIEF.md`. Earlier handoff notes: `.research/context/handoffs/`.", ""]
    return _defuse("\n".join(out))


def _unique_path(folder, stem: str):
    path = folder / f"{stem}.md"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}.md"
        n += 1
    return path


def _queue(pid: str, panel: str, provider: str, note: str) -> None:
    path = context.pending_path(pid, panel, provider)
    try:
        earlier = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        earlier = ""
    write_text_atomic(path, (earlier + "\n\n---\n\n" if earlier else "") + note.strip() + "\n")


def handoff(pid: str, panel: str, to: str, smart: bool = False) -> dict:
    if panel not in sessions.ORIGINS:
        raise ValueError(f"unknown panel: {panel}")
    if to not in sessions.PROVIDERS:
        raise ValueError(f"unknown provider: {to}")
    owner = sessions.effective_panel(pid, panel)
    entry = sessions.load(pid)["panels"][owner]
    frm = entry["active"]
    if frm == to:
        return {"file": None, "summary": "", "pending": context.pending_path(pid, owner, to).exists(), "panel": owner,
                "from": frm, "to": to, "smart": False, "unchanged": True}

    messages = transcript.since_last_handoff(transcript.dashboard_entries(pid, owner))
    summary = written_by = error = None
    if smart and messages:
        summary, written_by, error = _smart_summary(pid, owner, frm, to, messages)
        if error:
            log.warning("smart handoff summary failed (%s); using the extracted summary", error)
    if not summary:
        summary = render_extracted(extract(pid, messages))
    try:
        brief_markdown = brief.generate(pid)["markdown"]
    except Exception:  # noqa: BLE001 — a handoff must not fail on the brief
        log.exception("brief generation failed during handoff")
        brief_markdown = None

    ts = _iso_now()
    note = compose_note(panel=owner, frm=frm, to=to, ts=ts, entry=entry, messages=messages, summary=summary,
                        written_by=written_by, brief_markdown=brief_markdown)
    folder = research_dir(pid) / "context" / "handoffs"
    path = _unique_path(folder, f"{_file_ts()}-{owner}-{frm}-to-{to}")
    write_text_atomic(path, note)
    _queue(pid, owner, to, note)
    new_entry = sessions.update_binding(pid, owner, {"provider": to})
    rel = rel_to(project_root(pid), path)
    transcript.append(pid, owner, {"provider": to, "session_id": new_entry[to].get("session_id"), "role": "handoff",
                                   "text": _trim(summary, 4000), "from": frm, "to": to, "file": rel,
                                   "smart": bool(written_by), "messages": len(messages)})
    return {"file": rel, "summary": summary, "pending": True, "panel": owner, "from": frm, "to": to,
            "smart": bool(written_by), "written_by": written_by, "error": error}


def provider_of_actor(actor: str | None) -> str | None:
    """'agent:codex:019a3f' -> 'codex'."""
    parts = (actor or "").split(":")
    return parts[1] if len(parts) >= 2 and parts[0] == "agent" and parts[1] in sessions.PROVIDERS else None


def leave_note(pid: str, panel: str, text: str, actor: str | None = None, to: str | None = None) -> dict:
    """Queue a note for the other backend of the project conversation (the MCP tool rd_handoff_note)."""
    if panel not in sessions.ORIGINS:
        raise ValueError(f"unknown panel: {panel}")
    text = (text or "").strip()
    if not text:
        raise ValueError("the note is empty")
    owner = sessions.effective_panel(pid, panel)
    frm = provider_of_actor(actor) or sessions.load(pid)["panels"][owner]["active"]
    to = to or _other(frm)
    if to not in sessions.PROVIDERS:
        raise ValueError(f"unknown provider: {to}")
    ts = _iso_now()
    note = _defuse(f"# Note from {LABELS.get(frm, frm)} for {LABELS[to]} ({owner} panel)\n\n"
                   f"- When: {ts}\n- Left by: {actor or 'an agent'}\n\n{_trim(text, NOTE_MAX_CHARS)}\n")
    folder = research_dir(pid) / "context" / "handoffs"
    path = _unique_path(folder, f"{_file_ts()}-{owner}-{frm}-note-to-{to}")
    write_text_atomic(path, note)
    _queue(pid, owner, to, note)
    rel = rel_to(project_root(pid), path)
    transcript.append(pid, owner, {"provider": frm, "session_id": None, "role": "handoff", "kind": "note",
                                   "text": _trim(text, 4000), "from": frm, "to": to, "file": rel, "by": actor})
    return {"file": rel, "pending": True, "panel": owner, "from": frm, "to": to}


def pending_notes(pid: str) -> list[dict]:
    """Notes queued and not yet delivered: [{panel, provider, bytes}]."""
    folder = research_dir(pid) / "context" / "pending"
    out = []
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        panel, _, provider = f.stem.rpartition("-")
        out.append({"panel": panel, "provider": provider, "bytes": f.stat().st_size,
                    "file": rel_to(project_root(pid), f)})
    return out


def recent_handoffs(pid: str, limit: int = 20) -> list[dict]:
    folder = research_dir(pid) / "context" / "handoffs"
    files = sorted(folder.glob("*.md"), key=lambda f: f.name, reverse=True)[:limit] if folder.is_dir() else []
    out = []
    for f in files:
        m = re.match(r"(\d{8}T\d{6}Z)-([a-z]+)-([a-z]+)-(to|note-to)-([a-z]+)", f.stem)
        out.append({"file": rel_to(project_root(pid), f), "ts": m.group(1) if m else None, "panel": m.group(2) if m else None,
                    "from": m.group(3) if m else None, "to": m.group(5) if m else None,
                    "kind": ("note" if m and m.group(4) == "note-to" else "handoff")})
    return out
