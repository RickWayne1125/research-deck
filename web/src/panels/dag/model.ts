// Derived, pure views of the DAG response that the map, lenses, inspector and timeline share: drawable edges
// (consumer → upstream turned into upstream → consumer), alt-group attempts, supersede chains, sweep-cell grids,
// lens membership and per-node verdicts. Nothing here talks to the server.
import { parseAddr } from '../../dag/api';
import { actorKind } from '../../dag/encoding';
import {
  DAG_STAGES, DEAD_STATUSES,
  type DagEdge, type DagEvent, type DagNode, type EdgeType, type Freshness, type GraphResponse, type Lenses,
  type NodeEval, type NodeKind, type NodeStatus, type Reason, type StageKey,
} from '../../dag-types';


export const isDead = (s: NodeStatus) => DEAD_STATUSES.includes(s);
export const isLive = (s: NodeStatus) => !isDead(s);

/** The edge key used by attest / unlink ops and by eval reasons: "<type>:<to address>". */
export const edgeKey = (e: Pick<DagEdge, 'type' | 'to'>) => `${e.type}:${e.to}`;

/** Kinds whose nodes live in the collapsible top rail instead of a stage lane. */
export const RAIL_KINDS: NodeKind[] = ['reference', 'dataset'];

export const ID_PREFIX: Record<NodeKind, string> = {
  problem: 'prob', reference: 'ref', dataset: 'data', experiment: 'exp', finding: 'find', gap: 'gap', solution: 'sol',
  decision: 'dec', design: 'design', module: 'mod', figure: 'fig', claim: 'claim', section: 'sec',
};
export const DEFAULT_STAGE: Record<NodeKind, StageKey> = {
  problem: 'S0', reference: 'S1', dataset: 'S1', experiment: 'S2', finding: 'S2', gap: 'S3', solution: 'S4',
  decision: 'S4', design: 'S5', module: 'S5', figure: 'S6', claim: 'S6', section: 'W',
};

export function stageOf(n: Pick<DagNode, 'stage'>): StageKey {
  return (DAG_STAGES as string[]).includes(n.stage) ? n.stage : 'S0';
}

/** A scripted figure is an action (cells, runs); a drawn one is a belief with a file. */
export function isAction(n: Pick<DagNode, 'kind' | 'facets'>): boolean {
  if (n.kind === 'experiment') return true;
  if (n.kind === 'figure') return !!n.facets?.spec && !n.facets?.tool;
  return false;
}

// ------------------------------------------------------------------ edges

export interface DrawEdge {
  id: string;                      // "<type>|<upstream>|<consumer>"
  type: EdgeType;
  source: string;                  // upstream node id
  target: string;                  // consumer node id (the node that stores the edge)
  edges: DagEdge[];                // the stored edges merged into this drawn one (one per facet)
  moved: { facet: string; reason: Reason }[];   // seen ≠ current, per facet
  polarity?: 'supports' | 'refutes';
  frozen: boolean;                 // points at an immutable run: address
}

/** Reasons on the consumer's eval that concern a given stored edge. */
export function reasonsForEdge(ev: NodeEval | undefined, key: string): Reason[] {
  return (ev?.reasons ?? []).filter(r => r.edge === key);
}

/** True when the consumer's recorded fingerprint for this edge differs from the upstream's current one. */
export function edgeMoved(ev: NodeEval | undefined, e: DagEdge): Reason | null {
  for (const r of reasonsForEdge(ev, edgeKey(e))) {
    if (r.level === 'review' || r.level === 'broken') return r;
    if (r.from != null && r.to != null && r.from !== r.to) return r;
  }
  return null;
}

/** Upstream node id of a stored edge: node:<id>… directly, run:<id>… through the run → node map. */
export function upstreamId(e: DagEdge, runNode: Map<string, string>): string | null {
  const a = parseAddr(e.to);
  if (a.scheme === 'node') return a.id;
  if (a.scheme === 'run') return runNode.get(a.id) ?? null;
  return null;
}

export function facetLabel(addr: string): string {
  const a = parseAddr(addr);
  if (!a.facet) return '';
  return a.selector ? `${a.facet}[${a.selector}]` : a.facet;
}

export function collectEdges(nodes: DagNode[], evals: Record<string, NodeEval>, runNode: Map<string, string>): DrawEdge[] {
  const ids = new Set(nodes.map(n => n.id));
  const out = new Map<string, DrawEdge>();
  for (const n of nodes) {
    for (const e of n.edges ?? []) {
      const up = upstreamId(e, runNode);
      if (!up || up === n.id || !ids.has(up)) continue;
      const id = `${e.type}|${up}|${n.id}`;
      let d = out.get(id);
      if (!d) {
        d = { id, type: e.type, source: up, target: n.id, edges: [], moved: [], frozen: false };
        out.set(id, d);
      }
      d.edges.push(e);
      if (e.polarity) d.polarity = d.polarity === 'refutes' ? 'refutes' : e.polarity;
      if (e.to.startsWith('run:')) d.frozen = true;
      const r = edgeMoved(evals[n.id], e);
      if (r) d.moved.push({ facet: facetLabel(e.to) || e.type, reason: r });
    }
  }
  return [...out.values()].sort((a, b) => a.id.localeCompare(b.id));
}

