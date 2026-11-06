// Resources tab: the resource pools (GET /api/resources?project=) as platforms: machines, GPU telemetry, quota, spend,
// price and the agents' budget; or, on request, the labeled example data. Unknown values stay "unknown" (never 0);
// telemetry older than 30 s is marked; a pool whose last read failed shows that reading and why; refreshes every 15 s.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Badge, Button, Empty, ErrorNote, Segmented, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useI18n, useRelTime, useT } from '../../i18n';
import { useApp } from '../../state/app';
import { poolApi, thisComputer, type PoolInfo } from '../../pools/api';
import { num, rateText, ruleText } from '../../pools/format';
import { KIND_ICON, PoolStateBadge } from '../../pools/PoolsSection';
import '../../pools/i18n';
import '../../pools/pools.css';
import { exApi, type ExCost, type ExGpu, type ExNode, type ExPlatform, type ExResources, type QuotaItem } from './api';
import { formatValue, gib, Meter, parseTime, useNow } from './parts';

const REFRESH_MS = 15_000;
const STALE_MS = 30_000;
const FILTER_KEY = 'rd.ex.poolFilter';

export function ResourcesView({ pid }: { pid: string }) {
  const t = useT();
  const rel = useRelTime();
  const { navigate } = useApp();
  const [data, setData] = useState<ExResources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [example, setExample] = useState(false);
  const [filter, setFilterState] = useState<'here' | 'all'>(() => {
    try { return localStorage.getItem(FILTER_KEY) === 'all' ? 'all' : 'here'; } catch { return 'here'; }
  });
  const setFilter = (v: 'here' | 'all') => { setFilterState(v); try { localStorage.setItem(FILTER_KEY, v); } catch { /* storage unavailable */ } };
  const busy = useRef(false);

  const load = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    try {
      const r = await exApi.resources(pid, example);
      setData(r);
      setFetchedAt(Date.now());
      setError(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }, [pid, example]);
  const addThisComputer = async () => {
    try { await poolApi.save(thisComputer(t('pl.thisComputer')), pid); await load(); } catch (e) { setError(String((e as Error).message ?? e)); }
  };

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
  const pools = data.source === 'pools';
  const hereCount = data.platforms.filter(p => p.pool?.here !== false).length;
  const shown = pools && filter === 'here' ? data.platforms.filter(p => p.pool?.here !== false) : data.platforms;
  const gpus = shown.reduce((n, p) => n + p.nodes.reduce((m, nd) => m + nd.gpus.length, 0), 0);
  // The server's as-of plus how long ago we fetched it, so ages keep moving between refreshes.
  const skew = fetchedAt ? now - fetchedAt : 0;
  const unmatched = data.unmatched ?? [];

  return (
    <div className="ex-res">
      <div className="ex-toolbar">
        {demo ? <span className="badge warn"><Icon name="info" size={11} />{t('ex.r.sourceDemo')}</span>
          : pools ? (hereCount !== data.platforms.length && (
            <Segmented ariaLabel={t('pl.title')} value={filter} onChange={setFilter} options={[
              { value: 'here', label: t('pl.r.filterHere', { n: hereCount }) }, { value: 'all', label: t('pl.r.filterAll', { n: data.platforms.length }) }]} />
          )) : <span className="badge data"><Icon name="server" size={11} />{data.source}</span>}
        <span className="muted ex-small" title={data.as_of}>{t('ex.r.asOf', { time: rel(data.as_of) })}</span>
        <span className="faint ex-small">· {t('ex.r.platforms', { n: shown.length, gpus })}</span>
        <div className="grow" />
        <span className="faint ex-small">{t('ex.r.auto')}</span>
        {!demo && <Button size="sm" icon="settings" onClick={() => navigate('settings', 'pools')}>{t('pl.r.manage')}</Button>}
        <Button size="sm" icon="refresh" onClick={load} disabled={loading}>{t('common.refresh')}</Button>
      </div>
      <div className="ex-pad">
        {demo && (
          <div className="notice warn"><Icon name="info" /> <span className="grow">{t('ex.r.demoNotice')}</span>
            {example && <Button size="sm" onClick={() => { setData(null); setExample(false); }}>{t('pl.r.exampleBack')}</Button>}</div>
        )}
        {pools && data.platforms.length > 0 && <div className="faint ex-small">{t('pl.r.lead')}</div>}
        {pools && unmatched.length > 0 && (
          <div className="notice"><Icon name="info" /><span className="grow">{t('pl.r.unmatched', { n: unmatched.length, names: unmatched.join('、') })}</span>
            <Button size="sm" onClick={() => navigate('settings', 'pools')}>{t('pl.r.register')}</Button></div>
        )}
        {error && <ErrorNote error={error} onRetry={load} />}
        {data.platforms.length === 0 ? (pools ? (
          <Empty icon="server" title={t('pl.empty.title')} action={
            <div className="row wrap" style={{ justifyContent: 'center' }}>
              <Button variant="primary" icon="terminal" onClick={addThisComputer}>{t('pl.empty.addLocal')}</Button>
              <Button icon="plus" onClick={() => navigate('settings', 'pools')}>{t('pl.empty.add')}</Button>
              <Button variant="ghost" onClick={() => { setData(null); setExample(true); }}>{t('pl.r.example')}</Button>
            </div>}>{t('pl.empty.body')}</Empty>
        ) : <div className="empty">{t('ex.r.empty')}</div>) : (
          <div className="ex-plat-grid">
            {shown.map(p => <PlatformCard key={p.id} p={p} skew={skew} demo={demo} />)}
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
  const { lang } = useI18n();
  const rel = useRelTime();
  const note = useNote()(p);
  const pool = p.pool;
  const inventoryOnly = p.nodes.length > 0 && p.nodes.every(n => n.inventory_only);
  return (
    <article className={`card ex-plat ${p.status === 'disabled' ? 'disabled' : ''} ${pool && !pool.here ? 'dim' : ''}`}>
      <div className="card-head">
        <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
          <div className="row wrap" style={{ gap: 6, minWidth: 0 }}>
            {pool && <Icon name={KIND_ICON[p.kind] ?? 'server'} size={14} />}
            <h3 className="h3 ellipsis" title={p.label}>{p.label}</h3>
            <span className="chip">{t(`ex.r.kind.${p.kind}`)}</span>
            {pool && <PoolStateBadge info={pool} manual={pool.source.type === 'manual'} short />}
            {(p.demo || demo) && <span className="badge warn">{t('ex.r.demoFlag')}</span>}
            {p.simulated && <span className="badge warn">{t('ex.r.simulated')}</span>}
          </div>
          {pool && <div className="faint ex-small">{t(`pl.src.${pool.source.type}`)}{pool.read_at && pool.source.type !== 'manual'
            ? ` · ${pool.state === 'failed' ? t('pl.r.showing', { rel: rel(pool.read_at) }) : rel(pool.read_at)}` : ''}</div>}
          {note && <div className="muted ex-small">{note}</div>}
        </div>
        {pool ? <PoolChips pool={pool} lang={lang} /> : (
          <span className="row ex-small ex-nowrap" style={{ gap: 5 }}>
            <span className={`dot ${PLATFORM_DOT[p.status] ?? ''}`} />{t(`ex.r.ps.${p.status}`)}
          </span>
        )}
      </div>
      <div className="card-body col ex-plat-body">
        {pool?.error && <div className="pl-res-errbox">{pool.error}<div className="ex-small" style={{ marginTop: 4 }}>{t('pl.r.errorFix')}</div></div>}
        {(p.quota_items?.length || p.quota || p.quota_note) ? <Quota p={p} /> : null}
        {(!pool || p.cost) && <Cost cost={p.cost} />}
        {p.nodes.length ? (pool && inventoryOnly && p.nodes.length > 4 ? <MachineTable p={p} /> : (
          <div className="ex-nodes">{p.nodes.map(n => <NodeRow key={n.id} n={n} skew={skew} />)}</div>
        )) : p.status !== 'disabled' && pool?.state !== 'reading' ? <div className="faint ex-small">{t('ex.r.noNodes')}</div> : null}
        {pool && <AgentBudget pool={pool} />}
        {pool && (inventoryOnly || p.cost?.estimate) && (
          <div className="faint ex-small">{[inventoryOnly ? t('pl.r.inventoryOnly') : null, p.cost?.estimate ? t('pl.r.spendQuota') : null].filter(Boolean).join(' ')}</div>
        )}
      </div>
    </article>
  );
}

/** The price, credential and "not used here" chips of a pool card. */
function PoolChips({ pool, lang }: { pool: PoolInfo; lang: string }) {
  const t = useT();
  return (
    <span className="row wrap ex-small" style={{ gap: 5, justifyContent: 'flex-end' }}>
      {!pool.here && <span className="chip pl-chip-dash">{t('pl.r.notHere')}</span>}
      {pool.credential?.state === 'expired' ? <Badge tone="accent">{t('pl.r.credExpired')}</Badge>
        : pool.credential?.state === 'soon' ? <Badge tone="warn">{t('pl.r.credSoon', { n: Math.max(0, Math.floor(pool.credential.days_left ?? 0)) })}</Badge> : null}
      <span className="chip">{rateText(pool.rate, t, lang)}</span>
    </span>
  );
}

function AgentBudget({ pool }: { pool: PoolInfo }) {
  const t = useT();
  const { lang } = useI18n();
  const day = pool.budget.agent_gpu_hours_per_day ?? 0;
  if (day <= 0) return null;
  const used = pool.budget.agent_used_today ?? 0;
  return (
    <div className="pl-meter">
      <div className="row"><span className="faint grow">{t('pl.r.agentToday')}</span><span className="num">{t('pl.b.gpuh', { used: num(used, lang), n: num(day, lang) })}</span></div>
      <Meter value={used} max={day} tone={used >= day ? 'warn' : 'process'} />
    </div>
  );
}

/** Many machines with no telemetry (a cloud allocation, a cluster): grouped by flavor, GPU, state and price. */
function MachineTable({ p }: { p: ExPlatform }) {
  const t = useT();
  const { lang } = useI18n();
  const vmState = (s: string) => { const k = `ex.r.vm.${s}`; const v = t(k); return v === k ? s : v; };
  const groups = new Map<string, { ids: string[]; flavor: string; gpu: string; state: string; tone: string; price: string }>();
  for (const n of p.nodes) {
    const models = new Map<string, number>();
    for (const g of n.gpus) models.set(g.name, (models.get(g.name) ?? 0) + 1);
    const gpu = models.size ? [...models].map(([m, c]) => `${m} × ${c}`).join(', ') : t('pl.r.noGpu');
    const state = n.state ? vmState(n.state) : t(`ex.r.ns.${n.status}`);
    const pr = n.price;
    const price = !pr ? '' : pr.state === 'free' ? t('pl.free') : pr.rule_amount != null && pr.unit && pr.item
      ? ruleText({ item: pr.item, amount: pr.rule_amount, unit: pr.unit }, t, lang) : t('pl.unknownPrice');
    const key = [n.flavor ?? '', gpu, state, price].join('\u0000');
    const g = groups.get(key) ?? { ids: [], flavor: n.flavor ?? '—', gpu, state, tone: n.status === 'online' ? 'ok' : '', price };
    g.ids.push(n.label || n.id);
    groups.set(key, g);
  }
  return (
    <div className="pl-table-wrap">
      <table className="table pl-machines">
        <thead><tr><th>{t('pl.r.machines')}</th><th>{t('pl.r.flavor')}</th><th>{t('pl.r.gpu')}</th><th>{t('pl.r.status')}</th><th>{t('pl.r.price')}</th></tr></thead>
        <tbody>{[...groups.values()].map(g => (
          <tr key={g.ids[0]}>
            <td className="mono" title={g.ids.join(', ')}>{g.ids.length === 1 ? g.ids[0] : `${g.ids[0]} … ${g.ids[g.ids.length - 1]}`}</td>
            <td>{g.flavor}</td><td>{g.gpu}</td>
            <td><Badge tone={g.tone === 'ok' ? 'ok' : undefined}>{g.state} {g.ids.length}</Badge></td>
            <td>{g.price}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
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
      {cost.metric && <span className="faint ex-small">{t(`ex.metric.${cost.metric}`)}{cost.since ? ` · ${t('pl.r.since', { date: cost.since })}` : ''}</span>}
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
