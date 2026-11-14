// Runs tab: every experiment record with its status and the DAG's answer to "does this need a rerun after the change?".
import { useMemo, useState } from 'react';
import { Button, Empty, ErrorNote, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { FreshBadge } from '../../dag/encoding';
import { useI18n, useRelTime, useT } from '../../i18n';
import { useApp } from '../../state/app';
import type { ExperimentStatus } from '../../types';
import { EX_FRESHNESS, EX_STATUSES, type ExFreshness, type ExRecord } from './api';
import { formatDuration, formatValue, reasonText, runDuration, StatusCell, useNow } from './parts';

interface Filters { status: ExperimentStatus | ''; fresh: ExFreshness | ''; platform: string; q: string }
const NO_FILTERS: Filters = { status: '', fresh: '', platform: '', q: '' };
const SHOWN_METRICS = 2;

export function RunsView({ records, loading, error, onRetry, onOpen, onNew, selected }: {
  records: ExRecord[] | null; loading: boolean; error: string | null; onRetry: () => void;
  onOpen: (id: string) => void; onNew: () => void; selected: string | null;
}) {
  const t = useT();
  const { lang } = useI18n();
  const rel = useRelTime();
  const { navigate } = useApp();
  const [f, setF] = useState<Filters>(NO_FILTERS);
  const anyRunning = !!records?.some(r => r.status === 'running');
  const now = useNow(15_000, anyRunning);

  const platforms = useMemo(() => [...new Set((records ?? []).map(r => r.target.platform).filter(Boolean))].sort(), [records]);
  const shown = useMemo(() => {
    const q = f.q.trim().toLowerCase();
    return (records ?? []).filter(r =>
      (!f.status || r.status === f.status) && (!f.fresh || r.freshness === f.fresh) && (!f.platform || r.target.platform === f.platform)
      && (!q || [r.title, r.id, r.node_id, r.command, r.target.node, r.dataset].some(s => s?.toLowerCase().includes(q))));
  }, [records, f]);
  const filtered = Boolean(f.status || f.fresh || f.platform || f.q);

  if (!records) {
    if (error) return <div className="ex-pad"><ErrorNote error={error} onRetry={onRetry} /></div>;
    return <div className="empty"><Spinner /></div>;
  }
  if (!records.length) {
    return <Empty icon="experiments" title={t('ex.empty.title')} action={<Button icon="plus" variant="primary" onClick={onNew}>{t('ex.new')}</Button>}>{t('ex.empty.body')}</Empty>;
  }

  return (
    <div className="ex-runs">
      <div className="ex-toolbar">
        <label className="ex-search">
          <Icon name="search" size={14} />
          <input className="input" type="search" value={f.q} placeholder={t('ex.search')} aria-label={t('ex.search')}
            onChange={e => setF({ ...f, q: e.target.value })} />
        </label>
        <select className="select ex-filter" aria-label={t('ex.filter.status')} value={f.status} onChange={e => setF({ ...f, status: e.target.value as Filters['status'] })}>
          <option value="">{t('ex.filter.allStatus')}</option>
          {EX_STATUSES.map(s => <option key={s} value={s}>{t(`ex.status.${s}`)}</option>)}
        </select>
        <select className="select ex-filter" aria-label={t('ex.filter.fresh')} value={f.fresh} onChange={e => setF({ ...f, fresh: e.target.value as Filters['fresh'] })}>
          <option value="">{t('ex.filter.fresh')}: {t('ex.filter.allFresh')}</option>
          {EX_FRESHNESS.map(s => <option key={s} value={s}>{t(`dagx.fresh.${s}`)}</option>)}
        </select>
        {platforms.length > 0 && (
          <select className="select ex-filter" aria-label={t('ex.filter.platform')} value={f.platform} onChange={e => setF({ ...f, platform: e.target.value })}>
            <option value="">{t('ex.filter.allPlatforms')}</option>
            {platforms.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        )}
        {filtered && <Button size="sm" variant="ghost" icon="close" onClick={() => setF(NO_FILTERS)}>{t('ex.filter.clear')}</Button>}
        <div className="grow" />
        {loading && <Spinner />}
        <span className="faint ex-small num">{t('ex.count', { n: shown.length, total: records.length })}</span>
      </div>
      {error && <div className="ex-pad-x"><ErrorNote error={error} onRetry={onRetry} /></div>}
      {!shown.length ? <Empty icon="search" title={t('ex.empty.filtered')} /> : (
        <div className="ex-table-wrap">
          <table className="table ex-table">
            <thead>
              <tr>
                <th>{t('ex.col.status')}</th><th>{t('ex.col.fresh')}</th><th>{t('ex.col.title')}</th><th>{t('ex.col.node')}</th>
                <th>{t('ex.col.target')}</th><th>{t('ex.col.metrics')}</th><th>{t('ex.col.started')}</th><th>{t('ex.col.duration')}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map(r => {
                const metrics = Object.entries(r.metrics ?? {});
                const reasons = (r.stale_reasons ?? []).map(s => reasonText(s, t)).join('\n');
                return (
                  <tr key={r.id} className={`ex-row ${selected === r.id ? 'active' : ''}`} onClick={() => onOpen(r.id)}
                    onKeyDown={e => { if (e.key === 'Enter' && e.target === e.currentTarget) onOpen(r.id); }} tabIndex={0} aria-selected={selected === r.id}>
                    <td className="ex-col-status"><StatusCell status={r.status} progress={r.progress} t={t} /></td>
                    <td className="ex-col-fresh"><FreshBadge level={r.freshness} title={reasons || t(`ex.freshExplain.${r.freshness}`)} /></td>
                    <td className="ex-col-title">
                      <div className="ellipsis ex-title" title={r.title}>{r.title}</div>
                      <div className="faint mono ex-small ellipsis">{r.id}</div>
                    </td>
                    <td className="ex-col-node">
                      {r.node_id ? (
                        <button type="button" className="ex-link mono" title={r.cell ?? r.dag_cell ?? undefined}
                          onClick={e => { e.stopPropagation(); navigate('dag', r.node_id!); }}>{r.node_id}</button>
                      ) : <span className="faint ex-small">{t('ex.noNode')}</span>}
                      {(r.cell ?? r.dag_cell) && <div className="faint mono ex-small ellipsis ex-cell">{r.cell ?? r.dag_cell}</div>}
                    </td>
                    <td className="ex-col-target">
                      <div className="ellipsis">{r.target.platform || '—'}{r.target.node ? <span className="muted"> · {r.target.node}</span> : null}</div>
                      {(r.target.gpus > 0 || r.target.gpu_type) && <div className="faint ex-small ellipsis">{r.target.gpus || '?'} × {r.target.gpu_type ?? 'GPU'}</div>}
                    </td>
                    <td className="ex-col-metrics" title={metrics.map(([k, v]) => `${k}: ${formatValue(v, lang)}`).join('\n') || undefined}>
                      {metrics.length ? metrics.slice(0, SHOWN_METRICS).map(([k, v]) => (
                        <div key={k} className="ex-metric ellipsis"><span className="faint mono">{k}</span> <span className="num">{formatValue(v, lang)}</span></div>
                      )) : <span className="faint">—</span>}
                      {metrics.length > SHOWN_METRICS && <div className="faint ex-small">{t('ex.moreMetrics', { n: metrics.length - SHOWN_METRICS })}</div>}
                    </td>
                    <td className="ex-nowrap ex-col-started" title={r.started_at ?? undefined}>{r.started_at ? rel(r.started_at) : '—'}</td>
                    <td className="ex-nowrap num ex-col-duration">{formatDuration(r.finished_at || r.status === 'running' || r.status === 'unknown' ? runDuration(r.started_at, r.finished_at, now) : null, t)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
