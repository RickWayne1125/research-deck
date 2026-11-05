// Today for an engineering project (a PR, an integration effort): no research pipeline, so no DAG calls at all.
// Header with the kind badge; the repositories (GET /git/repos) and the recent commits of the one the Coding panel
// shows (GET /git/log?repo=&limit=15) beside the documents (/writing/docs), experiment records (/experiments) and
// figures (/figures). Every card loads on its own and says "unavailable" on an error instead of failing the page.
import { useState } from 'react';
import { get, p } from '../../api/client';
import { Badge, IconButton, PanelHead } from '../../components/ui';
import { Icon } from '../../components/icons';
import { FIGURES, useApp } from '../../state/app';
import { useRelTime, useT } from '../../i18n';
import type { Experiment, ExperimentStatus, Figure, GitCommit, ProjectDetail, WritingDoc } from '../../types';
import { currentRepo, fetchRepos, setCurrentRepo, type RepoInfo } from '../coding/api';
import { useQuiet } from './data';
import { tOr, usePlural } from './parts';

const COMMITS = 15;
const MAX_EXPS = 6;
const MAX_FIGS = 6;
const isArray = (v: unknown) => Array.isArray(v);
const repoKey = (r: RepoInfo | null | undefined) => r?.repo ?? '';
const timeOf = (e: Experiment) => Date.parse(e.finished_at ?? e.started_at ?? '') || 0;

const EXP_TONE: Record<ExperimentStatus, 'process' | 'ok' | 'accent' | undefined> = {
  running: 'process', queued: 'process', succeeded: 'ok', failed: 'accent', planned: undefined, cancelled: undefined, unknown: undefined,
};
const EXP_ORDER: ExperimentStatus[] = ['running', 'queued', 'failed', 'succeeded', 'planned', 'cancelled', 'unknown'];

