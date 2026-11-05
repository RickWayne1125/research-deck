// Impact-preview state for the panel: what-if edits recompute 300 ms after the last keystroke (§8), rollbacks and
// relinks compute at once, and a proposal (snapshot restore) brings its own impact. Only the latest request's answer
// is kept, so a slow preview never overwrites a newer one.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { dagApi } from '../../dag/api';
import type { Impact, Op } from '../../dag-types';

export interface PreviewReq {
  key: string;                          // origin of the preview ("edit:<node>#<facet>", "rollback:<node>", …)
  title: string;
  ops: Op[];
  source: 'edit' | 'rollback' | 'relink' | 'restore' | 'other';
  node?: string;
  inline?: boolean;                     // shown inside the inspector's facet editor instead of the side panel
  fork?: { node: string; set: Record<string, unknown> } | null;   // a knob edit that can fork as an attempt
  proposalId?: string;                  // approving an existing proposal instead of posting ops
  requiresUnlock?: string[];
}
export interface PreviewState extends PreviewReq { impact: Impact | null; loading: boolean; error: string | null }

export const DEBOUNCE_MS = 300;

export function errText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { message?: string; detail?: string } | string | null;
    if (typeof d === 'string') return d;
    return d?.message ?? d?.detail ?? e.message;
  }
  return String((e as Error)?.message ?? e);
}

export function usePreview(pid: string) {
  const [state, setState] = useState<PreviewState | null>(null);
  const timer = useRef(0);
  const seq = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const compute = useCallback((req: PreviewReq, delay: number) => {
    window.clearTimeout(timer.current);
    const my = ++seq.current;
    // Keep the previous impact on screen while the same origin recomputes (no flicker while typing).
    setState(s => ({ ...req, impact: s?.key === req.key ? s.impact : null, loading: true, error: null }));
    timer.current = window.setTimeout(() => {
      dagApi.impact(pid, { ops: req.ops })
        .then(impact => { if (my === seq.current) setState(s => (s ? { ...s, impact, loading: false } : s)); })
        .catch(e => { if (my === seq.current) setState(s => (s ? { ...s, loading: false, error: errText(e) } : s)); });
    }, delay);
  }, [pid]);

  const open = useCallback((req: PreviewReq) => compute(req, 0), [compute]);
  const update = useCallback((req: PreviewReq) => compute(req, DEBOUNCE_MS), [compute]);
  const show = useCallback((req: PreviewReq, impact: Impact | null) => {
    window.clearTimeout(timer.current); seq.current++;
    setState({ ...req, impact, loading: false, error: null });
  }, []);
  const discard = useCallback(() => { window.clearTimeout(timer.current); seq.current++; setState(null); }, []);
  const setImpact = useCallback((impact: Impact, error: string | null = null) => setState(s => (s ? { ...s, impact, error, loading: false } : s)), []);

  return useMemo(() => ({ state, open, update, show, discard, setImpact }), [state, open, update, show, discard, setImpact]);
}
export type PreviewApi = ReturnType<typeof usePreview>;
