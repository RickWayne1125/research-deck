// Experiments panel calls (docs/API.md § Experiments and resources) and the extra fields the backend adds to the
// shared types. Records are project-scoped; resources are the machine's resource pools (pools/api.ts).
import { get, p, patch, post } from '../../api/client';
import type { Experiment, ExperimentStatus, Freshness, GpuInfo, Platform, ResourceNode, Resources } from '../../types';
import type { NodePrice, PoolInfo } from '../../pools/api';

export type ExFreshness = Experiment['freshness'];
export const EX_STATUSES: ExperimentStatus[] = ['planned', 'queued', 'running', 'succeeded', 'failed', 'cancelled', 'unknown'];
export const EX_FRESHNESS: ExFreshness[] = ['stale', 'fresh', 'reusable', 'unknown'];
export const LIVE_STATUSES: ExperimentStatus[] = ['queued', 'running', 'unknown'];

export interface ExRecord extends Experiment {
  cell?: string | null; dag_cell?: string | null; run_id?: string | null; logs?: string | null;
  dag_level?: Freshness | null; notes?: string | null;
  code: Experiment['code'] & { footprint_source?: 'trace'; declared_footprint?: string[] };
  created?: { by: string; at: string }; updated?: { by: string; at: string };
}

export interface LogPage {
  lines: string[]; next: number; size: number; eof: boolean; source: 'file' | 'none';
  path?: string; missing?: boolean; truncated_before?: boolean; reset?: boolean; error?: string;
}

export type ExGpu = GpuInfo & { key?: string | null; reserved?: boolean; mem_unit?: 'MiB'; demo?: boolean };
export interface ExNode extends Omit<ResourceNode, 'gpus'> {
  gpus: ExGpu[]; demo?: boolean; agent?: boolean; inventory_only?: boolean; state?: string | null; size?: string | null;
  telemetry_at?: string | null; telemetry_age_s?: number | null; stale?: boolean; scope?: string | null; queued?: number | null;
  note_key?: string; simulated?: boolean;
  flavor?: string | null; price?: NodePrice;        // resource pools: the machine's flavor and its price
}
export interface QuotaItem { name: string; current: number | string | null; limit: number | string | null; unit: string }
export type ExCost = NonNullable<Platform['cost']> & { metric?: string; source?: string; source_key?: string; delay_note?: string | null; demo?: boolean; simulated?: boolean; since?: string | null };
export interface ExPlatform extends Omit<Platform, 'nodes' | 'cost'> {
  nodes: ExNode[]; cost?: ExCost | null; demo?: boolean; note_key?: string; quota_items?: QuotaItem[]; quota_note?: string | null; quota_note_key?: string;
  provider_kind?: string; checked_at?: string | null; simulated?: boolean;
  pool?: PoolInfo;                                   // set when the platform is a resource pool (source "pools")
}
export interface ExResources extends Omit<Resources, 'platforms'> {
  platforms: ExPlatform[]; demo?: boolean;
  alerts?: { level: string; kind: string; message: string }[];
  selection?: string[] | null; unmatched?: string[];   // resource pools: the project's choice, names no pool answers to
}

export interface NewExperiment {
  title: string; node_id?: string | null; command?: string | null; config: Record<string, unknown>;
  target: { platform: string; node: string; gpus: number; gpu_type?: string | null };
}

const ex = (pid: string, rest = '') => p(pid, `/experiments${rest}`);
const enc = encodeURIComponent;

export const exApi = {
  list: (pid: string) => get<ExRecord[]>(ex(pid)),
  get: (pid: string, eid: string) => get<ExRecord>(ex(pid, `/${enc(eid)}`)),
  create: (pid: string, body: NewExperiment) => post<ExRecord>(ex(pid), body),
  patch: (pid: string, eid: string, body: Partial<ExRecord>) => patch<ExRecord>(ex(pid, `/${enc(eid)}`), body),
  logs: (pid: string, eid: string, offset: number) => get<LogPage>(ex(pid, `/${enc(eid)}/logs`), { offset }),
  /** SSE of the raw log as it grows (logStream.ts); offset < 0 starts from the tail. */
  logStreamUrl: (pid: string, eid: string, offset: number) => `${ex(pid, `/${enc(eid)}/logs/stream`)}?offset=${offset}`,
  /** The whole log (at most its last 20 MB) as a text/plain attachment. */
  logRawUrl: (pid: string, eid: string) => ex(pid, `/${enc(eid)}/logs/raw`),
  /** The resource pools as platforms, for a project (whether it uses each); example: the labeled demo data instead. */
  resources: (project?: string | null, example = false) => get<ExResources>('/api/resources', { project, demo: example ? 1 : undefined }),
};
