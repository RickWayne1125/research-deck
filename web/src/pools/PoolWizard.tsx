// Adding or editing a resource pool: 1 the source, 2 fill it in and test it (one read, nothing saved), 3 prices and
// budget. A command source is shown in full before it is saved: it runs with the researcher's permissions, no shell.
import { useMemo, useState } from 'react';
import { Button, Dialog } from '../components/ui';
import { Icon } from '../components/icons';
import { useI18n, useT } from '../i18n';
import {
  EVERY_CHOICES, MATCH_KEYS, POOL_KINDS, poolApi, type InventoryNode, type MatchKey, type PoolDef, type PoolKind, type PoolList,
  type PriceRule, type SourceType, type TestResult,
} from './api';
import { blank, DEFAULT_EVERY, fromName, isIdLike, NAME_MAX, nameKey, problems, slugId, tidyName } from './draft';
import { amount, commandLine, everyText, matchText, num, ruleText } from './format';

/** add: name = a platform name the records use, to make the pool for (its id, or one of its names). */
export type WizardStart = { mode: 'add'; name?: string } | { mode: 'edit'; def: PoolDef } | { mode: 'import'; def: PoolDef; exists: boolean };

const UNITS = ['USD', 'CNY', 'EUR', 'SU', 'credits'];

export function PoolWizard({ start, list, pid, onClose, onSaved }: {
  start: WizardStart; list: PoolList; pid: string; onClose: () => void; onSaved: () => void;
}) {
  const t = useT();
  const editing = start.mode === 'edit';
  const [def, setDef] = useState<PoolDef>(() => (start.mode !== 'add' ? structuredClone(start.def)
    : start.name ? fromName(start.name, list.pools.map(p => p.def.id)) : blank()));
  const [step, setStep] = useState<1 | 2 | 3>(start.mode === 'add' ? 1 : 2);
  // A name that is the id stays the id; one kept among the names lets the id follow the label.
  const [idTouched, setIdTouched] = useState(start.mode !== 'add' || (!!start.name && isIdLike(start.name)));
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bad = problems(def);
  // An imported file with the id of a pool there is replaces it (said above the form, and on the save button).
  const replacing = start.mode === 'import' && start.exists && def.id === start.def.id;
  const taken = !editing && !replacing && list.pools.some(p => p.def.id === def.id);
  // A platform name belongs to one pool (the server refuses a clash too): which other pool has this one already?
  const ownerOf = (name: string) => list.pools.find(p => p.def.id !== def.id
    && [p.def.id, ...(p.def.names ?? [])].some(n => nameKey(n) === nameKey(name)))?.def;
  const clash = !!ownerOf(def.id) || (def.names ?? []).some(n => !!ownerOf(n));
  const blocked = bad.length > 0 || taken || clash;

  const set = (patch: Partial<PoolDef>) => { setDef(d => ({ ...d, ...patch })); setTest(null); };
  const setSource = (patch: Partial<PoolDef['source']>) => { setDef(d => ({ ...d, source: { ...d.source, ...patch } })); setTest(null); };
  const choose = (type: SourceType, preset?: Partial<PoolDef>) => {
    setDef(d => {
      const source: PoolDef['source'] = { type, ...(DEFAULT_EVERY[type] ? { every: DEFAULT_EVERY[type], timeout: 30 } : {}),
        ...(type === 'manual' ? { inventory: d.source.inventory ?? { nodes: [{ id: d.id || 'node-1', gpus: [{ model: '', count: 1 }] }] } } : {}),
        ...(type === 'command' ? { run: d.source.run ?? [] } : {}), ...(type === 'http' ? { url: d.source.url ?? '' } : {}), ...preset?.source };
      const kind: PoolKind = preset?.kind ?? (type === 'local' ? 'local' : d.kind);
      return { ...d, ...preset, kind, source, credential: type === 'command' || type === 'http' ? d.credential : null };
    });
    setTest(null);
    setStep(2);
  };
  const presets = useMemo(() => [
    { key: 'ssh', type: 'command' as const, def: { kind: 'home' as PoolKind, source: { type: 'command' as const, run: [list.python, `${list.adapters}/rd_pool_ssh.py`, '<host>'], every: 30, timeout: 30 } } },
    { key: 'slurm', type: 'command' as const, def: { kind: 'cluster' as PoolKind, source: { type: 'command' as const, run: [list.python, `${list.adapters}/rd_pool_slurm.py`, '<login-node>', '--partition', 'gpu'], every: 300, timeout: 40 } } },
    { key: 'http', type: 'http' as const, def: { kind: 'cluster' as PoolKind, source: { type: 'http' as const, url: 'https://<host>/pools/<id>', every: 60, timeout: 30 } } },
  ], [list.adapters, list.python]);

  const runTest = async () => {
    setTesting(true);
    setError(null);
    try { setTest(await poolApi.test(def)); } catch (e) { setError(String((e as Error).message ?? e)); } finally { setTesting(false); }
  };
  const save = async () => {
    setSaving(true);
    setError(null);
    try { await poolApi.save(def, pid); onSaved(); } catch (e) { setError(String((e as Error).message ?? e)); setSaving(false); }
  };

  const title = editing ? t('pl.w.editTitle', { label: def.label || def.id }) : start.mode === 'import' ? t('pl.w.importTitle') : t('pl.w.addTitle');
  const steps = [t('pl.w.step1'), t('pl.w.step2'), t('pl.w.step3')];
  const footer = (
    <>
      <span className="faint pl-small grow">{t('pl.w.only')}</span>
      {step > 1 && !(editing && step === 2) && <Button onClick={() => setStep(s => (s - 1) as 1 | 2)}>{t('pl.w.back')}</Button>}
      {step === 2 && <Button variant="primary" disabled={blocked} onClick={() => setStep(3)}>{t('pl.w.next')}</Button>}
      {step === 3 && <Button variant="primary" disabled={saving || blocked} onClick={save}>
        {replacing ? t('pl.w.saveReplace') : t('pl.w.save')}</Button>}
    </>
  );

  return (
    <Dialog title={<span className="row wrap pl-w-title">{title}<span className="grow" />
      <span className="row pl-steps">{steps.map((s, i) => (
        <span key={s} className={`pl-step ${i + 1 < step ? 'done' : i + 1 === step ? 'on' : ''}`}><b>{i + 1 < step ? '✓' : i + 1}</b>{s}</span>
      ))}</span></span>} onClose={onClose} width={1120} footer={footer}>
      {error && <div className="notice accent pl-w-error">{error}</div>}
      {replacing && <div className="notice warn pl-w-error">{t('pl.w.exists', { id: def.id })}</div>}
      {step === 3 ? <PricesStep def={def} set={set} test={test} /> : (
        <div className="pl-w-grid">
          <div className="col pl-w-col pl-w-left">
            <span className="label">{t('pl.w.source')}</span>
            {(['manual', 'local', 'command', 'http'] as SourceType[]).map(type => (
              <button key={type} type="button" className={`pl-opt ${step > 1 && def.source.type === type ? 'on' : ''}`} onClick={() => choose(type)}>
                <b>{t(`pl.src.${type}`)}</b><span className="faint pl-small">{t(`pl.src.${type}.hint`)}</span>
              </button>
            ))}
            <span className="label pl-w-presets">{t('pl.w.presets')}</span>
            {presets.map(p => (
              <button key={p.key} type="button" className="pl-opt" onClick={() => choose(p.type, p.def)}>
                <b>{t(`pl.preset.${p.key}`)}</b><span className="faint pl-small">{t(`pl.preset.${p.key}.hint`)}</span>
              </button>
            ))}
          </div>
          <div className="col pl-w-col pl-w-mid">
            {step === 1 ? <div className="empty"><Icon name="server" size={22} /><span>{t('pl.w.pickSource')}</span></div> : (
              <FormStep def={def} set={set} setSource={setSource} editing={editing} taken={taken} bad={bad}
                idTouched={idTouched} touchId={() => setIdTouched(true)} ownerOf={ownerOf} suggest={list.unmatched} />
            )}
            {step === 2 && (
              <div className="row pl-w-test">
                <Button icon="play" onClick={runTest} disabled={testing || bad.length > 0}>{testing ? t('pl.w.testing') : t('pl.w.test')}</Button>
                <span className="faint pl-small">{t('pl.w.testHint')}</span>
              </div>
            )}
          </div>
          <div className="col pl-w-col pl-w-right">
            <span className="label">{t('pl.w.result')}</span>
            {test ? <TestView r={test} /> : <span className="faint pl-small">{t('pl.w.noResult')}</span>}
          </div>
        </div>
      )}
    </Dialog>
  );
}

