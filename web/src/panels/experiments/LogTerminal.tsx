// The run's log as a read-only terminal (xterm.js), fed by GET …/logs/stream (logStream.ts): colors, carriage-return
// progress bars and partial lines show as the run wrote them. Toolbar: live state, Follow (scrolling up pauses it),
// search, copy all, download (…/logs/raw), text size, and an expanded view over the panel (Esc closes it). The
// colors come from the design tokens (termTheme.ts) and follow the UI theme.
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { SearchAddon, type ISearchOptions } from '@xterm/addon-search';
import '@xterm/xterm/css/xterm.css';
import { Button, IconButton, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useT } from '../../i18n';
import { exApi } from './api';
import { openLogStream, type LogMeta, type LogPhase } from './logStream';
import { terminalColors, type TermColors } from './termTheme';

const FONT_KEY = 'rd.ex.termFont';
const FONT_MIN = 9;
const FONT_MAX = 20;
const FONT_DEFAULT = 12;
const SCROLLBACK = 10_000;
const SEARCH_LIMIT = 2000;      // highlighted matches at most

const rootStyle = () => getComputedStyle(document.documentElement);
const readColors = () => terminalColors(name => rootStyle().getPropertyValue(name));
const monoFont = () => rootStyle().getPropertyValue('--mono').trim() || 'monospace';

function loadFont(): number {
  try {
    const v = Number(localStorage.getItem(FONT_KEY));
    return v >= FONT_MIN && v <= FONT_MAX ? v : FONT_DEFAULT;
  } catch { return FONT_DEFAULT; }
}

/** Expand / collapse, drawn like components/icons.tsx (16 px grid, 1.5 px stroke), which has neither. */
function ExpandIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg viewBox="0 0 16 16" width={16} height={16} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={1.5}
      strokeLinecap="round" strokeLinejoin="round">
      <path d={expanded ? 'M6 2.5V6H2.5M10 2.5V6h3.5M13.5 10H10v3.5M2.5 10H6v3.5' : 'M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10'} />
    </svg>
  );
}

