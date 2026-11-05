// The impact side panel of preview mode (docs/DAG.md §8): ImpactView plus what only this panel offers — one-click
// rollback-closure restores, the lock checklist, a reason that is logged with the change, and Apply / Apply and plan
// reruns / Fork as attempt / Discard. ImpactBody is also embedded in the inspector under a what-if facet edit.
import { useMemo, useState } from 'react';
import { Icon } from '../../components/icons';
import { Button, IconButton, Spinner } from '../../components/ui';
import { useT } from '../../i18n';
import { ImpactView, LockChecks, lockCheckItems, useLockChecks } from '../../dag/ImpactView';
import type { Op } from '../../dag-types';
import type { PreviewState } from './preview';

export interface ApplyArgs { reason: string; unlock: string[]; queue: boolean }

export function ImpactBody({ state, busy, onApply, onDiscard, onFork, onAddOp, onHoverNodes, compact, readOnly }: {
  state: PreviewState; busy: boolean;
  onApply: (a: ApplyArgs) => void; onDiscard: () => void; onFork?: () => void; onAddOp?: (op: Op) => void;
  onHoverNodes: (ids: string[]) => void; compact?: boolean; readOnly?: boolean;
}) {
  const t = useT();
  const { impact, loading, error } = state;
  const items = useMemo(() => lockCheckItems(impact, state.requiresUnlock, t), [impact, state.requiresUnlock, t]);
  const locks = useLockChecks(items);
  const [reason, setReason] = useState('');
  const unlocking = items.filter(i => i.kind === 'unlock').map(i => i.id);
  const needsReason = unlocking.length > 0;
  const canApply = !readOnly && !!impact && !loading && !error && !busy && locks.all && (!needsReason || reason.trim().length > 0);
  const restores = (impact?.suggest_restore ?? []).filter(s => s.op);
  const reruns = impact?.summary.rerun ?? 0;

  return (
    <div className="dg-impact-body col">
      {error && <div className="notice accent" role="alert"><Icon name="warn" /> <span>{error}</span></div>}
      {loading && !impact && <div className="row muted"><Spinner /> {t('dag.preview.computing')}</div>}
      {impact && (
        <div className={loading ? 'dgx-loading' : ''}>
          <ImpactView impact={impact} compact={compact} onHoverNodes={onHoverNodes} />
        </div>
      )}
      {restores.length > 0 && onAddOp && !readOnly && (
        <div className="dg-restores col">
          <span className="label">{t('dag.preview.closure')}</span>
          {restores.map((s, i) => (
            <button key={i} type="button" className="dg-restore" onClick={() => onAddOp(s.op!)} disabled={busy}>
              <Icon name="plus" size={12} /><span className="ellipsis">{s.note ?? s.reason ?? s.node}</span>
            </button>
          ))}
        </div>
      )}
      {!readOnly && <LockChecks items={items} checked={locks.checked} onToggle={locks.toggle} />}
      {!readOnly && (
        <label className="field">
          <span className="label">{needsReason ? t('dag.preview.reasonRequired') : t('dag.preview.reason')}</span>
          <input className="input" value={reason} onChange={e => setReason(e.target.value)} placeholder={t('dag.preview.reasonPh')} />
        </label>
      )}
      <div className="dg-impact-actions">
        <Button onClick={onDiscard} disabled={busy}>{t('dag.preview.discard')}</Button>
        <span className="grow" />
        {onFork && !readOnly && (
          <Button icon="branch" onClick={onFork} disabled={!impact || loading || busy} title={t('dag.preview.forkHint')}>{t('dag.preview.fork')}</Button>
        )}
        {!readOnly && reruns > 0 && (
          <Button onClick={() => onApply({ reason, unlock: unlocking, queue: true })} disabled={!canApply} title={t('dag.preview.applyQueueHint')}>{t('dag.preview.applyQueue')}</Button>
        )}
        {!readOnly && (
          <Button variant="primary" icon={busy ? undefined : 'check'} onClick={() => onApply({ reason, unlock: unlocking, queue: false })} disabled={!canApply}>
            {busy && <Spinner />}{state.proposalId ? t('dag.preview.approve') : t('dag.preview.apply')}
          </Button>
        )}
      </div>
    </div>
  );
}

export function ImpactPanel(props: Parameters<typeof ImpactBody>[0]) {
  const t = useT();
  const { state } = props;
  return (
    <section className="dg-side-inner" aria-label={t('dag.preview.title')}>
      <header className="dg-side-head">
        <div className="col grow" style={{ gap: 2 }}>
          <span className="label">{t(`dag.preview.source.${state.source}`)}</span>
          <h2 className="h3">{state.title}</h2>
        </div>
        <IconButton icon="close" label={t('dag.preview.discard')} onClick={props.onDiscard} />
      </header>
      <div className="dg-side-scroll">
        <ImpactBody {...props} />
      </div>
    </section>
  );
}
