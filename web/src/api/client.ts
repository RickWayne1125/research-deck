// The one HTTP client every panel uses. Paths are those of docs/API.md; the Vite dev server proxies /api to :8765.
import type { AgentEvent, ProjectEvent } from '../types';

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : (detail as { message?: string })?.message ?? `HTTP ${status}`);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&');
  return qs ? `${path}${path.includes('?') ? '&' : '?'}${qs}` : path;
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown; query?: Query; signal?: AbortSignal } = {}): Promise<T> {
  const res = await fetch(withQuery(path, opts.query), {
    method: opts.method ?? 'GET',
    // X-RD-Request marks the dashboard's own requests; the server refuses mutations without it (CSRF guard).
    headers: { 'X-RD-Request': '1', ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });
  const text = await res.text();
  let data: unknown = null;
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!res.ok) throw new ApiError(res.status, (data as { detail?: unknown })?.detail ?? data);
  return data as T;
}

export const get = <T>(path: string, query?: Query, signal?: AbortSignal) => api<T>(path, { query, signal });
export const post = <T>(path: string, body?: unknown, query?: Query) => api<T>(path, { method: 'POST', body: body ?? {}, query });
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body: body ?? {} });
export const patch = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PATCH', body: body ?? {} });
export const del = <T>(path: string, query?: Query) => api<T>(path, { method: 'DELETE', query });

/** Project-scoped path helper: p('demo', '/writing/docs') -> /api/projects/demo/writing/docs */
export const p = (projectId: string, rest: string) => `/api/projects/${encodeURIComponent(projectId)}${rest}`;

/** Live project events (topics: dag, outline, file, sessions, agent, experiments, figures, writing, project, survey). Returns unsubscribe. */
export function subscribeEvents(projectId: string, onEvent: (e: ProjectEvent) => void): () => void {
  const topics = ['dag', 'outline', 'file', 'sessions', 'agent', 'experiments', 'figures', 'writing', 'project', 'survey'];
  const handler = (ev: MessageEvent) => { try { onEvent(JSON.parse(ev.data)); } catch { /* ignore */ } };
  let es: EventSource | null = null;
  let timer = 0;
  let delay = 1000;
  let closed = false;
  // EventSource retries a dropped connection by itself, but gives up for good after an HTTP error (a proxy's 502
  // while the server restarts). Then open a new one, backing off up to 15 s.
  const open = () => {
    es = new EventSource(withQuery('/api/events', { project: projectId }));
    topics.forEach(t => es!.addEventListener(t, handler));
    es.addEventListener('hello', () => { delay = 1000; });
    es.onerror = () => {
      if (closed || !es || es.readyState !== EventSource.CLOSED) return;
      timer = window.setTimeout(() => { if (!closed) open(); }, delay);
      delay = Math.min(delay * 2, 15000);
    };
  };
  open();
  return () => { closed = true; window.clearTimeout(timer); es?.close(); };
}

/** Stream an agent run's events (replayed from the start, then live) until `done`. Returns unsubscribe. */
export function streamRun(runId: string, onEvent: (e: AgentEvent) => void): () => void {
  const es = new EventSource(`/api/agent/runs/${encodeURIComponent(runId)}/stream`);
  es.addEventListener('agent', (ev: MessageEvent) => {
    try {
      const e = JSON.parse(ev.data) as AgentEvent;
      onEvent(e);
      if (e.type === 'done') es.close();
    } catch { /* ignore */ }
  });
  es.onerror = () => { /* EventSource retries; the server replays from the start, so a gap is harmless */ };
  return () => es.close();
}
