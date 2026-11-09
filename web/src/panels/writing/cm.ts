// CodeMirror 6 pieces of the writing editor: the prose theme, Markdown / LaTeX languages, finding marks tinted per
// pass, marks over accepted edits, and the claims gutter (DAG claims bound to the document, colored by freshness).
// All positions live in state fields, so they move with the text as the author types.
import { RangeSet, StateEffect, StateField, type EditorState, type Extension } from '@codemirror/state';
import { Decoration, EditorView, GutterMarker, gutter, type DecorationSet } from '@codemirror/view';
import { HighlightStyle, StreamLanguage, defaultHighlightStyle, syntaxHighlighting, type StreamParser } from '@codemirror/language';
import { markdown } from '@codemirror/lang-markdown';
import { stex } from '@codemirror/legacy-modes/mode/stex';
import type { ReviewPass } from '../../types';
import type { Freshness } from '../../dag-types';
import { FRESH_STYLE } from '../../dag/encoding';
import { FRESHNESS_LEVEL } from '../../dag-types';
import type { DocClaim } from './api';

// ------------------------------------------------------------------ languages and look

// stex names its tokens after CodeMirror 5 styles; rename them to tags the token-colored style below paints.
const STEX_TOKENS: Record<string, string> = { tag: 'macroName', bracket: 'meta', keyword: 'keyword', atom: 'atom', comment: 'comment', number: 'number', error: 'invalid' };
const texParser = stex as StreamParser<unknown>;
const texMode: StreamParser<unknown> = {
  ...texParser,
  token: (stream, state) => {
    const t = texParser.token(stream, state);
    return t ? (STEX_TOKENS[t] ?? t) : t;
  },
};

export function languageFor(kind: 'tex' | 'md'): Extension {
  return kind === 'tex' ? StreamLanguage.define(texMode) : markdown();
}

type Spec = HighlightStyle['specs'][number];
// The default style's colors → design tokens (the default style is the only source of tag objects we can import).
const TOKEN_FOR: Record<string, string> = {
  '#404740': 'var(--faint)',        // meta: braces in LaTeX
  '#708': 'var(--data-ink)',        // keywords: math in LaTeX
  '#219': 'var(--info)',            // atoms, urls: \ref / \cite keys, link targets
  '#164': 'var(--data-ink)',        // numbers
  '#a11': 'var(--emphasis-ink)',    // strings
  '#e40': 'var(--warn)',
  '#00f': 'var(--ink-strong)',
  '#30a': 'var(--ink)',
  '#085': 'var(--process-ink)',
  '#167': 'var(--process-ink)',
  '#256': 'var(--process-ink)',     // macro names: LaTeX commands
  '#00c': 'var(--ink-strong)',
  '#940': 'var(--faint)',           // comments
  '#f00': 'var(--accent)',          // invalid
};
const proseHighlight = HighlightStyle.define(defaultHighlightStyle.specs.map((s: Spec): Spec => {
  const { color, textDecoration, ...rest } = s as Spec & { color?: string; textDecoration?: string };
  const out: Spec = { ...rest };
  if (color) out.color = TOKEN_FOR[color] ?? 'var(--ink)';
  if (textDecoration === 'line-through') out.textDecoration = textDecoration;
  if (textDecoration === 'underline' && rest.fontWeight === 'bold') { out.fontWeight = '600'; out.color = 'var(--ink-strong)'; }   // headings
  else if (textDecoration === 'underline') out.textDecoration = 'underline';                                                          // links
  if (color === '#940') out.fontStyle = 'italic';
  return out;
}));

