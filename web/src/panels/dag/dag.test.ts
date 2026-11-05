// Pure parts of the map: layout determinism and lane structure, drawable edges, attempts, supersede chains, cell grids,
// the filters, and impact categories.
import { describe, expect, it } from 'vitest';
import type { DagNode, GraphResponse, Impact, NodeEval } from '../../dag-types';
import { impactCategories, lockCheckItems, primaryCategory, whyPathNodes } from '../../dag/ImpactView';
import { groupBox, layoutMap, MAIN_LANES, type LayoutNode } from './layout';
import {
  altGroups, cellGrid, collectEdges, edgeMoved, filterMembers, legacyFilter, parseCell, supersedeChains, verdictsByNode,
} from './model';
import { nodeSize, shapePath } from './shapes';

const node = (id: string, kind: DagNode['kind'], stage: DagNode['stage'], extra: Partial<DagNode> = {}): DagNode => ({
  id, kind, stage, title: { en: id }, status: 'active', head: { rev: 1, vid: `v-${id}`, fp: 's:0' }, facets: {}, edges: [], ...extra,
});

const NODES: DagNode[] = [
  node('prob.ttft', 'problem', 'S0'),
  node('ref.sarathi', 'reference', 'S1'),
  node('data.sharegpt', 'dataset', 'S1'),
  node('gap.interference', 'gap', 'S3', { edges: [{ type: 'basis', to: 'node:prob.ttft', seen: 's:1' }] }),
  node('sol.chunk', 'solution', 'S4', { status: 'confirmed', alt_group: 'gap.interference', edges: [{ type: 'basis', to: 'node:gap.interference', seen: 's:2' }] }),
  node('sol.mlfq', 'solution', 'S4', { status: 'refuted', alt_group: 'gap.interference', edges: [{ type: 'evidence', to: 'run:r-1#out.gain', polarity: 'refutes' }] }),
  node('sol.disagg', 'solution', 'S4', { status: 'abandoned', alt_group: 'gap.interference' }),
  node('design.sched', 'design', 'S5', { status: 'locked', edges: [{ type: 'basis', to: 'node:sol.chunk#mechanism', seen: 's:3' }] }),
  node('mod.sched', 'module', 'S5', { edges: [
    { type: 'implements', to: 'node:design.sched#policy', seen: 's:4' },
    { type: 'implements', to: 'node:design.sched#preemption', seen: 's:5' },
  ] }),
  node('exp.e2e', 'experiment', 'S6', { facets: { spec: { type: 'json', value: { command: 'x', overrides: { workload: 'sharegpt' }, sweep: { system: ['vllm', 'sarathi', 'ours'], rate: [4, 8, 16] } } } },
    edges: [{ type: 'input', to: 'node:data.sharegpt' }] }),
  node('exp.proto-mlfq', 'experiment', 'S4'),
  node('claim.ttft-2x', 'claim', 'S6', { edges: [{ type: 'evidence', to: 'node:exp.e2e#out.speedup[system=ours]', polarity: 'supports', predicate: { agg: 'min', op: '>=', rhs: 2 }, seen: 't:1' }] }),
  node('sec.design', 'section', 'W', { edges: [{ type: 'describes', to: 'node:design.sched#preemption', seen: 's:5' }] }),
];
const CELLS = ['rate=4,system=ours', 'rate=8,system=ours', 'rate=16,system=ours', 'rate=4,system=vllm', 'rate=8,system=vllm', 'rate=16,system=vllm'];
const EVAL: Record<string, NodeEval> = {
  'mod.sched': { level: 'review', archived: false, reasons: [{ level: 'review', edge: 'implements:node:design.sched#preemption', from: 's:5', to: 's:9' }], flags: [], shaky: [] },
  'exp.e2e': { level: 'stale', archived: false, reasons: [], flags: [], shaky: [], cells: Object.fromEntries(CELLS.map((c, i) => [c, { level: i < 3 ? 'stale' : 'fresh', run: null, reused: false, why: [] }])) },
  'claim.ttft-2x': { level: 'pending', archived: false, reasons: [], flags: [], shaky: ['exp.e2e'] },
};
const RUN_NODE = new Map([['r-1', 'exp.proto-mlfq']]);

