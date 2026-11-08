import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../types';
import { applyEvent, pendingSteers, segmentsOf, type Live } from './live';

const start: Live = { runId: 'r1', prompt: 'Summarize', status: 'running', events: [], error: null, meta: null, steerable: false };
const replay = (events: AgentEvent[], from: Live = start) => events.reduce(applyEvent, from);

describe('applyEvent', () => {
  it('takes who answers and whether it can be steered from the start event', () => {
    const l = replay([{ type: 'start', provider: 'claude', model: 'm', effort: 'high', fast: false, session_id: null, purpose: 'chat', steerable: true }]);
    expect(l.meta).toEqual({ provider: 'claude', model: 'm', effort: 'high', fast: false });
    expect(l.steerable).toBe(true);
  });

  it('ends on done: stopped, failed or finished', () => {
    const done = (extra: Partial<Extract<AgentEvent, { type: 'done' }>>): AgentEvent =>
      ({ type: 'done', ok: true, text: '', session_id: null, duration_ms: 1, ...extra });
    expect(replay([done({ cancelled: true, ok: false })]).status).toBe('cancelled');
    expect(replay([done({ ok: false })]).status).toBe('error');
    expect(replay([done({})]).status).toBe('done');
  });

  it('starts over on reset: a restarted server replays the run from the beginning', () => {
    const before = replay([{ type: 'text', delta: 'piece 1 ' }, { type: 'error', message: 'x' }]);
    const after = replay([{ type: 'reset' }, { type: 'text', delta: 'piece 1 ' }], before);
    expect(after.events).toEqual([{ type: 'text', delta: 'piece 1 ' }]);
    expect(after.error).toBeNull();
    expect(after.prompt).toBe('Summarize');               // what the page knew about the run stays
  });
});

describe('segmentsOf', () => {
  it('splits the answer where the agent read a steered message', () => {
    const segs = segmentsOf([
      { type: 'text', delta: 'piece 1 ' }, { type: 'tool', name: 'Read', detail: 'notes/idea.md' },
      { type: 'steer', id: 's1', text: 'focus on the risks' },     // handed over: not part of the answer yet
      { type: 'text', delta: 'piece 2 ' },
      { type: 'user', id: 's1', text: 'focus on the risks' },
      { type: 'text', delta: '(read: focus on the risks)' },
    ]);
    expect(segs).toEqual([
      { tools: [{ name: 'Read', detail: 'notes/idea.md' }], text: 'piece 1 piece 2 ' },
      { user: 'focus on the risks', tools: [], text: '(read: focus on the risks)' },
    ]);
  });
});

describe('pendingSteers', () => {
  it('lists what was handed over but not read, then what this page sent that the run has not reported', () => {
    const l = replay([
      { type: 'steer', id: 's1', text: 'read already' }, { type: 'user', id: 's1', text: 'read already' },
      { type: 'steer', id: 's2', text: 'handed over' },
    ]);
    const sent = [
      { key: 'k1', runId: 'r1', text: 'handed over', id: 's2' },        // reported: counted once, as s2
      { key: 'k2', runId: 'r1', text: 'on its way' },                    // the request has not answered yet
      { key: 'k3', runId: 'r1', text: 'answered, not reported', id: 's3' },
      { key: 'k4', runId: 'other', text: 'another run' },
    ];
    expect(pendingSteers(l, sent)).toEqual([
      { key: 's2', text: 'handed over' }, { key: 'k2', text: 'on its way' }, { key: 'k3', text: 'answered, not reported' },
    ]);
  });
});
