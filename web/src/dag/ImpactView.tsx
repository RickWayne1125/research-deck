// The impact preview of a change (docs/DAG.md §5, §8): a summary bar, the precision badge, what the change patches,
// and grouped lists (rerun, conditional, revived, already tried, review/orphaned/broken, locks, gates, suggested
// restores, reused) whose why-paths highlight on hover. Shared by the DAG panel (what-if edits, rollbacks) and the
// overview Inbox (proposals). ImpactDialog wraps it with the lock checklist and Apply / Discard.
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Icon } from '../components/icons';
import { Button, Dialog, Spinner } from '../components/ui';
import { registerStrings, useT } from '../i18n';
import { parseAddr } from './api';
import type { Impact, ImpactItem } from '../dag-types';
import './impact.css';

registerStrings({
  zh: {
    'dagx.impact.exact': '精确', 'dagx.impact.predicted': '预测',
    'dagx.impact.exactHint': '按实际改动的代码和配置计算',
    'dagx.impact.predictedHint': '代码尚未写出：按实现该设计的模块文件推测，实际提交后会重新精确计算',
    'dagx.impact.rerun': '需重跑', 'dagx.impact.conditional': '视结果而定', 'dagx.impact.reused': '可复用',
    'dagx.impact.revived': '复活', 'dagx.impact.review': '需复核', 'dagx.impact.orphaned': '上游失效',
    'dagx.impact.broken': '不成立', 'dagx.impact.lock': '锁定', 'dagx.impact.already_tried': '以前试过',
    'dagx.impact.suggest_restore': '建议一并恢复', 'dagx.impact.gates': '门禁变化', 'dagx.impact.patched': '这次改动',
    'dagx.impact.none': '这次改动不影响任何节点或实验格。',
    'dagx.impact.cells': '{n} 格', 'dagx.impact.gpuh': '{h} GPU·h',
    'dagx.impact.implFirst': '先实现', 'dagx.impact.implFirstHint': '结果反映的代码已与设计不符：先改代码，再重跑',
    'dagx.impact.margin': '余量 {m}', 'dagx.impact.current': '当前 {v}',
    'dagx.impact.requiresHuman': '需要你来批准', 'dagx.impact.errors': '无法完整计算',
    'dagx.impact.why': '原因链', 'dagx.impact.more': '另外 {n} 项',
    'dagx.impact.showAll': '展开全部', 'dagx.impact.showLess': '收起',
    'dagx.impact.digest': '基于 {d}',
    'dagx.impact.recovered': '省下 {h} GPU·h',
    'dagx.impact.requires': '需要 {r}',
    'dagx.impact.lockChecks': '锁定项（全部勾选后才能应用）',
    'dagx.impact.unlockCheck': '先解锁 {id}（解锁原因随批准一起记录）',
    'dagx.impact.ackCheck': '我知道已锁定的 {id} 会受影响（{kind}）',
    'dagx.impact.apply': '应用', 'dagx.impact.discard': '放弃', 'dagx.impact.close': '关闭',
    'dagx.impact.loading': '正在计算影响…',
  },
  en: {
    'dagx.impact.exact': 'Exact', 'dagx.impact.predicted': 'Predicted',
    'dagx.impact.exactHint': 'Computed from the actual code and config change',
    'dagx.impact.predictedHint': 'No code yet: predicted from the files of the modules that implement this design; re-previewed exactly once the code lands',
    'dagx.impact.rerun': 'Rerun', 'dagx.impact.conditional': 'Conditional', 'dagx.impact.reused': 'Reused',
    'dagx.impact.revived': 'Revived', 'dagx.impact.review': 'Review', 'dagx.impact.orphaned': 'Orphaned',
    'dagx.impact.broken': 'Broken', 'dagx.impact.lock': 'Lock', 'dagx.impact.already_tried': 'Already tried',
    'dagx.impact.suggest_restore': 'Suggested restores', 'dagx.impact.gates': 'Gates', 'dagx.impact.patched': 'This change',
    'dagx.impact.none': 'This change affects no node or cell.',
    'dagx.impact.cells': '{n} cells', 'dagx.impact.gpuh': '{h} GPU-h',
    'dagx.impact.implFirst': 'implement first', 'dagx.impact.implFirstHint': 'Results reflect code that no longer matches the design: change the code, then rerun',
    'dagx.impact.margin': 'margin {m}', 'dagx.impact.current': 'now {v}',
    'dagx.impact.requiresHuman': 'Needs your approval', 'dagx.impact.errors': 'Could not compute everything',
    'dagx.impact.why': 'Why', 'dagx.impact.more': '{n} more',
    'dagx.impact.showAll': 'Show all', 'dagx.impact.showLess': 'Show less',
    'dagx.impact.digest': 'against {d}',
    'dagx.impact.recovered': '{h} GPU-h recovered',
    'dagx.impact.requires': 'requires {r}',
    'dagx.impact.lockChecks': 'Locks (tick all to apply)',
    'dagx.impact.unlockCheck': 'Unlock {id} first (the reason is logged with your approval)',
    'dagx.impact.ackCheck': 'I accept that locked {id} is affected ({kind})',
    'dagx.impact.apply': 'Apply', 'dagx.impact.discard': 'Discard', 'dagx.impact.close': 'Close',
    'dagx.impact.loading': 'Computing impact…',
  },
});

