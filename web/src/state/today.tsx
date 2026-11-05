// The data behind what waits for the researcher and the number on it in the navigation: one loader per project, shared
// through context, that reloads (debounced) on 'dag' and 'experiments' events. Research projects load the DAG (graph,
// gates, proposals, recent events), the runs, the latest early survey (kept current from its 'survey' events) and the
// outline (its own loader, reloaded on 'outline', 'dag' and 'experiments' events, and at once after an outline change);
// engineering projects only the runs. In a research project the list sits at the top of the outline page, and the
// outline's own items (forks to choose, drafted items, blocked and suggested tasks) count with Today's.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { get, p } from '../api/client';
import { dagApi } from '../dag/api';
import type { DagEvent, GateStatus, GraphResponse, Proposal } from '../dag-types';
import type { Experiment } from '../types';
import { startApi, type Survey } from '../start/api';
import { computeNeeds, computeWaiting, needsCount, type Needs, type Waiting } from '../panels/overview/today';
import { outlineApi, type Outline } from '../panels/outline/api';
import { outlineItemIds, outlinePending } from '../panels/outline/model';
import { useI18n } from '../i18n';
import { useApp } from './app';
import { isResearch } from './views';

export interface TodayValue {
  graph: GraphResponse | null;
  gates: GateStatus[] | null;
  proposals: Proposal[] | null;
  events: DagEvent[] | null;
  runs: Experiment[] | null;
  survey: Survey | null;
  /** The outline (research projects; null until loaded or for an engineering project). */
  outline: Outline | null;
  /** Reload the outline now (after an outline or task change). */
  reloadOutline: () => Promise<void>;
  /** The outline task being worked on (shown above Experiments, Code and Paper), per project for this tab. */
  activeTask: string | null;
  setActiveTask: (id: string | null) => void;
  /** Today's items, without the outline's own items (the outline page shows those itself). */
  needs: Needs;
  waiting: Waiting;
  /** One per card that asks for a decision, the outline's pending items included. */
  count: number;
  loaded: boolean;
  error: string | null;
  reload: () => void;
}

const OPEN = new Set<Proposal['state']>(['open', 'needs_rebase']);
const EVENTS = 12;
const Ctx = createContext<TodayValue | null>(null);

interface Raw { graph: GraphResponse | null; gates: GateStatus[] | null; proposals: Proposal[] | null; events: DagEvent[] | null; runs: Experiment[] | null; survey: Survey | null; loaded: boolean; error: string | null }
const EMPTY: Raw = { graph: null, gates: null, proposals: null, events: null, runs: null, survey: null, loaded: false, error: null };

export function TodayProvider({ children }: { children: ReactNode }) {
  const { projectId, project, projects, onEvent } = useApp();
  const { lang } = useI18n();
  const known = project && project.id === projectId ? project : projects.find(x => x.id === projectId) ?? null;
  const research = !!known && isResearch(known);
  const [raw, setRaw] = useState<Raw>(EMPTY);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!projectId || !known) return;
    const mine = ++seq.current;
    const none = Promise.resolve(null);
    const [graph, gates, open, rebase, events, runs, survey] = await Promise.allSettled([
      research ? dagApi.graph(projectId) : none,
      research ? dagApi.gates(projectId) : none,
      research ? dagApi.proposals(projectId, 'open') : none,
      research ? dagApi.proposals(projectId, 'needs_rebase') : none,
      research ? dagApi.timeline(projectId) : none,
      get<Experiment[]>(p(projectId, '/experiments')),
      research ? startApi.survey(projectId) : none,
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
        survey: ok(survey, prev.survey),
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
    offs.push(onEvent('survey', e => { if (e.payload?.id) setRaw(prev => ({ ...prev, survey: e.payload as Survey })); }));
    return () => { offs.forEach(off => off()); window.clearTimeout(timer); };
  }, [onEvent, load]);

  // The outline: its own small loader, so an outline change does not reload the map.
  const [outline, setOutline] = useState<{ pid: string; data: Outline } | null>(null);
  const oseq = useRef(0);
  const loadOutline = useCallback(async () => {
    if (!projectId || !research) { setOutline(null); return; }
    const mine = ++oseq.current;
    try {
      const data = await outlineApi.get(projectId, lang);
      if (mine === oseq.current) setOutline({ pid: projectId, data });
    } catch { /* keep the last one; the page shows the map's error */ }
  }, [projectId, research, lang]);
  useEffect(() => { loadOutline(); }, [loadOutline]);
  const taskKey = `rd.outline.task.${projectId ?? ''}`;
  const [activeTask, setActive] = useState<string | null>(null);
  useEffect(() => { try { setActive(sessionStorage.getItem(taskKey)); } catch { setActive(null); } }, [taskKey]);
  const setActiveTask = useCallback((id: string | null) => {
    setActive(id);
    try { if (id) sessionStorage.setItem(taskKey, id); else sessionStorage.removeItem(taskKey); } catch { /* storage unavailable */ }
  }, [taskKey]);
  useEffect(() => {
    let timer = 0;
    const soon = () => { window.clearTimeout(timer); timer = window.setTimeout(() => loadOutline(), 300); };
    const offs = ['outline', 'dag', 'experiments', 'figures'].map(topic => onEvent(topic, soon));
    return () => { offs.forEach(off => off()); window.clearTimeout(timer); };
  }, [onEvent, loadOutline]);

  const value = useMemo<TodayValue>(() => {
    const o = outline && outline.pid === projectId ? outline.data : null;
    const all = computeNeeds(raw.graph, raw.proposals, raw.runs);
    const inOutline = outlineItemIds(o);
    const needs = { ...all, review: all.review.filter(n => !inOutline.has(n.id)) };
    const w = computeWaiting(raw.graph);         // an outline item without backing shows on the outline itself
    const waiting = { ...w, evidence: w.evidence.filter(n => !inOutline.has(n.id)) };
    return { ...raw, outline: o, reloadOutline: loadOutline, activeTask, setActiveTask, needs, waiting,
             count: needsCount(needs) + outlinePending(o).length, reload: load };
  }, [raw, load, outline, projectId, loadOutline, activeTask, setActiveTask]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useToday(): TodayValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToday outside TodayProvider');
  return v;
}
