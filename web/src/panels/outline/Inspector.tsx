// The inspector beside the outline: the selected item (its state, tasks, evidence, the text that covers it, and what
// can be done to it), a fork (its directions side by side, choose or abandon one), or a section (title, role, phase,
// order). With nothing selected: the outliner keys and the results no item uses yet.
import { useEffect, useState } from 'react';
import { Button } from '../../components/ui';
import { useApp } from '../../state/app';
import { useRelTime, useT } from '../../i18n';
import { dagApi } from '../../dag/api';
import { SECTION_PHASES, type Item, type Section, type SectionPhase } from './api';
import { errMsg, useOl } from './ctx';
import { bi, outlineText, pathTo } from './model';
import { EvidenceChip, StateChip, TaskChip, usePhaseLabel } from './parts';

export function Inspector() {
  const { sel, items, o } = useOl();
  const it = sel ? items.get(sel) : undefined;
  const sec = sel ? o.sections.find(s => s.id === sel) : undefined;
  return (
    <aside className="card ol-ins" aria-label={it ? it.num : sec ? `§${sec.num}` : undefined}>
      {it ? <ItemPane key={it.id} it={it} /> : sec ? <SectionPane key={sec.id} s={sec} /> : <Idle />}
    </aside>
  );
}

function Keys() {
  const t = useT();
  const k = (key: string, label: string) => <span><kbd>{key}</kbd>{label}</span>;
  return (
    <div className="ol-keys">
      {k('↵', t('ol.key.next'))}{k('⌥↵', t('ol.key.par'))}{k('Tab', t('ol.key.indent'))}{k('⇧Tab', t('ol.key.outdent'))}
      {k('⌥↑↓', t('ol.key.move'))}{k('⌘.', t('ol.key.fold'))}
    </div>
  );
}

function Idle() {
  const t = useT();
  const { o } = useOl();
  const { navigate } = useApp();
  return (
    <div className="ol-ins-body">
      <p className="ol-hint" style={{ margin: 0 }}>{t('ol.ins.none')}</p>
      <div className="ol-ins-sec"><h3>{t('ol.ins.keys')}</h3><Keys /></div>
      {o.loose.length > 0 && (
        <div className="ol-ins-sec">
          <h3>{t('ol.ins.loose')}</h3>
          <span className="ol-hint">{t('ol.ins.looseBody')}</span>
          <div className="ol-flags">
            {o.loose.map(x => <button key={x.id} type="button" className="chip ol-chip" title={x.id} onClick={() => navigate('dag', x.id)}>{x.title || x.id}</button>)}
          </div>
        </div>
      )}
    </div>
  );
}

