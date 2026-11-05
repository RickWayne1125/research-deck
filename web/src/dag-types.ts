// Research DAG JSON shapes (docs/DAG.md §2, §5, §7). The backend (server/research_deck/dag/) is the source of truth.

export type StageKey = 'S0' | 'S1' | 'S2' | 'S3' | 'S4' | 'S5' | 'S6' | 'W';
export const DAG_STAGES: StageKey[] = ['S0', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'W'];

export type NodeKind =
  | 'problem' | 'reference' | 'dataset' | 'experiment' | 'finding' | 'gap' | 'solution'
  | 'decision' | 'design' | 'module' | 'figure' | 'claim' | 'section';
export const ACTION_KINDS: NodeKind[] = ['experiment', 'figure'];   // figure only when scripted

export type NodeStatus = 'proposed' | 'active' | 'confirmed' | 'locked' | 'refuted' | 'abandoned' | 'superseded';
export const DEAD_STATUSES: NodeStatus[] = ['refuted', 'abandoned', 'superseded'];

export type Freshness = 'fresh' | 'review' | 'orphaned' | 'pending' | 'unbuilt' | 'stale' | 'broken';
export const FRESHNESS_LEVEL: Record<Freshness, number> = { fresh: 0, review: 1, orphaned: 2, pending: 3, unbuilt: 4, stale: 4, broken: 5 };

export type NodeFlag = 'drift' | 'shaky' | 'impl_lag' | 'reused' | 'cutoff' | 'lock_alert' | 'unsealed' | 'behind_head' | 'conflict' | 'trace_quality';
export type EdgeType = 'input' | 'evidence' | 'basis' | 'implements' | 'describes' | 'cites';

export interface Predicate { agg: 'min' | 'max' | 'mean' | 'all' | 'any'; op: '>=' | '<=' | '>' | '<' | '=='; rhs: number }

export interface Reason {
  level: Freshness; edge?: string; addr?: string; from?: string | null; to?: string | null;
  value?: number | null; note?: string;
}
export interface CellEval {
  level: Freshness; run: string | null; reused: boolean; cutoff?: boolean; impl_lag?: boolean;
  why: Reason[]; gpu_h?: number | null; platform?: string | null; provisional?: boolean;
}
export interface NodeEval {
  level: Freshness | null;          // null for nodes with nothing to evaluate
  archived: boolean;                // dead (refuted / abandoned / superseded)
  reasons: Reason[];
  flags: string[];                  // NodeFlag values (strings so new flags do not break old clients)
  shaky: string[];                  // ids of not-fresh nodes this one rests on (soft/evidence), shown as "via X"
  cells?: Record<string, CellEval>; // action nodes: one entry per sweep cell ("_" when there is no sweep)
  values?: Record<string, number | null>;  // evidence / binding values for beliefs (actual numbers)
}

export interface DagEdge {
  type: EdgeType; to: string;       // address: node:<id>[#facet[selector]] | run:<id>#out.<name>
  seen?: string; pin?: string;
  polarity?: 'supports' | 'refutes';
  predicate?: Predicate; kill_if?: Predicate;
}
export interface Facet { type: 'prose' | 'text' | 'json' | 'bound' | 'artifact' | 'derived'; value?: unknown; bind?: string }
export interface Actor { by: string; at: string; via?: string }   // by: human:<name> | agent:<claude|codex>:<session> | system
export interface DagNode {
  id: string; kind: NodeKind; stage: StageKey; purpose?: string;
  title: { en?: string; zh?: string };
  status: NodeStatus;
  head: { rev: number; vid: string; fp: string };
  facets: Record<string, Facet>;
  edges: DagEdge[];
  alt_group?: string | null; superseded_by?: string | null;
  lock?: { by: string; at: string; vid: string; fp: string; tag?: string; reason?: string } | null;
  selected?: Record<string, string>;
  notes?: string; created?: Actor; updated?: Actor;
}

export interface GraphResponse {
  nodes: DagNode[];
  eval: Record<string, NodeEval>;
  lenses: Lenses;
  digest: string;
  at?: string | null;               // set when the graph is a past state (read-only)
  stage_mode?: 'strict' | 'ahead' | 'free';   // how the map grows step by step (dag/stages.py)
}

