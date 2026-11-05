import { describe, expect, it } from 'vitest';
import { allowedViews, fallbackView, isResearch, isViewAllowed, isViewVisible, visibleViews } from './views';

const RESEARCH_NAV = ['outline', 'experiments', 'writing', 'coding', 'settings'];

describe('view visibility', () => {
  it('a research project works from its outline: Today and the map leave the navigation, the map stays open', () => {
    const p = { kind: 'research' as const, views: null };
    expect(visibleViews(p)).toEqual(RESEARCH_NAV);
    expect(isViewVisible(p, 'dag')).toBe(false);
    expect(isViewAllowed(p, 'dag')).toBe(true);
    expect(isViewAllowed(p, 'overview')).toBe(false);
    expect(allowedViews(p)).toEqual(['outline', 'dag', 'experiments', 'writing', 'coding', 'settings']);
    expect(isResearch(p)).toBe(true);
  });

  it('an engineering project has Today, no outline and no map, and no stages', () => {
    const p = { kind: 'engineering' as const, views: null };
    expect(visibleViews(p)).toEqual(['overview', 'experiments', 'writing', 'coding', 'settings']);
    expect(allowedViews(p)).toEqual(visibleViews(p));
    expect(isViewVisible(p, 'dag')).toBe(false);
    expect(isViewAllowed(p, 'outline')).toBe(false);
    expect(isViewVisible(p, 'coding')).toBe(true);
    expect(isResearch(p)).toBe(false);
  });

  it('views overrides the kind, in navigation order, and settings always stays', () => {
    expect(visibleViews({ kind: 'engineering', views: ['coding', 'dag', 'overview'] })).toEqual(['overview', 'dag', 'coding', 'settings']);
    expect(visibleViews({ kind: 'engineering', views: ['outline', 'coding'] })).toEqual(['coding', 'settings']);
    expect(visibleViews({ kind: 'research', views: ['writing'] })).toEqual(['writing', 'settings']);
    expect(allowedViews({ kind: 'research', views: ['writing'] })).toEqual(['writing', 'settings']);
    // the override is about views only: stages still follow the kind
    expect(isResearch({ kind: 'research', views: ['writing'] })).toBe(true);
  });

  it('maps merged views: the old visualization view to the paper, a research project\'s Today and map to the outline', () => {
    expect(visibleViews({ kind: 'research', views: ['visualization', 'coding'] })).toEqual(['writing', 'coding', 'settings']);
    expect(visibleViews({ kind: 'research', views: ['overview', 'dag', 'writing'] })).toEqual(['outline', 'writing', 'settings']);
  });

  it('ignores unknown ids, treats an empty list as unset and an unknown kind as research', () => {
    expect(visibleViews({ kind: 'engineering', views: ['nope', 'coding'] })).toEqual(['coding', 'settings']);
    expect(visibleViews({ kind: 'engineering', views: [] })).not.toContain('dag');
    expect(visibleViews({ kind: 'engineering', views: ['nope'] })).not.toContain('dag');
    expect(visibleViews({ kind: 'hobby', views: null })).toEqual(RESEARCH_NAV);
    expect(visibleViews(null)).toEqual(RESEARCH_NAV);
  });

  it('a closed view falls back to the outline, else Today, else the first view shown', () => {
    expect(fallbackView({ kind: 'research', views: null })).toBe('outline');
    expect(fallbackView({ kind: 'engineering', views: null })).toBe('overview');
    expect(fallbackView({ kind: 'research', views: ['coding', 'writing'] })).toBe('writing');
  });
});
