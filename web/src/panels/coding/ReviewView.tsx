// Review tab: pick a range (uncommitted work, or one commit), run a review on the coding panel's agent, then work
// through the findings by severity: jump to the line in the diff, mark resolved or dismissed, or ask the agent.
import { useEffect, useState } from 'react';
import { Badge, Button, Empty, ErrorNote, IconButton, Segmented, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { Markdown } from '../../components/Markdown';
import { useApp } from '../../state/app';
import { useRelTime, useT } from '../../i18n';
import type { CodeFinding, GitCommit } from '../../types';
import { commitRange, WORKING, type CdStatus, type Range } from './api';
import { countLabel, providerLabel, RunLine, SeverityBadge, SEVERITIES } from './parts';
import type { ReviewController } from './reviewState';

export function ReviewView({ review, status, log, onJump }: {
  review: ReviewController; status: CdStatus | null; log: GitCommit[] | null; onJump: (f: CodeFinding, range: Range) => void;
}) {
  const t = useT();
  const rel = useRelTime();
  const { askAgent } = useApp();
  const { stored, findings, run, openCount } = review;
  const dirty = status?.dirty.length ?? 0;
  const commits = log ?? [];

  const [kind, setKind] = useState<'working' | 'commit'>(() => stored?.range.kind ?? (dirty ? 'working' : 'commit'));
  const [sha, setSha] = useState(() => (stored?.range.kind === 'commit' ? stored.range.sha : ''));
  // Follow the last review's range, e.g. one started from the Changes tab.
  useEffect(() => {
    if (!stored) return;
    setKind(stored.range.kind);
    if (stored.range.kind === 'commit') setSha(stored.range.sha);
  }, [stored?.runId]); // eslint-disable-line react-hooks/exhaustive-deps
  const commit = commits.find(c => c.sha === sha) ?? commits[0] ?? null;
  const picked: Range | null = kind === 'working' ? WORKING : commit ? commitRange(commit) : null;
  const [filter, setFilter] = useState<'open' | 'all'>('open');

  const running = run.running || stored?.status === 'running';
  const startFailed = run.status === 'error' && !run.runId && run.error;
  const rangeTitle = (r: Range) => (r.kind === 'working' ? t('cd.review.workingTitle') : `${r.short} · ${r.subject ?? ''}`);
  const ask = (f: CodeFinding) => askAgent(t('cd.ask.finding', { title: f.title, where: f.line ? `${f.file}:${f.line}` : f.file }), {
    file: f.file || undefined,
    extra: `Review finding (${f.severity}) at ${f.file}${f.line ? `:${f.line}` : ''}: ${f.title}\n${f.body}${f.suggestion ? `\nSuggested fix: ${f.suggestion}` : ''}`,
  });

  return (
    <div className="cd-review">
      <div className="cd-review-inner">
        <section className="card">
          <div className="card-body col" style={{ gap: 10 }}>
            <div className="row wrap" style={{ gap: 10 }}>
              <span className="label">{t('cd.review.range')}</span>
              <Segmented<'working' | 'commit'> ariaLabel={t('cd.review.range')} value={kind} onChange={setKind}
                options={[{ value: 'working', label: t('cd.review.working') }, { value: 'commit', label: t('cd.review.commit') }]} />
              {kind === 'commit' && (
                <select className="select cd-commit-select" value={commit?.sha ?? ''} onChange={e => setSha(e.target.value)} aria-label={t('cd.review.commit')}>
                  {commits.slice(0, 150).map(c => <option key={c.sha} value={c.sha}>{c.short} · {c.subject}</option>)}
                </select>
              )}
              <div className="grow" />
              {running
                ? <Button icon="stop" onClick={run.cancel} disabled={!run.runId}>{t('common.stop')}</Button>
                : <Button variant="accent" icon="sparkle" onClick={() => picked && review.start(picked)} disabled={!picked || (kind === 'working' && !dirty)}>{t('cd.review.run')}</Button>}
            </div>
            <p className="muted cd-review-hint">{kind === 'working' && !dirty ? t('cd.review.cleanHint') : t('cd.review.hint')}</p>
            {startFailed && <ErrorNote error={run.error!} />}
            <RunLine run={run} label={t('cd.run.reviewing')} />
          </div>
        </section>

        {stored ? (
          <section className="cd-results">
            <div className="cd-results-head">
              <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
                <span className="label">{t('cd.review.last')}</span>
                <span className="h3 ellipsis">
                  {rangeTitle(stored.range)}
                  {stored.focus && <span className="muted"> · {stored.focus.path}:{stored.focus.start_line}–{stored.focus.end_line}</span>}
                </span>
                <span className="faint cd-results-meta">
                  {rel(stored.startedAt)}
                  {stored.meta && ` · ${providerLabel(stored.meta.provider, t)} · ${stored.meta.model} · ${stored.meta.effort}${stored.meta.fast ? ' · fast' : ''}`}
                  {stored.files != null && ` · ${countLabel(t, 'cd.changes.files', stored.files)}`}
                </span>
              </div>
              {findings && findings.length > 0 && (
                <Segmented<'open' | 'all'> ariaLabel={t('cd.review.filter')} value={filter} onChange={setFilter} options={[
                  { value: 'open', label: t('cd.review.filterOpen', { n: openCount }) },
                  { value: 'all', label: t('cd.review.filterAll', { n: findings.length }) },
                ]} />
              )}
              <IconButton icon="close" label={t('cd.review.clear')} onClick={review.clear} />
            </div>

            {stored.truncated && <div className="notice warn"><Icon name="warn" /> {t('cd.review.truncated')}</div>}
            {stored.status === 'running' && (
              <div className="cd-waiting"><Spinner /><span className="muted">{t('cd.review.waiting')}</span></div>
            )}
            {stored.status === 'error' && (
              <ErrorNote error={stored.error === 'lost' ? t('cd.review.lost') : stored.error || t('agent.error')} onRetry={() => review.start(stored.range, stored.focus)} />
            )}
            {stored.status === 'cancelled' && <div className="notice"><Icon name="info" /> {t('cd.review.cancelled')}</div>}
            {stored.status === 'done' && findings === null && (
              <>
                <div className="notice warn"><Icon name="warn" /> {t('cd.review.unparsed')}</div>
                <div className="card"><div className="card-body"><Markdown text={stored.raw} /></div></div>
              </>
            )}
            {stored.status === 'done' && findings?.length === 0 && (
              <Empty icon="check" title={t('cd.review.none')}>{t('cd.review.noneHint')}</Empty>
            )}
            {findings && findings.length > 0 && filter === 'open' && openCount === 0 && (
              <Empty icon="check" title={t('cd.review.allHandled')} />
            )}
            {findings && SEVERITIES.map(sev => {
              const list = findings.filter(f => f.severity === sev && (filter === 'all' || f.status === 'open'));
              if (!list.length) return null;
              return (
                <div key={sev} className="cd-sev-group">
                  <div className="cd-sev-head"><SeverityBadge severity={sev} /><span className="muted num">{list.length}</span></div>
                  {list.map(f => (
                    <FindingCard key={f.id} f={f} onJump={() => onJump(f, stored.range)} onMark={s => review.setMark(f.id, s)} onAsk={() => ask(f)} />
                  ))}
                </div>
              );
            })}
            {(stored.raw || (stored.status === 'running' && run.text)) && (
              <details className="cd-raw">
                <summary className="label">{t('cd.review.raw')}</summary>
                <pre className="code">{stored.status === 'running' ? run.text : stored.raw}</pre>
              </details>
            )}
          </section>
        ) : !running && (
          <Empty icon="sparkle" title={t('cd.review.emptyTitle')}>{t('cd.review.emptyHint')}</Empty>
        )}
      </div>
    </div>
  );
}

function FindingCard({ f, onJump, onMark, onAsk }: {
  f: CodeFinding; onJump: () => void; onMark: (s: CodeFinding['status']) => void; onAsk: () => void;
}) {
  const t = useT();
  return (
    <article className={`cd-finding sev-${f.severity} ${f.status !== 'open' ? 'is-closed' : ''}`}>
      <div className="cd-finding-head">
        <h3 className="h3 grow">{f.title}</h3>
        {f.status !== 'open' && <Badge tone={f.status === 'resolved' ? 'ok' : undefined}>{t(`cd.review.status.${f.status}`)}</Badge>}
      </div>
      {f.file && (
        <button type="button" className="cd-loc mono" onClick={onJump} title={t('cd.review.jump')}>
          <Icon name="diff" size={13} />{f.file}{f.line ? `:${f.line}` : ''}
        </button>
      )}
      {f.body && <Markdown text={f.body} className="cd-finding-body" />}
      {f.suggestion && (
        <div className="cd-suggest">
          <div className="label">{t('cd.review.suggestion')}</div>
          <Markdown text={f.suggestion} />
        </div>
      )}
      <div className="row wrap cd-finding-actions">
        {f.status === 'open' ? (
          <>
            <Button size="sm" icon="check" onClick={() => onMark('resolved')}>{t('cd.review.resolve')}</Button>
            <Button size="sm" variant="ghost" icon="close" onClick={() => onMark('dismissed')}>{t('cd.review.dismiss')}</Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" icon="rollback" onClick={() => onMark('open')}>{t('cd.review.reopen')}</Button>
        )}
        <div className="grow" />
        <Button size="sm" variant="ghost" icon="send" onClick={onAsk}>{t('cd.askAgent')}</Button>
      </div>
    </article>
  );
}