function ItemPane({ it }: { it: Item }) {
  const t = useT();
  const rel = useRelTime();
  const { navigate, askAgent } = useApp();
  const { o, items, tasks, run, openDialog, setEditing, select, busy, error, pid, reload } = useOl();
  const phaseLabel = usePhaseLabel();
  const path = pathTo(o, it.id);
  const section = path?.section;
  const parent = it.direction ? items.get(it.parent) : undefined;          // the fork item of a direction
  const live = it.state !== 'abandoned';
  const myTasks = [...it.tasks, ...it.suggested].map(id => tasks.get(id)).filter((x): x is NonNullable<typeof x> => !!x);
  const [condition, setCondition] = useState(it.condition);
  const [sumOf, setSumOf] = useState(() => it.summary_of.map(id => items.get(id)?.num ?? id).join(' '));
  useEffect(() => { setCondition(it.condition); }, [it.condition]);
  const [actErr, setActErr] = useState<string | null>(null);
  const accept = async () => {
    setActErr(null);
    try { await dagApi.ops(pid, [{ op: 'set_status', node: it.id, to: 'active' }]); await reload(); } catch (e) { setActErr(errMsg(e)); }
  };
  const revive = async () => {
    setActErr(null);
    try { await dagApi.ops(pid, [{ op: 'set_status', node: it.id, to: 'active', reason: 'revived on the outline' }]); await reload(); } catch (e) { setActErr(errMsg(e)); }
  };
  const saveSummary = () => {
    const byNum = new Map([...items.values()].map(x => [x.num, x.id]));
    const ids = sumOf.split(/[\s,，、]+/).map(x => x.trim()).filter(Boolean).map(n => byNum.get(n.replace(/^§/, '')) ?? n).filter(id => items.has(id));
    void run([{ op: 'edit_item', item: it.id, summary_of: ids }]);
  };
  const ask = () => askAgent(t('ol.ins.askPrompt', { num: it.num, text: it.text }), {});
  const isSummary = section?.phase === 'summary';
  return (
    <>
      <div className="ol-ins-head">
        <div className="row" style={{ gap: 8 }}>
          <h2>{it.direction ? `${it.num} · ${t('ol.dir', { n: it.direction })}` : it.num}</h2>
          <StateChip it={it} chosen={!!parent?.fork && parent.fork.chosen === it.id} />
          <span className="grow" />
          {section && <span className="ol-hint">{phaseLabel(section.phase)}</span>}
        </div>
        <span className="ol-ins-text">{it.text}</span>
        {it.state === 'proposed' && (
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="ol-hint grow">{t('ol.pend.itemBody')}</span>
            <Button size="sm" variant="primary" onClick={accept}>{t('ol.pend.accept')}</Button>
            <Button size="sm" onClick={() => openDialog({ kind: 'remove', item: it.id })}>{t('ol.pend.reject')}</Button>
          </div>
        )}
        {it.state === 'abandoned' && (
          <span className="ol-hint">{it.why ? t('ol.tree.why', { why: it.why }) : it.why_kind ? t(`ol.reason.${it.why_kind}`) : ''}
            {it.ended_at ? ` · ${t('ol.ins.abandonedAt', { when: rel(it.ended_at) })}` : ''}</span>
        )}
        {it.proposals.length > 0 && <span className="ol-hint">{t('ol.ins.proposal')}</span>}
        {(error || actErr) && <div className="notice accent" role="alert">{actErr ?? error}</div>}
      </div>
      <div className="ol-ins-body">
        {it.fork && <ForkPane it={it} />}

        {!it.fork && (
          <div className="ol-ins-sec">
            <h3>{t('ol.ins.tasks')}</h3>
            {myTasks.length ? <div className="ol-flags">{myTasks.map(x => <TaskChip key={x.id} task={x} />)}</div>
              : <span className="ol-hint">{t('ol.ins.noTasks')}</span>}
            {live && <div className="row wrap" style={{ gap: 6 }}><Button size="sm" icon="plus" onClick={() => openDialog({ kind: 'task', item: it.id })}>{t('ol.ins.assign')}</Button></div>}
          </div>
        )}

        <div className="ol-ins-sec">
          <h3>{t('ol.ins.evidence')}</h3>
          {it.evidence.length ? (
            <div className="ol-ins-list">
              {it.evidence.map(e => (
                <div key={`${e.rel}:${e.id}`} className="ol-ins-row">
                  <span className="ol-faint" style={{ fontSize: 'var(--fs-xs)', minWidth: 34 }}>{t(`ol.link.${e.rel}`)}</span>
                  <span className="grow"><EvidenceChip e={e} /></span>
                  {live && e.rel !== 'task' && <button type="button" className="ol-link" disabled={busy} onClick={() => run([{ op: 'unlink', item: it.id, to: e.id, type: e.rel }])}>{t('ol.link.remove')}</button>}
                </div>
              ))}
            </div>
          ) : <span className="ol-hint">{t('ol.ins.noEvidence')}</span>}
          {live && <div className="row"><Button size="sm" icon="link" onClick={() => openDialog({ kind: 'link', item: it.id })}>{t('ol.ins.link')}</Button></div>}
        </div>

        <div className="ol-ins-sec">
          <h3>{t('ol.ins.written')}</h3>
          {it.written.length ? it.written.map((w, i) => (
            <button key={i} type="button" className="ol-link" style={{ textAlign: 'left' }} onClick={() => navigate('writing', w.file ?? null)}>
              {t('ol.ins.writtenIn', { where: `${w.file ?? ''} ${w.section}`.trim() })}
            </button>
          )) : <span className="ol-hint">{t('ol.ins.notWritten')}</span>}
        </div>

        {live && !it.fork && (
          <div className="ol-ins-sec">
            <label className="ol-check"><input type="checkbox" checked={it.derived} disabled={busy} onChange={e => run([{ op: 'edit_item', item: it.id, derived: e.target.checked }])} />{t('ol.ins.derived')}</label>
            <label className="field"><span className="label">{t('ol.ins.condition')}</span>
              <input className="input" value={condition} placeholder={t('ol.ins.conditionPh')} onChange={e => setCondition(e.target.value)}
                onBlur={() => condition !== it.condition && run([{ op: 'edit_item', item: it.id, condition }])}
                onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
            </label>
            {isSummary && (
              <label className="field"><span className="label">{t('ol.ins.summaryOf')}</span>
                <input className="input mono" value={sumOf} placeholder={t('ol.ins.summaryOfPh')} onChange={e => setSumOf(e.target.value)}
                  onBlur={saveSummary} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
              </label>
            )}
          </div>
        )}

        <div className="ol-ins-sec">
          {live ? (
            <div className="row wrap" style={{ gap: 6 }}>
              <Button size="sm" onClick={() => setEditing({ kind: 'text', id: it.id })}>{t('ol.key.edit')}</Button>
              <Button size="sm" onClick={() => setEditing({ kind: 'new', parent: it.id, at: {} })}>{t('ol.ins.addChild')}</Button>
              <Button size="sm" onClick={() => navigate('outline', `@focus/${it.id}`)}>{t('ol.ins.focus')}</Button>
              {!it.direction && <>
                <Button size="sm" disabled={busy} onClick={() => run([{ op: 'move_item', item: it.id, how: 'up' }])}>{t('ol.ins.up')}</Button>
                <Button size="sm" disabled={busy} onClick={() => run([{ op: 'move_item', item: it.id, how: 'down' }])}>{t('ol.ins.down')}</Button>
                <Button size="sm" disabled={busy} onClick={() => run([{ op: 'move_item', item: it.id, how: 'indent' }])}>{t('ol.ins.indent')}</Button>
                <Button size="sm" disabled={busy} onClick={() => run([{ op: 'move_item', item: it.id, how: 'outdent' }])}>{t('ol.ins.outdent')}</Button>
                <Button size="sm" disabled={busy} onClick={() => run([{ op: 'move_item', item: it.id, how: 'join' }])}>{t('ol.ins.join')}</Button>
                <Button size="sm" disabled={busy} onClick={() => run([{ op: 'move_item', item: it.id, how: 'split' }])}>{t('ol.ins.split')}</Button>
              </>}
              {!it.fork && <Button size="sm" icon="branch" onClick={() => openDialog({ kind: 'fork', item: it.id })}>{t('ol.ins.fork')}</Button>}
              {parent?.fork && parent.fork.chosen !== it.id && (
                <>
                  <Button size="sm" variant="primary" disabled={busy} onClick={() => run([{ op: 'choose_direction', item: parent.id, direction: it.id }])}>{t('ol.fork.choose', { n: it.direction ?? '' })}</Button>
                  <Button size="sm" onClick={() => openDialog({ kind: 'abandon', item: parent.id, direction: it.id })}>{t('ol.fork.abandon', { n: it.direction ?? '' })}</Button>
                </>
              )}
              {!it.direction && <Button size="sm" variant="danger" onClick={() => openDialog({ kind: 'remove', item: it.id })}>{t('ol.ins.remove')}</Button>}
            </div>
          ) : it.direction ? (
            <div className="row"><Button size="sm" onClick={revive}>↺ {t('ol.ins.revive')}</Button></div>
          ) : null}
          <div className="row"><Button size="sm" icon="robot" onClick={ask}>{t('ol.ins.ask')}</Button>
            {parent && <Button size="sm" variant="ghost" onClick={() => select(parent.id)}>↑ {parent.num}</Button>}</div>
        </div>
      </div>
    </>
  );
}

