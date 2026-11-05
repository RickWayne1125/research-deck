// The paper view's dialogs: versions (snapshots + git, diff, restore) and the merge view for a file that changed on
// disk while it was being edited.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { MergeView } from '@codemirror/merge';
import { useT, useRelTime } from '../../i18n';
import { Button, Dialog, Empty, ErrorNote, Spinner, useLoad } from '../../components/ui';
import { writingApi, type WrVersion } from './api';
import { languageFor, proseLook } from './cm';

const mergeTheme = EditorView.theme({
  '&': { fontSize: '13px', backgroundColor: 'var(--surface)' },
  '.cm-scroller': { fontFamily: 'var(--serif)', lineHeight: '1.6' },
  '.cm-content': { padding: '8px 0' },
  '.cm-line': { padding: '0 10px' },
});

export interface MergeHandle { right: () => string }

/** Side by side: a (left) read-only, b (right) read-only unless `editable` (then a's chunks can be taken into b). */
export const MergePane = forwardRef<MergeHandle, { a: string; b: string; kind: 'tex' | 'md'; editable?: boolean; labels: [string, string] }>(
  function MergePane({ a, b, kind, editable, labels }, ref) {
    const host = useRef<HTMLDivElement>(null);
    const view = useRef<MergeView | null>(null);
    useEffect(() => {
      const common = [EditorView.lineWrapping, languageFor(kind), proseLook, mergeTheme];
      const ro = [EditorState.readOnly.of(true), EditorView.editable.of(false)];
      const mv = new MergeView({
        parent: host.current!,
        a: { doc: a, extensions: [...common, ...ro] },
        b: { doc: b, extensions: [...common, ...(editable ? [] : ro)] },
        highlightChanges: true, gutter: true,
        collapseUnchanged: { margin: 3, minSize: 8 },
        ...(editable ? { revertControls: 'a-to-b' as const } : {}),
      });
      view.current = mv;
      return () => { mv.destroy(); view.current = null; };
    }, [a, b, kind, editable]);
    useImperativeHandle(ref, () => ({ right: () => view.current?.b.state.doc.toString() ?? b }), [b]);
    return (
      <div className="wr-merge">
        <div className="wr-merge-labels"><span className="label">{labels[0]}</span><span className="label">{labels[1]}</span></div>
        <div ref={host} className="wr-merge-host" />
      </div>
    );
  },
);

// ------------------------------------------------------------------ versions

export function VersionsDialog({ pid, path, kind, current, onRestore, onBeforeSnapshot, onClose }: {
  pid: string; path: string; kind: 'tex' | 'md'; current: () => string;
  onRestore: (content: string, label: string) => void; onBeforeSnapshot: () => Promise<void>; onClose: () => void;
}) {
  const t = useT();
  const rel = useRelTime();
  const { data, error, loading, reload } = useLoad(() => writingApi.versions(pid, path), [pid, path]);
  const [picked, setPicked] = useState<WrVersion | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [now] = useState(current);       // the editor text when the dialog opened

  useEffect(() => {
    if (!picked) return;
    let alive = true;
    setContent(null); setLoadErr(null);
    writingApi.version(pid, path, picked.id).then(r => { if (alive) setContent(r.content); })
      .catch(e => { if (alive) setLoadErr(String((e as Error).message)); });
    return () => { alive = false; };
  }, [pid, path, picked]);

  const snapshot = async () => {
    setBusy(true);
    try { await onBeforeSnapshot(); await writingApi.snapshot(pid, path, label.trim() || undefined); setLabel(''); reload(); }
    catch (e) { setLoadErr(String((e as Error).message)); } finally { setBusy(false); }
  };
  const snaps = (data ?? []).filter(v => v.source === 'snapshot');
  const commits = (data ?? []).filter(v => v.source === 'git');
  const row = (v: WrVersion) => (
    <button key={v.id} type="button" className={`wr-version${picked?.id === v.id ? ' active' : ''}`} onClick={() => setPicked(v)}>
      <span className="ellipsis">{v.label || (v.source === 'git' ? v.sha : rel(v.created_at))}</span>
      <span className="faint wr-small row" style={{ gap: 6 }}>
        <span>{rel(v.created_at)}</span>
        {v.source === 'git' ? <span className="mono">{v.sha}</span> : v.words != null ? <span>{t('wr.versions.words', { n: v.words })}</span> : null}
        {v.auto && <span className="badge">{t('wr.versions.auto')}</span>}
      </span>
    </button>
  );
  return (
    <Dialog title={t('wr.versions')} onClose={onClose} width={1180}
      footer={<>
        <input className="input grow" style={{ maxWidth: 280 }} value={label} onChange={e => setLabel(e.target.value)} placeholder={t('wr.versions.label')} aria-label={t('wr.versions.label')} />
        <Button icon="pin" onClick={snapshot} disabled={busy}>{t('wr.versions.snapshot')}</Button>
        <span className="grow" />
        <Button onClick={onClose}>{t('common.close')}</Button>
        <Button variant="primary" icon="rollback" disabled={content === null || content === now}
          onClick={() => { if (content !== null && picked) { onRestore(content, picked.label || rel(picked.created_at)); onClose(); } }}>{t('wr.versions.restore')}</Button>
      </>}>
      <div className="wr-versions">
        <div className="wr-versions-list">
          {error && <ErrorNote error={error} onRetry={reload} />}
          {loading && !data ? <div className="empty"><Spinner /></div> : !snaps.length && !commits.length ? <p className="faint">{t('wr.versions.empty')}</p> : null}
          {snaps.length > 0 && <><div className="label">{t('wr.versions.snapshots')}</div>{snaps.map(row)}</>}
          {commits.length > 0 && <><div className="label" style={{ marginTop: 12 }}>{t('wr.versions.git')}</div>{commits.map(row)}</>}
        </div>
        <div className="wr-versions-diff">
          {loadErr && <ErrorNote error={loadErr} />}
          {!picked ? <Empty icon="history" title={t('wr.versions.pick')} />
            : content === null ? <div className="empty"><Spinner /></div>
              : content === now ? <Empty icon="check" title={t('wr.versions.same')} />
                : <MergePane a={content} b={now} kind={kind} labels={[t('wr.versions.this'), t('wr.versions.current')]} />}
        </div>
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ conflict

export function ConflictDialog({ disk, mine, kind, onSave, onReload, onClose }: {
  disk: string; mine: string; kind: 'tex' | 'md'; onSave: (merged: string) => void; onReload: () => void; onClose: () => void;
}) {
  const t = useT();
  const merge = useRef<MergeHandle>(null);
  return (
    <Dialog title={t('wr.conflict.title')} onClose={onClose} width={1180}
      footer={<>
        <Button onClick={onReload}>{t('wr.conflict.reload')}</Button>
        <span className="grow" />
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="primary" onClick={() => onSave(merge.current?.right() ?? mine)}>{t('wr.conflict.saveMerged')}</Button>
      </>}>
      <p className="muted wr-small" style={{ marginTop: 0 }}>{t('wr.conflict.hint')}</p>
      <MergePane ref={merge} a={disk} b={mine} kind={kind} editable labels={[t('wr.conflict.disk'), t('wr.conflict.mine')]} />
    </Dialog>
  );
}