// ------------------------------------------------------------------ attempts and supersede chains

export interface AltGroup {
  id: string;                      // the alt_group value: the parent node's id (the question these siblings answer)
  members: string[];               // display order: chosen, then live, then dead; ids sorted within each
  chosen: string[];                // confirmed or locked
  dead: string[];
  stage: StageKey;
}

export function altGroups(nodes: DagNode[]): AltGroup[] {
  const by = new Map<string, DagNode[]>();
  for (const n of nodes) if (n.alt_group) by.set(n.alt_group, [...(by.get(n.alt_group) ?? []), n]);
  const rank = (n: DagNode) => (n.status === 'confirmed' || n.status === 'locked' ? 0 : isLive(n.status) ? 1 : 2);
  return [...by.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([id, ms]) => {
    const sorted = [...ms].sort((a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id));
    return {
      id, members: sorted.map(n => n.id),
      chosen: sorted.filter(n => rank(n) === 0).map(n => n.id),
      dead: sorted.filter(n => isDead(n.status)).map(n => n.id),
      stage: stageOf(sorted[0]),
    };
  });
}

/** Supersede chains: head (the live successor at the end) → older ids, newest first. */
export function supersedeChains(nodes: DagNode[]): Map<string, string[]> {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const heads = new Map<string, string[]>();
  for (const n of nodes) {
    if (n.status !== 'superseded' || !n.superseded_by) continue;
    // Follow the chain to its end (guarding against cycles in hand-edited files).
    let cur = n.superseded_by; const seen = new Set([n.id]);
    while (byId.get(cur)?.status === 'superseded' && byId.get(cur)?.superseded_by && !seen.has(cur)) {
      seen.add(cur); cur = byId.get(cur)!.superseded_by!;
    }
    if (!byId.has(cur)) continue;
    heads.set(cur, [...(heads.get(cur) ?? []), n.id]);
  }
  // Newest first: by depth from the head (direct predecessor first).
  for (const [head, ids] of heads) {
    const depth = (id: string) => { let d = 0, c: string | null | undefined = id; while (c && c !== head && d < 50) { c = byId.get(c)?.superseded_by; d++; } return d; };
    ids.sort((a, b) => depth(a) - depth(b) || a.localeCompare(b));
    heads.set(head, ids);
  }
  return heads;
}

// ------------------------------------------------------------------ sweep cells

/** "rate=8,system=ours" → { rate: '8', system: 'ours' }; "_" → {}. */
export function parseCell(cell: string): Record<string, string> {
  if (!cell || cell === '_') return {};
  const out: Record<string, string> = {};
  for (const part of cell.split(',')) {
    const i = part.indexOf('=');
    if (i > 0) out[part.slice(0, i)] = part.slice(i + 1);
  }
  return out;
}

const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

/** Arrange cells for the node mini-grid: a matrix for a two-key sweep, otherwise rows of up to `perRow`. */
export function cellGrid(cells: string[], perRow = 8): { rows: (string | null)[][]; rowKey?: string; colKey?: string } {
  const sorted = [...cells].sort(natural);
  const parsed = sorted.map(parseCell);
  const keys = [...new Set(parsed.flatMap(p => Object.keys(p)))].sort();
  if (keys.length === 2 && sorted.length > 1) {
    // rows = the key with fewer values (systems), columns = the other (rates)
    const vals = keys.map(k => [...new Set(parsed.map(p => p[k]).filter((v): v is string => v != null))].sort(natural));
    const [ri, ci] = vals[0].length <= vals[1].length ? [0, 1] : [1, 0];
    if (vals[ci].length <= perRow) {
      const rows = vals[ri].map(rv => vals[ci].map(cv => {
        const i = parsed.findIndex(p => p[keys[ri]] === rv && p[keys[ci]] === cv);
        return i >= 0 ? sorted[i] : null;
      }));
      return { rows, rowKey: keys[ri], colKey: keys[ci] };
    }
  }
  const rows: string[][] = [];
  for (let i = 0; i < sorted.length; i += perRow) rows.push(sorted.slice(i, i + perRow));
  return { rows };
}

// ------------------------------------------------------------------ filters (the map's chips)