// ------------------------------------------------------------------ step 2: fill in

function FormStep({ def, set, setSource, editing, taken, bad, idTouched, touchId, ownerOf, suggest }: {
  def: PoolDef; set: (p: Partial<PoolDef>) => void; setSource: (p: Partial<PoolDef['source']>) => void; editing: boolean; taken: boolean;
  bad: string[]; idTouched: boolean; touchId: () => void; ownerOf: (name: string) => PoolDef | undefined; suggest: string[];
}) {
  const t = useT();
  const s = def.source;
  const credName = def.credential?.split(':')[1] || 'my-pool-reader';
  const idOwner = taken ? undefined : ownerOf(def.id);
  return (
    <div className="col pl-form">
      <div className="pl-two">
        <label className="field"><span className="label">{t('pl.w.label')}</span>
          <input className="input" value={def.label} autoFocus
            onChange={e => set({ label: e.target.value, ...(idTouched ? {} : { id: slugId(e.target.value) }) })} /></label>
        <label className="field"><span className="label">{t('pl.w.id')}</span>
          <input className={`input mono ${bad.includes('id') || taken || idOwner ? 'invalid' : ''}`} value={def.id} disabled={editing}
            onChange={e => { touchId(); set({ id: e.target.value.trim().toLowerCase() }); }} />
          {taken ? <span className="pl-small pl-bad">{t('pl.w.idTaken')}</span>
            : idOwner ? <span className="pl-small pl-bad">{t('pl.w.nameOwned', { pool: idOwner.label })}</span>
            : <span className="faint pl-small">{t('pl.w.idHint')}</span>}</label>
      </div>
      <NamesEditor id={def.id} names={def.names ?? []} suggest={suggest} ownerOf={ownerOf}
        onChange={names => set({ names: names.length ? names : undefined })} />
      <label className="field"><span className="label">{t('pl.w.kind')}</span>
        <select className="select" value={def.kind} onChange={e => set({ kind: e.target.value as PoolKind })}>
          {POOL_KINDS.map(k => <option key={k} value={k}>{t(`pl.kind.${k}`)}{['local', 'home', 'lab'].includes(k) ? ` · ${t('pl.w.unbilled')}` : ''}</option>)}
        </select></label>

      {s.type === 'local' && <p className="st-hint">{t('pl.w.localHint')}</p>}
      {s.type === 'manual' && <InventoryEditor nodes={s.inventory?.nodes ?? []} onChange={nodes => setSource({ inventory: { nodes } })} />}
      {s.type === 'command' && (
        <div className="field"><span className="label">{t('pl.w.run')}</span>
          <ArgvEditor argv={s.run ?? []} onChange={run => setSource({ run })} />
          <span className="faint pl-small">{t('pl.w.runHint', { n: s.timeout ?? 30 })}</span></div>
      )}
      {s.type === 'http' && (
        <label className="field"><span className="label">{t('pl.w.url')}</span>
          <input className={`input mono ${bad.includes('url') ? 'invalid' : ''}`} value={s.url ?? ''} placeholder="https://…" onChange={e => setSource({ url: e.target.value.trim() })} />
          <span className="faint pl-small">{t('pl.w.urlHint')}</span></label>
      )}
      {(s.type === 'command' || s.type === 'http') && (
        <label className="field"><span className="label">{t('pl.w.credential')}</span>
          <input className={`input mono ${bad.includes('credential') ? 'invalid' : ''}`} value={def.credential ?? ''} placeholder="keychain:… · env:…"
            onChange={e => set({ credential: e.target.value.trim() || null })} />
          <span className="faint pl-small">{t('pl.w.credHint', { name: credName })}{' '}
            {t(s.type === 'command' ? 'pl.w.credCommand' : 'pl.w.credHttp')}</span></label>
      )}
      {s.type !== 'manual' && (
        <div className="pl-two">
          <label className="field"><span className="label">{t('pl.w.every')}</span>
            <select className="select" value={s.every ?? DEFAULT_EVERY[s.type]} onChange={e => setSource({ every: Number(e.target.value) })}>
              {[...new Set([...EVERY_CHOICES, s.every ?? DEFAULT_EVERY[s.type]])].sort((a, b) => a - b).map(v => <option key={v} value={v}>{everyText(v, t)}</option>)}
            </select></label>
          {s.type !== 'local' && (
            <label className="field"><span className="label">{t('pl.w.timeout')}</span>
              <input className="input num" type="number" min={1} max={120} value={s.timeout ?? 30}
                onChange={e => setSource({ timeout: Math.max(1, Math.min(120, Math.round(Number(e.target.value) || 30))) })} /></label>
          )}
        </div>
      )}
    </div>
  );
}

