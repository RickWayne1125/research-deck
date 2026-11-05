// matplotlib editor: CodeMirror (python) | live SVG preview. Edits re-render the unsaved buffer after ~900 ms; ⌘S saves
// to the project file (409 = changed on disk -> conflict notice). Render log, data files with a CSV preview, AI edits.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { Icon } from '../../components/icons';
import { Button, IconButton, Spinner } from '../../components/ui';
import { useT } from '../../i18n';
import { useApp } from '../../state/app';
import type { RenderResult } from '../../types';
import { AiAssist } from './AiAssist';
import { CodeEditor, type CodeEditorHandle } from './CodeEditor';
import { CsvPreview } from './CsvPreview';
import { RatioSplit } from './RatioSplit';
import { errMessage, vz, type FigureView } from './api';
import type { EditorHandle } from './editor';

const RENDER_DELAY_MS = 900;

export const MplEditor = forwardRef<EditorHandle, { projectId: string; figure: FigureView; onDirty: (d: boolean) => void }>(
  function MplEditor({ projectId, figure, onDirty }, ref) {
    const t = useT();
    const { onEvent } = useApp();
    const editor = useRef<CodeEditorHandle>(null);
    const [loaded, setLoaded] = useState<{ content: string } | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const saved = useRef<{ text: string; sha: string | null }>({ text: '', sha: null });
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [conflict, setConflict] = useState(false);
    const [info, setInfo] = useState<string | null>(null);
    const [preview, setPreview] = useState<string | null>(figure.preview);
    const [result, setResult] = useState<RenderResult | null>(null);
    const [rendering, setRendering] = useState(false);
    const [logOpen, setLogOpen] = useState(false);
    const [exporting, setExporting] = useState(false);
    const seq = useRef(0);
    const timer = useRef<number | null>(null);

    useEffect(() => { onDirty(dirty); }, [dirty, onDirty]);

    const render = useCallback(async (source?: string) => {
      const n = ++seq.current;
      setRendering(true);
      try {
        const res = await vz.render(projectId, figure.id, source);
        if (n !== seq.current) return;
        setResult(res);
        if (res.ok && res.preview) setPreview(res.preview);
        if (!res.ok) setLogOpen(true);
      } catch (e) {
        if (n === seq.current) setResult({ ok: false, preview: null, log: errMessage(e), duration_ms: 0 });
      } finally {
        if (n === seq.current) setRendering(false);
      }
    }, [projectId, figure.id]);

    const scheduleRender = useCallback((text: string) => {
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => render(text), RENDER_DELAY_MS);
    }, [render]);
    useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

    // Load the script once; render right away when the preview is missing or out of date.
    useEffect(() => {
      let alive = true;
      vz.readFile(projectId, figure.source).then(f => {
        if (!alive) return;
        saved.current = { text: f.content, sha: f.sha };
        setLoaded({ content: f.content });
        if (figure.status !== 'ok') render();
      }).catch(e => alive && setLoadError(errMessage(e)));
      return () => { alive = false; };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [projectId, figure.id, figure.source]);

    const onChange = useCallback((text: string) => {
      setDirty(text !== saved.current.text);
      scheduleRender(text);
    }, [scheduleRender]);

    const save = useCallback(async (force = false): Promise<boolean> => {
      const text = editor.current?.getDoc() ?? '';
      setSaving(true);
      setSaveError(null);
      try {
        const r = await vz.writeFile(projectId, figure.source, text, force ? null : saved.current.sha);
        saved.current = { text, sha: r.sha };
        setDirty((editor.current?.getDoc() ?? '') !== text);
        setConflict(false);
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) setConflict(true);
        else setSaveError(errMessage(e));
        return false;
      } finally {
        setSaving(false);
      }
    }, [projectId, figure.source]);

    const reloadFromDisk = useCallback(async () => {
      const f = await vz.readFile(projectId, figure.source);
      saved.current = { text: f.content, sha: f.sha };
      editor.current?.setDoc(f.content);
      setDirty(false);
      setConflict(false);
    }, [projectId, figure.source]);

    useImperativeHandle(ref, () => ({ save: () => save(), dirty: () => dirty }), [save, dirty]);

    // ⌘S anywhere in the panel (CodeMirror handles it itself while focused and marks the event handled).
    useEffect(() => {
      const onKey = (e: KeyboardEvent) => {
        if (e.defaultPrevented || !(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 's') return;
        e.preventDefault();
        void save();
      };
      window.addEventListener('keydown', onKey);
      return () => window.removeEventListener('keydown', onKey);
    }, [save]);

    // Someone else wrote the script (another tab, an agent, the terminal): reload when clean, warn when not.
    // Data file changes just re-render the current buffer.
    useEffect(() => onEvent('file', (e) => {
      const path = e.payload?.path as string | undefined;
      if (path === figure.source && e.payload?.sha !== saved.current.sha) {
        window.setTimeout(async () => {
          try {
            const f = await vz.readFile(projectId, figure.source);
            if (f.sha === saved.current.sha) return;
            if ((editor.current?.getDoc() ?? '') === saved.current.text) {
              saved.current = { text: f.content, sha: f.sha };
              editor.current?.setDoc(f.content);
              setInfo(t('vz.reloaded'));
            } else setConflict(true);
          } catch { /* the next event retries */ }
        }, 300);
      } else if (path && figure.data.includes(path)) {
        scheduleRender(editor.current?.getDoc() ?? '');
      }
    }), [onEvent, projectId, figure.source, figure.data, scheduleRender, t]);

    const exportPdf = async () => {
      setExporting(true);
      try {
        if (dirty) await save();
        const r = await vz.exportNative(projectId, figure.id);
        setInfo(t('vz.mpl.exported', { path: r.outputs.join(', ') }));
      } catch (e) {
        const detail = e instanceof ApiError ? (e.detail as { log?: string }) : null;
        if (detail?.log) { setResult({ ok: false, preview: null, log: detail.log, duration_ms: 0 }); setLogOpen(true); }
        setInfo(errMessage(e));
      } finally {
        setExporting(false);
      }
    };

    if (loadError) return <div className="vz-pad"><div className="notice accent"><Icon name="warn" /> {t('vz.error.load', { msg: loadError })}</div></div>;
    if (!loaded) return <div className="empty"><Spinner /></div>;

    const failed = result && !result.ok;
    return (
      <div className="vz-editor">
        <div className="vz-toolbar">
          <span className="label">{t('vz.mpl.code')}</span>
          <span className="mono faint ellipsis" style={{ fontSize: 'var(--fs-xs)' }} title={t('vz.mpl.saveHint', { path: figure.source })}>{figure.source}</span>
          {dirty && <span className="badge accent">{t('vz.unsaved')}</span>}
          <div className="grow" />
          <span className="vz-render-state" title={t('vz.mpl.liveHint')}>
            {rendering ? <><Spinner /> {t('vz.mpl.rendering')}</>
              : failed ? <><span className="dot accent" /> {t('vz.status.error')}</>
              : result ? <><span className="dot ok" /> {t('vz.mpl.rendered', { ms: result.duration_ms })}</>
              : <><span className="dot" /> {t('vz.mpl.live')}</>}
          </span>
          <IconButton icon="refresh" label={t('vz.mpl.render')} onClick={() => render(editor.current?.getDoc())} />
          <Button size="sm" icon="download" onClick={exportPdf} disabled={exporting}>{t('vz.mpl.exportPdf')}</Button>
          <Button size="sm" variant={dirty ? 'accent' : undefined} onClick={() => save()} disabled={saving || !dirty} title={t('vz.saveShortcut')}>
            {saving ? t('common.saving') : dirty ? t('common.save') : t('common.saved')}
          </Button>
        </div>
        {conflict && (
          <div className="vz-banner notice accent" role="alert">
            <Icon name="warn" />
            <div className="grow"><b>{t('vz.conflict.title')}</b> {t('vz.conflict.body', { path: figure.source })}</div>
            <Button size="sm" onClick={reloadFromDisk}>{t('vz.conflict.reload')}</Button>
            <Button size="sm" variant="danger" onClick={() => save(true)}>{t('vz.conflict.overwrite')}</Button>
          </div>
        )}
        {saveError && <div className="vz-banner notice accent" role="alert"><Icon name="warn" /><span className="grow">{t('vz.saveFailed', { msg: saveError })}</span></div>}
        {info && <div className="vz-banner notice"><Icon name="info" /><span className="grow">{info}</span><IconButton icon="close" label={t('common.close')} onClick={() => setInfo(null)} /></div>}

        <div className="vz-editor-body">
          <RatioSplit storageKey="vz.mpl.ratio" initial={0.52} label={t('vz.split.resize')}
            left={<CodeEditor ref={editor} initial={loaded.content} onChange={onChange} onSave={() => save()} ariaLabel={figure.source} />}
            right={(
              <div className="vz-side-col">
                <div className={`vz-preview ${failed ? 'is-failed' : ''}`} aria-label={t('vz.mpl.preview')}>
                  {preview ? <img src={preview} alt={figure.title} /> : <div className="faint">{rendering ? <Spinner /> : t('vz.noPreview')}</div>}
                  {failed && preview && <div className="vz-preview-flag"><Icon name="warn" size={14} /> {t('vz.mpl.renderFailed')}</div>}
                </div>
                <details className="vz-log" open={logOpen} onToggle={e => setLogOpen((e.target as HTMLDetailsElement).open)}>
                  <summary>
                    <Icon name={logOpen ? 'chevronDown' : 'chevronRight'} size={14} />
                    <span className="label">{t('vz.mpl.log')}</span>
                    {failed && <span className="badge accent">{t('vz.status.error')}</span>}
                  </summary>
                  <pre className="code">{result?.log?.trim() || t('vz.mpl.logEmpty')}</pre>
                </details>
                <AiAssist projectId={projectId} figureId={figure.id} kind="matplotlib"
                  getSource={() => editor.current?.getDoc() ?? ''}
                  onAccept={(proposal) => { editor.current?.setDoc(proposal); return t('vz.ai.accepted'); }} />
                <section className="vz-data">
                  <div className="label">{t('vz.mpl.data')}</div>
                  {figure.data.length ? figure.data.map(path => <CsvPreview key={path} projectId={projectId} path={path} />)
                    : <p className="vz-hint">{t('vz.mpl.noData')}</p>}
                </section>
              </div>
            )} />
        </div>
      </div>
    );
  });
