// The Research Map (docs/DAG.md §8): stage lanes with gate chips, the reference/dataset rail, attempt brackets,
// supersede stacks and typed edges, on @xyflow/react. Lens dimming, impact painting, selection and hover are classes
// on the React Flow wrappers; positions come from layout.ts, with manual drags remembered per project.
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Controls, MarkerType, ReactFlow, ReactFlowProvider, useReactFlow, useStore,
  type Edge, type Node, type NodeChange, applyNodeChanges,
} from '@xyflow/react';
import { useI18n, useT } from '../../i18n';
import { impactCategories, primaryCategory } from '../../dag/ImpactView';
import type { DagEvent, DagNode, GateStatus, GraphResponse, Impact, StageKey } from '../../dag-types';
import { groupBox, layoutMap, MAIN_LANES, type Box, type LayoutGroup, type LayoutNode } from './layout';
import {
  altGroups, collectEdges, isAction, isDead, lastAgent, nodeTitle, RAIL_KINDS, stageOf, statusReason, supersedeChains, type DrawEdge,
} from './model';
import { NODE_TYPES, type CardData, type GroupData, type LaneData, type RailData } from './NodeCard';
import { nodeSize } from './shapes';

export interface MapViewProps {
  pid: string;
  graph: GraphResponse;
  runNode: Map<string, string>;
  runCount: Map<string, number>;
  thumbs: Map<string, string>;
  verdicts: Map<string, DagEvent>;
  gates: GateStatus[];
  showDead: boolean;
  showCites: boolean;
  railCollapsed: boolean;
  onToggleRail: () => void;
  lensSet: Set<string> | null;
  selected: string | null;
  onSelect: (id: string | null) => void;
  impact: Impact | null;
  hoverIds: string[];
  onGate: (gate: string) => void;
  onGroup: (id: string) => void;
  centerReq: { id: string; n: number } | null;
  resetN: number;
  readOnly: boolean;
}

type Pos = Record<string, { x: number; y: number }>;
const posKey = (pid: string) => `rd.dag.pos.${pid}`;
function readPos(pid: string): Pos {
  try { const v = JSON.parse(localStorage.getItem(posKey(pid)) || '{}'); return v && typeof v === 'object' ? v : {}; } catch { return {}; }
}
function writePos(pid: string, p: Pos) {
  try { if (Object.keys(p).length) localStorage.setItem(posKey(pid), JSON.stringify(p)); else localStorage.removeItem(posKey(pid)); } catch { /* storage unavailable */ }
}

const MIN_READABLE_ZOOM = 0.55;

// Backgrounds let clicks and drags through to the pane; only their headers (.dg-hit) take the pointer.
const BG_STYLE = { pointerEvents: 'none' as const };

const EDGE_HEAD: Record<string, string> = {
  input: 'var(--ink)', basis: 'var(--slate)', implements: 'var(--slate)', describes: 'var(--faint)', cites: 'var(--faint)',
};

export function MapView(props: MapViewProps) {
  return <ReactFlowProvider><MapInner {...props} /></ReactFlowProvider>;
}

