// A CodeMirror 6 editor themed with the design tokens (light and dark follow the CSS variables).
// The parent owns saving; setDoc() replaces the text as one undoable change (used to accept an AI proposal).
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { basicSetup } from 'codemirror';
import { EditorView, keymap } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { HighlightStyle, defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { python } from '@codemirror/lang-python';

type Spec = HighlightStyle['specs'][number];

// Re-color the default highlight style's tags with tokens instead of its fixed hex values (no @lezer/highlight import).
const TOKEN_FOR: Record<string, string> = {
  '#404740': 'var(--muted)',        // meta, decorators
  '#708': 'var(--process-ink)',     // keywords
  '#219': 'var(--info)',            // atoms, booleans
  '#164': 'var(--data-ink)',        // numbers
  '#a11': 'var(--emphasis-ink)',    // strings
  '#e40': 'var(--warn)',            // escapes, regexps
  '#00f': 'var(--ink-strong)',      // definitions
  '#30a': 'var(--ink)',             // locals
  '#085': 'var(--data-ink)',        // types, namespaces
  '#167': 'var(--process-ink)',     // class names
  '#256': 'var(--slate)',           // self, builtins
  '#00c': 'var(--ink-strong)',      // property definitions
  '#940': 'var(--faint)',           // comments
  '#f00': 'var(--accent)',          // invalid
};
const tokenHighlight = HighlightStyle.define(defaultHighlightStyle.specs.map((s: Spec): Spec => {
  const { color, ...rest } = s as Spec & { color?: string };
  if (!color) return s;
  const out: Spec = { ...rest, color: TOKEN_FOR[color] ?? 'var(--ink)' };
  if (color === '#708') out.fontWeight = '500';
  if (color === '#940') out.fontStyle = 'italic';
  return out;
}));

const tokenTheme = EditorView.theme({
  '&': { height: '100%', fontSize: '12.5px', backgroundColor: 'var(--surface)', color: 'var(--ink)' },
  '.cm-scroller': { fontFamily: 'var(--mono)', lineHeight: '1.55' },
  '.cm-content': { caretColor: 'var(--accent)', padding: '8px 0' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-gutters': { backgroundColor: 'var(--plate)', color: 'var(--faint)', borderRight: '1px solid var(--rule)' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--wash) 55%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'var(--wash)', color: 'var(--muted)' },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
    { backgroundColor: 'color-mix(in srgb, var(--accent) 18%, transparent)' },
  '.cm-matchingBracket, &.cm-focused .cm-matchingBracket': { backgroundColor: 'var(--wash)', outline: '1px solid var(--rule-strong)' },
  '.cm-searchMatch': { backgroundColor: 'var(--stale-wash)', outline: '1px solid var(--stale)' },
  '.cm-tooltip': { backgroundColor: 'var(--surface)', border: '1px solid var(--rule)', color: 'var(--ink)', borderRadius: 'var(--r-sm)' },
  '.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: 'var(--wash)', color: 'var(--ink-strong)' },
  '.cm-panels': { backgroundColor: 'var(--plate)', color: 'var(--ink)', borderColor: 'var(--rule)' },
  '.cm-panels input, .cm-panels button': { color: 'var(--ink)' },
  '.cm-foldPlaceholder': { backgroundColor: 'var(--wash)', border: '1px solid var(--rule)', color: 'var(--muted)' },
});

export interface CodeEditorHandle {
  setDoc: (text: string) => void;
  getDoc: () => string;
  focus: () => void;
}

export const CodeEditor = forwardRef<CodeEditorHandle, {
  initial: string; onChange: (text: string) => void; onSave: () => void; ariaLabel?: string;
}>(function CodeEditor({ initial, onChange, onSave, ariaLabel }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const cb = useRef({ onChange, onSave });
  cb.current = { onChange, onSave };

  useEffect(() => {
    const v = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: initial,
        extensions: [
          keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => { cb.current.onSave(); return true; } }]),
          basicSetup,
          python(),
          syntaxHighlighting(tokenHighlight),
          tokenTheme,
          EditorView.contentAttributes.of({ 'aria-label': ariaLabel ?? 'code' }),
          EditorView.updateListener.of(u => { if (u.docChanged) cb.current.onChange(u.state.doc.toString()); }),
        ],
      }),
    });
    view.current = v;
    return () => { v.destroy(); view.current = null; };
    // The editor is created once; later `initial` values go through setDoc.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useImperativeHandle(ref, () => ({
    setDoc: (text: string) => {
      const v = view.current;
      if (!v || v.state.doc.toString() === text) return;
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: text } });
    },
    getDoc: () => view.current?.state.doc.toString() ?? '',
    focus: () => view.current?.focus(),
  }), []);

  return <div ref={host} className="vz-cm" />;
});
