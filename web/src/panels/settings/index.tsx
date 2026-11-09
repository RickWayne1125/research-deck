// Settings: how new projects start (folder, survey, stage rules), the outline templates, the resource pools, the integrations Research Deck found (Claude Code and
// Codex CLIs, the figure apps), appearance, and where things live. Model, effort and permission belong to the
// conversation (its header).
import { useEffect, useState, type ReactNode } from 'react';
import { useApp } from '../../state/app';
import { useT } from '../../i18n';
import { ErrorNote, PanelHead, Spinner, useLoad } from '../../components/ui';
import { agentApi } from '../../agent/api';
import { CopyButton, ProviderMark, providerLabel } from '../../agent/parts';
import { NewProjectSettingsSection } from '../../start/NewProjectSettings';
import { OutlineTemplatesSection } from '../outline/Templates';
import { PoolsSection } from '../../pools/PoolsSection';
import { ZoteroSection } from '../../integrations/ZoteroSection';
import { DocmostSection } from '../../integrations/DocmostSection';
import { AppearanceSection } from './Appearance';
import './settings.css';
import './i18n';

const SECTIONS = ['newProjects', 'templates', 'pools', 'zotero', 'docmost', 'integrations', 'appearance', 'about'] as const;
type Section = (typeof SECTIONS)[number];
/** The tabs (Radix Tabs, as in the preview) and the sections on each, in the order they show. */
const TABS = { general: ['appearance', 'integrations', 'about'], new: ['newProjects', 'templates'], pools: ['pools'], lit: ['zotero', 'docmost'] } as const;
type Tab = keyof typeof TABS;
const TAB_KEY = 'rd.st.tab';
const tabOf = (s: string | null | undefined): Tab | null =>
  (Object.keys(TABS) as Tab[]).find(k => (TABS[k] as readonly string[]).includes(s ?? '')) ?? null;
/** Sections wide enough to take the whole row */
const WIDE = new Set<Section>(['newProjects', 'templates', 'pools']);

export default function SettingsPanel() {
  const { projectId, project, sub } = useApp();
  const t = useT();
  const pid = projectId!;
  const [tab, setTabState] = useState<Tab>(() => {
    const fromRoute = tabOf(sub);
    if (fromRoute) return fromRoute;
    try { const v = localStorage.getItem(TAB_KEY) as Tab | null; return v && v in TABS ? v : 'general'; } catch { return 'general'; }
  });
  const setTab = (next: Tab) => { setTabState(next); try { localStorage.setItem(TAB_KEY, next); } catch { /* storage unavailable */ } };
  // #/<p>/settings/<section>: its tab, scrolled to it
  useEffect(() => {
    const at = tabOf(sub);
    if (!at) return;
    setTabState(at);
    window.setTimeout(() => document.getElementById(`st-${sub}`)?.scrollIntoView({ block: 'start' }), 80);
  }, [sub]);
  const shows = (id: Section) => (TABS[tab] as readonly string[]).includes(id) && (id !== 'templates' || project?.kind !== 'engineering');
  const body: Record<Section, () => ReactNode> = {
    newProjects: () => <NewProjectSettingsSection />,
    templates: () => <OutlineTemplatesSection />,
    pools: () => <PoolsSection />,
    zotero: () => <ZoteroSection />,
    docmost: () => <DocmostSection />,
    integrations: () => <IntegrationsSection />,
    appearance: () => <AppearanceSection />,
    about: () => <AboutSection pid={pid} />,
  };
  const title: Record<Section, string> = {
    newProjects: t('np.st.title'), templates: t('ol.tpl.title'), pools: t('pl.title'), zotero: t('ig.zotero'), docmost: t('ig.docmost'),
    integrations: t('st.sec.integrations'), appearance: t('st.sec.appearance'), about: t('st.sec.about'),
  };
  return (
    <div className="panel st">
      <PanelHead title={t('nav.settings')} subtitle={project ? `${project.name} · ${t('st.subtitle')}` : t('st.subtitle')} />
      <div className="tabs st-tabs" role="tablist" aria-label={t('nav.settings')}>
        {(Object.keys(TABS) as Tab[]).map(k => (
          <button key={k} type="button" role="tab" className="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{t(`st.tab.${k}`)}</button>
        ))}
      </div>
      <div className="panel-body st-body" role="tabpanel">
        <div className="st-main">
          {(TABS[tab] as readonly Section[]).filter(shows).map(id => (
            <Section key={id} id={id} title={title[id]} desc={t(`st.desc.${id}`)} wide={WIDE.has(id)}>{body[id]()}</Section>
          ))}
        </div>
      </div>
    </div>
  );
}

