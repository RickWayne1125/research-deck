// Focus: any item as the root, with the path to it and the chain under it. However deep the outline goes, what is
// on screen is one chain.
import { Button } from '../../components/ui';
import { useApp } from '../../state/app';
import { useT } from '../../i18n';
import { useOl } from './ctx';
import { Chain, ForkBlock } from './Chain';
import { bi, pathTo } from './model';
import { StateChip, usePhaseLabel } from './parts';
import { useOutlinerKeys } from './Story';

export function Focus({ id }: { id: string }) {
  useOutlinerKeys();
  const t = useT();
  const { navigate, askAgent } = useApp();
  const { o, lang, items, setEditing, select, openDialog, sel } = useOl();
  const phaseLabel = usePhaseLabel();
  const it = items.get(id);
  const path = pathTo(o, id);
  if (!it || !path) {
    return <div className="card" style={{ padding: 16 }}><span className="ol-hint">{t('ol.focus.empty')}</span></div>;
  }
  const up = path.items.length > 1 ? path.items[path.items.length - 2] : null;
  return (
    <div className="col" style={{ gap: 12 }}>
      <nav className="ol-crumb" aria-label={t('ol.focus.crumb')}>
        <button type="button" className="ol-link" onClick={() => navigate('outline')}>{t('ol.focus.crumb')}</button>›
        <span>{phaseLabel(path.section.phase)}</span>›
        <button type="button" className="ol-link" onClick={() => { navigate('outline'); select(path.section.id, { reveal: true }); }}>§{path.section.num} {bi(path.section.title, lang)}</button>
        {path.items.slice(0, -1).map(x => <span key={x.id}>› <button type="button" className="ol-link" onClick={() => navigate('outline', `@focus/${x.id}`)}>{x.num}{x.direction ? ` · ${t('ol.dir', { n: x.direction })}` : ''}</button></span>)}
        › <b>{it.num}{it.direction ? ` · ${t('ol.dir', { n: it.direction })}` : ''}</b>
      </nav>
      <div className={`ol-root${sel === it.id ? ' sel' : ''}`} onClick={() => select(it.id)}>
        <div className="row wrap" style={{ justifyContent: 'space-between' }}>
          <span className="ol-hint">{t('ol.focus.root', { num: it.num })}</span><StateChip it={it} />
        </div>
        <span style={{ color: 'var(--ink-strong)' }}>{it.text}</span>
        <span className="ol-hint">{t('ol.focus.where', { sec: path.section.num, num: it.num })}</span>
      </div>
      {it.fork && <ForkBlock it={it} />}
      <div>
        <span className="ol-hint" style={{ display: 'block', marginBottom: 8 }}>{t('ol.focus.chain')}</span>
        {it.children.length ? <Chain steps={it.children} parent={it.id} depth={0} /> : <span className="ol-hint">{t('ol.focus.empty')}</span>}
        <FocusDraft id={it.id} />
      </div>
      <div className="row wrap" style={{ gap: 6 }}>
        <Button size="sm" onClick={() => navigate('outline', up ? `@focus/${up.id}` : null)}>{t('ol.focus.up')}</Button>
        <Button size="sm" onClick={() => setEditing({ kind: 'new', parent: it.id, at: {} })}>{t('ol.focus.add')}</Button>
        <Button size="sm" onClick={() => openDialog({ kind: 'task', item: it.id })}>{t('ol.ins.assign')}</Button>
        <Button size="sm" icon="robot" onClick={() => askAgent(t('ol.focus.askPrompt', { num: it.num, text: it.text }), {})}>{t('ol.focus.ask')}</Button>
      </div>
    </div>
  );
}

/** With no sub-items yet, the chain is empty: the new one is written here. */
function FocusDraft({ id }: { id: string }) {
  const { items, editing } = useOl();
  const it = items.get(id);
  if (!it || it.children.length || !(editing?.kind === 'new' && editing.parent === id)) return null;
  return <Chain steps={[]} parent={id} depth={0} />;
}
