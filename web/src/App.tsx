// The shell: the navigation (brand, project, jump, the five sections, settings), the view, and the project
// conversation on the right (⌘J), folded to a thin rail when closed. The navigation and the conversation are
// resizable (components/resize.tsx; widths per browser in localStorage); which sections the navigation offers depends
// on the project's kind and `views` (state/views.ts).
import { Component, lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useApp } from './state/app';
import { useToday } from './state/today';
import { stepOfStage } from './state/stages';
import { fallbackView, isResearch, visibleViews } from './state/views';
import { useI18n, useT } from './i18n';
import { Icon } from './components/icons';
import { Button, Dialog, IconButton, Menu, Segmented, Spinner } from './components/ui';
import { ResizeHandle, useResizableWidth } from './components/resize';
import { Palette } from './components/Palette';
import { post } from './api/client';
import { AgentDock } from './agent/AgentDock';
import { NewProjectDialog } from './start/NewProjectDialog';
import './start/i18n';
import { ProviderMark, useRunningPanels, useSessions } from './agent/parts';
import type { ProjectKind, ProjectSummary, ViewId } from './types';
import './styles/shell.css';

const VIEW_ICON: Record<ViewId, string> = {
  overview: 'overview', dag: 'dag', experiments: 'experiments', writing: 'writing', coding: 'coding', settings: 'settings',
};

// The navigation runs from the 56 px icon rail to 320 px; dragged below 132 px it snaps to the rail (labels hidden),
// dragged out again it opens. The conversation takes 300 px up to 60 % of the window (92 % where it floats).
const NAV = { rail: 56, open: 132, initial: 208, max: 320 };
const DOCK = { initial: 380, min: 300 };
const FLOATING = '(max-width: 1100px)';
const NAV_OPEN_KEY = 'rd.shell.navOpenW';
function snapNav(w: number, { from, via }: { from: number; via: 'drag' | 'key' }): number {
  if (via === 'key' && from <= NAV.rail && w > from) return NAV.open;     // ← / → step out of the rail
  return w < NAV.open ? NAV.rail : w;
}
const dockMax = () => Math.round(window.innerWidth * (window.matchMedia?.(FLOATING).matches ? 0.92 : 0.6));
function readOpenWidth(): number {
  try { const v = Number(localStorage.getItem(NAV_OPEN_KEY)); return v >= NAV.open && v <= NAV.max ? v : NAV.initial; } catch { return NAV.initial; }
}
const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
export const MOD = MAC ? '⌘' : 'Ctrl ';

/** A lazy panel that survives a rebuild: an open tab still holds the old chunk names, so a failed chunk load reloads
 *  the page once (sessionStorage guards against a reload loop). */
function lazyPanel(load: () => Promise<{ default: React.ComponentType }>) {
  return lazy(() => load().then(m => { try { sessionStorage.removeItem('rd.chunkReload'); } catch { /* ignore */ } return m; },
    (err) => {
      let reloaded = false;
      try { reloaded = sessionStorage.getItem('rd.chunkReload') === '1'; sessionStorage.setItem('rd.chunkReload', '1'); } catch { /* ignore */ }
      if (!reloaded && /dynamically imported module|Importing a module script failed|Loading chunk/i.test(String(err?.message ?? err))) {
        location.reload();
        return new Promise<never>(() => {});
      }
      throw err;
    }));
}

const PANEL_COMPONENTS: Record<ViewId, React.LazyExoticComponent<React.ComponentType>> = {
  overview: lazyPanel(() => import('./panels/overview')),
  dag: lazyPanel(() => import('./panels/dag')),
  experiments: lazyPanel(() => import('./panels/experiments')),
  writing: lazyPanel(() => import('./panels/writing')),
  coding: lazyPanel(() => import('./panels/coding')),
  settings: lazyPanel(() => import('./panels/settings')),
};

