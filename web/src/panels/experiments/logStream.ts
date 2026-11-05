// Client of GET …/experiments/{eid}/logs/stream (server/research_deck/experiments/logstream.py): an EventSource that
// resumes after the last byte it was given. A dropped connection is resumed by the browser itself (Last-Event-ID is
// the last data event's byte offset); when the browser gives up (an HTTP error, a restarted server) a new
// EventSource starts from that offset after a growing pause.

export interface LogMeta {
  source: 'file' | 'none'; live: boolean; path?: string; missing?: boolean;
  size?: number; start?: number; truncated_before?: boolean;
}
export interface LogEof { offset: number; status: string }
/** connecting: the first request; open: events arrive; retrying: reconnecting; ended: eof (or closed). */
export type LogPhase = 'connecting' | 'open' | 'retrying' | 'ended';

export interface LogStreamHandlers {
  meta(m: LogMeta): void;
  data(text: string, offset: number): void;
  /** The file shrank or was replaced: what was shown is gone; data starts again at byte 0. */
  reset(): void;
  eof(e: LogEof): void;
  notice(message: string): void;
  phase(p: LogPhase): void;
}

/** The part of EventSource this client uses (tests pass a fake). */
export interface EventSourceLike {
  readonly readyState: number;
  onerror: ((ev: Event) => unknown) | null;
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void;
  close(): void;
}
export type EventSourceFactory = (url: string) => EventSourceLike;

export interface LogStreamOptions {
  url: (offset: number) => string;
  /** Where to start: a byte offset, or -1 for the tail. */
  offset?: number;
  create?: EventSourceFactory;
  /** Pauses (ms) before the 1st, 2nd, … new connection after the browser gave up; the last one repeats. */
  delays?: number[];
}

const CLOSED = 2;     // EventSource.CLOSED
export const RETRY_DELAYS = [1000, 2000, 5000, 10_000, 15_000];

export interface LogStreamHandle { close(): void; offset(): number }

export function openLogStream(opts: LogStreamOptions, on: LogStreamHandlers): LogStreamHandle {
  const create = opts.create ?? ((url: string) => new EventSource(url));
  const delays = opts.delays?.length ? opts.delays : RETRY_DELAYS;
  let at = opts.offset ?? -1;           // where a new connection resumes
  let es: EventSourceLike | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let failures = 0;
  let done = false;

  const json = (ev: MessageEvent): Record<string, unknown> | null => {
    try { return JSON.parse(ev.data); } catch { return null; }
  };

  const connect = () => {
    if (done) return;
    on.phase(failures ? 'retrying' : 'connecting');
    const src = create(opts.url(at));
    es = src;
    const mine = () => es === src && !done;
    src.addEventListener('meta', ev => {
      const m = json(ev);
      if (!mine() || !m) return;
      failures = 0;
      on.phase('open');
      on.meta(m as unknown as LogMeta);
    });
    src.addEventListener('data', ev => {
      const d = json(ev);
      if (!mine() || !d || typeof d.data !== 'string' || typeof d.offset !== 'number') return;
      at = d.offset;
      on.data(d.data, d.offset);
    });
    src.addEventListener('reset', () => {
      if (!mine()) return;
      at = 0;
      on.reset();
    });
    src.addEventListener('notice', ev => {
      const d = json(ev);
      if (mine() && typeof d?.message === 'string') on.notice(d.message);
    });
    src.addEventListener('eof', ev => {
      if (!mine()) return;
      const d = json(ev);
      if (typeof d?.offset === 'number') at = d.offset;
      done = true;
      src.close();
      es = null;
      on.phase('ended');
      on.eof({ offset: at, status: typeof d?.status === 'string' ? d.status : 'unknown' });
    });
    src.onerror = () => {
      if (!mine()) return;
      if (src.readyState !== CLOSED) { on.phase('retrying'); return; }   // the browser reconnects (Last-Event-ID)
      src.close();
      es = null;
      const wait = delays[Math.min(failures, delays.length - 1)];
      failures += 1;
      on.phase('retrying');
      timer = setTimeout(connect, wait);
    };
  };

  connect();
  return {
    close() {
      done = true;
      clearTimeout(timer);
      es?.close();
      es = null;
    },
    offset: () => at,
  };
}
