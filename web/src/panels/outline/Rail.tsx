// The outline beside the text: the section the cursor is in and its items.
// In the outline file (notes/outline.md, outline/doc.py) the rail is the file's contents: clicking an item or picking a
// section goes to its line, the item at the cursor is marked, and each item shows its state on the outline.
// In any other file it shows how far the text has got with each item (being written, written here, written in another
// file, not yet). Clicking an item goes to its paragraph here, or else to its line in the outline file; it never
// changes the text. The pin ties the paragraph at the cursor to an item with a `% rd:describes <item>` marker (with
// `% rd:sec <section>` when the cursor is not in that section's region); the paper sync turns the markers into the
// map's describes edges, which is what "written" means on the outline. The agent can draft the section from its
// items or check the text against them.
import { useMemo, useState, type ReactNode } from 'react';
import { Button } from '../../components/ui';
import { Icon } from '../../components/icons';
import { ResizeHandle, type Resizable } from '../../components/resize';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useI18n } from '../../i18n';
import type { OutlineSync } from '../writing/api';
import type { Item, Section, Step } from './api';
import { STATE_TONE, bi, docMarks, itemAt, lineOf, markerLines, outlineText, sectionAt, writeStates, type WriteState } from './model';
import './outline.css';
import './i18n';

const TONE: Record<WriteState, string> = { here: 'bad', written: 'ok', elsewhere: 'ok', todo: 'off' };

/** How an item shows in the rail: its tone, its chip, whether it is dimmed, and what clicking it does. */
interface Look { tone: string; label: string; dim: boolean; hint: string; markable: boolean }

