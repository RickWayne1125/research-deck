// Pure helpers over the outline (unit-tested in outline.test.ts): walking items, finding an item's place, which
// pending items the page lists, the outline as text (for the agent), and the task board's columns.
import type { Bi, Draft, DraftStep, Group, Item, ItemState, Outline, Pending, Phase, Section, SectionPhase, Step, Task, TaskStatus, TaskType, Template } from './api';
import { PHASES } from './api';

export function bi(v: Bi | string | null | undefined, lang: string): string {
  if (!v) return '';
  if (typeof v === 'string') return v;
  return (lang === 'zh' ? v.zh || v.en : v.en || v.zh) || '';
}

/** Every item of the outline, depth first: sub-items, then the fork's directions (and theirs). */
export function* walk(steps: Step[]): Generator<Item> {
  for (const step of steps) {
    for (const it of step.items) {
      yield it;
      yield* walk(it.children);
      if (it.fork) for (const d of it.fork.directions) { yield d; yield* walk(d.children); }
    }
  }
}

export function* allItems(o: Outline | null | undefined): Generator<Item> {
  for (const s of o?.sections ?? []) yield* walk(s.items);
}

export function itemIndex(o: Outline | null | undefined): Map<string, Item> {
  return new Map([...allItems(o)].map(i => [i.id, i]));
}

export function outlineItemIds(o: Outline | null | undefined): Set<string> {
  const ids = new Set<string>((o?.sections ?? []).map(s => s.id));
  for (const i of allItems(o)) ids.add(i.id);
  return ids;
}

/** Items shown in the overview: abandoned ones (and proposals that were not accepted) only when asked for. */
export function liveSteps(steps: Step[], showAbandoned: boolean): Step[] {
  if (showAbandoned) return steps;
  return steps.map(s => ({ ...s, items: s.items.filter(i => i.state !== 'abandoned') })).filter(s => s.items.length);
}

/** The path from the section down to the item: [section, item, …, item]. Null when the item is not in the outline. */
export function pathTo(o: Outline | null | undefined, id: string): { section: Section; items: Item[] } | null {
  for (const s of o?.sections ?? []) {
    const trail: Item[] = [];
    const find = (steps: Step[]): boolean => {
      for (const step of steps) {
        for (const it of step.items) {
          trail.push(it);
          if (it.id === id) return true;
          if (find(it.children)) return true;
          for (const d of it.fork?.directions ?? []) {
            trail.push(d);
            if (d.id === id || find(d.children)) return true;
            trail.pop();
          }
          trail.pop();
        }
      }
      return false;
    };
    if (find(s.items)) return { section: s, items: [...trail] };
  }
  return null;
}

/** The step an item sits in and its index: what the next item after it is ("together lead to 3.4"). */
export function nextNumAfter(steps: Step[], si: number): string | null {
  return steps[si + 1]?.items[0]?.num ?? null;
}

// ------------------------------------------------------------------ states

export type Tone = 'ok' | 'run' | 'warn' | 'bad' | 'off' | 'dash' | '';
export const STATE_TONE: Record<ItemState, Tone> = {
  holds: 'ok', doing: 'run', blocked: 'bad', todo: '', locked: 'off', needs_tasks: 'warn', choose: 'run',
  pending: 'dash', proposed: 'dash', abandoned: 'off',
};
export const TASK_TONE: Record<TaskStatus, string> = { done: 'done', doing: 'doing', blocked: 'blocked', todo: 'todo', locked: 'locked', sugg: 'sugg' };

export function phaseIndex(p: SectionPhase | null | undefined): number {
  return p ? PHASES.indexOf(p as Phase) : -1;
}

/** ①…④ for the four phases, ∑ for the summary sections. */
export function phaseMark(p: SectionPhase | null | undefined): string {
  const i = phaseIndex(p);
  return i >= 0 ? '①②③④'[i] : '∑';
}

export function groupOf(o: Outline, sectionId: string): Group | undefined {
  return o.groups.find(g => g.sections.includes(sectionId));
}

// ------------------------------------------------------------------ what waits for the researcher

/** The outline's own pending items; open proposals are listed with Today's (they carry the impact preview there). */
export function outlinePending(o: Outline | null | undefined): Exclude<Pending, { kind: 'proposal' }>[] {
  return (o?.pending ?? []).filter((x): x is Exclude<Pending, { kind: 'proposal' }> => x.kind !== 'proposal');
}

