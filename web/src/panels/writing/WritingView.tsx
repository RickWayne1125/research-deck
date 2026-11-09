// The paper's text: documents on the left (toggle), the editor in a reading column.
// Saving: autosave 1.2 s after the last change with base_sha conflict detection (409 → banner, reload or merge), ⌘S now.
// Proofreading: "AI proofread" (⇧⌘K) runs the fixed passes typo → terminology → wording on the selection, or on the
// whole document when nothing is selected; suggestions tint the text as each pass lands. Hover a tint (or step with
// ⌥⌘↓/↑) to accept ↵ or reject ⌫; a rejection asks why, and the answer becomes a learned rule. "Accept all" (⌥⌘K)
// takes every open suggestion as one undoable edit. The gutter marks map claims bound to the document; an outline item
// shows its number there. In a research project the left pane switches between the outline (the items of the section
// at the cursor and how far the text has got with each: panels/outline/Rail.tsx) and the documents; after a save that
// changed the outline markers (% rd:sec, % rd:describes) the paper is synced to the map.
// The outline file (notes/outline.md, outline/doc.py) is the outline itself: before it is saved, its new lines get their
// rd: tags; the save changes the outline, and the file comes back with its numbers up to date (taken in when nothing was
// typed meanwhile). Clicking an item in another file opens the outline file at that item.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './i18n';
import './writing.css';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { dagApi } from '../../dag/api';
import { OutlineRail } from '../outline/Rail';
import { allItems, docMarks, lineOf, outlineItemIds, outlineTags } from '../outline/model';
import { useI18n } from '../../i18n';
import { ApiError } from '../../api/client';
import { Button, ErrorNote, IconButton, PanelHead, Segmented, Spinner, useLoad } from '../../components/ui';
import { PaperTabs } from './PaperTabs';
import { useResizableWidth } from '../../components/resize';
import type { ReviewPass } from '../../types';
import { writingApi, type DocClaim, type OutlineSync, type WrFinding, type WrReview } from './api';
import { WritingEditor, type EditorHandle } from './Editor';
import { FindingCard, WHY_KEYS, type FindingActions } from './Findings';
import { ReviewBar } from './Review';
import { ConflictDialog, VersionsDialog } from './Dialogs';
import { ClaimCard, DocsDrawer, NoDoc, Preview } from './Parts';
import { KEYS, MAC, baseName, docKind, lineEdits, wordCount } from './text';

const AUTOSAVE_MS = 1200;
const NARROW_PX = 1100;
// The documents list is resizable (components/resize.tsx) up to 30 % of the body; when narrow it floats over the text.
const DOCS = { initial: 248, min: 180, max: 420, share: 0.3 };
/** The proofreading passes: spelling and grammar, the project's terms, then wording. */
const PASSES: ReviewPass[] = ['typo', 'terminology', 'wording'];
const upTo = (min: number, max: number, v: number) => Math.max(min, Math.min(max, Math.round(v)));
type SaveState = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict';
interface OpenDoc { path: string; kind: 'tex' | 'md'; initial: string }
interface CardState { id: string; rect: DOMRect; keys: boolean; why: boolean }
interface Toast { text: string; action?: { label: string; run: () => void }; n: number }