// ------------------------------------------------------------------ categories (also used to paint the map)

export type ImpactCategory = 'rerun' | 'conditional' | 'reused' | 'revived' | 'review' | 'orphaned' | 'broken' | 'lock' | 'already_tried' | 'patched';
const LIST_KEYS = ['rerun', 'conditional', 'revived', 'already_tried', 'broken', 'review', 'orphaned', 'lock', 'reused'] as const;

/** Node id → the categories it falls in. `patched` marks the nodes the change itself edits. */
export function impactCategories(impact: Impact | null | undefined): Map<string, Set<ImpactCategory>> {
  const m = new Map<string, Set<ImpactCategory>>();
  if (!impact) return m;
  const add = (id: string | undefined, c: ImpactCategory) => {
    if (!id) return;
    const s = m.get(id) ?? new Set<ImpactCategory>();
    s.add(c); m.set(id, s);
  };
  for (const k of LIST_KEYS) for (const it of impact[k] ?? []) add(it.node, k);
  for (const p of impact.patched ?? []) { const a = parseAddr(p.addr); if (a.scheme === 'node') add(a.id, 'patched'); }
  return m;
}

/** The one category that decides how a node is painted in preview mode (strongest first). */
export const CATEGORY_PRECEDENCE: ImpactCategory[] = ['broken', 'rerun', 'conditional', 'review', 'orphaned', 'revived', 'already_tried', 'reused', 'patched'];
export function primaryCategory(cats: Set<ImpactCategory> | undefined): ImpactCategory | null {
  if (!cats) return null;
  return CATEGORY_PRECEDENCE.find(c => cats.has(c)) ?? (cats.has('lock') ? 'lock' : null);
}

/** Node ids along an item's why-path (plus the item's own node), for hover highlighting. */
export function whyPathNodes(impact: Impact, item: ImpactItem): string[] {
  const ids = new Set<string>([item.node]);
  const paths = impact.why_paths ?? {};
  const keys = Object.keys(paths).filter(k => k === item.node || k.startsWith(`${item.node}[`));
  for (const k of keys) for (const step of paths[k]) {
    const a = parseAddr(step);
    if (a.scheme === 'node') ids.add(a.id);
    else if (!a.scheme && /^[a-z]+\.[\w.-]+$/.test(step)) ids.add(step);   // bare node ids between edge labels
  }
  for (const v of item.via ?? []) ids.add(v);
  return [...ids];
}

function whyPathFor(impact: Impact, item: ImpactItem): string[] | null {
  const paths = impact.why_paths ?? {};
  const key = Object.keys(paths).find(k => k === item.node || k.startsWith(`${item.node}[`));
  return key ? paths[key] : null;
}

// ------------------------------------------------------------------ formatting

const shortVal = (v: unknown): string => {
  if (v === null || v === undefined) return '∅';
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  if (/^[a-z]:[0-9a-f]{8,}$/.test(s)) return `${s.slice(0, 6)}…`;
  return s.length > 42 ? `${s.slice(0, 40)}…` : s;
};
const gpu = (h: number | null | undefined) => (h == null || !Number.isFinite(h) ? '—' : h >= 10 ? h.toFixed(0) : h >= 1 ? h.toFixed(1) : h === 0 ? '0' : h.toFixed(2));

const TONE: Record<ImpactCategory | 'gates' | 'suggest_restore', string> = {
  rerun: 'stale', conditional: 'stale', reused: 'info', revived: 'data', review: 'warn', orphaned: 'emphasis',
  broken: 'accent', lock: 'accent', already_tried: 'neutral', patched: 'neutral', gates: 'neutral', suggest_restore: 'info',
};

// ------------------------------------------------------------------ ImpactView

