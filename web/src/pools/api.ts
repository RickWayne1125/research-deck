// Resource pools (docs/API.md § Resource pools): the compute a researcher can run on, each read through rd-pool/1.
// Pools belong to this computer; a project may use only some of them (project.yaml resources.pools).
import { del, get, post, put } from '../api/client';
import type { ExPlatform } from '../panels/experiments/api';

export type SourceType = 'manual' | 'local' | 'command' | 'http';
export type PoolKind = 'local' | 'home' | 'lab' | 'cluster' | 'cloud';
export type PriceItem = 'gpu_hour' | 'node_hour';
export type MatchKey = 'gpu' | 'flavor' | 'node';
export const SOURCE_TYPES: SourceType[] = ['manual', 'local', 'command', 'http'];
export const POOL_KINDS: PoolKind[] = ['local', 'home', 'lab', 'cluster', 'cloud'];
export const MATCH_KEYS: MatchKey[] = ['gpu', 'flavor', 'node'];
export const EVERY_CHOICES = [10, 30, 60, 300, 600, 1800, 3600];

export interface PriceRule { item: PriceItem; match: Partial<Record<MatchKey, string>>; amount: number; unit: string; from?: 'definition' | 'source' }
export interface InventoryGpu { model: string; count: number; mem_total_mib?: number | null }
export interface InventoryNode { id: string; label?: string; status?: string; flavor?: string | null; gpus: InventoryGpu[] }

export interface PoolDef {
  id: string; label: string; kind: PoolKind;
  source: { type: SourceType; run?: string[]; url?: string; every?: number; timeout?: number; inventory?: { nodes: InventoryNode[] } };
  credential: string | null;
  prices: PriceRule[];
  budget: { agent_gpu_hours_per_day?: number; month?: { amount: number; unit: string } };
  note?: string;
}

/** What one GPU-hour costs (pools/service.py rate): free = not billed; unknown and varies have no amount. */
export interface Rate {
  state: 'known' | 'free' | 'unknown' | 'varies'; amount: number | null; unit: string | null; item: PriceItem | null;
  rule_amount: number | null; from: string | null; why: string | null; options?: { amount: number; unit: string | null }[];
}
export type NodePrice = Pick<Rate, 'state' | 'amount' | 'unit' | 'item' | 'rule_amount' | 'from'>;

export interface PoolCredential { ref: string | null; expires_at: string | null; days_left: number | null; state: 'ok' | 'soon' | 'expired' | null }
export interface PoolInfo {
  state: 'ok' | 'stale' | 'failed' | 'reading'; here: boolean; source: PoolDef['source'];
  read_at: string | null; age_s: number | null; tried_at: string | null; error: string | null; warnings: string[];
  duration_s: number | null; reading: boolean; capabilities: string[]; credential: PoolCredential | null; billed: boolean;
  prices: PriceRule[]; rate: Rate;
  budget: { agent_gpu_hours_per_day: number | null; agent_used_today: number | null; month: { amount: number; unit: string } | null };
}
export type PoolPlatform = ExPlatform & { pool: PoolInfo };
export interface PoolView { def: PoolDef; platform: PoolPlatform }
export interface PoolList {
  pools: PoolView[]; selection: string[] | null; unmatched: string[]; broken: { file: string; error: string }[];
  dir: string; adapters: string; python: string;
}

/** A normalized rd-pool/1 document (what a source returned). */
export interface PoolDoc {
  protocol: string; as_of: string | null;
  nodes: { id: string; label: string; status: string; state: string | null; flavor: string | null; running: string[]; queued: number | null;
    gpus: { model: string; count: number; mem_total_mib: number | null; util: number | null }[]; cpu: number | null; ram: number | null }[];
  quota: { name: string; used: number | null; limit: number | null; unit: string | null }[];
  spend: { amount: number | null; unit: string; since: string | null; kind: 'billed' | 'estimate' } | null;
  prices: PriceRule[]; credential: { expires_at: string | null }; capabilities: string[];
}
export interface TestResult {
  ok: boolean; error?: string; duration_s: number; warnings?: string[]; doc?: PoolDoc; raw?: string; raw_truncated?: boolean;
  platform?: PoolPlatform;
}

const enc = encodeURIComponent;
const q = (project?: string | null) => (project ? `?project=${enc(project)}` : '');

export const poolApi = {
  list: (project?: string | null) => get<PoolList>('/api/pools', { project }),
  get: (id: string, project?: string | null) => get<PoolView & { yaml: string }>(`/api/pools/${enc(id)}`, { project }),
  save: (def: PoolDef, project?: string | null) => put<PoolView>(`/api/pools/${enc(def.id)}${q(project)}`, def),
  remove: (id: string) => del<{ trashed: string }>(`/api/pools/${enc(id)}`),
  refresh: (id: string, project?: string | null) => post<PoolView>(`/api/pools/${enc(id)}/refresh`, {}, { project }),
  test: (def: PoolDef) => post<TestResult>('/api/pools/test', def),
  parse: (text: string) => post<{ def: PoolDef; exists: boolean }>('/api/pools/parse', { text }),
  setSelection: (pid: string, pools: string[] | null) => put<{ selection: string[] | null }>(`/api/projects/${enc(pid)}/pools`, { pools }),
};

/** "Add this computer": a pool that reads this machine; not billed, agents may not queue there. */
export const thisComputer = (label: string): PoolDef => ({
  id: 'local', label, kind: 'local', source: { type: 'local', every: 10 }, credential: null, prices: [], budget: { agent_gpu_hours_per_day: 0 },
});
