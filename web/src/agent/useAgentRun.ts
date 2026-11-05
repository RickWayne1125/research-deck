// Start an agent run and follow its stream. Every panel uses this for AI actions (review, explain, figure edits),
// and the agent dock uses it for chat. The run goes to the panel's bound session unless `ephemeral` is set.
import { useCallback, useEffect, useRef, useState } from 'react';
import { p, post, streamRun } from '../api/client';
import type { AgentEvent, RunRequest, RunStarted } from '../types';

export interface AgentRunState {
  runId: string | null;
  status: 'idle' | 'running' | 'done' | 'error' | 'cancelled';
  text: string;
  events: AgentEvent[];
  error: string | null;
  meta: RunStarted | null;
  sessionId: string | null;
}

const IDLE: AgentRunState = { runId: null, status: 'idle', text: '', events: [], error: null, meta: null, sessionId: null };

export function useAgentRun(projectId: string | null) {
  const [state, setState] = useState<AgentRunState>(IDLE);
  const off = useRef<(() => void) | null>(null);
  useEffect(() => () => off.current?.(), []);

  /** Start a run; resolves with the final text when it finishes (rejects on error). */
  const start = useCallback((req: RunRequest, onEvent?: (e: AgentEvent) => void): Promise<string> => {
    if (!projectId) return Promise.reject(new Error('no project'));
    off.current?.();
    setState({ ...IDLE, status: 'running' });
    return post<RunStarted>(p(projectId, '/agent/run'), req).then(meta => new Promise<string>((resolve, reject) => {
      setState(s => ({ ...s, runId: meta.run_id, meta, sessionId: meta.session_id }));
      off.current = streamRun(meta.run_id, (e) => {
        onEvent?.(e);
        setState(s => {
          const next: AgentRunState = { ...s, events: [...s.events, e] };
          if (e.type === 'text') next.text = s.text + e.delta;
          if (e.type === 'session') next.sessionId = e.session_id;
          if (e.type === 'error') next.error = e.message;
          if (e.type === 'done') {
            next.text = e.text || next.text;
            next.status = e.cancelled ? 'cancelled' : e.ok ? 'done' : 'error';
          }
          return next;
        });
        if (e.type === 'done') (e.ok ? resolve(e.text) : reject(new Error(e.cancelled ? 'cancelled' : 'agent failed')));
      });
    }), (err) => { setState(s => ({ ...s, status: 'error', error: String(err.message || err) })); throw err; });
  }, [projectId]);

  /** Follow a run that another endpoint started (e.g. /coding/review, /figures/{id}/ai-edit return RunStarted). */
  const attach = useCallback((meta: RunStarted, onEvent?: (e: AgentEvent) => void): Promise<string> => {
    off.current?.();
    setState({ ...IDLE, status: 'running', runId: meta.run_id, meta, sessionId: meta.session_id });
    return new Promise<string>((resolve, reject) => {
      off.current = streamRun(meta.run_id, (e) => {
        onEvent?.(e);
        setState(s => {
          const next: AgentRunState = { ...s, events: [...s.events, e] };
          if (e.type === 'text') next.text = s.text + e.delta;
          if (e.type === 'session') next.sessionId = e.session_id;
          if (e.type === 'error') next.error = e.message;
          if (e.type === 'done') { next.text = e.text || next.text; next.status = e.cancelled ? 'cancelled' : e.ok ? 'done' : 'error'; }
          return next;
        });
        if (e.type === 'done') (e.ok ? resolve(e.text) : reject(new Error(e.cancelled ? 'cancelled' : 'agent failed')));
      });
    });
  }, []);

  const cancel = useCallback(() => {
    if (state.runId) post(`/api/agent/runs/${state.runId}/cancel`).catch(() => {});
  }, [state.runId]);

  const reset = useCallback(() => { off.current?.(); setState(IDLE); }, []);

  return { ...state, start, attach, cancel, reset };
}

/** Extract the first fenced code block (optionally of a language) from an agent's answer. */
export function extractFence(text: string, lang?: string): string | null {
  const re = lang ? new RegExp('```' + lang + '[^\\n]*\\n([\\s\\S]*?)```') : /```[^\n]*\n([\s\S]*?)```/;
  const m = text.match(re);
  return m ? m[1].replace(/\n$/, '') : null;
}

/** Parse JSON the agent was asked to return: a fenced ```json block, a bare object/array, or JSON lines. */
export function extractJson<T = unknown>(text: string): T | null {
  const fenced = extractFence(text, 'json') ?? extractFence(text);
  for (const candidate of [fenced, text]) {
    if (!candidate) continue;
    const s = candidate.trim();
    try { return JSON.parse(s) as T; } catch { /* try next */ }
    const start = s.search(/[[{]/), end = Math.max(s.lastIndexOf('}'), s.lastIndexOf(']'));
    if (start >= 0 && end > start) { try { return JSON.parse(s.slice(start, end + 1)) as T; } catch { /* next */ } }
  }
  const lines = text.split('\n').map(l => l.trim()).filter(l => l.startsWith('{') && l.endsWith('}'));
  if (lines.length) { try { return lines.map(l => JSON.parse(l)) as T; } catch { /* give up */ } }
  return null;
}
