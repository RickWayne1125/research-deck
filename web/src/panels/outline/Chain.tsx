// A numbered chain (2.1, 2.2 …; sub-items 3.1.1 …): a line through the number pills, parallel items framed together
// with what they lead to, sub-chains folded until opened, forks as direction cards. Items are edited in place like an
// outliner: ↵ saves and starts the next item, ⌥↵ a parallel one, Tab puts it under the item above, ⇧Tab one level up,
// Esc cancels; ⌘. folds.
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as RKeyboardEvent } from 'react';
import { useApp } from '../../state/app';
import { useT } from '../../i18n';
import type { Item, Step } from './api';
import { useOl, type At } from './ctx';
import { STATE_TONE, liveSteps, nextNumAfter } from './model';
import { EvidenceChip, StateChip, TaskChip } from './parts';

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');

/** The editor of an item's text (or of a new item): a textarea that grows with its text. */
export function ItemEditor({ initial, placeholder, onCommit, onCancel, onIndent, onOutdent }: {
  initial: string; placeholder?: string;
  onCommit: (text: string, then: 'next' | 'par' | 'stay') => void; onCancel: () => void;
  onIndent?: (text: string) => void; onOutdent?: (text: string) => void;
}) {
  const t = useT();
  const [text, setText] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  const done = useRef(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);
  useEffect(() => { const el = ref.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, []);
  const finish = (fn: () => void) => { if (done.current) return; done.current = true; fn(); };
  const onKey = (e: RKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const then = e.altKey ? 'par' : (e.metaKey || e.ctrlKey) ? 'stay' : 'next';
      finish(() => onCommit(text, then));
    } else if (e.key === 'Escape') {
      e.preventDefault(); finish(onCancel);
    } else if (e.key === 'Tab' && (e.shiftKey ? onOutdent : onIndent)) {
      e.preventDefault();
      finish(() => (e.shiftKey ? onOutdent! : onIndent!)(text));
    }
  };
  return (
    <div className="col grow" style={{ gap: 2, minWidth: 0 }} onClick={e => e.stopPropagation()}>
      <textarea ref={ref} className="ol-edit" rows={1} value={text} placeholder={placeholder} onChange={e => setText(e.target.value)}
        onKeyDown={onKey} onBlur={() => finish(() => (text.trim() && text.trim() !== initial.trim() ? onCommit(text, 'stay') : onCancel()))} />
      <span className="ol-edit-hint">{t('ol.edit.hint')}</span>
    </div>
  );
}

/** A new item being written at its place in a chain. */
function DraftRow({ parent, at, par, initial = '' }: { parent: string; at: At; par: boolean; initial?: string }) {
  const t = useT();
  const { run, setEditing, select, toggle, items } = useOl();
  const commit = async (text: string, then: 'next' | 'par' | 'stay') => {
    if (!text.trim()) { setEditing(null); return; }
    const res = await run([{ op: 'add_item', parent, text: text.trim(), at }]);
    const id = res?.last;
    if (!id) { setEditing(null); return; }
    if (then === 'next') setEditing({ kind: 'new', parent, at: { after: id } });
    else if (then === 'par') setEditing({ kind: 'new', parent, at: { parallel: id } });
    else { setEditing(null); select(id); }
  };
  // Tab: the new item goes under the item it follows; ⇧Tab: up a level, after its parent.
  const anchor = 'after' in at ? at.after : 'parallel' in at ? at.parallel : null;
  const indent = anchor ? (text: string) => { toggle(anchor, true); setEditing({ kind: 'new', parent: anchor, at: {}, text }); } : undefined;
  const up = items.get(parent);
  const outdent = up && !up.direction ? (text: string) => setEditing({ kind: 'new', parent: up.parent, at: { after: up.id }, text }) : undefined;
  return (
    <div className="ol-nr dash">
      <span className="ol-nb" aria-hidden="true">+</span>
      <div className={cx('ol-nt', par && 'par')}>
        <ItemEditor initial={initial} placeholder={t('ol.add.ph')} onCommit={commit} onCancel={() => setEditing(null)} onIndent={indent} onOutdent={outdent} />
      </div>
    </div>
  );
}

