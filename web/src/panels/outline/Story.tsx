// The outline itself, two ways: by phase or in paper order, each section a card (Radix Card) with its phase and how many
// of its items hold. By phase, a passed phase is folded into the chips under the cards ("the other sections") unless
// something in it does not hold; the phases' progress and what leaving the current one takes are in the right column
// (Side.tsx). With an item selected (not editing): ↵ edits it, ⌥↵ starts a parallel item, Tab / ⇧Tab indent and
// outdent, ⌥↑ / ⌥↓ move it, ↑ / ↓ select the item above or below, ⌘. folds, Esc lets go.
import { useEffect, useState } from 'react';
import { useT } from '../../i18n';
import type { Group, Section } from './api';
import { useOl } from './ctx';
import { Chain } from './Chain';
import { bi, pathTo } from './model';
import { usePhaseLabel } from './parts';

export function Story({ order }: { order: 'phase' | 'paper' }) {
  useOutlinerKeys();
  const { o } = useOl();
  const groups = new Map<string, Group>();
  for (const g of o.groups) for (const id of g.sections) groups.set(id, g);
  if (order === 'paper') return <div className="ol-secs">{o.sections.map(s => <SectionBox key={s.id} s={s} group={groups.get(s.id)} />)}</div>;
  return <PhaseStory />;
}

function PhaseStory() {
  const t = useT();
  const { o, sel, lang } = useOl();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const secs = new Map(o.sections.map(s => [s.id, s]));
  const selSection = sel ? (secs.has(sel) ? sel : pathTo(o, sel)?.section.id ?? null) : null;
  const shown: { s: Section; g: Group; fold?: () => void }[] = [];
  const folded: { s: Section; g: Group }[] = [];
  for (const g of o.groups) {
    const ss = g.sections.map(id => secs.get(id)).filter((x): x is Section => !!x);
    const passed = g.state === 'done' && g.missing.length === 0;
    const open = expanded[g.phase] ?? (!passed || ss.some(x => x.id === selSection));
    for (const s of ss) {
      if (open) shown.push({ s, g, fold: passed ? () => setExpanded(x => ({ ...x, [g.phase]: false })) : undefined });
      else folded.push({ s, g });
    }
  }
  return (
    <div className="ol-secs">
      {shown.map(({ s, g, fold }) => <SectionBox key={s.id} s={s} group={g} onFold={fold} />)}
      {folded.length > 0 && (
        <div className="ol-rest">
          <span className="ol-hint">{t('ol.side.rest')}</span>
          {folded.map(({ s, g }) => (
            <button key={s.id} type="button" className="badge surface lg" title={t('ol.expand')}
              onClick={() => setExpanded(x => ({ ...x, [g.phase]: true }))}>
              §{s.num} {bi(s.title, lang)} · {s.counts.items ? `${s.counts.holds}/${s.counts.items}` : t('ol.side.noItems')}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** How a section's count reads: all hold (green), the current phase's (amber), in progress (blue), nothing yet (gray). */
function holdsTone(s: Section, g: Group | undefined): string {
  if (!s.counts.items) return '';
  if (s.counts.holds === s.counts.items) return 'ok';
  return g?.state === 'current' ? 'warn' : 'process';
}

export function SectionBox({ s, group, onFold }: { s: Section; group?: Group; onFold?: () => void }) {
  const t = useT();
  const { lang, sel, select, editing, setEditing, o } = useOl();
  const phaseLabel = usePhaseLabel();
  const adding = editing?.kind === 'new' && editing.parent === s.id && !('after' in editing.at) && !('parallel' in editing.at) && !('first' in editing.at);
  const current = group?.state === 'current';
  const waits = group?.state === 'later' && o.stage_mode !== 'free';
  return (
    <section className={`ol-sec${sel === s.id ? ' sel' : ''}${current ? ' cur' : ''}`} id={`ol-i-${s.id}`} aria-label={`§${s.num} ${bi(s.title, lang)}`}
      onClick={() => select(s.id)}>
      <div className="ol-sec-head">
        <span className="ol-sec-num">§{s.num}</span>
        <h3>{bi(s.title, lang)}</h3>
        <span className={`badge${current ? ' accent' : ''}${s.phase === 'summary' ? ' outline' : ''}`}>
          {phaseLabel(s.phase)}{current ? ` · ${t('ol.side.current')}` : ''}
        </span>
        {waits && <span className="badge outline" title={t('ol.group.waits')}>{t('ol.group.later')}</span>}
        <span className="grow" />
        {onFold && (
          <button type="button" className="ol-link" onClick={(e) => { e.stopPropagation(); onFold(); }}>{t('ol.collapse')}</button>
        )}
        {s.counts.items > 0 && (
          <span className={`badge ${holdsTone(s, group)}`}>{t('ol.side.holds', { h: s.counts.holds, n: s.counts.items })}</span>
        )}
      </div>
      {s.role && <p className="ol-sec-role">{s.role}</p>}
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
