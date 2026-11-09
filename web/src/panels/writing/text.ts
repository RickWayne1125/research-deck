// Text helpers shared by the editor and the panel: where a finding's quote is now, word counts, pass colors.
import type { ReviewPass } from '../../types';

/** Each pass's tint (docs: typo --accent, terminology --process, wording --data, consistency --warn, logic --emphasis). */
export const PASS_TINT: Record<ReviewPass, { wash: string; line: string; ink: string }> = {
  typo: { wash: 'var(--accent-wash)', line: 'var(--accent)', ink: 'var(--accent)' },
  terminology: { wash: 'var(--process)', line: 'var(--process-line)', ink: 'var(--process-ink)' },
  wording: { wash: 'var(--data)', line: 'var(--data-line)', ink: 'var(--data-ink)' },
  consistency: { wash: 'var(--warn-wash)', line: 'var(--warn)', ink: 'var(--warn)' },
  logic: { wash: 'var(--emphasis)', line: 'var(--emphasis-line)', ink: 'var(--emphasis-ink)' },
};

export const LESS_CERTAIN = 0.6;     // findings below this are folded away in the side panel
export const AUTO_FIX = 0.8;         // "Fix typos" accepts typo-pass findings at or above this confidence

export const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
export const KEYS = {
  check: MAC ? '⇧⌘K' : 'Ctrl+Shift+K',
  fix: MAC ? '⌥⌘K' : 'Ctrl+Alt+K',
  next: MAC ? '⌥⌘↓' : 'Ctrl+Alt+↓',
  prev: MAC ? '⌥⌘↑' : 'Ctrl+Alt+↑',
  save: MAC ? '⌘S' : 'Ctrl+S',
};

function loose(s: string): { out: string; map: number[] } {
  let out = '';
  const map: number[] = [];
  let space = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (/\s/.test(c)) {
      if (space) continue;
      out += ' ';
      space = true;
    } else {
      out += c;
      space = false;
    }
    map.push(i);
  }
  return { out, map };
}

function commonTail(a: string, b: string): number {
  let n = 0;
  while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
  return n;
}

function occurrences(text: string, quote: string): [number, number][] {
  const hits: [number, number][] = [];
  for (let i = text.indexOf(quote); i >= 0; i = text.indexOf(quote, i + 1)) hits.push([i, i + quote.length]);
  if (hits.length) return hits;
  const t = loose(text), q = loose(quote).out.trim();
  if (!q) return hits;
  for (let i = t.out.indexOf(q); i >= 0; i = t.out.indexOf(q, i + 1)) hits.push([t.map[i], t.map[i + q.length - 1] + 1]);
  return hits;
}

export function lineAt(text: string, offset: number): number {
  let n = 1;
  for (let i = text.indexOf('\n'); i >= 0 && i < offset; i = text.indexOf('\n', i + 1)) n++;
  return n;
}

/** Where a quote is in text: the occurrence whose preceding text ends like `before`, then the one nearest `near`
 *  (an offset, e.g. where it was last seen). Mirrors writing/findings.py locate(). */
export function locate(text: string, quote: string, before = '', near?: number | null): { from: number; to: number } | null {
  if (!quote) return null;
  const hits = occurrences(text, quote);
  if (!hits.length) return null;
  if (hits.length === 1) return { from: hits[0][0], to: hits[0][1] };
  const want = loose(before).out.slice(-60);
  let best = hits[0], bestScore = -1, bestDist = Infinity;
  for (const h of hits) {
    const score = want ? commonTail(loose(text.slice(Math.max(0, h[0] - 80), h[0])).out, want) : 0;
    const dist = near != null ? Math.abs(h[0] - near) : 0;
    if (score > bestScore || (score === bestScore && dist < bestDist)) { best = h; bestScore = score; bestDist = dist; }
  }
  return { from: best[0], to: best[1] };
}

/** Word count as the backend counts it (writing/docs.py): no LaTeX commands, comments or code; CJK characters count one each. */
export function wordCount(text: string, kind: 'tex' | 'md'): number {
  let t = text;
  if (kind === 'tex') {
    t = t.replace(/(^|[^\\])%.*$/gm, '$1 ')
      .replace(/\\(?:cite[a-zA-Z]*|[cC]?ref|eqref|autoref|label|includegraphics|input|include|bibliography[a-z]*|usepackage|documentclass|begin|end|url|href)\*?(?:\[[^\]]*\])*\{[^}]*\}/g, ' ')
      .replace(/\\[a-zA-Z@]+\*?/g, ' ');
  } else {
    t = t.replace(/^---\s*\n[\s\S]*?\n---\s*\n/, ' ').replace(/```[\s\S]*?```/g, ' ').replace(/<!--[\s\S]*?-->/g, ' ').replace(/\]\([^)]*\)/g, ']');
  }
  const latin = t.match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g)?.length ?? 0;
  const cjk = t.match(/[㐀-䶿一-鿿豈-﫿]/g)?.length ?? 0;
  return latin + cjk;
}

export function docKind(path: string): 'tex' | 'md' {
  return /\.tex$/i.test(path) ? 'tex' : 'md';
}

/** "paper/sections/intro.tex" → "intro.tex" */
export const baseName = (path: string) => path.split('/').pop() || path;

/** The edits that turn `a` into `b`, line by line, each limited to what differs within its line (one stretch when the
 *  number of lines differs), so a caret outside them stays where it is. */
export function lineEdits(a: string, b: string): { from: number; to: number; insert: string }[] {
  if (a === b) return [];
  const span = (x: string, y: string, at: number) => {
    let s = 0;
    while (s < x.length && s < y.length && x[s] === y[s]) s++;
    let e = 0;
    while (e < x.length - s && e < y.length - s && x[x.length - 1 - e] === y[y.length - 1 - e]) e++;
    return { from: at + s, to: at + x.length - e, insert: y.slice(s, y.length - e) };
  };
  const al = a.split('\n'), bl = b.split('\n');
  if (al.length !== bl.length) return [span(a, b, 0)];
  const out: { from: number; to: number; insert: string }[] = [];
  let pos = 0;
  al.forEach((x, i) => {
    if (x !== bl[i]) out.push(span(x, bl[i], pos));
    pos += x.length + 1;
  });
  return out;
}
