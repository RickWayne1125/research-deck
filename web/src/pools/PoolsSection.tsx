// Settings › Resource pools: the pools on this computer (add, edit, test, refresh, remove to the trash), which of them
// this project uses, the platform names no pool answers to, and one table of prices and budgets.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Badge, Button, Dialog, ErrorNote, Segmented, Spinner, useLoad } from '../components/ui';
import { Icon } from '../components/icons';
import { useI18n, useRelTime, useT } from '../i18n';
import { useApp } from '../state/app';
import { Meter } from '../panels/experiments/parts';
import { poolApi, thisComputer, type PoolCredential, type PoolInfo, type PoolList, type PoolView } from './api';
import { amount, budgetSummary, matchText, num, pricesSummary, sourceText } from './format';
import { PoolWizard, type WizardStart } from './PoolWizard';
import './i18n';
import './pools.css';

export const KIND_ICON: Record<string, string> = { local: 'terminal', home: 'gpu', lab: 'server', cluster: 'layers', cloud: 'globe' };

export function PoolsSection() {
  const { projectId } = useApp();
  const pid = projectId!;
  const t = useT();
  const list = useLoad(() => poolApi.list(pid), [pid]);
  const [view, setView] = useState<'pools' | 'prices'>('pools');
  const [wizard, setWizard] = useState<WizardStart | null>(null);
  const [deleting, setDeleting] = useState<PoolView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const data = list.data;

  // A pool read in the background (just saved, or due): look again shortly.
  const reading = !!data?.pools.some(p => p.platform.pool.reading || p.platform.pool.state === 'reading');
  useEffect(() => {
    if (!reading) return;
    const id = window.setTimeout(list.reload, 2500);
    return () => window.clearTimeout(id);
  }, [reading, list.reload, data]);

  const act = useCallback(async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try { await fn(); list.reload(); } catch (e) { setError(String((e as Error).message ?? e)); } finally { setBusy(null); }
  }, [list.reload]);

  const toggleHere = (id: string, on: boolean) => act(`here:${id}`, () => {
    const all = (data?.pools ?? []).map(p => p.def.id);
    const cur = data?.selection ?? all;
    const next = on ? [...new Set([...cur, id])] : cur.filter(x => x !== id);
    return poolApi.setSelection(pid, all.every(x => next.includes(x)) ? null : next);   // every pool again = the default (all)
  });

  const importFile = async (file: File) => {
    setError(null);
    try {
      const r = await poolApi.parse(await file.text());
      setWizard({ mode: 'import', def: r.def, exists: r.exists });
    } catch (e) { setError(String((e as Error).message ?? e)); }
  };

  if (!data) return list.error ? <ErrorNote error={list.error} onRetry={list.reload} /> : <div className="empty"><Spinner /></div>;
  const here = (id: string) => data.selection === null || data.selection.includes(id);

  return (
    <div className="col pl">
      <div className="row wrap pl-top">
        <Segmented ariaLabel={t('pl.title')} value={view} onChange={setView}
          options={[{ value: 'pools', label: t('pl.view.pools') }, { value: 'prices', label: t('pl.view.prices') }]} />
        <span className="grow" />
        <Button size="sm" icon="download" onClick={() => fileRef.current?.click()}>{t('pl.import')}</Button>
        <input ref={fileRef} type="file" accept=".yaml,.yml,.json,text/yaml,application/json" hidden
          onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) importFile(f); }} />
        <Button size="sm" variant="primary" icon="plus" onClick={() => setWizard({ mode: 'add' })}>{t('pl.add')}</Button>
      </div>
      <p className="st-hint">{t('pl.lead')}</p>
      {error && <div className="notice accent">{error}</div>}
      {data.broken.map(b => (
        <div key={b.file} className="notice warn"><Icon name="warn" /><span><span className="mono">{b.file}</span> · {t('pl.broken', { error: b.error })}</span></div>
      ))}

      {view === 'pools' ? (
        <>
          {data.unmatched.length > 0 && (
            <section className="pl-card">
              <div className="h3">{t('pl.unmatched.title')}</div>
              <span className="st-hint">{t('pl.unmatched.body')}</span>
              <div className="row wrap pl-chips">
                {data.unmatched.map(name => (
                  <button key={name} type="button" className="chip mono pl-chip-btn" title={t('pl.unmatched.register')}
                    onClick={() => setWizard({ mode: 'add', id: name })}><Icon name="plus" size={11} />{name}</button>
                ))}
              </div>
            </section>
          )}
          {data.pools.length === 0 ? (
            <section className="pl-card pl-empty">
              <b>{t('pl.empty.title')}</b>
              <span className="st-hint">{t('pl.empty.body')}</span>
              <div className="row wrap">
                <Button size="sm" variant="primary" icon="terminal" disabled={busy === 'local'}
                  onClick={() => act('local', () => poolApi.save(thisComputer(t('pl.thisComputer')), pid))}>{t('pl.empty.addLocal')}</Button>
                <Button size="sm" icon="plus" onClick={() => setWizard({ mode: 'add' })}>{t('pl.empty.add')}</Button>
              </div>
              <span className="st-hint">{t('pl.empty.localHint')}</span>
            </section>
          ) : (
            <section className="pl-list" aria-label={t('pl.title')}>
              {data.pools.map(v => (
                <PoolRow key={v.def.id} v={v} here={here(v.def.id)} busy={busy}
                  onToggle={on => toggleHere(v.def.id, on)}
                  onEdit={() => setWizard({ mode: 'edit', def: v.def })}
                  onRefresh={() => act(`refresh:${v.def.id}`, () => poolApi.refresh(v.def.id, pid))}
                  onDelete={() => setDeleting(v)} />
              ))}
            </section>
          )}
        </>
      ) : <PricesView data={data} />}

      {wizard && (
        <PoolWizard start={wizard} list={data} pid={pid} onClose={() => setWizard(null)}
          onSaved={() => { setWizard(null); list.reload(); }} />
      )}
      {deleting && (
        <Dialog title={t('pl.del.title', { label: deleting.def.label })} onClose={() => setDeleting(null)} width={520} footer={<>
          <Button onClick={() => setDeleting(null)}>{t('common.cancel')}</Button>
          <Button variant="danger" disabled={busy === `del:${deleting.def.id}`}
            onClick={() => act(`del:${deleting.def.id}`, () => poolApi.remove(deleting.def.id)).then(() => setDeleting(null))}>{t('pl.del.confirm')}</Button>
        </>}>
          <p className="pl-p">{t('pl.del.body', { id: deleting.def.id, dir: `${data.dir}/.trash/` })}</p>
        </Dialog>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ one pool

/** A pool's state; short leaves out when (the Experiments card says it on the source line). */
export function PoolStateBadge({ info, manual, short }: { info: PoolInfo; manual?: boolean; short?: boolean }) {
  const t = useT();
  const rel = useRelTime();
  if (info.state === 'reading') return <Badge>{t('pl.state.reading')}</Badge>;
  if (info.state === 'failed') {
    return <Badge tone="accent" title={info.error ?? undefined}>{info.read_at && !short ? t('pl.state.failedOld', { rel: rel(info.read_at) }) : t('pl.state.failed')}</Badge>;
  }
  if (info.state === 'stale') return <Badge tone="warn">{short ? t('pl.state.staleShort') : t('pl.state.stale', { rel: info.read_at ? rel(info.read_at) : '?' })}</Badge>;
  return <Badge tone="ok">{manual || short || !info.read_at ? t('pl.state.ok') : t('pl.state.okAt', { rel: rel(info.read_at) })}</Badge>;
}

export function CredentialBadge({ c }: { c: PoolCredential }) {
  const t = useT();
  if (c.state === 'expired') return <Badge tone="accent">{t('pl.cred.expired')}</Badge>;
  if (c.state === 'soon') return <Badge tone="warn">{t('pl.cred.soon', { n: Math.max(0, Math.floor(c.days_left ?? 0)) })}</Badge>;
  if (c.state === 'ok') return <Badge>{t('pl.cred.ok', { n: Math.floor(c.days_left ?? 0) })}</Badge>;
  return null;
}

function PoolRow({ v, here, busy, onToggle, onEdit, onRefresh, onDelete }: {
  v: PoolView; here: boolean; busy: string | null; onToggle: (on: boolean) => void; onEdit: () => void; onRefresh: () => void; onDelete: () => void;
}) {
  const t = useT();
  const { lang } = useI18n();
  const { def } = v;
  const info = v.platform.pool;
  const src = sourceText(def, t);
  return (
    <div className={`pl-row ${here ? '' : 'dim'}`}>
      <div className="col pl-row-main">
        <div className="row wrap pl-row-head">
          <Icon name={KIND_ICON[def.kind] ?? 'server'} />
          <h3 className="h3 ellipsis" title={def.label}>{def.label}</h3>
          <span className="mono faint pl-id">{def.id}</span>
          <span className="chip">{t(`pl.kind.${def.kind}`)}</span>
          <PoolStateBadge info={info} manual={def.source.type === 'manual'} />
        </div>
        <dl className="kv pl-kv">
          <dt>{t('pl.k.source')}</dt>
          <dd>{src.kind}{src.detail && <> <code className="mono pl-code">{src.detail}</code></>}{src.every && <span className="faint"> · {src.every}</span>}</dd>
          <dt>{t('pl.k.reads')}</dt>
          <dd className="row wrap pl-chips">{info.capabilities.length
            ? info.capabilities.map(c => <span key={c} className="chip">{t(`pl.cap.${c}`)}</span>)
            : <span className="faint">{info.state === 'reading' ? t('pl.state.reading') : t('pl.cap.none')}</span>}</dd>
          <dt>{t('pl.k.price')}</dt><dd>{pricesSummary(info, t, lang)}</dd>
          <dt>{t('pl.k.budget')}</dt><dd>{budgetSummary(info, t, lang)}</dd>
          {info.credential && <>
            <dt>{t('pl.k.credential')}</dt>
            <dd className="row wrap pl-chips"><span className="mono">{info.credential.ref ?? t('pl.cred.fromSource')}</span><CredentialBadge c={info.credential} /></dd>
          </>}
          {info.error && <><dt>{t('pl.k.error')}</dt><dd className="pl-err">{info.error}</dd></>}
          {info.warnings.length > 0 && <><dt>{t('pl.k.warnings')}</dt><dd className="pl-warn">{info.warnings.slice(0, 3).join('；')}</dd></>}
        </dl>
      </div>
      <div className="col pl-row-side">
        <label className="row pl-here">
          <input type="checkbox" checked={here} disabled={busy === `here:${def.id}`} onChange={e => onToggle(e.target.checked)} />{t('pl.here')}
        </label>
        <div className="row wrap pl-acts">
          <Button size="sm" onClick={onEdit}>{t('pl.edit')}</Button>
          <Button size="sm" icon="refresh" onClick={onRefresh} disabled={busy === `refresh:${def.id}` || def.source.type === 'manual'}>{t('common.refresh')}</Button>
          <Button size="sm" onClick={onDelete}>{t('pl.delete')}</Button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ prices and budgets

function PricesView({ data }: { data: PoolList }) {
  const t = useT();
  const { lang } = useI18n();
  const rows = data.pools.flatMap(v => {
    const info = v.platform.pool;
    if (!info.prices.length) return [{ key: `${v.def.id}-none`, pool: v.def.label, item: '—', match: '—', amount: info.billed ? t('pl.unknownPrice') : t('pl.free'), unit: '—', from: info.billed ? '—' : t('pl.from.default') }];
    return info.prices.map((r, i) => ({
      key: `${v.def.id}-${i}`, pool: v.def.label, item: t(`pl.item.${r.item}`), match: matchText(r.match, t),
      amount: num(r.amount, lang), unit: r.unit, from: t(`pl.from.${r.from ?? 'definition'}`),
    }));
  });
  return (
    <div className="pl-prices">
      <div className="col pl-prices-main">
        <section className="pl-card">
          <div className="h3">{t('pl.p.prices')}</div>
          {rows.length ? (
            <div className="pl-table-wrap">
              <table className="table pl-table">
                <thead><tr><th>{t('pl.p.pool')}</th><th>{t('pl.p.item')}</th><th>{t('pl.p.match')}</th><th>{t('pl.p.amount')}</th><th>{t('pl.p.unit')}</th><th>{t('pl.p.from')}</th></tr></thead>
                <tbody>{rows.map(r => <tr key={r.key}><td>{r.pool}</td><td>{r.item}</td><td>{r.match}</td><td className="num">{r.amount}</td><td>{r.unit}</td><td className="faint">{r.from}</td></tr>)}</tbody>
              </table>
            </div>
          ) : <span className="faint">{t('pl.p.none')}</span>}
          <span className="st-hint">{t('pl.p.rule')}</span>
        </section>
        <section className="pl-card">
          <div className="h3">{t('pl.p.how')}</div>
          <span>{t('pl.p.howRun')}</span>
          <span className="st-hint">{t('pl.p.howDuration')}</span>
        </section>
      </div>
      <section className="pl-card pl-budgets">
        <div className="h3">{t('pl.p.budgets')}</div>
        {data.pools.length === 0 && <span className="faint">{t('pl.p.none')}</span>}
        {data.pools.map(v => <BudgetCard key={v.def.id} v={v} />)}
        <span className="st-hint">{t('pl.p.budgetRule')}</span>
      </section>
    </div>
  );
}

function BudgetCard({ v }: { v: PoolView }) {
  const t = useT();
  const { lang } = useI18n();
  const info = v.platform.pool;
  const day = info.budget.agent_gpu_hours_per_day ?? 0;
  const used = info.budget.agent_used_today ?? 0;
  const month = info.budget.month;
  const spend = v.platform.cost;
  const spent = month && spend && spend.currency === month.unit ? spend.amount : null;
  const quotas = (v.platform.quota_items ?? []).filter(q => typeof q.current === 'number' && typeof q.limit === 'number');
  return (
    <div className="pl-budget">
      <b>{v.def.label}</b>
      {day > 0 ? (
        <div className="pl-meter">
          <div className="row"><span className="faint grow">{t('pl.b.agentToday')}</span><span className="num">{t('pl.b.gpuh', { used: num(used, lang), n: num(day, lang) })}</span></div>
          <Meter value={used} max={day} tone={used >= day ? 'warn' : 'process'} />
        </div>
      ) : null}
      {month && (
        <div className="pl-meter">
          <div className="row"><span className="faint grow">{t('pl.b.month')}</span>
            <span className="num">{spent != null ? `${amount(spent, month.unit, lang)} / ${amount(month.amount, month.unit, lang)}` : t('pl.b.monthCap', { v: amount(month.amount, month.unit, lang) })}</span></div>
          <Meter value={spent} max={month.amount} tone="data" />
        </div>
      )}
      {quotas.map(q => (
        <div key={q.name} className="pl-meter">
          <div className="row"><span className="faint grow">{t('pl.b.quota', { name: q.name })}</span>
            <span className="num">{num(q.current as number, lang)} / {num(q.limit as number, lang)}{q.unit && q.unit !== 'count' ? ` ${q.unit}` : ''}</span></div>
          <Meter value={q.current as number} max={q.limit as number} tone="data" />
        </div>
      ))}
      <span className="st-hint">{day > 0 ? t('pl.b.agentHint') : t('pl.agentNever')}{!info.billed && !info.prices.length ? ` · ${t('pl.free')}` : ''}</span>
    </div>
  );
}

