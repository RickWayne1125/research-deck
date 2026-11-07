// Resource pools: prices and costs as text (units never added, unknown never 0), the client-side rate for a machine,
// the wizard's draft checks, and platform names (a pool's id or one of its other names).
import { describe, expect, it } from 'vitest';
import type { CellCost } from '../types';
import type { ExPlatform } from '../panels/experiments/api';
import type { PoolDef, PoolInfo, Rate } from './api';
import { blank, fromName, headOf, idFor, isIdLike, nameKey, problems, slugId } from './draft';
import { amount, answersTo, cellCostText, commandLine, costs, isMoney, nameList, platformRate, rateText, sumCosts } from './format';

// A t() that shows the key and its variables, so the tests read the choice made, not the wording.
const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key}(${Object.values(vars).join('|')})` : key);

const rate = (r: Partial<Rate>): Rate => ({ state: 'known', amount: null, unit: null, item: null, rule_amount: null, from: null, why: null, ...r });
const cost = (c: Partial<CellCost>): CellCost => ({ state: 'known', amount: null, unit: null, rate: null, item: null, rule_amount: null, pool: null, why: null, ...c });

describe('prices and costs as text', () => {
  it('tells money from quota units and formats each', () => {
    expect(isMoney('USD')).toBe(true);
    expect(isMoney('SU')).toBe(false);
    expect(amount(0.1875, 'USD', 'en')).toBe('0.19 USD');
    expect(amount(12400, 'SU', 'en')).toBe('12,400 SU');
  });

  it('never adds different units, and leaves zero out', () => {
    expect(costs({ USD: 0.58, SU: 128 }, 'en')).toBe('0.58 USD + 128 SU');
    expect(costs({ USD: 0 }, 'en')).toBe('');
    const sum = sumCosts([cost({ amount: 1, unit: 'USD' }), cost({ amount: 2, unit: 'USD' }), cost({ amount: 64, unit: 'SU' }),
      cost({ state: 'free', amount: 0 }), cost({ state: 'unknown' }), undefined]);
    expect(sum).toEqual({ cost: { USD: 3, SU: 64 }, unknown: 2, free: 1 });
  });

  it('says unknown, free and varying prices instead of a number', () => {
    expect(rateText(rate({ state: 'free', amount: 0 }), t, 'en')).toBe('pl.free');
    expect(rateText(rate({ state: 'unknown' }), t, 'en')).toBe('pl.unknownPrice');
    expect(rateText(rate({ state: 'varies', options: [{ amount: 1, unit: 'USD' }, { amount: 2.5, unit: 'USD' }] }), t, 'en')).toBe('pl.priceRange(1.00 USD|2.50 USD)');
    expect(rateText(rate({ amount: 0.08, unit: 'USD', item: 'gpu_hour', rule_amount: 0.08 }), t, 'en')).toBe('pl.perGpuHour(0.08 USD)');
    expect(rateText(rate({ amount: 32, unit: 'SU', item: 'node_hour', rule_amount: 64 }), t, 'en')).toBe('pl.perNodeHour(64 SU)');
    expect(cellCostText(cost({ state: 'unknown' }), t, 'en')).toBe('pl.unknownPrice');
    expect(cellCostText(cost({ amount: 1.5, unit: 'USD' }), t, 'en')).toBe('≈ 1.50 USD');
  });

  it('quotes command arguments only when needed', () => {
    expect(commandLine(['/usr/bin/python3', '/x/rd_pool_ssh.py', 'gpu-box'])).toBe('/usr/bin/python3 /x/rd_pool_ssh.py gpu-box');
    expect(commandLine(['sh', '-c', "echo 'hi' there"])).toBe(`sh -c 'echo '\\''hi'\\'' there'`);
  });
});

describe('the price of a machine', () => {
  const info = { rate: rate({ state: 'varies' }), here: true } as PoolInfo;
  const node = (id: string, gpu: string, amount: number | null, unit = 'USD') => ({
    id, label: id, status: 'online' as const, gpus: [{ name: gpu, util: null, mem_used: null, mem_total: null, temp: null }],
    price: { state: amount == null ? 'unknown' as const : 'known' as const, amount, unit, item: 'gpu_hour' as const, rule_amount: amount, from: 'source' },
  });
  const p = { id: 'c', label: 'C', kind: 'cloud', status: 'ok', pool: info,
    nodes: [node('a', 'H100', 2.49), node('b', 'A100', 1.2), node('c', 'A100', 1.2)] } as unknown as ExPlatform;

  it('agrees when the matching machines agree, and says so when they do not', () => {
    expect(platformRate(p)?.state).toBe('varies');
    expect(platformRate(p, undefined, 'a100')).toMatchObject({ state: 'known', amount: 1.2, unit: 'USD' });
    expect(platformRate(p, 'a')).toMatchObject({ amount: 2.49 });
    expect(platformRate(p, 'nowhere')).toMatchObject({ state: 'varies' });               // no such machine: the pool's rate
    expect(platformRate({ ...p, pool: undefined } as ExPlatform)).toBeNull();              // not a pool (example data)
  });
});

describe('the wizard draft', () => {
  it('makes an id from a name', () => {
    expect(slugId('Lab GPU #2')).toBe('lab-gpu-2');
    expect(slugId('家里 5090')).toBe('5090');
    expect(slugId('..a..b..')).toBe('a.b');
  });

  it('lists what keeps a draft from being saved', () => {
    const d: PoolDef = { ...blank('box'), source: { type: 'command', run: ['rd-pool', ''] } };
    expect(problems(d)).toEqual(['run']);
    expect(problems({ ...d, id: 'Box', source: { type: 'http', url: 'http://example.org/p' } })).toEqual(['id', 'url']);
    expect(problems({ ...d, source: { type: 'http', url: 'http://127.0.0.1:9000/pools/box' }, credential: 'hunter2' })).toEqual(['credential']);
    expect(problems({ ...d, source: { type: 'local' }, prices: [{ item: 'gpu_hour', match: {}, amount: NaN, unit: 'USD' }] })).toEqual(['prices']);
    expect(problems({ ...d, source: { type: 'local' }, credential: 'keychain:box-reader' })).toEqual([]);
    expect(problems({ ...d, source: { type: 'local' }, names: ['8× RTX A6000', ' '] })).toEqual(['names']);
  });
});

describe('platform names', () => {
  const A6000 = '8× RTX A6000 (lab node, GPUs 0-3)';

  it('compares them as the server does: case and extra spaces aside', () => {
    expect(nameKey('  8×  RTX\tA6000 ')).toBe('8× rtx a6000');
    expect(isIdLike('Workstation')).toBe(true);
    expect(isIdLike(A6000)).toBe(false);
    expect(headOf(A6000)).toBe('8× RTX A6000');
    expect(headOf('RTX 5090 32 GiB；A100')).toBe('RTX 5090 32 GiB');
  });

  it('makes a pool for a name: the name is its id when it can be, else one of its names', () => {
    expect(fromName('Workstation', [])).toMatchObject({ id: 'workstation', label: 'Workstation' });
    expect(fromName('Workstation', []).names).toBeUndefined();
    expect(fromName(A6000, [])).toMatchObject({ id: '8-rtx-a6000', label: '8× RTX A6000', names: [A6000] });
    expect(idFor(A6000, ['8-rtx-a6000', '8-rtx-a6000-2'])).toBe('8-rtx-a6000-3');
    expect(idFor('(GPU smoke)', [])).toBe('gpu-smoke');                  // nothing before the bracket: the whole name
  });

  it('finds the pool a name belongs to', () => {
    const p = { id: 'lab', label: 'Lab', nodes: [], pool: { names: [A6000] } } as unknown as ExPlatform;
    expect(answersTo(p, 'LAB')).toBe(true);
    expect(answersTo(p, '8× rtx a6000  (lab node, GPUs 0-3)')).toBe(true);
    expect(answersTo(p, '8× RTX A6000')).toBe(false);
    expect(answersTo(p, ' ')).toBe(false);
    expect(nameList(['a, b', 'c'], 'en')).toBe('a, b; c');
  });
});