/** One panel failing must not blank the shell: show the error in place, with a retry. */
class PanelBoundary extends Component<{ children: ReactNode; label: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { console.error(`[${this.props.label}]`, error); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="empty" role="alert">
        <Icon name="warn" size={22} />
        <div className="h3">{this.props.label}</div>
        <div className="muted mono" style={{ maxWidth: 560, fontSize: 'var(--fs-sm)' }}>{String(this.state.error.message || this.state.error)}</div>
        <Button onClick={() => this.setState({ error: null })}>↻</Button>
      </div>
    );
  }
}

export default function App() {
  const { view, project, projects, projectId, navigate, dockOpen, setDockOpen, focusDock } = useApp();
  const t = useT();
  const today = useToday();
  const View = PANEL_COMPONENTS[view];

  // The project the route names, once it has loaded (while switching, `project` is still the previous one); its entry
  // in the project list already knows the kind and views, so the navigation is right before the details arrive.
  const current = project && project.id === projectId ? project : null;
  const known = current ?? projects.find(p => p.id === projectId) ?? null;
  const views = visibleViews(known);
  const hidden = !!known && !views.includes(view);
  useEffect(() => {
    if (known && hidden) navigate(fallbackView(known), null, known.id, { replace: true });
  }, [known, hidden, navigate]);

  const shell = useRef<HTMLDivElement>(null);
  const nav = useResizableWidth('rd.shell.navW', NAV.initial, NAV.rail, NAV.max, { cssVar: '--nav-w', target: shell, snap: snapNav });
  const dock = useResizableWidth('rd.shell.dockW', DOCK.initial, DOCK.min, dockMax, { cssVar: '--dock-w', target: shell });
  const collapsed = nav.width <= NAV.rail;
  const lastOpen = useRef(readOpenWidth());       // what the expand button goes back to
  useEffect(() => {
    if (collapsed || nav.width === lastOpen.current) return;
    lastOpen.current = nav.width;
    try { localStorage.setItem(NAV_OPEN_KEY, String(nav.width)); } catch { /* storage unavailable */ }
  }, [collapsed, nav.width]);
  const { commit: commitNav } = nav;
  const toggleNav = useCallback(() => commitNav(collapsed ? lastOpen.current : NAV.rail), [commitNav, collapsed]);

  // ⌘K jumps anywhere; ⌘J opens the conversation (or closes it when the cursor is already in it).
  const [palette, setPalette] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(MAC ? e.metaKey : e.ctrlKey) || e.altKey || e.shiftKey || !projectId) return;
      if (e.code === 'KeyK') { e.preventDefault(); setPalette(o => !o); }
      if (e.code === 'KeyJ') {
        e.preventDefault();
        if (dockOpen && document.activeElement?.closest('#rd-dock')) setDockOpen(false);
        else focusDock();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [projectId, dockOpen, setDockOpen, focusDock]);

  const main = views.filter(v => v !== 'settings');
  return (
    <div ref={shell} className={`shell${dockOpen && projectId ? ' dock-open' : ''}${collapsed ? ' nav-collapsed' : ''}`} style={{ ...nav.style, ...dock.style }}>
      <nav id="rd-nav" className="sidenav" aria-label={t('app.name')}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="currentColor" /><circle cx="10" cy="11" r="3" fill="var(--paper)" /><circle cx="22" cy="11" r="3" fill="var(--paper)" /><circle cx="16" cy="22" r="3.4" fill="var(--accent)" /><path d="M10 11 16 22 22 11" fill="none" stroke="var(--paper)" strokeWidth="1.6" /></svg></span>
          <b>{t('app.name')}</b>
        </div>
        <ProjectSwitcher current={known} />
        <button type="button" className="nav-item nav-jump" onClick={() => setPalette(true)} disabled={!projectId} title={`${t('nav.jump')} (${MOD}K)`} aria-label={t('nav.jump')}>
          <Icon name="search" /> <span className="grow">{t('nav.jump')}…</span><kbd>{MOD}K</kbd>
        </button>
        <div className="nav-group">
          {main.map(id => <NavItem key={id} id={id} active={view === id} disabled={!projectId} onClick={() => navigate(id)}
            badge={id === 'overview' ? today.count : 0} badgeTitle={t('nav.badge', { n: today.count })} />)}
        </div>
        <div className="grow" />
        {views.includes('settings') && <NavItem id="settings" active={view === 'settings'} disabled={!projectId} onClick={() => navigate('settings')} />}
        <NavFoot />
        <button type="button" className="nav-item nav-toggle" onClick={toggleNav} aria-expanded={!collapsed} aria-controls="rd-nav"
          title={t(collapsed ? 'nav.expand' : 'nav.collapse')} aria-label={t(collapsed ? 'nav.expand' : 'nav.collapse')}>
          <Icon name={collapsed ? 'chevronRight' : 'chevronLeft'} /> <span>{t(collapsed ? 'nav.expand' : 'nav.collapse')}</span>
        </button>
      </nav>
      <ResizeHandle pane={nav} edge="right" label={t('nav.resize')} controls="rd-nav" onToggle={toggleNav} className="nav-handle" />

      <main className="main" aria-live="polite">
        {!projectId ? <NoProject hasProjects={projects.length > 0} /> : (
          <Suspense fallback={<div className="empty"><Spinner /></div>}>
            {current && !hidden ? <PanelBoundary key={`${projectId}:${view}`} label={t(`nav.${view}`)}><View /></PanelBoundary> : <div className="empty"><Spinner /></div>}
          </Suspense>
        )}
      </main>

      {projectId && (dockOpen ? (
        <aside id="rd-dock" className="dock" aria-label={t('agent.dock')}>
          <ResizeHandle pane={dock} edge="left" label={t('agent.resize')} controls="rd-dock" />
          <AgentDock />
        </aside>
      ) : <DockRail pid={projectId} onOpen={focusDock} />)}

      {palette && projectId && <Palette onClose={() => setPalette(false)} />}
    </div>
  );
}