/** A fork: its directions side by side, choosing one, abandoning one, adding one; the abandoned ones with why. */
function ForkPane({ it }: { it: Item }) {
  const t = useT();
  const rel = useRelTime();
  const { askAgent } = useApp();
  const { tasks, run, busy, openDialog, select } = useOl();
  const [adding, setAdding] = useState('');
  const dirs = it.fork?.directions ?? [];
  const live = dirs.filter(d => d.state !== 'abandoned');
  const gone = dirs.filter(d => d.state === 'abandoned');
  const chosen = it.fork?.chosen ?? null;
  const done = (d: Item) => d.tasks.map(id => tasks.get(id)).filter(x => x && x.status === 'done').length;
  const ask = () => askAgent(t('ol.fork.askPrompt', { num: it.num, text: it.text, dirs: live.map(d => `${t('ol.dir', { n: d.direction ?? '' })}: ${d.text}`).join('; ') }), {});
  return (
    <div className="ol-ins-sec">
      <h3>{t('ol.fork.title')}</h3>
      {live.length > 0 && (
        <table className="ol-cmp">
          <thead><tr><th />{live.map(d => <th key={d.id}><button type="button" className="ol-dl" onClick={() => select(d.id)}>{t('ol.dir', { n: d.direction ?? '' })}</button></th>)}</tr></thead>
          <tbody>
            <tr><td className="ol-hint">{t('ol.fork.row.state')}</td>{live.map(d => <td key={d.id}><StateChip it={d} chosen={chosen === d.id} /></td>)}</tr>
            <tr><td className="ol-hint">{t('ol.fork.row.tasks')}</td>{live.map(d => <td key={d.id} className="num">{done(d)}/{d.tasks.length}</td>)}</tr>
            <tr><td className="ol-hint">{t('ol.fork.row.evidence')}</td>{live.map(d => (
              <td key={d.id}><div className="ol-flags">{d.evidence.length ? d.evidence.map(e => <EvidenceChip key={e.id} e={e} />) : <span className="ol-faint">—</span>}</div></td>
            ))}</tr>
          </tbody>
        </table>
      )}
      <div className="row wrap" style={{ gap: 6 }}>
        {live.filter(d => d.id !== chosen).map((d, i) => (
          <Button key={d.id} size="sm" variant={i === 0 && !chosen ? 'primary' : undefined} disabled={busy}
            onClick={() => run([{ op: 'choose_direction', item: it.id, direction: d.id }])}>{t('ol.fork.choose', { n: d.direction ?? '' })}</Button>
        ))}
        {live.map(d => (
          <Button key={`a:${d.id}`} size="sm" onClick={() => openDialog({ kind: 'abandon', item: it.id, direction: d.id })}>{t('ol.fork.abandon', { n: d.direction ?? '' })}</Button>
        ))}
      </div>
      {!chosen && <span className="ol-hint">{t('ol.fork.after')}</span>}
      <div className="row" style={{ gap: 6 }}>
        <input className="input grow" value={adding} placeholder={t('ol.fork.dirPh')} onChange={e => setAdding(e.target.value)}
          onKeyDown={async e => { if (e.key === 'Enter' && adding.trim()) { if (await run([{ op: 'add_direction', item: it.id, text: adding.trim() }])) setAdding(''); } }} />
        <Button size="sm" icon="plus" disabled={!adding.trim() || busy} onClick={async () => { if (await run([{ op: 'add_direction', item: it.id, text: adding.trim() }])) setAdding(''); }}>{t('ol.fork.addDir')}</Button>
      </div>
      {gone.length > 0 && (
        <div className="col" style={{ gap: 4, borderTop: 'var(--line) solid var(--rule)', paddingTop: 8 }}>
          <h3>{t('ol.fork.abandoned')}</h3>
          {gone.map(d => (
            <div key={d.id} className="col" style={{ gap: 2 }}>
              <button type="button" className="ol-link" style={{ textAlign: 'left' }} onClick={() => select(d.id, { reveal: true })}>{t('ol.dir', { n: d.direction ?? '' })} · {d.text}</button>
              <span className="ol-hint">{d.why ?? (d.why_kind ? t(`ol.reason.${d.why_kind}`) : '')}{d.ended_at ? ` · ${t('ol.ins.abandonedAt', { when: rel(d.ended_at) })}` : ''}</span>
            </div>
          ))}
        </div>
      )}
      <div className="row"><Button size="sm" icon="robot" onClick={ask}>{t('ol.fork.ask')}</Button></div>
    </div>
  );
}

