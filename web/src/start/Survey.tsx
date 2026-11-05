// The early survey on Today: the card while it runs (its steps, then the papers as they download), the same card
// when it stopped or failed (with a retry), and the project-folder card once it is done.
import { useEffect, useState } from 'react';
import { Button, IconButton, Spinner } from '../components/ui';
import { Icon } from '../components/icons';
import { useApp } from '../state/app';
import { useT, type TFunc } from '../i18n';
import { SOURCE_LABEL, SURVEY_STEPS, startApi, type Survey, type SurveyPaper, type SurveyStep } from './api';
import './i18n';
import './start.css';

/** "6 分钟" / "40 s" between two timestamps (or until now). */
export function duration(t: TFunc, from: string, to?: string | null): string {
  const s = Math.max(0, Math.round(((to ? Date.parse(to) : Date.now()) - Date.parse(from)) / 1000));
  return s < 90 ? t('sv.sec', { n: s }) : t('sv.min', { n: Math.round(s / 60) });
}

const DISMISS_KEY = 'rd.survey.dismissed';
export function isDismissed(pid: string, id: string): boolean {
  try { return localStorage.getItem(`${DISMISS_KEY}.${pid}`) === id; } catch { return false; }
}
export function dismiss(pid: string, id: string): void {
  try { localStorage.setItem(`${DISMISS_KEY}.${pid}`, id); } catch { /* storage unavailable */ }
}

/** Downloaded, link-only and failed papers. */
export function paperCounts(s: Survey) {
  const by = (st: SurveyPaper['status']) => s.papers.filter(p => p.status === st).length;
  return { done: by('done'), link: by('link'), failed: by('failed'), wanted: s.papers.filter(p => p.status !== 'link').length };
}

