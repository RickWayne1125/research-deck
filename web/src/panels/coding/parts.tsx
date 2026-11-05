// Small pieces shared by the coding tabs: the run status line, a streamed agent answer, status and severity badges.
import { useEffect, useState } from 'react';
import { Badge, Button, ErrorNote, IconButton, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { Markdown } from '../../components/Markdown';
import { useT } from '../../i18n';
import type { CodeFinding } from '../../types';
import type { FollowRun } from './useFollowRun';

export function providerLabel(provider: string, t: (k: string) => string): string {
  return provider === 'claude' ? 'Claude Code' : provider === 'codex' ? 'Codex' : provider === 'fake' ? t('cd.run.fake') : provider;
}

/** Spinner, backend · model · effort (· fast), elapsed seconds, the last tool, and Stop while it runs. */
export function RunLine({ run, label }: { run: FollowRun; label?: string }) {
  const t = useT();
  const [, tick] = useState(0);
  useEffect(() => {
    if (!run.running) return;
    const id = window.setInterval(() => tick(x => x + 1), 1000);
    return () => window.clearInterval(id);
  }, [run.running]);
  if (run.status === 'idle') return null;
  const secs = run.durationMs != null ? run.durationMs / 1000 : run.startedAt ? (Date.now() - run.startedAt) / 1000 : 0;
  return (
    <div className="cd-runline" aria-live="polite">
      {run.running ? <Spinner /> : <Icon name={run.status === 'done' ? 'check' : 'warn'} size={14} />}
      <span className="cd-runline-state">{label && run.running ? label : t(`cd.run.${run.status}`)}</span>
      {run.meta && (
        <span className="cd-runmeta mono" title={t('cd.run.metaHint')}>
          {providerLabel(run.meta.provider, t)} · {run.meta.model} · {run.meta.effort}{run.meta.fast ? ' · fast' : ''}
        </span>
      )}
      <span className="faint num">{Math.max(0, Math.round(secs))}s</span>
      {run.running && run.tool && <span className="faint ellipsis cd-runtool" title={run.tool}>{run.tool}</span>}
      <div className="grow" />
      {run.running && <Button size="sm" variant="ghost" icon="stop" onClick={run.cancel}>{t('common.stop')}</Button>}
    </div>
  );
}

/** A streamed markdown answer (explanations). */
export function AgentAnswer({ run, title, onClose, onAsk }: { run: FollowRun; title: string; onClose?: () => void; onAsk?: () => void }) {
  const t = useT();
  return (
    <section className="cd-answer" aria-label={title}>
      <div className="cd-answer-head">
        <Icon name="sparkle" size={14} />
        <span className="cd-answer-title ellipsis grow" title={title}>{title}</span>
        {onClose && <IconButton icon="close" label={t('common.close')} onClick={onClose} />}
      </div>
      <RunLine run={run} label={t('cd.run.explaining')} />
      {run.error && <ErrorNote error={run.error} />}
      {run.text
        ? <Markdown text={run.text} className="cd-answer-md" />
        : run.running && <div className="faint cd-answer-wait">{t('agent.thinking')}</div>}
      {run.status === 'done' && onAsk && (
        <div className="row"><Button size="sm" icon="send" onClick={onAsk}>{t('cd.followUp')}</Button></div>
      )}
    </section>
  );
}

const STATUS_TONE: Record<string, 'data' | 'emphasis' | 'process' | 'warn' | undefined> = { A: 'data', D: 'emphasis', M: 'process', U: 'warn' };

export function FileStatus({ status, untracked }: { status: string; untracked?: boolean }) {
  const t = useT();
  const s = untracked || status === '?' ? '?' : status;
  return <Badge tone={STATUS_TONE[s]} title={t(`cd.fileStatus.${s === '?' ? 'untracked' : s}`)}>{s}</Badge>;
}

export const SEVERITIES: CodeFinding['severity'][] = ['high', 'medium', 'low', 'info'];
const SEVERITY_TONE: Record<CodeFinding['severity'], 'accent' | 'warn' | 'process' | undefined> = { high: 'accent', medium: 'warn', low: 'process', info: undefined };

export function SeverityBadge({ severity }: { severity: CodeFinding['severity'] }) {
  const t = useT();
  return <Badge tone={SEVERITY_TONE[severity]}>{t(`cd.sev.${severity}`)}</Badge>;
}

/** A count phrase: key + ".one" when n is 1 ("1 file"), else key with {n} ("3 files"). */
export function countLabel(t: (k: string, v?: Record<string, string | number>) => string, key: string, n: number): string {
  return t(n === 1 ? `${key}.one` : key, { n });
}

/** "+12 −3" with tabular numbers. */
export function Counts({ add, del }: { add: number; del: number }) {
  return <span className="cd-counts num"><span className="cd-add">+{add}</span> <span className="cd-del">−{del}</span></span>;
}