function draftAt(at: At, id: string | null): 'after' | 'parallel' | null {
  if (!id) return null;
  if ('after' in at && at.after === id) return 'after';
  if ('parallel' in at && at.parallel === id) return 'parallel';
  return null;
}

/** A chain of steps under `parent` (a section or an item). */
export function Chain({ steps, parent, depth }: { steps: Step[]; parent: string; depth: number }) {
  const t = useT();
  const { showAbandoned, editing } = useOl();
  const shown = liveSteps(steps, showAbandoned);
  const ed = editing?.kind === 'new' && editing.parent === parent ? editing : null;
  const draft = ed ? ed.at : null;
  const init = ed?.text ?? '';
  const isFirst = !!draft && 'first' in draft;
  const atEnd = !!draft && !('first' in draft) && !('after' in draft) && !('parallel' in draft);
  if (!shown.length && !draft) return null;
  // the number pills are as wide as the longest number here (3.1, 3.1.2, 3.1.2.1 …)
  const longest = Math.max(3, ...shown.flatMap(st => st.items.map(i => i.num.length)), draft && shown[0] ? shown[0].items[0].num.length : 3);
  return (
    <ol className="ol-nc" data-depth={depth} style={{ ['--pill' as string]: `${Math.max(36, 12 + longest * 7)}px` }}>
      {isFirst && <li><DraftRow parent={parent} at={draft!} par={false} initial={init} /></li>}
      {shown.map((step, si) => {
        const par = step.items.length > 1 || (!!draft && step.items.some(i => draftAt(draft, i.id) === 'parallel'));
        const next = nextNumAfter(shown, si);
        const after = !!draft && step.items.some(i => draftAt(draft, i.id) === 'after');
        return [
          <li key={step.items[0].id}>
            {step.items.map(it => [
              <ItemRow key={it.id} it={it} par={par} depth={depth} />,
              draft && draftAt(draft, it.id) === 'parallel' ? <DraftRow key={`d:${it.id}`} parent={parent} at={draft} par initial={init} /> : null,
            ])}
            {par && (
              <div className="ol-foot"><span />
                <span className="ol-nt par">{step.note ? t('ol.par.note', { note: step.note }) : next ? t('ol.par.lead', { num: next }) : t('ol.par')}</span>
              </div>
            )}
          </li>,
          after ? <li key={`d:${step.items[0].id}`}><DraftRow parent={parent} at={draft!} par={false} initial={init} /></li> : null,
        ];
      })}
      {atEnd && <li><DraftRow parent={parent} at={draft!} par={false} initial={init} /></li>}
    </ol>
  );
}

