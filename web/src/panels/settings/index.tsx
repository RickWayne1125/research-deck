// Settings: how new projects start (folder, survey, stage rules), the integrations Research Deck found (Claude Code and
// Codex CLIs, the figure apps), appearance, and where things live. Model, effort and permission belong to the
// conversation (its header).
import { type ReactNode } from 'react';
import { useApp } from '../../state/app';
import { useI18n, useT } from '../../i18n';
import { ErrorNote, PanelHead, Segmented, Spinner, useLoad } from '../../components/ui';
import { agentApi } from '../../agent/api';
import { CopyButton, ProviderMark, providerLabel } from '../../agent/parts';
import { NewProjectSettingsSection } from '../../start/NewProjectSettings';
import './settings.css';
import './i18n';

const SECTIONS = ['newProjects', 'integrations', 'appearance', 'about'] as const;
type Section = (typeof SECTIONS)[number];

export default function SettingsPanel() {
  const { projectId, project } = useApp();
  const t = useT();
  const pid = projectId!;
  return (
    <div className="panel st">
      <PanelHead title={t('nav.settings')} subtitle={project ? `${project.name} · ${t('st.subtitle')}` : t('st.subtitle')} />
      <div className="panel-body st-body">
        <div className="st-main">
          <Section id="newProjects" title={t('np.st.title')}><NewProjectSettingsSection /></Section>
          <Section id="integrations" title={t('st.sec.integrations')}><IntegrationsSection /></Section>
          <Section id="appearance" title={t('st.sec.appearance')}><AppearanceSection /></Section>
          <Section id="about" title={t('st.sec.about')}><AboutSection pid={pid} /></Section>
        </div>
      </div>
    </div>
  );
}

function Section({ id, title, children }: { id: Section; title: string; children: ReactNode }) {
  return (
    <section id={`st-${id}`} className="st-sec" aria-labelledby={`st-${id}-h`}>
      <h2 id={`st-${id}-h`} className="h2 st-sec-title">{title}</h2>
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

// ------------------------------------------------------------------ appearance

function AppearanceSection() {
  const t = useT();
  const { lang, setLang } = useI18n();
  const { theme, setTheme } = useApp();
  return (
    <dl className="kv st-kv st-appearance">
      <dt>{t('st.app.lang')}</dt>
      <dd className="col" style={{ gap: 4, alignItems: 'flex-start' }}>
        <Segmented ariaLabel={t('st.app.lang')} value={lang} onChange={setLang}
          options={[{ value: 'zh', label: t('lang.zh') }, { value: 'en', label: t('lang.en') }]} />
        <span className="st-hint st-flush">{t('st.app.langHint')}</span>
      </dd>
      <dt>{t('st.app.theme')}</dt>
      <dd>
        <Segmented ariaLabel={t('st.app.theme')} value={theme} onChange={setTheme}
          options={[{ value: 'auto', label: t('theme.auto') }, { value: 'light', label: t('theme.light') }, { value: 'dark', label: t('theme.dark') }]} />
      </dd>
    </dl>
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
