// Typed client for the research DAG routes (docs/DAG.md §7). All panels go through these, never raw paths.
import { get, p, post } from '../api/client';
import type {
  DagEvent, GateStatus, GraphResponse, Impact, Lenses, NodeDetail, Op, OpsResult, Proposal, RunPlan, RunSummary, Snapshot, Version, WhyChain,
} from '../dag-types';

const d = (pid: string, rest: string) => p(pid, `/dag${rest}`);
const enc = encodeURIComponent;

export const dagApi = {
  graph: (pid: string, q?: { at?: string; lens?: string; dead?: boolean }) =>
    get<GraphResponse>(d(pid, '/graph'), { at: q?.at, lens: q?.lens, dead: q?.dead ? 1 : undefined }),
  node: (pid: string, id: string) => get<NodeDetail>(d(pid, `/nodes/${enc(id)}`)),
  explain: (pid: string, id: string, cell?: string) => get<WhyChain[]>(d(pid, `/nodes/${enc(id)}/explain`), { cell }),
  history: (pid: string, id: string) => get<Version[]>(d(pid, `/nodes/${enc(id)}/history`)),
  ops: (pid: string, ops: Op[], opts?: { base_digest?: string; rationale?: string }) => post<OpsResult>(d(pid, '/ops'), { ops, ...opts }),
  impact: (pid: string, body: { ops?: Op[]; code?: Record<string, unknown>; touch_code?: string[]; explain?: boolean }) =>
    post<Impact>(d(pid, '/impact'), { explain: true, ...body }),
  proposals: (pid: string, state?: string) => get<Proposal[]>(d(pid, '/proposals'), { state }),
  propose: (pid: string, body: { title: string; rationale?: string; ops: Op[] }) => post<Proposal>(d(pid, '/proposals'), body),
  approve: (pid: string, id: string, ops?: number[]) => post<OpsResult>(d(pid, `/proposals/${enc(id)}/approve`), { ops }),
  reject: (pid: string, id: string, reason: string) => post<Proposal>(d(pid, `/proposals/${enc(id)}/reject`), { reason }),
  lock: (pid: string, id: string, reason: string) => post(d(pid, `/nodes/${enc(id)}/lock`), { reason }),
  unlock: (pid: string, id: string, reason: string) => post(d(pid, `/nodes/${enc(id)}/unlock`), { reason }),
  runs: (pid: string, q?: { node?: string; cell?: string }) => get<RunSummary[]>(d(pid, '/runs'), q),
  plan: (pid: string, body?: { targets?: string[]; conditional?: boolean }) => post<RunPlan>(d(pid, '/runs/plan'), body ?? {}),
  queue: (pid: string, body: { cells: { node: string; cell: string }[]; platform: string; confirm: true }) =>
    post<{ experiments: string[] }>(d(pid, '/runs/queue'), body),
  exclude: (pid: string, runId: string, reason: string) => post<RunSummary>(d(pid, `/runs/${enc(runId)}/exclude`), { reason }),
  select: (pid: string, node: string, cell: string, run_id: string | null) => post(d(pid, '/cells/select'), { node, cell, run_id }),
  lenses: (pid: string) => get<Lenses>(d(pid, '/lenses')),
  timeline: (pid: string, q?: { since?: string; node?: string; actor?: string }) => get<DagEvent[]>(d(pid, '/timeline'), q),
  snapshots: (pid: string) => get<Snapshot[]>(d(pid, '/snapshots')),
  snapshot: (pid: string, name: string, note?: string) => post<Snapshot>(d(pid, '/snapshots'), { name, note }),
  restore: (pid: string, name: string) => post<Proposal>(d(pid, `/snapshots/${enc(name)}/restore`)),
  gates: (pid: string) => get<GateStatus[]>(d(pid, '/gates')),
  passGate: (pid: string, gate: string, note?: string) => post<Snapshot>(d(pid, `/gates/${enc(gate)}/pass`), { note }),
  check: (pid: string) => get<Record<string, unknown>>(d(pid, '/check')),
  paperSync: (pid: string) => post<Record<string, unknown>>(d(pid, '/paper/sync')),
};

/** "node:exp.e7#out.ttft[system=ours]" → { scheme: 'node', id: 'exp.e7', facet: 'out.ttft', selector: 'system=ours' } */
export function parseAddr(addr: string): { scheme: string; id: string; facet?: string; selector?: string } {
  const m = addr.match(/^([a-z]+):([^#]+)(?:#([^[]+)(?:\[(.*)\])?)?$/);
  if (!m) return { scheme: '', id: addr };
  return { scheme: m[1], id: m[2], facet: m[3], selector: m[4] };
}
