// Prices, costs and budgets as text. Units are never added together; an unknown price is said, never shown as 0.
import type { TFunc } from '../i18n';
import type { CellCost } from '../types';
import type { ExPlatform } from '../panels/experiments/api';
import type { PoolDef, PoolInfo, PriceRule, Rate } from './api';

/** A currency code (USD, CNY, EUR) as opposed to a quota unit (SU, credits). */
export const isMoney = (unit: string | null | undefined) => !!unit && /^[A-Z]{3}$/.test(unit);

export function num(v: number, lang: string, digits?: number, minDigits = 0): string {
  const max = digits ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 1 ? 2 : 3);
  return new Intl.NumberFormat(lang === 'zh' ? 'zh-CN' : 'en-US', { maximumFractionDigits: max, minimumFractionDigits: Math.min(minDigits, max) }).format(v);
}

/** "0.58 USD", "1.00 USD", "420 USD", "12,400 SU". */
export function amount(v: number, unit: string, lang: string): string {
  return `${isMoney(unit) ? (Math.abs(v) >= 100 ? num(v, lang, 0) : num(v, lang, 2, 2)) : num(v, lang)} ${unit}`;
}

/** Per-unit totals: "0.58 USD + 128 SU" (different units are listed, never summed). */
export function costs(cost: Record<string, number> | null | undefined, lang: string): string {
  const parts = Object.entries(cost ?? {}).filter(([, v]) => v > 0).map(([u, v]) => amount(v, u, lang));
  return parts.join(' + ');
}

/** One rule as written: "0.08 USD / GPU·h", "64 SU / machine·h". */
export function ruleText(r: Pick<PriceRule, 'item' | 'amount' | 'unit'>, t: TFunc, lang: string): string {
  return t(r.item === 'gpu_hour' ? 'pl.perGpuHour' : 'pl.perNodeHour', { v: amount(r.amount, r.unit, lang) });
}

export function matchText(m: PriceRule['match'], t: TFunc): string {
  const parts = Object.entries(m).map(([k, v]) => `${t(`pl.match.${k}`)} ${v}`);
  return parts.length ? parts.join(' · ') : t('pl.match.any');
}

/** A pool's price in a few words: the rule when there is one price, else what is known. */
export function rateText(rate: Rate, t: TFunc, lang: string): string {
  if (rate.state === 'free') return t('pl.free');
  if (rate.state === 'unknown') return t('pl.unknownPrice');
  if (rate.state === 'varies') {
    const units = [...new Set((rate.options ?? []).map(o => o.unit).filter(Boolean))];
    return units.length === 1 && rate.options?.length
      ? t('pl.priceRange', { lo: amount(Math.min(...rate.options.map(o => o.amount)), units[0]!, lang), hi: amount(Math.max(...rate.options.map(o => o.amount)), units[0]!, lang) })
      : t('pl.varies');
  }
  if (rate.item === 'node_hour' && rate.rule_amount != null && rate.unit) return ruleText({ item: 'node_hour', amount: rate.rule_amount, unit: rate.unit }, t, lang);
  return rate.amount != null && rate.unit ? ruleText({ item: 'gpu_hour', amount: rate.amount, unit: rate.unit }, t, lang) : t('pl.unknownPrice');
}

/** The prices row of a pool: its rules (where each comes from), or what holds without one. */
export function pricesSummary(info: PoolInfo, t: TFunc, lang: string): string {
  if (!info.prices.length) return info.billed ? t('pl.unknownPrice') : t('pl.free');
  const shown = info.prices.slice(0, 3).map(r => {
    const m = Object.keys(r.match).length ? `${matchText(r.match, t)} ` : '';
    return `${m}${ruleText(r, t, lang)}`;
  });
  const fromAll = new Set(info.prices.map(r => r.from));
  const from = fromAll.size === 1 ? t(`pl.from.${[...fromAll][0]}`) : t('pl.from.both');
  const list = shown.join(lang === 'zh' ? '，' : ', ') + (info.prices.length > 3 ? ` … (${info.prices.length})` : '');
  return t('pl.pricesFrom', { list, from });
}

