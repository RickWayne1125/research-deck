import { describe, expect, it } from 'vitest';
import type { Draft, Item, Outline, Step, Task, Template } from './api';
import { arrangeDraft, boardColumns, forks, itemIndex, liveSteps, outlinePending, outlineText, pathTo } from './model';

function item(id: string, num: string, extra: Partial<Item> = {}): Item {
  return {
    id, num, depth: num.split('.').length - 2, section: 'sec.design', parent: 'sec.design', direction: null, text: id,
    status: 'active', derived: false, condition: '', summary_of: [], children: [], fork: null, tasks: [], suggested: [],
    evidence: [], written: [], proposals: [], kids: { total: 0, holds: 0 }, state: 'todo', ...extra,
  };
}
const step = (...items: Item[]): Step => ({ items, note: null });

const lfu = item('claim.lfu', '3.1', { direction: 2, parent: 'claim.policy', state: 'abandoned', status: 'abandoned', why: 'LFU hits 0.37' });
const look = item('claim.look', '3.1', { direction: 1, parent: 'claim.policy', state: 'doing', children: [step(item('claim.look-a', '3.1.1', { parent: 'claim.look' }))] });
const policy = item('claim.policy', '3.1', { state: 'doing', fork: { directions: [look, lfu], chosen: 'claim.look' } });
const ties = item('claim.ties', '3.2', { state: 'holds', tasks: ['t-1'] });
const mods = item('claim.mods', '3.3', { state: 'todo' });

const outline: Outline = {
  has_outline: true, template: 'systems', phases: { idea: { zh: '想法', en: 'Idea' }, insight: { en: 'Insight' }, design: { en: 'Design' }, evaluation: { en: 'Evaluation' } },
  project_phase: 'design', stage_mode: 'strict',
  sections: [{ id: 'sec.design', num: '3', title: { en: 'Design' }, role: 'How it works', phase: 'design', status: 'active',
    items: [step(policy), { items: [ties, mods], note: 'two parts' }], counts: { items: 3, holds: 1 } }],
  groups: [], tasks: [], counts: { done: 0, doing: 0, todo: 0, blocked: 0, total: 0, abandoned: 0, suggested: 0 },
  pending: [{ kind: 'fork', item: 'claim.policy', num: '3.1', text: 'x' }, { kind: 'proposal', proposal: 'p1', title: 'p' }],
  loose: [],
};

describe('walking the outline', () => {
  it('indexes every item, directions and their sub-items included', () => {
    expect([...itemIndex(outline).keys()].sort()).toEqual(['claim.lfu', 'claim.look', 'claim.look-a', 'claim.mods', 'claim.policy', 'claim.ties']);
  });

  it('finds the path from the section down to an item, through a fork', () => {
    const p = pathTo(outline, 'claim.look-a');
    expect(p?.section.id).toBe('sec.design');
    expect(p?.items.map(i => i.id)).toEqual(['claim.policy', 'claim.look', 'claim.look-a']);
    expect(pathTo(outline, 'nope')).toBeNull();
  });

  it('hides abandoned items unless asked', () => {
    const steps = [step(item('a', '1.1', { state: 'abandoned' })), step(item('b', '1.2'))];
    expect(liveSteps(steps, false).map(s => s.items[0].id)).toEqual(['b']);
    expect(liveSteps(steps, true)).toHaveLength(2);
  });

  it('lists forks and keeps open proposals out of the outline\'s own pending items', () => {
    expect(forks(outline).map(f => f.item.id)).toEqual(['claim.policy']);
    expect(outlinePending(outline).map(p => p.kind)).toEqual(['fork']);
  });

  it('writes the outline as text, abandoned directions only when asked', () => {
    const text = outlineText(outline, 'en');
    expect(text).toContain('§3 Design [design] — How it works');
    expect(text).toContain('↳ direction 1 (chosen)');
    expect(text).not.toContain('LFU');
    expect(text).toContain('(parallel: two parts)');
    expect(outlineText(outline, 'en', { abandoned: true })).toContain('given up: LFU hits 0.37');
  });
});

describe('the task board', () => {
  const task = (id: string, extra: Partial<Task>): Task => ({
    id, type: 'exp', title: id, items: [], status: 'todo', set_status: 'todo', note: '', assignee: '', links: {}, by: '',
    created_at: '', updated_at: '', reason: null, phase: 'design', nums: [], abandoned: false, ...extra,
  });
  it('sorts tasks into columns, waiting and suggested ones under not started, abandoned ones out', () => {
    const cols = boardColumns([
      task('a', { status: 'done' }), task('b', { status: 'locked', phase: 'evaluation' }), task('c', { status: 'sugg' }),
      task('d', { status: 'blocked' }), task('e', { status: 'doing', type: 'code' }), task('f', { abandoned: true }), task('g', {}),
    ], 'all', 'all');
    expect(cols.done.map(x => x.id)).toEqual(['a']);
    expect(cols.todo.map(x => x.id)).toEqual(['g', 'c', 'b']);
    expect(cols.blocked.map(x => x.id)).toEqual(['d']);
    expect(boardColumns([task('e', { status: 'doing', type: 'code' })], 'exp', 'all').doing).toEqual([]);
  });
});

describe('a structured draft', () => {
  const tpl: Template = {
    id: 'systems', name: 'Systems', phases: outline.phases,
    sections: [
      { key: 'intro', title: { zh: '引言', en: 'Introduction' }, role: { en: 'The problem' }, phase: 'summary' },
      { key: 'motivation', title: { zh: '背景与动机', en: 'Background and Motivation' }, role: { en: 'Why' }, phase: 'insight' },
      { key: 'design', title: { zh: '设计', en: 'Design' }, role: { en: 'How' }, phase: 'design' },
    ],
  };
  it('lands in the template\'s sections by key or title, and a new section after the one before it', () => {
    const draft: Draft = { changes: [], sections: [
      { key: null, title: 'Introduction', items: [{ text: 'a', children: [] }] },
      { key: null, title: 'Threat model', items: [{ text: 'b', children: [] }] },
      { key: 'design', title: 'Our design', items: [[{ text: 'c', children: [] }, { text: 'd', children: [] }]], notes: { '0': 'two parts' } },
    ] };
    const out = arrangeDraft(tpl, draft, 'en');
    expect(out.map(s => [s.key, s.title, s.items.length])).toEqual([
      ['intro', 'Introduction', 1], [null, 'Threat model', 1], ['motivation', 'Background and Motivation', 0], ['design', 'Design', 1]]);
    expect(out[3].notes).toEqual({ '0': 'two parts' });
    expect(out[1].fromTemplate).toBe(false);
  });
});
