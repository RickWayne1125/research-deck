// App-wide state: the project list and current project, the view, theme, backend health and the agent catalog.
// Routing is the hash: #/<projectId>/<view>[/<sub>] so a reload or a shared link reopens the same place.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { get, p, subscribeEvents } from '../api/client';
import { applyMode } from './appearance';
import { PHONE_QUERY } from './layout';
import type { AgentCatalog, Health, ProjectDetail, ProjectEvent, ProjectSummary, ViewId } from '../types';

export type Theme = 'auto' | 'light' | 'dark';
const VIEWS: ViewId[] = ['outline', 'overview', 'dag', 'experiments', 'writing', 'coding', 'settings'];
/** The paper view's sub-route for the figures: #/<p>/writing/@figures[/<figure id>]. */
export const FIGURES = '@figures';

interface Route { projectId: string | null; view: ViewId; sub: string | null }
function parseHash(): Route {
  const [, pid, view, ...rest] = (location.hash || '#/').slice(1).split('/');
  const sub = rest.length ? rest.map(decodeURIComponent).join('/') : null;
  const projectId = pid ? decodeURIComponent(pid) : null;
  // Links from before the figures moved into the paper view.
  if (view === 'visualization') return { projectId, view: 'writing', sub: sub ? `${FIGURES}/${sub}` : FIGURES };
  return { projectId, view: (VIEWS as string[]).includes(view) ? (view as ViewId) : 'overview', sub };
}

interface AppValue {
  projects: ProjectSummary[];
  project: ProjectDetail | null;
  projectId: string | null;
  view: ViewId;
  sub: string | null;                       // view-specific sub-route (a node id, a file path, a figure id)
  /** replace: rewrite the current history entry instead of adding one (redirects) */
  navigate: (view: ViewId, sub?: string | null, projectId?: string, opts?: { replace?: boolean }) => void;
  reloadProjects: () => Promise<void>;
  reloadProject: () => Promise<void>;
  theme: Theme; setTheme: (t: Theme) => void;
  health: Health | null; online: boolean;
  catalog: AgentCatalog | null;
  dockOpen: boolean; setDockOpen: (v: boolean) => void;
  /** Open the project conversation and put the cursor in its composer (⌘J). */
  focusDock: () => void;
  dockFocus: number;
  /** Subscribe to this project's live events for a topic; returns unsubscribe. */
  onEvent: (topic: string, fn: (e: ProjectEvent) => void) => () => void;
  /** Send something to the agent dock (prefills its input and opens it). Panels use this for "Ask about this". */
  askAgent: (prompt: string, context?: Record<string, unknown>) => void;
  pendingAsk: { prompt: string; context?: Record<string, unknown>; n: number } | null;
}

const AppContext = createContext<AppValue | null>(null);

/** Which project to show: the route's (also while the project list has not loaded, and until a list fetched again
 *  says it is not registered: a link to a project made in another tab must not bounce); else the last one shown, if
 *  it is still registered; else the first; null when there is none. A removed project, a stale link or a remembered
 *  id thus never leaves the page on "unknown project". */
export function pickProject(route: string | null, last: string, projects: readonly { id: string }[],
  { listed, missing }: { listed: boolean; missing: string | null }): string | null {
  const registered = (id: string) => projects.some(p => p.id === id);
  if (route && (!listed || registered(route) || missing !== route)) return route;
  if (!listed) return null;
  return registered(last) ? last : projects[0]?.id ?? null;
}

function readLocal<T extends string>(key: string, fallback: T): T {
  try { return (localStorage.getItem(key) as T) || fallback; } catch { return fallback; }
}