export function LogTerminal({ pid, eid, title, live }: { pid: string; eid: string; title: string; live: boolean }) {
  const t = useT();
  const [phase, setPhase] = useState<LogPhase>('connecting');
  const [meta, setMeta] = useState<LogMeta | null>(null);
  const [hasData, setHasData] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [fontSize, setFontSize] = useState(loadFont);
  const [colors, setColors] = useState<TermColors | null>(readColors);
  const [portal, setPortal] = useState<HTMLElement | null>(null);     // set while expanded: the panel body
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<{ index: number; count: number } | null>(null);
  const [copied, setCopied] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [term, setTerm] = useState<Terminal | null>(null);

  const termRef = useRef<Terminal | null>(null);
  const streamedInto = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const searchRef = useRef<SearchAddon | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const frame = useRef(0);
  const pending = useRef<string[]>([]);        // data that came before the terminal had a place on the page
  const offset = useRef(-1);                   // where a new stream resumes: -1 = the tail
  const phaseRef = useRef<LogPhase>('connecting');
  const followRef = useRef(true);
  const fontRef = useRef(fontSize);
  fontRef.current = fontSize;
  const colorsRef = useRef(colors);
  colorsRef.current = colors;
  const sectionRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);      // expand / collapse, in whichever toolbar is shown
  const searchInput = useRef<HTMLInputElement>(null);
  const expanded = portal !== null;

  const setFollowing = useCallback((on: boolean) => { followRef.current = on; setFollow(on); }, []);

  const fitSoon = useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const term = termRef.current;
      if (!term?.element?.isConnected) return;
      try { fitRef.current?.fit(); } catch { /* not measurable yet */ }
      if (followRef.current) term.scrollToBottom();
    });
  }, []);

  const afterWrite = useCallback(() => { if (followRef.current) termRef.current?.scrollToBottom(); }, []);

  const openInto = useCallback((el: HTMLElement) => {
    const term = termRef.current;
    if (!term) return;
    if (!term.element) {
      term.open(el);
      if (pending.current.length) {
        term.write(pending.current.join(''), afterWrite);
        pending.current = [];
      }
    } else if (term.element.parentElement !== el) {
      el.appendChild(term.element);              // inline ↔ expanded: the same terminal, scrollback and all
    }
    fitSoon();
  }, [afterWrite, fitSoon]);

  // The host is wherever the terminal is shown; it is fitted to the host's size.
  const attach = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    hostRef.current = el;
    if (!el) return;
    observer.current = new ResizeObserver(fitSoon);
    observer.current.observe(el);
    openInto(el);
  }, [fitSoon, openInto]);

  useEffect(() => {
    const xt = new Terminal({
      disableStdin: true, cursorBlink: false, cursorStyle: 'bar', cursorWidth: 1, cursorInactiveStyle: 'none',
      convertEol: true, scrollback: SCROLLBACK, fontFamily: monoFont(), fontSize: fontRef.current, lineHeight: 1.2,
      allowProposedApi: true,                   // the search addon's highlights are decorations
      theme: colorsRef.current?.theme, rightClickSelectsWord: false,
    });
    const fit = new FitAddon();
    const search = new SearchAddon({ highlightLimit: SEARCH_LIMIT });
    xt.loadAddon(fit);
    xt.loadAddon(search);
    const subscriptions = [
      xt.onScroll(() => {
        const b = xt.buffer.active;
        const atBottom = b.viewportY >= b.baseY;      // scrolling up pauses Follow, back at the bottom resumes it
        if (atBottom !== followRef.current) setFollowing(atBottom);
      }),
      search.onDidChangeResults(r => setResults({ index: r.resultIndex, count: r.resultCount })),
    ];
    xt.attachCustomKeyEventHandler(e => {
      if (e.type !== 'keydown' || !(e.metaKey || e.ctrlKey) || e.altKey) return true;
      const key = e.key.toLowerCase();
      if (key === 'f') { e.preventDefault(); setSearching(true); searchInput.current?.focus(); return false; }
      if (key === 'a') { e.preventDefault(); xt.selectAll(); return false; }
      return true;
    });
    termRef.current = xt;
    fitRef.current = fit;
    searchRef.current = search;
    if (hostRef.current) openInto(hostRef.current);
    setTerm(xt);
    return () => {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
      subscriptions.forEach(s => s.dispose());
      xt.dispose();
      termRef.current = null;
      fitRef.current = null;
      searchRef.current = null;
    };
  }, [openInto, setFollowing]);

  // The stream into the terminal. A new terminal (the first, or one made again by a dev re-mount) starts from the
  // tail; the same terminal resumes where its stream stopped, e.g. when a finished run is live again (requeued).
  useEffect(() => {
    if (!term) return;
    if (streamedInto.current !== term) {
      streamedInto.current = term;
      offset.current = -1;
      pending.current = [];
    }
    const handle = openLogStream({ url: at => exApi.logStreamUrl(pid, eid, at), offset: offset.current }, {
      meta: m => { setMeta(m); setError(null); },
      data: (text, at) => {
        offset.current = at;
        if (term.element) term.write(text, afterWrite);
        else pending.current.push(text);
        setHasData(true);
        setNotice(null);
      },
      reset: () => { offset.current = 0; pending.current = []; term.reset(); },
      eof: e => { offset.current = e.offset; },
      notice: setNotice,
      phase: p => { phaseRef.current = p; setPhase(p); },
    });
    return () => handle.close();
  }, [term, pid, eid, generation, afterWrite]);

  useEffect(() => { if (live && phaseRef.current === 'ended') setGeneration(g => g + 1); }, [live]);

  // While reconnecting, ask the line-page endpoint why (an unknown record, a path outside the project, no server).
  useEffect(() => {
    if (phase !== 'retrying') return;
    let alive = true;
    exApi.logs(pid, eid, -1).then(() => { if (alive) setError(null); },
      e => { if (alive) setError(String((e as Error)?.message ?? e)); });
    return () => { alive = false; };
  }, [phase, pid, eid]);

  // Colors follow the UI theme (light or dark and the accent, on <html>: state/appearance.ts).
  useEffect(() => {
    const update = () => setColors(readColors());
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-accent-color', 'data-gray-color'] });
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', update);
    return () => { mo.disconnect(); mq.removeEventListener('change', update); };
  }, []);
  useEffect(() => { if (termRef.current && colors) termRef.current.options.theme = colors.theme; }, [colors]);

  useEffect(() => {
    const t = termRef.current;
    if (!t || t.options.fontSize === fontSize) return;
    t.options.fontSize = fontSize;
    fitSoon();
    try { localStorage.setItem(FONT_KEY, String(fontSize)); } catch { /* storage unavailable */ }
  }, [fontSize, fitSoon]);

  const toggleFollow = () => {
    const term = termRef.current;
    if (followRef.current) {
      setFollowing(false);
      // xterm keeps scrolling with new output while the view is at the bottom; one line up holds it in place
      if (term && term.buffer.active.baseY > 0) term.scrollLines(-1);
    } else {
      setFollowing(true);
      term?.scrollToBottom();
    }
  };

  const bump = (d: number) => setFontSize(n => Math.min(FONT_MAX, Math.max(FONT_MIN, n + d)));

  const expand = () => {
    setPortal(sectionRef.current?.closest<HTMLElement>('.ex-body') ?? document.body);
    requestAnimationFrame(() => toggleRef.current?.focus());
  };
  const collapse = useCallback(() => {
    setPortal(null);
    requestAnimationFrame(() => toggleRef.current?.focus());
  }, []);
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); collapse(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [expanded, collapse]);

  // ---------------------------------------------------------------- search
  const find = (dir: 'next' | 'prev', q: string, incremental = false) => {
    const s = searchRef.current;
    if (!s) return;
    if (!q) { s.clearDecorations(); termRef.current?.clearSelection(); setResults(null); return; }
    const c = colorsRef.current;
    const opts: ISearchOptions = {
      incremental,
      decorations: c ? { matchBackground: c.match, activeMatchBackground: c.activeMatch, matchOverviewRuler: c.match,
        activeMatchColorOverviewRuler: c.activeMatch } : undefined,
    };
    if (dir === 'next') s.findNext(q, opts); else s.findPrevious(q, opts);
  };
  const closeSearch = () => {
    setSearching(false);
    setQuery('');
    setResults(null);
    searchRef.current?.clearDecorations();
    termRef.current?.clearSelection();
  };
  const onSearchKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') { e.preventDefault(); find(e.shiftKey ? 'prev' : 'next', query); }
    // Esc closes the search only, not the expanded view or the drawer (their listeners are on window)
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeSearch(); termRef.current?.focus(); }
  };
  useEffect(() => { if (searching) searchInput.current?.focus(); }, [searching]);

  const copyAll = () => {
    const term = termRef.current;
    if (!term) return;
    term.selectAll();
    const text = term.getSelection().replace(/\s+$/, '');
    term.clearSelection();
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }).catch(() => { /* clipboard refused */ });
  };

  // ---------------------------------------------------------------- view
  const streaming = phase === 'open' && (meta?.live ?? live);
  const indicator = phase === 'retrying'
    ? <span className="ex-live ex-retrying ex-small"><span className="ex-dot ex-dot-unknown" />{t('ex.d.term.reconnecting')}</span>
    : streaming ? <span className="ex-live ex-small"><span className="ex-dot ex-dot-running" />
      {meta?.missing && !hasData ? t('ex.d.term.waiting') : t('ex.d.logsLive')}</span> : null;
  const matches = !results || !query ? '' : results.count === 0 ? t('ex.d.term.noMatches')
    : results.index < 0 ? t('ex.d.term.manyMatches', { n: SEARCH_LIMIT }) : `${results.index + 1} / ${results.count}`;

  const toolbar = (
    <div className="ex-term-bar" role="toolbar" aria-label={t('ex.d.term.tools')}>
      <Button size="sm" variant="ghost" icon="chevronDown" aria-pressed={follow} title={t('ex.d.term.followHint')}
        onClick={toggleFollow}>{t('ex.d.follow')}</Button>
      {searching ? (
        <div className="ex-term-search" role="search">
          <input ref={searchInput} className="input" type="search" value={query} placeholder={t('ex.d.term.searchPh')}
            aria-label={t('ex.d.term.search')} onKeyDown={onSearchKey}
            onChange={e => { setQuery(e.target.value); find('next', e.target.value, true); }} />
          <span className="faint num ex-small ex-term-count" aria-live="polite">{matches}</span>
          <button type="button" className="icon-btn" aria-label={t('ex.d.term.prev')} title={t('ex.d.term.prev')}
            disabled={!query} onClick={() => find('prev', query)}><Icon name="chevronDown" style={{ transform: 'rotate(180deg)' }} /></button>
          <IconButton icon="chevronDown" label={t('ex.d.term.next')} disabled={!query} onClick={() => find('next', query)} />
          <IconButton icon="close" label={t('ex.d.term.searchClose')} onClick={closeSearch} />
        </div>
      ) : <IconButton icon="search" label={t('ex.d.term.search')} onClick={() => setSearching(true)} />}
      <div className="ex-term-tools">
        <IconButton icon="minus" label={t('ex.d.term.smaller')} disabled={fontSize <= FONT_MIN} onClick={() => bump(-1)} />
        <span className="num muted ex-small ex-term-size" title={t('ex.d.term.size', { n: fontSize })}>{fontSize}</span>
        <IconButton icon="plus" label={t('ex.d.term.larger')} disabled={fontSize >= FONT_MAX} onClick={() => bump(1)} />
        <IconButton icon={copied ? 'check' : 'copy'} label={copied ? t('common.copied') : t('ex.d.term.copy')} onClick={copyAll} />
        <a className="icon-btn" href={exApi.logRawUrl(pid, eid)} download={`${eid}.log`} aria-label={t('ex.d.term.download')}
          title={t('ex.d.term.download')}><Icon name="download" /></a>
        <button ref={toggleRef} type="button" className="icon-btn" onClick={expanded ? collapse : expand}
          aria-label={expanded ? t('ex.d.term.collapse') : t('ex.d.term.expand')}
          title={expanded ? t('ex.d.term.collapse') : t('ex.d.term.expand')}><ExpandIcon expanded={expanded} /></button>
      </div>
    </div>
  );
  const terminal = (
    <div className={`ex-term${expanded ? ' ex-term-big' : ''}`}>
      {toolbar}
      <div ref={attach} className="ex-term-host" role="region" aria-label={t('ex.d.term.label', { title })}
        style={colors ? { background: colors.theme.background } : undefined} />
    </div>
  );
  const empty = phase === 'connecting'
    ? <div className="row faint ex-small"><Spinner />{t('ex.d.term.connecting')}</div>
    : <div className="faint ex-small">{meta?.missing && meta.path ? t('ex.d.logsMissing', { path: meta.path }) : t('ex.d.logsEmpty')}</div>;
  const path = meta?.path && <span className="faint mono ex-small ellipsis" title={meta.path}>{meta.path}</span>;

  return (
    <section ref={sectionRef} className="ex-sec">
      <div className="row">
        <span className="label">{t('ex.d.logs')}</span>
        {indicator}
        <span className="grow" />
        {path}
      </div>
      {error && <div className="notice warn ex-small">{t('ex.d.logsError', { error })}</div>}
      {notice && <div className="notice warn ex-small">{t('ex.d.logsError', { error: notice })}</div>}
      {hasData && meta?.truncated_before && <div className="faint ex-small">{t('ex.d.logsTruncated')}</div>}
      {!hasData ? empty : expanded ? <div className="faint ex-small">{t('ex.d.term.expandedNote')}</div> : terminal}
      {hasData && portal && createPortal(
        <div className="ex-term-overlay" role="dialog" aria-modal="true" aria-label={t('ex.d.term.label', { title })}>
          <div className="row ex-term-overlay-head">
            <span className="h3 ellipsis" title={title}>{title}</span>
            <span className="label">{t('ex.d.logs')}</span>
            {indicator}
            <span className="grow" />
            {path}
          </div>
          {terminal}
        </div>, portal)}
    </section>
  );
}
