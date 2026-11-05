// Which views a project shows (pure, unit-tested in views.test.ts). A research project works from its outline: the
// outline page is its home, what Today listed sits at the top of it, and the map opens from there (its route stays, for
// node pages and links) without its own place in the navigation. An engineering project (a PR, an integration effort)
// has Today and neither outline nor map. `views` in the project config, when set, overrides the kind's default for any
// kind; settings always stays.
import type { ProjectKind, ViewId } from '../types';

/** Every view, in navigation order: Outline, Today, Map, Experiments, Paper, Code, Settings. */
export const ALL_VIEWS: ViewId[] = ['outline', 'overview', 'dag', 'experiments', 'writing', 'coding', 'settings'];

/** What the navigation leaves out, by kind. */
const NAV_HIDDEN: Record<ProjectKind, ViewId[]> = { research: ['overview', 'dag'], engineering: ['outline', 'dag'] };

/** Older configs may name views that were merged since: the figures live in the paper view now, and in a research
 *  project Today and the map are parts of the outline page. */
const ALIASES: Record<string, ViewId> = { visualization: 'writing' };
const RESEARCH_ALIASES: Record<string, ViewId> = { overview: 'outline', dag: 'outline' };

type KindAndViews = { kind?: ProjectKind | string | null; views?: readonly string[] | null };

const kindOf = (p: KindAndViews | null | undefined): ProjectKind => (p?.kind === 'engineering' ? 'engineering' : 'research');

/** The views the navigation shows for a project, in navigation order. Unknown ids in `views` are ignored; an empty
 *  list counts as unset (the backend reports it as null). Without a project, a research project's views. */
export function visibleViews(p: KindAndViews | null | undefined): ViewId[] {
  const kind = kindOf(p);
  const alias = (v: string) => ALIASES[v] ?? (kind === 'research' ? RESEARCH_ALIASES[v] : undefined) ?? v;
  const listed = Array.isArray(p?.views)
    ? p!.views!.map(alias).filter(v => (ALL_VIEWS as string[]).includes(v) && !(kind === 'engineering' && v === 'outline'))
    : [];
  if (listed.length) return ALL_VIEWS.filter(v => v === 'settings' || listed.includes(v));
  const hidden = NAV_HIDDEN[kind];
  return ALL_VIEWS.filter(v => !hidden.includes(v));
}

/** The views a project can open: the navigation's, and in a research project with an outline page the map as well
 *  (reached from the outline, the palette and node links). */
export function allowedViews(p: KindAndViews | null | undefined): ViewId[] {
  const shown = visibleViews(p);
  const extra: ViewId[] = kindOf(p) === 'research' && shown.includes('outline') ? ['dag'] : [];
  return ALL_VIEWS.filter(v => shown.includes(v) || extra.includes(v));
}

export function isViewVisible(p: KindAndViews | null | undefined, view: ViewId): boolean {
  return visibleViews(p).includes(view);
}

export function isViewAllowed(p: KindAndViews | null | undefined, view: ViewId): boolean {
  return allowedViews(p).includes(view);
}

/** Where to go when the current view is not open to the project: the outline, else Today, else the first view shown. */
export function fallbackView(p: KindAndViews | null | undefined): ViewId {
  const shown = visibleViews(p);
  return shown.includes('outline') ? 'outline' : shown.includes('overview') ? 'overview' : shown[0];
}

/** Research projects have stages (and the map); engineering projects do not. */
export function isResearch(p: KindAndViews | null | undefined): boolean {
  return kindOf(p) === 'research';
}
