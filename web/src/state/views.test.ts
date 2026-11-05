import { describe, expect, it } from 'vitest';
import { ALL_VIEWS, fallbackView, isResearch, isViewVisible, visibleViews } from './views';

describe('view visibility', () => {
  it('a research project shows every view and has stages', () => {
    expect(visibleViews({ kind: 'research', views: null })).toEqual(ALL_VIEWS);
    expect(isResearch({ kind: 'research', views: null })).toBe(true);
  });

  it('an engineering project hides the map and has no stages', () => {
    const p = { kind: 'engineering' as const, views: null };
    expect(visibleViews(p)).toEqual(['overview', 'experiments', 'writing', 'coding', 'settings']);
    expect(isViewVisible(p, 'dag')).toBe(false);
    expect(isViewVisible(p, 'coding')).toBe(true);
    expect(isResearch(p)).toBe(false);
  });

  it('views overrides the kind, in navigation order, and settings always stays', () => {
    expect(visibleViews({ kind: 'engineering', views: ['coding', 'dag', 'overview'] })).toEqual(['overview', 'dag', 'coding', 'settings']);
    expect(visibleViews({ kind: 'research', views: ['writing'] })).toEqual(['writing', 'settings']);
    // the override is about views only: stages still follow the kind
    expect(isResearch({ kind: 'research', views: ['writing'] })).toBe(true);
  });

  it('maps the old visualization view to the paper view', () => {
    expect(visibleViews({ kind: 'research', views: ['visualization', 'coding'] })).toEqual(['writing', 'coding', 'settings']);
  });

  it('ignores unknown ids, treats an empty list as unset and an unknown kind as research', () => {
    expect(visibleViews({ kind: 'engineering', views: ['nope', 'coding'] })).toEqual(['coding', 'settings']);
    expect(visibleViews({ kind: 'engineering', views: [] })).not.toContain('dag');
    expect(visibleViews({ kind: 'engineering', views: ['nope'] })).not.toContain('dag');
    expect(visibleViews({ kind: 'hobby', views: null })).toEqual(ALL_VIEWS);
    expect(visibleViews(null)).toEqual(ALL_VIEWS);
  });

  it('a hidden view falls back to Today, else to the first view shown', () => {
    expect(fallbackView({ kind: 'engineering', views: null })).toBe('overview');
    expect(fallbackView({ kind: 'research', views: ['coding', 'writing'] })).toBe('writing');
  });
});