/** The budget row: what agents may queue here each day and the month's cap. */
export function budgetSummary(info: PoolInfo, t: TFunc, lang: string): string {
  const b = info.budget;
  const parts: string[] = [];
  if (b.month) parts.push(t('pl.monthCap', { v: amount(b.month.amount, b.month.unit, lang) }));
  const day = b.agent_gpu_hours_per_day ?? 0;
  parts.push(day > 0
    ? (b.agent_used_today != null ? t('pl.agentDayUsed', { n: num(day, lang), used: num(b.agent_used_today, lang) }) : t('pl.agentDay', { n: num(day, lang) }))
    : t('pl.agentNever'));
  return parts.join(' · ');
}

/** The estimate of one cell (or a run): "≈ 0.19 USD", "not billed", "price unknown". */
export function cellCostText(c: CellCost | null | undefined, t: TFunc, lang: string): string {
  if (!c) return '';
  if (c.state === 'free') return t('pl.free');
  if (c.amount != null && c.unit) return `≈ ${amount(c.amount, c.unit, lang)}`;
  return c.state === 'varies' ? t('pl.varies') : t('pl.unknownPrice');
}

/** Sum cell costs per unit; free cells add nothing and unknown ones are counted apart. */
export function sumCosts(items: (CellCost | null | undefined)[]): { cost: Record<string, number>; unknown: number; free: number } {
  const cost: Record<string, number> = {};
  let unknown = 0, free = 0;
  for (const c of items) {
    if (!c) { unknown += 1; continue; }
    if (c.state === 'free') { free += 1; continue; }
    if (c.amount == null || !c.unit) { unknown += 1; continue; }
    cost[c.unit] = (cost[c.unit] ?? 0) + c.amount;
  }
  return { cost, unknown, free };
}

/** A command as one line, each argument quoted when it needs to be (what the wizard shows before saving). */
export function commandLine(argv: string[]): string {
  return argv.map(a => (/^[\w@%+=:,./~-]+$/.test(a) ? a : `'${a.replace(/'/g, `'\\''`)}'`)).join(' ');
}

/** "every 10 minutes" from seconds. */
export function everyText(s: number | undefined, t: TFunc): string {
  if (!s) return '';
  if (s % 3600 === 0) return t('pl.every.h', { n: s / 3600 });
  if (s % 60 === 0) return t('pl.every.m', { n: s / 60 });
  return t('pl.every.s', { n: s });
}

/** The source line: "Command rd-pool-openstack --cloud js2 · every 10 minutes". */
export function sourceText(def: Pick<PoolDef, 'source'>, t: TFunc): { kind: string; detail: string | null; every: string } {
  const s = def.source;
  return {
    kind: t(`pl.src.${s.type}`),
    detail: s.type === 'command' ? commandLine(s.run ?? []) : s.type === 'http' ? s.url ?? null : null,
    every: s.type === 'manual' ? '' : everyText(s.every, t),
  };
}

/** What one GPU-hour costs on a platform for a machine or GPU model (the new-experiment dialog): the matching machines'
 *  prices when they agree, "varies" when they do not, the pool's own rate when no machine matches. */
export function platformRate(p: ExPlatform | undefined, host?: string, gpu?: string): Pick<Rate, 'state' | 'amount' | 'unit'> | null {
  if (!p?.pool) return null;
  const h = (host ?? '').trim().toLowerCase(), g = (gpu ?? '').trim().toLowerCase();
  const nodes = p.nodes.filter(n => n.gpus.length && n.price
    && (!h || n.id.toLowerCase() === h || n.label.toLowerCase() === h)
    && (!g || n.gpus.some(x => x.name.toLowerCase() === g)));
  if (!nodes.length) return { state: p.pool.rate.state, amount: p.pool.rate.amount, unit: p.pool.rate.unit };
  const prices = nodes.map(n => n.price!);
  const eq = (a: number | null, b: number | null) => (a == null || b == null ? a === b : Math.abs(a - b) < 1e-9);
  const same = prices.every(x => x.state === prices[0].state && x.unit === prices[0].unit && eq(x.amount, prices[0].amount));
  return same ? { state: prices[0].state, amount: prices[0].amount, unit: prices[0].unit } : { state: 'varies', amount: null, unit: null };
}