export function ImpactView(props: { impact: Impact; compact?: boolean; onHoverNodes?: (ids: string[]) => void }): JSX.Element {
  const { impact, compact, onHoverNodes } = props;
  const t = useT();
  const s = impact.summary;
  const total = LIST_KEYS.reduce((n, k) => n + (impact[k]?.length ?? 0), 0) + (impact.gates?.length ?? 0) + (impact.suggest_restore?.length ?? 0);
  const hover = (ids: string[]) => onHoverNodes?.(ids);

  const chips: { key: ImpactCategory; n: number; extra?: string }[] = [
    { key: 'rerun', n: s.rerun, extra: s.gpu_h?.rerun ? t('dagx.impact.gpuh', { h: gpu(s.gpu_h.rerun) }) : undefined },
    { key: 'reused', n: s.reused, extra: s.gpu_h?.reused ? t('dagx.impact.gpuh', { h: gpu(s.gpu_h.reused) }) : undefined },
    { key: 'review', n: s.review },
    { key: 'conditional', n: s.conditional },
    { key: 'revived', n: s.revived },
    { key: 'orphaned', n: s.orphaned },
    { key: 'broken', n: s.broken },
    { key: 'lock', n: s.lock },
  ];

  return (
    <div className={`dgx-impact ${compact ? 'is-compact' : ''}`} onMouseLeave={() => hover([])}>
      <div className="dgx-impact-summary" role="group" aria-label={t('dagx.impact.patched')}>
        <span className={`dgx-precision ${impact.precision}`} title={t(`dagx.impact.${impact.precision}Hint`)}>
          <Icon name={impact.precision === 'exact' ? 'check' : 'sparkle'} size={11} />{t(`dagx.impact.${impact.precision}`)}
        </span>
        {chips.filter(c => c.n > 0 || c.key === 'rerun' || c.key === 'reused').map((c, i) => (
          <span key={c.key} className={`dgx-sum tone-${TONE[c.key]} ${c.n === 0 ? 'is-zero' : ''}`}>
            {i > 0 && <span className="dgx-sep" aria-hidden="true">·</span>}
            <span>{t(`dagx.impact.${c.key}`)}</span> <b className="num">{c.n}</b>{c.extra && <span className="faint num"> ({c.extra})</span>}
          </span>
        ))}
      </div>

      {impact.requires_human?.value && (
        <div className="notice warn dgx-notice"><Icon name="lock" /><span>{t('dagx.impact.requiresHuman')}{impact.requires_human.reasons.length ? `: ${impact.requires_human.reasons.join('; ')}` : ''}</span></div>
      )}
      {!!impact.errors?.length && (
        <div className="notice accent dgx-notice"><Icon name="warn" /><span>{t('dagx.impact.errors')}: {impact.errors.join('; ')}</span></div>
      )}

      {!compact && impact.patched?.length > 0 && (
        <Group title={t('dagx.impact.patched')} tone="neutral" count={impact.patched.length} compact={false}>
          {impact.patched.map((p, i) => (
            <li key={`${p.addr}-${i}`} className="dgx-item is-static">
              <div className="dgx-addr mono ellipsis" title={p.addr}>{p.addr}</div>
              <div className="dgx-fromto mono"><span>{shortVal(p.from)}</span><Icon name="chevronRight" size={11} /><span>{shortVal(p.to)}</span></div>
              {p.via && <div className="faint dgx-via">{p.via}</div>}
            </li>
          ))}
        </Group>
      )}

      {total === 0 && <div className="muted dgx-none">{t('dagx.impact.none')}</div>}

      {LIST_KEYS.map(k => {
        const items = impact[k] ?? [];
        if (!items.length) return null;
        return (
          <Group key={k} title={t(`dagx.impact.${k}`)} tone={TONE[k]} count={items.length} compact={!!compact} defaultOpen={!compact || k !== 'reused'}>
            {items.map((it, i) => <Item key={`${it.node}-${i}`} kind={k} item={it} impact={impact} onHover={hover} />)}
          </Group>
        );
      })}

      {!!impact.gates?.length && (
        <Group title={t('dagx.impact.gates')} tone="neutral" count={impact.gates.length} compact={!!compact}>
          {impact.gates.map(g => (
            <li key={g.gate} className="dgx-item is-static">
              <div className="row"><b className="mono">{g.gate}</b><span className="dgx-fromto mono"><span>{g.from}</span><Icon name="chevronRight" size={11} /><span>{g.to}</span></span></div>
            </li>
          ))}
        </Group>
      )}
      {!!impact.suggest_restore?.length && (
        <Group title={t('dagx.impact.suggest_restore')} tone="info" count={impact.suggest_restore.length} compact={!!compact}>
          {impact.suggest_restore.map((it, i) => <Item key={`${it.node}-${i}`} kind="suggest_restore" item={it} impact={impact} onHover={hover} />)}
        </Group>
      )}
      {!compact && impact.base_digest && <div className="faint mono dgx-digest">{t('dagx.impact.digest', { d: impact.base_digest })}</div>}
    </div>
  );
}