function layoutInput(nodes: DagNode[]) {
  const ln: LayoutNode[] = nodes.map(n => ({ id: n.id, stage: n.stage, rail: n.kind === 'reference' || n.kind === 'dataset', ...nodeSize(n, { cells: n.kind === 'experiment' ? CELLS : [] }) }));
  const edges = collectEdges(nodes, EVAL, RUN_NODE);
  const groups = altGroups(nodes).map(g => ({ id: g.id, members: g.members }));
  return { ln, edges, groups };
}

describe('layout', () => {
  it('is deterministic and independent of input order', () => {
    const a = layoutInput(NODES), b = layoutInput([...NODES].reverse());
    const la = layoutMap(a.ln, a.edges, a.groups, { railCollapsed: false });
    const lb = layoutMap(b.ln, b.edges, b.groups, { railCollapsed: false });
    expect(la.pos).toEqual(lb.pos);
    expect(la).toEqual(layoutMap(a.ln, a.edges, a.groups, { railCollapsed: false }));
  });

  it('places every node inside its lane, rail on top, W at the bottom', () => {
    const { ln, edges, groups } = layoutInput(NODES);
    const l = layoutMap(ln, edges, groups, { railCollapsed: false });
    for (const n of NODES) {
      const b = l.pos[n.id];
      expect(b, n.id).toBeTruthy();
      if (n.kind === 'reference' || n.kind === 'dataset') { expect(b.y + b.h).toBeLessThanOrEqual(l.rail.h); continue; }
      const lane = l.lanes[n.stage];
      expect(b.x).toBeGreaterThanOrEqual(lane.x);
      expect(b.x + b.w).toBeLessThanOrEqual(lane.x + lane.w + 0.01);
      expect(b.y).toBeGreaterThanOrEqual(lane.y);
      expect(b.y + b.h).toBeLessThanOrEqual(lane.y + lane.h + 0.01);
    }
    // lanes are concatenated left to right without gaps
    for (let i = 1; i < MAIN_LANES.length; i++) expect(l.lanes[MAIN_LANES[i]].x).toBeCloseTo(l.lanes[MAIN_LANES[i - 1]].x + l.lanes[MAIN_LANES[i - 1]].w);
    expect(l.lanes.W.y).toBeGreaterThanOrEqual(l.lanes.S0.y + l.lanes.S0.h);
  });

  it('keeps an alt group together inside its bracket, without overlaps', () => {
    const { ln, edges, groups } = layoutInput(NODES);
    const l = layoutMap(ln, edges, groups, { railCollapsed: false });
    const box = l.groups['gap.interference'];
    expect(box).toBeTruthy();
    for (const id of ['sol.chunk', 'sol.mlfq', 'sol.disagg']) {
      const b = l.pos[id];
      expect(b.x).toBeGreaterThanOrEqual(box.x); expect(b.y).toBeGreaterThanOrEqual(box.y);
      expect(b.x + b.w).toBeLessThanOrEqual(box.x + box.w); expect(b.y + b.h).toBeLessThanOrEqual(box.y + box.h);
    }
    expect(groupBox(['sol.chunk', 'sol.mlfq', 'sol.disagg'].map(id => l.pos[id]))).toEqual(box);
    const boxes = Object.values(l.pos);
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      expect(overlap).toBe(false);
    }
  });

  it('collapses the rail to a bar and drops its nodes', () => {
    const { ln, edges, groups } = layoutInput(NODES);
    const l = layoutMap(ln, edges, groups, { railCollapsed: true });
    expect(l.rail.h).toBeGreaterThan(0);
    expect(l.pos['ref.sarathi']).toBeUndefined();
    expect(l.lanes.S0.y).toBe(l.rail.h);
  });

  it('copes with 150 nodes', () => {
    const many: DagNode[] = Array.from({ length: 150 }, (_, i) => node(`find.n${i}`, 'finding', MAIN_LANES[i % 7], { edges: i > 7 ? [{ type: 'basis', to: `node:find.n${i - 7}`, seen: 's' }] : [] }));
    const { ln, edges, groups } = layoutInput(many);
    const t0 = performance.now();
    const l = layoutMap(ln, edges, groups, { railCollapsed: false });
    expect(Object.keys(l.pos)).toHaveLength(150);
    expect(performance.now() - t0).toBeLessThan(1500);
  });
});

