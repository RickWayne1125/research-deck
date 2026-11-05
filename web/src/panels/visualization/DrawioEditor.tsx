// draw.io editor: the official web embed (embed.diagrams.net) driven by its JSON postMessage protocol, saving to the
// project file:
//   configure -> {action:'configure', config}    project fonts/colors, uncompressed XML
//   init      -> {action:'load', xml, autosave:1}
//   save / autosave {xml} -> PUT /file with base_sha (one write at a time; 409 = conflict, the XML stays here)
//                          -> {action:'export', format:'svg'} -> PUT /figures/{id}/preview
// Only messages from https://embed.diagrams.net and from our own iframe are accepted.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { Icon } from '../../components/icons';
import { Button, IconButton, Spinner } from '../../components/ui';
import { ResizeHandle, useResizableWidth } from '../../components/resize';
import { useI18n, useT } from '../../i18n';
import { useApp } from '../../state/app';
import { AiAssist } from './AiAssist';
import { errMessage, vz, type FigureView, type StyleFull } from './api';
import type { EditorHandle } from './editor';

const EMBED_ORIGIN = 'https://embed.diagrams.net';
const EXPORT_DELAY_MS = 1500;

function embedUrl(lang: string): string {
  return `${EMBED_ORIGIN}/?embed=1&proto=json&spin=1&libraries=1&noExitBtn=1&saveAndExit=0&ui=min&configure=1&lang=${lang}`;
}