export function EngineeringOverview({ project }: { project: ProjectDetail }) {
  const t = useT();
  const pid = project.id;
  const [n, setN] = useState(0);       // the refresh button reloads every card
  const repos = useQuiet(() => fetchRepos(pid), [pid, n], ['file'], isArray);
  const docs = useQuiet(() => get<WritingDoc[]>(p(pid, '/writing/docs')), [pid, n], ['writing', 'file'], isArray);
  const exps = useQuiet(() => get<Experiment[]>(p(pid, '/experiments')), [pid, n], ['experiments'], isArray);
  const figs = useQuiet(() => get<Figure[]>(p(pid, '/figures')), [pid, n], ['figures'], isArray);

  // The repository whose commits show: the one the Coding panel shows (remembered per project), else the first.
  const [picked, setPicked] = useState<string>(() => currentRepo(pid) ?? '');
  const gitRepos = (repos ?? []).filter(r => r.is_repo);
  const selected = gitRepos.find(r => repoKey(r) === picked) ?? gitRepos[0] ?? null;
  const pick = (r: RepoInfo) => { setPicked(repoKey(r)); setCurrentRepo(pid, r.repo); };

  return (
    <div className="panel ov">
      <PanelHead title={project.name} subtitle={project.summary || t('ov.noSummary')}>
        <Badge tone="process" title={t('ov.eng.badgeTitle')}>{t('ov.eng.badge')}</Badge>
        <IconButton icon="refresh" label={t('common.refresh')} onClick={() => setN(x => x + 1)} />
      </PanelHead>
      <div className="panel-body">
        <div className="ov-body">
          <div className="ov-eng-grid">
            <div className="ov-eng-col">
              <Repos pid={pid} repos={repos} current={selected} />
              {selected && <Commits pid={pid} repos={gitRepos} repo={selected} onPick={pick} n={n} />}
            </div>
            <div className="ov-eng-col">
              <Docs docs={docs} />
              <Experiments exps={exps} />
              <Figures figs={figs} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A card frame: title, a count, and the "loading / unavailable" states of a quiet load. */
function Card<T>({ title, icon, value, count, action, children }: {
  title: string; icon: string; value: T | null | undefined; count?: number; action?: React.ReactNode;
  children: (v: T) => React.ReactNode;
}) {
  const t = useT();
  return (
    <section className="card ov-eng-card" aria-label={title}>
      <div className="card-head">
        <Icon name={icon} size={14} className="ov-eng-icon" />
        <h2 className="h3 grow">{title}</h2>
        {count != null && <span className="badge num">{count}</span>}
        {action}
      </div>
      {value === undefined ? <div className="card-body faint ov-small">…</div>
        : value === null ? <div className="card-body faint ov-small">{t('ov.sum.na')}</div>
        : children(value)}
    </section>
  );
}

function RepoState({ repo }: { repo: RepoInfo }) {
  const t = useT();
  const plural = usePlural();
  if (!repo.is_repo) return <Badge>{t('ov.eng.repos.notRepo')}</Badge>;
  if (repo.dirty == null) {
    const slow = /slow/i.test(repo.error ?? '');
    return <Badge tone={slow ? 'warn' : 'accent'} title={repo.error ?? undefined}>{t(slow ? 'ov.eng.repos.slow' : 'ov.eng.repos.error')}</Badge>;
  }
  return repo.dirty > 0
    ? <Badge tone="warn">{plural('ov.eng.repos.dirty', repo.dirty)}</Badge>
    : <Badge tone="ok">{t('ov.eng.repos.clean')}</Badge>;
}

function Repos({ pid, repos, current }: { pid: string; repos: RepoInfo[] | null | undefined; current: RepoInfo | null }) {
  const t = useT();
  const { navigate } = useApp();
  const open = (r: RepoInfo) => { setCurrentRepo(pid, r.repo); navigate('coding', 'changes'); };
  return (
    <Card title={t('ov.eng.repos')} icon="branch" value={repos} count={repos?.length}>
      {list => list.length === 0 ? <div className="card-body muted ov-small">{t('ov.eng.repos.empty')}</div> : (
        <div className="list">
          {list.map(r => {
            const isCurrent = !!current && r.is_repo && repoKey(r) === repoKey(current);
            return (
              <button key={repoKey(r) || r.label} type="button" className={`list-item ov-eng-repo${isCurrent ? ' active' : ''}`}
                onClick={() => open(r)} aria-current={isCurrent || undefined}
                title={`${t('ov.eng.repos.open', { repo: r.label })}${isCurrent ? ` · ${t('ov.eng.repos.current')}` : ''}`}>
                <span className="ov-eng-repo-main">
                  <span className="ov-eng-repo-label ellipsis">{r.label}</span>
                  <span className="ov-eng-repo-meta">
                    {r.is_repo && <span className="mono ellipsis">{r.branch ?? t('ov.eng.repos.detached')}</span>}
                    {r.head && <span className="mono faint">{r.head.slice(0, 7)}</span>}
                    {r.repo && r.repo !== r.label && <span className="mono faint ellipsis">{r.repo}</span>}
                  </span>
                </span>
                <RepoState repo={r} />
                <Icon name="chevronRight" size={14} className="ov-eng-go" />
              </button>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function Commits({ pid, repos, repo, onPick, n }: { pid: string; repos: RepoInfo[]; repo: RepoInfo; onPick: (r: RepoInfo) => void; n: number }) {
  const t = useT();
  const rel = useRelTime();
  const { navigate } = useApp();
  const key = repoKey(repo);
  const log = useQuiet(() => get<GitCommit[]>(p(pid, '/git/log'), { limit: COMMITS, repo: repo.repo }), [pid, key, n], ['file'], isArray);
  const picker = repos.length > 1 && (
    <select className="select ov-eng-select" aria-label={t('ov.eng.commits.repo')} title={t('ov.eng.commits.repo')} value={key}
      onChange={e => { const r = repos.find(x => repoKey(x) === e.target.value); if (r) onPick(r); }}>
      {repos.map(r => <option key={repoKey(r)} value={repoKey(r)}>{r.label}</option>)}
    </select>
  );
  return (
    <Card title={t('ov.eng.commits')} icon="history" value={log} action={(
      <>
        {picker}
        <button type="button" className="ov-link ov-small" onClick={() => { setCurrentRepo(pid, repo.repo); navigate('coding', 'changes'); }}>
          {t('ov.eng.commits.open')}
        </button>
      </>
    )}>
      {commits => commits.length === 0 ? <div className="card-body muted ov-small">{t('ov.eng.commits.empty')}</div> : (
        <ol className="ov-eng-commits">
          {commits.map(c => (
            <li key={c.sha} className="ov-eng-commit">
              <span className="mono ov-eng-sha" title={c.sha}>{c.short}</span>
              <span className="ov-eng-commit-main">
                <span className="ov-eng-commit-subject" title={c.subject}>{c.subject}</span>
                <span className="ov-eng-commit-meta">
                  <span className="ellipsis">{c.author}</span>
                  {c.refs.map(r => <span key={r} className="chip">{r}</span>)}
                </span>
              </span>
              <time className="faint num ov-xs ov-nowrap" dateTime={c.date} title={c.date}>{rel(c.date)}</time>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function Docs({ docs }: { docs: WritingDoc[] | null | undefined }) {
  const t = useT();
  const rel = useRelTime();
  const plural = usePlural();
  const { navigate } = useApp();
  return (
    <Card title={t('ov.eng.docs')} icon="writing" value={docs} count={docs?.length}>
      {list => list.length === 0 ? <div className="card-body muted ov-small">{t('ov.eng.docs.empty')}</div> : (
        <div className="list">
          {[...list].sort((a, b) => b.updated_at - a.updated_at).map(d => (
            <button key={d.path} type="button" className="list-item ov-eng-doc" onClick={() => navigate('writing', d.path)} title={d.path}>
              <span className="ov-eng-doc-main">
                <span className="ellipsis ov-eng-doc-title">{d.title}</span>
                <span className="mono faint ellipsis ov-xs">{d.path}</span>
              </span>
              <span className="ov-eng-doc-meta">
                <Badge>{d.kind.toUpperCase()}</Badge>
                <span className="num">{plural('ov.eng.docs.words', d.words)}</span>
                <span className="faint">{rel(d.updated_at)}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}

function Experiments({ exps }: { exps: Experiment[] | null | undefined }) {
  const t = useT();
  const rel = useRelTime();
  const { navigate } = useApp();
  return (
    <Card title={t('ov.eng.exps')} icon="experiments" value={exps} count={exps?.length}
      action={exps?.length ? <button type="button" className="ov-link ov-small" onClick={() => navigate('experiments')}>{t('ov.sum.open', { panel: t('nav.experiments') })}</button> : undefined}>
      {list => {
        if (list.length === 0) return <div className="card-body muted ov-small">{t('ov.eng.exps.empty')}</div>;
        const counts = EXP_ORDER.map(s => [s, list.filter(e => e.status === s).length] as const).filter(([, k]) => k > 0);
        const recent = [...list].sort((a, b) => timeOf(b) - timeOf(a)).slice(0, MAX_EXPS);
        return (
          <>
            <div className="ov-eng-counts">
              {counts.map(([s, k]) => <Badge key={s} tone={EXP_TONE[s]}><span className="num">{k}</span> {t(`ov.eng.exps.status.${s}`)}</Badge>)}
            </div>
            <div className="list">
              {recent.map(e => {
                const when = e.finished_at ?? e.started_at;
                return (
                  <button key={e.id} type="button" className="list-item ov-eng-exp" onClick={() => navigate('experiments')} title={e.id}>
                    <span className="ellipsis grow">{e.title || e.id}</span>
                    <Badge tone={EXP_TONE[e.status]}>{tOr(t, `ov.eng.exps.status.${e.status}`, String(e.status))}</Badge>
                    <span className="faint num ov-xs ov-nowrap">{when ? rel(when) : '—'}</span>
                  </button>
                );
              })}
            </div>
            {list.length > recent.length && <div className="card-body faint ov-xs ov-eng-more">{t('ov.eng.exps.more', { n: list.length - recent.length })}</div>}
          </>
        );
      }}
    </Card>
  );
}

function Figures({ figs }: { figs: Figure[] | null | undefined }) {
  const t = useT();
  const plural = usePlural();
  const { navigate } = useApp();
  return (
    <Card title={t('ov.eng.figs')} icon="visualization" value={figs} count={figs?.length}
      action={figs?.length ? <button type="button" className="ov-link ov-small" onClick={() => navigate('writing', FIGURES)}>{t('ov.sum.open', { panel: t('wr.tab.figures') })}</button> : undefined}>
      {list => {
        if (list.length === 0) return <div className="card-body muted ov-small">{t('ov.eng.figs.empty')}</div>;
        const attention = list.filter(f => f.status === 'stale' || f.status === 'error').length;
        const shown = [...list].sort((a, b) => (Date.parse(b.updated_at ?? '') || 0) - (Date.parse(a.updated_at ?? '') || 0)).slice(0, MAX_FIGS);
        return (
          <>
            {attention > 0 && <div className="ov-eng-counts"><Badge tone="warn">{plural('ov.sum.figures.stale', attention)}</Badge></div>}
            <div className="ov-eng-figs">
              {shown.map(f => (
                <button key={f.id} type="button" className="ov-eng-fig" onClick={() => navigate('writing', `${FIGURES}/${f.id}`)} title={f.source}>
                  <span className="ov-eng-thumb">
                    {f.preview ? <img src={f.preview} alt="" loading="lazy" /> : <span className="faint ov-xs">{t('ov.eng.figs.noPreview')}</span>}
                  </span>
                  <span className="ov-eng-fig-meta">
                    <span className="ellipsis ov-eng-fig-title">{f.title}</span>
                    {f.status && f.status !== 'ok' && (
                      <span className={`ov-xs ${f.status === 'error' ? 'ov-eng-bad' : f.status === 'stale' ? 'ov-warn' : 'faint'}`}>{tOr(t, `ov.eng.figs.status.${f.status}`, String(f.status))}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
            {list.length > shown.length && <div className="card-body faint ov-xs ov-eng-more">{t('ov.eng.figs.more', { n: list.length - shown.length })}</div>}
          </>
        );
      }}
    </Card>
  );
}
