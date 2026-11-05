// The research map (docs/DAG.md §8): a list grouped by the four steps (the default) or the graph (stage lanes, rail,
// attempts, typed edges); filter chips (all, to review, needs attention, confirmed, abandoned); the node details
// (the inspector) on the side; and impact preview for every what-if edit, rollback, relink and choice.
// Route: #/<project>/dag[/<node id>[/<inspector tab>] | /filter:<all|proposed|attention|confirmed|dead>].
// All reads and writes go through dagApi (docs/DAG.md §7); a 'dag' event reloads the graph.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, get, p as path } from '../../api/client';
import { Icon } from '../../components/icons';
import { Button, Empty, ErrorNote, IconButton, PanelHead, Segmented, Spinner } from '../../components/ui';
import { ResizeHandle, useResizableWidth } from '../../components/resize';
import { useT } from '../../i18n';
import { useApp, useLiveReload } from '../../state/app';
import { useToday } from '../../state/today';
import { leaving, stepOfStage } from '../../state/stages';
import { dagApi } from '../../dag/api';
import { useDagLabels } from '../../dag/encoding';
import type { DagEvent, DagNode, GateStatus, GraphResponse, Impact, Op, OpsResult, RunSummary } from '../../dag-types';
import { NextStepDialog } from '../overview/NextStep';
import { Legend, Toasts, useToasts } from './Chrome';
import { GateDialog, NewNodeDialog, StatusDialog } from './Dialogs';
import { ImpactPanel, type ApplyArgs } from './ImpactPanel';
import { Inspector, isTab, type InspectorTab, type StatusAction } from './Inspector';
import { ListView } from './ListView';
import { MapView } from './MapView';
import { FILTERS, filterMembers, isFilter, legacyFilter, verdictsByNode, type Filter } from './model';
import { errText, usePreview, type PreviewReq } from './preview';
import './dag.css';
import './i18n';

type View = 'list' | 'graph';
// The details / impact side panel: 320 px (the inspector's tab row) up to what leaves the map 320 px (at most 760 px).
const SIDE_MIN = 320;
const sideDefault = () => (window.innerWidth <= 1280 ? 360 : 412);
const sideMax = (body: HTMLElement | null) => Math.max(SIDE_MIN, Math.min(760, (body?.clientWidth ?? window.innerWidth) - 320));
interface FigureLite { id: string; node_id?: string | null; updated_at?: string | null; preview?: string | null }

/** The view's sub-route: "filter:<name>" (older links: "lens:<name>"), "<node id>" or "<node id>/<inspector tab>". */
function parseSub(sub: string | null): { filter: Filter | null; node: string | null; tab: InspectorTab | null } {
  if (!sub) return { filter: null, node: null, tab: null };
  if (sub.startsWith('filter:')) { const f = sub.slice(7); return { filter: isFilter(f) ? f : null, node: null, tab: null }; }
  if (sub.startsWith('lens:')) return { filter: legacyFilter(sub.slice(5)), node: null, tab: null };
  const [node, tab] = sub.split('/');
  return { filter: null, node: node || null, tab: isTab(tab) ? tab : null };
}

function useStored<T extends string>(key: string, initial: T, allowed: readonly T[]): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try { const s = localStorage.getItem(key) as T | null; return s && allowed.includes(s) ? s : initial; } catch { return initial; }
  });
  const set = useCallback((next: T) => { setV(next); try { localStorage.setItem(key, next); } catch { /* storage unavailable */ } }, [key]);
  return [v, set];
}

