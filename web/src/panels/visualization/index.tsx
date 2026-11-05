// The figures half of the paper view: a gallery of the project's figures and an editor per kind (draw.io embed,
// matplotlib live preview, OmniGraffle/DataGraph through the native apps). An AI edit is a proposal: it shows as a
// diff and nothing is written before Accept. Route: #/<project>/writing/@figures[/<figure id>].
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { Icon } from '../../components/icons';
import { Button, Dialog, Empty, IconButton, Menu, PanelHead, Spinner, useLoad } from '../../components/ui';
import { useT } from '../../i18n';
import { FIGURES, useApp } from '../../state/app';
import { PaperTabs } from '../writing/PaperTabs';
import type { FigureKind } from '../../types';
import { DrawioEditor } from './DrawioEditor';
import { Gallery, KindBadge, NewFigureDialog, NewFigureMenu, NodeChip, StatusBadge } from './Gallery';
import { MplEditor } from './MplEditor';
import { NativeFigure } from './NativeFigure';
import { errMessage, KIND_LABEL, vz, type FigureView, type StyleFull } from './api';
import type { EditorHandle } from './editor';
import './i18n';
import './visualization.css';
import { ServesInline } from '../outline/Serves';

export function FiguresView() {
  const { projectId, sub: route, navigate, onEvent, askAgent } = useApp();
  const t = useT();
  const pid = projectId!;
  const sub = route && route.startsWith(`${FIGURES}/`) ? route.slice(FIGURES.length + 1) || null : null;
  const figs = useLoad(() => vz.list(pid), [pid]);
  const [tokens, setTokens] = useState<StyleFull | null>(null);
  const [newKind, setNewKind] = useState<FigureKind | 'import' | null>(null);
  const [dirty, setDirty] = useState(false);
  const [leaving, setLeaving] = useState<null | { go: () => void }>(null);
  const editor = useRef<EditorHandle>(null);
  const reloadFigs = figs.reload;

  const loadStyle = useCallback(() => { vz.style(pid).then(setTokens).catch(() => {}); }, [pid]);
  useEffect(() => { loadStyle(); }, [loadStyle]);

  // Live updates: figure registry/preview changes, file writes (statuses depend on them), style changes.
  const reloadTimer = useRef<number | null>(null);
  useEffect(() => {
    const soon = () => {
      if (reloadTimer.current) window.clearTimeout(reloadTimer.current);
      reloadTimer.current = window.setTimeout(() => reloadFigs(), 250);
    };
    const offFigures = onEvent('figures', (e) => { if (e.payload?.action === 'style') loadStyle(); soon(); });
    const offFiles = onEvent('file', soon);
    return () => { offFigures(); offFiles(); if (reloadTimer.current) window.clearTimeout(reloadTimer.current); };
    // reloadFigs changes identity every render (useLoad); the subscription only needs the latest via closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onEvent, loadStyle, pid]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const list = figs.data ?? [];
  const figure = sub ? list.find(f => f.id === sub) ?? null : null;
  const guarded = (go: () => void) => { if (dirty) setLeaving({ go }); else go(); };
  const toGallery = () => guarded(() => navigate('writing', FIGURES));
  const canvas = tokens?.roles?.canvas?.fill;
  const bodyStyle = (canvas && canvas !== 'none' ? { '--vz-canvas': canvas } : {}) as CSSProperties;

  const ask = () => {
    if (figure) askAgent(t('vz.askPrompt', { title: figure.title, path: figure.source }), { file: figure.source, node_id: figure.node_id ?? undefined });
    else askAgent(t('vz.askGalleryPrompt'), { file: '.research/figures.json' });
  };

  let content: React.ReactNode;
  if (!sub) {
    content = <Gallery projectId={pid} figures={list} loading={figs.loading} onOpen={(id) => navigate('writing', `${FIGURES}/${id}`)}
      onNew={setNewKind} onRemoved={reloadFigs} />;
  } else if (!figure) {
    content = figs.loading && !figs.data ? <div className="empty"><Spinner /></div> : (
      <Empty icon="warn" title={t('vz.notFound', { id: sub })} action={<Button icon="chevronLeft" onClick={toGallery}>{t('vz.back')}</Button>}>
        {figs.error ?? t('vz.notFoundBody')}
      </Empty>
    );
  } else if (figure.kind === 'drawio') {
    content = <DrawioEditor key={figure.id} ref={editor} projectId={pid} figure={figure} tokens={tokens} onDirty={setDirty} />;
  } else if (figure.kind === 'matplotlib') {
    content = <MplEditor key={figure.id} ref={editor} projectId={pid} figure={figure} onDirty={setDirty} />;
  } else {
    content = <NativeFigure key={figure.id} projectId={pid} figure={figure} onChanged={reloadFigs} />;
  }

  return (
    <div className="panel vz">
      <PanelHead
        title={figure || sub ? (
          <span className="vz-crumbs">
            <button type="button" className="vz-crumb" onClick={toGallery}>{t('wr.tab.figures')}</button>
            <span className="faint">/</span>
            <span className="ellipsis">{figure?.title ?? sub}</span>
          </span>
        ) : t('wr.tab.figures')}
        subtitle={figure ? t('vz.subtitleEditor', { kind: KIND_LABEL[figure.kind], path: figure.source })
          : !sub ? t('vz.subtitle', { n: list.length }) : undefined}>
        <PaperTabs />
        {figure && (
          <>
            <KindBadge kind={figure.kind} />
            <StatusBadge status={figure.status} />
            {figure.node_id && <NodeChip id={figure.node_id} />}
            <ServesInline node={figure.node_id} figure={figure.id} />
            <FigureMeta projectId={pid} figure={figure} onSaved={reloadFigs} />
          </>
        )}
        {!sub && <NewFigureMenu onPick={setNewKind} />}
        <IconButton icon="robot" label={t('vz.askAgent')} onClick={ask} />
      </PanelHead>

      <div className="panel-body vz-body" style={bodyStyle}>
        <div className="vz-main">{content}</div>
      </div>

      {newKind && (
        <NewFigureDialog projectId={pid} kind={newKind} onClose={() => setNewKind(null)}
          onCreated={(f) => { setNewKind(null); reloadFigs(); navigate('writing', `${FIGURES}/${f.id}`); }} />
      )}
      {leaving && (
        <Dialog title={t('vz.leaveTitle')} onClose={() => setLeaving(null)} width={460} footer={(
          <>
            <Button onClick={() => setLeaving(null)}>{t('common.cancel')}</Button>
            <Button variant="danger" onClick={() => { const go = leaving.go; setLeaving(null); setDirty(false); go(); }}>{t('vz.leaveDiscard')}</Button>
            <Button variant="primary" onClick={async () => {
              const ok = await editor.current?.save();
              if (ok === false) return;
              const go = leaving.go; setLeaving(null); setDirty(false); go();
            }}>{t('vz.leaveSave')}</Button>
          </>
        )}>
          <p style={{ margin: 0 }}>{t('vz.leaveBody', { title: figure?.title ?? '' })}</p>
        </Dialog>
      )}
    </div>
  );
}

/** Title, linked DAG node and caption of the open figure. */
function FigureMeta({ projectId, figure, onSaved }: { projectId: string; figure: FigureView; onSaved: () => void }) {
  const t = useT();
  const [title, setTitle] = useState(figure.title);
  const [node, setNode] = useState(figure.node_id ?? '');
  const [caption, setCaption] = useState(figure.caption ?? '');
  const [error, setError] = useState<string | null>(null);
  const reset = () => { setTitle(figure.title); setNode(figure.node_id ?? ''); setCaption(figure.caption ?? ''); setError(null); };
  return (
    <Menu button={(open, toggle) => (
      <IconButton icon="settings" label={t('vz.meta')} aria-expanded={open} onClick={() => { if (!open) reset(); toggle(); }} />
    )}>
      {(close) => (
        <form className="col vz-meta" onSubmit={async (e) => {
          e.preventDefault();
          try {
            await vz.patch(projectId, figure.id, { title: title.trim(), node_id: node.trim() || null, caption });
            onSaved();
            close();
          } catch (err) { setError(errMessage(err)); }
        }}>
          <div className="h3">{t('vz.meta')}</div>
          <label className="field"><span className="label">{t('vz.field.title')}</span>
            <input className="input" value={title} onChange={e => setTitle(e.target.value)} /></label>
          <label className="field"><span className="label">{t('vz.field.node')}</span>
            <input className="input mono" value={node} onChange={e => setNode(e.target.value)} placeholder={t('vz.field.nodePh')} /></label>
          <label className="field"><span className="label">{t('vz.field.caption')}</span>
            <textarea className="textarea" rows={3} value={caption} onChange={e => setCaption(e.target.value)} /></label>
          {error && <div className="notice accent"><Icon name="warn" /> {error}</div>}
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <Button size="sm" onClick={close}>{t('common.cancel')}</Button>
            <Button size="sm" variant="primary" type="submit" disabled={!title.trim()}>{t('vz.meta.save')}</Button>
          </div>
        </form>
      )}
    </Menu>
  );
}