/** The other platform names the pool answers to: typed, or picked from the names this project has no pool for. */
function NamesEditor({ id, names, suggest, ownerOf, onChange }: {
  id: string; names: string[]; suggest: string[]; ownerOf: (name: string) => PoolDef | undefined; onChange: (n: string[]) => void;
}) {
  const t = useT();
  const [draft, setDraft] = useState('');
  const has = (n: string) => nameKey(n) === nameKey(id) || names.some(x => nameKey(x) === nameKey(n));
  const add = (n: string) => {
    const s = tidyName(n).slice(0, NAME_MAX);
    if (s && !has(s)) onChange([...names, s]);
  };
  const typed = () => { add(draft); setDraft(''); };
  const left = suggest.filter(n => !has(n));
  return (
    <div className="field"><span className="label">{t('pl.w.names')}</span>
      {names.length > 0 && (
        <div className="col pl-names">
          {names.map((n, i) => {
            const owner = ownerOf(n);
            return (
              <div key={nameKey(n)} className={`pl-name ${owner ? 'clash' : ''}`}>
                <span className="grow pl-name-text">{n}{owner && <span className="pl-small pl-bad"> · {t('pl.w.nameOwned', { pool: owner.label })}</span>}</span>
                <button type="button" aria-label={t('pl.w.removeName', { name: n })} onClick={() => onChange(names.filter((_, j) => j !== i))}><Icon name="close" size={10} /></button>
              </div>
            );
          })}
        </div>
      )}
      <div className="row pl-name-add">
        <input className="input grow" value={draft} placeholder={t('pl.w.namePlaceholder')} aria-label={t('pl.w.names')}
          onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && draft.trim()) { e.preventDefault(); typed(); } }} />
        <Button size="sm" icon="plus" disabled={!draft.trim()} onClick={typed}>{t('pl.w.addName')}</Button>
      </div>
      {left.length > 0 && (
        <div className="row wrap pl-chips">
          <span className="faint pl-small">{t('pl.w.nameSuggest')}</span>
          {left.map(n => (
            <button key={n} type="button" className="chip pl-chip-btn" title={n} onClick={() => add(n)}>
              <Icon name="plus" size={11} /><span className="pl-chip-text">{n}</span></button>
          ))}
        </div>
      )}
      <span className="faint pl-small">{t('pl.w.namesHint')}</span>
    </div>
  );
}

