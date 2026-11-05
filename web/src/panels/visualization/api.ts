// Typed calls to the viz routes (docs/API.md § Visualization) plus the extra detail the backend sends beyond the
// shared types (style sources, per-tool conventions, native app state).
import { del, get, p, patch, post, put } from '../../api/client';
import type { FileContent, Figure, FigureKind, RenderResult, RunStarted, StyleTokens } from '../../types';

export interface PaletteFull {
  id: string; label: string; label_zh?: string; note?: string; note_zh?: string; source: string;
  colors: { role: string; hex: string }[];
  roles: Record<string, string>;      // text, structure, accent, muted, light, surface, accent_surface, accent_fill, accent_text, accent_keyline, background
  series: string[]; recommended?: boolean;
}

export interface StyleFull extends Omit<StyleTokens, 'palettes' | 'font'> {
  font: StyleTokens['font'] & { fallback?: string[] };
  palettes: PaletteFull[];
  geometry: { grid_px: number; stroke_width: number };
  tools: {
    drawio: { font_px: number; font_pt: number; grid_px: number; stroke_width: number };
    omnigraffle: { font_pt: number; grid_pt: number; corner_radius: number[] };
    datagraph: { font_pt: number; series: string[] };
    matplotlib: { font_pt: number; width_in: number; height_in: number };
  };
  datagraph_series: string[];
  override: Record<string, unknown>;
}

export interface FigureView extends Figure {
  exists: boolean;
  kind_label: string;
  native: { app: string; installed: boolean; path: string | null } | null;
  last_render: { at: string; duration_ms: number } | null;
  last_error: { at: string; log: string } | null;
  node: { id: string; label?: string | null; status?: string | null } | null;
}

export interface Discovered { path: string; kind: FigureKind }
export interface ExportResult { ok: boolean; app: string; outputs: string[]; log?: string; preview?: string | null }

export const vz = {
  style: (pid: string) => get<StyleFull>('/api/style', { project: pid }),
  setStyle: (pid: string, body: Record<string, unknown>) => put<StyleFull>(p(pid, '/style'), body),
  list: (pid: string) => get<FigureView[]>(p(pid, '/figures')),
  one: (pid: string, fid: string) => get<FigureView>(p(pid, `/figures/${encodeURIComponent(fid)}`)),
  discover: (pid: string) => get<Discovered[]>(p(pid, '/figures/discover')),
  create: (pid: string, body: { kind: FigureKind; title: string; node_id?: string; caption?: string; source?: string }) =>
    post<FigureView>(p(pid, '/figures'), body),
  patch: (pid: string, fid: string, body: Partial<Pick<Figure, 'title' | 'caption' | 'node_id' | 'data' | 'source'>>) =>
    patch<FigureView>(p(pid, `/figures/${encodeURIComponent(fid)}`), body),
  remove: (pid: string, fid: string) => del<{ ok: boolean }>(p(pid, `/figures/${encodeURIComponent(fid)}`)),
  render: (pid: string, fid: string, source?: string) =>
    post<RenderResult>(p(pid, `/figures/${encodeURIComponent(fid)}/render`), source === undefined ? {} : { source }),
  putPreview: (pid: string, fid: string, body: { svg?: string; png_base64?: string }) =>
    put<FigureView>(p(pid, `/figures/${encodeURIComponent(fid)}/preview`), body),
  aiEdit: (pid: string, fid: string, instruction: string, source?: string) =>
    post<RunStarted>(p(pid, `/figures/${encodeURIComponent(fid)}/ai-edit`), { instruction, source }),
  openNative: (pid: string, fid: string) => post<{ ok: boolean; app: string }>(p(pid, `/figures/${encodeURIComponent(fid)}/open-native`)),
  exportNative: (pid: string, fid: string) => post<ExportResult>(p(pid, `/figures/${encodeURIComponent(fid)}/export-native`)),
  readFile: (pid: string, path: string) => get<FileContent>(p(pid, '/file'), { path }),
  writeFile: (pid: string, path: string, content: string, base_sha?: string | null) =>
    put<{ path: string; sha: string; mtime: number }>(p(pid, '/file'), { path, content, base_sha: base_sha ?? undefined }),
};

export const KIND_TONE: Record<FigureKind, 'process' | 'data' | 'emphasis' | undefined> = {
  drawio: 'process', matplotlib: 'data', omnigraffle: 'emphasis', datagraph: undefined,
};
export const KIND_LABEL: Record<FigureKind, string> = { drawio: 'draw.io', matplotlib: 'matplotlib', omnigraffle: 'OmniGraffle', datagraph: 'DataGraph' };
export const STATUS_TONE: Record<string, 'ok' | 'stale' | 'accent' | undefined> = { ok: 'ok', stale: 'stale', error: 'accent', unrendered: undefined };

/** The message of an ApiError (string detail or {message}). */
export function errMessage(e: unknown): string {
  return (e as Error)?.message ?? String(e);
}