// ------------------------------------------------------------------ tasks

export function taskIndex(o: Outline | null | undefined): Map<string, Task> {
  return new Map((o?.tasks ?? []).map(t => [t.id, t]));
}

export type Column = 'todo' | 'doing' | 'blocked' | 'done';
export const COLUMNS: Column[] = ['todo', 'doing', 'blocked', 'done'];

/** The task board: tasks of live items by column (suggestions and tasks waiting for their phase under "not started");
 *  filtered by type and, when given, by phase. */
export function boardColumns(tasks: Task[], type: TaskType | 'all', phase: Phase | 'all'): Record<Column, Task[]> {
  const out: Record<Column, Task[]> = { todo: [], doing: [], blocked: [], done: [] };
  for (const t of tasks) {
    if (t.abandoned) continue;
    if (type !== 'all' && t.type !== type) continue;
    if (phase !== 'all' && t.phase !== phase) continue;
    const col: Column = t.status === 'done' ? 'done' : t.status === 'doing' ? 'doing' : t.status === 'blocked' ? 'blocked' : 'todo';
    out[col].push(t);
  }
  // within a column: phase order, then suggestions last
  const rank = (t: Task) => (t.phase ? PHASES.indexOf(t.phase) : 9) * 10 + (t.status === 'sugg' ? 5 : t.status === 'locked' ? 3 : 0);
  for (const c of COLUMNS) out[c].sort((a, b) => rank(a) - rank(b));
  return out;
}

export function typeCounts(tasks: Task[]): Record<TaskType | 'all', number> {
  const live = tasks.filter(t => !t.abandoned);
  return {
    all: live.length, lit: live.filter(t => t.type === 'lit').length, code: live.filter(t => t.type === 'code').length,
    fig: live.filter(t => t.type === 'fig').length, exp: live.filter(t => t.type === 'exp').length,
  };
}

// ------------------------------------------------------------------ forks

/** Every fork in the outline, in paper order (for the research tree). */
export function forks(o: Outline | null | undefined): { item: Item; section: Section }[] {
  const out: { item: Item; section: Section }[] = [];
  for (const s of o?.sections ?? []) for (const it of walk(s.items)) if (it.fork) out.push({ item: it, section: s });
  return out;
}

// ------------------------------------------------------------------ the outline as text

/** The outline as numbered text, for the agent ("evaluate the story", "what is missing here"). */
export function outlineText(o: Outline, lang: string, opts: { abandoned?: boolean } = {}): string {
  const lines: string[] = [];
  const state = (i: Item) => (i.state === 'holds' ? '' : ` [${i.state}]`);
  const steps = (ss: Step[], indent: string) => {
    for (const st of liveSteps(ss, !!opts.abandoned)) {
      const par = st.items.length > 1;
      for (const it of st.items) {
        const mark = par ? '‖ ' : '';
        lines.push(`${indent}${it.num} ${mark}${it.text}${it.derived ? ' (derived)' : ''}${state(it)}`);
        steps(it.children, indent + '  ');
        if (it.fork) {
          for (const d of it.fork.directions) {
            if (d.state === 'abandoned' && !opts.abandoned) continue;
            const chosen = it.fork.chosen === d.id ? ' (chosen)' : '';
            lines.push(`${indent}  ↳ direction ${d.direction}${chosen}: ${d.text}${state(d)}${d.why ? ` — given up: ${d.why}` : ''}`);
            steps(d.children, indent + '    ');
          }
        }
      }
      if (par && st.note) lines.push(`${indent}  (parallel: ${st.note})`);
    }
  };
  for (const s of o.sections) {
    lines.push(`§${s.num} ${bi(s.title, lang)} [${s.phase}]${s.role ? ` — ${s.role}` : ''}`);
    steps(s.items, '  ');
  }
  return lines.join('\n');
}

// ------------------------------------------------------------------ a structured draft, as the outline will be

export interface PlannedSection {
  key: string | null; title: string; role: string; phase: SectionPhase;
  items: DraftStep[]; notes: Record<string, string>; fromTemplate: boolean;
}

/** Where a draft's sections land (what outline/service.py init does): every template section in order, a draft
 *  section's items in the template section it names (by key, else by title), and a section the template does not have
 *  right after the one before it. */