export interface LensItem { id: string; cells?: string[]; note?: string }
export interface Lenses {
  tried: { count: number; dead: number; runs: number; items: LensItem[] };
  confirmed: { count: number; shaky: number; items: LensItem[] };
  revise: { count: number; items: LensItem[] };
  rerun: { count: number; gpu_h: number; blocked: number; conditional: number; reused_cells: number; reused_gpu_h: number; items: LensItem[] };
}

export interface Version {
  vid: string; rev: number; parent: string | null; reverts?: string | null; fp: string;
  facets: Record<string, unknown>; edges: DagEdge[]; status: NodeStatus;
  by: string; at: string; git?: string | null; op: string; via?: string | null;
  diff?: { facet: string; from: unknown; to: unknown }[];
}

export interface RunSummary {
  id: string; node: string; cell: string; state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'lost';
  by: string; platform: string | null; started: string | null; ended: string | null; gpu_hours: number | null;
  trace_quality?: 'traced' | 'declared' | 'coarse'; excluded?: { by: string; reason: string } | null;
  outputs?: Record<string, { value: unknown; unit?: string; cutoff?: boolean }>;
  experiment?: string | null; git?: { head: string | null; snapshot: string | null; dirty: boolean } | null;
  footprint?: string[];
}

export interface NodeDetail extends DagNode {
  eval: NodeEval;
  history: Version[];
  runs: Record<string, RunSummary[]>;      // per cell, newest first
  dependents: { id: string; edge: EdgeType }[];
}

export interface WhyChain { cell?: string | null; level: Freshness; steps: { addr: string; from?: string | null; to?: string | null; note?: string }[]; text: string }

export type Op = Record<string, unknown> & { op: string };

export interface ImpactItem {
  node: string; cells?: string[]; why?: Reason[] | { addr: string; from?: string | null; to?: string | null }[];
  reason?: string; est_gpu_h?: number; platform?: string | null; impl_lag?: boolean;
  edge?: string; diff?: string; predicate?: string; current?: number | null; margin?: number | null;
  via?: string[]; kind?: string; requires?: string; run?: string; age?: string; note?: string;
}
export interface Impact {
  base_digest: string;
  precision: 'exact' | 'predicted';
  patched: { addr: string; from: string | null; to: string | null; via?: string }[];
  summary: {
    rerun: number; conditional: number; reused: number; revived: number; review: number; orphaned: number; broken: number; lock: number;
    gpu_h: { rerun: number; conditional_worst: number; reused: number; full_campaign: number };
    usd?: { rerun: number };
  };
  rerun: ImpactItem[]; conditional: ImpactItem[]; reused: ImpactItem[]; revived: ImpactItem[];
  review: ImpactItem[]; orphaned: ImpactItem[]; broken: ImpactItem[]; lock: ImpactItem[];
  already_tried: ImpactItem[]; suggest_restore: (ImpactItem & { op?: Op })[];
  gates: { gate: string; from: string; to: string }[];
  requires_human: { value: boolean; reasons: string[] };
  why_paths: Record<string, string[]>;
  errors?: string[];
}

export interface Proposal {
  id: string; by: string; at: string; state: 'open' | 'applied' | 'rejected' | 'withdrawn' | 'needs_rebase';
  title: string; rationale?: string; ops: Op[]; requires: string[]; base_digest: string; impact: Impact | null;
  decided?: { by: string; at: string; reason?: string } | null;
}

export interface OpsResult { applied: boolean; events?: DagEvent[]; proposal?: Proposal; eval_delta?: Record<string, NodeEval> }

export interface DagEvent {
  e: string; at: string; by: string; op: string; node?: string | null; cell?: string | null; run?: string | null;
  kind?: string; reason?: string; summary?: string; vid?: string; [k: string]: unknown;
}

export interface GateCheck { key?: string; label: string; zh?: string; ok: boolean; value?: string | number | null; target?: string | number | null; items?: string[] }
export interface GateStatus { gate: string; after: StageKey; title: { en: string; zh: string }; state: 'open' | 'passed' | 'passed_degraded' | 'failing'; checks: GateCheck[]; passed?: { by: string; at: string; snapshot: string } | null }

export interface Snapshot { name: string; at: string; by: string; git: string | null; nodes: Record<string, string>; runs: Record<string, string>; note?: string }

export interface RunPlan { waves: { node: string; cell: string; est_gpu_h: number | null; platform: string | null; blocked?: string | null }[][]; gpu_h: number; usd: number }