export const proseTheme = EditorView.theme({
  '&': { backgroundColor: 'transparent', color: 'var(--ink)', fontSize: '15.5px' },
  '.cm-scroller': { fontFamily: 'var(--serif)', lineHeight: '1.75', overflow: 'visible' },
  '.cm-content': { caretColor: 'var(--accent)', padding: '28px 0 45vh' },
  '.cm-line': { padding: '0 12px 0 16px' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent)', borderLeftWidth: '1.5px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--faint)', border: 'none', fontFamily: 'var(--mono)', fontSize: '10.5px' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 6px 0 10px', lineHeight: 'inherit', minWidth: '34px' },
  '.cm-activeLineGutter': { backgroundColor: 'var(--accent-a3)', color: 'var(--accent-11)' },
  '.cm-activeLine': { backgroundColor: 'var(--accent-a3)' },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
    { backgroundColor: 'color-mix(in srgb, var(--accent) 16%, transparent)' },
  '.cm-matchingBracket, &.cm-focused .cm-matchingBracket': { backgroundColor: 'var(--wash)', outline: '1px solid var(--rule-strong)' },
}, { dark: false });

export const proseLook: Extension = [proseTheme, syntaxHighlighting(proseHighlight)];

// ------------------------------------------------------------------ finding marks

export interface MarkSpec { id: string; pass: ReviewPass; from: number; to: number; tentative: boolean }
export interface MarkRange { from: number; to: number; pass: ReviewPass; tentative: boolean }

export const setMarks = StateEffect.define<MarkSpec[]>();      // replaces every finding mark
export const dropMarks = StateEffect.define<string[]>();
export const focusMark = StateEffect.define<string | null>();

function markDeco(m: MarkSpec, focused: boolean) {
  const cls = `wr-mark wr-mark-${m.pass}${m.tentative ? ' wr-tentative' : ''}${focused ? ' wr-focus' : ''}`;
  return Decoration.mark({ class: cls, attributes: { 'data-fid': m.id }, fid: m.id, pass: m.pass, tentative: m.tentative }).range(m.from, m.to);
}

function specsOf(decos: DecorationSet): MarkSpec[] {
  const out: MarkSpec[] = [];
  const it = decos.iter();
  while (it.value) {
    const s = it.value.spec as { fid: string; pass: ReviewPass; tentative: boolean };
    if (it.to > it.from) out.push({ id: s.fid, pass: s.pass, tentative: s.tentative, from: it.from, to: it.to });
    it.next();
  }
  return out;
}

interface MarksState { decos: DecorationSet; focus: string | null }

export const marksField = StateField.define<MarksState>({
  create: () => ({ decos: Decoration.none, focus: null }),
  update(value, tr) {
    let { decos, focus } = value;
    decos = decos.map(tr.changes);
    let rebuild = false;
    for (const e of tr.effects) {
      if (e.is(setMarks)) { decos = Decoration.set(e.value.filter(m => m.to > m.from).map(m => markDeco(m, m.id === focus)), true); }
      else if (e.is(dropMarks)) { const ids = new Set(e.value); decos = decos.update({ filter: (_f, _t, d) => !ids.has((d.spec as { fid: string }).fid) }); if (focus && ids.has(focus)) focus = null; }
      else if (e.is(focusMark)) { focus = e.value; rebuild = true; }
    }
    if (rebuild) decos = Decoration.set(specsOf(decos).map(m => markDeco(m, m.id === focus)), true);
    return { decos, focus };
  },
  provide: f => EditorView.decorations.from(f, v => v.decos),
});

export function markRanges(state: EditorState): Map<string, MarkRange> {
  const out = new Map<string, MarkRange>();
  for (const m of specsOf(state.field(marksField).decos)) out.set(m.id, { from: m.from, to: m.to, pass: m.pass, tentative: m.tentative });
  return out;
}

// ------------------------------------------------------------------ accepted edits

export interface AcceptedSpec { id: string; from: number; to: number; quote: string; replacement: string }
export const addAccepted = StateEffect.define<AcceptedSpec[]>();
export const dropAccepted = StateEffect.define<string[]>();

export const acceptedField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(decos, tr) {
    decos = decos.map(tr.changes);
    for (const e of tr.effects) {
      if (e.is(addAccepted)) {
        decos = decos.update({
          add: e.value.filter(a => a.to > a.from).map(a => Decoration.mark({ class: 'wr-accepted', fid: a.id, quote: a.quote, replacement: a.replacement }).range(a.from, a.to)),
          sort: true,
        });
      } else if (e.is(dropAccepted)) {
        const ids = new Set(e.value);
        decos = decos.update({ filter: (_f, _t, d) => !ids.has((d.spec as { fid: string }).fid) });
      }
    }
    return decos;
  },
  provide: f => EditorView.decorations.from(f),
});