function NavItem({ id, active, disabled, onClick, badge = 0, badgeTitle }: { id: ViewId; active: boolean; disabled: boolean; onClick: () => void; badge?: number; badgeTitle?: string }) {
  const t = useT();
  return (
    <button type="button" className={`nav-item ${active ? 'active' : ''}`} onClick={onClick} disabled={disabled}
      title={t(`nav.${id}`)} aria-label={badge ? `${t(`nav.${id}`)} · ${badgeTitle}` : t(`nav.${id}`)} aria-current={active ? 'page' : undefined}>
      <Icon name={VIEW_ICON[id]} /> <span className="grow">{t(`nav.${id}`)}</span>
      {badge > 0 && <span className="nav-badge num" title={badgeTitle}>{badge}</span>}
    </button>
  );
}

/** The backends' state (both CLIs found, or which one is missing; or the server is unreachable), language and theme. */
function NavFoot() {
  const { health, online } = useApp();
  const t = useT();
  const missing = (['claude', 'codex'] as const).filter(c => health && !health.clis[c]?.ok);
  const state = !online ? 'offline' : !health ? 'loading' : missing.length ? 'missing' : 'ready';
  const text = state === 'offline' ? t('health.offline')
    : state === 'missing' ? t('nav.cliMissing', { cli: missing.map(c => (c === 'claude' ? 'Claude Code' : 'Codex')).join(' · ') })
      : state === 'ready' ? t('nav.cliReady') : t('common.loading');
  return (
    <div className="nav-foot">
      <div className="row nav-status" title={text}>
        <span className={`dot ${state === 'ready' ? 'ok' : state === 'loading' ? '' : 'accent'}`} />
        <span className="ellipsis">{text}</span>
      </div>
      <div className="row nav-prefs">
        <LangSwitch />
        <ThemeSwitch />
      </div>
    </div>
  );
}