/** One item: its number, text (editable), state, tasks and evidence, its fork, and its sub-chain. */
export function ItemRow({ it, par, depth }: { it: Item; par: boolean; depth: number }) {
  const t = useT();
  const { sel, select, editing, setEditing, isOpen, toggle, tasks, showAbandoned, run, itemBefore } = useOl();
  const kids = liveSteps(it.children, showAbandoned);
  const nkids = kids.reduce((n, s) => n + s.items.length, 0);
  const open = isOpen(it) || (editing?.kind === 'new' && editing.parent === it.id);
  const editText = editing?.kind === 'text' && editing.id === it.id;
  const tone = it.state === 'abandoned' ? 'gone' : STATE_TONE[it.state];
  const myTasks = it.tasks.map(id => tasks.get(id)).filter((x): x is NonNullable<typeof x> => !!x);
  const sugg = it.suggested.map(id => tasks.get(id)).filter((x): x is NonNullable<typeof x> => !!x);
  const commit = async (text: string, then: 'next' | 'par' | 'stay') => {
    const changed = text.trim() && text.trim() !== it.text.trim();
    if (changed && !(await run([{ op: 'edit_item', item: it.id, text: text.trim() }]))) { setEditing(null); return; }
    if (then === 'next') setEditing({ kind: 'new', parent: it.parent, at: { after: it.id } });
    else if (then === 'par') setEditing({ kind: 'new', parent: it.parent, at: { parallel: it.id } });
    else setEditing(null);
  };
  const move = async (text: string, how: 'indent' | 'outdent') => {
    const ops = [];
    if (text.trim() && text.trim() !== it.text.trim()) ops.push({ op: 'edit_item', item: it.id, text: text.trim() });
    ops.push({ op: 'move_item', item: it.id, how });
    const prev = how === 'indent' ? itemBefore(it.id) : null;
    if (prev) toggle(prev, true);                 // it goes under the item above: show it there
    setEditing(null);
    if (await run(ops)) { select(it.id); setEditing({ kind: 'text', id: it.id }); }
  };
  return (
    <div className={cx('ol-nr', tone)} id={`ol-i-${it.id}`} data-ol-item={it.id}>
      <button type="button" className="ol-nb" onClick={() => select(it.id)} title={it.id}>{it.num}</button>
      <div className={cx('ol-nt', par && 'par', it.state === 'proposed' && 'prop', sel === it.id && 'sel')}
        onClick={(e) => { e.stopPropagation(); select(it.id); }}>
        <div className="ol-nt-top">
          {editText
            ? <ItemEditor initial={it.text} onCommit={commit} onCancel={() => setEditing(null)}
                onIndent={text => move(text, 'indent')} onOutdent={text => move(text, 'outdent')} />
            : <div className="ol-t" tabIndex={0} data-ol-text={it.id}
                onClick={(e) => { e.stopPropagation(); if (sel === it.id && it.state !== 'abandoned') setEditing({ kind: 'text', id: it.id }); else select(it.id); }}
                onDoubleClick={() => it.state !== 'abandoned' && setEditing({ kind: 'text', id: it.id })}>{it.text}</div>}
          <StateChip it={it} />
        </div>
        {(myTasks.length > 0 || sugg.length > 0 || it.evidence.length > 0) && (
          <div className="ol-rows">
            {(myTasks.length > 0 || sugg.length > 0) && <>
              <span className="k">{t('ol.row.tasks')}</span>
              <div className="ol-flags">{myTasks.map(x => <TaskChip key={x.id} task={x} />)}{sugg.map(x => <TaskChip key={x.id} task={x} />)}</div>
            </>}
            {it.evidence.length > 0 && <>
              <span className="k">{t('ol.row.evidence')}</span>
              <div className="ol-flags">{it.evidence.map(e => <EvidenceChip key={`${e.rel}:${e.id}`} e={e} />)}</div>
            </>}
          </div>
        )}
        {it.fork && <ForkBlock it={it} />}
        {nkids > 0 && !open && (
          <button type="button" className="ol-fold" onClick={(e) => { e.stopPropagation(); toggle(it.id, true); }}>
            ▸ {t('ol.foldedHolds', { n: it.kids.total || nkids, h: it.kids.holds })}
          </button>
        )}
        {open && (nkids > 0 || (editing?.kind === 'new' && editing.parent === it.id)) && (
          <div className="ol-kids">
            <Chain steps={it.children} parent={it.id} depth={depth + 1} />
            {nkids > 0 && <button type="button" className="ol-fold" onClick={(e) => { e.stopPropagation(); toggle(it.id, false); }}>▾ {t('ol.collapse')}</button>}
          </div>
        )}
      </div>
    </div>
  );
}