function MapInner(p: MapViewProps) {
  const t = useT();
  const { lang } = useI18n();
  const { graph, showDead, showCites, railCollapsed } = p;
  const rf = useReactFlow();

  // ---- what is drawn, and how big (structure only: independent of lens, selection and preview)
  const model = useMemo(() => {
    const byId = new Map(graph.nodes.map(n => [n.id, n]));
    const chains = supersedeChains(graph.nodes);
    const folded = new Set<string>();
    if (!showDead) for (const ids of chains.values()) ids.forEach(id => folded.add(id));
    const visible = graph.nodes.filter(n => !folded.has(n.id));
    const groups = altGroups(visible);
    const chosen = new Set(groups.flatMap(g => g.chosen));
    const data = new Map<string, CardData>();
    for (const n of visible) {
      const ev = graph.eval[n.id];
      const chip = isDead(n.status) && !showDead && !RAIL_KINDS.includes(n.kind);
      const cells = isAction(n) ? Object.keys(ev?.cells ?? {}) : [];
      const thumb = n.kind === 'figure' && !isAction(n) ? p.thumbs.get(n.id) ?? null : null;
      const { w, h } = nodeSize(n, { chip, cells, thumb: !!thumb });
      const version = n.kind === 'dataset' ? facetString(n, 'version') : null;
      data.set(n.id, {
        node: n, ev, w, h, chip, cells, runCount: p.runCount.get(n.id) ?? 0, stack: chains.get(n.id)?.length ?? 0,
        reason: isDead(n.status) ? statusReason(n, p.verdicts.get(n.id)) : null, agent: lastAgent(n), thumb,
        chosen: chosen.has(n.id), version,
      });
    }
    const edges = collectEdges(visible, graph.eval, p.runNode).filter(e => showCites || e.type !== 'cites');
    return { byId, visible, groups, data, edges };
  }, [graph, showDead, showCites, p.runNode, p.runCount, p.thumbs, p.verdicts]);

  const layout = useMemo(() => {
    const nodes: LayoutNode[] = model.visible.map(n => {
      const d = model.data.get(n.id)!;
      return { id: n.id, stage: stageOf(n), rail: RAIL_KINDS.includes(n.kind), w: d.w, h: d.h };
    });
    const groups: LayoutGroup[] = model.groups.map(g => ({ id: g.id, members: g.members }));
    return layoutMap(nodes, model.edges, groups, { railCollapsed });
  }, [model, railCollapsed]);

  // ---- manual positions (remembered per project)
  const [overrides, setOverrides] = useState<Pos>(() => readPos(p.pid));
  const firstReset = useRef(p.resetN);
  useEffect(() => {
    if (p.resetN === firstReset.current) return;
    setOverrides({}); writePos(p.pid, {});
    requestAnimationFrame(() => rf.fitView({ padding: 0.08, duration: 250 }));
  }, [p.resetN, p.pid, rf]);

  const boxes = useMemo(() => {
    const out: Record<string, Box> = {};
    for (const [id, b] of Object.entries(layout.pos)) {
      const o = overrides[id];
      out[id] = o ? { ...b, x: o.x, y: o.y } : b;
    }
    return out;
  }, [layout, overrides]);

  // ---- classes from lens / preview / selection / hover
  const cats = useMemo(() => impactCategories(p.impact), [p.impact]);
  const hover = useMemo(() => new Set(p.hoverIds), [p.hoverIds]);
  const neighbours = useMemo(() => {
    const s = new Set<string>();
    if (p.selected) for (const e of model.edges) { if (e.source === p.selected) s.add(e.target); if (e.target === p.selected) s.add(e.source); }
    return s;
  }, [model.edges, p.selected]);

  const cardClass = useCallback((id: string) => {
    const c: string[] = [];
    if (p.lensSet && !p.lensSet.has(id)) c.push('dg-dim');
    if (p.impact) {
      const set = cats.get(id);
      const prim = primaryCategory(set);
      c.push(prim ? `pv-${prim}` : 'pv-dim');
      if (set?.has('lock')) c.push('pv-lock');
    }
    if (id === p.selected) c.push('dg-sel');
    else if (neighbours.has(id)) c.push('dg-rel');
    if (hover.has(id)) c.push('dg-hot');
    return c.join(' ');
  }, [p.lensSet, p.impact, cats, p.selected, neighbours, hover]);

  // ---- React Flow nodes
  const built = useMemo<Node[]>(() => {
    const nodes: Node[] = [];
    const railCount = { refs: 0, data: 0 };
    for (const n of model.visible) { if (n.kind === 'reference') railCount.refs++; if (n.kind === 'dataset') railCount.data++; }
    if (layout.rail.h > 0) {
      nodes.push({
        id: '__rail', type: 'dgRail', position: { x: layout.rail.x, y: layout.rail.y }, width: layout.rail.w, height: layout.rail.h,
        data: { collapsed: railCollapsed, refs: railCount.refs, datasets: railCount.data, onToggle: p.onToggleRail } satisfies RailData,
        draggable: false, selectable: false, focusable: false, zIndex: -3, className: 'dg-bg', style: BG_STYLE,
      });
    }
    const counts = new Map<StageKey, number>();
    for (const n of model.visible) if (!RAIL_KINDS.includes(n.kind)) counts.set(stageOf(n), (counts.get(stageOf(n)) ?? 0) + 1);
    [...MAIN_LANES, 'W' as StageKey].forEach((s, i) => {
      const b = layout.lanes[s];
      nodes.push({
        id: `__lane:${s}`, type: 'dgLane', position: { x: b.x, y: b.y }, width: b.w, height: b.h,
        data: { stage: s, count: counts.get(s) ?? 0, gates: p.gates.filter(g => g.after === s), alt: i % 2 === 1, onGate: p.onGate } satisfies LaneData,
        draggable: false, selectable: false, focusable: false, zIndex: -3, className: 'dg-bg', style: BG_STYLE,
      });
    });
    for (const g of model.groups) {
      const box = groupBox(g.members.map(id => boxes[id]).filter(Boolean));
      if (!box) continue;
      const parent = model.byId.get(g.id);
      nodes.push({
        id: `__grp:${g.id}`, type: 'dgGroup', position: { x: box.x, y: box.y }, width: box.w, height: box.h,
        data: { id: g.id, label: parent ? nodeTitle(parent, lang) : g.id, tried: g.members.length, chosen: g.chosen.length, onOpen: p.onGroup } satisfies GroupData,
        draggable: false, selectable: false, focusable: false, zIndex: -2, style: BG_STYLE, className: `dg-bg ${p.lensSet && !g.members.some(id => p.lensSet!.has(id)) ? 'dg-dim' : ''}`,
      });
    }
    for (const n of model.visible) {
      const b = boxes[n.id];
      if (!b) continue;   // a rail node while the rail is collapsed
      nodes.push({
        id: n.id, type: 'dgCard', position: { x: b.x, y: b.y }, width: b.w, height: b.h, data: model.data.get(n.id)!,
        draggable: !p.readOnly, selectable: false, className: cardClass(n.id), zIndex: n.id === p.selected ? 4 : 2,   // above edges (0–1), lanes (-3), groups (-2)
        ariaLabel: `${n.id}`,
      });
    }
    return nodes;
  }, [model, layout, boxes, railCollapsed, p.onToggleRail, p.gates, p.onGate, p.onGroup, p.lensSet, p.readOnly, p.selected, cardClass, lang]);

  // Controlled nodes keep React Flow's measurements across rebuilds (otherwise every rebuild re-measures every node).
  const [rfNodes, setRfNodes] = useState<Node[]>(built);
  useEffect(() => {
    setRfNodes(prev => {
      const old = new Map(prev.map(n => [n.id, n]));
      return built.map(n => { const o = old.get(n.id); return o?.measured ? { ...n, measured: o.measured } : n; });
    });
  }, [built]);
  const onNodesChange = useCallback((changes: NodeChange[]) => setRfNodes(ns => applyNodeChanges(changes, ns)), []);
  const onNodeDragStop = useCallback((_: unknown, _n: Node, dragged: Node[]) => {
    setOverrides(prev => {
      const next = { ...prev };
      for (const d of dragged) if (d.type === 'dgCard') next[d.id] = { x: Math.round(d.position.x), y: Math.round(d.position.y) };
      writePos(p.pid, next);
      return next;
    });
  }, [p.pid]);

  // ---- React Flow edges
  const edges = useMemo<Edge[]>(() => {
    const rail = new Set(model.visible.filter(n => RAIL_KINDS.includes(n.kind)).map(n => n.id));
    const wl = new Set(model.visible.filter(n => !RAIL_KINDS.includes(n.kind) && stageOf(n) === 'W').map(n => n.id));
    const chosen = new Set(model.groups.flatMap(g => g.chosen));
    const out: Edge[] = [];
    for (const e of model.edges) {
      if (!boxes[e.source] || !boxes[e.target]) continue;
      out.push(toFlowEdge(e, {
        sourceHandle: rail.has(e.source) ? 'b' : 'r',
        targetHandle: wl.has(e.target) && !wl.has(e.source) ? 't' : rail.has(e.target) ? 'l' : 'l',
        cls: edgeClass(e),
        chosen: chosen.has(e.source) || chosen.has(e.target),
      }));
    }
    return out;

    function edgeClass(e: DrawEdge): string {
      const c: string[] = [];
      const touchesSel = !!p.selected && (e.source === p.selected || e.target === p.selected);
      if (touchesSel || (hover.has(e.source) && hover.has(e.target))) c.push('is-hot');
      else if (p.selected) c.push('is-quiet');
      if (p.lensSet && !(p.lensSet.has(e.source) && p.lensSet.has(e.target))) c.push('dg-dim');
      if (p.impact && !cats.has(e.source) && !cats.has(e.target)) c.push('pv-dim');
      return c.join(' ');
    }
  }, [model, boxes, p.selected, p.lensSet, p.impact, cats, hover]);

  // ---- viewport: fit once, then center on deep links
  const paneW = useStore(s => s.width);
  const paneH = useStore(s => s.height);
  const fitted = useRef(false);
  const pendingCenter = useRef<{ id: string; n: number } | null>(p.centerReq);
  useEffect(() => { if (p.centerReq) pendingCenter.current = p.centerReq; }, [p.centerReq]);
  useEffect(() => {
    if (!paneW || !paneH) return;           // the pane is not measured yet
    const req = pendingCenter.current;
    if (req && boxes[req.id]) {
      const b = boxes[req.id];
      pendingCenter.current = null;
      fitted.current = true;
      requestAnimationFrame(() => rf.setCenter(b.x + b.w / 2, b.y + b.h / 2, { zoom: Math.max(rf.getZoom(), 0.95), duration: 300 }));
      return;
    }
    if (!fitted.current && Object.keys(boxes).length && paneW > 0 && paneH > 0) {
      fitted.current = true;
      // Fit everything when cards stay legible; otherwise fit the height and start at S0 (reading order).
      const fit = Math.min((paneW - 32) / layout.width, (paneH - 32) / layout.height);
      if (fit >= MIN_READABLE_ZOOM) requestAnimationFrame(() => rf.fitView({ padding: 0.06, duration: 0, maxZoom: 1 }));
      else {
        const zoom = Math.min(0.9, Math.max(MIN_READABLE_ZOOM, (paneH - 32) / layout.height));
        requestAnimationFrame(() => rf.setViewport({ x: 16, y: Math.max(16, (paneH - layout.height * zoom) / 2), zoom }));
      }
    }
  }, [boxes, p.centerReq, rf, paneW, paneH, layout.width, layout.height]);

  return (
    <div className={`dg-flow ${p.impact ? 'is-preview' : ''} ${p.lensSet ? 'is-lens' : ''}`}>
      <ReactFlow
        nodes={rfNodes} edges={edges} nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange} onNodeDragStop={onNodeDragStop}
        onNodeClick={(_, n) => { if (n.type === 'dgCard') p.onSelect(n.id === p.selected ? null : n.id); }}
        onPaneClick={() => p.onSelect(null)}
        nodesConnectable={false} elementsSelectable={false} nodesFocusable edgesFocusable={false}
        minZoom={0.1} maxZoom={2} zoomOnDoubleClick={false} onlyRenderVisibleElements={rfNodes.length > 240}
        proOptions={{ hideAttribution: true }} aria-label={t('dag.map.aria')}>
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
    </div>
  );
}

