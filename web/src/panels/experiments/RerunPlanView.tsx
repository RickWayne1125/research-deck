// Rerun plan tab: what the DAG says must run again after the change — stale/unbuilt cells in waves with their reasons,
// GPU-h per platform, conditional cells (best/worst case), "implement first" (impl_lag), and what is reused and why.
// Queueing creates experiment records; nothing dispatches them to compute (the researcher runs them).
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Empty, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { dagApi } from '../../dag/api';
import { FreshBadge, useDagLabels } from '../../dag/encoding';
import { useI18n, useT } from '../../i18n';
import { useApp, useLiveReload } from '../../state/app';
import type { GraphResponse, Lenses, RunPlan } from '../../types';
import type { ExRecord } from './api';
import { dagReasonText, formatValue } from './parts';

type PlanItem = RunPlan['waves'][number][number];
interface PlanData { lenses: Lenses | null; best: RunPlan | null; worst: RunPlan | null; graph: GraphResponse | null; failed: boolean }

const key = (i: { node: string; cell: string }) => `${i.node}\u0000${i.cell}`;
const sumGpuH = (items: PlanItem[]) => items.reduce((s, i) => s + (i.est_gpu_h ?? 0), 0);

function usePlan(pid: string) {
  const [data, setData] = useState<PlanData | null>(null);
  const load = useCallback(async () => {
    const [lenses, best, worst, graph] = await Promise.allSettled([
      dagApi.lenses(pid), dagApi.plan(pid, { conditional: false }), dagApi.plan(pid, { conditional: true }), dagApi.graph(pid),
    ]);
    const val = <T,>(r: PromiseSettledResult<T>) => (r.status === 'fulfilled' ? r.value : null);
    setData({ lenses: val(lenses), best: val(best), worst: val(worst), graph: val(graph), failed: best.status === 'rejected' && lenses.status === 'rejected' });
  }, [pid]);
  useEffect(() => { load(); }, [load]);
  // DAG evaluations and experiment records change together; one reload per burst.
  const [tick, setTick] = useState(0);
  useLiveReload(['dag', 'experiments'], useCallback(() => setTick(n => n + 1), []));
  useEffect(() => {
    if (!tick) return;
    const id = window.setTimeout(load, 400);
    return () => window.clearTimeout(id);
  }, [tick, load]);
  return { data, reload: load };
}