/** The folded conversation: one button that opens it, with a dot while an answer is being written. */
function DockRail({ pid, onOpen }: { pid: string; onOpen: () => void }) {
  const t = useT();
  const running = useRunningPanels(pid);
  const { doc } = useSessions(pid);
  const provider = doc?.panels.project?.active ?? 'claude';
  return (
    <div className="dock-rail">
      <button type="button" className="dock-rail-btn" onClick={onOpen} title={`${t('agent.dock')} (${MOD}J)`} aria-label={t('agent.dock')}>
        <ProviderMark provider={provider} size={16} />
        {running.size > 0 && <span className="dot accent dock-rail-dot" />}
      </button>
    </div>
  );
}

function ProjectSwitcher({ current }: { current: ProjectSummary | null }) {
  const { projects, navigate, view } = useApp();
  const t = useT();
  const [adding, setAdding] = useState<'idea' | 'folder' | null>(null);
  const sub = !current ? '' : isResearch(current)
    ? `${t('nav.kind.research')} · ${t(`step.${stepOfStage(current.stage)}`)}` : t('nav.kind.engineering');
  return (
    <>
      <Menu align="left" button={(open, toggle) => (
        <button type="button" className="project-btn" aria-expanded={open} onClick={toggle} title={current?.name ?? t('nav.projects')}>
          <span className="project-initial" aria-hidden="true">{(current?.name ?? '?').slice(0, 1).toUpperCase()}</span>
          <span className="project-text">
            <span className="ellipsis project-name">{current?.name ?? t('nav.projects')}</span>
            {sub && <span className="ellipsis faint project-sub">{sub}{current?.demo ? ` · ${t('nav.demo')}` : ''}</span>}
          </span>
          <Icon name="chevronDown" size={14} />
        </button>
      )}>
        {(close) => (
          <div style={{ minWidth: 280 }}>
            <div className="label" style={{ padding: '6px 9px' }}>{t('nav.projects')}</div>
            {projects.map(p => (
              <button key={p.id} type="button" className="menu-item" onClick={() => { navigate(view, null, p.id); close(); }}>
                <span className={`dot ${p.id === current?.id ? 'accent' : ''}`} />
                <span className="col grow" style={{ gap: 0, minWidth: 0 }}>
                  <span className="ellipsis">{p.name}</span>
                  <span className="faint mono ellipsis" style={{ fontSize: 10.5 }}>{p.root}</span>
                </span>
                {p.kind === 'engineering' && <span className="badge process">{t('nav.kind.engineering')}</span>}
                {p.demo && <span className="badge">{t('nav.demo')}</span>}
              </button>
            ))}
            <hr style={{ border: 0, borderTop: '1px solid var(--rule)', margin: '6px 4px' }} />
            <button type="button" className="menu-item" onClick={() => { setAdding('idea'); close(); }}><Icon name="sparkle" /> {t('np.menu.fromIdea')}</button>
            <button type="button" className="menu-item" onClick={() => { setAdding('folder'); close(); }}><Icon name="folder" /> {t('np.menu.addFolder')}</button>
          </div>
        )}
      </Menu>
      {adding === 'idea' && <NewProjectDialog onClose={() => setAdding(null)} />}
      {adding === 'folder' && <AddProjectDialog onClose={() => setAdding(null)} />}
    </>
  );
}