describe('model', () => {
  it('draws upstream → consumer edges, merges facets, resolves run: through runs, flags moved edges', () => {
    const edges = collectEdges(NODES, EVAL, RUN_NODE);
    const impl = edges.find(e => e.type === 'implements')!;
    expect(impl).toMatchObject({ source: 'design.sched', target: 'mod.sched' });
    expect(impl.edges).toHaveLength(2);
    expect(impl.moved.map(m => m.facet)).toEqual(['preemption']);
    const frozen = edges.find(e => e.target === 'sol.mlfq')!;
    expect(frozen).toMatchObject({ source: 'exp.proto-mlfq', polarity: 'refutes', frozen: true });
    expect(edges.find(e => e.type === 'input')).toMatchObject({ source: 'data.sharegpt', target: 'exp.e2e' });
    expect(edgeMoved(EVAL['mod.sched'], NODES.find(n => n.id === 'mod.sched')!.edges[0])).toBeNull();
  });

  it('orders attempts chosen first and counts the dead', () => {
    const [g] = altGroups(NODES);
    expect(g.id).toBe('gap.interference');
    expect(g.members[0]).toBe('sol.chunk');
    expect(g.chosen).toEqual(['sol.chunk']);
    expect(new Set(g.dead)).toEqual(new Set(['sol.mlfq', 'sol.disagg']));
  });

  it('folds supersede chains into their live head, newest first', () => {
    const chain = [
      node('design.a', 'design', 'S5', { status: 'superseded', superseded_by: 'design.b' }),
      node('design.b', 'design', 'S5', { status: 'superseded', superseded_by: 'design.c' }),
      node('design.c', 'design', 'S5'),
    ];
    expect(supersedeChains(chain).get('design.c')).toEqual(['design.b', 'design.a']);
  });

  it('builds a system × rate matrix for two-key sweeps', () => {
    expect(parseCell('rate=8,system=ours')).toEqual({ rate: '8', system: 'ours' });
    expect(parseCell('_')).toEqual({});
    const g = cellGrid(CELLS);
    expect(g.rowKey).toBe('system');
    expect(g.colKey).toBe('rate');
    expect(g.rows).toEqual([['rate=4,system=ours', 'rate=8,system=ours', 'rate=16,system=ours'], ['rate=4,system=vllm', 'rate=8,system=vllm', 'rate=16,system=vllm']]);
    expect(cellGrid(['_']).rows).toEqual([['_']]);
  });

  it('filters the map: drafts, what needs attention, confirmed and abandoned', () => {
    const g = { nodes: [...NODES, node('gap.new', 'gap', 'S3', { status: 'proposed' })], eval: EVAL, lenses: undefined } as unknown as GraphResponse;
    expect(filterMembers(g, 'proposed')).toEqual(new Set(['gap.new']));
    expect(filterMembers(g, 'attention')).toEqual(new Set(['mod.sched', 'exp.e2e', 'claim.ttft-2x']));   // review, rerun, waiting upstream
    expect(filterMembers(g, 'confirmed')).toEqual(new Set(['sol.chunk', 'design.sched']));
    expect(filterMembers(g, 'dead')).toEqual(new Set(['sol.mlfq', 'sol.disagg']));
    expect(filterMembers(g, 'all').has('sol.mlfq')).toBe(false);
    expect(filterMembers(g, 'all').size).toBe(NODES.length + 1 - 2);
    expect(legacyFilter('tried')).toBe('dead');
    expect(legacyFilter('rerun')).toBe('attention');
  });

  it('keeps the latest verdict per node', () => {
    const v = verdictsByNode([
      { e: '1', at: '2026-11-01T00:00:00Z', by: 'human:r', op: 'decision', node: 'sol.mlfq', reason: 'old' },
      { e: '2', at: '2026-11-02T00:00:00Z', by: 'human:r', op: 'decision', node: 'sol.mlfq', reason: 'new' },
      { e: '3', at: '2026-11-03T00:00:00Z', by: 'system', op: 'run_recorded', node: 'sol.mlfq' },
    ]);
    expect(v.get('sol.mlfq')?.reason).toBe('new');
  });
});