export default function DagPanel() {
  const { projectId, project, sub, navigate, askAgent } = useApp();
  const pid = projectId!;
  const t = useT();
  const L = useDagLabels();
  const toasts = useToasts();
  const today = useToday();
  const rootRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const sideW = useResizableWidth('rd.dag.sideW', sideDefault, SIDE_MIN, () => sideMax(bodyRef.current), { cssVar: '--dg-side-w', target: rootRef });

  // ---------------------------------------------------------------- data
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [loadError, setLoadError] = useState<{ status: number | null; msg: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [gates, setGates] = useState<GateStatus[]>([]);
  const [events, setEvents] = useState<DagEvent[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [figures, setFigures] = useState<FigureLite[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    const [g, gt, ev, rn] = await Promise.allSettled([
      dagApi.graph(pid, { dead: true }), dagApi.gates(pid), dagApi.timeline(pid), dagApi.runs(pid),
    ]);
    if (g.status === 'fulfilled') { setGraph(g.value); setLoadError(null); }
    else {
      const e = g.reason;
      setLoadError({ status: e instanceof ApiError ? e.status : null, msg: errText(e) });
      if (e instanceof ApiError && e.status === 404) setGraph(null);
    }
    if (gt.status === 'fulfilled') setGates(gt.value ?? []);
    if (ev.status === 'fulfilled') setEvents(ev.value ?? []);
    if (rn.status === 'fulfilled') setRuns(rn.value ?? []);
    setLoading(false);
  }, [pid]);
  useEffect(() => { load(); }, [load]);

  // Live: debounce bursts of 'dag' events (an op batch publishes once, a run campaign many times).
  const loadRef = useRef(load);
  loadRef.current = load;
  const timer = useRef(0);
  const soon = useCallback(() => { window.clearTimeout(timer.current); timer.current = window.setTimeout(() => loadRef.current(), 250); }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useLiveReload(['dag'], soon);

  // Drawn-figure thumbnails come from the figure registry, when it exists.
  const loadFigures = useCallback(() => { get<FigureLite[]>(path(pid, '/figures')).then(f => setFigures(Array.isArray(f) ? f : [])).catch(() => {}); }, [pid]);
  useEffect(() => { loadFigures(); }, [loadFigures]);
  useLiveReload(['figures'], loadFigures);

  const runNode = useMemo(() => new Map(runs.map(r => [r.id, r.node])), [runs]);
  const runCount = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of runs) m.set(r.node, (m.get(r.node) ?? 0) + 1);
    return m;
  }, [runs]);
  const thumbs = useMemo(() => new Map(figures.filter(f => f.node_id && f.preview).map(f => [f.node_id!, `${path(pid, `/figures/${encodeURIComponent(f.id)}/preview`)}?v=${encodeURIComponent(f.updated_at ?? '')}`])), [figures, pid]);
  const verdicts = useMemo(() => verdictsByNode(events), [events]);

  // ---------------------------------------------------------------- view state and routing
  const initial = useMemo(() => parseSub(sub), []);   // eslint-disable-line react-hooks/exhaustive-deps
  const [view, setView] = useStored<View>('rd.dag.view2', 'list', ['list', 'graph']);
  const [filter, setFilterState] = useState<Filter>(initial.filter ?? 'all');
  const [selected, setSelected] = useState<string | null>(initial.node);
  const [details, setDetails] = useState(!!initial.tab);             // the inspector, in the list view
  const [tab, setTab] = useState<InspectorTab>(initial.tab ?? 'overview');
  const [centerReq, setCenterReq] = useState<{ id: string; n: number } | null>(initial.node ? { id: initial.node, n: 1 } : null);
  const [railCollapsed, setRailCollapsed] = useStored<'1' | '0'>(`rd.dag.rail.${pid}`, '0', ['1', '0']);
  const [resetN, setResetN] = useState(0);
  const [hoverIds, setHoverIds] = useState<string[]>([]);

  const pushed = useRef<string | null>(sub);
  const push = useCallback((s: string | null) => { pushed.current = s; navigate('dag', s); }, [navigate]);
  // A sub-route we did not push ourselves is a deep link: select a node (and show it), or set the filter.
  useEffect(() => {
    if (sub === pushed.current) return;
    pushed.current = sub;
    const r = parseSub(sub);
    if (r.filter) { setFilterState(r.filter); setSelected(null); setDetails(false); return; }
    if (!r.node) { setSelected(null); return; }
    const id = r.node;
    setSelected(id);
    if (r.tab) { setTab(r.tab); setDetails(true); }
    setCenterReq(c => ({ id, n: (c?.n ?? 0) + 1 }));
  }, [sub]);

  const select = useCallback((id: string | null) => {
    setSelected(id);
    if (!id) setDetails(false);
    push(id ?? (filter !== 'all' ? `filter:${filter}` : null));
  }, [push, filter]);
  const selectAndCenter = useCallback((id: string, nextTab?: string) => {
    setSelected(id);
    if (nextTab && isTab(nextTab)) { setTab(nextTab); setDetails(true); }
    push(id);
    setCenterReq(c => ({ id, n: (c?.n ?? 0) + 1 }));
  }, [push]);
  const openDetails = useCallback((id: string) => { setSelected(id); setDetails(true); setTab('overview'); push(id); }, [push]);
  const setFilter = useCallback((f: Filter) => {
    setFilterState(f);
    if (!selected) push(f !== 'all' ? `filter:${f}` : null);
  }, [push, selected]);

  // ---------------------------------------------------------------- preview / apply
  const preview = usePreview(pid);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState<{ key: string; n: number } | null>(null);

  const reportOps = useCallback((res: OpsResult | null, title: string) => {
    if (res && !res.applied && res.proposal) {
      toasts.push({
        tone: 'info', text: t('dag.toast.proposal', { id: res.proposal.id, title }),
        action: { label: t('dag.toast.openInbox'), run: () => navigate('overview') },
      }, 12000);
    } else {
      toasts.push({ tone: 'ok', text: t('dag.toast.applied', { title }) });
    }
  }, [toasts, t, navigate]);

  const applyPreview = useCallback(async (args: ApplyArgs) => {
    const s = preview.state;
    if (!s?.impact) return;
    setBusy(true);
    try {
      for (const id of args.unlock) await dagApi.unlock(pid, id, args.reason.trim() || s.title);
      const res = s.proposalId
        ? await dagApi.approve(pid, s.proposalId)
        : await dagApi.ops(pid, s.ops, { base_digest: s.impact.base_digest, rationale: args.reason.trim() || undefined });
      setApplied({ key: s.key, n: Date.now() });
      preview.discard();
      setHoverIds([]);
      reportOps(res, s.title);
      if (args.queue) navigate('experiments', 'plan');
      load();
    } catch (e) {
      // 409: the graph moved under the preview (base_vid / digest). Show the server's fresh impact when it sent one.
      if (e instanceof ApiError && e.status === 409) {
        const d = e.detail as { impact?: Impact } | null;
        if (d && typeof d === 'object' && d.impact) preview.setImpact(d.impact, t('dag.preview.rebased'));
        else { toasts.push({ tone: 'warn', text: t('dag.preview.conflict', { msg: errText(e) }) }); load(); }
      } else {
        toasts.push({ tone: 'accent', text: t('dag.toast.failed', { msg: errText(e) }) }, 9000);
      }
    } finally { setBusy(false); }
  }, [preview, pid, reportOps, load, navigate, toasts, t]);

  // An inline what-if belongs to the facet editor of one node: leaving that node drops it.
  useEffect(() => {
    if (preview.state?.inline && preview.state.node !== selected) preview.discard();
  }, [selected, preview]);

  const discardPreview = useCallback(() => {
    const s = preview.state;
    preview.discard();
    setHoverIds([]);
    if (s?.proposalId) dagApi.reject(pid, s.proposalId, 'discarded in the impact preview').catch(() => {});
  }, [preview, pid]);

  const addOp = useCallback((op: Op) => {
    const s = preview.state;
    if (!s) return;
    preview.open({ ...s, ops: [...s.ops, op], inline: false, key: `${s.key}+` });
  }, [preview]);

  const runOps = useCallback(async (ops: Op[], title: string) => {
    try { reportOps(await dagApi.ops(pid, ops, { base_digest: graph?.digest }), title); load(); today.reload(); }
    catch (e) { toasts.push({ tone: 'accent', text: t('dag.toast.failed', { msg: errText(e) }) }, 9000); }
  }, [pid, graph?.digest, reportOps, load, today, toasts, t]);

  // Choosing a decision's option is a what-if first: the side panel shows what it changes before Apply.
  const choose = useCallback((d: DagNode, o: DagNode) => {
    preview.open({ key: `choose:${d.id}:${o.id}`, title: t('dag.list.chooseTitle', { option: L.title(o), decision: L.title(d) }),
      ops: [{ op: 'edit', node: d.id, set: { choice: o.id } }], source: 'other', node: d.id } satisfies PreviewReq);
  }, [preview, t, L]);

  // ---------------------------------------------------------------- dialogs
  const [statusFor, setStatusFor] = useState<{ id: string; action: StatusAction } | null>(null);
  const [gateOpen, setGateOpen] = useState<string | null>(null);
  const [newNode, setNewNode] = useState<'starter' | 'new' | null>(null);
  const [nextStep, setNextStep] = useState(false);

  const onStatus = useCallback((id: string, action: string) => setStatusFor({ id, action: action as StatusAction }), []);
  const onGate = useCallback((g: string) => setGateOpen(g), []);
  const onGroup = useCallback(() => setFilter('dead'), [setFilter]);
  const onToggleRail = useCallback(() => setRailCollapsed(railCollapsed === '1' ? '0' : '1'), [railCollapsed, setRailCollapsed]);
  const onMapSelect = useCallback((id: string | null) => select(id), [select]);
  const accept = useCallback((id: string) => {
    const n = graph?.nodes.find(x => x.id === id);
    runOps([{ op: 'set_status', node: id, to: 'active' }], t('dag.list.accepted', { title: n ? L.title(n) : id }));
  }, [graph, runOps, t, L]);

  const ask = useCallback((id: string, kind: 'explain' | 'fix' | 'free', text?: string) => {
    const n = graph?.nodes.find(x => x.id === id);
    const ev = graph?.eval[id];
    const reasons = (ev?.reasons ?? []).slice(0, 8)
      .map(r => `- ${r.level}: ${r.edge ?? r.addr ?? ''}${r.from != null || r.to != null ? ` (${r.from ?? '∅'} → ${r.to ?? '∅'})` : ''}${r.note ? ` — ${r.note}` : ''}`).join('\n');
    const vars = { id, title: n ? L.title(n) : id, level: ev?.level ? L.fresh(ev.level) : '—', reasons: reasons || '-' };
    const prompt = kind === 'explain' ? t('dag.agent.explainPrompt', vars) : kind === 'fix' ? t('dag.agent.fixPrompt', vars) : (text ?? '');
    askAgent(prompt, { node_id: id });
  }, [graph, askAgent, t, L]);

  // ---------------------------------------------------------------- keyboard: Esc steps back
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.key !== 'Escape' || document.querySelector('.scrim')) return;
      if (preview.state) discardPreview();
      else if (details && view === 'list') setDetails(false);
      else if (selected) select(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [preview.state, discardPreview, details, view, selected, select]);

  // ---------------------------------------------------------------- derived
  const impact = preview.state?.impact ?? null;
  const members = useMemo(() => (graph ? filterMembers(graph, filter) : new Set<string>()), [graph, filter]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map(f => [f, graph ? filterMembers(graph, f).size : 0])) as Record<Filter, number>, [graph]);
  const lensSet = useMemo(() => (graph && filter !== 'all' && filter !== 'dead' && !impact ? members : null), [graph, filter, members, impact]);
  const step = stepOfStage(project?.stage);
  const missing = leaving(step, gates).missing.length;
  const empty = !loading && ((graph && graph.nodes.length === 0) || loadError?.status === 404);

  let side: React.ReactNode = null;
  if (graph && preview.state && !preview.state.inline) {
    side = <ImpactPanel state={preview.state} busy={busy} onApply={applyPreview} onDiscard={discardPreview} onAddOp={addOp}
      onHoverNodes={setHoverIds} readOnly={false} />;
  } else if (graph && selected && (view === 'graph' || details)) {
    side = <Inspector pid={pid} id={selected} graph={graph} tab={tab} onTab={setTab} onClose={() => (view === 'list' ? setDetails(false) : select(null))} onSelect={selectAndCenter}
      readOnly={false} preview={preview} previewBusy={busy} onApplyPreview={applyPreview}
      onHover={setHoverIds} onStatus={onStatus} onRun={runOps} onAsk={ask} onOpenCoding={() => navigate('coding', 'changes')} applied={applied} />;
  }

  const statusNode = statusFor && graph ? graph.nodes.find(n => n.id === statusFor.id) : null;
  const gate = gateOpen ? gates.find(g => g.gate === gateOpen) ?? null : null;
  const live = graph?.nodes.filter(n => !['refuted', 'abandoned', 'superseded'].includes(n.status)).length ?? 0;

  return (
    <div ref={rootRef} className="panel dg-root" style={sideW.style}>
      <PanelHead title={t('nav.dag')} subtitle={graph && graph.nodes.length ? t('dag.subtitle2', { n: live }) : t('dag.subtitleEmpty')}>
        {loading && graph && <Spinner />}
        {graph && graph.nodes.length > 0 && (
          <>
            <Segmented<View> ariaLabel={t('dag.view.aria')} value={view} onChange={setView} options={[
              { value: 'list', label: t('dag.view.list') }, { value: 'graph', label: t('dag.view.graph') },
            ]} />
            <Button size="sm" icon="plus" onClick={() => setNewNode('new')}>{t('dag.new.button')}</Button>
            {view === 'graph' && <IconButton icon="refresh" label={t('dag.resetLayout')} onClick={() => setResetN(n => n + 1)} />}
            {view === 'graph' && <Legend />}
          </>
        )}
      </PanelHead>

      {graph && graph.nodes.length > 0 && (
        <div className="dg-toolbar">
          <div className="dg-filters" role="group" aria-label={t('dag.filter.aria')}>
            {FILTERS.map(f => (
              <button key={f} type="button" className={`dg-filter${filter === f ? ' on' : ''}`} aria-pressed={filter === f} onClick={() => setFilter(f)}
                title={t(`dag.filter.${f}.hint`)} disabled={f !== 'all' && counts[f] === 0 && filter !== f}>
                {t(`dag.filter.${f}`)} <span className="num">{counts[f]}</span>
              </button>
            ))}
          </div>
          <span className="grow" />
          {preview.state && (
            <span className="dg-pv-flag">
              {preview.state.loading ? <Spinner /> : <Icon name="eye" size={13} />}
              {t('dag.preview.mode')}
              <button type="button" className="dg-inline-link" onClick={discardPreview}>{t('dag.preview.exit')}</button>
            </span>
          )}
        </div>
      )}

      <div ref={bodyRef} className="panel-body dg-body">
        {!graph && loading && <div className="empty"><Spinner /></div>}
        {!graph && !loading && loadError && loadError.status !== 404 && <div className="dg-pad"><ErrorNote error={loadError.msg} onRetry={load} /></div>}
        {empty && (
          <Empty icon="dag" title={t('dag.empty.title')} action={<Button variant="primary" icon="plus" onClick={() => setNewNode('starter')}>{t('dag.empty.starter')}</Button>}>
            {t('dag.empty.body')}
          </Empty>
        )}
        {graph && graph.nodes.length > 0 && (
          <>
            <div className={`dg-canvas${view === 'list' ? ' is-list' : ''}`}>
              {loadError && <div className="dg-float-note"><ErrorNote error={loadError.msg} onRetry={load} /></div>}
              {view === 'list' ? (
                <ListView graph={graph} members={members} runNode={runNode} selected={selected} currentStep={step} missing={missing} readOnly={false}
                  onSelect={select} onAccept={accept} onReject={id => setStatusFor({ id, action: 'abandon' })} onDetails={openDetails}
                  onAsk={id => ask(id, 'free', t('dag.list.askPrompt', { id }))} onChoose={choose} onNextStep={() => setNextStep(true)} />
              ) : (
                <MapView pid={pid} graph={graph} runNode={runNode} runCount={runCount} thumbs={thumbs} verdicts={verdicts} gates={gates}
                  showDead={filter === 'dead'} showCites={false} railCollapsed={railCollapsed === '1'} onToggleRail={onToggleRail}
                  lensSet={lensSet} selected={selected} onSelect={onMapSelect} impact={impact} hoverIds={hoverIds}
                  onGate={onGate} onGroup={onGroup} centerReq={centerReq} resetN={resetN} readOnly={false} />
              )}
            </div>
            {side && (
              <aside id="dg-side" className="dg-side">
                <ResizeHandle pane={sideW} edge="left" label={t('dag.side.resize')} controls="dg-side" />
                {side}
              </aside>
            )}
          </>
        )}
      </div>

      <Toasts toasts={toasts.toasts} onDismiss={toasts.dismiss} />

      {statusFor && statusNode && graph && (
        <StatusDialog pid={pid} node={statusNode} action={statusFor.action} graph={graph} onClose={() => setStatusFor(null)}
          onDone={(res, action) => {
            setStatusFor(null);
            if (res) reportOps(res, t('dag.status.doneTitle', { action: t(`dag.status.${action}`), id: statusNode.id }));
            else toasts.push({ tone: 'ok', text: t('dag.status.doneTitle', { action: t(`dag.status.${action}`), id: statusNode.id }) });
            load();
            today.reload();
          }} />
      )}
      {gate && (
        <GateDialog gate={gate} readOnly={false} onClose={() => setGateOpen(null)} onSelect={id => selectAndCenter(id)}
          onPass={async note => {
            const snap = await dagApi.passGate(pid, gate.gate, note || undefined);
            setGateOpen(null);
            toasts.push({ tone: 'ok', text: t('dag.gate.passed', { gate: gate.gate, snap: snap?.name ?? '' }) });
            load();
            today.reload();
          }} />
      )}
      {newNode && (
        <NewNodeDialog pid={pid} graph={graph} starter={newNode === 'starter'} onClose={() => setNewNode(null)}
          onCreated={(id, res) => { setNewNode(null); reportOps(res, t('dag.new.createdTitle', { id })); load().then(() => selectAndCenter(id)); }} />
      )}
      {nextStep && <NextStepDialog pid={pid} step={step} onClose={() => { setNextStep(false); load(); }} />}
    </div>
  );
}