function Group({ title, tone, count, compact, defaultOpen = true, children }: { title: string; tone: string; count: number; compact: boolean; defaultOpen?: boolean; children: ReactNode[] | ReactNode }) {
  const t = useT();
  const [all, setAll] = useState(false);
  const list = Array.isArray(children) ? children : [children];
  const limit = compact ? 3 : 8;
  const shown = all ? list : list.slice(0, limit);
  return (
    <details className={`dgx-group tone-${tone}`} open={defaultOpen}>
      <summary><span className="dgx-swatch" aria-hidden="true" /><span className="label">{title}</span><span className="faint num">{count}</span></summary>
      <ul className="dgx-list">{shown}</ul>
      {list.length > limit && (
        <button type="button" className="dgx-more" onClick={() => setAll(a => !a)}>
          {all ? t('dagx.impact.showLess') : t('dagx.impact.more', { n: list.length - limit })}
        </button>
      )}
    </details>
  );
}

function Item({ kind, item, impact, onHover }: { kind: string; item: ImpactItem; impact: Impact; onHover: (ids: string[]) => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const path = whyPathFor(impact, item);
  const why = (item.why ?? []) as { addr?: string; from?: string | null; to?: string | null; note?: string }[];
  const ids = useMemo(() => whyPathNodes(impact, item), [impact, item]);
  const expandable = !!path || why.length > 0 || (item.cells?.length ?? 0) > 3;
  return (
    <li className={`dgx-item ${open ? 'is-open' : ''}`} onMouseEnter={() => onHover(ids)} onFocus={() => onHover(ids)}>
      <button type="button" className="dgx-item-head" onClick={() => expandable && setOpen(o => !o)} aria-expanded={expandable ? open : undefined}>
        {expandable && <Icon name={open ? 'chevronDown' : 'chevronRight'} size={11} />}
        <span className="mono ellipsis dgx-node" title={item.node}>{item.node}</span>
        {item.cells && item.cells.length > 0 && <span className="faint num">{t('dagx.impact.cells', { n: item.cells.length })}</span>}
        {item.est_gpu_h != null && <span className="faint num">{t('dagx.impact.gpuh', { h: gpu(item.est_gpu_h) })}</span>}
        {item.impl_lag && <span className="badge warn" title={t('dagx.impact.implFirstHint')}>{t('dagx.impact.implFirst')}</span>}
        {item.platform && <span className="faint mono">{item.platform}</span>}
      </button>
      <div className="dgx-item-body">
        {item.edge && <div className="mono faint ellipsis" title={item.edge}>{item.edge}</div>}
        {item.diff && <div className="dgx-diff">{item.diff}</div>}
        {item.predicate && (
          <div className="row wrap dgx-pred">
            <span className="mono">{item.predicate}</span>
            {item.current != null && <span className="faint">{t('dagx.impact.current', { v: item.current })}</span>}
            {item.margin != null && <span className={`badge ${item.margin < 0 ? 'accent' : ''}`}>{t('dagx.impact.margin', { m: item.margin })}</span>}
          </div>
        )}
        {item.reason && <div className="muted">{item.reason}</div>}
        {item.run && <div className="faint mono">{item.run}{item.age ? ` · ${item.age}` : ''}{kind === 'revived' && item.est_gpu_h ? ` · ${t('dagx.impact.recovered', { h: gpu(item.est_gpu_h) })}` : ''}</div>}
        {item.requires && <div className="faint">{t('dagx.impact.requires', { r: item.requires })}</div>}
        {item.note && <div className="muted">{item.note}</div>}
        {item.cells && item.cells.length > 0 && item.cells.length <= 3 && <div className="faint mono dgx-cells">{item.cells.join(' · ')}</div>}
      </div>
      {open && (
        <div className="dgx-expand">
          {item.cells && item.cells.length > 3 && <div className="faint mono dgx-cells">{item.cells.join(' · ')}</div>}
          {why.map((w, i) => (
            <div key={i} className="dgx-why mono">
              <span className="ellipsis" title={w.addr}>{w.addr}</span>
              {(w.from !== undefined || w.to !== undefined) && <span className="dgx-fromto"><span>{shortVal(w.from)}</span><Icon name="chevronRight" size={10} /><span>{shortVal(w.to)}</span></span>}
              {w.note && <span className="faint">{w.note}</span>}
            </div>
          ))}
          {path && (
            <div className="dgx-path" aria-label={t('dagx.impact.why')}>
              {path.map((step, i) => <span key={i} className={i % 2 ? 'dgx-path-edge' : 'dgx-path-node mono'}>{step}</span>)}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// ------------------------------------------------------------------ lock checklist

export interface LockCheckItem { id: string; kind: 'unlock' | 'ack'; label: string }

/** The lock rows a human must tick before applying: unlocks the change needs, and locked nodes it affects. */
export function lockCheckItems(impact: Impact | null, requiresUnlock: string[] | undefined, t: (k: string, v?: Record<string, string | number>) => string): LockCheckItem[] {
  const unlock = new Set((requiresUnlock ?? []).map(r => r.replace(/^unlock:/, '')));
  for (const l of impact?.lock ?? []) if (l.requires?.startsWith('unlock:')) unlock.add(l.requires.slice(7));
  const out: LockCheckItem[] = [...unlock].sort().map(id => ({ id, kind: 'unlock', label: t('dagx.impact.unlockCheck', { id }) }));
  for (const l of impact?.lock ?? []) {
    if (unlock.has(l.node)) continue;
    out.push({ id: l.node, kind: 'ack', label: t('dagx.impact.ackCheck', { id: l.node, kind: l.kind ?? 'lock' }) });
  }
  return out;
}

export function LockChecks({ items, checked, onToggle }: { items: LockCheckItem[]; checked: Set<string>; onToggle: (key: string) => void }) {
  const t = useT();
  if (!items.length) return null;
  return (
    <fieldset className="dgx-locks">
      <legend className="label">{t('dagx.impact.lockChecks')}</legend>
      {items.map(it => {
        const key = `${it.kind}:${it.id}`;
        return (
          <label key={key} className="dgx-lock">
            <input type="checkbox" checked={checked.has(key)} onChange={() => onToggle(key)} />
            <Icon name={it.kind === 'unlock' ? 'unlock' : 'lock'} size={13} />
            <span>{it.label}</span>
          </label>
        );
      })}
    </fieldset>
  );
}

/** Checkbox state for a lock list that resets whenever the set of items changes. */
export function useLockChecks(items: LockCheckItem[]) {
  const sig = items.map(i => `${i.kind}:${i.id}`).join('|');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  useEffect(() => { setChecked(new Set()); }, [sig]);
  const toggle = (key: string) => setChecked(prev => { const n = new Set(prev); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const all = items.every(i => checked.has(`${i.kind}:${i.id}`));
  return { checked, toggle, all };
}

// ------------------------------------------------------------------ ImpactDialog

export function ImpactDialog(props: {
  title: string; impact: Impact | null; loading?: boolean; error?: string | null;
  onApply?: () => void; onDiscard: () => void; applyLabel?: string; requiresUnlock?: string[]; onHoverNodes?: (ids: string[]) => void;
}): JSX.Element {
  const { title, impact, loading, error, onApply, onDiscard, applyLabel, requiresUnlock, onHoverNodes } = props;
  const t = useT();
  const items = useMemo(() => lockCheckItems(impact, requiresUnlock, t), [impact, requiresUnlock, t]);
  const locks = useLockChecks(items);
  const canApply = !!onApply && !!impact && !loading && !error && locks.all;
  return (
    <Dialog title={title} onClose={onDiscard} width={720} footer={
      <>
        <Button onClick={onDiscard}>{onApply ? t('dagx.impact.discard') : t('dagx.impact.close')}</Button>
        {onApply && <Button variant="primary" icon="check" onClick={onApply} disabled={!canApply}>{applyLabel ?? t('dagx.impact.apply')}</Button>}
      </>
    }>
      <div className="col dgx-dialog">
        {error && <div className="notice accent" role="alert"><Icon name="warn" /> <span>{error}</span></div>}
        {loading && !impact && <div className="row muted"><Spinner /> {t('dagx.impact.loading')}</div>}
        {impact && (
          <div className={loading ? 'dgx-loading' : ''}>
            <ImpactView impact={impact} onHoverNodes={onHoverNodes} />
          </div>
        )}
        {onApply && <LockChecks items={items} checked={locks.checked} onToggle={locks.toggle} />}
      </div>
    </Dialog>
  );
}
