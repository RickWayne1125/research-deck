// The outline's JSON (server/research_deck/outline/model.py) and its routes (docs/API.md § Outline).
import { del, get, p, patch, post, put } from '../../api/client';

export type Phase = 'idea' | 'insight' | 'design' | 'evaluation';
export type SectionPhase = Phase | 'summary';
export const PHASES: Phase[] = ['idea', 'insight', 'design', 'evaluation'];
export const SECTION_PHASES: SectionPhase[] = [...PHASES, 'summary'];

/** holds: everything under it is done; choose: a fork waits for a direction; pending: a summary item whose items do
 *  not hold yet; needs_tasks: nothing backs it yet; locked: its tasks wait for a later phase. */
export type ItemState = 'holds' | 'doing' | 'blocked' | 'todo' | 'locked' | 'needs_tasks' | 'choose' | 'pending' | 'proposed' | 'abandoned';
export type TaskType = 'lit' | 'code' | 'fig' | 'exp';
export const TASK_TYPES: TaskType[] = ['lit', 'code', 'fig', 'exp'];
/** As stored: todo, doing, blocked, done, sugg (an agent's suggestion); as shown, also locked (waits for its phase). */
export type TaskStatus = 'todo' | 'doing' | 'blocked' | 'done' | 'sugg' | 'locked';
export type Bi = { zh?: string; en?: string };

export interface Evidence { id: string; kind: string; rel: 'evidence' | 'basis' | 'cites'; title: string; status: string; level: string | null }
export interface Step { items: Item[]; note: string | null }
export interface Item {
  id: string; num: string; depth: number; section: string; parent: string;
  direction: number | null;                    // 1, 2, … when it is a direction of a fork
  text: string; status: string; derived: boolean; condition: string; summary_of: string[];
  why?: string | null; why_kind?: string | null; ended_at?: string | null;
  children: Step[];
  fork: { directions: Item[]; chosen: string | null } | null;
  tasks: string[]; suggested: string[]; evidence: Evidence[];
  written: { section: string; file: string | null }[];
  proposals: string[];
  kids: { total: number; holds: number };
  state: ItemState;
}
export interface Section {
  id: string; num: string; title: Bi; role: string; phase: SectionPhase; status: string; items: Step[];
  counts: { items: number; holds: number };
}
export interface Group {
  phase: SectionPhase; sections: string[]; state: 'done' | 'current' | 'later' | 'summary';
  items: number; holds: number; tasks: number; tasks_done: number; missing: string[];
}
export interface TaskLinks { node?: string; figure?: string; survey?: string; branch?: string; path?: string }
export interface Task {
  id: string; type: TaskType; title: string; items: string[]; status: TaskStatus; set_status: TaskStatus;
  note: string; assignee: '' | 'me' | 'agent'; links: TaskLinks; by: string; created_at: string; updated_at: string;
  /** Why the shown status differs from the set one: run_failed, stale, survey_<status>. */
  reason: string | null;
  phase: Phase | null; nums: string[]; abandoned: boolean;
}
export type Pending =
  | { kind: 'fork'; item: string; num: string; text: string }
  | { kind: 'proposed_item'; item: string; num: string; text: string }
  | { kind: 'blocked_task'; task: string; title: string; note: string; reason: string | null; nums: string[] }
  | { kind: 'suggested_task'; task: string; title: string; nums: string[] }
  | { kind: 'proposal'; proposal: string; title: string };
export interface Outline {
  has_outline: boolean; template: string | null; phases: Record<Phase, Bi>;
  project_phase: Phase; stage_mode: string;
  sections: Section[]; groups: Group[]; tasks: Task[];
  counts: { done: number; doing: number; todo: number; blocked: number; total: number; abandoned: number; suggested: number };
  pending: Pending[];
  loose: { id: string; kind: string; title: string; status: string }[];
}

export interface TemplateSection { key: string; title: Bi; role: Bi | string; phase: SectionPhase; tasks?: TaskType[] }
export interface Template {
  id: string; name: Bi | string; description?: Bi | string; builtin?: boolean; overrides?: boolean;
  phases: Record<Phase, Bi>; sections: TemplateSection[];
}

/** A structured draft (outline/structure.py): a step is an item or a list of parallel items. */
export interface DraftItem { text: string; children: DraftStep[]; derived?: boolean }
export type DraftStep = DraftItem | DraftItem[];
export interface DraftSection { key: string | null; title: string; items: DraftStep[]; notes?: Record<string, string>; phase?: SectionPhase; role?: string }
export interface Draft { sections: DraftSection[]; changes: string[]; by?: 'agent' | 'parse' }

export type OutlineOp = { op: string; [k: string]: unknown };
export interface OpsResult { applied: boolean; created: string[]; last: string | null; proposal?: string | null }

export const outlineApi = {
  get: (pid: string, lang: string) => get<Outline>(p(pid, '/outline'), { lang }),
  ops: (pid: string, ops: OutlineOp[], lang: string) => post<OpsResult>(p(pid, '/outline/ops'), { ops, lang }),
  init: (pid: string, template: string, lang: string, structure?: { sections: DraftSection[] } | null) =>
    post<OpsResult>(p(pid, '/outline/init'), { template, lang, structure: structure ?? null }),
  structure: (pid: string, text: string, template: string, lang: string, agent = true) =>
    post<Draft>(p(pid, '/outline/structure'), { text, template, lang, agent }),
  extract: (pid: string, name: string, base64: string) => post<{ text: string }>(p(pid, '/outline/extract'), { name, content_base64: base64 }),
  saveTemplate: (pid: string, id: string, name: string) => post<Template>(p(pid, '/outline/save-template'), { id, name }),
  tasks: (pid: string) => get<Task[]>(p(pid, '/tasks')),
  createTask: (pid: string, t: Partial<Task> & { type: TaskType; title: string; items: string[] }) => post<Task>(p(pid, '/tasks'), t),
  updateTask: (pid: string, tid: string, t: Partial<Task>) => patch<Task>(p(pid, `/tasks/${encodeURIComponent(tid)}`), t),
  deleteTask: (pid: string, tid: string) => del<{ ok: boolean }>(p(pid, `/tasks/${encodeURIComponent(tid)}`)),
  templates: () => get<Template[]>('/api/outline/templates'),
  template: (id: string) => get<Template>(`/api/outline/templates/${encodeURIComponent(id)}`),
  putTemplate: (t: Template) => put<Template>(`/api/outline/templates/${encodeURIComponent(t.id)}`, t),
  deleteTemplate: (id: string) => del<{ ok: boolean }>(`/api/outline/templates/${encodeURIComponent(id)}`),
};