/** A fork's directions: the live ones as cards, the abandoned ones folded into a line (the research tree shows them). */
export function ForkBlock({ it }: { it: Item }) {
  const t = useT();
  const { navigate } = useApp();
  const { showAbandoned } = useOl();
  const dirs = it.fork?.directions ?? [];
  const gone = dirs.filter(d => d.state === 'abandoned');
  const shown = showAbandoned ? dirs : dirs.filter(d => d.state !== 'abandoned');
  return (
    <div className="ol-fork" onClick={e => e.stopPropagation()}>
      {shown.map(d => <DirectionCard key={d.id} d={d} chosen={it.fork?.chosen === d.id} />)}
      {!showAbandoned && gone.length > 0 && (
        <div className="ol-dir hid">
          <span className="ol-hint grow">{t('ol.dir.hidden', { n: gone.length, names: gone.map(d => d.text).join(t('ol.secSep')) })}</span>
          <button type="button" className="ol-link" onClick={() => navigate('outline', '@tree')}>{t('ol.dir.show')}</button>
        </div>
      )}
    </div>
  );
}

function DirectionCard({ d, chosen }: { d: Item; chosen: boolean }) {
  const t = useT();
  const { sel, select, editing, setEditing, tasks, isOpen, toggle, showAbandoned, run } = useOl();
  const editText = editing?.kind === 'text' && editing.id === d.id;
  const myTasks = [...d.tasks, ...d.suggested].map(id => tasks.get(id)).filter((x): x is NonNullable<typeof x> => !!x);
  const kids = liveSteps(d.children, showAbandoned);
  const nkids = kids.reduce((n, s) => n + s.items.length, 0);
  const open = isOpen(d) || (editing?.kind === 'new' && editing.parent === d.id);
  const commit = async (text: string) => {
    if (text.trim() && text.trim() !== d.text.trim()) await run([{ op: 'edit_item', item: d.id, text: text.trim() }]);
    setEditing(null);
  };
  return (
    <div className={cx('ol-dir', chosen && 'chosen', d.state === 'abandoned' && 'gone', sel === d.id && 'sel')} id={`ol-i-${d.id}`} data-ol-item={d.id}
      onClick={() => select(d.id)}>
      <div className="ol-nt-top">
        <button type="button" className="ol-dl" onClick={(e) => { e.stopPropagation(); select(d.id); }}>{t('ol.dir', { n: d.direction ?? '?' })}</button>
        {editText
          ? <ItemEditor initial={d.text} onCommit={commit} onCancel={() => setEditing(null)} />
          : <div className="ol-t" tabIndex={0} data-ol-text={d.id}
              onClick={(e) => { e.stopPropagation(); if (sel === d.id && d.state !== 'abandoned') setEditing({ kind: 'text', id: d.id }); else select(d.id); }}>{d.text}</div>}
        <StateChip it={d} chosen={chosen} />
      </div>
      {(myTasks.length > 0 || d.evidence.length > 0) && (
        <div className="ol-rows">
          {myTasks.length > 0 && <><span className="k">{t('ol.row.tasks')}</span><div className="ol-flags">{myTasks.map(x => <TaskChip key={x.id} task={x} />)}</div></>}
          {d.evidence.length > 0 && <><span className="k">{t('ol.row.evidence')}</span><div className="ol-flags">{d.evidence.map(e => <EvidenceChip key={`${e.rel}:${e.id}`} e={e} />)}</div></>}
        </div>
      )}
      {d.state === 'abandoned' && d.why && <span className="ol-why">{t('ol.tree.why', { why: d.why })}</span>}
      {d.fork && <ForkBlock it={d} />}
      {nkids > 0 && !open && (
        <button type="button" className="ol-fold" onClick={(e) => { e.stopPropagation(); toggle(d.id, true); }}>▸ {t('ol.foldedHolds', { n: d.kids.total || nkids, h: d.kids.holds })}</button>
      )}
      {open && (nkids > 0 || (editing?.kind === 'new' && editing.parent === d.id)) && (
        <div className="ol-kids">
          <Chain steps={d.children} parent={d.id} depth={d.depth + 1} />
          {nkids > 0 && <button type="button" className="ol-fold" onClick={(e) => { e.stopPropagation(); toggle(d.id, false); }}>▾ {t('ol.collapse')}</button>}
        </div>
      )}
    </div>
  );
}