function facetString(n: DagNode, name: string): string | null {
  const v = n.facets?.[name]?.value;
  if (v === undefined || v === null) return null;
  return typeof v === 'string' ? v : JSON.stringify(v);
}

function toFlowEdge(e: DrawEdge, o: { sourceHandle: string; targetHandle: string; cls: string; chosen: boolean }): Edge {
  const moved = e.moved.length > 0;
  const head = moved ? 'var(--stale)'
    : e.type === 'evidence' ? (e.polarity === 'refutes' ? 'var(--accent)' : 'var(--ok)')
      : EDGE_HEAD[e.type] ?? 'var(--slate)';
  const facets = [...new Set(e.moved.map(m => m.facet))];
  const label = moved ? (facets.length > 2 ? `${facets.slice(0, 2).join(', ')} +${facets.length - 2}` : facets.join(', ')) : undefined;
  return {
    id: e.id, source: e.source, target: e.target, sourceHandle: o.sourceHandle, targetHandle: o.targetHandle,
    type: 'smoothstep', pathOptions: { borderRadius: 10, offset: 16 },
    className: ['dg-e', `dg-e-${e.type}`, moved ? 'is-moved' : '', e.frozen ? 'is-frozen' : '', o.chosen ? 'is-chosen' : '', o.cls].filter(Boolean).join(' '),
    markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13, color: head },
    label,
    labelStyle: label ? { fill: 'var(--stale)', fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 500 } : undefined,
    labelBgStyle: label ? { fill: 'var(--stale-wash)', stroke: 'var(--stale)', strokeWidth: 0.6 } : undefined,
    labelBgPadding: [4, 2], labelBgBorderRadius: 3,
    zIndex: o.cls.includes('is-hot') || moved ? 1 : 0,
    focusable: false,
  } as Edge;
}