export function acceptedRanges(state: EditorState): Map<string, AcceptedSpec> {
  const out = new Map<string, AcceptedSpec>();
  const it = state.field(acceptedField).iter();
  while (it.value) {
    const s = it.value.spec as { fid: string; quote: string; replacement: string };
    out.set(s.fid, { id: s.fid, from: it.from, to: it.to, quote: s.quote, replacement: s.replacement });
    it.next();
  }
  return out;
}

// ------------------------------------------------------------------ claims gutter

const RANK = (f: Freshness | null) => (f ? FRESHNESS_LEVEL[f] : -1);

export function worstLevel(claims: DocClaim[]): Freshness | null {
  return claims.reduce<Freshness | null>((w, c) => (RANK(c.freshness) > RANK(w) ? c.freshness : w), null);
}

class ClaimMarker extends GutterMarker {
  constructor(readonly claims: DocClaim[]) { super(); }
  eq(other: GutterMarker): boolean {
    return other instanceof ClaimMarker && other.claims.map(c => c.id + c.freshness + (c.outline ?? '')).join() === this.claims.map(c => c.id + c.freshness + (c.outline ?? '')).join();
  }
  toDOM(): Node {
    const level = worstLevel(this.claims);
    const style = FRESH_STYLE[level ?? 'unknown'];
    const el = document.createElement('span');
    const num = this.claims.find(c => c.outline)?.outline;
    if (num) {                                   // an outline item: its number, as the paragraph's label
      el.className = 'wr-claim-num';
      el.textContent = num;
      el.style.setProperty('--claim-color', style.color);
      el.dataset.claims = this.claims.map(c => c.id).join(' ');
      return el;
    }
    el.className = `wr-claim-dot${style.dashed ? ' dashed' : ''}${this.claims.some(c => c.kind === 'section' || c.id.startsWith('sec.')) && this.claims.length === 1 ? ' section' : ''}`;
    el.style.setProperty('--claim-color', style.color);
    el.style.setProperty('--claim-wash', style.wash);
    el.dataset.claims = this.claims.map(c => c.id).join(' ');
    return el;
  }
}

class SpacerMarker extends GutterMarker {
  toDOM(): Node { const el = document.createElement('span'); el.className = 'wr-claim-dot spacer'; return el; }
}

export const setClaims = StateEffect.define<{ pos: number; claims: DocClaim[] }[]>();

export const claimsField = StateField.define<RangeSet<GutterMarker>>({
  create: () => RangeSet.empty,
  update(set, tr) {
    set = set.map(tr.changes);
    for (const e of tr.effects) if (e.is(setClaims)) set = RangeSet.of(e.value.map(c => new ClaimMarker(c.claims).range(c.pos)), true);
    return set;
  },
});

export function claimsAt(state: EditorState, lineFrom: number): DocClaim[] {
  let found: DocClaim[] = [];
  state.field(claimsField).between(lineFrom, lineFrom, (from, _to, m) => {
    if (from === lineFrom && m instanceof ClaimMarker) found = m.claims;
  });
  return found;
}

/** The gutter; `on` gets hover (with the marker's rectangle), leave and click. */
export function claimsGutter(on: { hover: (claims: DocClaim[], rect: DOMRect) => void; leave: () => void; click: (claims: DocClaim[]) => void }): Extension {
  return [claimsField, gutter({
    class: 'wr-claims-gutter',
    markers: v => v.state.field(claimsField),
    initialSpacer: () => new SpacerMarker(),
    domEventHandlers: {
      mouseover(view, line, event) {
        const claims = claimsAt(view.state, line.from);
        const target = (event.target as HTMLElement | null)?.closest('.wr-claim-dot, .wr-claim-num');
        if (claims.length && target) on.hover(claims, target.getBoundingClientRect());
        return false;
      },
      mouseout() { on.leave(); return false; },
      mousedown(view, line) {
        const claims = claimsAt(view.state, line.from);
        if (!claims.length) return false;
        on.click(claims);
        return true;
      },
    },
  })];
}
