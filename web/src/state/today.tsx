// The data behind Today and the number on it in the navigation: one loader per project, shared through context, that
// reloads (debounced) on 'dag' and 'experiments' events. Research projects load the DAG (graph, gates, proposals,
// recent events) and the runs; engineering projects only the runs.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { get, p } from '../api/client';
import { dagApi } from '../dag/api';
import type { DagEvent, GateStatus, GraphResponse, Proposal } from '../dag-types';
import type { Experiment } from '../types';
import { computeNeeds, computeWaiting, needsCount, type Needs, type Waiting } from '../panels/overview/today';
import { useApp } from './app';
import { isResearch } from './views';

export interface TodayValue {
  graph: GraphResponse | null;
  gates: GateStatus[] | null;
  proposals: Proposal[] | null;
  events: DagEvent[] | null;
  runs: Experiment[] | null;
  needs: Needs;
  waiting: Waiting;
  count: number;
  loaded: boolean;
  error: string | null;
  reload: () => void;
}

const OPEN = new Set<Proposal['state']>(['open', 'needs_rebase']);
const EVENTS = 12;
const Ctx = createContext<TodayValue | null>(null);

interface Raw { graph: GraphResponse | null; gates: GateStatus[] | null; proposals: Proposal[] | null; events: DagEvent[] | null; runs: Experiment[] | null; loaded: boolean; error: string | null }
const EMPTY: Raw = { graph: null, gates: null, proposals: null, events: null, runs: null, loaded: false, error: null };

export function TodayProvider({ children }: { children: ReactNode }) {
  const { projectId, project, projects, onEvent } = useApp();
  const known = project && project.id === projectId ? project : projects.find(x => x.id === projectId) ?? null;
  const research = !!known && isResearch(known);
  const [raw, setRaw] = useState<Raw>(EMPTY);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!projectId || !known) return;
    const mine = ++seq.current;
    const none = Promise.resolve(null);
    const [graph, gates, open, rebase, events, runs] = await Promise.allSettled([
      research ? dagApi.graph(projectId) : none,
      research ? dagApi.gates(projectId) : none,
      research ? dagApi.proposals(projectId, 'open') : none,
      research ? dagApi.proposals(projectId, 'needs_rebase') : none,
      research ? dagApi.timeline(projectId) : none,
      get<Experiment[]>(p(projectId, '/experiments')),
    ]);
    if (mine !== seq.current) return;
    const ok = <T,>(r: PromiseSettledResult<T | null>, old: T | null): T | null => (r.status === 'fulfilled' ? r.value : old);
    setRaw(prev => {
      const props = [open, rebase].flatMap(r => (r.status === 'fulfilled' && r.value ? r.value : []));
      const seen = new Set<string>();
      const ev = ok(events, prev.events);
      const g = ok(graph, prev.graph);
      return {
        graph: g,
        gates: ok(gates, prev.gates),
        proposals: open.status === 'fulfilled' || rebase.status === 'fulfilled'
          ? props.filter(x => OPEN.has(x.state) && !seen.has(x.id) && (seen.add(x.id), true)) : prev.proposals,
        events: ev ? [...ev].sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0)).slice(0, EVENTS) : null,
        runs: ok(runs, prev.runs),
        loaded: true,
        error: graph.status === 'rejected' && !g ? String((graph.reason as Error)?.message ?? graph.reason) : null,
      };
    });
  // `known` changes identity on every project reload; what matters is the id and the kind.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, research, !!known]);

  useEffect(() => { setRaw(EMPTY); load(); }, [load]);
  useEffect(() => {
    let timer = 0;
    const soon = () => { window.clearTimeout(timer); timer = window.setTimeout(() => load(), 400); };
    const offs = ['dag', 'experiments'].map(topic => onEvent(topic, soon));
    return () => { offs.forEach(off => off()); window.clearTimeout(timer); };
  }, [onEvent, load]);

  const value = useMemo<TodayValue>(() => {
    const needs = computeNeeds(raw.graph, raw.proposals, raw.runs);
    return { ...raw, needs, waiting: computeWaiting(raw.graph), count: needsCount(needs), reload: load };
  }, [raw, load]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useToday(): TodayValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToday outside TodayProvider');
  return v;
}