export function arrangeDraft(template: Template | null, draft: Draft | null, lang: string): PlannedSection[] {
  const out: PlannedSection[] = (template?.sections ?? []).map(s => ({
    key: s.key, title: bi(s.title, lang), role: bi(s.role, lang), phase: s.phase, items: [], notes: {}, fromTemplate: true,
  }));
  let last: number | null = null;
  for (const spec of draft?.sections ?? []) {
    let idx = spec.key ? out.findIndex(x => x.fromTemplate && x.key === spec.key) : -1;
    if (idx < 0 && template) {
      const title = (spec.title ?? '').trim().toLowerCase();
      const key = title ? template.sections.find(s => [s.title.zh, s.title.en].some(x => (x ?? '').toLowerCase() === title))?.key : undefined;
      if (key) idx = out.findIndex(x => x.fromTemplate && x.key === key);
    }
    if (idx < 0) {
      idx = last === null ? out.length : last + 1;
      out.splice(idx, 0, { key: null, title: spec.title || '…', role: spec.role ?? '', phase: spec.phase ?? 'insight', items: [], notes: {}, fromTemplate: false });
    }
    const base = out[idx].items.length;
    out[idx].items.push(...spec.items);
    for (const [k, v] of Object.entries(spec.notes ?? {})) out[idx].notes[String(base + Number(k))] = v;
    last = idx;
  }
  return out;
}

export function draftCount(steps: DraftStep[]): number {
  return steps.reduce((n, st) => n + (Array.isArray(st) ? st : [st]).reduce((m, it) => m + 1 + draftCount(it.children ?? []), 0), 0);
}

/** A new node id from a title: prefix.slug, made unique among `taken` (Chinese titles have no ASCII slug: a short
 *  random one then). */
export function slugId(prefix: string, title: string, taken: Set<string>): string {
  const base = title.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32).replace(/-+$/, '')
    || Math.random().toString(36).slice(2, 8);
  let id = `${prefix}.${base}`;
  for (let n = 2; taken.has(id); n++) id = `${prefix}.${base}-${n}`;
  return id;
}

// ------------------------------------------------------------------ the outline in a paper file

/** What a .tex / .md file says about the outline: `% rd:sec <section>` regions (up to `% rd:end` or the next one),
 *  `% rd:describes <item>` / `\rdref{<item>}` markers (the first line naming each item), and its section headings.
 *  Markdown writes the markers as comments: `<!-- rd:sec … -->`, `<!-- rd:describes … -->`. */
export interface DocMarks {
  regions: { sec: string; line: number; end: number }[];
  describes: Map<string, number>;
  headings: { title: string; label: string | null; line: number }[];
  /** The outline file's own tags (outline/doc.py): `<!-- rd:item <id> -->` at the end of an item's line. */
  items: Map<string, number>;
  lines: number;
}

const SEC_LINE = /^\s*(?:%|<!--)\s*rd:sec\s+([^\s>]+)/;
/** The outline file's section heading: `## 1 Title <!-- rd:sec <id> -->` (the section runs to the next one). */
const SEC_HEAD_TAG = /^ {0,3}##(?!#).*?<!--\s*rd:sec\s+([^\s>]+?)\s*-->/;
const ITEM_TAG = /<!--\s*rd:item\s+([^\s>]+?)\s*-->/;
const END_LINE = /^\s*(?:%|<!--)\s*rd:end\b/;
const DESCRIBES = /(?:%|<!--)\s*rd:describes\s+([^\s>]+)|\\rdref\{([^}]+)\}/g;
const HEADING = /^\s*(?:\\section\*?\{([^}]*)\}(?:\s*\\label\{([^}]*)\})?|#{1,2}\s+(.+))/;

export function docMarks(text: string): DocMarks {
  const lines = text.split('\n');
  const regions: DocMarks['regions'] = [];
  const describes = new Map<string, number>();
  const headings: DocMarks['headings'] = [];
  const items = new Map<string, number>();
  let open: { sec: string; line: number } | null = null;
  lines.forEach((raw, i) => {
    const n = i + 1;
    const s = SEC_LINE.exec(raw);
    if (s) {
      if (open) regions.push({ ...open, end: n - 1 });
      open = { sec: s[1], line: n };
      return;
    }
    if (END_LINE.test(raw)) { if (open) regions.push({ ...open, end: n }); open = null; return; }
    const head = SEC_HEAD_TAG.exec(raw);
    if (head) {
      if (open) regions.push({ ...open, end: n - 1 });
      open = { sec: head[1], line: n };
    }
    const tag = ITEM_TAG.exec(raw);
    if (tag && !items.has(tag[1])) items.set(tag[1], n);
    for (const m of raw.matchAll(DESCRIBES)) {
      const id = (m[1] || m[2]).replace(/^node:/, '');
      if (!describes.has(id)) describes.set(id, n);
    }
    const h = HEADING.exec(raw);
    if (h) headings.push({ title: (h[1] ?? h[3] ?? '').trim().replace(/^§?\s*\d+(?:\.\d+)*\.?\s+/, ''), label: h[2] ?? null, line: n });
  });
  if (open) regions.push({ ...(open as { sec: string; line: number }), end: lines.length });
  return { regions, describes, headings, items, lines: lines.length };
}

