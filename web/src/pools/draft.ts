// A pool definition being written in the wizard: its id from the name, a blank one, and what is wrong with it before
// it can be tested or saved (the server validates again: store.validate).
import type { PoolDef, SourceType } from './api';

const ID_RE = /^[a-z0-9][a-z0-9._-]{0,40}$/;
const CRED_RE = /^(keychain|env):[A-Za-z0-9._-]{1,100}$/;
const HTTP_RE = /^(https:\/\/[^/\s]+|http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$))/;

export const DEFAULT_EVERY: Record<SourceType, number> = { manual: 0, local: 10, command: 600, http: 60 };

/** An id from a name: lowercase letters, digits and - _ . ("Lab GPU #2" → "lab-gpu-2"). */
export function slugId(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/\.\.+/g, '.').replace(/^[-._]+|[-._]+$/g, '').slice(0, 41);
}

export const blank = (id = ''): PoolDef => ({ id, label: id, kind: 'cluster', source: { type: 'command' }, credential: null, prices: [], budget: {} });

/** The fields that keep the draft from being tested or saved: id, run, url, credential, inventory, prices. */
export function problems(d: PoolDef): string[] {
  const out: string[] = [];
  if (!ID_RE.test(d.id) || d.id.includes('..')) out.push('id');
  const s = d.source;
  if (s.type === 'command' && (!s.run?.length || s.run.some(a => !a.trim()))) out.push('run');
  if (s.type === 'http' && !HTTP_RE.test(s.url ?? '')) out.push('url');
  if (d.credential && !CRED_RE.test(d.credential)) out.push('credential');
  if (s.type === 'manual' && (s.inventory?.nodes ?? []).some(n => !n.id.trim())) out.push('inventory');
  if (d.prices.some(p => !(p.amount >= 0) || !p.unit.trim())) out.push('prices');
  return out;
}
