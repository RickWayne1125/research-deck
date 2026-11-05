// The project conversation: one thread per project, whichever view asks. The header holds the backend, model, effort
// and Fast behind one button (switching backend hands the context off), the session tools behind "⋯"; then the
// conversation (the dashboard transcript, handoff lines, optionally the session's own log, and the live run) and the
// composer, whose chips carry what the researcher is looking at.
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { FIGURES, useApp } from '../state/app';
import { useRelTime, useT } from '../i18n';
import { Icon } from '../components/icons';
import { Button, Dialog, ErrorNote, IconButton, Menu, Spinner, useLoad } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { streamRun } from '../api/client';
import type { AgentEvent, PanelId, ProviderId, RunContext, RunStarted } from '../types';
import { useAgentRun } from './useAgentRun';
import { agentApi, type BindingChange, type DockEntry } from './api';
import {
  PROVIDERS, ProviderMark, copyText, markRunning, modelInfo, modelLabel, modelsOf, providerLabel, resolveBinding,
  shortId, useSessions, type ResolvedBinding,
} from './parts';
import './agent.css';
import './i18n';

const PANEL: PanelId = 'project';
const TRANSCRIPT_LIMIT = 200;
let consumedAsk = 0;        // the last askAgent() request (pendingAsk.n) already put into the composer

export function AgentDock() {
  const { projectId } = useApp();
  return <DockBody key={projectId} pid={projectId!} />;
}

interface RunExtras { tools: { name: string; detail?: string }[]; usage?: Extract<AgentEvent, { type: 'usage' }>; duration?: number }

/** What the live area shows: a run started here (useAgentRun) or one already going when the dock opened. */
interface Live {
  runId: string | null; prompt: string | null; ctx?: RunContext; status: 'running' | 'done' | 'error' | 'cancelled';
  text: string; events: AgentEvent[]; error: string | null;
  meta: Pick<RunStarted, 'provider' | 'model' | 'effort' | 'fast'> | null;
}

