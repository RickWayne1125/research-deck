// Node geometry for the Research Map (docs/DAG.md §8 "shape = kind"): one SVG path per shape, drawn at any outset so
// the same outline serves the body, the inner line of a locked node's double border, the freshness ring and the
// impact-preview ring. Sizes are fixed per kind so the layout is deterministic before anything is measured.
import type { DagNode } from '../../dag-types';
import { cellGrid, isAction } from './model';

export type Shape = 'round' | 'pill' | 'cylinder' | 'ticket' | 'lozenge' | 'rect' | 'page';

export function shapeOf(n: Pick<DagNode, 'kind' | 'facets'>): Shape {
  switch (n.kind) {
    case 'reference': return 'pill';
    case 'dataset': return 'cylinder';
    case 'experiment': return 'ticket';
    case 'figure': return isAction(n) ? 'ticket' : 'rect';
    case 'decision': return 'lozenge';
    case 'design': case 'module': return 'rect';
    case 'claim': case 'section': return 'page';
    default: return 'round';
  }
}

export const CARD_W = 212;
export const CHIP = { w: 156, h: 26 };
const CELL = 10, CELL_GAP = 2, GRID_ROWS_MAX = 4;

/** Height of the cell mini-grid block (0 when the node has no cells). */
export function gridHeight(cells: string[]): number {
  if (!cells.length) return 0;
  const rows = Math.min(GRID_ROWS_MAX, cellGrid(cells).rows.length);
  return rows * (CELL + CELL_GAP) + 4;
}
export const GRID = { cell: CELL, gap: CELL_GAP, rowsMax: GRID_ROWS_MAX };

export function nodeSize(n: Pick<DagNode, 'kind' | 'facets'>, opts: { chip?: boolean; cells?: string[]; thumb?: boolean }): { w: number; h: number } {
  if (opts.chip) return CHIP;
  switch (n.kind) {
    case 'reference': return { w: 172, h: 34 };
    case 'dataset': return { w: 172, h: 46 };
    case 'decision': return { w: CARD_W, h: 72 };
    default: break;
  }
  if (isAction(n)) return { w: CARD_W + 8, h: 70 + gridHeight(opts.cells ?? []) };
  if (n.kind === 'figure' && opts.thumb) return { w: CARD_W, h: 112 };
  return { w: CARD_W, h: 68 };
}

/** The outline of a shape for a w×h body, grown by `o` px on every side (negative shrinks). */
export function shapePath(shape: Shape, w: number, h: number, o = 0): string {
  const x0 = -o, y0 = -o, x1 = w + o, y1 = h + o;
  const W = x1 - x0, H = y1 - y0;
  const f = (v: number) => Math.round(v * 100) / 100;
  const rr = (r: number) => {
    const k = Math.max(0, Math.min(r, W / 2, H / 2));
    return `M${f(x0 + k)},${f(y0)}H${f(x1 - k)}A${f(k)},${f(k)} 0 0 1 ${f(x1)},${f(y0 + k)}V${f(y1 - k)}A${f(k)},${f(k)} 0 0 1 ${f(x1 - k)},${f(y1)}H${f(x0 + k)}A${f(k)},${f(k)} 0 0 1 ${f(x0)},${f(y1 - k)}V${f(y0 + k)}A${f(k)},${f(k)} 0 0 1 ${f(x0 + k)},${f(y0)}Z`;
  };
  switch (shape) {
    case 'round': return rr(7 + o);
    case 'pill': return rr(H / 2);
    case 'rect': return rr(Math.max(1.5, 2 + o));
    case 'ticket': {                       // cut top-left and bottom-right corners: a build action
      const c = 11 + o * 0.4;
      return `M${f(x0 + c)},${f(y0)}H${f(x1)}V${f(y1 - c)}L${f(x1 - c)},${f(y1)}H${f(x0)}V${f(y0 + c)}Z`;
    }
    case 'lozenge': {                      // pointed ends: a decision
      const p = 14 + o * 0.5, m = (y0 + y1) / 2;
      return `M${f(x0)},${f(m)}L${f(x0 + p)},${f(y0)}H${f(x1 - p)}L${f(x1)},${f(m)}L${f(x1 - p)},${f(y1)}H${f(x0 + p)}Z`;
    }
    case 'page': {                         // folded top-right corner: prose that ends up in the paper
      const c = 12 + o * 0.4;
      return `M${f(x0)},${f(y0)}H${f(x1 - c)}L${f(x1)},${f(y0 + c)}V${f(y1)}H${f(x0)}Z`;
    }
    case 'cylinder': {
      const ry = Math.min(7, H / 4), rx = W / 2;
      return `M${f(x0)},${f(y0 + ry)}A${f(rx)},${f(ry)} 0 0 1 ${f(x1)},${f(y0 + ry)}V${f(y1 - ry)}A${f(rx)},${f(ry)} 0 0 1 ${f(x0)},${f(y1 - ry)}Z`;
    }
  }
}

/** Extra strokes drawn over the body: the page fold and the cylinder's front rim. */
export function shapeDetail(shape: Shape, w: number, h: number): string | null {
  if (shape === 'page') return `M${w - 12},0V12H${w}`;
  if (shape === 'cylinder') { const ry = Math.min(7, h / 4); return `M0,${ry}A${w / 2},${ry} 0 0 0 ${w},${ry}`; }
  return null;
}