function AddProjectDialog({ onClose }: { onClose: () => void }) {
  const { reloadProjects, navigate } = useApp();
  const { lang } = useI18n();
  const t = useT();
  const [root, setRoot] = useState('');
  const [name, setName] = useState('');
  const [kind, setKind] = useState<ProjectKind>('research');
  const [state, setState] = useState('');
  const [error, setError] = useState<string | null>(null);
  const stateOk = !state.trim() || /^\.research-[a-z0-9][a-z0-9-]{0,40}$/.test(state.trim());
  const submit = async () => {
    try {
      const p = await post<{ id: string }>('/api/projects', { root, name: name || undefined, kind, state: state.trim() || undefined });
      await reloadProjects();
      navigate('overview', null, p.id);
      onClose();
    } catch (e) { setError(String((e as Error).message)); }
  };
  return (
    <Dialog title={t('nav.addProject')} onClose={onClose} footer={<><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" onClick={submit} disabled={!root.trim() || !stateOk}>{t('common.confirm')}</Button></>}>
      <div className="col" style={{ gap: 12 }}>
        <label className="field"><span className="label">{lang === 'zh' ? '项目文件夹（绝对路径）' : 'Project folder (absolute path)'}</span>
          <input className="input mono" value={root} onChange={e => setRoot(e.target.value)} placeholder="~/Research/MyProject" autoFocus /></label>
        <label className="field"><span className="label">{lang === 'zh' ? '名称（可选）' : 'Name (optional)'}</span>
          <input className="input" value={name} onChange={e => setName(e.target.value)} /></label>
        <div className="field">
          <span className="label">{t('nav.kind.label')}</span>
          <div className="row">
            <Segmented<ProjectKind> ariaLabel={t('nav.kind.label')} value={kind} onChange={setKind}
              options={[{ value: 'research', label: t('nav.kind.research') }, { value: 'engineering', label: t('nav.kind.engineering') }]} />
          </div>
          <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{t(kind === 'engineering' ? 'nav.kind.engineeringHint' : 'nav.kind.researchHint')}</span>
        </div>
        <label className="field"><span className="label">{lang === 'zh' ? '状态文件夹（可选）' : 'State folder (optional)'}</span>
          <input className="input mono" value={state} onChange={e => setState(e.target.value)} placeholder=".research-<name>" aria-invalid={!stateOk} />
          <span className={stateOk ? 'muted' : 'notice accent'} style={{ fontSize: 'var(--fs-sm)' }}>{lang === 'zh'
            ? '只在这个文件夹已经属于另一个项目时填写，例如 .research-paper2：两个项目共用同一批代码和文件，各自保存地图、对话和设置。'
            : 'Only when another project already uses this folder, e.g. .research-paper2: both projects share the files and keep their own map, conversation and settings.'}</span></label>
        <p className="muted" style={{ margin: 0, fontSize: 'var(--fs-sm)' }}>{lang === 'zh'
          ? `Research Deck 会在该文件夹下创建 ${state.trim() || '.research'}/（研究地图、对话、写作设置等），不会改动其他文件。`
          : `Research Deck creates ${state.trim() || '.research'}/ in that folder (research map, conversation, writing settings); nothing else is touched.`}</p>
        {error && <div className="notice accent">{error}</div>}
      </div>
    </Dialog>
  );
}

function LangSwitch() {
  const { lang, setLang } = useI18n();
  return <Segmented ariaLabel="Language" value={lang} onChange={setLang} options={[{ value: 'zh', label: '中' }, { value: 'en', label: 'EN' }]} />;
}

function ThemeSwitch() {
  const { theme, setTheme } = useApp();
  const t = useT();
  const next = theme === 'auto' ? 'light' : theme === 'light' ? 'dark' : 'auto';
  return <IconButton icon={theme === 'dark' ? 'moon' : theme === 'light' ? 'sun' : 'split'} label={`${t(`theme.${theme}`)} → ${t(`theme.${next}`)}`} onClick={() => setTheme(next)} />;
}

function NoProject({ hasProjects }: { hasProjects: boolean }) {
  const t = useT();
  const [adding, setAdding] = useState<'idea' | 'folder' | null>(null);
  if (hasProjects) return <div className="empty"><Spinner /></div>;
  return (
    <div className="empty">
      <Icon name="folder" size={22} />
      <div className="h3">{t('np.empty.title')}</div>
      <div className="muted">{t('np.empty.body')}</div>
      <div className="row wrap" style={{ justifyContent: 'center' }}>
        <Button variant="primary" icon="sparkle" onClick={() => setAdding('idea')}>{t('np.menu.fromIdea')}</Button>
        <Button icon="folder" onClick={() => setAdding('folder')}>{t('np.menu.addFolder')}</Button>
      </div>
      {adding === 'idea' && <NewProjectDialog onClose={() => setAdding(null)} />}
      {adding === 'folder' && <AddProjectDialog onClose={() => setAdding(null)} />}
    </div>
  );
}
