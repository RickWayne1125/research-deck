// The diff of one range: changed files with +/− counts, then each file in unified or split rows with old/new line
// numbers. Click a line number to select it, shift-click another to extend the range; the toolbar then explains,
// reviews or asks the agent about the selected lines. A review finding can jump here (target) to its file and line.
import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, Empty, ErrorNote, IconButton, Segmented, Spinner, useLoad } from '../../components/ui';
import { ResizeHandle, useResizableWidth } from '../../components/resize';
import { Icon } from '../../components/icons';
import { useApp, useLiveReload } from '../../state/app';
import { useI18n, useT } from '../../i18n';
import type { DiffLine } from '../../types';
import { fetchDiff, rangeKey, sameRange, startExplain, type CdDiffFile, type Focus, type Range } from './api';
import { AgentAnswer, countLabel, Counts, FileStatus } from './parts';
import { useFollowRun } from './useFollowRun';

export interface JumpTarget { range: Range; path: string; line: number | null; n: number }
interface Sel { path: string; a: number; b: number }    // row indexes within one file (all hunks flattened)
type Mode = 'unified' | 'split';

const BIG_FILE_ROWS = 1200;
// The explanation drawer floats over the diff: 300 px up to 92 % of it (coding.css caps it the same way).
const DRAWER_MIN = 300;
const drawerMax = (box: HTMLElement | null) => Math.max(DRAWER_MIN, Math.round((box?.clientWidth ?? window.innerWidth) * 0.92));
const lineClass = (t: DiffLine['t']) => (t === '+' ? 'diff-add' : t === '-' ? 'diff-del' : '');
const rowsOf = (f: CdDiffFile) => f.hunks.flatMap(h => h.lines);

/** Split view pairs: context on both sides; a block of deletions beside the additions that replace it. */
function pairUp(lines: DiffLine[], base: number): { li: number | null; ri: number | null }[] {
  const out: { li: number | null; ri: number | null }[] = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].t === ' ') { out.push({ li: base + i, ri: base + i }); i++; continue; }
    const dels: number[] = [], adds: number[] = [];
    while (i < lines.length && lines[i].t === '-') dels.push(base + i++);
    while (i < lines.length && lines[i].t === '+') adds.push(base + i++);
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) out.push({ li: dels[k] ?? null, ri: adds[k] ?? null });
  }
  return out;
}

const FileCard = memo(function FileCard({ file, mode, collapsed, sel, onToggle, onPick, onExplain }: {
  file: CdDiffFile; mode: Mode; collapsed: boolean; sel: Sel | null;
  onToggle: (path: string) => void; onPick: (path: string, idx: number, extend: boolean) => void; onExplain: (f: CdDiffFile) => void;
}) {
  const t = useT();
  const rows = useMemo(() => rowsOf(file), [file]);
  const starts = useMemo(() => { let n = 0; return file.hunks.map(h => { const s = n; n += h.lines.length; return s; }); }, [file]);
  const lo = sel ? Math.min(sel.a, sel.b) : -1, hi = sel ? Math.max(sel.a, sel.b) : -2;
  const inSel = (i: number | null) => (i != null && i >= lo && i <= hi ? 'cd-sel' : '');
  const gutterOf = (e: React.MouseEvent) => (e.target as HTMLElement).closest<HTMLElement>('.cd-gut[data-idx]');
  return (
    <section className="cd-file" data-file={file.path}>
      <header className="cd-file-head">
        <IconButton icon={collapsed ? 'chevronRight' : 'chevronDown'} label={collapsed ? t('cd.changes.expand') : t('cd.changes.collapse')}
          aria-expanded={!collapsed} onClick={() => onToggle(file.path)} />
        <FileStatus status={file.status} untracked={file.untracked} />
        <span className="cd-path mono ellipsis" title={file.old_path ? `${file.old_path} → ${file.path}` : file.path}>
          {file.old_path && <span className="faint">{file.old_path} → </span>}{file.path}
        </span>
        {file.untracked && <Badge>{t('cd.changes.untracked')}</Badge>}
        {file.binary && <Badge>{t('cd.changes.binary')}</Badge>}
        {file.truncated && <Badge tone="warn">{t('cd.changes.fileTruncated')}</Badge>}
        <div className="grow" />
        {!file.binary && <Counts add={file.additions} del={file.deletions} />}
        {!file.binary && <IconButton icon="sparkle" label={t('cd.changes.explainFile')} onClick={() => onExplain(file)} />}
      </header>
      {!collapsed && (
        file.binary ? <div className="cd-file-note faint">{t('cd.changes.binaryNote')}</div>
          : !file.hunks.length ? <div className="cd-file-note faint">{file.old_path ? t('cd.changes.renameOnly') : t('cd.changes.noTextChange')}</div>
            : (
              <div className={`cd-rows code ${mode}`}
                onMouseDown={(e) => { if (e.shiftKey && gutterOf(e)) e.preventDefault(); }}
                onClick={(e) => { const g = gutterOf(e); if (g) onPick(file.path, Number(g.dataset.idx), e.shiftKey); }}>
                {file.hunks.map((h, hi_) => (
                  <Fragment key={hi_}>
                    <div className="cd-hunk">{h.header}</div>
                    {mode === 'unified'
                      ? h.lines.map((l, li) => {
                        const idx = starts[hi_] + li;
                        return (
                          <div key={li} className={`cd-line ${lineClass(l.t)} ${inSel(idx)}`} data-new={l.new ?? undefined} data-old={l.old ?? undefined}>
                            <span className="cd-gut" data-idx={idx}>{l.old ?? ''}</span>
                            <span className="cd-gut" data-idx={idx}>{l.new ?? ''}</span>
                            <span className="cd-mark" aria-hidden="true">{l.t === '+' ? '+' : l.t === '-' ? '−' : ''}</span>
                            <span className="cd-code">{l.text}</span>
                          </div>
                        );
                      })
                      : pairUp(h.lines, starts[hi_]).map(({ li, ri }, k) => {
                        const left = li != null ? rows[li] : null, right = ri != null ? rows[ri] : null;
                        return (
                          <div key={k} className="cd-sline" data-new={right?.new ?? undefined} data-old={left?.old ?? undefined}>
                            <span className={`cd-gut ${inSel(li)}`} data-idx={li ?? undefined}>{left?.old ?? ''}</span>
                            <span className={`cd-code ${left ? lineClass(left.t) : 'cd-blank'} ${inSel(li)}`}>{left?.text ?? ''}</span>
                            <span className={`cd-gut ${inSel(ri)}`} data-idx={ri ?? undefined}>{right?.new ?? ''}</span>
                            <span className={`cd-code ${right ? lineClass(right.t) : 'cd-blank'} ${inSel(ri)}`}>{right?.text ?? ''}</span>
                          </div>
                        );
                      })}
                  </Fragment>
                ))}
              </div>
            )
      )}
    </section>
  );
});