/** The outline section the line is in: its `% rd:sec` region, else the heading above it (by title or by
 *  \label{sec:<key>}), else the section most of the file's markers belong to. */
export function sectionAt(o: Outline | null | undefined, marks: DocMarks, line: number): string | null {
  if (!o) return null;
  const ids = new Set(o.sections.map(s => s.id));
  const region = marks.regions.find(r => line >= r.line && line <= r.end && ids.has(r.sec));
  if (region) return region.sec;
  const norm = (x: string) => x.trim().toLowerCase().replace(/\s+/g, ' ');
  const heading = [...marks.headings].reverse().find(h => h.line <= line) ?? marks.headings[0];
  if (heading) {
    const byLabel = heading.label?.match(/^sec:(.+)$/)?.[1];
    if (byLabel && ids.has(`sec.${byLabel}`)) return `sec.${byLabel}`;
    const hit = o.sections.find(s => [s.title.zh, s.title.en].some(x => x && norm(x) === norm(heading.title)));
    if (hit) return hit.id;
  }
  const counts = new Map<string, number>();
  const owner = new Map<string, string>();
  for (const s of o.sections) for (const it of walk(s.items)) owner.set(it.id, s.id);
  for (const id of marks.describes.keys()) { const s = owner.get(id); if (s) counts.set(s, (counts.get(s) ?? 0) + 1); }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

export type WriteState = 'here' | 'written' | 'elsewhere' | 'todo';

/** How far the text has got with each item of a section: being written (the marker nearest above the cursor), written
 *  here (a marker in this file), written in another file (the map's describes edges), or not yet. */
export function writeStates(section: Section, marks: DocMarks, cursor: number): Map<string, WriteState> {
  const out = new Map<string, WriteState>();
  let here: string | null = null, best = 0;
  for (const it of walk(section.items)) {
    const at = marks.describes.get(it.id);
    if (at && at <= cursor && at > best) { best = at; here = it.id; }
  }
  for (const it of walk(section.items)) {
    out.set(it.id, it.id === here ? 'here' : marks.describes.has(it.id) ? 'written' : it.written.length ? 'elsewhere' : 'todo');
  }
  return out;
}

/** The marker lines for a file: LaTeX comments in .tex, HTML comments in Markdown. */
export function markerLines(path: string | null, marks: { sec?: string; describes: string }): string[] {
  const md = !!path && /\.(md|markdown)$/i.test(path);
  const line = (body: string) => (md ? `<!-- ${body} -->` : `% ${body}`);
  return [...(marks.sec ? [line(`rd:sec ${marks.sec}`)] : []), line(`rd:describes ${marks.describes}`)];
}

// ------------------------------------------------------------------ the outline file (outline/doc.py)

/** Where an item or a section is in the outline file: the line of its tag, or null. */
export function lineOf(marks: DocMarks, id: string): number | null {
  return marks.items.get(id) ?? marks.regions.find(r => r.sec === id)?.line ?? null;
}

/** In the outline file, the item at the cursor: the nearest tagged line of the section at or above it. */
export function itemAt(section: Section, marks: DocMarks, cursor: number): string | null {
  let best = 0, at: string | null = null;
  for (const it of walk(section.items)) {
    const line = marks.items.get(it.id);
    if (line && line <= cursor && line > best) { best = line; at = it.id; }
  }
  return at;
}

export interface TextEdit { from: number; to: number; insert: string }

const FILE_HEAD = /^ {0,3}##(?:[ \t]+(.*?))?[ \t]*$/;
const ANY_TAG = /[ \t]*<!--\s*rd:(sec|item)\s+([^\s>]+?)\s*-->/g;
const SEC_ID = /^sec\.[A-Za-z0-9][A-Za-z0-9._-]*$/;
const ITEM_ID = /^claim\.[A-Za-z0-9][A-Za-z0-9._-]*$/;
const DIRECTION = /^↳[ \t]*(?:(?:direction|方向)[ \t]*\d*[ \t]*)?(?:[(（][ \t]*(?:chosen|选定|已选)[ \t]*[)）][ \t]*)?[:：]?[ \t]*/i;
const TAG_END = /[ \t]*[(（][ \t]*(?:derived|推导|proposed|agent 提议|提议)[ \t]*[)）][ \t]*$/i;

/** What an item line says, without its bullet, number, ‖, ↳ label, tags and (derived) / (proposed): empty while a
 *  line is only being started. The same rules as outline/doc.py parse(). */
export function itemText(body: string): string {
  let b = body.replace(ANY_TAG, '').trim().replace(/^(?:[-*+]|\d+[.)])(?:[ \t]+|$)/, '');
  if (b.startsWith('↳')) b = b.replace(DIRECTION, '');
  b = b.replace(/^\*\*\d+(?:\.\d+)*\*\*\s*/, '').replace(/^[‖∥][ \t]*/, '');
  for (let m = TAG_END.exec(b); m && m.index > 0; m = TAG_END.exec(b)) b = b.slice(0, m.index);
  return b.trim();
}

