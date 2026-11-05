// The writing editor: CodeMirror 6 in a reading column, with finding marks, accepted-edit marks and the claims
// gutter. The parent owns saving and the review state; it drives the editor through the handle below.
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { minimalSetup } from 'codemirror';
import { EditorState } from '@codemirror/state';
import { EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from '@codemirror/view';
import { bracketMatching } from '@codemirror/language';
import type { DocClaim, WrFinding } from './api';
import {
  acceptedField, acceptedRanges, addAccepted, claimsGutter, dropAccepted, dropMarks, focusMark, languageFor, markRanges,
  marksField, proseLook, setClaims, setMarks, type AcceptedSpec, type MarkSpec,
} from './cm';
import { LESS_CERTAIN, locate } from './text';

export interface Selection { text: string; start_line: number; end_line: number }
type Placeable = Pick<WrFinding, 'id' | 'pass' | 'quote' | 'before' | 'confidence' | 'offset'>;
type Applicable = Pick<WrFinding, 'id' | 'quote' | 'before' | 'replacement' | 'offset'>;

export interface EditorHandle {
  getText: () => string;
  /** Replace the whole text as one undoable change (restore a version, take a merged text). */
  replaceAll: (text: string) => void;
  goToLine: (line: number) => void;
  focus: () => void;
  selection: () => Selection | null;
  cursor: () => number;
  /** Put whole lines before the cursor's line (one undoable change) and leave the cursor after them. */
  insertLines: (lines: string[]) => void;
  /** Mark these findings in the text (locating each by quote + before); returns the ids that are not in the text any more. */
  syncMarks: (findings: Placeable[]) => string[];
  dropMarks: (ids: string[]) => void;
  /** Marked findings in text order. */
  marks: () => { id: string; from: number }[];
  focusMark: (id: string | null) => void;
  markRect: (id: string) => DOMRect | null;
  /** Apply replacements as one transaction (one undo step); returns the ids applied. */
  apply: (items: Applicable[]) => string[];
  /** Put the original words back where accepted edits still stand; returns the ids reverted. */
  revert: (ids: string[]) => string[];
  setClaims: (claims: DocClaim[]) => void;
}

export interface EditorEvents {
  onChange: (text: string) => void;
  onSave: () => void;
  onSelection: (empty: boolean) => void;
  /** The line the cursor is on (1-based), when it changes. */
  onCursorLine?: (line: number) => void;
  onHoverMark: (id: string | null, rect: DOMRect | null) => void;
  onHoverClaim: (claims: DocClaim[] | null, rect: DOMRect | null) => void;
  onClickClaim: (claims: DocClaim[]) => void;
  onUserKey: () => void;
}

export const WritingEditor = forwardRef<EditorHandle, { kind: 'tex' | 'md'; initial: string; ariaLabel: string } & EditorEvents>(
  function WritingEditor({ kind, initial, ariaLabel, ...events }, ref) {
    const host = useRef<HTMLDivElement>(null);
    const view = useRef<EditorView | null>(null);
    const cb = useRef(events);
    cb.current = events;

    useEffect(() => {
      const v = new EditorView({
        parent: host.current!,
        state: EditorState.create({
          doc: initial,
          extensions: [
            keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => { cb.current.onSave(); return true; } }]),
            minimalSetup,
            lineNumbers(),
            claimsGutter({
              hover: (claims, rect) => cb.current.onHoverClaim(claims, rect),
              leave: () => cb.current.onHoverClaim(null, null),
              click: (claims) => cb.current.onClickClaim(claims),
            }),
            highlightActiveLineGutter(),
            highlightActiveLine(),
            bracketMatching(),
            EditorView.lineWrapping,
            EditorView.contentAttributes.of({ 'aria-label': ariaLabel, spellcheck: kind === 'md' ? 'true' : 'false' }),
            languageFor(kind),
            proseLook,
            marksField,
            acceptedField,
            EditorView.updateListener.of(u => {
              if (u.docChanged) cb.current.onChange(u.state.doc.toString());
              if (u.selectionSet) cb.current.onSelection(u.state.selection.main.empty);
              if (u.selectionSet || u.docChanged) {
                const line = u.state.doc.lineAt(u.state.selection.main.head).number;
                if (line !== u.startState.doc.lineAt(u.startState.selection.main.head).number || u.docChanged) cb.current.onCursorLine?.(line);
              }
            }),
            EditorView.domEventHandlers({
              mouseover(e) {
                const el = (e.target as HTMLElement | null)?.closest<HTMLElement>('[data-fid]');
                if (el) cb.current.onHoverMark(el.dataset.fid!, el.getBoundingClientRect());
                return false;
              },
              mouseout(e) {
                const from = (e.target as HTMLElement | null)?.closest<HTMLElement>('[data-fid]');
                const to = (e.relatedTarget as HTMLElement | null)?.closest?.<HTMLElement>('[data-fid]');
                if (from && (!to || to.dataset.fid !== from.dataset.fid)) cb.current.onHoverMark(null, null);
                return false;
              },
              keydown(e) {
                if (!['Shift', 'Meta', 'Control', 'Alt'].includes(e.key)) cb.current.onUserKey();
                return false;
              },
            }),
          ],
        }),
      });
      view.current = v;
      return () => { v.destroy(); view.current = null; };
      // The editor is created once per document (the parent keys it by path).
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useImperativeHandle(ref, (): EditorHandle => ({
      getText: () => view.current?.state.doc.toString() ?? '',
      replaceAll: (text) => {
        const v = view.current;
        if (!v) return;
        // Replace only the stretch that differs, so marks, claims and the caret outside it stay where they are.
        const old = v.state.doc.toString();
        if (old === text) return;
        let a = 0;
        while (a < old.length && a < text.length && old[a] === text[a]) a++;
        let b = 0;
        while (b < old.length - a && b < text.length - a && old[old.length - 1 - b] === text[text.length - 1 - b]) b++;
        v.dispatch({ changes: { from: a, to: old.length - b, insert: text.slice(a, text.length - b) }, userEvent: 'input.restore' });
      },
      goToLine: (n) => {
        const v = view.current;
        if (!v) return;
        const line = v.state.doc.line(Math.max(1, Math.min(n, v.state.doc.lines)));
        v.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: 'center' }) });
        v.focus();
      },
      focus: () => view.current?.focus(),
      selection: () => {
        const v = view.current;
        if (!v) return null;
        const { from, to, empty } = v.state.selection.main;
        if (empty) return null;
        const text = v.state.sliceDoc(from, to);
        if (!text.trim()) return null;
        return { text, start_line: v.state.doc.lineAt(from).number, end_line: v.state.doc.lineAt(Math.max(from, to - 1)).number };
      },
      cursor: () => view.current?.state.selection.main.head ?? 0,
      insertLines: (lines) => {
        const v = view.current;
        if (!v || !lines.length) return;
        const at = v.state.doc.lineAt(v.state.selection.main.head).from;
        const insert = lines.join('\n') + '\n';
        v.dispatch({ changes: { from: at, insert }, selection: { anchor: at + insert.length }, scrollIntoView: true, userEvent: 'input' });
        v.focus();
      },
      syncMarks: (findings) => {
        const v = view.current;
        if (!v) return [];
        const doc = v.state.doc.toString();
        const current = markRanges(v.state);
        const specs: MarkSpec[] = [];
        const missing: string[] = [];
        for (const f of findings) {
          const cur = current.get(f.id);
          let at = cur && doc.slice(cur.from, cur.to) === f.quote ? { from: cur.from, to: cur.to } : null;
          if (!at) at = locate(doc, f.quote, f.before, cur?.from ?? f.offset ?? null);
          if (!at) { missing.push(f.id); continue; }
          specs.push({ id: f.id, pass: f.pass, from: at.from, to: at.to, tentative: f.confidence < LESS_CERTAIN });
        }
        v.dispatch({ effects: setMarks.of(specs) });
        return missing;
      },
      dropMarks: (ids) => view.current?.dispatch({ effects: dropMarks.of(ids) }),
      marks: () => {
        const v = view.current;
        if (!v) return [];
        return [...markRanges(v.state)].map(([id, r]) => ({ id, from: r.from })).sort((a, b) => a.from - b.from);
      },
      focusMark: (id) => {
        const v = view.current;
        if (!v) return;
        const r = id ? markRanges(v.state).get(id) : null;
        v.dispatch({ effects: r ? [focusMark.of(id), EditorView.scrollIntoView(r.from, { y: 'center' })] : [focusMark.of(null)] });
      },
      markRect: (id) => {
        const v = view.current;
        if (!v) return null;
        const el = v.contentDOM.querySelector<HTMLElement>(`[data-fid="${CSS.escape(id)}"]`);
        if (el) return el.getBoundingClientRect();
        const r = markRanges(v.state).get(id);
        const c = r ? v.coordsAtPos(r.from) : null;
        return c ? new DOMRect(c.left, c.top, 1, c.bottom - c.top) : null;
      },
      apply: (items) => {
        const v = view.current;
        if (!v) return [];
        const doc = v.state.doc.toString();
        const current = markRanges(v.state);
        const edits: { id: string; from: number; to: number; insert: string; quote: string }[] = [];
        for (const f of items) {
          if (f.replacement == null) continue;
          const cur = current.get(f.id);
          const at = cur && doc.slice(cur.from, cur.to) === f.quote ? cur : locate(doc, f.quote, f.before, cur?.from ?? f.offset ?? null);
          if (at) edits.push({ id: f.id, from: at.from, to: at.to, insert: f.replacement, quote: doc.slice(at.from, at.to) });
        }
        edits.sort((a, b) => a.from - b.from);
        const kept = edits.filter((e, i) => i === 0 || e.from >= edits[i - 1].to);   // overlapping edits: the first one wins
        if (!kept.length) return [];
        const changes = v.state.changes(kept.map(e => ({ from: e.from, to: e.to, insert: e.insert })));
        const accepted: AcceptedSpec[] = kept.map(e => ({ id: e.id, from: changes.mapPos(e.from, -1), to: changes.mapPos(e.to, 1), quote: e.quote, replacement: e.insert }));
        v.dispatch({ changes, effects: [dropMarks.of(kept.map(e => e.id)), addAccepted.of(accepted)], userEvent: 'input.review' });
        return kept.map(e => e.id);
      },
      revert: (ids) => {
        const v = view.current;
        if (!v) return [];
        const acc = acceptedRanges(v.state);
        const back = ids.map(id => acc.get(id)).filter((a): a is AcceptedSpec => !!a && v.state.sliceDoc(a.from, a.to) === a.replacement)
          .sort((a, b) => a.from - b.from);
        if (!back.length) return [];
        v.dispatch({ changes: back.map(a => ({ from: a.from, to: a.to, insert: a.quote })), effects: dropAccepted.of(back.map(a => a.id)), userEvent: 'input.review' });
        return back.map(a => a.id);
      },
      setClaims: (claims) => {
        const v = view.current;
        if (!v) return;
        const byLine = new Map<number, DocClaim[]>();
        for (const c of claims) {
          if (!c.line || c.line > v.state.doc.lines) continue;
          byLine.set(c.line, [...(byLine.get(c.line) ?? []), c]);
        }
        const items = [...byLine].sort((a, b) => a[0] - b[0]).map(([line, cs]) => ({ pos: v.state.doc.line(line).from, claims: cs }));
        v.dispatch({ effects: setClaims.of(items) });
      },
    }), []);

    return <div ref={host} className="wr-cm" />;
  },
);