function DockBody({ pid }: { pid: string }) {
  const t = useT();
  const { health, pendingAsk, view, sub, setDockOpen, dockFocus, onEvent } = useApp();
  const sessions = useSessions(pid);
  const b = resolveBinding(sessions.doc, PANEL);
  const run = useAgentRun(pid);

  // ---------------------------------------------------------------- transcript
  const [entries, setEntries] = useState<DockEntry[]>([]);
  const [logError, setLogError] = useState<string | null>(null);
  const [showImported, setShowImported] = useState(() => { try { return localStorage.getItem('rd.ag.imported') === '1'; } catch { return false; } });
  const loadTranscript = useCallback(async () => {
    try {
      setEntries(await agentApi.transcript(pid, PANEL, { limit: TRANSCRIPT_LIMIT, imported: showImported }));
      setLogError(null);
    } catch (e) { setLogError(String((e as Error).message ?? e)); }
  }, [pid, showImported]);
  const bindingKey = b ? `${b.provider}:${b.session.session_id ?? ''}` : '';
  useEffect(() => { loadTranscript(); }, [loadTranscript, bindingKey]);
  // A run that finished anywhere in this project (another view, another tab) is part of the conversation.
  useEffect(() => onEvent('agent', () => { loadTranscript(); }), [onEvent, loadTranscript]);
  const toggleImported = () => {
    setShowImported(v => {
      try { localStorage.setItem('rd.ag.imported', v ? '0' : '1'); } catch { /* ignore */ }
      return !v;
    });
  };

  // ---------------------------------------------------------------- live run
  const [sent, setSent] = useState<{ prompt: string; ctx?: RunContext } | null>(null);
  const [extras, setExtras] = useState<Record<string, RunExtras>>({});
  const collecting = useRef<RunExtras>({ tools: [] });
  const runningHere = useRef(false);
  const [follow, setFollow] = useState<Live | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Keep the rail's "running" dot right even if the conversation closes mid-run.
  useEffect(() => () => { if (runningHere.current) markRunning(pid, PANEL, false); }, [pid]);

  // A chat run already going when the conversation opened (e.g. it was closed mid-answer): follow it.
  useEffect(() => {
    if (!b) return;
    let off: (() => void) | null = null, alive = true;
    agentApi.runs(pid).then(rs => {
      const r = rs.find(x => x.status === 'running' && x.purpose === 'chat');
      if (!alive || !r || run.runId) return;
      const prompt = [...entries].reverse().find(e => e.role === 'user' && e.run_id === r.run_id)?.text ?? null;
      setFollow({ runId: r.run_id, prompt, status: 'running', text: '', events: [], error: null, meta: { provider: r.provider as ProviderId, model: r.model, effort: r.effort, fast: r.fast } });
      off = streamRun(r.run_id, (e) => {
        setFollow(f => {
          if (!f) return f;
          const next = { ...f, events: [...f.events, e] };
          if (e.type === 'text') next.text = f.text + e.delta;
          if (e.type === 'error') next.error = e.message;
          if (e.type === 'done') next.status = e.cancelled ? 'cancelled' : e.ok ? 'done' : 'error';
          return next;
        });
        if (e.type === 'done') loadTranscript().then(() => setFollow(null));
      });
    }).catch(() => {});
    return () => { alive = false; off?.(); };
    // Only when the session changes: following is a one-time catch-up, not a poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid, bindingKey]);

  const live: Live | null = run.status !== 'idle'
    ? { runId: run.runId, prompt: sent?.prompt ?? null, ctx: sent?.ctx, status: run.status as Live['status'], text: run.text, events: run.events, error: run.error, meta: run.meta }
    : follow;
  const running = live?.status === 'running';

  const send = async (text: string, ctx?: RunContext) => {
    if (!b || !text.trim() || running) return;
    setNotice(null);
    setSent({ prompt: text, ctx });
    collecting.current = { tools: [] };
    runningHere.current = true;
    markRunning(pid, PANEL, true);
    stickToBottom.current = true;
    try {
      await run.start({ panel: PANEL, prompt: text, purpose: 'chat', context: ctx }, (e) => {
        if (e.type === 'tool') collecting.current.tools.push({ name: e.name, detail: e.detail });
        if (e.type === 'usage') collecting.current.usage = e;
        if (e.type === 'done') collecting.current.duration = e.duration_ms;
      });
    } catch { /* the error stays visible in the live area */ }
    finally {
      runningHere.current = false;
      markRunning(pid, PANEL, false);
    }
  };

  // When a run ends: keep its tool lines and usage under its answer, reload the transcript (which now holds the
  // exchange), then clear the live area. An error stays, with retry.
  useEffect(() => {
    const status = run.status;
    if (status === 'idle' || status === 'running') return;
    const id = run.runId;
    if (id) setExtras(x => ({ ...x, [id]: collecting.current }));
    loadTranscript().then(() => {
      if (status === 'error') return;
      run.reset();
      setSent(null);
      if (status === 'cancelled') setNotice(t('ag.cancelled'));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.status]);

  // ---------------------------------------------------------------- composer
  const [input, setInput] = useState('');
  const [askCtx, setAskCtx] = useState<RunContext | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const focusInput = useCallback(() => requestAnimationFrame(() => {
    const el = inputRef.current;
    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  }), []);
  useEffect(() => { setDismissed(new Set()); }, [view, sub]);
  useEffect(() => {
    // Each askAgent() fills the composer once, even though the dock remounts when the project changes.
    if (!pendingAsk || pendingAsk.n <= consumedAsk) return;
    consumedAsk = pendingAsk.n;
    setInput(pendingAsk.prompt);
    setAskCtx(toRunContext(pendingAsk.context));
    focusInput();
  }, [pendingAsk?.n]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (dockFocus) focusInput(); }, [dockFocus, focusInput]);

  // Context chips: what a view asked about (askAgent) over where the researcher is (the route); each removable.
  const routeCtx = useMemo(() => contextFromRoute(view, sub), [view, sub]);
  const ctx = useMemo<RunContext>(() => {
    const route = Object.fromEntries(Object.entries(routeCtx ?? {}).filter(([k, v]) => !dismissed.has(`${k}:${String(v)}`)));
    return { ...route, ...(askCtx ?? {}) };
  }, [routeCtx, askCtx, dismissed]);
  const chips = (Object.keys(ctx) as (keyof RunContext)[]).map(key => ({ key, from: askCtx && key in askCtx ? 'ask' as const : 'route' as const, ...describeContext(key, ctx, t) }));
  const removeChip = (key: keyof RunContext, from: 'ask' | 'route') => {
    if (from === 'ask') setAskCtx(c => { if (!c) return c; const n = { ...c }; delete n[key]; return Object.keys(n).length ? n : null; });
    else setDismissed(d => new Set(d).add(`${key}:${String(routeCtx?.[key])}`));
  };
  const submit = () => {
    const text = input.trim();
    if (!text || running) return;
    setInput('');
    setAskCtx(null);
    send(text, Object.keys(ctx).length ? ctx : undefined);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); }
  };

  // ---------------------------------------------------------------- scrolling
  const logRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const onScroll = () => {
    const el = logRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };
  useEffect(() => {
    const el = logRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [entries, live?.text, live?.events.length, live?.status]);

  // ---------------------------------------------------------------- binding changes
  const change = async (c: BindingChange) => {
    try { await sessions.update(PANEL, c); setNotice(null); }
    catch (e) { setNotice(String((e as Error).message ?? e)); }
  };
  // Switching backend hands the conversation's gist to the other one (an extract, no model call), then switches.
  const [switching, setSwitching] = useState<ProviderId | null>(null);
  const switchTo = async (to: ProviderId) => {
    if (!b || to === b.provider) return;
    setSwitching(to); setNotice(null);
    try {
      await agentApi.handoff(pid, PANEL, to, false);
      sessions.reload();
      await loadTranscript();
    } catch (e) { setNotice(t('ag.handoff.failed', { error: String((e as Error).message ?? e) })); }
    finally { setSwitching(null); }
  };

  if (!b) {
    return <div className="ag-dock">{sessions.error ? <div className="ag-pad"><ErrorNote error={sessions.error} onRetry={sessions.reload} /></div> : <div className="empty"><Spinner /></div>}</div>;
  }
  const agentName = providerLabel(b.provider, t);
  const write = b.session.permission === 'write';

  return (
    <div className="ag-dock">
      <div className="ag-head">
        <div className="row ag-head-row">
          <h2 className="h3 grow ellipsis">{t('agent.dock')}</h2>
          {running && <span className="ag-running" title={t('ag.chip.running')}><span className="dot accent" /></span>}
          <ModelPill b={b} busy={running || !!switching} switching={switching} onChange={change} onSwitch={switchTo} />
          <SessionMenu pid={pid} b={b} disabled={running} showImported={showImported} onToggleImported={toggleImported}
            onChange={change} onBound={() => loadTranscript()} onNotice={setNotice} />
          <IconButton icon="close" label={t('ag.closeDock')} onClick={() => setDockOpen(false)} />
        </div>
        {health?.fake_agent && <div className="ag-fake">{t('ag.fakeMode')}</div>}
      </div>

      <div className="ag-log" ref={logRef} onScroll={onScroll} aria-live="polite">
        {logError && <ErrorNote error={t('ag.log.loadError', { error: logError })} onRetry={loadTranscript} />}
        {!entries.length && !live && !logError && <div className="ag-empty muted">{t('agent.empty')}</div>}
        {entries.map((e, i) => <EntryView key={`${e.ts}-${i}-${e.role}`} entry={e} extras={e.run_id ? extras[e.run_id] : undefined}
          hideUser={!!live?.prompt && live.status !== 'done' && e.role === 'user' && !!live.runId && e.run_id === live.runId} />)}
        {live && <LiveView live={live} pendingInTranscript={!!live.runId && entries.some(e => e.run_id === live.runId && e.role === 'assistant')}
          onRetry={sent && live.status === 'error' ? () => { const s = sent; run.reset(); send(s.prompt, s.ctx); } : undefined}
          onDismiss={() => { run.reset(); setSent(null); }} />}
        {switching && <div className="ag-notice row" style={{ justifyContent: 'center' }}><Spinner /> {t('ag.switching', { agent: providerLabel(switching, t) })}</div>}
        {notice && <div className="ag-notice">{notice}</div>}
      </div>

      <div className="ag-compose">
        {chips.length > 0 && (
          <div className="ag-chips">
            {chips.map(c => (
              <span key={c.key} className={`chip ag-ctx ${c.from}`} title={c.from === 'route' ? `${t('ag.ctx.fromRoute')}: ${c.title}` : c.title}>
                <span className="ag-ctx-kind">{t(`ag.ctx.${c.key === 'node_id' ? 'node' : c.key}`)}</span>
                <span className="mono ellipsis">{c.value}</span>
                <button type="button" className="ag-ctx-x" aria-label={t('ag.ctx.remove')} onClick={() => removeChip(c.key, c.from)}><Icon name="close" size={10} /></button>
              </span>
            ))}
          </div>
        )}
        <textarea ref={inputRef} className="textarea ag-input" rows={3} value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown} placeholder={t('agent.placeholder', { agent: agentName })} aria-label={t('agent.send')} />
        <div className="row ag-compose-foot">
          <span className={`ag-perm-note${write ? ' write' : ''}`} title={t(write ? 'ag.perm.writeHint' : 'ag.perm.readHint')}>
            {write && <Icon name="warn" size={12} />}{t(write ? 'ag.perm.writeFoot' : 'ag.perm.readFoot')}
          </span>
          <span className="grow" />
          {running
            ? <Button icon="stop" onClick={() => (run.runId ? run.cancel() : follow?.runId && agentApi.cancel(follow.runId).catch(() => {}))}>{t('agent.cancel')}</Button>
            : <Button variant="accent" icon="send" onClick={submit} disabled={!input.trim() || !!switching} title={t('ag.sendHint')}>{t('agent.send')}</Button>}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ header: model pill and session menu

/** Backend, model, effort and Fast behind one button. */
function ModelPill({ b, busy, switching, onChange, onSwitch }: {
  b: ResolvedBinding; busy: boolean; switching: ProviderId | null; onChange: (c: BindingChange) => Promise<void>; onSwitch: (p: ProviderId) => void;
}) {
  const t = useT();
  const { catalog, health } = useApp();
  const models = modelsOf(catalog, b.provider);
  const info = modelInfo(catalog, b.provider, b.session.model);
  const efforts = info?.efforts ?? [b.session.effort];
  const available = (p: ProviderId) => !!health?.fake_agent || (catalog?.providers.find(x => x.id === p)?.available ?? true);
  const model = modelLabel(catalog, b.provider, b.session.model);
  const label = `${providerLabel(b.provider, t)} · ${model} · ${b.session.effort}${b.session.fast ? ` · ${t('agent.fast')}` : ''}`;
  return (
    <Menu button={(open, toggle) => (
      <button type="button" className="ag-pill" aria-expanded={open} onClick={toggle} title={label} aria-label={label}>
        <ProviderMark provider={b.provider} size={13} />
        <span className="ellipsis ag-pill-model">{model}</span>
        <span className="ag-pill-effort">{b.session.effort}</span>
        {b.session.fast && <Icon name="bolt" size={11} />}
        <Icon name="chevronDown" size={12} />
      </button>
    )}>
      {() => (
        <div className="col ag-pill-pop">
          <div className="seg" role="group" aria-label={t('agent.provider')}>
            {PROVIDERS.map(p => (
              <button key={p} type="button" aria-pressed={b.provider === p} disabled={busy || (!available(p) && b.provider !== p)}
                title={available(p) ? providerLabel(p, t) : t('agent.cliMissing', { agent: providerLabel(p, t) })}
                onClick={() => onSwitch(p)}>
                <span className="ag-seg-label">{switching === p ? <Spinner /> : <ProviderMark provider={p} size={12} />}{providerLabel(p, t)}</span>
              </button>
            ))}
          </div>
          <p className="faint ag-pill-hint">{t('ag.switchHint')}</p>
          <label className="field"><span className="label">{t('agent.model')}</span>
            <select className="select" value={b.session.model} disabled={busy} title={info?.description}
              onChange={e => onChange({ provider: b.provider, model: e.target.value })}>
              {!info && <option value={b.session.model}>{b.session.model}</option>}
              {models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </label>
          <label className="field"><span className="label">{t('agent.effort')}</span>
            <select className="select mono" value={b.session.effort} disabled={busy}
              onChange={e => onChange({ provider: b.provider, effort: e.target.value })}>
              {efforts.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
          </label>
          <label className="ag-check" title={info?.fast ? t('agent.fastHint') : t('ag.fastNone')}>
            <input type="checkbox" checked={b.session.fast} disabled={busy || !info?.fast}
              onChange={() => onChange({ provider: b.provider, fast: !b.session.fast })} />
            <Icon name="bolt" size={12} /><span>{t('agent.fast')}</span>
            <span className="faint ag-pill-hint">{info?.fast ? t('agent.fastHint') : t('ag.fastNone')}</span>
          </label>
        </div>
      )}
    </Menu>
  );
}

/** New conversation, bind an existing session, continue in a terminal, the session's own log, permission. */
function SessionMenu({ pid, b, disabled, showImported, onToggleImported, onChange, onBound, onNotice }: {
  pid: string; b: ResolvedBinding; disabled: boolean; showImported: boolean; onToggleImported: () => void;
  onChange: (c: BindingChange) => Promise<void>; onBound: () => void; onNotice: (s: string | null) => void;
}) {
  const t = useT();
  const { project } = useApp();
  const [binding, setBinding] = useState(false);
  const sid = b.session.session_id;
  const terminalCmd = sid && project
    ? `cd "${project.root.replace(/(["\\$`])/g, '\\$1')}" && ${b.provider === 'claude' ? `claude --resume ${sid}` : `codex resume ${sid}`}`
    : '';
  return (
    <>
      <Menu button={(open, toggle) => <IconButton icon="dots" label={t('common.more')} aria-expanded={open} onClick={toggle} />}>
        {(close) => (
          <div className="ag-menu">
            <div className="ag-menu-meta faint">
              {t('agent.session')}: {sid ? <span className="mono" title={sid}>{shortId(sid)}</span> : t('ag.session.none')}
            </div>
            <button type="button" className="menu-item" disabled={disabled}
              onClick={async () => { close(); await onChange({ provider: b.provider, new_session: true }); onNotice(t('ag.session.newDone')); }}>
              <Icon name="plus" /> {t('ag.newChat')}
            </button>
            <button type="button" className="menu-item" disabled={disabled} onClick={() => { close(); setBinding(true); }}>
              <Icon name="link" /> {t('agent.bindExisting')}…
            </button>
            <button type="button" className="menu-item" disabled={!terminalCmd}
              onClick={async () => { close(); if (await copyText(terminalCmd)) onNotice(t('ag.copiedResume')); }}>
              <Icon name="terminal" /> {t('ag.copyResume')}
            </button>
            <label className="menu-item ag-menu-check" title={t('ag.log.importedHint')}>
              <input type="checkbox" checked={showImported} onChange={onToggleImported} /> {t('ag.log.showImported')}
            </label>
            <hr className="ag-menu-rule" />
            <div className="label ag-menu-label">{t('agent.permission')}</div>
            {(['read', 'write'] as const).map(p => (
              <button key={p} type="button" className="menu-item" disabled={disabled} aria-pressed={b.session.permission === p}
                onClick={() => { close(); if (b.session.permission !== p) onChange({ provider: b.provider, permission: p }); }}>
                <Icon name={b.session.permission === p ? 'check' : 'minus'} />
                <span className="col" style={{ gap: 0 }}>
                  <span>{t(`ag.perm.${p}`)}</span>
                  <span className="faint ag-menu-hint">{t(p === 'read' ? 'ag.perm.readHint' : 'ag.perm.writeHint')}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </Menu>
      {binding && <BindDialog pid={pid} b={b} onClose={() => setBinding(false)}
        onBind={async (provider, sessionId) => { await onChange({ provider, session_id: sessionId }); setBinding(false); onBound(); }} />}
    </>
  );
}

// ------------------------------------------------------------------ binding an existing session

function BindDialog({ pid, b, onClose, onBind }: { pid: string; b: ResolvedBinding; onClose: () => void; onBind: (p: ProviderId, id: string) => Promise<void> }) {
  const t = useT();
  const rel = useRelTime();
  const [filter, setFilter] = useState<'all' | ProviderId>('all');
  const [busy, setBusy] = useState<string | null>(null);
  const list = useLoad(() => agentApi.discover(pid), [pid]);
  const rows = (list.data ?? []).filter(s => filter === 'all' || s.provider === filter);
  return (
    <Dialog title={t('ag.bind.title')} onClose={onClose} width={620}>
      <div className="col" style={{ gap: 12 }}>
        <p className="muted" style={{ margin: 0, fontSize: 'var(--fs-sm)' }}>{t('ag.bind.hint')}</p>
        <div className="seg" role="group" aria-label={t('agent.provider')} style={{ alignSelf: 'flex-start' }}>
          {(['all', 'claude', 'codex'] as const).map(f => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>{f === 'all' ? t('ag.bind.all') : providerLabel(f, t)}</button>
          ))}
        </div>
        {list.loading && <div className="empty"><Spinner /></div>}
        {list.error && <ErrorNote error={list.error} onRetry={list.reload} />}
        {!list.loading && !list.error && !rows.length && <div className="empty muted">{t('ag.bind.empty')}</div>}
        {rows.length > 0 && (
          <div className="list ag-bind-list">
            {rows.map(s => {
              const current = b.entry[s.provider].session_id === s.session_id;
              return (
                <div key={`${s.provider}:${s.session_id}`} className="ag-bind-row">
                  <ProviderMark provider={s.provider} />
                  <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
                    <span className="ellipsis">{s.title || t('ag.bind.untitled')}</span>
                    <span className="faint ag-bind-meta">
                      <span className="mono">{shortId(s.session_id)}</span> · {t('ag.bind.turns', { n: s.turns })} · {rel(s.updated_at)}
                    </span>
                  </div>
                  {current
                    ? <span className="badge ok">{t('ag.bind.current')}</span>
                    : <Button size="sm" disabled={!!busy} onClick={async () => { setBusy(s.session_id); try { await onBind(s.provider, s.session_id); } finally { setBusy(null); } }}>
                        {busy === s.session_id ? <Spinner /> : null}{t('ag.bind.bind')}
                      </Button>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ messages

function AnswerMeta({ provider, model, effort, fast, children }: { provider: string; model?: string | null; effort?: string | null; fast?: boolean | null; children?: React.ReactNode }) {
  const t = useT();
  const { catalog } = useApp();
  return (
    <div className="ag-meta">
      <ProviderMark provider={provider} size={11} />
      <span>{providerLabel(provider, t)}</span>
      {model && <span>· {modelLabel(catalog, provider, model)}</span>}
      {effort && <span>· {effort}</span>}
      {fast && <Icon name="bolt" size={10} />}
      {children}
    </div>
  );
}

function EntryView({ entry, extras, hideUser }: { entry: DockEntry; extras?: RunExtras; hideUser?: boolean }) {
  const t = useT();
  const rel = useRelTime();
  if (entry.role === 'handoff') {
    const line = entry.kind === 'note'
      ? t('ag.handoff.note', { from: providerLabel(entry.from, t), to: providerLabel(entry.to, t) })
      : t('ag.handoff.line', { from: providerLabel(entry.from, t), to: providerLabel(entry.to, t) });
    return (
      <details className="ag-sys">
        <summary>
          <Icon name={entry.kind === 'note' ? 'pin' : 'split'} size={12} />
          <span className="grow">{line}</span>
          <span className="faint">{rel(entry.ts)}</span>
        </summary>
        <div className="ag-sys-body">
          <Markdown text={entry.text} />
          {entry.file && <div className="faint mono ag-sys-file">{t('ag.handoff.file', { file: entry.file })}</div>}
        </div>
      </details>
    );
  }
  if (entry.role === 'user') {
    if (hideUser) return null;
    return (
      <div className={`ag-msg user ${entry.imported ? 'imported' : ''}`}>
        <div className="ag-bubble">{entry.text}</div>
        <div className="ag-meta right">{entry.imported && <span className="ag-imported" title={t('ag.log.importedHint')}>{t('ag.log.imported')} ·</span>}<span>{rel(entry.ts)}</span></div>
      </div>
    );
  }
  return (
    <div className={`ag-msg assistant ${entry.imported ? 'imported' : ''}`}>
      <Markdown text={entry.text} className="ag-answer" />
      {extras && <RunDetails extras={extras} />}
      <AnswerMeta provider={entry.provider} model={entry.model} effort={entry.effort} fast={entry.fast}>
        {entry.imported && <span className="ag-imported" title={t('ag.log.importedHint')}>· {t('ag.log.imported')}</span>}
        <span>· {rel(entry.ts)}</span>
      </AnswerMeta>
    </div>
  );
}

function ToolLine({ name, detail }: { name: string; detail?: string }) {
  return <div className="ag-tool mono"><span className="ag-tool-name">{name}</span>{detail ? <span className="ag-tool-detail"> · {detail}</span> : null}</div>;
}

function UsageLine({ usage, duration }: { usage?: Extract<AgentEvent, { type: 'usage' }>; duration?: number }) {
  const t = useT();
  if (!usage && duration == null) return null;
  const parts: string[] = [];
  if (usage) {
    parts.push(t('ag.usage', { input: usage.input.toLocaleString(), output: usage.output.toLocaleString() }));
    if (usage.cache_read) parts.push(t('ag.usageCached', { n: usage.cache_read.toLocaleString() }));
    if (usage.cost) parts.push(t('ag.cost', { cost: usage.cost.toFixed(3) }));
  }
  if (duration != null) parts.push(t('ag.duration', { s: (duration / 1000).toFixed(1) }));
  return <div className="ag-usage mono">{parts.join(' · ')}</div>;
}

function RunDetails({ extras }: { extras: RunExtras }) {
  const t = useT();
  return (
    <>
      {extras.tools.length > 0 && (
        <details className="ag-tools">
          <summary className="mono">{t('ag.tools', { n: extras.tools.length })}</summary>
          {extras.tools.map((x, i) => <ToolLine key={i} name={x.name} detail={x.detail} />)}
        </details>
      )}
      <UsageLine usage={extras.usage} duration={extras.duration} />
    </>
  );
}

function LiveView({ live, pendingInTranscript, onRetry, onDismiss }: { live: Live; pendingInTranscript: boolean; onRetry?: () => void; onDismiss: () => void }) {
  const t = useT();
  const tools = live.events.filter((e): e is Extract<AgentEvent, { type: 'tool' }> => e.type === 'tool');
  const usage = [...live.events].reverse().find((e): e is Extract<AgentEvent, { type: 'usage' }> => e.type === 'usage');
  const done = [...live.events].reverse().find((e): e is Extract<AgentEvent, { type: 'done' }> => e.type === 'done');
  const last = live.events[live.events.length - 1];
  const thinking = live.status === 'running' && (!live.text || last?.type === 'thinking' || last?.type === 'tool');
  if (pendingInTranscript && live.status === 'done') return null;    // the transcript already shows the answer
  return (
    <>
      {live.prompt && live.status !== 'done' && (
        <div className="ag-msg user"><div className="ag-bubble">{live.prompt}</div></div>
      )}
      <div className="ag-msg assistant live">
        {tools.map((x, i) => <ToolLine key={i} name={x.name} detail={x.detail} />)}
        {live.text && <Markdown text={live.text} className="ag-answer" />}
        {thinking && <div className="ag-thinking"><Spinner /><span>{t('agent.thinking')}</span></div>}
        {live.status === 'cancelled' && <div className="ag-usage">{t('ag.cancelled')}</div>}
        {live.status !== 'running' && <UsageLine usage={usage} duration={done?.duration_ms} />}
        {live.meta && <AnswerMeta provider={live.meta.provider} model={live.meta.model} effort={live.meta.effort} fast={live.meta.fast} />}
      </div>
      {live.status === 'error' && (
        <div className="ag-error">
          <ErrorNote error={`${t('agent.error')}: ${live.error ?? ''}`} onRetry={onRetry} />
          <Button size="sm" variant="ghost" onClick={onDismiss}>{t('common.close')}</Button>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ context helpers

/** A chip's text for one context entry. */
function describeContext(key: keyof RunContext, c: RunContext, t: (k: string, v?: Record<string, string | number>) => string): { value: string; title: string } {
  if (key === 'selection' && c.selection) {
    const s = c.selection;
    return { value: s.start_line ? t('ag.ctx.lines', { a: s.start_line, b: s.end_line ?? s.start_line }) : s.text.slice(0, 32), title: s.text.slice(0, 600) };
  }
  const v = String(c[key] ?? '');
  return { value: key === 'extra' ? v.slice(0, 32) : v, title: v };
}

/** askAgent(prompt, context) passes an untyped record; keep what a run understands, the rest as a note. */
function toRunContext(c: Record<string, unknown> | undefined): RunContext | null {
  if (!c) return null;
  const out: RunContext = {};
  const rest: string[] = [];
  for (const [k, v] of Object.entries(c)) {
    if (v == null || v === '') continue;
    if (k === 'node_id' && typeof v === 'string') out.node_id = v;
    else if (k === 'file' && typeof v === 'string') out.file = v;
    else if (k === 'selection' && typeof v === 'object' && typeof (v as { text?: unknown }).text === 'string') out.selection = v as RunContext['selection'];
    else if (k === 'extra' && typeof v === 'string') rest.unshift(v);
    else rest.push(`${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`);
  }
  if (rest.length) out.extra = rest.join('\n');
  return Object.keys(out).length ? out : null;
}

/** What the current route points at: a map node, a document, a figure or an experiment. */
export function contextFromRoute(view: string, sub: string | null): RunContext | null {
  if (!sub) return null;
  if (view === 'dag' && !sub.includes(':')) return { node_id: sub.split('/')[0] };
  if (view === 'writing' && sub.startsWith(`${FIGURES}/`)) return { extra: `figure: ${sub.slice(FIGURES.length + 1)}` };
  if (view === 'writing' && sub !== FIGURES && (sub.includes('/') || /\.[A-Za-z0-9]{1,6}$/.test(sub))) return { file: sub };
  if (view === 'experiments' && !['runs', 'resources', 'plan'].includes(sub)) return { extra: `experiment: ${sub}` };
  return null;
}
