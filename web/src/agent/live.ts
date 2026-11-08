// The live answer in the project conversation, as pure functions of the run's events (agents/runner.py, AgentEvent):
// what the dock shows while an answer streams, which steered messages are still waiting to be read, and how a
// restarted server's replay starts over. The dock (AgentDock.tsx) holds the state; these are tested on their own.
import type { AgentEvent, RunContext, RunStarted } from '../types';

export interface ToolCall { name: string; detail?: string }
export interface RunExtras { tools: ToolCall[]; usage?: Extract<AgentEvent, { type: 'usage' }>; duration?: number }

/** The answer the live area shows: started here, by the queue, in another tab, or going when the page opened. */
export interface Live {
  runId: string | null;                     // null while the request that starts it is on its way
  prompt: string | null; ctx?: RunContext;  // known when it started here; otherwise the transcript has it
  status: 'running' | 'done' | 'error' | 'cancelled';
  events: AgentEvent[]; error: string | null;
  meta: Pick<RunStarted, 'provider' | 'model' | 'effort' | 'fast'> | null;
  steerable: boolean;                       // a message reaches the running turn (Claude); else steering restarts it
}
/** A message steered in from this page that the answer has not reported yet (its steer event carries `id`). */
export interface SentSteer { key: string; runId: string; text: string; id?: string }

export const isTool = (e: AgentEvent): e is Extract<AgentEvent, { type: 'tool' }> => e.type === 'tool';
export const isUsage = (e: AgentEvent): e is Extract<AgentEvent, { type: 'usage' }> => e.type === 'usage';
export const isDone = (e: AgentEvent): e is Extract<AgentEvent, { type: 'done' }> => e.type === 'done';

export function applyEvent(l: Live, e: AgentEvent): Live {
  if (e.type === 'reset') return { ...l, status: 'running', events: [], error: null };   // a new server replays it
  const next: Live = { ...l, events: [...l.events, e] };
  if (e.type === 'start') {
    if (!l.meta) next.meta = { provider: e.provider as RunStarted['provider'], model: e.model, effort: e.effort, fast: e.fast };
    if (e.steerable !== undefined) next.steerable = e.steerable;
  }
  if (e.type === 'error') next.error = e.message;
  if (e.type === 'done') next.status = e.cancelled ? 'cancelled' : e.ok ? 'done' : 'error';
  return next;
}

/** Messages steered into the answer that the agent has not read yet: its steer events without a user event, then
 *  those sent from this page that it has not reported yet. */
export function pendingSteers(live: Live, sent: SentSteer[]): { key: string; text: string }[] {
  const read = new Set(live.events.flatMap(e => (e.type === 'user' && e.id ? [e.id] : [])));
  const handed = live.events.filter((e): e is Extract<AgentEvent, { type: 'steer' }> => e.type === 'steer');
  const known = new Set(handed.map(e => e.id));
  return [
    ...handed.filter(e => !read.has(e.id)).map(e => ({ key: e.id, text: e.text })),
    ...sent.filter(s => s.runId === live.runId && !(s.id && (known.has(s.id) || read.has(s.id)))).map(s => ({ key: s.key, text: s.text })),
  ];
}

/** The answer as it streams: split where the agent read a steered message, each part with its own tool calls. */
export interface Segment { user?: string; tools: ToolCall[]; text: string }
export function segmentsOf(events: AgentEvent[]): Segment[] {
  const segs: Segment[] = [{ tools: [], text: '' }];
  for (const e of events) {
    const cur = segs[segs.length - 1];
    if (e.type === 'text') cur.text += e.delta;
    else if (e.type === 'tool') cur.tools.push({ name: e.name, detail: e.detail });
    else if (e.type === 'user') segs.push({ user: e.text, tools: [], text: '' });
  }
  return segs;
}
