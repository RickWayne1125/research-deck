// Resources tab: platforms, nodes, GPU telemetry, quota and cost from GET /api/resources (labeled demo data).
// Unknown values stay "unknown" (never 0); telemetry older than 30 s is marked; refreshes every 15 s while visible.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, ErrorNote, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useI18n, useRelTime, useT } from '../../i18n';
import { exApi, type ExCost, type ExGpu, type ExNode, type ExPlatform, type ExResources, type QuotaItem } from './api';
import { formatValue, gib, Meter, parseTime, useNow } from './parts';

const REFRESH_MS = 15_000;
const STALE_MS = 30_000;

export function ResourcesView() {
  const t = useT();
  const rel = useRelTime();
  const [data, setData] = useState<ExResources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchedAt, setFetchedAt] = useState(0);
  const busy = useRef(false);

  const load = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    try {
      const r = await exApi.resources();
      setData(r);
      setFetchedAt(Date.now());
      setError(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = window.setInterval(() => { if (document.visibilityState === 'visible') load(); }, REFRESH_MS);
    const onVis = () => { if (document.visibilityState === 'visible') load(); };
    document.addEventListener('visibilitychange', onVis);
    return () => { window.clearInterval(id); document.removeEventListener('visibilitychange', onVis); };
  }, [load]);
  const now = useNow(5000);

  if (!data) {
    if (error) return <div className="ex-pad"><ErrorNote error={error} onRetry={load} /></div>;
    return <div className="empty"><Spinner /></div>;
  }
  const demo = data.source === 'demo';
  const gpus = data.platforms.reduce((n, p) => n + p.nodes.reduce((m, nd) => m + nd.gpus.length, 0), 0);
  // The server's as-of plus how long ago we fetched it, so ages keep moving between refreshes.
  const skew = fetchedAt ? now - fetchedAt : 0;

  return (
    <div className="ex-res">
      <div className="ex-toolbar">
        {demo ? <span className="badge warn"><Icon name="info" size={11} />{t('ex.r.sourceDemo')}</span>
          : <span className="badge data"><Icon name="server" size={11} />{data.source}</span>}
        <span className="muted ex-small" title={data.as_of}>{t('ex.r.asOf', { time: rel(data.as_of) })}</span>
        <span className="faint ex-small">· {t('ex.r.platforms', { n: data.platforms.length, gpus })}</span>
        <div className="grow" />
        <span className="faint ex-small">{t('ex.r.auto')}</span>
        <Button size="sm" icon="refresh" onClick={load} disabled={loading}>{t('common.refresh')}</Button>
      </div>
      <div className="ex-pad">
        {demo && <div className="notice warn"><Icon name="info" /> <span>{t('ex.r.demoNotice')}</span></div>}
        {error && <ErrorNote error={error} onRetry={load} />}
        {data.platforms.length === 0 ? <div className="empty">{t('ex.r.empty')}</div> : (
          <div className="ex-plat-grid">
            {data.platforms.map(p => <PlatformCard key={p.id} p={p} skew={skew} demo={demo} />)}
          </div>
        )}
      </div>
    </div>
  );
}

const PLATFORM_DOT: Record<string, string> = { ok: 'ok', degraded: 'warn', disabled: '', unknown: '' };
const NODE_DOT: Record<string, string> = { online: 'ok', stale: 'warn', offline: '', unknown: '' };

function useNote() {
  const t = useT();
  return (item: { note?: string | null; note_key?: string }) => (item.note_key ? t(item.note_key) : item.note ?? null);
}

function PlatformCard({ p, skew, demo }: { p: ExPlatform; skew: number; demo: boolean }) {
  const t = useT();
  const note = useNote()(p);
  return (
    <article className={`card ex-plat ${p.status === 'disabled' ? 'disabled' : ''}`}>
      <div className="card-head">
        <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
          <div className="row" style={{ gap: 6, minWidth: 0 }}>
            <h3 className="h3 ellipsis" title={p.label}>{p.label}</h3>
            <span className="chip">{t(`ex.r.kind.${p.kind}`)}</span>
            {(p.demo || demo) && <span className="badge warn">{t('ex.r.demoFlag')}</span>}
            {p.simulated && <span className="badge warn">{t('ex.r.simulated')}</span>}
          </div>
          {note && <div className="muted ex-small">{note}</div>}
        </div>
        <span className="row ex-small ex-nowrap" style={{ gap: 5 }}>
          <span className={`dot ${PLATFORM_DOT[p.status] ?? ''}`} />{t(`ex.r.ps.${p.status}`)}
        </span>
      </div>
      <div className="card-body col ex-plat-body">
        {(p.quota_items?.length || p.quota || p.quota_note) ? <Quota p={p} /> : null}
        <Cost cost={p.cost} />
        {p.nodes.length ? (
          <div className="ex-nodes">{p.nodes.map(n => <NodeRow key={n.id} n={n} skew={skew} />)}</div>
        ) : p.status !== 'disabled' ? <div className="faint ex-small">{t('ex.r.noNodes')}</div> : null}
      </div>
    </article>
  );
}