export function OutlineRail({ head, text, cursor, path, outlineFile, sync, floating, width, onJump, onInsert, onOpenItem }: {
  head: ReactNode; text: string; cursor: number; path: string | null;
  /** The outline file: in it the rail is the file's contents. */
  outlineFile: string | null;
  /** What the last save of the outline file here did to the outline. */
  sync?: OutlineSync | null;
  floating?: boolean; width?: Resizable;
  onJump: (line: number) => void; onInsert: (lines: string[]) => void;
  /** Open the outline file at this item or section. */
  onOpenItem: (id: string) => void;
}) {
  const { t, lang } = useI18n();
  const { navigate, askAgent } = useApp();
  const { outline: o } = useToday();
  const isFile = !!path && path === outlineFile;
  const marks = useMemo(() => docMarks(text), [text]);
  const detected = sectionAt(o, marks, cursor);
  const [picked, setPicked] = useState<{ id: string; at: string | null } | null>(null);
  // a section picked by hand holds until the cursor moves into another section
  const secId = picked && picked.at === detected ? picked.id : detected ?? picked?.id ?? o?.sections[0]?.id ?? null;
  const sec = o?.sections.find(s => s.id === secId) ?? null;
  const states = useMemo(() => (sec && !isFile ? writeStates(sec, marks, cursor) : new Map<string, WriteState>()), [sec, marks, cursor, isFile]);
  const current = isFile && sec ? itemAt(sec, marks, cursor) : null;

  const look = (it: Item): Look => {
    if (isFile) {
      const known = marks.items.has(it.id);
      return { tone: STATE_TONE[it.state] || '', label: t(`ol.state.${it.state}`), dim: !known,
               hint: t(known ? 'ol.rail.toLine' : 'ol.rail.notInFile'), markable: false };
    }
    const st = states.get(it.id) ?? 'todo';
    const here = marks.describes.has(it.id);
    return { tone: TONE[st], label: t(`ol.rail.${st}`), dim: st === 'todo',
             hint: t(here ? 'ol.rail.jump' : outlineFile ? 'ol.rail.jumpFile' : 'ol.rail.toOutline'), markable: !here && !!path };
  };
  const pick = (it: Item) => {
    const line = isFile ? marks.items.get(it.id) : marks.describes.get(it.id);
    if (line) onJump(line);
    else if (outlineFile && !isFile) onOpenItem(it.id);
    else navigate('outline', `@item/${it.id}`);
  };
  const mark = (it: Item) => {
    const inRegion = marks.regions.some(r => r.sec === sec?.id && cursor >= r.line && cursor <= r.end);
    onInsert(markerLines(path, { sec: inRegion || !sec ? undefined : sec.id, describes: it.id }));
  };
  const pickSection = (id: string) => {
    setPicked({ id, at: detected });
    const line = isFile ? lineOf(marks, id) : null;
    if (line) onJump(line);
  };
  const sectionText = sec && o ? outlineText({ ...o, sections: [sec] }, lang) : '';
  const draft = () => sec && path && askAgent(t('ol.rail.draftPrompt', { sec: `§${sec.num} ${bi(sec.title, lang)}`, file: path, id: sec.id, outline: sectionText }), { file: path });
  const check = () => sec && path && askAgent(t('ol.rail.checkPrompt', { sec: `§${sec.num} ${bi(sec.title, lang)}`, file: path, outline: sectionText }), { file: path });
  const all = sec && !isFile ? [...states.entries()] : [];
  const error = isFile ? (sync ? sync.error : o?.file?.error) : null;
  const warnings = isFile ? (sync ? sync.warnings : o?.file?.warnings) ?? [] : [];

  return (
    <nav id="wr-docs" className={`wr-docs ol-rail${floating ? ' floating' : ''}`} aria-label={t('ol.rail.title')}>
      {width && <ResizeHandle pane={width} edge="right" label={t('ol.rail.title')} controls="wr-docs" />}
      <div className="wr-docs-head">{head}</div>
      {!o?.has_outline ? (
        <div className="ol-rail-body">
          <p className="ol-hint" style={{ margin: 0 }}>{t('ol.rail.none')}</p>
          <Button size="sm" onClick={() => navigate('outline')}>{t('ol.rail.toOutline')}</Button>
        </div>
      ) : (
        <div className="ol-rail-body">
          {outlineFile && !isFile && (
            <button type="button" className="ol-rail-file" title={t('ol.rail.openFileHint')} onClick={() => onOpenItem(sec?.id ?? '')}>
              <Icon name="file" size={14} /><span className="grow">{t('ol.rail.openFile')}</span><span className="mono">{outlineFile}</span>
            </button>
          )}
          <div className="col" style={{ gap: 4 }}>
            <select className="select ol-rail-pick" value={secId ?? ''} aria-label={t('ol.rail.section')}
              onChange={e => pickSection(e.target.value)}>
              {o.sections.map(s => <option key={s.id} value={s.id}>§{s.num} {bi(s.title, lang)}</option>)}
            </select>
            {sec?.role && <span className="ol-hint">{sec.role}</span>}
            <span className="ol-faint" style={{ fontSize: 'var(--fs-xs)' }}>{detected ? t('ol.rail.atCursor') : t('ol.rail.notFound')}</span>
          </div>
          {sec && (sec.items.length
            ? <RailSteps steps={sec.items} look={look} current={current} onPick={pick} onMark={isFile ? undefined : mark} />
            : <span className="ol-hint">{t('ol.focus.empty')}</span>)}
          {all.length > 0 && (
            <div className="ol-flags">
              {all.map(([id, st]) => {
                const it = findItem(sec!, id);
                return it ? <span key={id} className={`chip ol-chip ${TONE[st]}`}>{it.num} {t(`ol.rail.${st}`)}</span> : null;
              })}
            </div>
          )}
          {error && <div className="notice accent ol-rail-sync" role="alert">{t('ol.rail.notApplied', { error })}</div>}
          {isFile && sync?.proposal && <div className="notice ol-rail-sync">{t('ol.rail.proposal')}</div>}
          {warnings.length > 0 && (
            <div className="ol-rail-sync ol-hint">{t('ol.rail.warnings')}<ul>{warnings.map(w => <li key={w}>{w}</li>)}</ul></div>
          )}
          <div className="col" style={{ gap: 6, paddingTop: 8, borderTop: 'var(--line) solid var(--rule)' }}>
            <span className="ol-hint">{t(isFile ? 'ol.rail.howFile' : 'ol.rail.how')}</span>
            <div className="row wrap" style={{ gap: 6 }}>
              {!isFile && <>
                <Button size="sm" icon="robot" disabled={!sec || !path} onClick={draft}>{t('ol.rail.draft')}</Button>
                <Button size="sm" icon="robot" disabled={!sec || !path} onClick={check}>{t('ol.rail.check')}</Button>
              </>}
              <Button size="sm" variant="ghost" onClick={() => navigate('outline', sec ? `@item/${current ?? sec.items[0]?.items[0]?.id ?? ''}` : null)}>{t('ol.rail.toOutline')}</Button>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}

function findItem(sec: Section, id: string): Item | undefined {
  const find = (steps: Step[]): Item | undefined => {
    for (const st of steps) for (const it of st.items) {
      if (it.id === id) return it;
      const k = find(it.children) ?? (it.fork?.directions ?? []).map(d => (d.id === id ? d : find(d.children))).find(Boolean);
      if (k) return k;
    }
    return undefined;
  };
  return find(sec.items);
}

function RailSteps({ steps, look, current, onPick, onMark }: {
  steps: Step[]; look: (it: Item) => Look; current: string | null; onPick: (it: Item) => void; onMark?: (it: Item) => void;
}) {
  const { t } = useI18n();
  const live = steps.map(s => ({ ...s, items: s.items.filter(i => i.state !== 'abandoned') })).filter(s => s.items.length);
  const longest = Math.max(3, ...live.flatMap(s => s.items.map(i => i.num.length)));
  return (
    <ol className="ol-nc" style={{ ['--pill' as string]: `${Math.max(36, 12 + longest * 7)}px` }}>
      {live.map(step => (
        <li key={step.items[0].id}>
          {step.items.map(it => {
            const l = look(it);
            const dirs = (it.fork?.directions ?? []).filter(d => d.state !== 'abandoned');
            return (
              <div key={it.id} className={`ol-nr ${l.tone}${l.dim ? ' off' : ''}${current === it.id ? ' cur' : ''}`}
                aria-current={current === it.id ? 'location' : undefined}>
                <button type="button" className="ol-nb" onClick={() => onPick(it)} title={l.hint}>{it.num}</button>
                <div className={`ol-nt${step.items.length > 1 ? ' par' : ''}`}>
                  <button type="button" className="ol-rail-text" onClick={() => onPick(it)} title={l.hint}>{it.text}</button>
                  <div className="row ol-rail-chips">
                    <span className={`chip ol-chip ${l.tone}`}>{l.label}</span>
                    {onMark && l.markable && (
                      <button type="button" className="ol-rail-mark" title={t('ol.rail.mark')} aria-label={t('ol.rail.mark')}
                        onClick={() => onMark(it)}><Icon name="pin" size={12} /></button>
                    )}
                  </div>
                  {it.children.length > 0 && (
                    <div className="ol-kids"><RailSteps steps={it.children} look={look} current={current} onPick={onPick} onMark={onMark} /></div>
                  )}
                  {dirs.map(d => (
                    <div key={d.id} className={`ol-kids${current === d.id ? ' cur' : ''}`}>
                      <button type="button" className="ol-rail-text ol-rail-dir" onClick={() => onPick(d)} title={look(d).hint}>
                        {t('ol.dir', { n: d.direction ?? '' })} · {d.text}
                      </button>
                      {d.children.length > 0 && <RailSteps steps={d.children} look={look} current={current} onPick={onPick} onMark={onMark} />}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </li>
      ))}
    </ol>
  );
}
