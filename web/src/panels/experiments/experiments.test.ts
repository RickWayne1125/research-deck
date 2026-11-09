// Pure parts of the Experiments log terminal: its colors from the real design tokens (both UI themes), the log
// stream client (resume offsets, reset, eof, reconnects), and the drawer's width.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clampDrawerWidth, DRAWER_DEFAULT, DRAWER_MIN, drawerMax, keyDrawerWidth, loadDrawerWidth, saveDrawerWidth } from './drawerWidth';
import { openLogStream, type EventSourceLike, type LogMeta, type LogPhase } from './logStream';
import { contrast, hex, luminance, mix, parseColor, terminalColors, type Rgb } from './termTheme';

// ---------------------------------------------------------------- colors

// tokens.css and the Radix tokens it imports, as text. Vitest blanks CSS imports (?raw too) and the web tsconfig has
// no Node types: hence an untyped dynamic import of node:fs.
const fsModule = 'node:fs';
const { readFileSync } = await import(/* @vite-ignore */ fsModule);
const tokensCss: string = readFileSync(new URL('../../styles/tokens.css', import.meta.url), 'utf8');
const radixCss: string = readFileSync(new URL('../../styles/vendor/radix-themes-tokens.css', import.meta.url), 'utf8');

/** The custom properties of every top-level block whose selector matches `selector`, later blocks winning. */
function blocks(css: string, selector: RegExp): Record<string, string> {
  const out: Record<string, string> = {};
  const re = new RegExp(selector.source, 'gm');
  for (let m = re.exec(css); m; m = re.exec(css)) {
    const start = m.index + m[0].length;
    const body = css.slice(start, css.indexOf('}', start));
    for (const d of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[d[1]] = d[2].trim();
  }
  return out;
}

/** Every token resolved to its final value, as the browser does on <html> for the default theme (Radix red: accent
 *  red, gray slate) in light or dark. */
function theme(mode: 'light' | 'dark'): Record<string, string> {
  const raw = {
    ...blocks(radixCss, /^:root, \.light, \.light-theme \{/),
    ...(mode === 'dark' ? blocks(radixCss, /^\.dark, \.dark-theme \{/) : {}),
    ...blocks(radixCss, /^:where\(\.radix-themes\) \{/),
    ...(mode === 'dark' ? blocks(radixCss, /^:is\(\.dark, \.dark-theme\),\s*:is\(\.dark, \.dark-theme\) :where\(\.radix-themes:not\(\.light, \.light-theme\)\) \{/) : {}),
    ...blocks(radixCss, /^\[data-accent-color='red'\] \{/),
    ...blocks(radixCss, /^\.radix-themes:where\(\[data-gray-color='slate'\]\) \{/),
    ...blocks(tokensCss, /^:root \{/),
    ...blocks(tokensCss, mode === 'dark' ? /^\.radix-themes\.dark \{/ : /^\.radix-themes\.light \{/),
  };
  const resolve = (v: string, depth = 0): string => (depth > 20 ? v
    : v.replace(/var\((--[\w-]+)(?:,\s*([^)]*))?\)/g, (_m, name: string, fallback?: string) =>
      (raw[name] !== undefined ? resolve(raw[name], depth + 1) : fallback ?? '')));
  return Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, resolve(v)]));
}
const light = theme('light');
const dark = theme('dark');

describe('terminal colors', () => {
  it('parses the token formats', () => {
    expect(parseColor('#fafaf7')).toEqual([250, 250, 247]);
    expect(parseColor(' #FFF ')).toEqual([255, 255, 255]);
    expect(parseColor('#11223344')).toEqual([17, 34, 51]);
    expect(parseColor('rgb(1, 2, 3)')).toEqual([1, 2, 3]);
    expect(parseColor('rgba(10 20 30 / .5)')).toEqual([10, 20, 30]);
    expect(parseColor('color-mix(in srgb, red, blue)')).toBeNull();
    expect(hex(mix([0, 0, 0], [255, 255, 255], 0.5))).toBe('#808080');
  });

  for (const [name, tokens] of [['light', light], ['dark', dark]] as const) {
    it(`is a dark, readable terminal in the ${name} UI theme`, () => {
      const c = terminalColors(tok => tokens[tok] ?? '');
      expect(c).not.toBeNull();
      const { theme } = c!;
      const rgb = (v: string | undefined) => parseColor(v ?? '') as Rgb;
      const ground = rgb(theme.background);
      expect(c!.darkUi).toBe(name === 'dark');
      expect(luminance(ground)).toBeLessThan(0.03);
      expect(contrast(rgb(theme.foreground), ground)).toBeGreaterThan(10);
      for (const k of ['red', 'green', 'yellow', 'blue', 'magenta', 'cyan'] as const) {
        const bright = `bright${k[0].toUpperCase()}${k.slice(1)}` as 'brightRed';
        expect(contrast(rgb(theme[k]), ground), k).toBeGreaterThanOrEqual(4.5);
        expect(contrast(rgb(theme[bright]), ground), bright).toBeGreaterThan(contrast(rgb(theme[k]), ground));
      }
      expect(contrast(rgb(theme.brightBlack), ground)).toBeGreaterThanOrEqual(3.5);
      expect(theme.cursor).toBe(theme.background);                        // read-only: the cursor stays invisible
      expect(c!.match).toMatch(/^#[0-9a-f]{6}$/);                          // the search addon wants #RRGGBB
      expect(c!.activeMatch).toMatch(/^#[0-9a-f]{6}$/);
    });
  }

  it('derives every color from the tokens', () => {
    const c = terminalColors(tok => dark[tok] ?? '')!;
    expect(c.theme.background).toBe(dark['--solid-paper']);
    expect(c.theme.foreground).toBe(dark['--ink']);
    expect(c.theme.red).toBe(dark['--accent']);                          // already readable on the dark paper
    const l = terminalColors(tok => light[tok] ?? '')!;
    expect(l.theme.background).toBe(light['--ink-strong']);
    expect(terminalColors(tok => (tok === '--ok' ? '' : light[tok]))).toBeNull();
  });
});

// ---------------------------------------------------------------- the log stream client

class FakeSource implements EventSourceLike {
  static made: FakeSource[] = [];
  readyState = 0;
  onerror: ((ev: Event) => unknown) | null = null;
  closed = false;
  private listeners = new Map<string, ((ev: MessageEvent) => void)[]>();

  constructor(public url: string) { FakeSource.made.push(this); }
  addEventListener(type: string, fn: (ev: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() { this.closed = true; this.readyState = 2; }
  emit(type: string, data: unknown = {}) {
    for (const fn of this.listeners.get(type) ?? []) fn({ data: JSON.stringify(data) } as MessageEvent);
  }
  fail(givesUp: boolean) { this.readyState = givesUp ? 2 : 0; this.onerror?.(new Event('error')); }
}

function recorder() {
  const seen: { phases: LogPhase[]; data: [string, number][]; resets: number; metas: LogMeta[]; eof: unknown[]; notices: string[] } =
    { phases: [], data: [], resets: 0, metas: [], eof: [], notices: [] };
  return {
    seen,
    handlers: {
      meta: (m: LogMeta) => seen.metas.push(m), data: (text: string, at: number) => seen.data.push([text, at]),
      reset: () => { seen.resets += 1; }, eof: (e: unknown) => seen.eof.push(e), notice: (m: string) => seen.notices.push(m),
      phase: (p: LogPhase) => seen.phases.push(p),
    },
  };
}

describe('log stream client', () => {
  afterEach(() => { FakeSource.made = []; vi.useRealTimers(); });
  const open = (handlers: ReturnType<typeof recorder>['handlers'], offset?: number) => openLogStream(
    { url: at => `/stream?offset=${at}`, offset, create: url => new FakeSource(url), delays: [100, 500] }, handlers);

  it('follows offsets through data and reset, and stops at eof', () => {
    const { seen, handlers } = recorder();
    const s = open(handlers);
    const es = FakeSource.made[0];
    expect(es.url).toBe('/stream?offset=-1');                             // the tail
    es.emit('meta', { source: 'file', live: true, path: 'run.log', missing: false });
    es.emit('data', { data: 'epoch 1\n', offset: 8 });
    es.emit('notice', { message: 'source down' });
    expect(s.offset()).toBe(8);
    es.emit('reset', { offset: 0 });
    expect(s.offset()).toBe(0);
    es.emit('data', { data: 'new\n', offset: 4 });
    es.emit('eof', { offset: 4, status: 'succeeded' });
    expect(es.closed).toBe(true);
    es.emit('data', { data: 'late', offset: 9 });                         // nothing after eof
    expect(seen.phases).toEqual(['connecting', 'open', 'ended']);
    expect(seen.data).toEqual([['epoch 1\n', 8], ['new\n', 4]]);
    expect(seen.resets).toBe(1);
    expect(seen.notices).toEqual(['source down']);
    expect(seen.eof).toEqual([{ offset: 4, status: 'succeeded' }]);
    expect(seen.metas[0].path).toBe('run.log');
  });

  it('lets the browser reconnect, and reconnects itself from the last offset when the browser gives up', () => {
    vi.useFakeTimers();
    const { seen, handlers } = recorder();
    const s = open(handlers, 120);
    const first = FakeSource.made[0];
    expect(first.url).toBe('/stream?offset=120');
    first.emit('meta', { source: 'file', live: true });
    first.emit('data', { data: 'x', offset: 121 });
    first.fail(false);                                                    // EventSource retries with Last-Event-ID
    expect(FakeSource.made).toHaveLength(1);
    first.fail(true);                                                     // an HTTP error: it gave up
    expect(first.closed).toBe(true);
    vi.advanceTimersByTime(99);
    expect(FakeSource.made).toHaveLength(1);
    vi.advanceTimersByTime(1);
    const second = FakeSource.made[1];
    expect(second.url).toBe('/stream?offset=121');
    first.emit('data', { data: 'stale', offset: 999 });                   // the old connection no longer counts
    second.fail(true);
    vi.advanceTimersByTime(500);                                          // the pauses grow
    const third = FakeSource.made[2];
    expect(third.url).toBe('/stream?offset=121');
    third.emit('meta', { source: 'file', live: true });
    expect(seen.phases).toEqual(['connecting', 'open', 'retrying', 'retrying', 'retrying', 'retrying', 'retrying', 'open']);
    expect(seen.data).toEqual([['x', 121]]);
    third.fail(true);
    s.close();                                                            // closing cancels the pending reconnect
    vi.advanceTimersByTime(10_000);
    expect(FakeSource.made).toHaveLength(3);
  });
});

// ---------------------------------------------------------------- drawer width

describe('drawer width', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('stays within the panel', () => {
    expect(clampDrawerWidth(100, 1200)).toBe(DRAWER_MIN);
    expect(clampDrawerWidth(5000, 1200)).toBe(drawerMax(1200));
    expect(drawerMax(1200)).toBeLessThan(1200);
    expect(clampDrawerWidth(700.4, 1200)).toBe(700);
    expect(drawerMax(200)).toBe(DRAWER_MIN);                              // a narrow panel: the drawer covers it (CSS caps at 100%)
  });

  it('answers the keyboard like a splitter on its left edge', () => {
    expect(keyDrawerWidth('ArrowLeft', false, 560, 1200)).toBe(584);     // ← widens
    expect(keyDrawerWidth('ArrowRight', true, 560, 1200)).toBe(464);
    expect(keyDrawerWidth('Home', false, 560, 1200)).toBe(DRAWER_MIN);
    expect(keyDrawerWidth('End', false, 560, 1200)).toBe(drawerMax(1200));
    expect(keyDrawerWidth('Enter', false, 900, 1200)).toBe(DRAWER_DEFAULT);
    expect(keyDrawerWidth('a', false, 560, 1200)).toBeNull();
  });

  it('is remembered, and forgotten on reset', () => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); },
      removeItem: (k: string) => { store.delete(k); },
    });
    expect(loadDrawerWidth()).toBe(DRAWER_DEFAULT);
    saveDrawerWidth(733.6);
    expect(loadDrawerWidth()).toBe(734);
    saveDrawerWidth(null);
    expect(loadDrawerWidth()).toBe(DRAWER_DEFAULT);
    store.set('rd.ex.drawerWidth', 'garbage');
    expect(loadDrawerWidth()).toBe(DRAWER_DEFAULT);
  });
});