export function DiffView({ pid, range, refreshKey, target, onReviewRange, onReviewSelection }: {
  pid: string; range: Range; refreshKey: string; target: JumpTarget | null;
  onReviewRange: (r: Range) => void; onReviewSelection: (r: Range, focus: Focus) => void;
}) {
  const t = useT();
  const { lang } = useI18n();
  const { askAgent } = useApp();
  const key = rangeKey(range);
  const working = range.kind === 'working';
  const { data, error, loading, reload } = useLoad(() => fetchDiff(pid, range).then(diff => ({ key, diff })), [pid, key, working ? refreshKey : '']);
  useLiveReload(working ? ['file'] : [], reload);
  const diff = data && data.key === key ? data.diff : null;

  const [mode, setModeState] = useState<Mode>(() => { try { return localStorage.getItem('rd.cd.diffMode') === 'split' ? 'split' : 'unified'; } catch { return 'unified'; } });
  const setMode = (m: Mode) => { setModeState(m); try { localStorage.setItem('rd.cd.diffMode', m); } catch { /* ignore */ } };
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Sel | null>(null);
  const [listOpen, setListOpen] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [explainTitle, setExplainTitle] = useState('');
  const explain = useFollowRun();
  const scroller = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const drawerW = useResizableWidth('rd.cd.drawerW', 440, DRAWER_MIN, () => drawerMax(boxRef.current), { cssVar: '--cd-drawer-w', target: boxRef });

  // A new range starts fresh: big, binary and dashboard-state files start collapsed.
  const seenKey = useRef<string | null>(null);
  useEffect(() => {
    if (!diff || seenKey.current === key) return;
    seenKey.current = key;
    setSel(null);
    setNotice(null);
    setListOpen(diff.files.length <= 15);
    setCollapsed(new Set(diff.files.filter(f => f.binary || f.path.startsWith('.research/') || rowsOf(f).length > BIG_FILE_ROWS).map(f => f.path)));
  }, [diff, key]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSel(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const onToggle = useCallback((path: string) => setCollapsed(c => { const n = new Set(c); if (n.has(path)) n.delete(path); else n.add(path); return n; }), []);
  const onPick = useCallback((path: string, idx: number, extend: boolean) => {
    setSel(s => (extend && s && s.path === path ? { ...s, b: idx } : { path, a: idx, b: idx }));
  }, []);

  const scrollToFile = (path: string) => {
    setCollapsed(c => { if (!c.has(path)) return c; const n = new Set(c); n.delete(path); return n; });
    requestAnimationFrame(() => scroller.current?.querySelector(`[data-file="${CSS.escape(path)}"]`)?.scrollIntoView({ block: 'start' }));
  };

  // Jump from a review finding: open the file, scroll to the line (or the nearest one shown), flash and select it.
  const handled = useRef(0);
  useEffect(() => {
    if (!target || !diff || target.n === handled.current || !sameRange(target.range, range)) return;
    handled.current = target.n;
    const file = diff.files.find(f => f.path === target.path || f.old_path === target.path);
    if (!file) { setNotice(t('cd.changes.notInDiff', { path: target.path })); return; }
    setNotice(null);
    setCollapsed(c => { const n = new Set(c); n.delete(file.path); return n; });
    // Two frames: one for React to expand the file, one for layout. Not cancelled on re-render: the jump is one-shot.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const card = scroller.current?.querySelector<HTMLElement>(`[data-file="${CSS.escape(file.path)}"]`);
        if (!card) return;
        let row: HTMLElement | null = null;
        if (target.line != null) {
          let best = Infinity;
          card.querySelectorAll<HTMLElement>('[data-new]').forEach(el => {
            const d = Math.abs(Number(el.dataset.new) - target.line!);
            if (d < best) { best = d; row = el; }
          });
        }
        const el = row as HTMLElement | null;
        (el ?? card).scrollIntoView({ block: el ? 'center' : 'start' });
        if (el) {
          el.classList.add('cd-flash');
          window.setTimeout(() => el.classList.remove('cd-flash'), 1600);
          const idx = el.querySelector<HTMLElement>('.cd-gut[data-idx]')?.dataset.idx;
          if (idx != null) setSel({ path: file.path, a: Number(idx), b: Number(idx) });
        }
      });
    });
  }, [target, diff, range, t]);

  const selInfo = useMemo(() => {
    if (!sel || !diff) return null;
    const file = diff.files.find(f => f.path === sel.path);
    if (!file) return null;
    const rows = rowsOf(file);
    const lo = Math.min(sel.a, sel.b), hi = Math.max(sel.a, sel.b);
    const picked = rows.slice(lo, hi + 1);
    if (!picked.length) return null;
    const news = picked.map(r => r.new).filter((n): n is number => n != null);
    const olds = picked.map(r => r.old).filter((n): n is number => n != null);
    // Deleted lines only: anchor the new-side focus on the nearest line that still exists.
    const anchor = news.length ? null : (rows.slice(hi + 1).find(r => r.new != null)?.new ?? [...rows.slice(0, lo)].reverse().find(r => r.new != null)?.new ?? 1);
    const onNew = news.length > 0;
    const nums = onNew ? news : olds;
    return {
      file, onNew, start: Math.min(...nums), end: Math.max(...nums),
      focusStart: onNew ? Math.min(...news) : anchor!, focusEnd: onNew ? Math.max(...news) : anchor!,
      text: picked.map(r => (r.t === ' ' ? ' ' : r.t) + r.text).join('\n'),
    };
  }, [sel, diff]);

  const oldRev = range.kind === 'commit' ? `${range.sha}~1` : 'HEAD';
  const newRev = range.kind === 'commit' ? range.sha : undefined;      // undefined: the file in the working tree

  const explainFile = useCallback((file: CdDiffFile) => {
    const deleted = file.status === 'D';
    setExplainTitle(t('cd.explain.titleFile', { path: file.path }));
    explain.start(() => startExplain(pid, { path: file.path, start_line: 1, rev: deleted ? oldRev : newRev, lang }));
  }, [explain.start, pid, oldRev, newRev, lang, t]);   // eslint-disable-line react-hooks/exhaustive-deps

  const explainSel = () => {
    if (!selInfo) return;
    const path = selInfo.onNew ? selInfo.file.path : (selInfo.file.old_path ?? selInfo.file.path);
    setExplainTitle(t('cd.explain.titleLines', { path, start: selInfo.start, end: selInfo.end }));
    explain.start(() => startExplain(pid, { path, start_line: selInfo.start, end_line: selInfo.end, rev: selInfo.onNew ? newRev : oldRev, lang }));
  };
  const reviewSel = () => {
    if (!selInfo) return;
    onReviewSelection(range, { path: selInfo.file.path, start_line: selInfo.focusStart, end_line: selInfo.focusEnd });
  };
  const selLines = selInfo ? `${selInfo.start}–${selInfo.end}${selInfo.onNew ? '' : ` (${t('cd.sel.old')})`}` : '';
  const askSel = () => {
    if (!selInfo) return;
    askAgent(t('cd.ask.selection', { path: selInfo.file.path, lines: selLines }), {
      file: selInfo.file.path, selection: { text: selInfo.text, start_line: selInfo.start, end_line: selInfo.end },
      extra: range.kind === 'commit' ? `Diff of commit ${range.short}` : 'Diff of the working tree vs HEAD',
    });
  };

  const totals = useMemo(() => diff?.files.reduce((a, f) => ({ add: a.add + f.additions, del: a.del + f.deletions }), { add: 0, del: 0 }), [diff]);

  return (
    <div ref={boxRef} className={`cd-diff ${explain.status !== 'idle' ? 'has-drawer' : ''}`} style={drawerW.style}>
      <div className="cd-diff-head">
        <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
          <span className="label">{working ? t('cd.changes.workingLabel') : t('cd.changes.commitLabel', { short: range.short })}</span>
          <span className="h3 ellipsis" title={working ? undefined : range.subject}>{working ? t('cd.changes.workingTitle') : range.subject ?? range.short}</span>
        </div>
        {diff && totals && <span className="muted num cd-stat">{countLabel(t, 'cd.changes.files', diff.files.length)} · <Counts add={totals.add} del={totals.del} /></span>}
        <Segmented<Mode> ariaLabel={t('cd.changes.view')} value={mode} onChange={setMode}
          options={[{ value: 'unified', label: t('cd.changes.unified') }, { value: 'split', label: t('cd.changes.split') }]} />
        <Button size="sm" icon="sparkle" onClick={() => onReviewRange(range)} disabled={!diff?.files.length}>{t('cd.changes.review')}</Button>
        {loading && diff && <Spinner />}
        <IconButton icon="refresh" label={t('common.refresh')} onClick={reload} />
      </div>

      <div className="cd-diff-scroll" ref={scroller}>
        {error && !diff && <div className="cd-pad"><ErrorNote error={error} onRetry={reload} /></div>}
        {!diff && !error && <div className="empty"><Spinner /></div>}
        {diff && !diff.files.length && (
          <Empty icon="check" title={working ? t('cd.changes.clean') : t('cd.changes.emptyCommit')}>{working ? t('cd.changes.cleanHint') : null}</Empty>
        )}
        {diff && diff.files.length > 0 && (
          <>
            {(diff.truncated || notice) && (
              <div className="cd-notes">
                {diff.truncated && <div className="notice warn"><Icon name="warn" /> {t('cd.changes.truncated')}</div>}
                {notice && <div className="notice"><Icon name="info" /> {notice}</div>}
              </div>
            )}
            <div className="cd-filelist">
              <button type="button" className="cd-filelist-toggle" aria-expanded={listOpen} onClick={() => setListOpen(o => !o)}>
                <Icon name={listOpen ? 'chevronDown' : 'chevronRight'} size={14} />
                <span className="label">{t('cd.changes.fileList', { n: diff.files.length })}</span>
                <span className="grow" />
                <span className="faint cd-hint">{t('cd.sel.hint')}</span>
              </button>
              {listOpen && (
                <div className="list">
                  {diff.files.map(f => (
                    <button key={f.path} type="button" className="list-item cd-filerow" onClick={() => scrollToFile(f.path)}>
                      <FileStatus status={f.status} untracked={f.untracked} />
                      <span className="cd-path mono ellipsis grow" title={f.path}>{f.path}</span>
                      {f.binary ? <Badge>{t('cd.changes.binary')}</Badge> : <Counts add={f.additions} del={f.deletions} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {diff.files.map(f => (
              <FileCard key={f.path} file={f} mode={mode} collapsed={collapsed.has(f.path)} sel={sel?.path === f.path ? sel : null}
                onToggle={onToggle} onPick={onPick} onExplain={explainFile} />
            ))}
          </>
        )}
      </div>

      {selInfo && (
        <div className="cd-seltool" role="toolbar" aria-label={t('cd.sel.toolbar')}>
          <span className="mono ellipsis cd-seltool-where" title={selInfo.file.path}>{selInfo.file.path.split('/').pop()} · {selLines}</span>
          <Button size="sm" variant="primary" icon="sparkle" onClick={explainSel} disabled={explain.running}>{t('cd.sel.explain')}</Button>
          <Button size="sm" icon="diff" onClick={reviewSel}>{t('cd.sel.review')}</Button>
          <Button size="sm" icon="send" onClick={askSel}>{t('cd.askAgent')}</Button>
          <IconButton icon="close" label={t('cd.sel.clear')} onClick={() => setSel(null)} />
        </div>
      )}

      {explain.status !== 'idle' && (
        <div id="cd-drawer" className="cd-drawer">
          <ResizeHandle pane={drawerW} edge="left" label={t('cd.drawer.resize')} controls="cd-drawer" />
          <div className="cd-drawer-scroll">
            <AgentAnswer run={explain} title={explainTitle} onClose={explain.reset}
              onAsk={() => askAgent(t('cd.ask.followUp', { target: explainTitle }), selInfo ? { file: selInfo.file.path, selection: { text: selInfo.text, start_line: selInfo.start, end_line: selInfo.end } } : undefined)} />
          </div>
        </div>
      )}
    </div>
  );
}