export function SurveyCard({ pid, survey, onDismiss }: { pid: string; survey: Survey; onDismiss?: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, tick] = useState(0);
  const running = survey.status === 'running';
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => tick(n => n + 1), 5000);
    return () => window.clearInterval(id);
  }, [running]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const showPapers = survey.papers.length > 0 && (survey.steps.download !== 'pending' || !running);
  return (
    <section className="card sv-card" aria-labelledby="sv-title">
      <div className="sv-head">
        <div className="col" style={{ gap: 2, minWidth: 0 }}>
          <h2 id="sv-title" className="sv-h2">{t('sv.title')} <span className={`chip sv-chip is-${survey.status}`}>{t(`sv.status.${survey.status}`)}</span></h2>
          <span className="faint sv-small">
            {running ? `${t('sv.elapsed', { t: duration(t, survey.created_at) })} · ${t('sv.away')}`
              : t('sv.took', { t: duration(t, survey.created_at, survey.finished_at) })}
          </span>
        </div>
        <span className="grow" />
        {running
          ? <Button size="sm" icon="stop" disabled={busy} onClick={() => act(() => startApi.cancelSurvey(pid))}>{t('sv.stop')}</Button>
          : <Button size="sm" icon="refresh" disabled={busy} onClick={() => act(() => startApi.startSurvey(pid))}>{busy && <Spinner />}{t('sv.retry')}</Button>}
        {!running && onDismiss && <IconButton icon="close" label={t('common.close')} onClick={onDismiss} />}
      </div>
      {survey.status === 'error' && survey.error && <div className="notice accent sv-note" role="alert"><Icon name="warn" /><span>{t('sv.error', { msg: survey.error })}</span></div>}
      {survey.status === 'cancelled' && <div className="notice sv-note"><Icon name="info" /><span>{t('sv.cancelled')}</span></div>}
      {error && <div className="notice accent sv-note" role="alert"><Icon name="warn" /><span>{error}</span></div>}
      <ol className="sv-steps">
        {SURVEY_STEPS.map(step => <StepRow key={step} step={step} survey={survey} />)}
      </ol>
      {survey.warnings.length > 0 && (
        <ul className="sv-warnings faint">{survey.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}
      {showPapers && <PaperTable survey={survey} />}
      {survey.agent && <div className="faint sv-small sv-agent">{t('sv.agent', { agent: survey.agent.model })}</div>}
    </section>
  );
}

function StepRow({ step, survey }: { step: SurveyStep; survey: Survey }) {
  const t = useT();
  const state = survey.steps[step];
  const c = paperCounts(survey);
  const reused = survey.papers.filter(p => p.existing).length;
  const label = {
    frame: t('sv.step.frame'),
    search: t('sv.step.search', { sources: survey.options.sources.map(s => SOURCE_LABEL[s]).join('、') }),
    select: t('sv.step.select'),
    download: t('sv.step.download', { dir: survey.options.papers_dir }),
    draft: t('sv.step.draft'),
    write: t('sv.step.write', { file: survey.files.survey ?? 'notes/survey.md' }),
  }[step];
  let meta: string | null = null;
  let extra: React.ReactNode = null;
  if (state === 'skipped') meta = t('sv.skipped');
  else if (step === 'frame' && survey.queries.length) {
    extra = <div className="sv-queries">{survey.queries.map(q => <span key={q} className="chip">{q}</span>)}</div>;
  } else if (step === 'search' && survey.search) {
    meta = t('sv.found', { n: survey.search.found });
    const silent = Object.entries(survey.search.sources).filter(([, v]) => v.failed > 0 && v.found === 0);
    if (silent.length) extra = silent.map(([src, v]) => (
      <div key={src} className="faint sv-small">{t('sv.sourceFailed', { source: SOURCE_LABEL[src as keyof typeof SOURCE_LABEL] ?? src, error: v.error ?? '' })}</div>
    ));
  }
  else if (step === 'select' && survey.papers.length) meta = t('sv.kept', { n: survey.papers.length }) + (reused ? ` · ${t('sv.reused', { n: reused })}` : '');
  else if (step === 'download' && survey.papers.length) {
    const finished = c.done + c.failed;
    meta = `${c.done} / ${c.wanted}`;
    extra = (
      <>
        {state === 'running' && <div className="sv-bar" aria-hidden="true"><span style={{ width: `${c.wanted ? Math.round(100 * finished / c.wanted) : 0}%` }} /></div>}
        {c.link > 0 && <div className="faint sv-small">{t('sv.paywalled', { n: c.link })}</div>}
        {c.failed > 0 && <div className="faint sv-small">{t('sv.failedPdfs', { n: c.failed })}</div>}
      </>
    );
  } else if (step === 'draft' && state === 'done') meta = t('sv.nodes', { n: survey.nodes.length });
  return (
    <li className={`sv-step is-${state}`}>
      <span className={`sv-mark is-${state}`} aria-label={state}>{state === 'done' && <Icon name="check" size={10} />}{state === 'error' && <Icon name="close" size={10} />}</span>
      <div className="grow sv-step-main"><div>{label}</div>{extra}</div>
      {meta && <span className="muted num sv-meta">{meta}</span>}
    </li>
  );
}

function PaperTable({ survey }: { survey: Survey }) {
  const t = useT();
  return (
    <div className="sv-table-wrap">
      <div className="sv-table-title"><span className="mono">{survey.options.papers_dir}/</span></div>
      <table className="sv-table">
        <thead><tr><th>{t('sv.table.file')}</th><th>{t('sv.table.title')}</th><th>{t('sv.table.year')}</th><th>{t('sv.table.role')}</th><th>{t('sv.table.status')}</th></tr></thead>
        <tbody>
          {survey.papers.map(p => (
            <tr key={p.key}>
              <td className="mono sv-file">{p.file ? p.file.split('/').pop() : '—'}</td>
              <td className="sv-paper">{p.url ? <a href={p.url} target="_blank" rel="noreferrer noopener">{p.title}</a> : p.title}</td>
              <td className="num">{p.year ?? ''}</td>
              <td><span className="chip">{t(`sv.role.${p.role}`)}</span></td>
              <td><span className={`chip sv-paper-st is-${p.status}`} title={p.error ?? undefined}>{t(`sv.paper.${p.status}`)}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Once the survey is done: what it left in the project folder. */
export function FolderCard({ survey }: { survey: Survey }) {
  const { project, navigate } = useApp();
  const t = useT();
  if (!project) return null;
  const c = paperCounts(survey);
  const open = (path: string) => navigate('writing', path);
  const rows: { path: string; note: string; doc?: boolean }[] = [
    ...(survey.idea_file ? [{ path: survey.idea_file, note: t('sv.folder.idea'), doc: true }] : []),
    ...(survey.files.survey ? [{ path: survey.files.survey, note: t('sv.folder.survey'), doc: true }] : []),
    { path: `${survey.options.papers_dir}/`, note: t('sv.folder.pdfs', { n: c.done }) },
    ...(survey.files.bib ? [{ path: survey.files.bib, note: t('sv.folder.bib', { n: survey.papers.length }) }] : []),
    ...(survey.files.index ? [{ path: survey.files.index, note: t('sv.folder.index'), doc: true }] : []),
  ];
  return (
    <section className="card sv-folder" aria-labelledby="sv-folder-h">
      <h2 id="sv-folder-h" className="sv-h2">{t('sv.folder.title')}</h2>
      <div className="mono sv-root" title={project.root}>{project.root}</div>
      <ul className="sv-files">
        {rows.map(r => (
          <li key={r.path}>
            {r.doc ? <button type="button" className="np-link mono" onClick={() => open(r.path)}>{r.path}</button> : <span className="mono">{r.path}</span>}
            <span className="muted"> {r.note}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
