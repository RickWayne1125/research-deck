// The resource pools at a glance, above the runs (as in the Radix preview): a card per pool with its state, how many
// GPUs are in use and how much of today's agent budget is spent, and why a read failed. The Resources tab keeps the
// full view (machines, telemetry, prices); "All resources" goes there.
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { Badge, Button } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useRelTime, useT } from '../../i18n';
import { useApp } from '../../state/app';
import { KIND_ICON } from '../../pools/PoolsSection';
import '../../pools/i18n';
import { exApi, type ExPlatform, type ExResources } from './api';

const REFRESH_MS = 30_000;
const BUSY_UTIL = 10;          // a GPU working harder than this (%) counts as in use

export function PoolStrip({ pid, onAll }: { pid: string; onAll: () => void }) {
  const t = useT();
  const { navigate } = useApp();
  const [data, setData] = useState<ExResources | null>(null);
  const busy = useRef(false);
  const load = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try { setData(await exApi.resources(pid, false)); } catch { /* the Resources tab says why */ } finally { busy.current = false; }
  }, [pid]);
  useEffect(() => {
    load();
    const id = window.setInterval(() => { if (document.visibilityState === 'visible') load(); }, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  if (!data) return null;
  const demo = data.source === 'demo';
  const shown = data.platforms.filter(p => p.pool?.here !== false).slice(0, 6);
  return (
    <section className="ex-sec" aria-labelledby="ex-pools-h">
      <div className="ex-sec-head">
        <h2 id="ex-pools-h">{t('ex.pools.title')}</h2>
        {demo && <Badge tone="warn">{t('ex.r.demoFlag')}</Badge>}
        <span className="grow" />
        <button type="button" className="ex-sec-link" onClick={onAll}>{t('ex.pools.all')}</button>
      </div>
      {shown.length === 0 ? (
        <div className="notice"><Icon name="info" /><span className="grow">{t('ex.pools.none')}</span>
          <Button size="sm" onClick={() => navigate('settings', 'pools')}>{t('ex.pools.add')}</Button></div>
      ) : (
        <div className="ex-pools">{shown.map(p => <PoolCard key={p.id} p={p} onAll={onAll} />)}</div>
      )}
    </section>
  );
}

/** "8× RTX A6000", or several models joined. */
function gpuSummary(p: ExPlatform): string {
  const n = new Map<string, number>();
  for (const node of p.nodes) for (const g of node.gpus) n.set(g.name, (n.get(g.name) ?? 0) + 1);
  return [...n].map(([name, k]) => `${k}× ${name}`).join(' · ');
}

function Bar({ label, value, max, text, tone }: { label: string; value: number; max: number; text: string; tone?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((100 * value) / max)) : 0;
  return (
    <div className="ex-bar">
      <div className="row"><span className="grow">{label}</span><span className="muted num">{text}</span></div>
      <div className={`ex-progress ${tone ?? ''}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
        style={{ '--v': `${pct}%` } as CSSProperties}><i /></div>
    </div>
  );
}

function PoolCard({ p, onAll }: { p: ExPlatform; onAll: () => void }) {
  const t = useT();
  const rel = useRelTime();
  const pool = p.pool;
  const gpus = p.nodes.flatMap(n => n.gpus);
  const inUse = gpus.filter(g => (g.util ?? 0) > BUSY_UTIL).length;
  const known = gpus.some(g => g.util != null);
  const budget = pool?.budget;
  const failed = pool?.state === 'failed';
  const state = pool ? pool.state : p.status === 'ok' ? 'ok' : p.status === 'disabled' ? 'off' : 'stale';
  const badge = state === 'failed' ? <Badge tone="danger">{t('pl.state.failed')}</Badge>
    : state === 'stale' ? <Badge tone="warn">{t('pl.state.staleShort')}</Badge>
      : state === 'reading' ? <Badge>{t('pl.state.reading')}</Badge>
        : state === 'off' ? <Badge>{t('ex.r.ps.disabled')}</Badge>
          : inUse === 0 && gpus.length > 0 && known ? <Badge>{t('ex.pools.idle')}</Badge> : <Badge tone="ok">{t('pl.state.ok')}</Badge>;
  return (
    <article className="ex-pool">
      <div className="ex-pool-head">
        <span className={`ex-pool-icon${state === 'ok' ? ' on' : ''}`}><Icon name={KIND_ICON[p.kind] ?? 'server'} size={18} /></span>
        <div className="col" style={{ gap: 0, minWidth: 0, flex: 1 }}>
          <span className="ex-pool-name ellipsis" title={p.label}>{p.label}</span>
          <span className="muted ex-small ellipsis">{[gpuSummary(p), t(`ex.r.kind.${p.kind}`)].filter(Boolean).join(' · ')}</span>
        </div>
        {badge}
      </div>
      {failed ? (
        <div className="notice warn ex-pool-err">
          <Icon name="warn" /><span className="grow">{pool?.error || t('pl.state.failed')}</span>
        </div>
      ) : gpus.length > 0 && (
        <Bar label={t('ex.pools.gpus')} value={inUse} max={gpus.length} text={known ? `${inUse} / ${gpus.length}` : `? / ${gpus.length}`} />
      )}
      {budget?.agent_gpu_hours_per_day ? (
        <Bar label={t('ex.pools.budget')} value={budget.agent_used_today ?? 0} max={budget.agent_gpu_hours_per_day} tone="gray"
          text={`${(budget.agent_used_today ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 })} / ${budget.agent_gpu_hours_per_day} GPU·h`} />
      ) : null}
      <div className="row ex-pool-foot">
        <span className="faint ex-small grow">{pool?.read_at ? t('ex.pools.read', { rel: rel(pool.read_at) }) : ''}</span>
        {failed && <Button size="sm" onClick={onAll}>{t('ex.pools.details')}</Button>}
      </div>
    </article>
  );
}
