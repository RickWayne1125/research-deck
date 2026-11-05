// ⌘K: jump to a section, an outline item, a map node, a document, a figure or an experiment. Lists load when the palette opens; typing
// filters by name and id; ↑/↓ pick, ↵ opens, Esc closes.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useApp, FIGURES } from '../state/app';
import { useToday } from '../state/today';
import { allowedViews, visibleViews } from '../state/views';
import { allItems } from '../panels/outline/model';
import { useI18n, useT } from '../i18n';
import { writingApi } from '../panels/writing/api';
import { vz } from '../panels/visualization/api';
import { Icon } from './icons';
import type { ViewId } from '../types';

interface Entry { key: string; section: 'views' | 'items' | 'nodes' | 'docs' | 'figures' | 'runs'; label: string; hint: string; icon: string; go: () => void }
const PER_SECTION = 8;

export function Palette({ onClose }: { onClose: () => void }) {
  const { projectId, project, navigate } = useApp();
  const { lang } = useI18n();
  const t = useT();
  const today = useToday();
  const pid = projectId!;
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [docs, setDocs] = useState<{ path: string; title: string }[]>([]);
  const [figs, setFigs] = useState<{ id: string; title: string; source: string }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const views = visibleViews(project);
  const mapOpen = allowedViews(project).includes('dag');

  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    writingApi.docs(pid).then(d => setDocs(Array.isArray(d) ? d : [])).catch(() => {});
    vz.list(pid).then(f => setFigs(Array.isArray(f) ? f : [])).catch(() => {});
  }, [pid]);

  const entries = useMemo<Entry[]>(() => {
    const title = (n: { title: { en?: string; zh?: string }; id: string }) => (lang === 'zh' ? n.title.zh || n.title.en : n.title.en || n.title.zh) || n.id;
    const all: Entry[] = [
      ...views.map(v => ({ key: `v:${v}`, section: 'views' as const, label: t(`nav.${v}`), hint: '', icon: v === 'overview' ? 'overview' : v, go: () => navigate(v as ViewId) })),
      ...(views.includes('outline') ? [...allItems(today.outline)].filter(i => i.state !== 'abandoned') : []).map(i => ({ key: `i:${i.id}`, section: 'items' as const, label: i.text, hint: i.direction ? `${i.num} · ${i.direction}` : i.num, icon: 'outline', go: () => navigate('outline', `@item/${i.id}`) })),
      ...(mapOpen ? (today.graph?.nodes ?? []) : []).map(n => ({ key: `n:${n.id}`, section: 'nodes' as const, label: title(n), hint: n.id, icon: 'dag', go: () => navigate('dag', n.id) })),
      ...docs.map(d => ({ key: `d:${d.path}`, section: 'docs' as const, label: d.title || d.path, hint: d.path, icon: 'file', go: () => navigate('writing', d.path) })),
      ...figs.map(f => ({ key: `f:${f.id}`, section: 'figures' as const, label: f.title || f.id, hint: f.source, icon: 'image', go: () => navigate('writing', `${FIGURES}/${f.id}`) })),
      ...(today.runs ?? []).map(r => ({ key: `r:${r.id}`, section: 'runs' as const, label: r.title || r.id, hint: r.id, icon: 'experiments', go: () => navigate('experiments', r.id) })),
    ];
    const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const hits = words.length ? all.filter(e => words.every(w => `${e.label} ${e.hint}`.toLowerCase().includes(w))) : all;
    const counts = new Map<string, number>();
    return hits.filter(e => { const n = counts.get(e.section) ?? 0; counts.set(e.section, n + 1); return n < (words.length ? PER_SECTION : e.section === 'views' ? 10 : 4); });
  }, [views, mapOpen, today.graph, today.outline, today.runs, docs, figs, q, lang, t, navigate]);

  useEffect(() => { setActive(0); }, [q]);
  useEffect(() => { list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' }); }, [active]);

  const open = (e: Entry | undefined) => { if (!e) return; onClose(); e.go(); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(i => Math.min(entries.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(i => Math.max(0, i - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); open(entries[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  };

  let lastSection = '';
  return (
    <div className="scrim palette-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-label={t('nav.jump')} onKeyDown={onKey}>
        <div className="palette-input">
          <Icon name="search" />
          <input ref={input} value={q} onChange={e => setQ(e.target.value)} placeholder={t('palette.placeholder')}
            role="combobox" aria-expanded="true" aria-controls="rd-palette-list" aria-activedescendant={entries[active] ? `rd-pal-${active}` : undefined} />
        </div>
        <div className="palette-list" id="rd-palette-list" role="listbox" ref={list}>
          {!entries.length && <div className="palette-empty muted">{t('palette.empty')}</div>}
          {entries.map((e, i) => {
            const head = e.section !== lastSection ? (lastSection = e.section, <div key={`h:${e.section}`} className="label palette-head">{t(`palette.${e.section}`)}</div>) : null;
            return [head, (
              <button key={e.key} id={`rd-pal-${i}`} data-i={i} type="button" role="option" aria-selected={i === active}
                className={`palette-item${i === active ? ' active' : ''}`} onMouseMove={() => setActive(i)} onClick={() => open(e)}>
                <Icon name={e.icon} size={14} />
                <span className="ellipsis grow">{e.label}</span>
                {e.hint && <span className="faint mono ellipsis palette-hint">{e.hint}</span>}
              </button>
            )];
          })}
        </div>
        <div className="palette-foot faint">{t('palette.hint')}</div>
      </div>
    </div>
  );
}
