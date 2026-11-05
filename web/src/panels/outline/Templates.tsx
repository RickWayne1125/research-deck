// Settings → Outline templates: the built-in templates and the researcher's own, each a list of sections (title, what
// the section makes the reader accept, its phase, the tasks it usually needs) and the phases' display names. Editing a
// built-in saves a copy under the same id that shadows it (removing the copy brings the built-in back); the current
// outline can be saved as a template. Changing a template never changes an outline made from it.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Spinner } from '../../components/ui';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useI18n } from '../../i18n';
import { PHASES, SECTION_PHASES, TASK_TYPES, outlineApi, type Bi, type Phase, type SectionPhase, type Template, type TaskType } from './api';
import { errMsg } from './ctx';
import { bi, phaseMark } from './model';
import './outline.css';
import './i18n';

type Lang = 'zh' | 'en';
const setBi = (v: Bi | string | undefined, lang: Lang, text: string): Bi => {
  const base: Bi = typeof v === 'string' ? { zh: v, en: v } : { ...(v ?? {}) };
  return { ...base, [lang]: text };
};
const slug = (s: string) => s.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);

export function OutlineTemplatesSection() {
  const { t, lang } = useI18n();
  const { projectId } = useApp();
  const today = useToday();
  const [list, setList] = useState<(Template & { overrides?: boolean })[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [draft, setDraft] = useState<Template | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = today.outline?.template ?? null;
  const picked = useRef(false);                 // the researcher chose one: do not follow the project's any more

  const load = async (pick?: string) => {
    try {
      const l = await outlineApi.templates();
      setList(l);
      const id = pick ?? sel ?? current ?? l[0]?.id ?? null;
      setSel(id);
      setDraft(structuredClone(l.find(x => x.id === id) ?? l[0] ?? null));
    } catch (e) { setError(errMsg(e)); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, []);
  // the project's template, once the outline has loaded
  useEffect(() => {
    if (!current || picked.current || !list) return;
    const x = list.find(y => y.id === current);
    if (x) { setSel(x.id); setDraft(structuredClone(x)); }
  }, [current, list]);
  const saved = list?.find(x => x.id === sel) ?? null;
  const dirty = useMemo(() => !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved), [draft, saved]);

  const act = async (fn: () => Promise<unknown>, pick?: string) => {
    setBusy(true); setError(null);
    try { await fn(); await load(pick); } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  };
  const save = () => draft && act(() => outlineApi.putTemplate(stripMeta(draft)), draft.id);
  const remove = () => saved && act(() => outlineApi.deleteTemplate(saved.id), saved.id);
  const copy = () => {
    if (!draft) return;
    const name = window.prompt(t('ol.tpl.newName'), `${bi(draft.name, lang)} 2`);
    if (!name?.trim()) return;
    const id = slug(name) || `tpl-${Date.now().toString(36)}`;
    void act(() => outlineApi.putTemplate(stripMeta({ ...draft, id, name: { zh: name.trim(), en: name.trim() }, description: { zh: name.trim(), en: name.trim() } })), id);
  };
  const fromOutline = () => {
    if (!projectId) return;
    const name = window.prompt(t('ol.tpl.newName'), '');
    if (!name?.trim()) return;
    const id = slug(name) || `tpl-${Date.now().toString(36)}`;
    void act(() => outlineApi.saveTemplate(projectId, id, name.trim()), id);
  };
  const edit = (fn: (d: Template) => void) => setDraft(d => { if (!d) return d; const n = structuredClone(d); fn(n); return n; });

  if (!list) return error ? <div className="notice accent" role="alert">{error}</div> : <Spinner />;
  return (
    <div className="col" style={{ gap: 12 }}>
      <p className="st-lead">{t('ol.tpl.lead')}</p>
      <div className="row wrap" style={{ gap: 8 }}>
        <Button size="sm" disabled={busy || !today.outline?.has_outline} onClick={fromOutline}>{t('ol.tpl.fromOutline')}</Button>
        <Button size="sm" disabled={busy || !draft} onClick={copy}>{t('ol.tpl.copy')}</Button>
      </div>
      <div className="ol-tpl-grid">
        <div className="col" style={{ gap: 8 }}>
          {list.map(x => (
            <button key={x.id} type="button" className="ol-tp" aria-pressed={x.id === sel}
              onClick={() => { picked.current = true; setSel(x.id); setDraft(structuredClone(x)); }}>
              <span className="row" style={{ justifyContent: 'space-between' }}>
                <b style={{ color: 'var(--ink-strong)' }}>{bi(x.name, lang)}</b>
                {x.id === current && <span className="ol-hint">{t('ol.tpl.inUse')}</span>}
              </span>
              <span className="ol-hint">{x.builtin ? t('ol.tpl.builtin') : x.overrides ? t('ol.tpl.override') : t('ol.tpl.mine')} · {bi(x.description, lang)}</span>
            </button>
          ))}
          <span className="st-hint">{t('ol.tpl.where')}</span>
        </div>
        {draft && (
          <section className="card" aria-label={bi(draft.name, lang)}>
            <div className="card-head" style={{ justifyContent: 'space-between' }}>
              <input className="input" style={{ maxWidth: 280, fontWeight: 600 }} value={bi(draft.name, lang)} aria-label={t('ol.tpl.name')}
                onChange={e => edit(d => { d.name = setBi(d.name, lang as Lang, e.target.value); })} />
              <div className="row" style={{ gap: 6 }}>
                {saved && !saved.builtin && <Button size="sm" variant="danger" disabled={busy} onClick={remove}>{saved.overrides ? t('ol.tpl.revert') : t('ol.tpl.delete')}</Button>}
                <Button size="sm" variant="primary" disabled={busy || !dirty} onClick={save}>{busy && <Spinner />}{t('common.save')}</Button>
              </div>
            </div>
            <table className="table ol-tt">
              <colgroup><col style={{ width: 40 }} /><col style={{ width: '22%' }} /><col /><col style={{ width: 128 }} /><col style={{ width: 150 }} /><col style={{ width: 24 }} /></colgroup>
              <thead><tr><th /><th>{t('ol.tpl.sec')}</th><th>{t('ol.tpl.role')}</th><th>{t('ol.tpl.phase')}</th><th>{t('ol.tpl.tasks')}</th><th /></tr></thead>
              <tbody>
                {draft.sections.map((s, i) => (
                  <tr key={i}>
                    <td className="mono ol-faint">
                      <button type="button" className="ol-link" disabled={i === 0} aria-label={t('ol.ins.up')} onClick={() => edit(d => { [d.sections[i - 1], d.sections[i]] = [d.sections[i], d.sections[i - 1]]; })}>↑</button>
                      {' '}{i + 1}
                    </td>
                    <td><input className="input" value={bi(s.title, lang)} aria-label={t('ol.tpl.sec')}
                      onChange={e => edit(d => { d.sections[i].title = setBi(d.sections[i].title, lang as Lang, e.target.value); })} /></td>
                    <td><input className="input" value={bi(s.role, lang)} aria-label={t('ol.tpl.role')}
                      onChange={e => edit(d => { d.sections[i].role = setBi(d.sections[i].role, lang as Lang, e.target.value); })} /></td>
                    <td><select className="select" value={s.phase} aria-label={t('ol.tpl.phase')} onChange={e => edit(d => { d.sections[i].phase = e.target.value as SectionPhase; })}>
                      {SECTION_PHASES.map(p => <option key={p} value={p}>{p === 'summary' ? t('ol.group.summaryName') : `${phaseMark(p)} ${bi(draft.phases[p as Phase], lang)}`}</option>)}
                    </select></td>
                    <td><div className="ol-flags">{TASK_TYPES.map(k => {
                      const on = (s.tasks ?? []).includes(k);
                      return <button key={k} type="button" className={`chip ol-chip${on ? ' run' : ''}`} aria-pressed={on}
                        onClick={() => edit(d => { const ts = d.sections[i].tasks ?? []; d.sections[i].tasks = on ? ts.filter(x => x !== k) : [...ts, k as TaskType]; })}>{t(`ol.type.${k}`)}</button>;
                    })}</div></td>
                    <td><button type="button" className="ol-link" aria-label={t('ol.tpl.removeSec')} disabled={draft.sections.length <= 1}
                      onClick={() => edit(d => { d.sections.splice(i, 1); })}>×</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="card-body"><Button size="sm" icon="plus" onClick={() => edit(d => {
              const n = d.sections.length + 1;
              let key = `section-${n}`;
              while (d.sections.some(x => x.key === key)) key = `${key}-x`;
              d.sections.push({ key, title: { zh: `新的一节`, en: 'New section' }, role: { zh: '这一节要让读者接受什么', en: 'What it makes the reader accept' }, phase: 'insight', tasks: [] });
            })}>{t('ol.tpl.addSec')}</Button></div>
            <div className="card-body col" style={{ gap: 8, borderTop: 'var(--line) solid var(--rule)' }}>
              <h3 className="h3" style={{ margin: 0 }}>{t('ol.tpl.phases')}</h3>
              <div className="ol-ph">
                {PHASES.map(p => (
                  <label key={p} className="field"><span className="label">{phaseMark(p)}</span>
                    <input className="input" value={bi(draft.phases[p], lang)} onChange={e => edit(d => { d.phases[p] = setBi(d.phases[p], lang as Lang, e.target.value); })} />
                  </label>
                ))}
              </div>
              <span className="st-hint">{t('ol.tpl.phasesHint')}</span>
            </div>
            {error && <div className="card-body"><div className="notice accent" role="alert">{error}</div></div>}
          </section>
        )}
      </div>
    </div>
  );
}

/** What the server adds to a template (builtin, overrides) is not part of it. */
function stripMeta(t: Template & { overrides?: boolean }): Template {
  const { builtin: _b, overrides: _o, ...rest } = t;
  void _b; void _o;
  return rest;
}
