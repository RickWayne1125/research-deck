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

let renewing: Promise<unknown> | null = null;
/** The researcher's session cookie lives as long as one server process (actors.py): after a restart (a redeploy) the
 *  page asks for a new one, once for all requests waiting on it. */
function renewSession(): Promise<unknown> {
  renewing ??= fetch('/api/session', { headers: { 'X-RD-Request': '1' } }).catch(() => null).finally(() => { renewing = null; });
  return renewing;
}

type Opts = { method?: string; body?: unknown; query?: Query; signal?: AbortSignal };

export async function api<T>(path: string, opts: Opts = {}, retried = false): Promise<T> {
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
  if (res.status === 403 && !retried && path !== '/api/session') {   // refused: maybe only the cookie is stale
    await renewSession();
    return api<T>(path, opts, true);
  }
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

/** The server sends a ping on every stream at least every 15 s. A stream silent for longer than this is half open (a
 *  proxy that outlived a server restart, a laptop that slept, a phone that changed networks): reopen it. */
const QUIET_MS = 40000;

/** Call `reopen` when the stream has been quiet for QUIET_MS; `heard()` on every message. Returns stop. */
function watchdog(reopen: () => void): { heard: () => void; stop: () => void } {
  let last = Date.now();
  const timer = window.setInterval(() => { if (Date.now() - last > QUIET_MS) { last = Date.now(); reopen(); } }, 5000);
  return { heard: () => { last = Date.now(); }, stop: () => window.clearInterval(timer) };
}

/** Live project events (topics: dag, outline, file, sessions, agent, queue, experiments, figures, writing, project,
 *  survey; and hello on every (re)connection: a page catches up on what it may have missed). Returns unsubscribe. */
export function subscribeEvents(projectId: string, onEvent: (e: ProjectEvent) => void): () => void {
  const topics = ['dag', 'outline', 'file', 'sessions', 'agent', 'queue', 'experiments', 'figures', 'writing', 'project', 'survey'];
  let es: EventSource | null = null;
  let timer = 0;
  let delay = 1000;
  let closed = false;
  // EventSource retries a dropped connection by itself, but gives up for good after an HTTP error (a proxy's 502
  // while the server restarts). Then open a new one, backing off up to 15 s.
  const open = () => {
    es?.close();
    es = new EventSource(withQuery('/api/events', { project: projectId }));
    const handler = (ev: MessageEvent) => { dog.heard(); try { onEvent(JSON.parse(ev.data)); } catch { /* ignore */ } };
    topics.forEach(t => es!.addEventListener(t, handler));
    es.addEventListener('ping', () => dog.heard());
    es.addEventListener('hello', () => { dog.heard(); delay = 1000; onEvent({ topic: 'hello', project: projectId, payload: null }); });
    es.onerror = () => {
      if (closed || !es || es.readyState !== EventSource.CLOSED) return;
      timer = window.setTimeout(() => { if (!closed) open(); }, delay);
      delay = Math.min(delay * 2, 15000);
    };
  };
  const dog = watchdog(() => { if (!closed) open(); });
  open();
  return () => { closed = true; dog.stop(); window.clearTimeout(timer); es?.close(); };
}

/** Stream an agent run's events (replayed from the start, then live) until `done`. A run outlives the server (a
 *  redeploy): the stream comes back by itself, and a `reset` event says to drop what came before, as the new server
 *  replays the run. `onGone`: the server no longer knows the run (it ended before a restart). Returns unsubscribe. */
export function streamRun(runId: string, onEvent: (e: AgentEvent) => void, opts: { onGone?: () => void } = {}): () => void {
  const base = `/api/agent/runs/${encodeURIComponent(runId)}`;
  let es: EventSource | null = null;
  let last = '';
  let closed = false;
  let timer = 0;
  let delay = 1000;
  const open = () => {
    es?.close();
    es = new EventSource(last ? `${base}/stream?last=${encodeURIComponent(last)}` : `${base}/stream`);
    es.addEventListener('ping', () => dog.heard());
    es.addEventListener('agent', (ev: MessageEvent) => {
      dog.heard();
      if (ev.lastEventId) last = ev.lastEventId;
      delay = 1000;
      let e: AgentEvent;
      try { e = JSON.parse(ev.data) as AgentEvent; } catch { return; }
      onEvent(e);
      if (e.type === 'done') { closed = true; dog.stop(); es?.close(); }
    });
    // EventSource reconnects by itself after a dropped connection, sending the last id (the server goes on after it).
    // After an HTTP error (a proxy's 502 while the server restarts) it gives up: open a new one, backing off up to 15 s.
    es.onerror = () => {
      if (closed || !es || es.readyState !== EventSource.CLOSED) return;
      timer = window.setTimeout(async () => {
        if (closed) return;
        try { await api(base); } catch (err) {
          if (err instanceof ApiError && err.status === 404) { closed = true; dog.stop(); opts.onGone?.(); return; }
        }
        if (!closed) open();
      }, delay);
      delay = Math.min(delay * 2, 15000);
    };
  };
  const dog = watchdog(() => { if (!closed) open(); });   // a reopened stream goes on after the last event it had
  open();
  return () => { closed = true; dog.stop(); window.clearTimeout(timer); es?.close(); };
}
