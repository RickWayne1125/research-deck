// Detail drawer of one run: does it need a rerun (and why), config, code and footprint, data/env, metrics, the log
// (a live terminal while running), artifacts, the command, and "ask the agent to analyze this run". Its left edge
// resizes it (drawerWidth.ts).
import { Fragment, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Button, IconButton, Segmented, Spinner, useLoad } from '../../components/ui';
import { Icon } from '../../components/icons';
import { FreshBadge, useDagLabels } from '../../dag/encoding';
import { useI18n, useRelTime, useT } from '../../i18n';
import { useApp } from '../../state/app';
import { exApi, LIVE_STATUSES, type ExRecord } from './api';
import { clampDrawerWidth, DRAWER_DEFAULT, DRAWER_MIN, drawerMax, keyDrawerWidth, loadDrawerWidth, saveDrawerWidth } from './drawerWidth';
import { LogTerminal } from './LogTerminal';
import { formatDuration, formatValue, reasonText, runDuration, StatusCell, toYaml, useNow } from './parts';

const CONTEXT_LOG_LINES = 40;

export function RunDrawer({ pid, id, summary, onClose }: { pid: string; id: string; summary: ExRecord | undefined; onClose: () => void }) {
  const t = useT();
  const { data, error, reload } = useLoad(() => exApi.get(pid, id), [pid, id]);
  // The list reloads on every 'experiments' event; follow it when this record changed.
  const stamp = `${summary?.updated?.at ?? ''}|${summary?.status ?? ''}|${summary?.freshness ?? ''}`;
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } reload(); }, [stamp]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Esc closes the drawer unless a dialog or the expanded log is open (each closes itself first).
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('.scrim, .ex-term-overlay')) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const aside = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(loadDrawerWidth);
  const [dragging, setDragging] = useState(false);
  const room = () => aside.current?.parentElement?.clientWidth ?? window.innerWidth;
  const resizeTo = (w: number) => { setWidth(w); saveDrawerWidth(w); };
  const onResizeStart = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const handle = e.currentTarget;
    const x0 = e.clientX;
    const w0 = aside.current?.getBoundingClientRect().width ?? width;
    let w = w0;
    handle.setPointerCapture(e.pointerId);
    setDragging(true);
    const body = document.body.style;
    const before = { cursor: body.cursor, userSelect: body.userSelect };
    body.cursor = 'col-resize';
    body.userSelect = 'none';
    const move = (ev: PointerEvent) => { w = clampDrawerWidth(w0 + x0 - ev.clientX, room()); setWidth(w); };
    const end = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', end);
      handle.removeEventListener('pointercancel', end);
      Object.assign(body, before);
      setDragging(false);
      if (w !== w0) saveDrawerWidth(w);
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
  };
  const reset = () => { setWidth(DRAWER_DEFAULT); saveDrawerWidth(null); };
  const onResizeKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const next = keyDrawerWidth(e.key, e.shiftKey, aside.current?.getBoundingClientRect().width ?? width, room());
    if (next == null) return;
    e.preventDefault();
    if (e.key === 'Enter') reset(); else resizeTo(next);
  };

  const rec = data ?? summary ?? null;
  return (
    <aside ref={aside} className="ex-drawer" aria-label={rec?.title ?? id} style={{ width: `min(${width}px, 100%)` }}>
      <div className={`ex-drawer-resize${dragging ? ' dragging' : ''}`} role="separator" aria-orientation="vertical" tabIndex={0}
        aria-label={t('ex.d.resize')} title={t('ex.d.resizeHint')} aria-valuemin={DRAWER_MIN} aria-valuemax={drawerMax(room())}
        aria-valuenow={Math.round(width)} onPointerDown={onResizeStart} onDoubleClick={reset} onKeyDown={onResizeKey} />
      <div className="ex-drawer-head">
        <div className="col grow" style={{ gap: 2 }}>
          <h2 className="h2 ellipsis" title={rec?.title}>{rec?.title ?? id}</h2>
          <span className="faint mono ex-small ellipsis">{id}</span>
        </div>
        <IconButton icon="close" label={t('common.close')} onClick={onClose} />
      </div>
      {!rec ? (
        <div className="ex-drawer-body">{error ? <div className="notice accent">{t('ex.d.notFound')}</div> : <div className="empty"><Spinner /></div>}</div>
      ) : <DrawerBody pid={pid} rec={rec} />}
    </aside>
  );
}

