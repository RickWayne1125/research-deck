// Coding panel calls (docs/API.md § Coding) and the extra fields the backend adds to the shared types.
import { get, p, post } from '../../api/client';
import type { Architecture, ArchModule, DiffFile, DiffResult, GitCommit, GitStatus, RunStarted } from '../../types';

export type CdModule = ArchModule & { lang?: 'py' | 'ts' | 'js' };
export type CdComponent = Architecture['components'][number] & { source?: 'yaml' | 'dag' };
export type CdDiffFile = DiffFile & { untracked?: boolean; truncated?: boolean };
export interface CdDiff extends Omit<DiffResult, 'files'> { files: CdDiffFile[]; truncated?: boolean; is_repo?: boolean }
export interface CdStatus extends GitStatus { upstream?: string | null; dirty: { path: string; status: string; staged?: boolean }[] }
export type Started = RunStarted & { files?: number; truncated?: boolean; from?: string | null; to?: string | null };

/** What a diff shows: uncommitted work (vs HEAD) or one commit's own changes. */
export type Range = { kind: 'working' } | { kind: 'commit'; sha: string; short: string; subject?: string };
export const WORKING: Range = { kind: 'working' };
export const rangeKey = (r: Range) => (r.kind === 'working' ? 'working' : r.sha);
export const sameRange = (a: Range | null, b: Range | null) => !!a && !!b && rangeKey(a) === rangeKey(b);
export const commitRange = (c: GitCommit): Range => ({ kind: 'commit', sha: c.sha, short: c.short, subject: c.subject });

/** Lines to focus a review on ("review selection"); numbers of the new version. */
export interface Focus { path: string; start_line: number; end_line: number }

// A research workspace can hold several repositories (code.repos in project.yaml). The one the panel looks at is
// remembered per project; every git call below sends it. Paths in responses stay relative to the project root.
// dirty is null (with error set) when a repository did not answer in time or could not be read (repos.py listing).
export interface RepoInfo { repo: string | null; label: string; is_repo: boolean; branch: string | null; head: string | null; dirty: number | null; error?: string }
const repoKey = (pid: string) => `rd.coding.repo.${pid}`;
export function currentRepo(pid: string): string | null {
  try { return localStorage.getItem(repoKey(pid)); } catch { return null; }
}
export function setCurrentRepo(pid: string, repo: string | null): void {
  try { if (repo) localStorage.setItem(repoKey(pid), repo); else localStorage.removeItem(repoKey(pid)); } catch { /* ignore */ }
}
const rq = (pid: string) => { const r = currentRepo(pid); return r ? { repo: r } : {}; };

export const fetchRepos = (pid: string) => get<RepoInfo[]>(p(pid, '/git/repos'));
export const fetchStatus = (pid: string) => get<CdStatus>(p(pid, '/git/status'), rq(pid));
export const fetchLog = (pid: string, limit = 150) => get<GitCommit[]>(p(pid, '/git/log'), { limit, ...rq(pid) });
export const fetchDiff = (pid: string, r: Range) => get<CdDiff>(p(pid, '/git/diff'), { ...(r.kind === 'commit' ? { to: r.sha } : {}), ...rq(pid) });

export const startReview = (pid: string, r: Range, lang: string, focus?: Focus | null) =>
  post<Started>(p(pid, '/coding/review'), { ...(r.kind === 'commit' ? { to: r.sha } : {}), ...(focus ? { focus, paths: [focus.path] } : {}), lang, ...rq(pid) });

export const startExplain = (pid: string, body: { path: string; start_line?: number; end_line?: number; rev?: string; lang: string }) =>
  post<Started>(p(pid, '/coding/explain'), { ...body, ...rq(pid) });
