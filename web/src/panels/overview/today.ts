// What needs the researcher today (pure; tested in today.test.ts). Today lists only what asks for a decision or is
// blocked, each with the action that settles it; everything else stays on the map.
import { DEAD_STATUSES, type DagNode, type GraphResponse, type Proposal } from '../../dag-types';
import type { Experiment } from '../../types';

export interface DecisionItem { node: DagNode; options: DagNode[] }
export interface Needs {
  proposals: Proposal[];                     // agent changes waiting for approval
  review: DagNode[];                         // nodes an agent drafted (status proposed)
  decisions: DecisionItem[];                 // decisions without a choice
  fix: string[];                             // nodes to revise: broken, orphaned or to review
  rerun: { ids: string[]; gpuH: number };    // experiments to run or rerun
  failed: Experiment[];                      // runs that failed in the last week
}
export interface Waiting {
  evidence: DagNode[];                       // findings and claims with no supporting evidence yet
  blocked: string[];                         // experiments waiting for code or for an upstream result
}

const DAY = 86_400_000;
const isLive = (n: DagNode) => !DEAD_STATUSES.includes(n.status);
const nodeId = (addr: string) => addr.match(/^node:([^#[]+)/)?.[1] ?? null;

/** A facet's plain value ("choice" holds the chosen solution's id once a decision is made). */
export function facetText(n: DagNode, name: string): string | null {
  const v = n.facets?.[name]?.value;
  return typeof v === 'string' && v.trim() ? v.trim() : null;
}

/** The solutions a decision chooses between: the ones it links to, else its alternatives' group. */
export function decisionOptions(d: DagNode, byId: Map<string, DagNode>): DagNode[] {
  const linked = (d.edges ?? []).map(e => nodeId(e.to)).filter((id): id is string => !!id)
    .map(id => byId.get(id)).filter((n): n is DagNode => !!n && n.kind === 'solution' && isLive(n));
  return [...new Map(linked.map(n => [n.id, n])).values()];
}

export function isOpenDecision(d: DagNode, byId: Map<string, DagNode>): boolean {
  if (d.kind !== 'decision' || !isLive(d) || d.status === 'confirmed' || d.status === 'locked') return false;
  const choice = facetText(d, 'choice');
  return !choice || !byId.has(choice);
}

export function computeNeeds(graph: GraphResponse | null, proposals: Proposal[] | null, runs: Experiment[] | null, now = Date.now()): Needs {
  const nodes = (graph?.nodes ?? []).filter(isLive);
  const byId = new Map(nodes.map(n => [n.id, n]));
  const lenses = graph?.lenses;
  const rerunItems = (lenses?.rerun.items ?? []).filter(i => i.note === 'rerun' && byId.has(i.id));
  return {
    proposals: proposals ?? [],
    review: nodes.filter(n => n.status === 'proposed'),
    decisions: nodes.filter(n => isOpenDecision(n, byId)).map(node => ({ node, options: decisionOptions(node, byId) })),
    fix: [...new Set((lenses?.revise.items ?? []).map(i => i.id).filter(id => byId.has(id)))],
    rerun: { ids: [...new Set(rerunItems.map(i => i.id))], gpuH: lenses?.rerun.gpu_h ?? 0 },
    failed: (runs ?? []).filter(r => r.status === 'failed' && now - (Date.parse(r.finished_at ?? r.started_at ?? '') || 0) < 7 * DAY),
  };
}

export function computeWaiting(graph: GraphResponse | null): Waiting {
  const nodes = (graph?.nodes ?? []).filter(isLive);
  const byId = new Set(nodes.map(n => n.id));
  const supported = (n: DagNode) => (n.edges ?? []).some(e => e.type === 'evidence' && e.polarity !== 'refutes');
  const blocked = (graph?.lenses.rerun.items ?? []).filter(i => i.note !== 'rerun' && byId.has(i.id)).map(i => i.id);
  return {
    evidence: nodes.filter(n => (n.kind === 'claim' || n.kind === 'finding') && !supported(n)),
    blocked: [...new Set(blocked)],
  };
}

/** The number on Today in the navigation: one per card that asks for a decision. */
export function needsCount(n: Needs): number {
  return n.proposals.length + (n.review.length ? 1 : 0) + n.decisions.length + (n.fix.length ? 1 : 0)
    + (n.rerun.ids.length ? 1 : 0) + (n.failed.length ? 1 : 0);
}
