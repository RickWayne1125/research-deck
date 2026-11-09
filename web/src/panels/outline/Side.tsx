// The outline page's right column, as in the Radix preview: the phases with how much of each holds (a progress bar
// each), what leaving the current phase takes, and the tasks by state with the ones in play. The inspector joins them
// on top when an item or a section is selected.
import type { CSSProperties } from 'react';
import { useApp } from '../../state/app';
import { useT } from '../../i18n';
import { Icon } from '../../components/icons';
import type { Group, Task, TaskStatus } from './api';
import { useOl } from './ctx';
import { phaseMark } from './model';
import { usePhaseName, useTaskStatus } from './parts';

/** done / in progress / the current phase / the summary: the bar's color */
function phaseTone(g: Group): string {
  if (g.state === 'current') return 'cur';
  if (g.state === 'summary') return 'sum';
  return g.state === 'done' && !g.missing.length ? 'ok' : 'run';
}

export function PhasesCard() {
  const t = useT();
  const { o, openDialog } = useOl();
  const phaseName = usePhaseName();
  const secs = new Map(o.sections.map(s => [s.id, s]));
  const lastPhase = [...o.groups].reverse().find(g => g.state !== 'summary')?.phase;
  const current = o.groups.find(g => g.state === 'current');
  const gate = current && (() => {
    const names = current.sections.map(id => secs.get(id)).filter(Boolean).map(s => `§${s!.num}`).join(t('ol.secSep'));
    const shown = current.missing.slice(0, 4).join(t('ol.secSep')) + (current.missing.length > 4 ? '…' : '');
    return current.missing.length ? t('ol.group.leaveMissing', { nums: shown })
      : t(current.phase === lastPhase ? 'ol.group.leaveLast' : 'ol.group.leave', { secs: names });
  })();
  return (
    <>
      <section className="ol-card" aria-labelledby="ol-phases-h">
        <h2 id="ol-phases-h">{t('ol.side.phases')}</h2>
        <ol className="ol-phases">
          {o.groups.map(g => {
            const name = g.phase === 'summary' ? `∑ ${t('ol.group.summaryName')}` : `${phaseMark(g.phase)} ${phaseName(g.phase)}`;
            const pct = g.items ? Math.round((100 * g.holds) / g.items) : g.state === 'done' ? 100 : 0;
            return (
              <li key={g.phase} className={`ol-phase ${phaseTone(g)}`}>
                <div className="ol-phase-row">
                  <span className={g.state === 'current' ? 'ol-phase-cur' : undefined}>{name}{g.state === 'current' ? ` · ${t('ol.side.current')}` : ''}</span>
                  <span className="muted num">{g.holds}/{g.items}</span>
                </div>
                <div className="ol-progress" role="progressbar" aria-label={name} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
                  style={{ '--v': `${pct}%` } as CSSProperties}><i /></div>
              </li>
            );
          })}
        </ol>
      </section>
      {current && gate && (
        <button type="button" className="notice soft ol-gatebox" onClick={() => openDialog({ kind: 'leave', phase: current.phase })}>
          <Icon name="info" /><span className="grow">{gate}</span><Icon name="chevronRight" size={14} />
        </button>
      )}
    </>
  );
}

const ORDER: Record<TaskStatus, number> = { doing: 0, blocked: 1, todo: 2, sugg: 3, locked: 4, done: 5 };
const STATUS_TONE: Record<TaskStatus, string> = { done: 'ok', doing: 'process', blocked: 'danger', todo: '', locked: '', sugg: '' };

export function TasksCard() {
  const t = useT();
  const { navigate } = useApp();
  const { o, openDialog } = useOl();
  const status = useTaskStatus();
  const c = o.counts;
  const tiles: [string, number, string][] = [['done', c.done, 'ok'], ['doing', c.doing, 'run'], ['todo', c.todo, ''], ['blocked', c.blocked, 'bad']];
  const list: Task[] = o.tasks.filter(x => !x.abandoned).sort((a, b) => ORDER[a.status] - ORDER[b.status]).slice(0, 6);
  return (
    <section className="ol-card" aria-labelledby="ol-tasks-h">
      <div className="ol-card-head">
        <h2 id="ol-tasks-h">{t('ol.side.tasks')}</h2>
        <button type="button" className="ol-link" onClick={() => navigate('outline', '@tasks')}>{t('ol.side.board')}</button>
      </div>
      <div className="ol-tiles">
        {tiles.map(([k, n, tone]) => (
          <div key={k} className={`ol-tile ${tone}`}><b className="num">{n}</b><span>{t(`ol.task.${k}`)}</span></div>
        ))}
      </div>
      {list.length > 0 ? (
        <ul className="ol-tlist">
          {list.map(x => (
            <li key={x.id}>
              <button type="button" onClick={() => openDialog({ kind: 'task', task: x.id })} title={x.title}>
                <span className={`badge t-${x.type}`}>{t(`ol.type.${x.type}`)}</span>
                <span className="ol-tlist-title">{x.title}</span>
                <span className={`badge surface ${STATUS_TONE[x.status]}`}>{x.nums.length ? `${x.nums.join(' ')} · ` : ''}{status(x)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : <span className="ol-hint">{t('ol.board.empty')}</span>}
    </section>
  );
}
