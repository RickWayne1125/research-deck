// The four steps the UI shows: Idea → Motivation & insight → System design → Evaluation. The project config keeps the
// finer stages (idea, motivation, insight, design, evaluation, writing) and the DAG its S0…W; both map onto the steps
// here. Writing is not a step: section nodes count under Evaluation and the paper view is always there.
import type { GateStatus, StageKey } from '../dag-types';
import type { StageId } from '../types';

export type StepId = 'idea' | 'insight' | 'design' | 'evaluation';
export const STEPS: StepId[] = ['idea', 'insight', 'design', 'evaluation'];

/** The project stages (project.yaml `stage`) each step covers. */
export const STEP_STAGES: Record<StepId, StageId[]> = {
  idea: ['idea'], insight: ['motivation', 'insight'], design: ['design'], evaluation: ['evaluation', 'writing'],
};
/** The DAG stages each step covers. */
export const STEP_DAG: Record<StepId, StageKey[]> = {
  idea: ['S0', 'S1'], insight: ['S2', 'S3', 'S4'], design: ['S5'], evaluation: ['S6', 'W'],
};
/** The gates that close each step (dag/gates.py GATES_CLOSING, grouped by step). */
export const STEP_GATES: Record<StepId, string[]> = {
  idea: ['G1'], insight: ['G2', 'G3', 'G4'], design: ['G5'], evaluation: ['G6', 'G7'],
};

export function stepOfStage(stage: string | null | undefined): StepId {
  return STEPS.find(s => (STEP_STAGES[s] as string[]).includes(stage ?? '')) ?? 'idea';
}

export function stepOfDag(stage: StageKey | string | null | undefined): StepId {
  return STEPS.find(s => (STEP_DAG[s] as string[]).includes(stage ?? '')) ?? 'idea';
}

/** The project stage after leaving this step; null after the last one. */
export function nextStage(step: StepId): StageId | null {
  const i = STEPS.indexOf(step);
  return i < STEPS.length - 1 ? STEP_STAGES[STEPS[i + 1]][0] : null;
}

export interface Missing { gate: string; label: string; zh?: string; items: string[] }

/** What stands between the project and the next step: the gates of this step and the earlier ones that are not
 *  passed yet, and the checks among them that fail ("2 to go"). A gate whose checks all hold is passed on the way. */
export function leaving(step: StepId, gates: GateStatus[] | null | undefined): { gates: GateStatus[]; missing: Missing[] } {
  const wanted = new Set(STEPS.slice(0, STEPS.indexOf(step) + 1).flatMap(s => STEP_GATES[s]));
  const open = (gates ?? []).filter(g => wanted.has(g.gate) && g.state !== 'passed');
  const missing = open.flatMap(g => g.checks.filter(c => !c.ok).map(c => ({ gate: g.gate, label: c.label, zh: c.zh, items: c.items ?? [] })));
  return { gates: open, missing };
}

/** Under the stage rules (any mode but free), a node of a step the project has not reached waits for that step: it
 *  can be drafted (mode ahead) but not accepted. */
export function waitsForStep(n: { stage?: string | null }, current: StepId, mode: string | null | undefined): boolean {
  return (mode ?? 'free') !== 'free' && STEPS.indexOf(stepOfDag(n.stage)) > STEPS.indexOf(current);
}
