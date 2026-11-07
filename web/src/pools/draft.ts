// A pool definition being written in the wizard: its id from the name, a blank one, one for a platform name the
// records use, and what is wrong with it before it can be tested or saved (the server validates again: store.validate).
import type { PoolDef, SourceType } from './api';

const ID_RE = /^[a-z0-9][a-z0-9._-]{0,40}$/;
const CRED_RE = /^(keychain|env):[A-Za-z0-9._-]{1,100}$/;
const HTTP_RE = /^(https:\/\/[^/\s]+|http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$))/;
export const NAME_MAX = 300;

export const DEFAULT_EVERY: Record<SourceType, number> = { manual: 0, local: 10, command: 600, http: 60 };

/** An id from a name: lowercase letters, digits and - _ . ("Lab GPU #2" → "lab-gpu-2"). */
export function slugId(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/\.\.+/g, '.').replace(/^[-._]+|[-._]+$/g, '').slice(0, 41);
}

/** A platform name with its spaces tidied, as the server keeps it. */
export const tidyName = (name: string): string => name.split(/\s+/).filter(Boolean).join(' ');
/** How platform names are compared, as the server does (store.name_key): ignoring case and extra spaces. */
export const nameKey = (name: string): string => tidyName(name).toLowerCase();
/** A platform name that can be a pool's id as it is (ignoring case): "workstation", "cloud-a100". */
export const isIdLike = (name: string): boolean => ID_RE.test(name.toLowerCase()) && !name.includes('..');
/** A description up to its first bracket, colon, semicolon or comma: "8× RTX A6000 (lab node …)" → "8× RTX A6000". */
export const headOf = (name: string): string => tidyName(name.split(/[(（:：;；,，]/)[0]) || tidyName(name);

/** An id for a pool made for a platform name, not one of taken: the name itself when it can be one, else from its
 *  start ("8× RTX A6000 (lab node …)" → "8-rtx-a6000"), with -2, -3 … when needed. */
export function idFor(name: string, taken: string[]): string {
  const base = isIdLike(name) ? name.toLowerCase() : slugId(headOf(name)) || slugId(name) || 'pool';
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let i = 2; ; i++) {
    const id = `${base.slice(0, 38)}-${i}`;
    if (!used.has(id)) return id;
  }
}

export const blank = (id = ''): PoolDef => ({ id, label: id, kind: 'cluster', source: { type: 'command' }, credential: null, prices: [], budget: {} });

/** A new pool for a platform name the records use: the name is its id when it can be, else one of its names. */
export function fromName(name: string, taken: string[]): PoolDef {
  const id = idFor(name, taken);
  const asId = id === name.toLowerCase();
  return { ...blank(id), label: asId ? name : headOf(name).slice(0, 80), ...(asId ? {} : { names: [tidyName(name).slice(0, NAME_MAX)] }) };
}

/** The fields that keep the draft from being tested or saved: id, names, run, url, credential, inventory, prices. */
export function problems(d: PoolDef): string[] {
  const out: string[] = [];
  if (!ID_RE.test(d.id) || d.id.includes('..')) out.push('id');
  if ((d.names ?? []).some(n => !n.trim() || n.length > NAME_MAX)) out.push('names');
  const s = d.source;
  if (s.type === 'command' && (!s.run?.length || s.run.some(a => !a.trim()))) out.push('run');
  if (s.type === 'http' && !HTTP_RE.test(s.url ?? '')) out.push('url');
  if (d.credential && !CRED_RE.test(d.credential)) out.push('credential');
  if (s.type === 'manual' && (s.inventory?.nodes ?? []).some(n => !n.id.trim())) out.push('inventory');
  if (d.prices.some(p => !(p.amount >= 0) || !p.unit.trim())) out.push('prices');
  return out;
}
