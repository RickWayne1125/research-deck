// The figure gallery: preview cards (title, kind, linked DAG node, freshness) and the "New figure" menu + dialog.
import { useEffect, useMemo, useState } from 'react';
import { Icon } from '../../components/icons';
import { Badge, Button, Dialog, Empty, IconButton, Menu, Segmented, Spinner } from '../../components/ui';
import { useRelTime, useT } from '../../i18n';
import { useApp } from '../../state/app';
import type { FigureKind } from '../../types';
import { errMessage, KIND_LABEL, KIND_TONE, STATUS_TONE, vz, type Discovered, type FigureView } from './api';

type Filter = 'all' | 'drawio' | 'matplotlib' | 'native';
const NATIVE: FigureKind[] = ['omnigraffle', 'datagraph'];
const EXT: Record<FigureKind, string> = { drawio: '.drawio', matplotlib: '.py', omnigraffle: '.graffle', datagraph: '.dgraph / .dgraphs' };

export function StatusBadge({ status }: { status?: string }) {
  const t = useT();
  const s = status ?? 'unrendered';
  return <Badge tone={STATUS_TONE[s]} title={t(`vz.status.${s}.hint`)}>{t(`vz.status.${s}`)}</Badge>;
}

export function KindBadge({ kind }: { kind: FigureKind }) {
  return <Badge tone={KIND_TONE[kind]}>{KIND_LABEL[kind]}</Badge>;
}

export function NodeChip({ id }: { id: string }) {
  const { navigate } = useApp();
  const t = useT();
  return (
    <button type="button" className="chip vz-node" title={t('vz.node.hint', { id })}
      onClick={(e) => { e.stopPropagation(); navigate('dag', id); }}>
      <Icon name="dag" size={12} /> <span className="mono">{t('vz.node', { id })}</span>
    </button>
  );
}

function FigureCard({ figure, onOpen, onRemove }: { figure: FigureView; onOpen: () => void; onRemove: () => void }) {
  const t = useT();
  const rel = useRelTime();
  return (
    <article className="card vz-card" onClick={onOpen} onKeyDown={(e) => { if (e.key === 'Enter') onOpen(); }} tabIndex={0}
      aria-label={figure.title}>
      <div className="vz-thumb">
        {figure.preview ? <img src={figure.preview} alt="" loading="lazy" /> : (
          <div className="col faint" style={{ alignItems: 'center', gap: 4 }}><Icon name="image" size={20} /><span>{t('vz.noPreview')}</span></div>
        )}
      </div>
      <div className="vz-card-meta">
        <div className="row">
          <span className="h3 ellipsis grow" title={figure.title}>{figure.title}</span>
          <Menu button={(open, toggle) => (
            <IconButton icon="dots" label={t('common.more')} aria-expanded={open} onClick={(e) => { e.stopPropagation(); toggle(); }} />
          )}>
            {(close) => (
              <div onClick={(e) => e.stopPropagation()}>
                <button type="button" className="menu-item" onClick={() => { close(); onRemove(); }}><Icon name="close" /> {t('vz.remove')}</button>
              </div>
            )}
          </Menu>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          <KindBadge kind={figure.kind} />
          <StatusBadge status={figure.status} />
          {!figure.exists && <Badge tone="accent">{t('vz.missingFile')}</Badge>}
          {figure.node_id && <NodeChip id={figure.node_id} />}
        </div>
        <div className="row faint" style={{ fontSize: 'var(--fs-xs)' }}>
          <span className="mono ellipsis grow" title={figure.source}>{figure.source}</span>
          <span className="vz-nowrap">{t('vz.updated', { t: rel(figure.updated_at) })}</span>
        </div>
      </div>
    </article>
  );
}