function DrawerBody({ pid, rec }: { pid: string; rec: ExRecord }) {
  const t = useT();
  const { lang } = useI18n();
  const rel = useRelTime();
  const L = useDagLabels();
  const { navigate, askAgent } = useApp();
  const live = LIVE_STATUSES.includes(rec.status);
  const now = useNow(5000, rec.status === 'running');
  const [configView, setConfigView] = useState<'json' | 'yaml'>('json');
  const [copied, setCopied] = useState(false);
  const cell = rec.cell ?? rec.dag_cell ?? null;
  const metrics = Object.entries(rec.metrics ?? {});
  const footprint = rec.code?.footprint ?? [];
  const configKeys = Object.keys(rec.config ?? {}).length;

  const copy = () => {
    if (!rec.command) return;
    navigator.clipboard?.writeText(rec.command).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); }).catch(() => {});
  };
  const ask = () => {
    const { logs_tail, ...record } = rec;
    const tail = (logs_tail ?? []).slice(-CONTEXT_LOG_LINES);
    askAgent(t('ex.d.askPrompt', { title: rec.title, id: rec.id }), {
      node_id: rec.node_id ?? undefined,
      extra: `Experiment record .research/experiments/${rec.id}.json (freshness and stale_reasons are derived from the DAG):\n`
        + `${JSON.stringify(record, null, 2)}${tail.length ? `\n\nLast ${tail.length} log lines:\n${tail.join('\n')}` : ''}`,
    });
  };
  const openFile = (path: string) => navigate('coding', path);
  const isProjectPath = (s: string) => !/^[a-z][a-z0-9+.-]*:\/\//i.test(s) && !s.startsWith('/');

  return (
    <div className="ex-drawer-body">
      <div className="row wrap ex-gap">
        <StatusCell status={rec.status} progress={rec.progress} t={t} />
        <div className="grow" />
        <Button variant="primary" icon="sparkle" onClick={ask}>{t('ex.d.ask')}</Button>
      </div>
      {rec.status === 'planned' && <div className="notice"><Icon name="info" /> {t('ex.d.planned')}</div>}

      <section className={`ex-sec ex-fresh ex-fresh-${rec.freshness}`}>
        <div className="row"><span className="label grow">{t('ex.d.rerun')}</span><FreshBadge level={rec.freshness} /></div>
        <p className="ex-explain">{t(`ex.freshExplain.${rec.freshness}`)}</p>
        {rec.stale_reasons && rec.stale_reasons.length > 0 && (
          <ul className="ex-reasons">{rec.stale_reasons.map((r, i) => <li key={i} title={r}>{reasonText(r, t)}</li>)}</ul>
        )}
        {/* "stale" here may mean pending or orphaned in the DAG; name the exact level when it differs */}
        {rec.dag_level && rec.dag_level !== 'fresh' && rec.dag_level !== rec.freshness && <div className="faint ex-small">DAG: {L.fresh(rec.dag_level)}</div>}
      </section>

      <section className="ex-sec">
        <dl className="kv">
          <dt>{t('ex.d.node')}</dt>
          <dd>{rec.node_id ? <button type="button" className="ex-link mono" onClick={() => navigate('dag', rec.node_id!)}>{rec.node_id}</button> : <span className="faint">{t('ex.noNode')}</span>}</dd>
          {cell && <><dt>{t('ex.d.cell')}</dt><dd className="mono">{cell}</dd></>}
          {rec.run_id && <><dt>{t('ex.d.run')}</dt><dd className="mono">{rec.run_id}</dd></>}
          {rec.job_id && <><dt>{t('ex.d.job')}</dt><dd className="mono">{rec.job_id}</dd></>}
          <dt>{t('ex.d.target')}</dt>
          <dd>{[rec.target.platform, rec.target.node].filter(Boolean).join(' · ') || '—'}
            {(rec.target.gpus > 0 || rec.target.gpu_type) && <span className="muted"> · {rec.target.gpus || '?'} × {rec.target.gpu_type ?? 'GPU'}</span>}</dd>
          <dt>{t('ex.d.started')}</dt><dd title={rec.started_at ?? undefined}>{rec.started_at ? rel(rec.started_at) : t('ex.d.notStarted')}</dd>
          {rec.finished_at && <><dt>{t('ex.d.finished')}</dt><dd title={rec.finished_at}>{rel(rec.finished_at)}</dd></>}
          {rec.started_at && (rec.finished_at || rec.status === 'running') && (
            <><dt>{t('ex.d.duration')}</dt><dd className="num">{formatDuration(runDuration(rec.started_at, rec.finished_at, now), t)}</dd></>
          )}
        </dl>
      </section>

      {rec.command && (
        <section className="ex-sec">
          <div className="row"><span className="label grow">{t('ex.d.command')}</span>
            <Button size="sm" variant="ghost" icon={copied ? 'check' : 'file'} onClick={copy}>{copied ? t('common.copied') : t('ex.d.copy')}</Button></div>
          <pre className="ex-pre ex-cmd">{rec.command}</pre>
        </section>
      )}

      <section className="ex-sec">
        <div className="row"><span className="label grow">{t('ex.d.config')}</span>
          {configKeys > 0 && <Segmented value={configView} onChange={setConfigView} ariaLabel={t('ex.d.config')}
            options={[{ value: 'json', label: 'JSON' }, { value: 'yaml', label: 'YAML' }]} />}</div>
        {configKeys ? <pre className="ex-pre">{configView === 'json' ? JSON.stringify(rec.config, null, 2) : toYaml(rec.config)}</pre>
          : <div className="faint ex-small">{t('ex.d.emptyConfig')}</div>}
      </section>

      <section className="ex-sec">
        <span className="label">{t('ex.d.code')}</span>
        <dl className="kv">
          <dt>{t('ex.d.commit')}</dt><dd className="mono">{rec.code?.commit ?? <span className="faint">{t('ex.d.noCommit')}</span>}</dd>
        </dl>
        {footprint.length ? (
          <>
            <div className="row ex-small"><span className="muted">{t('ex.d.footprint', { n: footprint.length })}</span>
              <span className="faint">· {rec.code.footprint_source === 'trace' ? t('ex.d.footprintTrace') : t('ex.d.footprintDeclared')}</span></div>
            <ul className="ex-files">
              {footprint.map(f => (
                <li key={f}><button type="button" className="ex-link mono" title={t('ex.d.openCoding')} onClick={() => openFile(f)}>{f}</button></li>
              ))}
            </ul>
          </>
        ) : <div className="faint ex-small">{t('ex.d.noFootprint')}</div>}
      </section>

      {(rec.dataset || rec.env) && (
        <section className="ex-sec">
          <span className="label">{t('ex.d.data')}</span>
          <dl className="kv">
            {rec.dataset && <><dt>{t('ex.d.dataset')}</dt><dd className="mono">{rec.dataset}</dd></>}
            {rec.env && <><dt>{t('ex.d.env')}</dt><dd className="mono">{rec.env}</dd></>}
          </dl>
        </section>
      )}

      <section className="ex-sec">
        <span className="label">{t('ex.d.metrics')}</span>
        {metrics.length ? (
          <dl className="kv ex-metrics">{metrics.map(([k, v]) => <Fragment key={k}><dt className="mono">{k}</dt><dd className="num">{formatValue(v, lang)}</dd></Fragment>)}</dl>
        ) : <div className="faint ex-small">{t('ex.d.noMetrics')}</div>}
      </section>

      <LogTerminal pid={pid} eid={rec.id} title={rec.title} live={live} />

      <section className="ex-sec">
        <span className="label">{t('ex.d.artifacts')}</span>
        {rec.artifacts?.length ? (
          <ul className="ex-files">
            {rec.artifacts.map(a => <li key={a}>{isProjectPath(a)
              ? <button type="button" className="ex-link mono" title={t('ex.d.openCoding')} onClick={() => openFile(a)}>{a}</button>
              : <span className="mono">{a}</span>}</li>)}
          </ul>
        ) : <div className="faint ex-small">{t('ex.d.noArtifacts')}</div>}
      </section>

      {rec.updated && <div className="faint ex-small">{t('ex.d.updated', { time: rel(rec.updated.at), by: L.actor(rec.updated.by) })}</div>}
    </div>
  );
}