/** On a phone the conversation covers the page: there it starts closed, and opening or closing it is not remembered. */
function onPhone(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.(PHONE_QUERY).matches;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(parseHash);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [listed, setListed] = useState(false);                     // the project list has loaded at least once
  const [missing, setMissing] = useState<string | null>(null);     // a route's project a fresh list does not have
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [theme, setThemeState] = useState<Theme>(() => readLocal<Theme>('rd.theme', 'auto'));
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(true);
  const [catalog, setCatalog] = useState<AgentCatalog | null>(null);
  const [dockOpen, setDockOpenState] = useState(() => !onPhone() && readLocal('rd.dock', 'open') === 'open');
  const [pendingAsk, setPendingAsk] = useState<AppValue['pendingAsk']>(null);
  const [dockFocus, setDockFocus] = useState(0);
  const listeners = useRef(new Map<string, Set<(e: ProjectEvent) => void>>());

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const reloadProjects = useCallback(async () => {
    try { setProjects(await get<ProjectSummary[]>('/api/projects')); setListed(true); setOnline(true); } catch { setOnline(false); }
  }, []);
  useEffect(() => { reloadProjects(); }, [reloadProjects]);

  // The route names a project the list does not have: fetch the list once more (the project may be new) and only then
  // let pickProject give way to a registered one.
  const checked = useRef<string | null>(null);
  useEffect(() => {
    const id = route.projectId;
    if (!listed || !id || projects.some(p => p.id === id) || checked.current === id) return;
    checked.current = id;
    get<ProjectSummary[]>('/api/projects').then(list => {
      setProjects(list);
      if (!list.some(p => p.id === id)) setMissing(id);
    }).catch(() => { checked.current = null; });
  }, [listed, route.projectId, projects]);

  // The session cookie marks this browser as the researcher (human-only DAG operations need it; see actors.py).
  useEffect(() => { get('/api/session').catch(() => {}); }, []);

  useEffect(() => {
    get<Health>('/api/system/health').then(h => { setHealth(h); setOnline(true); }).catch(() => setOnline(false));
    get<AgentCatalog>('/api/agents/catalog').then(setCatalog).catch(() => {});
  }, []);

  // The route's project, else the last one, else the first (pickProject); the address follows, replacing a project that
  // is gone so that Back does not return to it.
  const projectId = pickProject(route.projectId, readLocal('rd.project', ''), projects, { listed, missing });
  useEffect(() => {
    if (projectId && projectId !== route.projectId) location.replace(`#/${encodeURIComponent(projectId)}/${route.view}`);
    else if (!projectId && route.projectId && listed && missing === route.projectId) location.replace('#/');
    if (projectId && projects.some(p => p.id === projectId)) try { localStorage.setItem('rd.project', projectId); } catch { /* ignore */ }
  }, [projectId, route.projectId, route.view, listed, missing, projects]);

  const reloadProject = useCallback(async () => {
    if (!projectId) { setProject(null); return; }
    try { setProject(await get<ProjectDetail>(p(projectId, ''))); } catch { setProject(null); }
  }, [projectId]);
  useEffect(() => { reloadProject(); }, [reloadProject]);

  useEffect(() => {
    if (!projectId) return;
    return subscribeEvents(projectId, (e) => {
      if (e.topic === 'project') reloadProject();
      listeners.current.get(e.topic)?.forEach(fn => fn(e));
      listeners.current.get('*')?.forEach(fn => fn(e));
    });
  }, [projectId, reloadProject]);

  const onEvent = useCallback((topic: string, fn: (e: ProjectEvent) => void) => {
    const set = listeners.current.get(topic) ?? new Set();
    set.add(fn);
    listeners.current.set(topic, set);
    return () => { set.delete(fn); };
  }, []);

  const navigate = useCallback((view: ViewId, sub?: string | null, pid?: string, opts?: { replace?: boolean }) => {
    const target = pid ?? projectId;
    if (!target) return;
    const hash = `#/${encodeURIComponent(target)}/${view}${sub ? '/' + sub.split('/').map(encodeURIComponent).join('/') : ''}`;
    if (opts?.replace) location.replace(hash); else location.hash = hash;
  }, [projectId]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem('rd.theme', t); } catch { /* ignore */ }
  }, []);
  // light or dark on <html> (the Radix theme root, state/appearance.ts); "auto" follows the system as it changes
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    const apply = () => applyMode(theme === 'auto' ? (mq?.matches ? 'dark' : 'light') : theme);
    apply();
    if (theme !== 'auto' || !mq) return;
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [theme]);

  const setDockOpen = useCallback((v: boolean) => {
    setDockOpenState(v);
    if (onPhone()) return;
    try { localStorage.setItem('rd.dock', v ? 'open' : 'closed'); } catch { /* ignore */ }
  }, []);

  const focusDock = useCallback(() => { setDockOpen(true); setDockFocus(n => n + 1); }, [setDockOpen]);

  const askAgent = useCallback((prompt: string, context?: Record<string, unknown>) => {
    setDockOpen(true);
    setPendingAsk(prev => ({ prompt, context, n: (prev?.n ?? 0) + 1 }));
  }, [setDockOpen]);

  const value = useMemo<AppValue>(() => ({
    projects, project, projectId, view: route.view, sub: route.sub, navigate, reloadProjects, reloadProject,
    theme, setTheme, health, online, catalog, dockOpen, setDockOpen, focusDock, dockFocus, onEvent, askAgent, pendingAsk,
  }), [projects, project, projectId, route, navigate, reloadProjects, reloadProject, theme, setTheme, health, online, catalog, dockOpen, setDockOpen, focusDock, dockFocus, onEvent, askAgent, pendingAsk]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppValue {
  const v = useContext(AppContext);
  if (!v) throw new Error('useApp outside AppProvider');
  return v;
}

/** Re-run `load` whenever one of the topics fires for the current project. */
export function useLiveReload(topics: string[], load: () => void): void {
  const { onEvent } = useApp();
  const key = topics.join(',');
  useEffect(() => {
    const offs = topics.map(t => onEvent(t, () => load()));
    return () => offs.forEach(off => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, onEvent, load]);
}