describe('shapes', () => {
  it('draws every kind and grows with the outset', () => {
    for (const n of NODES) {
      const { w, h } = nodeSize(n, {});
      expect(shapePath('round', w, h, 0)).toMatch(/^M/);
    }
    for (const s of ['round', 'pill', 'cylinder', 'ticket', 'lozenge', 'rect', 'page'] as const) {
      expect(shapePath(s, 200, 60, 6)).not.toEqual(shapePath(s, 200, 60, 0));
    }
  });
});

describe('impact helpers', () => {
  const impact = {
    base_digest: 'd:1', precision: 'predicted',
    patched: [{ addr: 'node:design.sched#preemption', from: 's:1', to: 's:2' }],
    summary: { rerun: 3, conditional: 1, reused: 6, revived: 0, review: 1, orphaned: 0, broken: 0, lock: 1, gpu_h: { rerun: 1.2, conditional_worst: 0, reused: 2.4, full_campaign: 3.6 } },
    rerun: [{ node: 'exp.e2e', cells: ['rate=4,system=ours'] }], conditional: [{ node: 'claim.ttft-2x' }], reused: [{ node: 'exp.e2e', cells: ['rate=*,system=vllm'] }],
    revived: [], review: [{ node: 'mod.sched' }], orphaned: [], broken: [], lock: [{ node: 'design.sched', kind: 'edit_locked', requires: 'unlock:design.sched' }],
    already_tried: [], suggest_restore: [], gates: [], requires_human: { value: true, reasons: [] },
    why_paths: { 'exp.e2e[rate=4,system=ours]': ['node:design.sched#preemption', 'implements', 'mod.sched', 'glob', 'code:src/sched/policy.py', 'trace'] },
  } as unknown as Impact;

  it('classifies nodes with a precedence for painting', () => {
    const c = impactCategories(impact);
    expect(primaryCategory(c.get('exp.e2e'))).toBe('rerun');
    expect(primaryCategory(c.get('design.sched'))).toBe('patched');
    expect(c.get('design.sched')?.has('lock')).toBe(true);
    expect(primaryCategory(c.get('mod.sched'))).toBe('review');
    expect(c.has('prob.ttft')).toBe(false);
  });

  it('follows why-paths to the nodes they pass through', () => {
    expect(new Set(whyPathNodes(impact, impact.rerun[0]))).toEqual(new Set(['exp.e2e', 'design.sched', 'mod.sched']));
  });

  it('asks to unlock what the change edits and to acknowledge other locks', () => {
    const t = (k: string, v?: Record<string, string | number>) => `${k}:${v?.id ?? ''}`;
    expect(lockCheckItems(impact, undefined, t).map(i => `${i.kind}:${i.id}`)).toEqual(['unlock:design.sched']);
    expect(lockCheckItems(impact, ['unlock:dec.x'], t).map(i => `${i.kind}:${i.id}`)).toEqual(['unlock:dec.x', 'unlock:design.sched']);
  });
});
