// Small pieces the Experiments tabs share: run status, bars, durations, metric values, plain-language reasons, YAML view.
import { useEffect, useState } from 'react';
import type { TFunc } from '../../i18n';
import type { ExperimentStatus, Reason } from '../../types';

/** Run status as a dot and a word; a running run also shows its progress (indeterminate when unknown). */
export function StatusCell({ status, progress, t }: { status: ExperimentStatus; progress?: number | null; t: TFunc }) {
  return (
    <span className="ex-status">
      <span className="row" style={{ gap: 6 }}>
        <span className={`ex-dot ex-dot-${status}`} aria-hidden="true" />
        <span>{t(`ex.status.${status}`)}</span>
        {status === 'running' && progress != null && <span className="faint num ex-small">{Math.round(progress * 100)}%</span>}
      </span>
      {status === 'running' && <Progress value={progress ?? null} label={t('ex.d.progress')} />}
    </span>
  );
}

export function Progress({ value, label }: { value: number | null; label: string }) {
  const pct = value == null ? null : Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className={`ex-progress ${pct == null ? 'indeterminate' : ''}`} role="progressbar" aria-label={label}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct == null ? undefined : Math.round(pct)}>
      <span style={pct == null ? undefined : { width: `${pct}%` }} />
    </span>
  );
}

/** A thin meter; `value` null draws an empty, dashed track (unknown is never drawn as zero). */
export function Meter({ value, max = 100, tone = 'process', title }: { value: number | null | undefined; max?: number | null; tone?: 'process' | 'data' | 'warn'; title?: string }) {
  const known = value != null && max != null && max > 0;
  const pct = known ? Math.max(0, Math.min(1, value! / max!)) * 100 : 0;
  return (
    <span className={`ex-meter ${known ? '' : 'unknown'}`} title={title}>
      {known && <span className={`ex-meter-fill ${tone}`} style={{ width: `${pct}%` }} />}
    </span>
  );
}

export function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ts = Date.parse(iso);
  return Number.isFinite(ts) ? ts : null;
}

export function formatDuration(ms: number | null, t: TFunc): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '—';
  const s = Math.round(ms / 1000);
  if (s < 60) return t('ex.u.s', { n: s });
  const m = Math.round(s / 60);
  if (m < 60) return t('ex.u.m', { n: m });
  const h = Math.floor(s / 3600);
  if (h < 24) return t('ex.u.h', { h, m: String(Math.floor((s % 3600) / 60)).padStart(2, '0') });
  return t('ex.u.d', { d: Math.floor(h / 24), h: h % 24 });
}

/** Elapsed time of a run: finished − started, or now − started while it runs. */
export function runDuration(started: string | null, finished: string | null, now: number): number | null {
  const a = parseTime(started);
  if (a == null) return null;
  const b = parseTime(finished) ?? now;
  return b - a;
}

/** Re-render every `ms` while `active` (live durations, telemetry ages). */
export function useNow(ms: number, active = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms, active]);
  return now;
}

export function formatValue(v: unknown, lang: string): string {
  if (v == null) return '—';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v);
    const abs = Math.abs(v);
    const digits = abs >= 1000 ? 0 : abs >= 10 ? 1 : abs >= 1 ? 2 : 3;
    return v.toLocaleString(lang === 'zh' ? 'zh-CN' : 'en', { maximumFractionDigits: digits });
  }
  return String(v);
}

/** MiB → "12.3 GiB" (resources report GPU memory in MiB). */
export function gib(mib: number | null | undefined): string {
  return mib == null ? '—' : `${(mib / 1024).toFixed(mib >= 10240 ? 0 : 1)}`;
}

// ---------------------------------------------------------------- reasons in plain language

const ADDR_KINDS = ['code', 'cfg', 'data', 'env', 'dir', 'node', 'run'] as const;
const short = (fp: string | null | undefined) => (fp ? (fp.length > 14 ? `${fp.slice(0, 12)}…` : fp) : '∅');

function addrText(addr: string, from: string | null | undefined, to: string | null | undefined, t: TFunc): string {
  const m = addr.match(/^([a-z]+):(.*)$/);
  const kind = m?.[1] as (typeof ADDR_KINDS)[number] | undefined;
  const change = from != null || to != null ? t('ex.reason.change', { from: short(from), to: short(to) }) : '';
  if (!m || !kind || !(ADDR_KINDS as readonly string[]).includes(kind)) return `${addr}${change}`;
  return t(`ex.reason.${kind}`, { target: m[2], change });
}

/** A reason string from the experiments backend ("code:src/x.py changed (p:41ac → p:d07e)") in the UI language. */
export function reasonText(reason: string, t: TFunc): string {
  const m = reason.match(/^(?:\w+ because )?([a-z]+:\S+) changed(?:\s+(?:\((.*?)\s*→\s*(.*?)\)|(\S+)\s*→\s*(\S+)))?(?:\s+in\s+\S+)?\.?$/);
  if (m) return addrText(m[1], m[2] ?? m[4], m[3] ?? m[5], t);
  if (['unbuilt', 'pending', 'orphaned', 'stale'].includes(reason)) return t(`ex.reason.${reason}`);
  return reason;
}

/** A DAG Reason object (CellEval.why) in plain language. */
export function dagReasonText(r: Reason, t: TFunc): string {
  if (r.note) return r.note;
  if (r.addr) return addrText(r.addr, r.from, r.to, t);
  if (['unbuilt', 'pending', 'orphaned', 'stale'].includes(r.level)) return t(`ex.reason.${r.level}`);
  return r.edge ?? r.level;
}

// ---------------------------------------------------------------- YAML view of a JSON value (display only)

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
function yamlScalar(v: unknown): string {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'string') {
    const plain = /^[A-Za-z_./][\w./@+-]*$/.test(v) && !/^(true|false|null|yes|no|on|off|~)$/i.test(v);
    return plain ? v : JSON.stringify(v);
  }
  return String(v);
}
const yamlKey = (k: string) => (/^[A-Za-z_][\w.-]*$/.test(k) ? k : JSON.stringify(k));

export function toYaml(v: unknown, indent = 0): string {
  const pad = '  '.repeat(indent);
  if (Array.isArray(v)) {
    if (!v.length) return `${pad}[]`;
    return v.map(x => (isObj(x) || Array.isArray(x)) && (Array.isArray(x) ? x.length : Object.keys(x).length)
      ? `${pad}-\n${toYaml(x, indent + 1)}` : `${pad}- ${isObj(x) ? '{}' : Array.isArray(x) ? '[]' : yamlScalar(x)}`).join('\n');
  }
  if (isObj(v)) {
    const keys = Object.keys(v);
    if (!keys.length) return `${pad}{}`;
    return keys.map(k => {
      const x = v[k];
      const nested = (isObj(x) && Object.keys(x).length) || (Array.isArray(x) && x.length);
      if (nested) return `${pad}${yamlKey(k)}:\n${toYaml(x, indent + 1)}`;
      return `${pad}${yamlKey(k)}: ${isObj(x) ? '{}' : Array.isArray(x) ? '[]' : yamlScalar(x)}`;
    }).join('\n');
  }
  return pad + yamlScalar(v);
}
