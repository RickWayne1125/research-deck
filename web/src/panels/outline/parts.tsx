// Small pieces of the outline page: an item's state chip, a task chip, an evidence chip, phase names.
import { useCallback } from 'react';
import { useApp } from '../../state/app';
import { useT } from '../../i18n';
import type { Evidence, Item, Phase, SectionPhase, Task } from './api';
import { useOl } from './ctx';
import { STATE_TONE, bi, phaseMark } from './model';

export function usePhaseName(): (p: SectionPhase | null | undefined) => string {
  const { o, lang } = useOl();
  const t = useT();
  return useCallback((p) => (!p ? '' : p === 'summary' ? t('ol.group.summaryName') : bi(o.phases[p as Phase], lang)), [o, lang, t]);
}

/** "③ 系统设计" */
export function usePhaseLabel(): (p: SectionPhase | null | undefined) => string {
  const name = usePhaseName();
  return useCallback((p) => (p === 'summary' ? name(p) : `${phaseMark(p)} ${name(p)}`), [name]);
}

/** The chip on an item's right: its state ("成立", "受阻"…), "推导" for an argued item, and for a summary item the
 *  items it follows ("= 2.1 成立"). */
export function StateChip({ it, chosen = false }: { it: Item; chosen?: boolean }) {
  const t = useT();
  const { items } = useOl();
  if (chosen && it.state !== 'abandoned') {
    return <span className={`chip ol-chip ${it.state === 'holds' ? 'ok' : 'run'}`}>{t('ol.chosen')}{it.state !== 'holds' ? ` · ${t(`ol.state.${it.state}`)}` : ''}</span>;
  }
  if (it.summary_of.length) {
    const targets = it.summary_of.map(id => items.get(id)).filter((x): x is Item => !!x);
    const nums = targets.map(x => x.num).join(t('ol.secSep'));
    if (it.state === 'holds') return <span className="chip ol-chip ok">{t('ol.sumHolds', { nums })}</span>;
    const worst = targets.find(x => x.state !== 'holds');
    return <span className={`chip ol-chip ${worst ? STATE_TONE[worst.state] : 'dash'}`}>{t('ol.sumOf', { nums })}{worst ? ` · ${t(`ol.state.${worst.state}`)}` : ''}</span>;
  }
  if (it.state === 'holds' && it.derived) return <span className="chip ol-chip ok">{t('ol.derived')}</span>;
  if (it.state === 'doing' && it.kids.total > 0 && !it.tasks.length) {
    return <span className="chip ol-chip warn">{t('ol.kids', { h: it.kids.holds, n: it.kids.total })}</span>;
  }
  return <span className={`chip ol-chip ${STATE_TONE[it.state]}`}>{t(`ol.state.${it.state}`)}</span>;
}

/** The status words on a task chip: done, in progress (or why), blocked (and why), not started, waits for ③. */
export function useTaskStatus(): (task: Task) => string {
  const t = useT();
  return useCallback((task: Task) => {
    const why = task.reason ? t(task.reason.startsWith('survey_') ? 'ol.why.survey' : `ol.why.${task.reason}`) : task.note;
    switch (task.status) {
      case 'locked': return t('ol.task.locked', { mark: phaseMark(task.phase) });
      case 'sugg': return t('ol.task.sugg');
      case 'doing': return why || t('ol.task.doing');
      case 'blocked': return why ? `${t('ol.task.blocked')} · ${why}` : t('ol.task.blocked');
      default: return t(`ol.task.${task.status}`);
    }
  }, [t]);
}

export function TaskChip({ task }: { task: Task }) {
  const t = useT();
  const { openDialog } = useOl();
  const status = useTaskStatus();
  return (
    <button type="button" className={`ol-tk ${task.type} ${task.status}`} title={task.title}
      onClick={(e) => { e.stopPropagation(); openDialog({ kind: 'task', task: task.id }); }}>
      <b>{t(`ol.type.${task.type}`)}</b>{task.title}<i>· {status(task)}</i>
    </button>
  );
}

const LEVEL_TONE: Record<string, string> = { fresh: 'ok', stale: 'warn', unbuilt: 'off', review: 'warn', broken: 'bad', orphaned: 'warn', pending: 'off' };

export function EvidenceChip({ e }: { e: Evidence }) {
  const { navigate } = useApp();
  const tone = e.level ? LEVEL_TONE[e.level] ?? '' : e.status === 'confirmed' || e.status === 'locked' ? 'ok' : '';
  return (
    <button type="button" className={`chip ol-chip ol-ev ${tone}`} title={`${e.id} · ${e.rel}${e.level ? ` · ${e.level}` : ''}`}
      onClick={(ev) => { ev.stopPropagation(); navigate('dag', e.id); }}>
      {e.title || e.id}
    </button>
  );
}
