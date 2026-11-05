// The Review tab's state, owned by the panel so a review keeps running while the user looks at other tabs.
// The last review (range, run, findings) and the resolved / dismissed marks are kept per project in localStorage;
// marks are keyed by a fingerprint of file + title, so a re-run of the same review keeps them.
// A review still running when the panel unmounts is re-attached on the next mount (the run stream replays).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { get } from '../../api/client';
import { extractJson } from '../../agent/useAgentRun';
import type { CodeFinding } from '../../types';
import { startReview, type Focus, type Range } from './api';
import { SEVERITIES } from './parts';
import { useFollowRun, type RunMeta, type RunOutcome } from './useFollowRun';

export type FindingStatus = CodeFinding['status'];

export interface StoredReview {
  runId: string;
  range: Range;
  focus: Focus | null;
  startedAt: number;
  finishedAt: number | null;
  meta: RunMeta | null;
  status: 'running' | 'done' | 'error' | 'cancelled';
  findings: CodeFinding[] | null;   // null: no answer yet, or it held no findings JSON
  raw: string;
  error: string | null;
  files: number | null;
  truncated: boolean;
}

const MAX_MARKS = 500;
const reviewKey = (pid: string) => `rd.cd.review.${pid}`;
const marksKey = (pid: string) => `rd.cd.findingMarks.${pid}`;

function readJson<T>(key: string): T | null {
  try { const v = localStorage.getItem(key); return v ? (JSON.parse(v) as T) : null; } catch { return null; }
}
function writeJson(key: string, value: unknown): void {
  try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); } catch { /* full or unavailable */ }
}

function fingerprint(file: string, title: string): string {
  const s = `${file}\u0000${title.trim().toLowerCase()}`;
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

/** The findings of a reviewer's answer: {"findings": [...]} (or a bare array), normalized; null if there is none. */
export function parseFindings(text: string): CodeFinding[] | null {
  const data = extractJson<unknown>(text);
  const list: unknown = Array.isArray(data) ? data : (data && typeof data === 'object' ? (data as { findings?: unknown }).findings : null);
  if (!Array.isArray(list)) return null;
  const seen = new Set<string>();
  return list.filter((f): f is Record<string, unknown> => !!f && typeof f === 'object').map((f) => {
    const severity = (SEVERITIES as string[]).includes(String(f.severity)) ? (f.severity as CodeFinding['severity']) : 'info';
    const file = String(f.file ?? f.path ?? '').replace(/^[ab]\//, '');
    const lineNum = Number(f.line);
    const line = f.line != null && f.line !== '' && Number.isFinite(lineNum) && lineNum > 0 ? Math.round(lineNum) : null;
    const body = String(f.body ?? f.description ?? '');
    const title = String(f.title ?? '').trim() || body.split('\n')[0].slice(0, 100);
    let id = fingerprint(file, title);
    while (seen.has(id)) id += '+';
    seen.add(id);
    const suggestion = f.suggestion == null || f.suggestion === '' ? null : String(f.suggestion);
    return { id, file, line, severity, title, body, suggestion, status: 'open' as const };
  }).sort((a, b) => SEVERITIES.indexOf(a.severity) - SEVERITIES.indexOf(b.severity));
}

export function useReview(pid: string, lang: string) {
  const [stored, setStored] = useState<StoredReview | null>(() => readJson<StoredReview>(reviewKey(pid)));
  const [marks, setMarks] = useState<Record<string, FindingStatus>>(() => readJson(marksKey(pid)) ?? {});
  useEffect(() => { writeJson(reviewKey(pid), stored); }, [pid, stored]);
  useEffect(() => { writeJson(marksKey(pid), marks); }, [pid, marks]);

  const finish = useCallback((o: RunOutcome) => {
    setStored(s => s && ({
      ...s, finishedAt: Date.now(), raw: o.text, error: o.ok ? null : (o.error ?? s.error),
      status: o.cancelled ? 'cancelled' : o.ok ? 'done' : 'error', findings: o.ok ? parseFindings(o.text) : null,
    }));
  }, []);
  const run = useFollowRun(finish);

  // Re-attach to a review that was still running when this panel was last open.
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current) return;
    resumed.current = true;
    const s = stored;
    if (!s || s.status !== 'running') return;
    get<{ status: string; text: string; error?: string | null }>(`/api/agent/runs/${encodeURIComponent(s.runId)}`)
      .then(r => {
        if (r.status === 'running') run.attach(s.runId, s.meta, s.startedAt);
        else finish({ text: r.text, ok: r.status === 'done', cancelled: r.status === 'cancelled', error: r.error ?? null });
      })
      .catch(() => setStored(x => x && ({ ...x, status: 'error', error: 'lost' })));
  }, [stored, run, finish]);

  const start = useCallback(async (range: Range, focus: Focus | null = null) => {
    const startedAt = Date.now();
    if (run.running) run.cancel();          // one review at a time
    const r = await run.start(() => startReview(pid, range, lang, focus));
    if (!r) return false;
    setStored({
      runId: r.run_id, range, focus, startedAt, finishedAt: null, status: 'running', findings: null, raw: '', error: null,
      meta: { provider: r.provider, model: r.model, effort: r.effort, fast: r.fast }, files: r.files ?? null, truncated: !!r.truncated,
    });
    return true;
  }, [run, pid, lang]);

  const setMark = useCallback((id: string, status: FindingStatus) => {
    setMarks(m => {
      const next = { ...m };
      delete next[id];
      if (status !== 'open') next[id] = status;
      const keys = Object.keys(next);
      for (const k of keys.slice(0, Math.max(0, keys.length - MAX_MARKS))) delete next[k];
      return next;
    });
  }, []);

  const clear = useCallback(() => { run.reset(); setStored(null); }, [run]);

  const findings = useMemo(() => stored?.findings?.map(f => ({ ...f, status: marks[f.id] ?? 'open' })) ?? null, [stored, marks]);
  const openCount = findings?.filter(f => f.status === 'open').length ?? 0;
  const openHigh = findings?.filter(f => f.status === 'open' && f.severity === 'high').length ?? 0;

  return { stored, findings, run, start, setMark, clear, openCount, openHigh };
}

export type ReviewController = ReturnType<typeof useReview>;
