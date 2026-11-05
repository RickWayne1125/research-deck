// The outline itself, two ways: by phase (the stage line: one node per phase, its sections beside it, a passed phase
// folded unless something in it does not hold; the current one with what leaving it takes) or in paper order. With
// an item selected (not editing): ↵ edits it, ⌥↵ starts a parallel item, Tab / ⇧Tab indent and outdent, ⌥↑ / ⌥↓ move
// it, ↑ / ↓ select the item above or below, ⌘. folds, Esc lets go.
import { useEffect, useState } from 'react';
import { useT } from '../../i18n';
import type { Group, Section } from './api';
import { useOl } from './ctx';
import { Chain } from './Chain';
import { bi, pathTo, phaseIndex, phaseMark } from './model';
import { usePhaseLabel, usePhaseName } from './parts';

const GROUP_TONE: Record<Group['state'], string> = { done: 'ok', current: 'run', later: 'off', summary: 'dash' };

export function Story({ order }: { order: 'phase' | 'paper' }) {
  useOutlinerKeys();
  const { o } = useOl();
  if (order === 'paper') return <div className="col" style={{ gap: 12 }}>{o.sections.map(s => <SectionBox key={s.id} s={s} paper />)}</div>;
  return <StageLine />;
}

function StageLine() {
  const t = useT();
  const { o, sel, openDialog } = useOl();
  const phaseName = usePhaseName();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const secs = new Map(o.sections.map(s => [s.id, s]));
  const selSection = sel ? (secs.has(sel) ? sel : pathTo(o, sel)?.section.id ?? null) : null;
  const lastPhase = [...o.groups].reverse().find(g => g.state !== 'summary')?.phase;
  return (
    <ol className="ol-line">
      {o.groups.map(g => {
        const ss = g.sections.map(id => secs.get(id)).filter((s): s is Section => !!s);
        const names = ss.map(s => `§${s.num}`).join(t('ol.secSep'));
        const fold = g.state === 'done' && g.missing.length === 0;
        const open = expanded[g.phase] ?? (!fold || ss.some(s => s.id === selSection));
        const mark = g.state === 'done' ? '✓' : g.state === 'summary' ? '∑' : String(phaseIndex(g.phase) + 1);
        const name = g.phase === 'summary' ? t('ol.group.summaryName') : `${phaseMark(g.phase)} ${phaseName(g.phase)}`;
        const progress = g.phase === 'summary' ? t('ol.group.progressSum', { h: g.holds, n: g.items })
          : t('ol.group.progress', { h: g.holds, n: g.items, d: g.tasks_done, t: g.tasks });
        const shown = g.missing.slice(0, 4).join(t('ol.secSep')) + (g.missing.length > 4 ? '…' : '');
        return (
          <li key={g.phase} className={`ol-sl ${g.state}`}>
            <span className="ol-node" aria-hidden="true">{mark}</span>
            <div className="ol-sbox">
              <div className="ol-sbox-head">
                <h2>{name}</h2>
                <span className={`chip ol-chip ${GROUP_TONE[g.state]}`}>{t(`ol.group.${g.state}`)}</span>
                <span className="ol-hint">{names} · {progress}</span>
                <span className="grow" />
                {g.state === 'current' && (
                  <button type="button" className="ol-gate" onClick={() => openDialog({ kind: 'leave', phase: g.phase })}>
                    {g.missing.length ? t('ol.group.leaveMissing', { nums: shown })
                      : t(g.phase === lastPhase ? 'ol.group.leaveLast' : 'ol.group.leave', { secs: names })}
                  </button>
                )}
                {g.state === 'later' && o.stage_mode !== 'free' && <span className="chip ol-chip off">{t('ol.group.waits')}</span>}
                {g.state === 'summary' && <span className="ol-hint">{t('ol.group.noTasks')}</span>}
                {(g.state === 'done' || !open) && (
                  <button type="button" className="ol-link" onClick={() => setExpanded(x => ({ ...x, [g.phase]: !open }))}>{t(open ? 'ol.collapse' : 'ol.expand')}</button>
                )}
              </div>
              {open && ss.map(s => <SectionBox key={s.id} s={s} />)}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function SectionBox({ s, paper = false }: { s: Section; paper?: boolean }) {
  const t = useT();
  const { lang, sel, select, editing, setEditing } = useOl();
  const phaseLabel = usePhaseLabel();
  const adding = editing?.kind === 'new' && editing.parent === s.id && !('after' in editing.at) && !('parallel' in editing.at) && !('first' in editing.at);
  return (
    <section className={`ol-sec${sel === s.id ? ' sel' : ''}`} id={`ol-i-${s.id}`} aria-label={`§${s.num} ${bi(s.title, lang)}`}
      onClick={() => select(s.id)}>
      <div className="ol-sec-head">
        <h3>§{s.num} {bi(s.title, lang)}</h3>
        {paper ? <span className={`chip ol-chip${s.phase === 'summary' ? ' dash' : ''}`}>{phaseLabel(s.phase)}</span>
          : s.phase === 'summary' && <span className="chip ol-chip dash">{t('ol.sec.summary')}</span>}
        {s.role && <span className="ol-sec-role">{s.role}</span>}
      </div>
      <Chain steps={s.items} parent={s.id} depth={0} />
      {!adding && (
        <button type="button" className="btn sm ghost ol-sec-add" onClick={(e) => { e.stopPropagation(); setEditing({ kind: 'new', parent: s.id, at: {} }); }}>
          + {t('ol.add.item')}
        </button>
      )}
    </section>
  );
}

/** The outliner keys for the selected item (the editor handles them itself while an item is being written). */
export function useOutlinerKeys(): void {
  const { sel, select, items, editing, setEditing, toggle, run, dialog } = useOl();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!sel || editing || dialog || document.querySelector('.scrim')) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      // only from the outline itself (an item's text, or nothing focused): a button keeps its own Enter and Tab
      if (el && el !== document.body && (!el.closest('.ol-main') || el.closest('button, a, [role="button"]'))) return;
      const it = items.get(sel);
      const mod = e.metaKey || e.ctrlKey;
      if (e.key === 'Escape') { select(null); return; }
      if (!it) return;
      const live = it.state !== 'abandoned';
      if (e.key === 'Enter' && !mod && live) {
        e.preventDefault();
        if (e.altKey && !it.direction) setEditing({ kind: 'new', parent: it.parent, at: { parallel: it.id } });
        else setEditing({ kind: 'text', id: it.id });
      } else if (e.key === 'Tab' && !it.direction && live) {
        e.preventDefault();
        void run([{ op: 'move_item', item: it.id, how: e.shiftKey ? 'outdent' : 'indent' }]);
      } else if (mod && e.key === '.') {
        e.preventDefault(); toggle(it.id);
      } else if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown') && !it.direction && live) {
        e.preventDefault();
        void run([{ op: 'move_item', item: it.id, how: e.key === 'ArrowUp' ? 'up' : 'down' }]);
      } else if (!e.altKey && !mod && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        const all = [...document.querySelectorAll<HTMLElement>('[data-ol-item]')].map(x => x.dataset.olItem!);
        const at = all.indexOf(sel);
        const next = all[at + (e.key === 'ArrowUp' ? -1 : 1)];
        if (next) {
          e.preventDefault(); select(next);
          document.querySelector<HTMLElement>(`[data-ol-text="${next}"]`)?.focus();
          document.getElementById(`ol-i-${next}`)?.scrollIntoView({ block: 'nearest' });
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sel, select, items, editing, setEditing, toggle, run, dialog]);
}