function readLocal<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
}
function writeLocal(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
/** The lines that tie the text to the outline (% rd:sec / rd:end / rd:describes, \rdref): a save that changes them syncs
 *  the paper to the map. */
const MARKER = /%\s*rd:(?:sec|end|describes)\b|\\rdref\{/;
const markerSig = (text: string) => text.split('\n').filter(l => MARKER.test(l)).join('\n');
const frames = (n = 2) => new Promise<void>(r => { const step = (k: number) => (k ? requestAnimationFrame(() => step(k - 1)) : r()); step(n); });

export function WritingView() {
  const { projectId, project, sub, navigate, onEvent, askAgent } = useApp();
  const { t, lang } = useI18n();
  const pid = projectId!;

  // ------------------------------------------------------------ documents
  const docs = useLoad(() => writingApi.docs(pid), [pid]);
  const [drawerOpen, setDrawerOpen] = useState(() => readLocal('rd.wr.drawer', true));
  // The left pane of a research project: the outline beside the text, or the documents.
  const today = useToday();
  const research = project?.kind !== 'engineering';
  const [left, setLeft] = useState<'outline' | 'docs'>(() => readLocal('rd.wr.left', 'outline'));
  useEffect(() => writeLocal('rd.wr.left', left), [left]);
  const [railText, setRailText] = useState('');
  const [cursorLine, setCursorLine] = useState(1);
  // The outline file: its path, the ids its new lines must not reuse, what its last save did, an item to open it at.
  const outlineFile = research ? today.outline?.file?.path ?? null : null;
  const outlineFileRef = useRef(outlineFile);
  outlineFileRef.current = outlineFile;
  const knownIds = useRef<Set<string>>(new Set());
  knownIds.current = useMemo(() => outlineItemIds(today.outline), [today.outline]);
  const [fileSync, setFileSync] = useState<OutlineSync | null>(null);
  const jumpTo = useRef<string | null>(null);
  const railTimer = useRef<number | undefined>(undefined);
  // Below this width the documents list floats over the text instead of taking a column.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyWidth, setBodyWidth] = useState(1400);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setBodyWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const narrow = bodyWidth < NARROW_PX;
  const docsW = useResizableWidth('rd.wr.docsW', DOCS.initial, DOCS.min, upTo(DOCS.min, DOCS.max, bodyWidth * DOCS.share),
    { cssVar: '--wr-docs-w', target: bodyRef });
  const [floatingDocs, setFloatingDocs] = useState(false);
  useEffect(() => writeLocal('rd.wr.drawer', drawerOpen), [drawerOpen]);

  const fallbackPath = useMemo(() => {
    const list = docs.data ?? [];
    const last = readLocal<string | null>(`rd.wr.doc.${pid}`, null);
    const main = project?.config.paper?.main;
    return list.find(d => d.path === last)?.path ?? list.find(d => d.path === main)?.path ?? list[0]?.path ?? null;
  }, [docs.data, pid, project]);
  const path = sub || fallbackPath;
  useEffect(() => { if (path) writeLocal(`rd.wr.doc.${pid}`, path); }, [pid, path]);

  const editor = useRef<EditorHandle>(null);
  const [doc, setDoc] = useState<OpenDoc | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const textRef = useRef('');
  const synced = useRef('');                     // the outline markers as last synced to the map
  const lastSaved = useRef('');
  const baseSha = useRef<string | null>(null);
  const saving = useRef<Promise<void> | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const [saveState, setSaveState] = useState<SaveState>('saved');
  const saveStateRef = useRef(saveState);
  saveStateRef.current = saveState;
  const [restored, setRestored] = useState<string | null>(null);   // a restored version waits for an explicit save
  const restoredRef = useRef(restored);
  restoredRef.current = restored;
  const [words, setWords] = useState(0);
  const [hasSelection, setHasSelection] = useState(false);
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const [previewText, setPreviewText] = useState('');
  const [toast, setToast] = useState<Toast | null>(null);
  const say = useCallback((text: string, action?: Toast['action']) => setToast(prev => ({ text, action, n: (prev?.n ?? 0) + 1 })), []);
  useEffect(() => { if (!toast) return; const h = window.setTimeout(() => setToast(null), toast.action ? 8000 : 4500); return () => clearTimeout(h); }, [toast]);

  // Load the document; on leaving it, save what is pending.
  useEffect(() => {
    if (!path) { setDoc(null); return; }
    let alive = true;
    setDoc(null); setLoadError(null); setReview(null); setStale(new Set()); setCard(null); setClaimCard(null); setRestored(null); setFileSync(null);
    setSaveState('saved'); setMode('edit');
    writingApi.file(pid, path).then(f => {
      if (!alive) return;
      textRef.current = f.content; lastSaved.current = f.content; baseSha.current = f.sha;
      setWords(wordCount(f.content, docKind(path)));
      setRailText(f.content); setCursorLine(1); synced.current = markerSig(f.content);
      docPath.current = path;
      setDoc({ path, kind: docKind(path), initial: f.content });
    }).catch(e => { if (alive) setLoadError(String((e as Error).message)); });
    return () => {
      alive = false;
      clearTimeout(timer.current);
      // Leaving with unsaved text: write it (unless it conflicts or is a restore the author has not kept yet).
      if (textRef.current !== lastSaved.current && saveStateRef.current !== 'conflict' && !restoredRef.current) {
        writingApi.save(pid, path, textRef.current, baseSha.current).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid, path]);

  // Leaving the page with unsaved text: warn, and send it anyway (a keepalive request outlives the page).
  const docPath = useRef<string | null>(null);
  useEffect(() => {
    const flush = (e: BeforeUnloadEvent) => {
      if (textRef.current === lastSaved.current || saveStateRef.current === 'conflict' || restoredRef.current || !docPath.current) return;
      try {
        fetch(`/api/projects/${encodeURIComponent(pid)}/file`, {
          method: 'PUT', keepalive: true, headers: { 'Content-Type': 'application/json', 'X-RD-Request': '1' },
          body: JSON.stringify({ path: docPath.current, content: textRef.current, base_sha: baseSha.current ?? undefined }),
        }).catch(() => {});
      } catch { /* a body over the keepalive limit: the warning below is all we can do */ }
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', flush);
    return () => window.removeEventListener('beforeunload', flush);
  }, [pid]);

  const [conflict, setConflict] = useState<{ disk: string; sha: string; merging: boolean } | null>(null);

  const save = useCallback(async (explicit = false): Promise<void> => {
    if (!doc) return;
    clearTimeout(timer.current);
    if (saving.current) await saving.current;
    if (saveStateRef.current === 'conflict') return;
    if (restoredRef.current && !explicit) return;
    if (doc.path === outlineFileRef.current && editor.current) {
      // the outline file: a new line gets its tag now, so it keeps its item from this save to the next
      const tags = outlineTags(textRef.current, knownIds.current);
      if (tags.length) {
        editor.current.patch(tags);
        textRef.current = editor.current.getText();
        clearTimeout(timer.current);
      }
    }
    const content = textRef.current;
    if (content === lastSaved.current) { setSaveState('saved'); setRestored(null); return; }
    setSaveState('saving');
    const run = writingApi.save(pid, doc.path, content, baseSha.current).then(r => {
      // the file as it is now: the outline file comes back with its numbers up to date
      const disk = r.content ?? content;
      baseSha.current = r.sha; lastSaved.current = disk; setRestored(null);
      if (disk !== content && textRef.current === content) {
        editor.current?.patch(lineEdits(content, disk));
        textRef.current = disk;
      }
      if (r.outline) setFileSync(r.outline);
      const sig = markerSig(content);
      if (doc.kind === 'tex' && sig !== synced.current) { synced.current = sig; dagApi.paperSync(pid).catch(() => {}); }
      setSaveState(textRef.current === disk ? 'saved' : 'dirty');
      if (textRef.current !== disk) timer.current = window.setTimeout(() => save(), AUTOSAVE_MS);
    }).catch(async (e: unknown) => {
      if (e instanceof ApiError && e.status === 409) {
        setSaveState('conflict');
        try { const f = await writingApi.file(pid, doc.path); setConflict({ disk: f.content, sha: f.sha, merging: false }); }
        catch { setConflict({ disk: '', sha: String((e.detail as { sha?: string })?.sha ?? ''), merging: false }); }
      } else setSaveState('error');
    });
    saving.current = run;
    await run;
    saving.current = null;
  }, [doc, pid]);
  const saveRef = useRef(save);
  saveRef.current = save;

  const onChange = useCallback((text: string) => {
    textRef.current = text;
    clearTimeout(timer.current);
    if (saveStateRef.current === 'conflict') return;
    if (text === lastSaved.current) { setSaveState('saved'); return; }
    setSaveState(s => (s === 'saving' ? s : 'dirty'));
    if (!restoredRef.current) timer.current = window.setTimeout(() => saveRef.current(), AUTOSAVE_MS);
  }, []);
  // Word count, a little behind the typing.
  const wordsTimer = useRef<number | undefined>(undefined);
  const onChangeWords = useCallback((text: string) => {
    onChange(text);
    clearTimeout(wordsTimer.current);
    wordsTimer.current = window.setTimeout(() => setWords(wordCount(text, doc?.kind ?? 'md')), 400);
    clearTimeout(railTimer.current);
    railTimer.current = window.setTimeout(() => setRailText(text), 300);
  }, [onChange, doc]);

  /** Put text into the editor as the saved state (reload from disk). */
  const takeDisk = useCallback((content: string, sha: string) => {
    lastSaved.current = content; baseSha.current = sha; textRef.current = content;
    editor.current?.replaceAll(content);
    setSaveState('saved'); setConflict(null); setRestored(null);
    setWords(wordCount(content, doc?.kind ?? 'md'));
  }, [doc]);

  const reloadFromDisk = useCallback(async () => {
    if (!doc) return;
    const f = await writingApi.file(pid, doc.path);
    takeDisk(f.content, f.sha);
  }, [doc, pid, takeDisk]);

  const overwriteWith = useCallback(async (content: string) => {
    if (!doc) return;
    const f = await writingApi.file(pid, doc.path);
    if (content !== textRef.current) { textRef.current = content; editor.current?.replaceAll(content); }
    baseSha.current = f.sha;
    setConflict(null);
    saveStateRef.current = 'dirty';
    setSaveState('dirty');
    await saveRef.current(true);
  }, [doc, pid]);

  // Someone else wrote the file: reload when nothing is pending here, otherwise flag the conflict.
  useEffect(() => onEvent('file', (e) => {
    const p = e.payload as { path?: string; sha?: string } | null;
    docs.reload();
    if (!doc || !p || p.path !== doc.path || !p.sha || p.sha === baseSha.current || saving.current) return;
    if (textRef.current === lastSaved.current) {
      writingApi.file(pid, doc.path).then(f => { if (f.sha !== baseSha.current) { takeDisk(f.content, f.sha); say(t('wr.external')); } }).catch(() => {});
    } else {
      writingApi.file(pid, doc.path).then(f => { if (f.sha !== baseSha.current) { setSaveState('conflict'); setConflict({ disk: f.content, sha: f.sha, merging: false }); } }).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [onEvent, doc, pid, takeDisk, say, t]);

  // ------------------------------------------------------------ the outline file at an item
  const openItem = useCallback((id: string) => {
    const file = outlineFileRef.current;
    if (!file) { navigate('outline', id ? `@item/${id}` : null); return; }
    if (docPath.current === file && doc?.path === file) {
      const line = lineOf(docMarks(textRef.current), id);
      if (line) goToLine(line);
      return;
    }
    jumpTo.current = id;
    navigate('writing', file);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, navigate]);
  useEffect(() => {
    const id = jumpTo.current;
    if (!doc || !id || doc.path !== outlineFileRef.current) return;
    jumpTo.current = null;
    const line = lineOf(docMarks(doc.initial), id);
    if (line) frames().then(() => editor.current?.goToLine(line));
  }, [doc]);

  // ------------------------------------------------------------ claims gutter
  const [claims, setClaims] = useState<DocClaim[]>([]);
  const loadClaims = useCallback(() => {
    if (!doc) return;
    writingApi.claims(pid, doc.path).then(r => setClaims(r.claims)).catch(() => setClaims([]));
  }, [doc, pid]);
  useEffect(() => { loadClaims(); }, [loadClaims]);
  useEffect(() => onEvent('dag', () => { loadClaims(); docs.reload(); }), [onEvent, loadClaims]);  // eslint-disable-line react-hooks/exhaustive-deps
  const outlineNums = useMemo(() => new Map([...allItems(today.outline)].map(i => [i.id, i.num])), [today.outline]);
  useEffect(() => {
    editor.current?.setClaims(claims.map(c => (outlineNums.has(c.id) ? { ...c, outline: outlineNums.get(c.id) } : c)));
  }, [claims, doc, outlineNums]);
  useEffect(() => { if (saveState === 'saved' && doc) loadClaims(); }, [saveState]);  // eslint-disable-line react-hooks/exhaustive-deps

  const [claimCard, setClaimCard] = useState<{ claims: DocClaim[]; rect: DOMRect } | null>(null);
  const claimTimer = useRef<number | undefined>(undefined);
  const onHoverClaim = useCallback((cs: DocClaim[] | null, rect: DOMRect | null) => {
    clearTimeout(claimTimer.current);
    if (cs && rect) setClaimCard({ claims: cs, rect });
    else claimTimer.current = window.setTimeout(() => setClaimCard(null), 250);
  }, []);

  // ------------------------------------------------------------ review state
  const [review, setReview] = useState<WrReview | null>(null);
  const reviewRef = useRef(review);
  reviewRef.current = review;
  const [stale, setStale] = useState<Set<string>>(new Set());

  // The latest review of this document, when there is one.
  useEffect(() => {
    if (!doc) return;
    let alive = true;
    writingApi.reviews(pid, doc.path, 1).then(list => list[0] ? writingApi.getReview(pid, list[0].review_id) : null)
      .then(r => { if (alive && r && !reviewRef.current) setReview(r); }).catch(() => {});
    return () => { alive = false; };
  }, [doc, pid]);

  const refreshReview = useCallback(async (id: string) => {
    try {
      const r = await writingApi.getReview(pid, id);
      if (reviewRef.current?.review_id === id) setReview(r);
    } catch { /* keep what we have */ }
  }, [pid]);

  // Follow a running review: events, with a slow poll as a safety net.
  useEffect(() => onEvent('writing', (e) => {
    const p = e.payload as { kind?: string; review_id?: string; path?: string; status?: string } | null;
    if (!p || p.kind !== 'review' && p.kind !== 'finding') return;
    const cur = reviewRef.current;
    if (cur && p.review_id === cur.review_id) refreshReview(cur.review_id);
    else if (p.kind === 'review' && doc && p.path === doc.path && p.status === 'running' && p.review_id && (!cur || cur.status !== 'running')) {
      writingApi.getReview(pid, p.review_id).then(r => setReview(r)).catch(() => {});   // a check started elsewhere (another tab, an agent)
    }
  }), [onEvent, refreshReview, doc, pid]);
  const running = review?.status === 'running';
  useEffect(() => {
    if (!running || !review) return;
    const h = window.setInterval(() => refreshReview(review.review_id), 2500);
    return () => clearInterval(h);
  }, [running, review?.review_id, refreshReview]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Tint the open findings in the text whenever the review changes.
  const findings = review?.findings ?? [];
  useEffect(() => {
    if (!doc || !editor.current) return;
    const open = findings.filter(f => f.status === 'open');
    const missing = editor.current.syncMarks(open);
    setStale(prev => {
      const next = new Set(missing);
      return next.size === prev.size && [...next].every(id => prev.has(id)) ? prev : next;
    });
  }, [findings, doc]);  // eslint-disable-line react-hooks/exhaustive-deps

  const patchFindings = useCallback((changed: WrFinding[]) => {
    const by = new Map(changed.map(f => [f.id, f]));
    setReview(r => r && { ...r, findings: r.findings.map(f => by.get(f.id) ?? f) });
  }, []);

  const startCheck = useCallback(async () => {
    if (!doc) return null;
    const sel = editor.current?.selection();
    const range = sel ? { start_line: sel.start_line, end_line: sel.end_line } : undefined;
    try {
      closeCardRef.current();
      const r = await writingApi.review(pid, { path: doc.path, passes: PASSES, text: textRef.current, range, lang });
      editor.current?.syncMarks([]);
      setStale(new Set());
      setReview(r);
      return r;
    } catch (e) { say(t('wr.check.failed', { msg: String((e as Error).message) })); return null; }
  }, [doc, pid, lang, say, t]);

  const cancelCheck = useCallback(() => { if (review) writingApi.cancel(pid, review.review_id).then(() => refreshReview(review.review_id)).catch(() => {}); }, [review, pid, refreshReview]);

  // ------------------------------------------------------------ the card, stepping, decisions
  const [card, setCard] = useState<CardState | null>(null);
  const cardRef = useRef(card);
  cardRef.current = card;
  const hoverTimer = useRef<number | undefined>(undefined);
  const findingById = useCallback((id: string) => reviewRef.current?.findings.find(f => f.id === id) ?? null, []);

  const closeCard = useCallback(() => { setCard(null); editor.current?.focusMark(null); }, []);
  const closeCardRef = useRef(closeCard);
  closeCardRef.current = closeCard;

  const onHoverMark = useCallback((id: string | null, rect: DOMRect | null) => {
    const c = cardRef.current;
    if (c && (c.keys || c.why)) return;                    // a pinned card stays put
    clearTimeout(hoverTimer.current);
    if (id && rect) setCard({ id, rect, keys: false, why: false });
    else hoverTimer.current = window.setTimeout(() => setCard(null), 260);
  }, []);

  const focusFinding = useCallback(async (id: string, why = false) => {
    const ed = editor.current;
    if (!ed) return;
    clearTimeout(hoverTimer.current);
    ed.focusMark(id);
    await frames(2);
    const rect = ed.markRect(id);
    if (rect) setCard({ id, rect, keys: true, why });
    else setCard(null);
  }, []);

  const step = useCallback((dir: 1 | -1, from?: string) => {
    const ed = editor.current;
    if (!ed) return;
    const marks = ed.marks();
    if (!marks.length) { closeCard(); return; }
    const c = cardRef.current;
    const at = from ?? (c?.keys ? c.id : null);
    const cur = at ? marks.findIndex(m => m.id === at) : -1;
    let i: number;
    if (cur >= 0) i = (cur + dir + marks.length) % marks.length;
    else {
      const pos = ed.cursor();
      i = dir > 0 ? marks.findIndex(m => m.from > pos) : marks.map(m => m.from < pos).lastIndexOf(true);
      if (i < 0) i = dir > 0 ? 0 : marks.length - 1;
    }
    focusFinding(marks[i].id);
  }, [focusFinding, closeCard]);

  /** After a decision on the focused finding in keyboard mode, go on to the next one. */
  const advance = useCallback((decided: string, marksBefore: { id: string; from: number }[]) => {
    const c = cardRef.current;
    if (!c || !c.keys) { if (c?.id === decided) setCard(null); return; }
    const i = marksBefore.findIndex(m => m.id === decided);
    const rest = marksBefore.filter(m => m.id !== decided && editor.current?.marks().some(x => x.id === m.id));
    if (!rest.length) { closeCard(); return; }
    const next = rest.find((_, k) => marksBefore.indexOf(rest[k]) > i) ?? rest[0];
    focusFinding(next.id);
  }, [focusFinding, closeCard]);

  const decide = useCallback(async (f: WrFinding, status: WrFinding['status'], reason?: string | null) => {
    const r = reviewRef.current;
    if (!r) return null;
    try {
      const out = await writingApi.decide(pid, r.review_id, f.id, status, reason ?? undefined);
      patchFindings([out]);
      return out;
    } catch (e) { say(String((e as Error).message)); return null; }
  }, [pid, patchFindings, say]);

  const actions: FindingActions = useMemo(() => ({
    accept: (f) => {
      const ed = editor.current;
      if (!ed) return;
      const before = ed.marks();
      if (f.replacement !== null) {
        const applied = ed.apply([f]);
        if (!applied.length) { setStale(s => new Set([...s, f.id])); say(t('wr.finding.stale')); advance(f.id, before); return; }
        saveRef.current();              // an accepted edit is written at once, so the file and the finding agree
      } else ed.dropMarks([f.id]);
      decide(f, 'accepted');
      advance(f.id, before);
    },
    reject: (f) => {
      const c = cardRef.current;
      if (c && c.id === f.id) setCard({ ...c, why: true });
      else focusFinding(f.id, true);
    },
    why: async (f, reason) => {
      const ed = editor.current;
      const before = ed?.marks() ?? [];
      ed?.dropMarks([f.id]);
      const out = await decide(f, 'rejected', reason);
      if (out?.rule_id && reason) say(t('wr.why.learned', { text: reason }));
      const c = cardRef.current;
      if (c) setCard({ ...c, why: false });
      advance(f.id, before);
    },
    cancelWhy: () => { const c = cardRef.current; if (c) setCard({ ...c, why: false }); },
    reopen: async (f) => {
      if (f.status === 'accepted' && f.replacement !== null && editor.current?.revert([f.id]).length) saveRef.current();
      await decide(f, 'open');
    },
    jumpLine: (line) => editor.current && goToLine(line),
    openNode: (id) => navigate('dag', id),
  }), [decide, advance, focusFinding, say, t, navigate]);  // eslint-disable-line react-hooks/exhaustive-deps

  const goToLine = (line: number) => {
    if (!editor.current) return;
    if (modeRef.current === 'preview') { setMode('edit'); frames().then(() => editor.current?.goToLine(line)); return; }
    editor.current.goToLine(line);
  };

  // Accept all: every open suggestion with a replacement, as one edit (undo in the toast).
  const acceptAll = useCallback(async () => {
    const ed = editor.current;
    const r = reviewRef.current;
    if (!ed || !doc || !r) return;
    const list = r.findings.filter(f => f.status === 'open' && f.replacement !== null && !stale.has(f.id));
    const applied = list.length ? ed.apply(list) : [];
    if (!applied.length) { say(t('wr.all.none')); return; }
    saveRef.current();
    try { patchFindings(await writingApi.decideMany(pid, r.review_id, applied, 'accepted')); } catch (e) { say(String((e as Error).message)); }
    const reviewId = r.review_id;
    say(t('wr.all.done', { n: applied.length }), {
      label: t('wr.fix.undo'),
      run: async () => {
        const back = editor.current?.revert(applied) ?? [];
        if (back.length) {
          saveRef.current();
          try { patchFindings(await writingApi.decideMany(pid, reviewId, back, 'open')); } catch { /* the marks come back on the next refresh */ }
        }
        say(t('wr.fix.undone', { n: back.length }));
      },
    });
  }, [doc, stale, pid, patchFindings, say, t]);

  // ------------------------------------------------------------ keyboard
  const [dialog, setDialog] = useState<null | 'versions'>(null);
  const keys = useRef({ startCheck, acceptAll, step, save, actions, closeCard, dialog, conflictOpen: false });
  keys.current = { startCheck, acceptAll, step, save, actions, closeCard, dialog, conflictOpen: !!conflict?.merging };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = keys.current;
      if (k.dialog || k.conflictOpen) return;
      const mod = MAC ? e.metaKey : e.ctrlKey;
      const stop = () => { e.preventDefault(); e.stopPropagation(); };
      if (mod && e.code === 'KeyK' && e.shiftKey && !e.altKey) { stop(); k.startCheck(); return; }
      if (mod && e.code === 'KeyK' && e.altKey) { stop(); k.acceptAll(); return; }
      if (mod && e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { stop(); k.step(e.key === 'ArrowDown' ? 1 : -1); return; }
      if (mod && e.code === 'KeyS' && !e.altKey && !e.shiftKey) { stop(); k.save(true); return; }
      const c = cardRef.current;
      if (!c?.keys) return;
      if ((e.target as HTMLElement | null)?.closest?.('input, textarea, select')) return;
      const f = findingById(c.id);
      if (!f || f.status !== 'open') return;
      if (c.why) {
        if (/^[1-4]$/.test(e.key)) { stop(); k.actions.why(f, t(WHY_KEYS[Number(e.key) - 1])); }
        else if (e.key === 'Enter') { stop(); k.actions.why(f, null); }
        else if (e.key === 'Escape') { stop(); k.actions.cancelWhy(); }
        return;
      }
      if (e.key === 'Enter' && !mod && !e.shiftKey && !e.altKey) { stop(); k.actions.accept(f); }
      else if ((e.key === 'Backspace' || e.key === 'Delete') && !mod && !e.altKey) { stop(); k.actions.reject(f); }
      else if (e.key === 'Escape') { stop(); k.closeCard(); }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [findingById, t]);

  // A scroll moves the text under a card: follow it when pinned, otherwise let it go.
  const onSheetScroll = useCallback(() => {
    const c = cardRef.current;
    if (c?.keys || c?.why) { const rect = editor.current?.markRect(c.id); if (rect) setCard({ ...c, rect }); }
    else if (c) setCard(null);
    setClaimCard(null);
  }, []);

  // ------------------------------------------------------------ rendering
  const docInfo = docs.data?.find(d => d.path === path) ?? null;
  const docsShown = narrow ? floatingDocs || !path : drawerOpen;
  const open = findings.filter(f => f.status === 'open' && !stale.has(f.id)).length;
  const cardFinding = card ? findingById(card.id) : null;
  const ask = () => {
    if (!doc) return;
    const sel = editor.current?.selection();
    askAgent(t(sel ? 'wr.ask.selection' : 'wr.ask.doc'), { file: doc.path, ...(sel ? { selection: sel } : {}) });
  };
  const showRestored = !!restored && (saveState === 'dirty' || saveState === 'saved');   // a conflict or an error says more
  const leftSwitch = (
    <Segmented<'outline' | 'docs'> value={left} onChange={setLeft} ariaLabel={t('wr.docs')}
      options={[{ value: 'outline', label: t('ol.rail.tab.outline') }, { value: 'docs', label: t('ol.rail.tab.docs') }]} />
  );
  const statusLabel = showRestored ? t('wr.status.restored') : t(`wr.status.${saveState}`);

  return (
    <div className="panel wr">
      <PanelHead
        title={doc ? (docInfo?.title ?? baseName(doc.path)) : t('nav.writing')}
        subtitle={doc ? (
          <span className="wr-subtitle">
            <span className={`wr-status ${showRestored ? 'dirty' : saveState}`} role="status"><i className="wr-status-dot" />{statusLabel}</span>
            <span className="mono">{doc.path}</span>
            <span className="num">{t('wr.words', { n: words.toLocaleString() })}</span>
          </span>
        ) : undefined}>
        <PaperTabs />
        <IconButton icon="folder" label={t('wr.docs.toggle')} aria-pressed={docsShown}
          onClick={() => (narrow ? setFloatingDocs(o => !o) : setDrawerOpen(o => !o))} />
        {doc && <>
          <Segmented value={mode} ariaLabel={t('wr.mode.preview')} onChange={(m) => { if (m === 'preview') setPreviewText(textRef.current); setMode(m); closeCard(); }}
            options={[{ value: 'edit', label: t('wr.mode.edit') }, { value: 'preview', label: t('wr.mode.preview') }]} />
          <IconButton icon="history" label={t('wr.versions')} onClick={() => setDialog('versions')} />
          <IconButton icon="robot" label={t('wr.ask.hint')} onClick={ask} />
          {(saveState === 'dirty' || saveState === 'error' || restored) && <Button size="sm" onClick={() => save(true)} title={KEYS.save}>{t('wr.save')}</Button>}
          <ReviewBar review={review} open={open} running={running} hasSelection={hasSelection}
            onCheck={() => startCheck()} onCancel={cancelCheck} onAcceptAll={acceptAll} onStep={(d) => step(d)} />
        </>}
      </PanelHead>

      <div ref={bodyRef} className={`panel-body wr-body${docsShown && !narrow ? ' with-docs' : ''}${narrow ? ' narrow' : ''}`}
        style={docsW.style}>
        {docsShown && (research && left === 'outline' ? (
          <OutlineRail head={leftSwitch} text={railText} cursor={cursorLine} path={doc?.path ?? null} floating={narrow} width={docsW}
            outlineFile={outlineFile} sync={fileSync} onOpenItem={openItem}
            onJump={(line) => goToLine(line)} onInsert={(lines) => editor.current?.insertLines(lines)} />
        ) : (
          <DocsDrawer docs={docs.data} loading={docs.loading} current={path} onRefresh={docs.reload} floating={narrow} width={docsW}
            head={research ? leftSwitch : undefined}
            onOpen={(p) => { setFloatingDocs(false); if (p !== path) navigate('writing', p); }} />
        ))}
        <div className="wr-main">
          {docs.error && <div className="wr-banner"><ErrorNote error={docs.error} onRetry={docs.reload} /></div>}
          {loadError && <div className="wr-banner"><ErrorNote error={t('wr.loadError', { msg: loadError })} /></div>}
          {conflict && (
            <div className="wr-banner notice accent" role="alert">
              <div className="grow"><b>{t('wr.conflict.title')}</b> {t('wr.conflict.body')}</div>
              <Button size="sm" onClick={() => reloadFromDisk()}>{t('wr.conflict.reload')}</Button>
              <Button size="sm" onClick={() => setConflict(c => c && { ...c, merging: true })}>{t('wr.conflict.merge')}</Button>
              <Button size="sm" variant="ghost" onClick={() => overwriteWith(textRef.current)}>{t('wr.conflict.keep')}</Button>
            </div>
          )}
          {restored && (
            <div className="wr-banner notice warn">
              <span className="grow">{t('wr.versions.restored', { label: restored, save: KEYS.save })}</span>
              <Button size="sm" variant="primary" onClick={() => save(true)}>{t('wr.save')}</Button>
            </div>
          )}
          {!path && !docs.loading ? <NoDoc /> : !doc ? (!loadError && <div className="empty"><Spinner /></div>) : (
            <div className="wr-sheet" onScroll={onSheetScroll}>
              <div className={`wr-page${mode === 'preview' ? ' hidden' : ''}`}>
                <WritingEditor key={doc.path} ref={editor} kind={doc.kind} initial={doc.initial} ariaLabel={doc.path}
                  onChange={onChangeWords} onSave={() => save(true)} onSelection={(empty) => setHasSelection(!empty)}
                  onCursorLine={setCursorLine}
                  onHoverMark={onHoverMark} onHoverClaim={onHoverClaim}
                  onClickClaim={(cs) => cs[0] && navigate('dag', cs[0].id)}
                  onUserKey={() => { if (cardRef.current?.keys && !cardRef.current.why) closeCard(); }} />
              </div>
              {mode === 'preview' && <Preview text={previewText} kind={doc.kind} pid={pid} path={doc.path} />}
            </div>
          )}
        </div>
      </div>

      {card && cardFinding && cardFinding.status === 'open' && mode === 'edit' && (
        <FindingCard f={cardFinding} rect={card.rect} keys={card.keys} why={card.why} actions={actions}
          onEnter={() => clearTimeout(hoverTimer.current)}
          onLeave={() => { if (!cardRef.current?.keys && !cardRef.current?.why) hoverTimer.current = window.setTimeout(() => setCard(null), 260); }}
          onClose={closeCard} />
      )}
      {claimCard && mode === 'edit' && (
        <ClaimCard claims={claimCard.claims} rect={claimCard.rect} onOpen={(id) => navigate('dag', id)}
          onEnter={() => clearTimeout(claimTimer.current)} onLeave={() => onHoverClaim(null, null)} />
      )}
      {toast && (
        <div className="wr-toast" role="status" key={toast.n}>
          <span>{toast.text}</span>
          {toast.action && <button type="button" className="wr-link" onClick={() => { toast.action!.run(); setToast(null); }}>{toast.action.label}</button>}
        </div>
      )}

      {dialog === 'versions' && doc && (
        <VersionsDialog pid={pid} path={doc.path} kind={doc.kind} current={() => textRef.current}
          onBeforeSnapshot={() => save(true)}
          onRestore={(content, label) => { setRestored(label); restoredRef.current = label; clearTimeout(timer.current); editor.current?.replaceAll(content); }}
          onClose={() => setDialog(null)} />
      )}
      {conflict?.merging && doc && (
        <ConflictDialog disk={conflict.disk} mine={textRef.current} kind={doc.kind}
          onReload={() => takeDisk(conflict.disk, conflict.sha)}
          onSave={(merged) => overwriteWith(merged)}
          onClose={() => setConflict(c => c && { ...c, merging: false })} />
      )}
    </div>
  );
}
