// The strip at the top of the outline page: the tasks by state, and what waits for the researcher (forks to choose,
// items the agent added, blocked and suggested tasks, and everything Today used to list), opened in place.
import type { ReactNode } from 'react';
import { Button } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useToday } from '../../state/today';
import { useT } from '../../i18n';
import { dagApi } from '../../dag/api';
import { Item as Row, useTodayCounts, type Register } from '../overview';
import { outlineApi, type Pending } from './api';
import { errMsg, useOl } from './ctx';
import { outlinePending } from './model';

export function StatusStrip({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const t = useT();
  const today = useToday();
  const { o } = useOl();
  const own = outlinePending(o);
  const { surveyDone } = useTodayCounts();
  const nd = today.needs;
  // what waits, in words: the outline's own items first, then Today's
  const all = [
    ...own.map(p => describe(t, p)),
    ...(nd.proposals.length ? [t('ol.pend.proposals', { n: nd.proposals.length })] : []),
    ...(nd.review.length ? [t('ol.pend.review', { n: nd.review.length })] : []),
    ...(surveyDone ? [t('ol.pend.survey')] : []),
    ...(nd.decisions.length ? [t('ol.pend.decisions', { n: nd.decisions.length })] : []),
    ...(nd.fix.length ? [t('td.fix.title', { n: nd.fix.length })] : []),
    ...(nd.rerun.ids.length ? [t('td.rerun.title', { n: nd.rerun.ids.length })] : []),
    ...(nd.failed.length ? [t('td.failed.title', { n: nd.failed.length })] : []),
  ];
  const n = Math.max(today.count, all.length);
  const words = all.slice(0, 2);
  const rest = all.length - words.length;
  // the tasks by state are in the tasks card (Side.tsx); the strip is what waits for the researcher
  return (
    <div className="ol-strip">
      <button type="button" className="ol-pend-btn" aria-expanded={open} onClick={onToggle}>
        <span className={`badge lg${n ? ' warn' : ''}`}>{n ? t('ol.pendingN', { n }) : t('ol.pendingNone')}</span>
        {n > 0 && <span>{[...words, ...(rest > 0 ? [t('ol.pend.more', { n: rest })] : [])].join(' · ')}</span>}
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={12} />
      </button>
    </div>
  );
}

function describe(t: ReturnType<typeof useT>, p: Exclude<Pending, { kind: 'proposal' }>): string {
  switch (p.kind) {
    case 'fork': return t('ol.pend.fork', { num: p.num });
    case 'proposed_item': return t('ol.pend.item', { num: p.num });
    case 'blocked_task': return t('ol.pend.blocked', { title: p.title });
    case 'suggested_task': return t('ol.pend.sugg', { title: p.title });
  }
}

/** The outline's own items in the list of what waits (the rest is Today's). */
export function OwnPending({ register }: { register: Register }) {
  const { o } = useOl();
  return <>{outlinePending(o).map(p => <PendingRow key={`${p.kind}:${'item' in p ? p.item : p.task}`} p={p} register={register} />)}</>;
}

function PendingRow({ p, register }: { p: Exclude<Pending, { kind: 'proposal' }>; register: Register }) {
  const t = useT();
  const { pid, select, run, openDialog, reload, setError } = useOl();
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); await reload(); } catch (e) { setError(errMsg(e)); } };
  let tag = '', tone: 'prop' | 'warn' | 'accent' | undefined, body: ReactNode = null, actions: ReactNode = null;
  let keys: { yes?: () => void; no?: () => void } = {};
  if (p.kind === 'fork') {
    const go = () => select(p.item, { reveal: true });
    tag = t('ol.tag.fork'); body = <p className="td-p td-clamp">{p.text} · {t('ol.pend.forkBody')}</p>;
    actions = <Button size="sm" variant="primary" onClick={go}>{t('ol.pend.choose')}</Button>;
    keys = { yes: go };
  } else if (p.kind === 'proposed_item') {
    const accept = () => act(() => dagApi.ops(pid, [{ op: 'set_status', node: p.item, to: 'active' }]));
    const reject = () => run([{ op: 'remove_item', item: p.item }]);
    tag = t('ol.tag.item'); tone = 'prop';
    body = <p className="td-p td-clamp"><button type="button" className="td-link" onClick={() => select(p.item, { reveal: true })}>{p.num}</button> {p.text}</p>;
    actions = <><Button size="sm" variant="primary" onClick={accept}>{t('ol.pend.accept')}</Button><Button size="sm" onClick={reject}>{t('ol.pend.reject')}</Button></>;
    keys = { yes: accept, no: reject };
  } else if (p.kind === 'blocked_task') {
    const open = () => openDialog({ kind: 'task', task: p.task });
    const why = p.reason ? t(p.reason.startsWith('survey_') ? 'ol.why.survey' : `ol.why.${p.reason}`) : p.note;
    tag = t('ol.tag.blocked'); tone = 'accent';
    body = <p className="td-p td-clamp">{why ? `${why} · ` : ''}{t('ol.pend.blockedBody', { nums: p.nums.join(t('ol.secSep')) })}</p>;
    actions = <Button size="sm" variant="primary" onClick={open}>{t('ol.pend.open')}</Button>;
    keys = { yes: open };
  } else {
    const take = () => act(() => outlineApi.updateTask(pid, p.task, { status: 'todo' }));
    const drop = () => act(() => outlineApi.deleteTask(pid, p.task));
    tag = t('ol.tag.sugg'); tone = 'prop';
    body = <p className="td-p td-clamp">{t('ol.pend.blockedBody', { nums: p.nums.join(t('ol.secSep')) })}</p>;
    actions = <><Button size="sm" variant="primary" onClick={take}>{t('ol.pend.take')}</Button><Button size="sm" onClick={drop}>{t('ol.pend.drop')}</Button></>;
    keys = { yes: take, no: drop };
  }
  const id = `o:${p.kind}:${'item' in p ? p.item : p.task}`;
  return <Row id={id} tag={tag} tone={tone} title={describe(t, p)} register={register} keys={keys} actions={actions}>{body}</Row>;
}