function randomItemId(): string {
  const bytes = new Uint8Array(4);
  crypto.getRandomValues(bytes);
  return `claim.i${[...bytes].map(b => b.toString(16).padStart(2, '0')).join('')}`;
}

/** The edits that give the outline file's untagged lines (and lines repeating a tag above them) a tag of their own,
 *  before a save: a new heading `<!-- rd:sec sec.<slug> -->`, a new item `<!-- rd:item claim.i<hex> -->`. A line
 *  keeps its item from one save to the next this way. `known` holds the ids already in use. */
export function outlineTags(text: string, known: Set<string>, newItemId: () => string = randomItemId): TextEdit[] {
  const edits: TextEdit[] = [];
  const seen = new Set<string>();
  const taken = () => new Set([...known, ...seen]);
  let inSection = false, hasItem = false, pos = 0;
  const tagAt = (raw: string, start: number, kind: string, id: string | null, fresh: string) => {
    if (id) {
      const m = [...raw.matchAll(ANY_TAG)].find(x => x[1] === kind && x[2] === id)!;
      const from = start + m.index! + m[0].indexOf(id);
      edits.push({ from, to: from + id.length, insert: fresh });
    } else {
      const end = raw.replace(/[ \t]+$/, '').length;
      edits.push({ from: start + end, to: start + raw.length, insert: ` <!-- rd:${kind} ${fresh} -->` });
    }
  };
  for (const raw of text.split('\n')) {
    const start = pos;
    pos += raw.length + 1;
    const h = FILE_HEAD.exec(raw);
    if (h) {
      const body = h[1] ?? '';
      const id = [...body.matchAll(ANY_TAG)].find(m => m[1] === 'sec')?.[2] ?? null;
      const title = body.replace(ANY_TAG, '').trim().replace(/^(?:§\s*)?\d+(?:\.\d+)*\.?\s+/, '').trim();
      if (!title && !id) continue;                         // "## " being typed: not a section yet
      inSection = true;
      hasItem = false;
      if (id && SEC_ID.test(id) && !seen.has(id)) { seen.add(id); continue; }
      const fresh = slugId('sec', title, taken());
      seen.add(fresh);
      tagAt(raw, start, 'sec', id, fresh);
      continue;
    }
    if (!inSection || !raw.trim()) continue;
    let body = raw.trim();
    const q = /^>[ \t]?(.*)$/.exec(body);
    if (q) {
      const inner = q[1].trim();
      if (/^[‖∥]/.test(inner) || !hasItem) continue;      // a group's note, or the section's role
      body = inner;
    }
    const id = [...body.matchAll(ANY_TAG)].find(m => m[1] === 'item')?.[2] ?? null;
    if (!id && !itemText(body)) continue;
    hasItem = true;
    if (id && ITEM_ID.test(id) && !seen.has(id)) { seen.add(id); continue; }
    let fresh = newItemId();
    while (seen.has(fresh) || known.has(fresh)) fresh = newItemId();
    seen.add(fresh);
    tagAt(raw, start, 'item', id, fresh);
  }
  return edits;
}