/** draw.io configuration from the project's style tokens: fonts, preset colors, role color schemes, default styles. */
function drawioConfig(tok: StyleFull | null): Record<string, unknown> {
  const font = tok?.font.family ?? 'Helvetica';
  const px = String(tok?.tools.drawio.font_px ?? 12);
  const sw = String(tok?.geometry.stroke_width ?? 1.2);
  const roles = tok?.roles ?? {};
  const ink = roles.ink?.fill ?? '#20242B';
  const line = roles.line?.stroke ?? '#59616C';
  const palette = tok?.palettes.find(p => p.id === tok.active_palette);
  const hexes = [
    ...['process', 'data', 'emphasis', 'neutral', 'structure', 'accent'].flatMap(r => [roles[r]?.fill, roles[r]?.stroke]),
    ...(palette?.colors.map(c => c.hex) ?? []), ...(tok?.series ?? []),
  ].filter((h): h is string => !!h && h.startsWith('#'));
  const neutral = roles.neutral ?? { fill: '#F4F5F6', stroke: '#A3A8AE' };
  return {
    compressXml: false,
    defaultFonts: [font, ...(tok?.font.fallback ?? []), ...(tok?.font.cjk ?? [])],
    presetColors: [...new Set(hexes.map(h => h.slice(1).toUpperCase()))],
    customColorSchemes: [['process', 'data', 'emphasis', 'neutral', 'structure', 'accent']
      .filter(r => roles[r]).map(r => ({ fill: roles[r].fill, stroke: roles[r].stroke, font: ink }))],
    defaultVertexStyle: { fontFamily: font, fontSize: px, fontColor: ink, strokeWidth: sw, fillColor: neutral.fill, strokeColor: neutral.stroke },
    defaultEdgeStyle: { edgeStyle: 'orthogonalEdgeStyle', rounded: '0', endArrow: 'block', endFill: '1', endSize: '6',
      strokeColor: line, strokeWidth: sw, fontFamily: font, fontSize: px, fontColor: ink },
  };
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error';
// The side column (state, AI edit, preview): 260 px up to what leaves the draw.io canvas 360 px (at most 640 px).
const SIDE_MIN = 260;
const sideDefault = () => (window.innerWidth <= 1100 ? 280 : 320);
const sideMax = (box: HTMLElement | null) => Math.max(SIDE_MIN, Math.min(640, (box?.clientWidth ?? window.innerWidth) - 360));

export const DrawioEditor = forwardRef<EditorHandle, {
  projectId: string; figure: FigureView; tokens: StyleFull | null; onDirty: (d: boolean) => void;
}>(function DrawioEditor({ projectId, figure, tokens, onDirty }, ref) {
  const t = useT();
  const { lang } = useI18n();
  const { onEvent } = useApp();
  const [src] = useState(() => embedUrl(lang === 'zh' ? 'zh' : 'en'));   // fixed for the editor's life
  const frame = useRef<HTMLIFrameElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const sideW = useResizableWidth('rd.vz.aiW', sideDefault, SIDE_MIN, () => sideMax(box.current), { cssVar: '--vz-dio-w', target: box });
  const [fileReady, setFileReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editorLoaded, setEditorLoaded] = useState(false);
  const [slow, setSlow] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [preview, setPreview] = useState<string | null>(figure.preview);
  const [info, setInfo] = useState<string | null>(null);

  // Long-lived state the message handler reads.
  const savedXml = useRef('');
  const baseSha = useRef<string | null>(null);
  const pending = useRef<string | null>(null);
  const saving = useRef<Promise<void> | null>(null);
  const blocked = useRef(false);            // a conflict or error stops autosave until the researcher acts
  const loads = useRef(0);
  const exportTimer = useRef<number | null>(null);
  const tokRef = useRef(tokens);
  tokRef.current = tokens;
  const statusRef = useRef(figure.status);
  // draw.io fits the diagram to its viewport on load; loaded while hidden (background tab, zero size) it lands at 1 %
  // with unrouted edges, so such a load is repeated once the editor is visible (only while nothing is unsaved).
  const loadedUnseen = useRef(false);

  const markDirty = useCallback(() => onDirty(pending.current !== null || blocked.current), [onDirty]);

  const send = useCallback((msg: Record<string, unknown>) => {
    frame.current?.contentWindow?.postMessage(JSON.stringify(msg), EMBED_ORIGIN);
  }, []);

  const requestExport = useCallback(() => {
    setExporting(true);
    send({ action: 'export', format: 'svg' });
  }, [send]);
  const scheduleExport = useCallback(() => {
    if (exportTimer.current) window.clearTimeout(exportTimer.current);
    exportTimer.current = window.setTimeout(requestExport, EXPORT_DELAY_MS);
  }, [requestExport]);
  useEffect(() => () => { if (exportTimer.current) window.clearTimeout(exportTimer.current); }, []);

  // Write the newest XML; one request at a time, later edits queue behind it.
  const flush = useCallback((force = false): Promise<void> => {
    if (saving.current) return saving.current;
    if ((blocked.current && !force) || pending.current === null) return Promise.resolve();
    const xml = pending.current;
    pending.current = null;
    if (xml === savedXml.current) {
      send({ action: 'status', message: t('vz.dio.saved'), modified: false });
      markDirty();
      return Promise.resolve();
    }
    setSaveState('saving');
    const job = (async () => {
      try {
        const r = await vz.writeFile(projectId, figure.source, xml, force ? null : baseSha.current);
        baseSha.current = r.sha;
        savedXml.current = xml;
        blocked.current = false;
        setConflict(false);
        setSaveError(null);
        setSaveState('saved');
        send({ action: 'status', message: t('vz.dio.saved'), modified: false });
        scheduleExport();
      } catch (e) {
        if (pending.current === null) pending.current = xml;   // never drop the browser's XML
        blocked.current = true;
        setSaveState('error');
        if (e instanceof ApiError && e.status === 409) setConflict(true);
        else setSaveError(errMessage(e));
        send({ action: 'status', message: t('vz.saveFailed', { msg: errMessage(e) }), modified: true });
      } finally {
        saving.current = null;
        markDirty();
      }
    })();
    saving.current = job;
    return job.then(() => { if (!blocked.current && pending.current !== null) return flush(); });
  }, [projectId, figure.source, send, t, scheduleExport, markDirty]);

  const loadIntoEditor = useCallback((xml: string) => {
    send({ action: 'load', xml, autosave: 1, title: figure.title });
  }, [send, figure.title]);

  // The file first; the iframe mounts once there is XML to hand it.
  useEffect(() => {
    let alive = true;
    vz.readFile(projectId, figure.source).then(f => {
      if (!alive) return;
      savedXml.current = f.content;
      baseSha.current = f.sha;
      setFileReady(true);
    }).catch(e => alive && setLoadError(errMessage(e)));
    return () => { alive = false; };
  }, [projectId, figure.source]);

  useEffect(() => {
    if (!fileReady || editorLoaded) return;
    const id = window.setTimeout(() => setSlow(true), 15000);
    return () => window.clearTimeout(id);
  }, [fileReady, editorLoaded]);

  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== EMBED_ORIGIN || ev.source !== frame.current?.contentWindow) return;
      let msg: { event?: string; xml?: string; data?: string; format?: string };
      try { msg = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data; } catch { return; }
      if (!msg || typeof msg !== 'object') return;
      switch (msg.event) {
        case 'configure': send({ action: 'configure', config: drawioConfig(tokRef.current) }); break;
        case 'init': loadIntoEditor(savedXml.current); break;
        case 'load':
          setEditorLoaded(true);
          loadedUnseen.current = document.hidden || (frame.current?.clientWidth ?? 0) === 0;
          // The first load refreshes a missing/outdated preview; later loads (reload, AI accept) always do.
          if (loads.current++ > 0 || statusRef.current !== 'ok') scheduleExport();
          break;
        case 'save':
        case 'autosave':
          if (typeof msg.xml === 'string') { pending.current = msg.xml; markDirty(); void flush(); }
          break;
        case 'export':
          if (msg.data) {
            vz.putPreview(projectId, figure.id, { svg: msg.data })
              .then(f => { setPreview(f.preview); statusRef.current = 'ok'; })
              .catch(e => setInfo(errMessage(e)))
              .finally(() => setExporting(false));
          } else setExporting(false);
          break;
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [send, loadIntoEditor, scheduleExport, flush, markDirty, projectId, figure.id]);

  useEffect(() => {
    const el = frame.current;
    if (!fileReady || !el) return;
    const retry = () => {
      if (!loadedUnseen.current || document.hidden || el.clientWidth === 0) return;
      loadedUnseen.current = false;
      if (pending.current === null && !blocked.current) loadIntoEditor(savedXml.current);
    };
    const ro = new ResizeObserver(retry);
    ro.observe(el);
    document.addEventListener('visibilitychange', retry);
    return () => { ro.disconnect(); document.removeEventListener('visibilitychange', retry); };
  }, [fileReady, loadIntoEditor]);

  const reloadFromDisk = useCallback(async () => {
    const f = await vz.readFile(projectId, figure.source);
    savedXml.current = f.content;
    baseSha.current = f.sha;
    pending.current = null;
    blocked.current = false;
    setConflict(false);
    setSaveError(null);
    setSaveState('idle');
    markDirty();
    loadIntoEditor(f.content);
  }, [projectId, figure.source, loadIntoEditor, markDirty]);

  const overwrite = useCallback(() => {
    if (pending.current === null) pending.current = savedXml.current;
    blocked.current = false;
    return flush(true);
  }, [flush]);

  // Another writer (an agent, the terminal, another tab): reload when nothing is unsaved here, else a conflict.
  useEffect(() => onEvent('file', (e) => {
    if (e.payload?.path !== figure.source || e.payload?.sha === baseSha.current) return;
    window.setTimeout(async () => {
      if (saving.current) await saving.current;
      try {
        const f = await vz.readFile(projectId, figure.source);
        if (f.sha === baseSha.current) return;
        if (pending.current === null && !blocked.current) {
          savedXml.current = f.content;
          baseSha.current = f.sha;
          loadIntoEditor(f.content);
          setInfo(t('vz.reloaded'));
        } else { blocked.current = true; setConflict(true); markDirty(); }
      } catch { /* the next event retries */ }
    }, 300);
  }), [onEvent, projectId, figure.source, loadIntoEditor, markDirty, t]);

  useImperativeHandle(ref, () => ({
    save: async () => {
      // Drain the queue: an in-flight write may leave newer XML pending behind it.
      for (let i = 0; i < 5 && (saving.current || (pending.current !== null && !blocked.current)); i++) await flush();
      return pending.current === null && !blocked.current;
    },
    dirty: () => pending.current !== null || blocked.current,
  }), [flush]);

  const acceptProposal = async (proposal: string) => {
    // Save first so the file and the editor agree, then show it in draw.io (its 'load' triggers a fresh preview).
    if (saving.current) await saving.current;
    const r = await vz.writeFile(projectId, figure.source, proposal, baseSha.current);
    baseSha.current = r.sha;
    savedXml.current = proposal;
    pending.current = null;
    markDirty();
    loadIntoEditor(proposal);
    return t('vz.ai.acceptedSaved');
  };

  if (loadError) return <div className="vz-pad"><div className="notice accent"><Icon name="warn" /> {t('vz.error.load', { msg: loadError })}</div></div>;
  if (!fileReady) return <div className="empty"><Spinner /></div>;

  return (
    <div ref={box} className="vz-dio" style={sideW.style}>
      <div className="vz-dio-stage">
        <iframe ref={frame} className="vz-dio-frame" src={src} title={`draw.io — ${figure.title}`} allow="clipboard-read; clipboard-write" />
        {!editorLoaded && (
          <div className="vz-dio-loading">
            <Spinner /> <span>{t('vz.dio.loading')}</span>
            {slow && <span className="faint">{t('vz.dio.offline')}</span>}
          </div>
        )}
      </div>
      <div id="vz-dio-side" className="vz-dio-pane">
        <ResizeHandle pane={sideW} edge="left" label={t('vz.dio.resize')} controls="vz-dio-side" />
        <aside className="vz-dio-side">
          <div className="vz-dio-state">
            {saveState === 'saving' ? <><Spinner /> {t('common.saving')}</>
              : saveState === 'error' ? <><span className="dot accent" /> {t('vz.unsaved')}</>
              : saveState === 'saved' ? <><span className="dot ok" /> {t('vz.dio.saved')}</>
              : <><span className="dot" /> <span className="mono ellipsis">{figure.source}</span></>}
            <div className="grow" />
            {exporting && <span className="faint row" style={{ gap: 4 }}><Spinner /> {t('vz.dio.exporting')}</span>}
          </div>
          {conflict && (
            <div className="notice accent" role="alert">
              <Icon name="warn" />
              <div className="col" style={{ gap: 6 }}>
                <div><b>{t('vz.conflict.title')}</b> {t('vz.conflict.body', { path: figure.source })}</div>
                <div className="row wrap">
                  <Button size="sm" onClick={reloadFromDisk}>{t('vz.conflict.reload')}</Button>
                  <Button size="sm" variant="danger" onClick={() => void overwrite()}>{t('vz.conflict.overwrite')}</Button>
                </div>
              </div>
            </div>
          )}
          {saveError && !conflict && (
            <div className="notice accent" role="alert"><Icon name="warn" /><span className="grow">{t('vz.saveFailed', { msg: saveError })}</span>
              <Button size="sm" onClick={() => { blocked.current = false; void flush(); }}>{t('common.retry')}</Button></div>
          )}
          {info && <div className="notice"><Icon name="info" /><span className="grow">{info}</span><IconButton icon="close" label={t('common.close')} onClick={() => setInfo(null)} /></div>}
          <div className="notice"><Icon name="info" /><span>{t('vz.dio.notice', { path: figure.source })}</span></div>

          <AiAssist projectId={projectId} figureId={figure.id} kind="drawio"
            getSource={() => pending.current ?? savedXml.current} onAccept={acceptProposal} />

          <section className="col" style={{ gap: 6 }}>
            <div className="row"><span className="label grow">{t('vz.dio.preview')}</span>
              <IconButton icon="refresh" label={t('vz.dio.exporting')} onClick={requestExport} disabled={!editorLoaded} /></div>
            <div className="vz-thumb vz-thumb-sm">{preview ? <img src={preview} alt={figure.title} /> : <span className="faint">{t('vz.noPreview')}</span>}</div>
          </section>
          {figure.native?.installed && (
            <Button size="sm" icon="external" onClick={() => vz.openNative(projectId, figure.id).catch(e => setInfo(errMessage(e)))}>{t('vz.dio.openDesktop')}</Button>
          )}
        </aside>
      </div>
    </div>
  );
});
