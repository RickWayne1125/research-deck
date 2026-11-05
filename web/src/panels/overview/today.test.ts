import { describe, expect, it } from 'vitest';
import type { DagNode, GateStatus, GraphResponse, Proposal } from '../../dag-types';
import type { Experiment } from '../../types';
import { leaving, nextStage, stepOfDag, stepOfStage } from '../../state/stages';
import { computeNeeds, computeWaiting, decisionOptions, isOpenDecision, needsCount } from './today';

const node = (id: string, kind: DagNode['kind'], extra: Partial<DagNode> = {}): DagNode => ({
  id, kind, stage: 'S3', title: { en: id }, status: 'active', head: { rev: 1, vid: 'v', fp: 's:0' }, facets: {}, edges: [], ...extra,
});
const lenses = (revise: string[], rerun: { id: string; note: string }[]) => ({
  tried: { count: 0, dead: 0, runs: 0, items: [] }, confirmed: { count: 0, shaky: 0, items: [] },
  revise: { count: revise.length, items: revise.map(id => ({ id })) },
  rerun: { count: rerun.length, gpu_h: 2.5, blocked: 0, conditional: 0, reused_cells: 0, reused_gpu_h: 0, items: rerun },
});

const NODES: DagNode[] = [
  node('sol.a', 'solution'), node('sol.b', 'solution'), node('sol.old', 'solution', { status: 'abandoned' }),
  node('dec.open', 'decision', { status: 'proposed', facets: { choice: { type: 'prose', value: 'open: not decided' } },
    edges: [{ type: 'basis', to: 'node:sol.a' }, { type: 'basis', to: 'node:sol.b#mechanism' }, { type: 'basis', to: 'node:sol.old' }] }),
  node('dec.done', 'decision', { facets: { choice: { type: 'text', value: 'sol.a' } }, edges: [{ type: 'basis', to: 'node:sol.a' }] }),
  node('claim.x', 'claim', { status: 'proposed' }),
  node('claim.ok', 'claim', { edges: [{ type: 'evidence', to: 'run:r1#out.acc' }] }),
  node('exp.e1', 'experiment', { stage: 'S6' }), node('exp.e2', 'experiment', { stage: 'S6' }),
];
const GRAPH = { nodes: NODES, eval: {}, digest: 'd', lenses: lenses(['claim.x'], [{ id: 'exp.e1', note: 'rerun' }, { id: 'exp.e2', note: 'blocked: implement first' }]) } as unknown as GraphResponse;

describe('Today', () => {
  it('collects what needs a decision', () => {
    const now = Date.parse('2026-11-05T12:00:00Z');
    const runs = [
      { id: 'r-old', title: 'old', status: 'failed', finished_at: '2026-10-01T00:00:00Z' },
      { id: 'r-new', title: 'new', status: 'failed', finished_at: '2026-11-04T00:00:00Z' },
      { id: 'r-ok', title: 'ok', status: 'succeeded', finished_at: '2026-11-04T00:00:00Z' },
    ] as unknown as Experiment[];
    const props = [{ id: 'p1' }] as unknown as Proposal[];
    const n = computeNeeds(GRAPH, props, runs, now);
    expect(n.review.map(x => x.id)).toEqual(['dec.open', 'claim.x']);
    expect(n.decisions.map(d => d.node.id)).toEqual(['dec.open']);
    expect(n.decisions[0].options.map(o => o.id)).toEqual(['sol.a', 'sol.b']);     // the abandoned one is not an option
    expect(n.fix).toEqual(['claim.x']);
    expect(n.rerun).toEqual({ ids: ['exp.e1'], gpuH: 2.5 });
    expect(n.failed.map(r => r.id)).toEqual(['r-new']);
    expect(needsCount(n)).toBe(1 + 1 + 1 + 1 + 1 + 1);
  });

  it('a decision is open until its choice names a live node', () => {
    const byId = new Map(NODES.filter(n => n.status !== 'abandoned').map(n => [n.id, n]));
    expect(isOpenDecision(NODES[3], byId)).toBe(true);
    expect(isOpenDecision(NODES[4], byId)).toBe(false);
    expect(decisionOptions(NODES[4], byId).map(o => o.id)).toEqual(['sol.a']);
  });

  it('lists what waits for evidence or upstream', () => {
    const w = computeWaiting(GRAPH);
    expect(w.evidence.map(n => n.id)).toEqual(['claim.x']);
    expect(w.blocked).toEqual(['exp.e2']);
  });
});

describe('steps', () => {
  const gate = (g: string, state: GateStatus['state'], ok: boolean[]): GateStatus => ({
    gate: g, after: 'S1', title: { en: g, zh: g }, state, checks: ok.map((v, i) => ({ label: `${g}.${i}`, ok: v })),
  });
  it('maps stages to the four steps', () => {
    expect(stepOfStage('motivation')).toBe('insight');
    expect(stepOfStage('writing')).toBe('evaluation');
    expect(stepOfStage(undefined)).toBe('idea');
    expect(stepOfDag('S4')).toBe('insight');
    expect(stepOfDag('W')).toBe('evaluation');
    expect(nextStage('insight')).toBe('design');
    expect(nextStage('evaluation')).toBeNull();
  });
  it('counts the open checks of this step and the earlier ones', () => {
    const gates = [gate('G1', 'passed', [true]), gate('G2', 'failing', [true, false]), gate('G3', 'open', [true]), gate('G4', 'failing', [false, false]), gate('G5', 'failing', [false])];
    const out = leaving('insight', gates);
    expect(out.gates.map(g => g.gate)).toEqual(['G2', 'G3', 'G4']);
    expect(out.missing.map(m => m.label)).toEqual(['G2.1', 'G4.0', 'G4.1']);
    expect(leaving('idea', gates).missing).toEqual([]);
  });
});