function SectionPane({ s }: { s: Section }) {
  const t = useT();
  const { o, lang, run, busy, error, setEditing, select } = useOl();
  const phaseLabel = usePhaseLabel();
  const [title, setTitle] = useState(bi(s.title, lang));
  const [role, setRole] = useState(s.role);
  const [adding, setAdding] = useState('');
  useEffect(() => { setTitle(bi(s.title, lang)); setRole(s.role); }, [s, lang]);
  const pos = o.sections.findIndex(x => x.id === s.id);
  return (
    <>
      <div className="ol-ins-head">
        <div className="row" style={{ gap: 8 }}><h2>§{s.num}</h2><span className="chip">{phaseLabel(s.phase)}</span>
          <span className="grow" /><span className="ol-hint">{t('ol.group.progressSum', { h: s.counts.holds, n: s.counts.items })}</span></div>
        {error && <div className="notice accent" role="alert">{error}</div>}
      </div>
      <div className="ol-ins-body">
        <label className="field"><span className="label">{t('ol.sec.title')}</span>
          <input className="input" value={title} onChange={e => setTitle(e.target.value)}
            onBlur={() => title.trim() && title.trim() !== bi(s.title, lang) && run([{ op: 'edit_section', section: s.id, title: title.trim() }])}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
        </label>
        <label className="field"><span className="label">{t('ol.sec.role')}</span>
          <textarea className="textarea" rows={2} value={role} onChange={e => setRole(e.target.value)}
            onBlur={() => role !== s.role && run([{ op: 'edit_section', section: s.id, role }])} />
        </label>
        <label className="field"><span className="label">{t('ol.sec.phase')}</span>
          <select className="select" value={s.phase} disabled={busy} onChange={e => run([{ op: 'edit_section', section: s.id, phase: e.target.value as SectionPhase }])}>
            {SECTION_PHASES.map(p => <option key={p} value={p}>{phaseLabel(p)}</option>)}
          </select>
        </label>
        <div className="row wrap" style={{ gap: 6 }}>
          <Button size="sm" onClick={() => setEditing({ kind: 'new', parent: s.id, at: {} })}>{t('ol.add.item')}</Button>
          <Button size="sm" disabled={busy || pos <= 0} onClick={() => run([{ op: 'move_section', section: s.id, to: pos - 1 }])}>{t('ol.ins.up')}</Button>
          <Button size="sm" disabled={busy || pos >= o.sections.length - 1} onClick={() => run([{ op: 'move_section', section: s.id, to: pos + 1 }])}>{t('ol.ins.down')}</Button>
        </div>
        <div className="ol-ins-sec">
          <h3>{t('ol.sec.addAfter')}</h3>
          <div className="row" style={{ gap: 6 }}>
            <input className="input grow" value={adding} placeholder={t('ol.sec.newPh')} onChange={e => setAdding(e.target.value)} />
            <Button size="sm" icon="plus" disabled={!adding.trim() || busy}
              onClick={async () => { if (await run([{ op: 'add_section', title: adding.trim(), phase: s.phase === 'summary' ? 'insight' : s.phase, after: s.id }])) setAdding(''); }}>{t('ol.sec.add')}</Button>
          </div>
        </div>
        <div className="ol-ins-sec">
          <Button size="sm" variant="danger" disabled={busy} onClick={async () => { if (window.confirm(t('ol.sec.removeConfirm', { num: s.num }))) { await run([{ op: 'remove_section', section: s.id }]); select(null); } }}>{t('ol.sec.remove')}</Button>
        </div>
        <details>
          <summary className="ol-hint">{t('ol.sec.asText')}</summary>
          <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--fs-xs)' }}>{outlineText({ ...o, sections: [s] }, lang)}</pre>
        </details>
      </div>
    </>
  );
}
