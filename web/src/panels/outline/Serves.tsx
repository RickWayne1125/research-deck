// Which outline items a run's node or a figure serves: through the tasks linked to it, or the items' own edges to it.
// Shown on the run drawer and the figure view, each a chip back to the item on the outline.
import { useMemo } from 'react';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useT } from '../../i18n';
import type { Item } from './api';
import { allItems } from './model';
import './i18n';

export function useServed(node?: string | null, figure?: string | null): Item[] {
  const { outline } = useToday();
  return useMemo(() => {
    if (!outline || (!node && !figure)) return [];
    const ids = new Set<string>();
    for (const t of outline.tasks) {
      if (t.abandoned || t.status === 'sugg') continue;
      if ((node && t.links?.node === node) || (figure && t.links?.figure === figure)) t.items.forEach(i => ids.add(i));
    }
    const out: Item[] = [];
    for (const it of allItems(outline)) {
      if (it.state === 'abandoned') continue;
      if (ids.has(it.id) || (node && it.evidence.some(e => e.id === node && e.rel !== 'task'))) out.push(it);
    }
    return out;
  }, [outline, node, figure]);
}

export function ServedChips({ items }: { items: Item[] }) {
  const { navigate } = useApp();
  return (
    <span className="row wrap" style={{ gap: 4, display: 'inline-flex' }}>
      {items.map(i => (
        <button key={i.id} type="button" className="chip mono" title={i.text} onClick={() => navigate('outline', `@item/${i.id}`)}>{i.num}</button>
      ))}
    </span>
  );
}

/** A <dt>/<dd> pair for a details list: the items the node serves (nothing when it serves none). */
export function ServesRow({ node, figure }: { node?: string | null; figure?: string | null }) {
  const t = useT();
  const items = useServed(node, figure);
  if (!items.length) return null;
  return <><dt>{t('ol.serves')}</dt><dd><ServedChips items={items} /></dd></>;
}

/** Inline: "提纲 5.1 5.2" (nothing when it serves none). */
export function ServesInline({ node, figure }: { node?: string | null; figure?: string | null }) {
  const t = useT();
  const items = useServed(node, figure);
  if (!items.length) return null;
  return <span className="row" style={{ gap: 4, display: 'inline-flex' }}><span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('ol.serves')}</span><ServedChips items={items} /></span>;
}
