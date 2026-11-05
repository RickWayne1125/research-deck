// Follow an agent run that a coding endpoint started (/coding/review, /coding/explain return RunStarted themselves,
// so useAgentRun, which starts its own run, does not fit). The stream replays from the start, so attaching to a run
// that is already going (after a reload or a tab switch) rebuilds the same text.
import { useCallback, useEffect, useRef, useState } from 'react';
import { post, streamRun } from '../../api/client';
import type { AgentEvent } from '../../types';
import type { Started } from './api';

export interface RunMeta { provider: string; model: string; effort: string; fast: boolean }
export interface FollowState {
  runId: string | null;
  status: 'idle' | 'starting' | 'running' | 'done' | 'error' | 'cancelled';
  text: string;
  error: string | null;
  meta: RunMeta | null;
  tool: string | null;          // the last tool the agent used ("Read src/x.py")
  startedAt: number | null;
  durationMs: number | null;
}

const IDLE: FollowState = { runId: null, status: 'idle', text: '', error: null, meta: null, tool: null, startedAt: null, durationMs: null };

function reduce(s: FollowState, e: AgentEvent): FollowState {
  switch (e.type) {
    case 'start': return { ...s, meta: { provider: e.provider, model: e.model, effort: e.effort, fast: e.fast } };
    case 'text': return { ...s, text: s.text + e.delta };
    case 'tool': return { ...s, tool: [e.name, e.detail].filter(Boolean).join(' ') };
    case 'error': return { ...s, error: e.message };
    case 'done': return { ...s, text: e.text || s.text, durationMs: e.duration_ms, status: e.cancelled ? 'cancelled' : e.ok ? 'done' : 'error' };
    default: return s;
  }
}

export interface RunOutcome { text: string; ok: boolean; cancelled: boolean; error: string | null }

export function useFollowRun(onDone?: (outcome: RunOutcome) => void) {
  const [state, setState] = useState<FollowState>(IDLE);
  const off = useRef<(() => void) | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => () => off.current?.(), []);

  const attach = useCallback((runId: string, meta?: RunMeta | null, startedAt?: number) => {
    off.current?.();
    setState({ ...IDLE, runId, status: 'running', meta: meta ?? null, startedAt: startedAt ?? Date.now() });
    let lastError: string | null = null;
    off.current = streamRun(runId, (e) => {
      setState(s => reduce(s, e));
      if (e.type === 'error') lastError = e.message;
      if (e.type === 'done') done.current?.({ text: e.text, ok: e.ok && !e.cancelled, cancelled: !!e.cancelled, error: lastError });
    });
  }, []);

  /** Call an endpoint that starts a run, then follow it. Resolves with RunStarted (null when the call failed). */
  const start = useCallback(async (call: () => Promise<Started>): Promise<Started | null> => {
    off.current?.();
    setState({ ...IDLE, status: 'starting', startedAt: Date.now() });
    try {
      const r = await call();
      attach(r.run_id, { provider: r.provider, model: r.model, effort: r.effort, fast: r.fast });
      return r;
    } catch (e) {
      setState(s => ({ ...s, status: 'error', error: String((e as Error)?.message ?? e) }));
      return null;
    }
  }, [attach]);

  const cancel = useCallback(() => {
    if (state.runId) post(`/api/agent/runs/${encodeURIComponent(state.runId)}/cancel`).catch(() => { /* already finished */ });
  }, [state.runId]);

  const reset = useCallback(() => { off.current?.(); off.current = null; setState(IDLE); }, []);

  return { ...state, start, attach, cancel, reset, running: state.status === 'starting' || state.status === 'running' };
}

export type FollowRun = ReturnType<typeof useFollowRun>;
