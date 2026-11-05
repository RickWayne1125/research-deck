"""Stage-by-stage progression (docs/DAG.md §1.1): the four steps the UI shows and the rules that keep the map growing
one step at a time.

  steps        Idea (S0 S1) → Motivation & insight (S2 S3 S4) → System design (S5) → Evaluation (S6 W); the project's
               stage (project.yaml) says which step it is in (idea → 0; motivation, insight → 1; design → 2; evaluation,
               writing → 3).
  modes        dag config `stages.mode`:
               strict  a node of a later step than the project's cannot be created; an edge from a node to one of an
                       earlier step needs that node confirmed (or locked);
               ahead   later-step nodes may be drafted (proposed) and linked freely, but none can become active until
                       its step starts and its earlier-step parents are confirmed;
               free    no stage rules (older projects that predate them).
  every mode but free: no new edge may point at a dead node (refuted, abandoned, superseded): a failed branch ends.
"""
from __future__ import annotations

from typing import Any

from ..util import read_yaml

MODES = ("strict", "ahead", "free")
# The outline (sections and their items) is written from the start; only its evidence follows the steps.
OUTLINE_KINDS = frozenset({"section", "claim"})
STEP_IDS = ("idea", "insight", "design", "evaluation")
STEP_OF_DAG = {"S0": 0, "S1": 0, "S2": 1, "S3": 1, "S4": 1, "S5": 2, "S6": 3, "W": 3}
STEP_OF_PROJECT = {"idea": 0, "motivation": 1, "insight": 1, "design": 2, "evaluation": 3, "writing": 3}
LABELS = {"idea": "Idea", "insight": "Motivation & insight", "design": "System design", "evaluation": "Evaluation"}


def mode(cfg: dict) -> str:
    m = (cfg.get("stages") or {}).get("mode")
    return m if m in MODES else "strict"


def node_step(n: dict) -> int:
    return STEP_OF_DAG.get(str(n.get("stage")), 0)


def project_step(store: Any) -> int:
    cfg = read_yaml(store.root / store.state / "project.yaml", {}) or {}
    return STEP_OF_PROJECT.get(str(cfg.get("stage") or "idea"), 0)


def label(step: int) -> str:
    return LABELS[STEP_IDS[max(0, min(step, len(STEP_IDS) - 1))]]