export function NewFigureMenu({ onPick }: { onPick: (kind: FigureKind | 'import') => void }) {
  const t = useT();
  const items: { kind: FigureKind | 'import'; icon: string; hint: string }[] = [
    { kind: 'drawio', icon: 'dag', hint: 'vz.new.hint.drawio' },
    { kind: 'matplotlib', icon: 'visualization', hint: 'vz.new.hint.matplotlib' },
    { kind: 'omnigraffle', icon: 'layers', hint: 'vz.new.hint.native' },
    { kind: 'datagraph', icon: 'image', hint: 'vz.new.hint.native' },
    { kind: 'import', icon: 'folder', hint: 'vz.new.hint.import' },
  ];
  return (
    <Menu button={(open, toggle) => <Button variant="accent" icon="plus" aria-expanded={open} onClick={toggle}>{t('vz.new')}</Button>}>
      {(close) => (
        <div style={{ width: 320 }}>
          {items.map(it => (
            <button key={it.kind} type="button" className="menu-item vz-menu-item" onClick={() => { close(); onPick(it.kind); }}>
              <Icon name={it.icon} />
              <span className="col" style={{ gap: 1, minWidth: 0 }}>
                <span>{t(`vz.new.${it.kind}`)}</span>
                <span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t(it.hint)}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </Menu>
  );
}

/** Create from a template (draw.io, matplotlib) or register an existing document (OmniGraffle, DataGraph, any import). */
export function NewFigureDialog({ projectId, kind, onClose, onCreated }: {
  projectId: string; kind: FigureKind | 'import'; onClose: () => void; onCreated: (f: FigureView) => void;
}) {
  const t = useT();
  const needsFile = kind === 'import' || NATIVE.includes(kind);
  const [title, setTitle] = useState('');
  const [node, setNode] = useState('');
  const [caption, setCaption] = useState('');
  const [candidates, setCandidates] = useState<Discovered[] | null>(needsFile ? null : []);
  const [file, setFile] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!needsFile) return;
    vz.discover(projectId).then(all => {
      const list = kind === 'import' ? all : all.filter(d => d.kind === kind);
      setCandidates(list);
      if (list[0]) setFile(list[0].path);
    }).catch(e => { setCandidates([]); setError(errMessage(e)); });
  }, [projectId, kind, needsFile]);

  const chosen = candidates?.find(c => c.path === file);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const realKind = kind === 'import' ? chosen?.kind : kind;
      if (!realKind) return;
      const f = await vz.create(projectId, {
        kind: realKind, title: title.trim(), node_id: node.trim() || undefined, caption: caption.trim() || undefined,
        source: needsFile ? file : undefined,
      });
      onCreated(f);
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const canSubmit = !busy && (needsFile ? !!file : !!title.trim());
  const heading = kind === 'import' ? t('vz.dialog.import') : t('vz.dialog.new', { kind: KIND_LABEL[kind] });

  return (
    <Dialog title={heading} onClose={onClose} width={520} footer={(
      <><Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="primary" onClick={submit} disabled={!canSubmit}>{busy ? <Spinner /> : null}{needsFile ? t('vz.register') : t('vz.create')}</Button></>
    )}>
      <form className="col" style={{ gap: 12 }} onSubmit={(e) => { e.preventDefault(); if (canSubmit) submit(); }}>
        {needsFile && (
          <label className="field"><span className="label">{t('vz.field.file')}</span>
            {candidates === null ? <Spinner /> : candidates.length ? (
              <select className="select mono" value={file} onChange={e => setFile(e.target.value)}>
                {candidates.map(c => <option key={c.path} value={c.path}>{c.path} — {KIND_LABEL[c.kind]}</option>)}
              </select>
            ) : (
              <div className="notice">{kind === 'import' ? t('vz.field.noFiles') : t('vz.field.noCandidates', { ext: EXT[kind], app: KIND_LABEL[kind] })}</div>
            )}
          </label>
        )}
        <label className="field"><span className="label">{t('vz.field.title')}</span>
          <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder={t('vz.field.titlePh')} autoFocus={!needsFile} /></label>
        <label className="field"><span className="label">{t('vz.field.node')}</span>
          <input className="input mono" value={node} onChange={e => setNode(e.target.value)} placeholder={t('vz.field.nodePh')} /></label>
        <label className="field"><span className="label">{t('vz.field.caption')}</span>
          <textarea className="textarea" rows={2} value={caption} onChange={e => setCaption(e.target.value)} /></label>
        {!needsFile && <p className="vz-hint">{t(`vz.new.hint.${kind}`)}</p>}
        {error && <div className="notice accent" role="alert"><Icon name="warn" /> {error}</div>}
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}

export function Gallery({ projectId, figures, loading, onOpen, onNew, onRemoved }: {
  projectId: string; figures: FigureView[]; loading: boolean;
  onOpen: (id: string) => void; onNew: (kind: FigureKind | 'import') => void; onRemoved: () => void;
}) {
  const t = useT();
  const [filter, setFilter] = useState<Filter>('all');
  const [removing, setRemoving] = useState<FigureView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown = useMemo(() => figures.filter(f => filter === 'all' || (filter === 'native' ? NATIVE.includes(f.kind) : f.kind === filter)), [figures, filter]);

  if (loading && !figures.length) return <div className="empty"><Spinner /></div>;
  if (!figures.length) {
    return (
      <Empty icon="visualization" title={t('vz.empty.title')} action={<NewFigureMenu onPick={onNew} />}>
        {t('vz.empty.body')}
      </Empty>
    );
  }
  const remove = async () => {
    if (!removing) return;
    try { await vz.remove(projectId, removing.id); setRemoving(null); onRemoved(); }
    catch (e) { setError(errMessage(e)); }
  };
  const count = (f: Filter) => figures.filter(x => f === 'all' || (f === 'native' ? NATIVE.includes(x.kind) : x.kind === f)).length;
  return (
    <div className="vz-gallery-wrap">
      <div className="vz-gallery-bar">
        <Segmented<Filter> value={filter} onChange={setFilter} options={[
          { value: 'all', label: `${t('vz.filter.all')} ${count('all')}` },
          { value: 'drawio', label: `draw.io ${count('drawio')}` },
          { value: 'matplotlib', label: `matplotlib ${count('matplotlib')}` },
          { value: 'native', label: `${t('vz.filter.native')} ${count('native')}` },
        ]} />
      </div>
      <div className="vz-gallery">
        {shown.map(f => <FigureCard key={f.id} figure={f} onOpen={() => onOpen(f.id)} onRemove={() => setRemoving(f)} />)}
      </div>
      {removing && (
        <Dialog title={t('vz.removeTitle')} onClose={() => setRemoving(null)} width={440}
          footer={<><Button onClick={() => setRemoving(null)}>{t('common.cancel')}</Button><Button variant="danger" onClick={remove}>{t('vz.remove')}</Button></>}>
          <p style={{ margin: 0 }}>{t('vz.removeBody', { title: removing.title })}</p>
          {error && <div className="notice accent" style={{ marginTop: 10 }}>{error}</div>}
        </Dialog>
      )}
    </div>
  );
}