function Quota({ p }: { p: ExPlatform }) {
  const t = useT();
  const { lang } = useI18n();
  const items: QuotaItem[] = p.quota_items?.length ? p.quota_items
    : Object.entries(p.quota ?? {}).map(([name, v]) => ({ name, current: null, limit: v, unit: '' }));
  const val = (v: number | string | null) => (v == null ? t('ex.r.unknownValue') : formatValue(v, lang));
  return (
    <div className="ex-block">
      <span className="label">{t('ex.r.quota')}</span>
      {items.length > 0 && (
        <dl className="kv ex-quota">
          {items.map(it => {
            const numeric = typeof it.current === 'number' && typeof it.limit === 'number';
            return (
              <div key={it.name} className="ex-quota-row">
                <dt>{it.name}</dt>
                <dd>
                  <span className="num">{it.current == null && typeof it.limit === 'string' ? it.limit : `${val(it.current)} / ${val(it.limit)}`}</span>
                  {it.unit && it.unit !== 'count' && <span className="faint"> {it.unit}</span>}
                  {numeric && <Meter value={it.current as number} max={it.limit as number} tone="data" />}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      {(p.quota_note_key || p.quota_note) && <div className="faint ex-small">{p.quota_note_key ? t(p.quota_note_key) : p.quota_note}</div>}
    </div>
  );
}

function Cost({ cost }: { cost: ExCost | null | undefined }) {
  const t = useT();
  const { lang } = useI18n();
  const rel = useRelTime();
  let body;
  if (cost == null) body = <span className="muted">{t('ex.r.costNone')}</span>;
  else if (cost.amount == null) body = <span className="muted">{t('ex.r.costUnknown')}<span className="faint"> · {cost.currency}</span></span>;
  else body = (
    <span className="row wrap" style={{ gap: 6 }}>
      <span className="num ex-amount">{formatValue(cost.amount, lang)} {cost.currency}</span>
      {cost.metric && <span className="faint ex-small">{t(`ex.metric.${cost.metric}`)}</span>}
      <span className={`badge ${cost.estimate ? 'warn' : ''}`}>{cost.estimate ? t('ex.r.estimate') : t('ex.r.reported')}</span>
      <span className="faint ex-small" title={cost.as_of ?? undefined}>{cost.as_of ? t('ex.r.costAsOf', { time: rel(cost.as_of) }) : t('ex.r.noAsOf')}</span>
    </span>
  );
  return (
    <div className="ex-block">
      <span className="label">{t('ex.r.cost')}</span>
      <div>{body}</div>
      {cost?.delay_note ? <div className="faint ex-small">{cost.delay_note}</div>
        : cost?.estimate && (cost.source_key || cost.source) ? <div className="faint ex-small">{cost.source_key ? t(cost.source_key) : cost.source}</div> : null}
    </div>
  );
}

function NodeRow({ n, skew }: { n: ExNode; skew: number }) {
  const t = useT();
  const { lang } = useI18n();
  const rel = useRelTime();
  const note = useNote()(n);
  const at = parseTime(n.telemetry_at);
  const age = n.telemetry_age_s != null ? n.telemetry_age_s * 1000 + skew : at != null ? Date.now() - at : null;
  const stale = !n.inventory_only && (n.stale || (age != null && age > STALE_MS));
  const status = stale && n.status === 'online' ? 'stale' : n.status;
  const unknown = t('ex.r.unknownValue');
  const scopeNote = n.scope === 'wsl' || n.scope === 'workspace' ? t(`ex.r.scope.${n.scope}`) : null;
  const vmState = (s: string) => { const k = `ex.r.vm.${s}`; const v = t(k); return v === k ? s : v; };
  return (
    <div className={`ex-node ${stale ? 'stale' : ''}`}>
      <div className="row wrap ex-node-head">
        <span className={`dot ${NODE_DOT[status] ?? ''}`} />
        <b className="ellipsis" title={n.label}>{n.label}</b>
        {/* an inventory-only VM has no agent: show its power state, not an agent status */}
        {n.inventory_only ? n.state && <span className="muted ex-small">{vmState(n.state)}</span>
          : <span className="muted ex-small">{t(`ex.r.ns.${status}`)}</span>}
        {n.inventory_only && <span className="chip">{t('ex.r.inventoryOnly')}</span>}
        {n.demo && <span className="badge warn">{t('ex.r.demoFlag')}</span>}
        {n.simulated && <span className="badge warn">{t('ex.r.simulated')}</span>}
        <span className="grow" />
        {!n.inventory_only && (stale
          ? <span className="badge stale" title={n.telemetry_at ?? undefined}><Icon name="warn" size={11} />{t('ex.r.staleTelemetry', { rel: n.telemetry_at ? rel(n.telemetry_at) : unknown })}</span>
          : n.telemetry_at ? <span className="faint ex-small" title={n.telemetry_at}>{t('ex.r.telemetry', { rel: rel(Date.now() - (age ?? 0)) })}</span>
            : <span className="faint ex-small">{t('ex.r.noTelemetry')}</span>)}
      </div>
      {(note || scopeNote) && <div className="faint ex-small">{[note, scopeNote].filter(Boolean).join(' · ')}</div>}
      {(n.cpu != null || n.ram != null) && (
        <div className="ex-hostbars ex-small">
          <span className="faint">{t('ex.r.cpu')}</span><Meter value={n.cpu} /><span className="num">{n.cpu == null ? unknown : `${formatValue(n.cpu, lang)}%`}</span>
          <span className="faint">{t('ex.r.ram')}</span><Meter value={n.ram} tone="data" /><span className="num">{n.ram == null ? unknown : `${formatValue(n.ram, lang)}%`}</span>
        </div>
      )}
      {n.gpus.length > 0 && (
        <div className="ex-gpus" role="table" aria-label="GPU">
          <div className="ex-gpu ex-gpu-head" role="row">
            <span role="columnheader">GPU</span><span role="columnheader">{t('ex.r.util')}</span><span role="columnheader">{t('ex.r.mem')}</span>
            <span role="columnheader">{t('ex.r.temp')}</span><span role="columnheader">{t('ex.r.power')}</span>
          </div>
          {n.gpus.map((g, i) => <GpuRow key={g.key ?? `${g.name}-${i}`} g={g} />)}
        </div>
      )}
      {(n.running?.length || n.queued) ? (
        <div className="row wrap ex-small" style={{ gap: 4 }}>
          {n.running?.length ? <><span className="faint">{t('ex.r.running')}</span>{n.running.map(j => <span key={j} className="chip mono">{j}</span>)}</> : null}
          {n.queued ? <span className="faint">{t('ex.r.queued', { n: n.queued })}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

function GpuRow({ g }: { g: ExGpu }) {
  const t = useT();
  const unknown = t('ex.r.unknownValue');
  const hot = g.temp != null && g.temp >= 85;
  return (
    <div className="ex-gpu" role="row">
      <span className="ellipsis" title={g.name} role="cell">{g.name}</span>
      <span className="ex-gpu-bar" role="cell">
        <Meter value={g.util} title={g.util == null ? unknown : `${Math.round(g.util)}%`} />
        <span className={`num ${g.util == null ? 'faint' : ''}`}>{g.util == null ? unknown : `${Math.round(g.util)}%`}</span>
      </span>
      <span className="ex-gpu-bar" role="cell">
        <Meter value={g.mem_used} max={g.mem_total} tone="data" />
        <span className={`num ${g.mem_used == null ? 'faint' : ''}`}>{g.mem_used == null ? `— / ${gib(g.mem_total)}` : `${gib(g.mem_used)} / ${gib(g.mem_total)}`} GiB</span>
      </span>
      <span className={`num ${g.temp == null ? 'faint' : hot ? 'ex-hot' : ''}`} role="cell">{g.temp == null ? '—' : `${Math.round(g.temp)} °C`}</span>
      <span className={`num ${g.power == null ? 'faint' : ''}`} role="cell">{g.power == null ? '—' : `${Math.round(g.power)} W`}</span>
    </div>
  );
}
