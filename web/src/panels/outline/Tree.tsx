// The research tree: every place the outline branches, each direction with its tasks, results, sub-items and, for an
// abandoned one, why it was given up. The overview shows only the chosen and open directions; this shows them all.
import { useState } from 'react';
import { useApp } from '../../state/app';
import { useT } from '../../i18n';
import type { Item } from './api';
import { useOl } from './ctx';
import { forks } from './model';
import { EvidenceChip, StateChip, TaskChip, usePhaseLabel } from './parts';

export function Tree() {
  const t = useT();
  const { o } = useOl();
  const [all, setAll] = useState(true);
  const list = forks(o);
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row wrap" style={{ gap: 10, justifyContent: 'space-between' }}>
        <span className="ol-hint" style={{ maxWidth: 820 }}>{t('ol.tree.hint')}</span>
        <label className="ol-check"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} />{t('ol.tree.show')}</label>
      </div>
      {list.length === 0 ? <div className="card" style={{ padding: 16 }}><span className="ol-hint">{t('ol.tree.none')}</span></div>
        : list.map(({ item, section }) => <ForkTree key={item.id} it={item} phase={section.phase} all={all} />)}
      {list.length > 0 && <span className="ol-hint">{t('ol.tree.foot')}</span>}
    </div>
  );
}

function ForkTree({ it, phase, all }: { it: Item; phase: Parameters<ReturnType<typeof usePhaseLabel>>[0]; all: boolean }) {
  const t = useT();
  const { navigate } = useApp();
  const phaseLabel = usePhaseLabel();
  const dirs = (it.fork?.directions ?? []).filter(d => all || d.state !== 'abandoned');
  const chosen = it.fork?.chosen ?? null;
  const n = Math.max(1, dirs.length);
  return (
    <section className="card" style={{ padding: '16px 18px' }} aria-label={it.num}>
      <div className="ol-tree">
        <button type="button" className="ol-tree-parent" onClick={() => navigate('outline', `@item/${it.id}`)} style={{ font: 'inherit', color: 'inherit' }}>
          <span className="ol-hint">{t('ol.tree.parent', { num: it.num, phase: phaseLabel(phase) })} · {chosen ? t('ol.tree.chosen') : t('ol.tree.open')}</span>
          <b style={{ color: 'var(--ink-strong)' }}>{it.text}</b>
        </button>
        <div className="ol-fan" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))`, ['--fan-l' as string]: `${50 / n}%` }}>
          {dirs.map(d => <Branch key={d.id} d={d} chosen={chosen === d.id} />)}
        </div>
      </div>
    </section>
  );
}

function Branch({ d, chosen }: { d: Item; chosen: boolean }) {
  const t = useT();
  const { navigate } = useApp();
  const { tasks } = useOl();
  const my = [...d.tasks, ...d.suggested].map(id => tasks.get(id)).filter((x): x is NonNullable<typeof x> => !!x);
  const subs = d.children.flatMap(s => s.items);
  const cls = d.state === 'abandoned' ? 'gone' : chosen ? 'win' : d.state === 'holds' ? '' : 'run';
  return (
    <div className={`ol-br ${cls}`}>
      <div className="row" style={{ gap: 8 }}>
        <button type="button" className="ol-dl" onClick={() => navigate('outline', `@item/${d.id}`)}>{t('ol.dir', { n: d.direction ?? '?' })}</button>
        <span className="grow" />
        <StateChip it={d} chosen={chosen} />
      </div>
      <span className="ol-t">{d.text}</span>
      {my.length > 0 && <div className="ol-flags">{my.map(x => <TaskChip key={x.id} task={x} />)}</div>}
      {d.evidence.length > 0 && <div className="ol-flags">{d.evidence.map(e => <EvidenceChip key={`${e.rel}:${e.id}`} e={e} />)}</div>}
      {d.state === 'abandoned' && (d.why || d.why_kind) && <span className="ol-why">{t('ol.tree.why', { why: d.why ?? t(`ol.reason.${d.why_kind}`) })}</span>}
      {subs.length > 0 && (
        <div className="ol-br-sub">
          {subs.map(s => <span key={s.id}><span className="n">{s.num}</span>{s.text}</span>)}
        </div>
      )}
      {d.fork && <span className="ol-hint">{t('ol.tree.parent', { num: d.num, phase: '' })}</span>}
    </div>
  );
}