function ArgvEditor({ argv, onChange }: { argv: string[]; onChange: (v: string[]) => void }) {
  const t = useT();
  const update = (i: number, v: string) => onChange(argv.map((a, j) => (j === i ? v : a)));
  return (
    <div className="pl-argv" role="group" aria-label={t('pl.w.run')}>
      {argv.map((a, i) => (
        <span key={i} className={`pl-arg ${/<[^>]+>/.test(a) ? 'todo' : ''}`}>
          <input className="mono" value={a} size={Math.max(4, Math.min(48, a.length + 1))} aria-label={t('pl.w.arg', { n: i + 1 })}
            onChange={e => update(i, e.target.value)} placeholder={i === 0 ? t('pl.w.program') : ''} />
          <button type="button" aria-label={t('pl.w.removeArg')} onClick={() => onChange(argv.filter((_, j) => j !== i))}><Icon name="close" size={10} /></button>
        </span>
      ))}
      <button type="button" className="pl-arg-add" onClick={() => onChange([...argv, ''])}><Icon name="plus" size={11} />{t('pl.w.addArg')}</button>
    </div>
  );
}

function InventoryEditor({ nodes, onChange }: { nodes: InventoryNode[]; onChange: (n: InventoryNode[]) => void }) {
  const t = useT();
  const upd = (i: number, patch: Partial<InventoryNode>) => onChange(nodes.map((n, j) => (j === i ? { ...n, ...patch } : n)));
  return (
    <div className="field"><span className="label">{t('pl.w.machines')}</span>
      <div className="pl-inv">
        <span className="faint pl-small">{t('pl.w.mId')}</span><span className="faint pl-small">{t('pl.w.mGpu')}</span>
        <span className="faint pl-small">{t('pl.w.mCount')}</span><span className="faint pl-small">{t('pl.w.mFlavor')}</span><span />
        {nodes.map((n, i) => {
          const g = n.gpus[0] ?? { model: '', count: 1 };
          return [
            <input key={`${i}-id`} className="input mono" value={n.id} onChange={e => upd(i, { id: e.target.value.trim() })} />,
            <input key={`${i}-g`} className="input" value={g.model} placeholder="RTX 5090"
              onChange={e => upd(i, { gpus: e.target.value.trim() ? [{ ...g, model: e.target.value }] : [] })} />,
            <input key={`${i}-c`} className="input num" type="number" min={1} max={64} value={g.count}
              onChange={e => upd(i, { gpus: g.model ? [{ ...g, count: Math.max(1, Math.round(Number(e.target.value) || 1)) }] : [] })} />,
            <input key={`${i}-f`} className="input" value={n.flavor ?? ''} onChange={e => upd(i, { flavor: e.target.value || null })} />,
            <button key={`${i}-x`} type="button" className="icon-btn" aria-label={t('pl.w.removeMachine')} onClick={() => onChange(nodes.filter((_, j) => j !== i))}><Icon name="close" /></button>,
          ];
        })}
      </div>
      <div><Button size="sm" icon="plus" onClick={() => onChange([...nodes, { id: `node-${nodes.length + 1}`, gpus: [] }])}>{t('pl.w.addMachine')}</Button></div>
      <span className="faint pl-small">{t('pl.w.manualHint')}</span>
    </div>
  );
}

