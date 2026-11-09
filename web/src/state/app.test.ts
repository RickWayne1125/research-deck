// Which project the page shows: a removed project, a stale link or a remembered id gives way to a registered project
// instead of leaving the page on "unknown project"; a link to a project not yet in the list waits for a fresh list.
import { describe, expect, it } from 'vitest';
import { pickProject } from './app';

const list = [{ id: 'demo' }, { id: 'thesis' }];
const ready = { listed: true, missing: null };

describe('pickProject', () => {
  it("shows the route's project, else the last one, else the first", () => {
    expect(pickProject('thesis', 'demo', list, ready)).toBe('thesis');
    expect(pickProject(null, 'thesis', list, ready)).toBe('thesis');
    expect(pickProject(null, '', list, ready)).toBe('demo');
    expect(pickProject(null, '', [], ready)).toBeNull();
  });

  it('skips a remembered project that is no longer registered', () => {
    expect(pickProject(null, 'removed', list, ready)).toBe('demo');
    expect(pickProject(null, 'removed', [], ready)).toBeNull();
  });

  it('trusts the route until the list has loaded', () => {
    expect(pickProject('removed', 'thesis', [], { listed: false, missing: null })).toBe('removed');
    expect(pickProject(null, 'thesis', [], { listed: false, missing: null })).toBeNull();
  });

  it('gives way only once a fresh list says the route\'s project is gone', () => {
    // not in the list yet (it may be new): keep it while the list is fetched again
    expect(pickProject('fresh', 'thesis', list, ready)).toBe('fresh');
    // gone: the last one shown, else the first
    expect(pickProject('removed', 'thesis', list, { listed: true, missing: 'removed' })).toBe('thesis');
    expect(pickProject('removed', 'removed', list, { listed: true, missing: 'removed' })).toBe('demo');
    expect(pickProject('removed', '', [], { listed: true, missing: 'removed' })).toBeNull();
    // registered again later (added back): shown again
    expect(pickProject('removed', 'demo', [...list, { id: 'removed' }], { listed: true, missing: 'removed' })).toBe('removed');
  });
});