export function RerunPlanView({ pid, records }: { pid: string; records: ExRecord[] | null }) {
  const t = useT();
  const { lang } = useI18n();
  const L = useDagLabels();
  const { navigate } = useApp();
  const { data } = usePlan(pid);

  const derived = useMemo(() => {
    if (!data?.best) return null;
    const all = data.best.waves.flat();
    const blocked = all.filter(i => i.blocked);
    const waves = data.best.waves.map(w => w.filter(i => !i.blocked)).filter(w => w.length);
    const bestKeys = new Set(all.map(key));
    const conditional = (data.worst?.waves.flat() ?? []).filter(i => !bestKeys.has(key(i)) && !i.blocked);
    const runnable = waves.flat();
    const byPlatform = new Map<string, { cells: number; gpu_h: number; unknown: number }>();
    for (const i of runnable) {
      const p = i.platform ?? '';
      const row = byPlatform.get(p) ?? { cells: 0, gpu_h: 0, unknown: 0 };
      row.cells += 1;
      if (i.est_gpu_h == null) row.unknown += 1; else row.gpu_h += i.est_gpu_h;
      byPlatform.set(p, row);
    }
    return { waves, blocked, conditional, runnable, byPlatform: [...byPlatform.entries()].sort((a, b) => b[1].gpu_h - a[1].gpu_h) };
  }, [data]);

  if (!data) return <div className="empty"><Spinner /></div>;
  if (data.failed || !derived) {
    return <Empty icon="dag" title={t('ex.p.noDag')} action={<Button icon="dag" onClick={() => navigate('dag')}>{t('nav.dag')}</Button>}>{t('ex.p.noDagBody')}</Empty>;
  }

  const nodes = new Map((data.graph?.nodes ?? []).map(n => [n.id, n]));
  const title = (id: string) => { const n = nodes.get(id); return n ? L.title(n) : id; };
  const reasons = (i: PlanItem) => (data.graph?.eval[i.node]?.cells?.[i.cell]?.why ?? []).map(r => dagReasonText(r, t));
  const level = (i: PlanItem) => data.graph?.eval[i.node]?.cells?.[i.cell]?.level ?? null;
  const h = (v: number) => formatValue(Math.round(v * 10) / 10, lang);
  const rerun = data.lenses?.rerun;
  const reused = (records ?? []).filter(r => r.freshness === 'fresh' || r.freshness === 'reusable');
  const bestH = sumGpuH(derived.runnable);
  const condH = sumGpuH(derived.conditional);
  const nothing = !derived.runnable.length && !derived.blocked.length && !derived.conditional.length;

  return (
    <div className="ex-plan">
      <div className="ex-toolbar">
        <span className="badge stale"><Icon name="refresh" size={11} />{t('ex.p.summary.rerun', { n: derived.runnable.length })} · {t('ex.p.gpuh', { h: h(bestH) })}</span>
        {derived.conditional.length > 0 && <span className="badge">{t('ex.p.summary.cond', { n: derived.conditional.length })}</span>}
        {derived.blocked.length > 0 && <span className="badge warn">{t('ex.p.summary.blocked', { n: derived.blocked.length })}</span>}
        {rerun && <span className="badge data">{t('ex.p.summary.reused', { n: rerun.reused_cells, h: h(rerun.reused_gpu_h) })}</span>}
        <div className="grow" />
        <Button size="sm" variant="ghost" icon="external" onClick={() => navigate('dag', 'lens:rerun')}>{t('ex.p.impact')}</Button>
        <span title={t('ex.p.queueDisabled')}><Button size="sm" icon="play" disabled>{t('ex.p.queue')}</Button></span>
      </div>
      <div className="ex-pad">
        <div className="notice"><Icon name="lock" /> <span>{t('ex.p.queueDisabled')}</span></div>

        {nothing ? <Empty icon="check" title={t('ex.p.empty')}>{t('ex.p.emptyBody')}</Empty> : (
          <>
            {derived.byPlatform.length > 0 && (
              <section className="ex-sec">
                <span className="label">{t('ex.p.perPlatform')}</span>
                <table className="table ex-mini">
                  <thead><tr><th>{t('ex.p.platform')}</th><th>{t('ex.p.cells')}</th><th>GPU·h</th></tr></thead>
                  <tbody>
                    {derived.byPlatform.map(([p, row]) => (
                      <tr key={p}><td>{p || <span className="faint">{t('ex.p.noPlatform')}</span>}</td><td className="num">{row.cells}</td>
                        <td className="num">{row.unknown === row.cells ? <span className="faint">{t('ex.p.estUnknown')}</span>
                          : <>{h(row.gpu_h)}{row.unknown > 0 && <span className="faint ex-small"> · {t('ex.p.unknownEst', { n: row.unknown })}</span>}</>}</td></tr>
                    ))}
                    <tr className="ex-total"><td>{t('ex.p.total')}</td><td className="num">{derived.runnable.length}</td><td className="num">{h(bestH)}</td></tr>
                  </tbody>
                </table>
              </section>
            )}

            {derived.waves.map((wave, wi) => (
              <section key={wi} className="ex-sec">
                <div className="row"><span className="label grow">{t('ex.p.wave', { n: wi + 1 })} · {wave.every(i => i.est_gpu_h == null)
                  ? t('ex.p.estUnknown') : t('ex.p.gpuh', { h: h(sumGpuH(wave)) })}</span></div>
                {wi === 0 && derived.waves.length > 1 && <div className="faint ex-small">{t('ex.p.waveHint')}</div>}
                <ul className="ex-cells">{wave.map(i => <CellRow key={key(i)} item={i} title={title(i.node)} level={level(i)} reasons={reasons(i)} h={h} />)}</ul>
              </section>
            ))}

            {derived.conditional.length > 0 && (
              <section className="ex-sec">
                <span className="label">{t('ex.p.cond')}</span>
                <div className="muted ex-small">{t('ex.p.condHint')}</div>
                <div className="row wrap ex-small" style={{ gap: 10 }}>
                  <span className="badge data">{t('ex.p.best', { h: h(bestH) })}</span>
                  <span className="badge stale">{t('ex.p.worst', { h: h(bestH + condH) })}</span>
                </div>
                <ul className="ex-cells">{derived.conditional.map(i => <CellRow key={key(i)} item={i} title={title(i.node)} level={level(i) ?? 'pending'} reasons={reasons(i)} h={h} />)}</ul>
              </section>
            )}

            {derived.blocked.length > 0 && (
              <section className="ex-sec ex-blocked">
                <span className="label">{t('ex.p.blocked')}</span>
                <div className="muted ex-small">{t('ex.p.blockedHint')}</div>
                <ul className="ex-cells">{derived.blocked.map(i => <CellRow key={key(i)} item={i} title={title(i.node)} level={level(i)} reasons={reasons(i)} h={h} />)}</ul>
              </section>
            )}
          </>
        )}

        <section className="ex-sec">
          <span className="label">{t('ex.p.reused')}</span>
          {rerun && <div className="muted ex-small">{t('ex.p.reusedCells', { n: rerun.reused_cells, h: h(rerun.reused_gpu_h) })}</div>}
          {reused.length ? (
            <>
              <div className="ex-small">{t('ex.p.reusedHint', { n: reused.length })}</div>
              <ul className="ex-reused">
                {reused.map(r => (
                  <li key={r.id}>
                    <FreshBadge level={r.freshness} />
                    <button type="button" className="ex-link" onClick={() => navigate('experiments', r.id)}>{r.title}</button>
                    {r.node_id && <button type="button" className="ex-link mono faint ex-small" onClick={() => navigate('dag', r.node_id!)}>{r.node_id}</button>}
                    <span className="muted ex-small">— {r.freshness === 'reusable' ? t('ex.p.reusedReusable')
                      : r.code.footprint.length ? t('ex.p.reusedFresh', { n: r.code.footprint.length }) : t('ex.p.reusedFreshNoTrace')}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : <div className="faint ex-small">{t('ex.p.noReused')}</div>}
        </section>
      </div>
    </div>
  );
}

function CellRow({ item, title, level, reasons, h }: { item: PlanItem; title: string; level: string | null; reasons: string[]; h: (v: number) => string }) {
  const t = useT();
  const { navigate } = useApp();
  return (
    <li className="ex-cellrow">
      <div className="row wrap" style={{ gap: 8 }}>
        {level && <FreshBadge level={level as Parameters<typeof FreshBadge>[0]['level']} />}
        <button type="button" className="ex-link" onClick={() => navigate('dag', item.node)}>{title}</button>
        <span className="mono faint ex-small">{item.node}</span>
        {item.cell && item.cell !== '_' && <span className="mono ex-small ex-cell">{item.cell}</span>}
        <span className="grow" />
        {item.platform && <span className="chip">{item.platform}</span>}
        <span className="num ex-small">{item.est_gpu_h == null ? <span className="faint">{t('ex.p.estUnknown')}</span> : t('ex.p.gpuh', { h: h(item.est_gpu_h) })}</span>
      </div>
      {reasons.length ? <ul className="ex-reasons">{reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        : item.blocked && item.blocked !== 'impl_lag' ? <div className="faint ex-small">{item.blocked}</div> : null}
    </li>
  );
}
