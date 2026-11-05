// A project without an outline: write it (paste, or drop a .md / .tex / .txt / .pdf), start from a template, or let
// the agent draft it; then tidy it into chains (the agent keeps the researcher's words and only restructures) and
// confirm. Nothing is written to the project before the confirmation.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Segmented, Spinner } from '../../components/ui';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useI18n } from '../../i18n';
import { outlineApi, type Draft, type DraftStep, type Template } from './api';
import { errMsg } from './ctx';
import { arrangeDraft, bi, phaseMark, type PlannedSection } from './model';

type Mode = 'paste' | 'template' | 'agent';
const TEXT_TYPES = /\.(md|markdown|tex|txt)$/i;

function readText(f: File): Promise<string> {
  return new Promise((ok, fail) => { const r = new FileReader(); r.onload = () => ok(String(r.result ?? '')); r.onerror = () => fail(r.error); r.readAsText(f); });
}
function readBase64(f: File): Promise<string> {
  return new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result ?? '').replace(/^data:[^,]*,/, ''));
    r.onerror = () => fail(r.error);
    r.readAsDataURL(f);
  });
}

export function Compose({ template: current }: { template: string | null }) {
  const { t, lang } = useI18n();
  const { projectId, askAgent, navigate } = useApp();
  const today = useToday();
  const pid = projectId!;
  const key = `rd.outline.raw.${pid}`;
  const [mode, setMode] = useState<Mode>('paste');
  const [raw, setRaw] = useState(() => { try { return localStorage.getItem(key) ?? ''; } catch { return ''; } });
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState(current ?? 'systems');
  const [useAgent, setUseAgent] = useState(true);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<null | 'tidy' | 'create' | 'read'>(null);
  const [reading, setReading] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => { outlineApi.templates().then(setTemplates).catch(e => setError(errMsg(e))); }, []);
  useEffect(() => { try { localStorage.setItem(key, raw); } catch { /* storage unavailable */ } }, [key, raw]);
  const tpl = templates.find(x => x.id === tid) ?? null;
  const tplName = (x: Template | null) => (x ? bi(x.name, lang) : tid);

  const load = async (f: File) => {
    setError(null); setBusy('read'); setReading(f.name);
    try {
      if (TEXT_TYPES.test(f.name)) setRaw(await readText(f));
      else if (/\.pdf$/i.test(f.name)) setRaw((await outlineApi.extract(pid, f.name, await readBase64(f))).text);
      else throw new Error(t('ol.c.drop'));
      setDraft(null);
    } catch (e) { setError(errMsg(e)); } finally { setBusy(null); setReading(''); }
  };
  const tidy = async () => {
    setError(null); setBusy('tidy');
    try { setDraft(await outlineApi.structure(pid, raw, tid, lang, useAgent)); } catch (e) { setError(errMsg(e)); } finally { setBusy(null); }
  };
  const create = async (withDraft: boolean) => {
    setError(null); setBusy('create');
    try {
      await outlineApi.init(pid, tid, lang, withDraft && draft ? { sections: draft.sections } : null);
      try { localStorage.removeItem(key); } catch { /* ignore */ }
      await today.reloadOutline();
    } catch (e) { setError(errMsg(e)); setBusy(null); }
  };
  const planned = useMemo(() => arrangeDraft(tpl, draft, lang), [tpl, draft, lang]);

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="card ol-next">
        <span className="chip">{t('ol.c.next')}</span>
        <span style={{ flex: '1 1 400px' }}>{t('ol.c.nextBody')}</span>
      </div>
      {error && <div className="notice accent" role="alert">{t('ol.err', { msg: error })}</div>}
      <div className="ol-compose">
        <section className="card" aria-labelledby="ol-c-in">
          <div className="card-head">
            <h2 id="ol-c-in" className="h2">{t('ol.c.yours')}</h2>
            <Segmented<Mode> value={mode} onChange={setMode} ariaLabel={t('ol.c.source')}
              options={[{ value: 'paste', label: t('ol.c.paste') }, { value: 'template', label: t('ol.c.template') }, { value: 'agent', label: t('ol.c.agent') }]} />
          </div>
          <div className="card-body col" style={{ gap: 10 }}>
            {mode === 'paste' && <>
              <label className="sr-only" htmlFor="ol-raw">{t('ol.c.yours')}</label>
              <textarea id="ol-raw" ref={box} className="textarea ol-raw" rows={22} value={raw} placeholder={t('ol.c.ph')}
                onChange={e => { setRaw(e.target.value); }} />
              <div className={`ol-drop${over ? ' over' : ''}`}
                onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                onDrop={e => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) void load(f); }}>
                <span className="ol-hint" style={{ flex: '1 1 240px' }}>{busy === 'read' ? t('ol.c.reading', { name: reading }) : t('ol.c.drop')}</span>
                <input ref={file} type="file" accept=".md,.markdown,.tex,.txt,.pdf" hidden onChange={e => { const f = e.target.files?.[0]; if (f) void load(f); e.target.value = ''; }} />
                <Button size="sm" onClick={() => file.current?.click()} disabled={!!busy}>{t('ol.c.pick')}</Button>
              </div>
              <div className="row wrap" style={{ gap: 10 }}>
                <label className="field" style={{ minWidth: 180 }}><span className="label">{t('ol.c.tpl')}</span>
                  <select className="select" value={tid} onChange={e => { setTid(e.target.value); }}>
                    {templates.map(x => <option key={x.id} value={x.id}>{tplName(x)}</option>)}
                  </select>
                </label>
                <span className="grow" />
                <label className="ol-check"><input type="checkbox" checked={!useAgent} onChange={e => setUseAgent(!e.target.checked)} />{t('ol.c.noAgent')}</label>
                <Button variant="primary" disabled={!raw.trim() || !!busy} onClick={tidy}>{busy === 'tidy' && <Spinner />}{busy === 'tidy' ? t('ol.c.tidying') : t('ol.c.tidy')}</Button>
              </div>
            </>}
            {mode === 'template' && <>
              <span className="ol-hint">{t('ol.c.tplBody')}</span>
              <div className="ol-tpls">
                {templates.map(x => (
                  <button key={x.id} type="button" className="ol-tp" aria-pressed={x.id === tid} onClick={() => setTid(x.id)}>
                    <b style={{ color: 'var(--ink-strong)' }}>{tplName(x)}</b>
                    <span className="ol-hint">{bi(x.description, lang)}</span>
                  </button>
                ))}
              </div>
              <div className="row wrap" style={{ gap: 10 }}>
                <button type="button" className="ol-link" onClick={() => navigate('settings', 'templates')}>{t('ol.c.tplEdit')}</button>
                <span className="grow" />
                <Button variant="primary" disabled={!tpl || !!busy} onClick={() => create(false)}>{busy === 'create' && <Spinner />}{t('ol.c.tplGo', { name: tplName(tpl) })}</Button>
              </div>
            </>}
            {mode === 'agent' && <>
              <span className="ol-hint">{t('ol.c.agentBody')}</span>
              <div className="row wrap" style={{ gap: 10 }}>
                <label className="field" style={{ minWidth: 180 }}><span className="label">{t('ol.c.tpl')}</span>
                  <select className="select" value={tid} onChange={e => setTid(e.target.value)}>
                    {templates.map(x => <option key={x.id} value={x.id}>{tplName(x)}</option>)}
                  </select>
                </label>
                <span className="grow" />
                <Button variant="primary" icon="robot" onClick={() => { askAgent(t('ol.c.agentPrompt', { tpl: tplName(tpl) }), {}); setMode('paste'); }}>{t('ol.c.agentGo')}</Button>
              </div>
            </>}
          </div>
        </section>

        <section className="card" aria-labelledby="ol-c-out">
          <div className="card-head">
            <h2 id="ol-c-out" className="h2">{t('ol.c.result')} {draft && <span className="chip ol-chip dash" style={{ marginLeft: 6 }}>{t('ol.c.pending')}</span>}</h2>
            <span className="ol-hint">{t('ol.c.tpl')}: {tplName(tpl)}</span>
          </div>
          {mode === 'template' ? <Planned sections={planned} /> : !draft ? (
            <div className="card-body"><span className="ol-hint">{t('ol.c.emptyResult')}</span></div>
          ) : (
            <>
              <div className="ol-changes">
                {draft.by === 'parse' ? <span>{t('ol.c.byParse')}</span> : <span>{t('ol.c.kept')}</span>}
                {draft.changes.length ? draft.changes.map((c, i) => <span key={i} className="ol-hint">· {c}</span>)
                  : draft.by !== 'parse' && <span className="ol-hint">{t('ol.c.unchanged')}</span>}
              </div>
              <Planned sections={planned} />
              <div className="card-head" style={{ borderTop: 'var(--line) solid var(--rule)', borderBottom: 0 }}>
                <span className="ol-hint" style={{ flex: '1 1 260px' }}>{t('ol.c.foot')}</span>
                <div className="row" style={{ gap: 8 }}>
                  <Button onClick={() => { setDraft(null); box.current?.focus(); }}>{t('ol.c.back')}</Button>
                  <Button variant="primary" disabled={!!busy} onClick={() => create(true)}>{busy === 'create' && <Spinner />}{busy === 'create' ? t('ol.c.creating') : t('ol.c.confirm')}</Button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

/** The sections as they will be: the ones with items in full, the empty ones on one line. */
function Planned({ sections }: { sections: PlannedSection[] }) {
  const { t } = useI18n();
  const full = sections.map((s, i) => ({ s, num: String(i + 1) })).filter(x => x.s.items.length);
  const empty = sections.map((s, i) => ({ s, num: String(i + 1) })).filter(x => !x.s.items.length);
  return (
    <>
      {full.map(({ s, num }) => (
        <div key={num} className="ol-dsec">
          <div className="ol-sec-head">
            <h3>§{num} {s.title}</h3>
            <span className={`chip ol-chip${s.phase === 'summary' ? ' dash' : ''}`}>{s.phase === 'summary' ? t('ol.sec.summary') : phaseMark(s.phase)}</span>
            {!s.fromTemplate && <span className="ol-hint">{t('ol.c.newSec')}</span>}
            {s.role && <span className="ol-sec-role">{s.role}</span>}
          </div>
          <DraftChain steps={s.items} prefix={num} notes={s.notes} />
        </div>
      ))}
      {empty.length > 0 && (
        <div className="ol-dsec"><span className="ol-hint">
          {empty.map(({ s, num }) => `§${num} ${s.title}（${s.phase === 'summary' ? t('ol.sec.summary') : phaseMark(s.phase)}）`).join(' · ')}
        </span></div>
      )}
    </>
  );
}

function DraftChain({ steps, prefix, notes }: { steps: DraftStep[]; prefix: string; notes?: Record<string, string> }) {
  const { t } = useI18n();
  let n = 0;
  const groups = steps.map(st => (Array.isArray(st) ? st : [st]));
  const total = groups.reduce((k, g) => k + g.length, 0);
  const width = Math.max(36, 12 + (prefix.length + 3) * 7);
  return (
    <ol className="ol-nc" style={{ ['--pill' as string]: `${width}px` }}>
      {groups.map((g, si) => {
        const par = g.length > 1;
        const rows = g.map(it => {
          n += 1;
          const num = `${prefix}.${n}`;
          return (
            <div key={num} className="ol-nr">
              <span className="ol-nb">{num}</span>
              <div className={`ol-nt${par ? ' par' : ''}`}>
                <div className="ol-t" style={{ cursor: 'default' }}>{it.text}</div>
                {(it.children ?? []).length > 0 && <div className="ol-kids"><DraftChain steps={it.children} prefix={num} /></div>}
              </div>
            </div>
          );
        });
        const next = n < total ? `${prefix}.${n + 1}` : null;
        return (
          <li key={si}>
            {rows}
            {par && <div className="ol-foot"><span /><span className="ol-nt par">{notes?.[String(si)] ? t('ol.par.note', { note: notes[String(si)] }) : next ? t('ol.par.lead', { num: next }) : t('ol.par')}</span></div>}
          </li>
        );
      })}
    </ol>
  );
}
