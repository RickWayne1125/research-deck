// Typed client for the writing routes (docs/API.md § Writing) plus the extra fields the backend records.
import { get, p, post, put } from '../../api/client';
import type { DocVersion, Finding, FileContent, GlossaryTerm, LearnedRule, ReviewPass, ReviewResult, WritingDoc } from '../../types';
import type { Freshness } from '../../dag-types';

/** A finding as stored: the core shape plus its dismissal fingerprint and where it was in the reviewed text. */
export interface WrFinding extends Finding { fp?: string; offset?: number; rule_id?: string; reject_reason?: string }

export interface WrReview extends Omit<ReviewResult, 'findings'> {
  findings: WrFinding[];
  created_at?: string; finished_at?: string | null; lang?: 'zh' | 'en';
  range?: { start_line: number; end_line: number } | null;
  summaries?: Partial<Record<ReviewPass, string>>;
  pass_errors?: Partial<Record<ReviewPass, string>>;
  agents?: Partial<Record<ReviewPass, { provider: string; model: string; effort: string; raw?: number; kept?: number }>>;
  cancelled?: boolean;
}

export interface ReviewSummary {
  review_id: string; path: string; passes: ReviewPass[]; status: ReviewResult['status'];
  progress: ReviewResult['progress']; created_at: string; finished_at: string | null;
  counts: Partial<Record<ReviewPass, { open: number; accepted: number; rejected: number }>>;
}

export interface DocClaim {
  id: string; label: string; text: string; line: number | null; evidence: string[];
  freshness: Freshness | null; values?: Record<string, unknown>; kind?: string;
}

export interface WrVersion extends DocVersion { author?: string; words?: number; auto?: boolean }
export interface WrRule extends LearnedRule { example?: { kind?: string; quote?: string; replacement?: string } }

const w = (pid: string, rest: string) => p(pid, `/writing${rest}`);
const enc = encodeURIComponent;

export const writingApi = {
  docs: (pid: string) => get<WritingDoc[]>(w(pid, '/docs')),
  file: (pid: string, path: string) => get<FileContent>(p(pid, '/file'), { path }),
  save: (pid: string, path: string, content: string, base_sha?: string | null) =>
    put<{ path: string; sha: string; mtime: number }>(p(pid, '/file'), { path, content, base_sha: base_sha ?? undefined }),
  review: (pid: string, body: { path: string; passes: ReviewPass[]; text?: string; range?: { start_line: number; end_line: number }; lang?: string }) =>
    post<WrReview>(w(pid, '/review'), body),
  getReview: (pid: string, id: string) => get<WrReview>(w(pid, `/review/${enc(id)}`)),
  reviews: (pid: string, path: string, limit = 5) => get<ReviewSummary[]>(w(pid, '/reviews'), { path, limit }),
  cancel: (pid: string, id: string) => post<WrReview>(w(pid, `/review/${enc(id)}/cancel`)),
  decide: (pid: string, reviewId: string, findingId: string, status: Finding['status'], reason?: string) =>
    post<WrFinding>(w(pid, `/findings/${enc(reviewId)}/${enc(findingId)}`), { status, reason: reason || undefined }),
  decideMany: (pid: string, reviewId: string, ids: string[], status: Finding['status']) =>
    post<WrFinding[]>(w(pid, `/findings/${enc(reviewId)}`), { ids, status }),
  glossary: (pid: string) => get<{ terms: GlossaryTerm[] }>(w(pid, '/glossary')),
  putGlossary: (pid: string, terms: GlossaryTerm[]) => put<{ terms: GlossaryTerm[] }>(w(pid, '/glossary'), { terms }),
  rules: (pid: string) => get<{ rules: WrRule[] }>(w(pid, '/rules')),
  putRules: (pid: string, rules: WrRule[]) => put<{ rules: WrRule[] }>(w(pid, '/rules'), { rules }),
  versions: (pid: string, path: string) => get<WrVersion[]>(w(pid, '/versions'), { path }),
  snapshot: (pid: string, path: string, label?: string) => post<WrVersion>(w(pid, '/versions'), { path, label }),
  version: (pid: string, path: string, id: string) => get<{ content: string }>(w(pid, `/versions/${enc(id)}`), { path }),
  claims: (pid: string, path: string) => get<{ claims: DocClaim[] }>(w(pid, '/claims'), { path }),
};