function Section({ id, title, desc, wide, children }: { id: Section; title: string; desc?: string; wide?: boolean; children: ReactNode }) {
  return (
    <section id={`st-${id}`} className={`st-sec${wide ? ' wide' : ''}`} aria-labelledby={`st-${id}-h`}>
      <div className="st-sec-top">
        <h2 id={`st-${id}-h`} className="st-sec-title">{title}</h2>
        {desc && <span className="st-sec-desc">{desc}</span>}
      </div>
      {children}
    </section>
  );
}

// ------------------------------------------------------------------ integrations

function IntegrationsSection() {
  const t = useT();
  const { health } = useApp();
  if (!health) return <div className="empty"><Spinner /></div>;
  const apps: { id: keyof typeof health.apps; label: string }[] = [
    { id: 'drawio', label: 'draw.io' }, { id: 'omnigraffle', label: 'OmniGraffle' }, { id: 'datagraph', label: 'DataGraph' },
  ];
  return (
    <div className="col st-int">
      {health.fake_agent && <div className="notice">{t('st.int.fakeAgent')}</div>}
      <div className="h3 st-subhead">{t('st.int.clis')}</div>
      <dl className="kv st-kv">
        {(['claude', 'codex'] as const).map(c => {
          const cli = health.clis[c];
          return [
            <dt key={`${c}-k`} className="row"><ProviderMark provider={c} size={12} /> {providerLabel(c, t)}</dt>,
            <dd key={`${c}-v`} className="row wrap st-int-val">
              <span className={`dot ${cli.ok ? 'ok' : 'accent'}`} /><span>{cli.ok ? t('st.int.found') : t('st.int.missing')}</span>
              {cli.version && <span className="mono faint">{cli.version}</span>}
              {cli.path && <span className="mono st-path ellipsis" title={cli.path}>{cli.path}</span>}
            </dd>,
          ];
        })}
      </dl>
      {(!health.clis.claude.ok || !health.clis.codex.ok) && <p className="st-hint">{t('st.int.cliHint')}</p>}

      <div className="h3 st-subhead">{t('st.int.apps')}</div>
      <dl className="kv st-kv">
        {apps.map(a => [
          <dt key={`${a.id}-k`}>{a.label}</dt>,
          <dd key={`${a.id}-v`} className="row wrap st-int-val">
            <span className={`dot ${health.apps[a.id].installed ? 'ok' : ''}`} />
            <span>{health.apps[a.id].installed ? t('st.int.installed') : t('st.int.notInstalled')}</span>
            {health.apps[a.id].path && <span className="mono faint st-path ellipsis">{health.apps[a.id].path}</span>}
          </dd>,
        ])}
      </dl>

    </div>
  );
}

// ------------------------------------------------------------------ about

function PathRow({ label, path }: { label: string; path: string | undefined }) {
  const t = useT();
  if (!path) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd className="row st-int-val"><span className="mono st-path ellipsis" title={path}>{path}</span><CopyButton text={path} label={t('common.copy')} /></dd>
    </>
  );
}

function AboutSection({ pid }: { pid: string }) {
  const t = useT();
  const { health } = useApp();
  const cfg = useLoad(() => agentApi.mcpConfig(pid), [pid]);
  const paths = cfg.data?.paths;
  const docs = paths ? ['ARCHITECTURE.md', 'API.md', 'DAG.md'].map(f => `${paths.docs}/${f}`) : [];
  return (
    <dl className="kv st-kv">
      <dt>{t('st.about.version')}</dt><dd className="mono">{health?.version ?? '—'}</dd>
      <dt>{t('st.about.server')}</dt><dd className="mono">{cfg.data?.env.RD_URL ?? location.origin}</dd>
      <PathRow label={t('st.about.app')} path={paths?.app_root} />
      <PathRow label={t('st.about.local')} path={paths?.local_dir} />
      <PathRow label={t('st.about.project')} path={paths?.project_root} />
      <PathRow label={t('st.about.research')} path={paths?.research_dir} />
      {docs.length > 0 && (
        <>
          <dt>{t('st.about.docs')}</dt>
          <dd className="col" style={{ gap: 2 }}>
            <span className="st-hint st-flush">{t('st.about.docsHint')}</span>
            {docs.map(d => <span key={d} className="row st-int-val"><span className="mono st-path ellipsis" title={d}>{d}</span><CopyButton text={d} label={t('common.copy')} /></span>)}
          </dd>
        </>
      )}
      {cfg.error && <><dt /><dd><ErrorNote error={cfg.error} onRetry={cfg.reload} /></dd></>}
    </dl>
  );
}
