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
