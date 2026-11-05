// The outline beside the paper's text: the section the cursor is in, its items with how far the text has got with
// each (being written, written here, written in another file, not yet), and the section's role. Clicking an item jumps
// to its paragraph, or starts one: a `% rd:describes <item>` marker at the cursor (with `% rd:sec <section>` when the
// cursor is not in that section's region). The agent can draft the section from its items or check the text against
// them. The paper sync turns the markers into the map's describes edges, which is what "written" means on the outline.
import { useMemo, useState, type ReactNode } from 'react';
import { Button } from '../../components/ui';
import { ResizeHandle, type Resizable } from '../../components/resize';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useI18n } from '../../i18n';
import type { Item, Section, Step } from './api';
import { bi, docMarks, markerLines, outlineText, sectionAt, writeStates, type WriteState } from './model';
import './outline.css';
import './i18n';

const TONE: Record<WriteState, string> = { here: 'bad', written: 'ok', elsewhere: 'ok', todo: 'off' };

export function OutlineRail({ head, text, cursor, path, floating, width, onJump, onInsert }: {
  head: ReactNode; text: string; cursor: number; path: string | null; floating?: boolean; width?: Resizable;
  onJump: (line: number) => void; onInsert: (lines: string[]) => void;
}) {
  const { t, lang } = useI18n();
  const { navigate, askAgent } = useApp();
  const { outline: o } = useToday();
  const marks = useMemo(() => docMarks(text), [text]);
  const detected = sectionAt(o, marks, cursor);
  const [picked, setPicked] = useState<{ id: string; at: string | null } | null>(null);
  // a section picked by hand holds until the cursor moves into another section
  const secId = picked && picked.at === detected ? picked.id : detected ?? picked?.id ?? o?.sections[0]?.id ?? null;
  const sec = o?.sections.find(s => s.id === secId) ?? null;
  const states = useMemo(() => (sec ? writeStates(sec, marks, cursor) : new Map<string, WriteState>()), [sec, marks, cursor]);

  const start = (it: Item) => {
    const at = marks.describes.get(it.id);
    if (at) { onJump(at); return; }
    const inRegion = marks.regions.some(r => r.sec === sec?.id && cursor >= r.line && cursor <= r.end);
    onInsert(markerLines(path, { sec: inRegion || !sec ? undefined : sec.id, describes: it.id }));
  };
  const sectionText = sec && o ? outlineText({ ...o, sections: [sec] }, lang) : '';
  const draft = () => sec && path && askAgent(t('ol.rail.draftPrompt', { sec: `§${sec.num} ${bi(sec.title, lang)}`, file: path, id: sec.id, outline: sectionText }), { file: path });
  const check = () => sec && path && askAgent(t('ol.rail.checkPrompt', { sec: `§${sec.num} ${bi(sec.title, lang)}`, file: path, outline: sectionText }), { file: path });
  const all = sec ? [...states.entries()] : [];

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
          <div className="col" style={{ gap: 4 }}>
            <select className="select ol-rail-pick" value={secId ?? ''} aria-label={t('ol.rail.section')}
              onChange={e => setPicked({ id: e.target.value, at: detected })}>
              {o.sections.map(s => <option key={s.id} value={s.id}>§{s.num} {bi(s.title, lang)}</option>)}
            </select>
            {sec?.role && <span className="ol-hint">{sec.role}</span>}
            <span className="ol-faint" style={{ fontSize: 'var(--fs-xs)' }}>{detected ? t('ol.rail.atCursor') : t('ol.rail.notFound')}</span>
          </div>
          {sec && (sec.items.length ? <RailSteps steps={sec.items} states={states} onPick={start} /> : <span className="ol-hint">{t('ol.focus.empty')}</span>)}
          {all.length > 0 && (
            <div className="ol-flags">
              {all.map(([id, st]) => {
                const it = findItem(sec!, id);
                return it ? <span key={id} className={`chip ol-chip ${TONE[st]}`}>{it.num} {t(`ol.rail.${st}`)}</span> : null;
              })}
            </div>
          )}
          <div className="col" style={{ gap: 6, paddingTop: 8, borderTop: 'var(--line) solid var(--rule)' }}>
            <span className="ol-hint">{t('ol.rail.how')}</span>
            <div className="row wrap" style={{ gap: 6 }}>
              <Button size="sm" icon="robot" disabled={!sec || !path} onClick={draft}>{t('ol.rail.draft')}</Button>
              <Button size="sm" icon="robot" disabled={!sec || !path} onClick={check}>{t('ol.rail.check')}</Button>
              <Button size="sm" variant="ghost" onClick={() => navigate('outline', sec ? `@item/${sec.items[0]?.items[0]?.id ?? ''}` : null)}>{t('ol.rail.toOutline')}</Button>
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

function RailSteps({ steps, states, onPick }: { steps: Step[]; states: Map<string, WriteState>; onPick: (it: Item) => void }) {
  const { t } = useI18n();
  const live = steps.map(s => ({ ...s, items: s.items.filter(i => i.state !== 'abandoned') })).filter(s => s.items.length);
  const longest = Math.max(3, ...live.flatMap(s => s.items.map(i => i.num.length)));
  return (
    <ol className="ol-nc" style={{ ['--pill' as string]: `${Math.max(36, 12 + longest * 7)}px` }}>
      {live.map(step => (
        <li key={step.items[0].id}>
          {step.items.map(it => {
            const st = states.get(it.id) ?? 'todo';
            const dirs = (it.fork?.directions ?? []).filter(d => d.state !== 'abandoned');
            return (
              <div key={it.id} className={`ol-nr ${TONE[st]}${st === 'todo' ? ' off' : ''}`}>
                <button type="button" className="ol-nb" onClick={() => onPick(it)} title={t(st === 'todo' ? 'ol.rail.start' : 'ol.rail.jump')}>{it.num}</button>
                <div className={`ol-nt${step.items.length > 1 ? ' par' : ''}`}>
                  <button type="button" className="ol-rail-text" onClick={() => onPick(it)}>{it.text}</button>
                  <span className={`chip ol-chip ${TONE[st]}`} style={{ alignSelf: 'flex-start' }}>{t(`ol.rail.${st}`)}</span>
                  {it.children.length > 0 && <div className="ol-kids"><RailSteps steps={it.children} states={states} onPick={onPick} /></div>}
                  {dirs.map(d => (
                    <div key={d.id} className="ol-kids"><span className="ol-hint">{t('ol.dir', { n: d.direction ?? '' })} · {d.text}</span>
                      {d.children.length > 0 && <RailSteps steps={d.children} states={states} onPick={onPick} />}</div>
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
