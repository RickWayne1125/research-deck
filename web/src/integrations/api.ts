// Zotero and Docmost (docs/API.md § Literature, § Docmost): this computer's connections, and a project's literature
// backend and bound Docmost page. Secrets never come back from these routes.
import { del, get, p, patch, post, put } from '../api/client';

export interface JobState {
  state: 'idle' | 'waiting' | 'running' | 'done' | 'error'; message: string; code?: number;
  /** A sign-in: "build" while the native window is prepared (first time only), then "window". */
  phase?: 'build' | 'window';
}

export interface ZoteroStatus {
  mode: 'local' | 'web';
  library: string;
  credential: string;
  local_key: boolean;
  local_remember: boolean | null;
  connect: JobState;
  check: { ok: boolean; at: string; message?: string; user?: { id: number; name: string }; write?: boolean | null; version?: number | null } | null;
}

export interface Collection { key: string; name: string; parent: string | null }

export interface Literature {
  backend: 'files' | 'zotero';
  collection: string | null;
  collection_name: string | null;
  bib: string;
  exported: { at: string; items: number; path: string; collection: string } | null;
  zotero: ZoteroStatus;
}

export interface DocmostStatus {
  url: string | null;
  signed_in: boolean;
  user: { id?: string; name?: string; email?: string } | null;
  at: string | null;
  login: JobState;
  install: JobState;
  playwright: boolean;
  /** The sign-in window here: a native Mac window, Chromium through Playwright, or none yet. */
  helper: 'native' | 'playwright' | null;
}

export type NoteState = 'synced' | 'pending' | 'conflict' | 'missing' | 'removed' | 'error';
export interface DocmostNote { path: string; title: string; state: NoteState; at: string | null; error: string | null; url: string | null }
export interface DocmostProject {
  binding: { page: string; slug_id: string; space: string; space_slug: string | null; title: string; url: string | null } | null;
  site: string | null;
  signed_in: boolean;
  running: boolean;
  last: { at: string; pushed: number; conflicts: number; errors: number } | null;
  notes: DocmostNote[];
}
export interface DocmostConflict {
  path: string; title: string; at: string; url: string | null; remote: string; note: string;
  diff: { kind: '+' | '-' | ' ' | '@'; text: string }[];
}

export const zoteroApi = {
  status: () => get<ZoteroStatus>('/api/settings/zotero'),
  save: (change: Partial<Pick<ZoteroStatus, 'mode'>> & { library?: string | null; credential?: string | null }) =>
    patch<ZoteroStatus>('/api/settings/zotero', change),
  connect: () => post<ZoteroStatus>('/api/settings/zotero/connect'),
  check: () => post<ZoteroStatus>('/api/settings/zotero/check'),
  forgetKey: () => del<ZoteroStatus>('/api/settings/zotero/key'),
  collections: () => get<{ collections: Collection[] }>('/api/zotero/collections'),
  literature: (pid: string) => get<Literature>(p(pid, '/literature')),
  setLiterature: (pid: string, body: { backend: 'files' | 'zotero'; collection?: string | null; create?: boolean }) =>
    put<Literature>(p(pid, '/literature'), body),
  exportBib: (pid: string) => post<Literature['exported']>(p(pid, '/literature/export')),
};

export const docmostApi = {
  status: () => get<DocmostStatus>('/api/settings/docmost'),
  setSite: (url: string | null) => patch<DocmostStatus>('/api/settings/docmost', { url }),
  login: () => post<DocmostStatus>('/api/settings/docmost/login'),
  logout: () => post<DocmostStatus>('/api/settings/docmost/logout'),
  installBrowser: () => post<DocmostStatus>('/api/settings/docmost/browser'),
  project: (pid: string) => get<DocmostProject>(p(pid, '/docmost')),
  bind: (pid: string, link: string) => put<DocmostProject>(p(pid, '/docmost'), { link }),
  unbind: (pid: string) => del<DocmostProject>(p(pid, '/docmost')),
  sync: (pid: string) => post<DocmostProject>(p(pid, '/docmost/sync')),
  conflict: (pid: string, path: string) => get<DocmostConflict>(p(pid, '/docmost/conflict'), { path }),
  resolve: (pid: string, path: string, action: 'push' | 'take' | 'recreate' | 'forget') =>
    post<DocmostProject>(p(pid, '/docmost/resolve'), { path, action }),
};