// ------------------------------------------------------------------ the test result

function TestView({ r }: { r: TestResult }) {
  const t = useT();
  const { lang } = useI18n();
  if (!r.ok || !r.doc) {
    return <div className="col pl-test"><b className="pl-bad">{t('pl.w.failed', { s: num(r.duration_s, lang) })}</b><div className="pl-err mono">{r.error}</div></div>;
  }
  const d = r.doc;
  const gpus = new Map<string, number>();
  for (const n of d.nodes) for (const g of n.gpus) gpus.set(g.model, (gpus.get(g.model) ?? 0) + g.count);
  const telemetry = d.nodes.some(n => n.cpu != null || n.gpus.some(g => g.util != null));
  const running = d.nodes.filter(n => n.running.length).length;
  const units = [...new Set(d.prices.map(p => p.unit))];
  const exp = d.credential.expires_at ? Math.floor((Date.parse(d.credential.expires_at) - Date.now()) / 86_400_000) : null;
  return (
    <div className="col pl-test">
      <b className="pl-good">{t('pl.w.ok', { s: num(r.duration_s, lang) })}</b>
      <dl className="kv pl-kv">
        <dt>{t('pl.w.rMachines')}</dt>
        <dd>{t('pl.w.rMachinesV', { n: d.nodes.length, running })}{gpus.size ? ` · ${[...gpus].map(([m, c]) => `${m} × ${c}`).join(', ')}` : ` · ${t('pl.w.noGpu')}`}{telemetry ? '' : ` · ${t('pl.w.noTelemetry')}`}</dd>
        {d.quota.length > 0 && <><dt>{t('pl.w.rQuota')}</dt>
          <dd>{d.quota.map(q => `${q.name} ${q.used == null ? '?' : num(q.used, lang)} / ${q.limit == null ? t('pl.w.limitUnknown') : num(q.limit, lang)}`).join(' · ')}</dd></>}
        {d.spend && <><dt>{t('pl.w.rSpend')}</dt><dd>{d.spend.amount == null ? '?' : amount(d.spend.amount, d.spend.unit, lang)} · {t(`pl.spend.${d.spend.kind}`)}</dd></>}
        {d.prices.length > 0 && <><dt>{t('pl.w.rPrices')}</dt><dd>{t('pl.w.rPricesV', { n: d.prices.length, units: units.join(', ') })}</dd></>}
        {exp != null && <><dt>{t('pl.k.credential')}</dt><dd>{exp <= 0 ? t('pl.cred.expired') : t('pl.cred.soon', { n: exp })}</dd></>}
      </dl>
      {(r.warnings ?? []).length > 0 && <div className="notice warn col pl-warns">{r.warnings!.map((w, i) => <span key={i}>{w}</span>)}</div>}
      {r.raw && <details><summary className="faint pl-small">{t('pl.w.raw')}{r.raw_truncated ? ` · ${t('pl.w.rawCut')}` : ''}</summary>
        <pre className="pl-raw mono">{r.raw}</pre></details>}
    </div>
  );
}

