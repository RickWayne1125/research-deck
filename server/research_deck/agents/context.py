"""What an agent is told besides the user's message: the dashboard's system note, the panel's context, the project
brief and any pending handoff from the other backend. Shared by every panel's runs.

Files (in <project>/.research/context/):
  BRIEF.md                    the project brief: stage, confirmed facts, open questions, active attempts (generated)
  handoffs/<ts>-<panel>-<from>-to-<to>.md   what one backend tells the other when the user switches
  transcripts/<panel>.jsonl   the dashboard's own record of each panel's messages (runner._transcript)
  pending/<panel>-<provider>.md  a handoff not yet delivered to that backend; prepended to its next prompt, then removed
"""
from __future__ import annotations

from pathlib import Path

from ..projects import project_config, project_root, research_dir

# Where a request comes from (the view the researcher is in); the conversation is the same either way.
ORIGIN_NOTES = {
    "writing": "The researcher is in the Paper view (documents and figures).",
    "coding": "The researcher is in the Code view (changes and reviews).",
    "experiments": "The researcher is in the Experiments view (runs and resources).",
    "visualization": "The researcher is working on a figure (draw.io / OmniGraffle diagrams, matplotlib / DataGraph plots).",
}


def system_note(pid: str, panel: str, purpose: str) -> str:
    cfg = project_config(pid)
    origin = ORIGIN_NOTES.get(panel)
    return (
        "You are working inside Research Deck, the researcher's dashboard, as the project's collaborator: you keep the "
        "research map (the DAG) current and help with the paper, the code, the experiments and the figures. "
        + (origin + " " if origin else "") +
        f"Project: {cfg.get('name')} ({cfg.get('venue') or 'no venue set'}), stage: {cfg.get('stage')}. "
        "The project's research DAG, brief and handoff notes are in .research/ (read .research/context/BRIEF.md first when "
        "you need the big picture); the research-deck MCP tools read and update the DAG. Propose DAG changes rather than "
        "locking, unlocking or deleting nodes yourself; the researcher confirms those. Answer in the language the researcher "
        "writes in unless asked otherwise. Keep technical identifiers as they are."
    )


def brief_path(pid: str) -> Path:
    return research_dir(pid) / "context" / "BRIEF.md"


def pending_path(pid: str, panel: str, provider: str) -> Path:
    return research_dir(pid) / "context" / "pending" / f"{panel}-{provider}.md"


def compose_prompt(pid: str, panel: str, provider: str, prompt: str, ctx: dict | None, *, consume_pending: bool = True) -> str:
    """The prompt actually sent: pending handoff (once), the panel context the user attached, then the message."""
    parts: list[str] = []
    pending = pending_path(pid, panel, provider)
    if pending.exists():
        parts.append("<handoff>\n" + pending.read_text(encoding="utf-8").strip() + "\n</handoff>")
        if consume_pending:
            pending.unlink(missing_ok=True)
    ctx = ctx or {}
    lines = []
    if ctx.get("node_id"):
        lines.append(f"DAG node in focus: {ctx['node_id']} (read it with the research-deck MCP tool or .research/dag/)")
    if ctx.get("file"):
        lines.append(f"File in focus: {ctx['file']}")
    sel = ctx.get("selection") or {}
    if sel.get("text"):
        where = f" (lines {sel.get('start_line')}-{sel.get('end_line')})" if sel.get("start_line") else ""
        lines.append(f"Selected text{where}:\n<selection>\n{sel['text']}\n</selection>")
    if ctx.get("extra"):
        lines.append(str(ctx["extra"]))
    if lines:
        parts.append("<context>\n" + "\n".join(lines) + "\n</context>")
    parts.append(prompt)
    return "\n\n".join(parts)


def project_cwd(pid: str) -> str:
    return str(project_root(pid))
