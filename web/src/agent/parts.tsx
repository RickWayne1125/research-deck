// Small pieces the conversation, the navigation and Settings share: provider marks, labels, copy buttons, the
// sessions hook and the "is an answer being written" store.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useApp } from '../state/app';
import { useT } from '../i18n';
import { Icon } from '../components/icons';
import type { AgentCatalog, ModelInfo, PanelBinding, PanelId, ProviderId, ProviderSession, SessionsDoc } from '../types';
import { agentApi, type BindingChange } from './api';
import './i18n';

export const PROVIDERS: ProviderId[] = ['claude', 'codex'];

const GLYPHS: Record<string, string> = {
  claude: 'M8 2.2v11.6M2.2 8h11.6M3.9 3.9l8.2 8.2M12.1 3.9l-8.2 8.2',
  codex: 'M8 1.8l5.4 3.1v6.2L8 14.2l-5.4-3.1V4.9zM5.7 6.6L7.3 8l-1.6 1.4M8.6 9.6h1.9',
  fake: 'M8 2.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11zM6 7v.01M10 7v.01M5.8 10.2c1.3 1 3.1 1 4.4 0',
  copy: 'M5.5 5.5h8v8h-8zM3 10.5h-.5v-8h8V3',
};

/** A small glyph (not a logo) that tells the two backends apart, tinted per provider through the tokens. */
export function ProviderMark({ provider, size = 14 }: { provider: string; size?: number }) {
  const kind = provider === 'claude' || provider === 'codex' ? provider : 'fake';
  return (
    <svg className={`ag-mark ${kind}`} viewBox="0 0 16 16" width={size} height={size} aria-hidden="true" fill="none"
      stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round"><path d={GLYPHS[kind]} /></svg>
  );
}

export function providerLabel(provider: string | null | undefined, t: (k: string) => string): string {
  return t(`ag.provider.${provider === 'claude' || provider === 'codex' ? provider : 'fake'}`);
}

export function modelsOf(catalog: AgentCatalog | null, provider: ProviderId): ModelInfo[] {
  return catalog?.providers.find(p => p.id === provider)?.models ?? [];
}

export function modelInfo(catalog: AgentCatalog | null, provider: string, model: string | null | undefined): ModelInfo | undefined {
  if (provider === 'claude' || provider === 'codex') return modelsOf(catalog, provider).find(m => m.id === model);
  // the fake agent answers under the bound model's name
  return catalog?.providers.flatMap(p => p.models).find(m => m.id === model);
}

export function modelLabel(catalog: AgentCatalog | null, provider: string, model: string | null | undefined): string {
  return modelInfo(catalog, provider, model)?.label ?? model ?? '';
}

export function shortId(id: string | null | undefined): string { return id ? id.slice(0, 8) : ''; }

/** Write text to the clipboard (with a fallback for pages without clipboard permission). */
export async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall back */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch { return false; }
}

/** An icon button that copies `text` and briefly shows a check. */
export function CopyButton({ text, label, disabled, size = 'icon' }: { text: string; label: string; disabled?: boolean; size?: 'icon' | 'sm' }) {
  const t = useT();
  const [done, setDone] = useState(false);
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const onClick = async () => {
    if (await copyText(text)) {
      setDone(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setDone(false), 1400);
    }
  };
  const glyph = done ? <Icon name="check" /> : <svg viewBox="0 0 16 16" width={16} height={16} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round"><path d={GLYPHS.copy} /></svg>;
  if (size === 'sm') {
    return <button type="button" className="btn sm" onClick={onClick} disabled={disabled} title={label}>{glyph}{done ? t('common.copied') : t('common.copy')}</button>;
  }
  return <button type="button" className="icon-btn" onClick={onClick} disabled={disabled} aria-label={label} title={done ? t('common.copied') : label}>{glyph}</button>;
}

// ------------------------------------------------------------------ sessions

export interface ResolvedBinding {
  entry: PanelBinding;     // the conversation's entry (one session per backend)
  provider: ProviderId;    // the active backend
  session: ProviderSession;
}

/** The project conversation's binding (every view talks to it; agents/sessions.py). */
export function resolveBinding(doc: SessionsDoc | null, _panel: PanelId = 'project'): ResolvedBinding | null {
  const entry = doc?.panels.project;
  if (!entry) return null;
  return { entry, provider: entry.active, session: entry[entry.active] };
}

/** The project's session bindings, kept live through the "sessions" topic. */
export function useSessions(pid: string | null) {
  const { onEvent } = useApp();
  const [doc, setDoc] = useState<SessionsDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    if (!pid) return;
    agentApi.sessions(pid).then(d => { setDoc(d); setError(null); }).catch(e => setError(String(e?.message ?? e)));
  }, [pid]);
  useEffect(() => { setDoc(null); load(); }, [load]);
  useEffect(() => onEvent('sessions', (e) => {
    if (e.payload && typeof e.payload === 'object' && 'panels' in e.payload) setDoc(e.payload as SessionsDoc);
    else load();
  }), [onEvent, load]);
  const update = useCallback(async (panel: PanelId, change: BindingChange) => {
    if (!pid) throw new Error('no project');
    const entry = await agentApi.bind(pid, panel, change);
    setDoc(d => (d ? { ...d, panels: { ...d.panels, [panel]: entry } } : d));
    return entry;
  }, [pid]);
  return { doc, error, reload: load, update, setDoc };
}

// ------------------------------------------------------------------ which panels have a run going

const localRuns = new Map<string, number>();     // `${pid}:${panel}` -> runs the dock started that are still going
const listeners = new Set<() => void>();
let version = 0;

/** The dock reports its own runs here so the chip lights up at once (other panels' runs are polled). */
export function markRunning(pid: string, panel: PanelId, running: boolean): void {
  const key = `${pid}:${panel}`;
  const n = Math.max(0, (localRuns.get(key) ?? 0) + (running ? 1 : -1));
  if (n) localRuns.set(key, n); else localRuns.delete(key);
  version++;
  listeners.forEach(fn => fn());
}

function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }

/** Panels (owners) with a run in progress: the dock's own runs at once, every other run within a few seconds. */
export function useRunningPanels(pid: string | null): Set<PanelId> {
  useSyncExternalStore(subscribe, () => version);
  const [polled, setPolled] = useState<Set<PanelId>>(new Set());
  useEffect(() => {
    if (!pid) return;
    let alive = true, timer = 0;
    const tick = async () => {
      let next = new Set<PanelId>();
      if (document.visibilityState === 'visible') {
        try { next = new Set((await agentApi.runs(pid)).filter(r => r.status === 'running').map(r => r.panel)); } catch { /* offline */ }
        if (alive) setPolled(prev => (sameSet(prev, next) ? prev : next));
      }
      if (alive) timer = window.setTimeout(tick, next.size ? 2500 : 6000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [pid]);
  const out = new Set(polled);
  if (pid) for (const key of localRuns.keys()) if (key.startsWith(`${pid}:`)) out.add(key.slice(pid.length + 1) as PanelId);
  return out;
}

function sameSet<T>(a: Set<T>, b: Set<T>): boolean {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}