// ------------------------------------------------------------------ step 3: prices and budget

function PricesStep({ def, set, test }: { def: PoolDef; set: (p: Partial<PoolDef>) => void; test: TestResult | null }) {
  const t = useT();
  const { lang } = useI18n();
  const upd = (i: number, patch: Partial<PriceRule>) => set({ prices: def.prices.map((p, j) => (j === i ? { ...p, ...patch } : p)) });
  const day = def.budget.agent_gpu_hours_per_day ?? 0;
  const month = def.budget.month;
  const unbilled = ['local', 'home', 'lab'].includes(def.kind);
  const fromSource = test?.doc?.prices ?? [];
  return (
    <div className="pl-w-step3">
      <div className="col pl-w-col">
        <span className="label">{t('pl.w.prices')}</span>
        <div className="pl-rules">
          {def.prices.map((p, i) => {
            const key = (Object.keys(p.match)[0] as MatchKey | undefined) ?? '';
            return (
              <div key={i} className="pl-rule">
                <select className="select" value={p.item} onChange={e => upd(i, { item: e.target.value as PriceRule['item'] })} aria-label={t('pl.p.item')}>
                  <option value="gpu_hour">{t('pl.item.gpu_hour')}</option><option value="node_hour">{t('pl.item.node_hour')}</option>
                </select>
                <select className="select" value={key} aria-label={t('pl.p.match')}
                  onChange={e => upd(i, { match: e.target.value ? { [e.target.value]: p.match[key as MatchKey] ?? '' } : {} })}>
                  <option value="">{t('pl.match.any')}</option>
                  {MATCH_KEYS.map(k => <option key={k} value={k}>{t(`pl.match.${k}`)}</option>)}
                </select>
                <input className="input" value={key ? p.match[key as MatchKey] ?? '' : ''} disabled={!key} aria-label={t('pl.w.matchValue')}
                  onChange={e => upd(i, { match: { [key]: e.target.value } })} />
                <input className="input num" type="number" min={0} step="any" value={Number.isFinite(p.amount) ? p.amount : ''} aria-label={t('pl.p.amount')}
                  onChange={e => upd(i, { amount: e.target.value === '' ? NaN : Number(e.target.value) })} />
                <input className="input" list="pl-units" value={p.unit} aria-label={t('pl.p.unit')} onChange={e => upd(i, { unit: e.target.value.trim() })} />
                <button type="button" className="icon-btn" aria-label={t('pl.w.removePrice')} onClick={() => set({ prices: def.prices.filter((_, j) => j !== i) })}><Icon name="close" /></button>
              </div>
            );
          })}
          <datalist id="pl-units">{UNITS.map(u => <option key={u} value={u} />)}</datalist>
        </div>
        <div><Button size="sm" icon="plus" onClick={() => set({ prices: [...def.prices, { item: 'gpu_hour', match: {}, amount: NaN, unit: 'USD' }] })}>{t('pl.w.addPrice')}</Button></div>
        <span className="st-hint">{unbilled ? t('pl.w.pricesUnbilled') : t('pl.w.pricesBilled')}</span>
        {fromSource.length > 0 && (
          <div className="col pl-src-prices">
            <span className="label">{t('pl.w.sourcePrices')}</span>
            {fromSource.map((p, i) => <span key={i} className="pl-small">{matchText(p.match, t)} · {ruleText(p, t, lang)}</span>)}
          </div>
        )}
      </div>
      <div className="col pl-w-col">
        <span className="label">{t('pl.w.budget')}</span>
        <label className="field"><span className="faint pl-small">{t('pl.w.agentDay')}</span>
          <input className="input num" type="number" min={0} step="any" value={day}
            onChange={e => set({ budget: { ...def.budget, agent_gpu_hours_per_day: Math.max(0, Number(e.target.value) || 0) } })} />
          <span className="faint pl-small">{day > 0 ? t('pl.w.agentDayHint', { n: num(day, lang) }) : t('pl.agentNever')}</span></label>
        <div className="field"><span className="faint pl-small">{t('pl.w.month')}</span>
          <div className="row">
            <input className="input num" type="number" min={0} step="any" value={month?.amount ?? ''} placeholder={t('pl.w.none')} aria-label={t('pl.w.month')}
              onChange={e => set({ budget: { ...def.budget, month: e.target.value === '' ? undefined : { amount: Math.max(0, Number(e.target.value)), unit: month?.unit ?? 'USD' } } })} />
            <input className="input" list="pl-units" value={month?.unit ?? ''} disabled={!month} aria-label={t('pl.p.unit')}
              onChange={e => month && set({ budget: { ...def.budget, month: { ...month, unit: e.target.value.trim() } } })} />
          </div>
          <span className="faint pl-small">{t('pl.w.monthHint')}</span></div>
        <label className="field"><span className="faint pl-small">{t('pl.w.note')}</span>
          <textarea className="textarea" rows={2} value={def.note ?? ''} onChange={e => set({ note: e.target.value || undefined })} /></label>
        {def.source.type === 'command' && (
          <div className="col pl-confirm">
            <span className="label">{t('pl.w.willRun')}</span>
            <pre className="pl-raw mono">{commandLine(def.source.run ?? [])}</pre>
            <span className="faint pl-small">{t('pl.w.willRunHint', { every: everyText(def.source.every, t), n: def.source.timeout ?? 30 })}
              {def.credential ? ` ${t('pl.w.willRunSecret', { ref: def.credential })}` : ''}</span>
          </div>
        )}
        {def.source.type === 'http' && (
          <div className="col pl-confirm">
            <span className="label">{t('pl.w.willGet')}</span>
            <pre className="pl-raw mono">GET {def.source.url}</pre>
            {def.credential && <span className="faint pl-small">{t('pl.w.willGetSecret', { ref: def.credential })}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
