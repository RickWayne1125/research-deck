// Research Map layout (docs/DAG.md §8): stage lanes S0…S6 as columns, a W writing swimlane across the bottom, and
// references/datasets in a collapsible rail on top.
//   1. each alt_group becomes one block: its siblings stacked (chosen first, dead chips last) under a header;
//   2. each lane is laid out by dagre (rankdir LR) over the lane's own edges, blocks as single nodes;
//   3. lanes are concatenated left to right; each lane is at least as wide as its rail items need;
//   4. W nodes sit in one row under the lanes, each as close as possible below what it describes.
// Pure and deterministic: the same nodes and edges always give the same positions (ids are sorted before dagre).
import dagre from '@dagrejs/dagre';
import type { StageKey } from '../../dag-types';

export const MAIN_LANES: StageKey[] = ['S0', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6'];

export interface Box { x: number; y: number; w: number; h: number }
export interface LayoutNode { id: string; stage: StageKey; rail: boolean; w: number; h: number }
export interface LayoutGroup { id: string; members: string[] }   // display order
export interface MapLayout {
  pos: Record<string, Box>;
  lanes: Record<StageKey, Box>;
  rail: Box;
  groups: Record<string, Box>;
  width: number;
  height: number;
}

export const L = {
  lanePad: 22, laneHead: 46, minLaneInner: 196, minLaneContent: 140,
  railHead: 30, railPad: 12, railGap: 8, railRowsMax: 3, railCollapsed: 34,
  wHead: 30, wMin: 74, wGap: 16,
  nodesep: 20, ranksep: 54,
  groupPad: 10, groupHead: 26, groupGap: 10, chipGap: 6,
  gridAfter: 6,                     // a lane with this many unconnected nodes lays them out as a grid below
};

/** Bounding box of a group given its members' boxes (used again after manual drags). */
export function groupBox(members: Box[]): Box | null {
  if (!members.length) return null;
  const x0 = Math.min(...members.map(b => b.x)) - L.groupPad;
  const y0 = Math.min(...members.map(b => b.y)) - L.groupHead;
  const x1 = Math.max(...members.map(b => b.x + b.w)) + L.groupPad;
  const y1 = Math.max(...members.map(b => b.y + b.h)) + L.groupPad;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

interface Block { id: string; w: number; h: number; inner?: { id: string; dx: number; dy: number }[] }

function stackGroup(g: LayoutGroup, size: Map<string, LayoutNode>): Block {
  let y = L.groupHead, w = 0;
  const inner: Block['inner'] = [];
  g.members.forEach((id, i) => {
    const n = size.get(id)!;
    const prev = i > 0 ? size.get(g.members[i - 1])! : null;
    if (prev) y += prev.h <= 30 && n.h <= 30 ? L.chipGap : L.groupGap;
    inner.push({ id, dx: L.groupPad, dy: y });
    y += n.h;
    w = Math.max(w, n.w);
  });
  return { id: `grp:${g.id}`, w: w + 2 * L.groupPad, h: y + L.groupPad, inner };
}

/** dagre over one lane; returns top-left positions relative to the lane content origin and the content size. */
function layoutLane(blocks: Block[], edges: [string, string][]): { at: Map<string, { x: number; y: number }>; w: number; h: number } {
  const at = new Map<string, { x: number; y: number }>();
  if (!blocks.length) return { at, w: 0, h: 0 };
  const ids = new Set(blocks.map(b => b.id));
  const lanesEdges = edges.filter(([a, b]) => a !== b && ids.has(a) && ids.has(b));
  const connected = new Set(lanesEdges.flat());
  const isolated = blocks.filter(b => !connected.has(b.id));
  const useGrid = isolated.length >= L.gridAfter;
  const inDagre = useGrid ? blocks.filter(b => connected.has(b.id)) : blocks;

  let w = 0, h = 0;
  if (inDagre.length) {
    try {
      const g = new dagre.graphlib.Graph();
      g.setGraph({ rankdir: 'LR', nodesep: L.nodesep, ranksep: L.ranksep, marginx: 0, marginy: 0 });
      g.setDefaultEdgeLabel(() => ({}));
      [...inDagre].sort((a, b) => a.id.localeCompare(b.id)).forEach(b => g.setNode(b.id, { width: b.w, height: b.h }));
      [...lanesEdges].sort((a, b) => (a[0] + a[1]).localeCompare(b[0] + b[1])).forEach(([a, b]) => g.setEdge(a, b));
      dagre.layout(g);
      let minX = Infinity, minY = Infinity;
      for (const b of inDagre) { const p = g.node(b.id); minX = Math.min(minX, p.x - b.w / 2); minY = Math.min(minY, p.y - b.h / 2); }
      for (const b of inDagre) {
        const p = g.node(b.id);
        const x = p.x - b.w / 2 - minX, y = p.y - b.h / 2 - minY;
        at.set(b.id, { x, y });
        w = Math.max(w, x + b.w); h = Math.max(h, y + b.h);
      }
    } catch (err) {
      // A dagre failure must not blank the map: fall back to one column.
      console.error('dag lane layout failed', err);
      let y = 0;
      for (const b of inDagre) { at.set(b.id, { x: 0, y }); y += b.h + L.nodesep; w = Math.max(w, b.w); }
      h = Math.max(0, y - L.nodesep);
    }
  }
  if (useGrid) {
    const sorted = [...isolated].sort((a, b) => a.id.localeCompare(b.id));
    const cols = Math.max(1, Math.min(3, Math.ceil(sorted.length / 5)));
    const colW = Math.max(...sorted.map(b => b.w));
    let y0 = h ? h + L.ranksep / 2 : 0, rowH = 0;
    sorted.forEach((b, i) => {
      const c = i % cols;
      if (c === 0 && i > 0) { y0 += rowH + L.nodesep; rowH = 0; }
      at.set(b.id, { x: c * (colW + L.nodesep), y: y0 });
      rowH = Math.max(rowH, b.h);
      w = Math.max(w, c * (colW + L.nodesep) + b.w);
    });
    h = y0 + rowH;
  }
  return { at, w, h };
}

export function layoutMap(nodes: LayoutNode[], edges: { source: string; target: string }[], groups: LayoutGroup[], opts: { railCollapsed: boolean }): MapLayout {
  const size = new Map(nodes.map(n => [n.id, n]));
  const pos: Record<string, Box> = {};
  const groupsOut: Record<string, Box> = {};

  // Which block each node belongs to (a group block or itself), and each block's lane.
  const blockOf = new Map<string, string>();
  const laneBlocks = new Map<StageKey, Block[]>(MAIN_LANES.map(s => [s, []]));
  const groupBlocks: Block[] = [];
  for (const g of groups) {
    const members = g.members.filter(id => size.has(id) && !size.get(id)!.rail && size.get(id)!.stage !== 'W');
    if (members.length < 1) continue;
    const block = stackGroup({ id: g.id, members }, size);
    groupBlocks.push(block);
    const lane = size.get(members[0])!.stage;
    laneBlocks.get(MAIN_LANES.includes(lane) ? lane : 'S0')!.push(block);
    members.forEach(id => blockOf.set(id, block.id));
  }
  const railNodes: LayoutNode[] = [];
  const wNodes: LayoutNode[] = [];
  for (const n of nodes) {
    if (blockOf.has(n.id)) continue;
    if (n.rail) { railNodes.push(n); continue; }
    if (n.stage === 'W') { wNodes.push(n); continue; }
    laneBlocks.get(MAIN_LANES.includes(n.stage) ? n.stage : 'S0')!.push({ id: n.id, w: n.w, h: n.h });
    blockOf.set(n.id, n.id);
  }
  const blockEdges: [string, string][] = [];
  for (const e of edges) {
    const a = blockOf.get(e.source), b = blockOf.get(e.target);
    if (a && b && a !== b) blockEdges.push([a, b]);
  }

  // Lay out every lane, then size it for its rail items.
  const laneLayouts = new Map(MAIN_LANES.map(s => [s, layoutLane(laneBlocks.get(s)!, blockEdges)]));
  const railByLane = new Map<StageKey, LayoutNode[]>(MAIN_LANES.map(s => [s, []]));
  for (const n of [...railNodes].sort((a, b) => a.id.localeCompare(b.id))) {
    const lane = MAIN_LANES.includes(n.stage) ? n.stage : 'S1';
    railByLane.get(lane)!.push(n);
  }
  const railW = Math.max(172, ...railNodes.map(n => n.w));
  const railGrid = new Map<StageKey, { cols: number; rows: number; rowH: number }>();
  const laneInner = new Map<StageKey, number>();
  for (const s of MAIN_LANES) {
    const content = laneLayouts.get(s)!.w;
    let inner = Math.max(L.minLaneInner, content);
    const items = railByLane.get(s)!;
    if (items.length && !opts.railCollapsed) {
      const fit = Math.max(1, Math.floor((inner + L.railGap) / (railW + L.railGap)));
      const cols = Math.min(items.length, Math.max(fit, Math.ceil(items.length / L.railRowsMax)));
      const rows = Math.ceil(items.length / cols);
      railGrid.set(s, { cols, rows, rowH: Math.max(...items.map(n => n.h)) });
      inner = Math.max(inner, cols * (railW + L.railGap) - L.railGap);
    }
    laneInner.set(s, inner);
  }

  const railRowsH = Math.max(0, ...[...railGrid.values()].map(g => g.rows * (g.rowH + L.railGap) - L.railGap));
  const railH = !railNodes.length ? 0 : opts.railCollapsed ? L.railCollapsed : L.railHead + railRowsH + L.railPad;
  const contentH = Math.max(L.minLaneContent, ...MAIN_LANES.map(s => laneLayouts.get(s)!.h));
  const laneTop = railH;
  const laneH = L.laneHead + contentH + 2 * L.lanePad;

  const lanes = {} as Record<StageKey, Box>;
  let x = 0;
  for (const s of MAIN_LANES) {
    const inner = laneInner.get(s)!;
    const w = inner + 2 * L.lanePad;
    lanes[s] = { x, y: laneTop, w, h: laneH };
    const ll = laneLayouts.get(s)!;
    const ox = x + L.lanePad + (inner - ll.w) / 2;
    const oy = laneTop + L.laneHead + L.lanePad;
    for (const b of laneBlocks.get(s)!) {
      const p = ll.at.get(b.id);
      if (!p) continue;
      if (b.inner) {
        groupsOut[b.id.slice(4)] = { x: ox + p.x, y: oy + p.y, w: b.w, h: b.h };
        for (const m of b.inner) { const n = size.get(m.id)!; pos[m.id] = { x: ox + p.x + m.dx, y: oy + p.y + m.dy, w: n.w, h: n.h }; }
      } else {
        pos[b.id] = { x: ox + p.x, y: oy + p.y, w: b.w, h: b.h };
      }
    }
    // Rail items of this lane, in a grid at the top of the lane's x-range.
    const grid = railGrid.get(s);
    if (grid && !opts.railCollapsed) {
      const items = railByLane.get(s)!;
      const gridW = grid.cols * (railW + L.railGap) - L.railGap;
      const gx = x + L.lanePad + (inner - gridW) / 2;
      items.forEach((n, i) => {
        const c = i % grid.cols, r = Math.floor(i / grid.cols);
        pos[n.id] = { x: gx + c * (railW + L.railGap) + (railW - n.w) / 2, y: L.railHead + r * (grid.rowH + L.railGap), w: n.w, h: n.h };
      });
    }
    x += w;
  }
  const width = x;

  // W row: each node as close as possible under the mean x of what it connects to.
  const wTop = laneTop + laneH;
  const wH = L.wHead + Math.max(L.wMin - L.wHead, ...wNodes.map(n => n.h)) + 2 * L.lanePad - 8;
  const center = (id: string) => { const b = pos[id]; return b ? b.x + b.w / 2 : null; };
  const desired = new Map<string, number>();
  const wIds = new Set(wNodes.map(n => n.id));
  wNodes.forEach((n, i) => {
    const xs: number[] = [];
    for (const e of edges) {
      const other = e.source === n.id ? e.target : e.target === n.id ? e.source : null;
      if (other && !wIds.has(other)) { const c = center(other); if (c !== null) xs.push(c); }
    }
    desired.set(n.id, xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length - n.w / 2 : L.lanePad + i * (n.w + L.wGap));
  });
  let cursor = L.lanePad;
  for (const n of [...wNodes].sort((a, b) => desired.get(a.id)! - desired.get(b.id)! || a.id.localeCompare(b.id))) {
    const nx = Math.max(cursor, desired.get(n.id)!);
    pos[n.id] = { x: nx, y: wTop + L.wHead + L.lanePad - 8, w: n.w, h: n.h };
    cursor = nx + n.w + L.wGap;
  }
  const fullW = Math.max(width, cursor + L.lanePad - L.wGap);
  lanes.W = { x: 0, y: wTop, w: fullW, h: wH };
  if (fullW > width) lanes.S6 = { ...lanes.S6, w: lanes.S6.w + fullW - width };

  return { pos, lanes, rail: { x: 0, y: 0, w: fullW, h: railH }, groups: groupsOut, width: fullW, height: wTop + wH };
}