export const FILTERS = ['all', 'proposed', 'attention', 'confirmed', 'dead'] as const;
export type Filter = (typeof FILTERS)[number];
export const isFilter = (v: string | null | undefined): v is Filter => !!v && (FILTERS as readonly string[]).includes(v);

/** Older links named lenses: tried → abandoned, confirmed → confirmed, revise / rerun → needs attention. */
export function legacyFilter(lens: string): Filter {
  return lens === 'tried' ? 'dead' : lens === 'confirmed' ? 'confirmed' : lens === 'revise' || lens === 'rerun' ? 'attention' : 'all';
}

/** The ids a filter shows. all: every live node; proposed: drafts waiting for review; attention: live nodes that are
 *  not fresh (to review, rerun, run or waiting upstream) or that the server lists to revise or rerun; confirmed:
 *  confirmed or locked; dead: refuted, abandoned or superseded. */
export function filterMembers(g: Pick<GraphResponse, 'nodes' | 'eval' | 'lenses'>, f: Filter): Set<string> {
  const listed = new Set([...(g.lenses?.revise.items ?? []), ...(g.lenses?.rerun.items ?? [])].map(i => i.id));
  const out = new Set<string>();
  for (const n of g.nodes) {
    const live = isLive(n.status);
    const level = g.eval[n.id]?.level ?? null;
    const keep = f === 'all' ? live
      : f === 'proposed' ? n.status === 'proposed'
        : f === 'attention' ? live && ((level !== null && level !== 'fresh') || listed.has(n.id))
          : f === 'confirmed' ? n.status === 'confirmed' || n.status === 'locked'
            : !live;
    if (keep) out.add(n.id);
  }
  return out;
}

// ------------------------------------------------------------------ actors and verdicts

/** The last agent that touched the node (for the robot avatar), or null when no agent did. */
export function lastAgent(n: Pick<DagNode, 'updated' | 'created'>): 'claude' | 'codex' | null {
  for (const a of [n.updated, n.created]) {
    const k = actorKind(a?.by);
    if (k === 'claude' || k === 'codex') return k;
    if (k === 'human') return null;
  }
  return null;
}

/** The latest verdict event per node (decision / set_status), used for reason chips and the attempts sidebar. */
export function verdictsByNode(events: DagEvent[]): Map<string, DagEvent> {
  const out = new Map<string, DagEvent>();
  for (const e of events) {
    if (!e.node || !(e.op === 'decision' || e.op === 'set_status')) continue;
    const prev = out.get(e.node);
    if (!prev || prev.at <= e.at) out.set(e.node, e);
  }
  return out;
}

/** A short reason for a node's status (refuted/abandoned/superseded): verdict event, then any field the server sent. */
export function statusReason(n: DagNode, verdict?: DagEvent): string | null {
  const own = (n as unknown as { status_reason?: unknown }).status_reason;
  if (typeof own === 'string' && own) return own;
  if (verdict?.reason) return String(verdict.reason);
  return null;
}

/** Frozen evidence runs on a node (refutations point at immutable run: addresses). */
export function evidenceRuns(n: DagNode): string[] {
  return (n.edges ?? []).filter(e => e.type === 'evidence' && e.to.startsWith('run:')).map(e => parseAddr(e.to).id);
}

// ------------------------------------------------------------------ small formatting helpers

/** Shorten fingerprints ("p:41ac9e07d2b3" → "p:41ac…") and long values for chips. */
export function shortFp(v: unknown): string {
  if (v === null || v === undefined) return '∅';
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  if (/^[a-z]:[0-9a-f]{8,}$/.test(s)) return `${s.slice(0, 6)}…`;
  return s.length > 48 ? `${s.slice(0, 46)}…` : s;
}

export function fmtGpuH(h: number | null | undefined): string {
  if (h === null || h === undefined || !Number.isFinite(h)) return '—';
  return h >= 10 ? h.toFixed(0) : h >= 1 ? h.toFixed(1) : h === 0 ? '0' : h.toFixed(2);
}

export function slug(s: string): string {
  return s.toLowerCase().normalize('NFKD').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
}

export const LEVEL_ORDER: Freshness[] = ['broken', 'stale', 'unbuilt', 'pending', 'orphaned', 'review', 'fresh'];

// ------------------------------------------------------------------ fork as attempt

/**
 * "Fork as attempt" for a knob what-if (docs/DAG.md §9 step 1): a sibling experiment that runs only the cells the edit
 * would rerun, with the edited config keys as overrides, so nothing in the existing graph changes. Sweep keys whose
 * affected cells share one value become plain overrides (system=ours); the others keep only the affected values.
 */
export function nodeTitle(n: Pick<DagNode, 'title' | 'id'>, lang: 'zh' | 'en'): string {
  return (lang === 'zh' ? n.title?.zh || n.title?.en : n.title?.en || n.title?.zh) || n.id;
}
