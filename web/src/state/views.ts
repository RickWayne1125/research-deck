// Which views a project shows (pure, unit-tested in views.test.ts). A research project shows every view; an
// engineering project (a PR, an integration effort) hides the research map. `views` in the project config, when set,
// overrides the kind's default for any kind; settings always stays.
import type { ProjectKind, ViewId } from '../types';

/** Every view, in navigation order: Today, Map, Experiments, Paper, Code, Settings. */
export const ALL_VIEWS: ViewId[] = ['overview', 'dag', 'experiments', 'writing', 'coding', 'settings'];

const HIDDEN_BY_KIND: Record<ProjectKind, ViewId[]> = { research: [], engineering: ['dag'] };

/** Older configs may name views that were merged since: the figures live in the paper view now. */
const ALIASES: Record<string, ViewId> = { visualization: 'writing' };

type KindAndViews = { kind?: ProjectKind | string | null; views?: readonly string[] | null };

const kindOf = (p: KindAndViews | null | undefined): ProjectKind => (p?.kind === 'engineering' ? 'engineering' : 'research');

/** The views the navigation shows for a project, in navigation order. Unknown ids in `views` are ignored; an empty
 *  list counts as unset (the backend reports it as null). Without a project every view shows. */
export function visibleViews(p: KindAndViews | null | undefined): ViewId[] {
  if (!p) return ALL_VIEWS;
  const listed = Array.isArray(p.views) ? p.views.map(v => ALIASES[v] ?? v).filter(v => (ALL_VIEWS as string[]).includes(v)) : [];
  if (listed.length) return ALL_VIEWS.filter(v => v === 'settings' || listed.includes(v));
  const hidden = HIDDEN_BY_KIND[kindOf(p)];
  return ALL_VIEWS.filter(v => !hidden.includes(v));
}

export function isViewVisible(p: KindAndViews | null | undefined, view: ViewId): boolean {
  return visibleViews(p).includes(view);
}

/** Where to go when the current view is hidden: Today, else the first view shown. */
export function fallbackView(p: KindAndViews | null | undefined): ViewId {
  const shown = visibleViews(p);
  return shown.includes('overview') ? 'overview' : shown[0];
}

/** Research projects have stages (and the map); engineering projects do not. */
export function isResearch(p: KindAndViews | null | undefined): boolean {
  return kindOf(p) === 'research';
}
