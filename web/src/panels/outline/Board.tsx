// The task view: every task of the outline by state (not started, in progress, blocked, done), filtered by type and
// phase. A card names the items it serves (click one to go back to the outline) and opens where the work happens.
import { useState } from 'react';
import { Button, Segmented } from '../../components/ui';
import { useApp } from '../../state/app';
import { useT } from '../../i18n';
import { TASK_TYPES, outlineApi, type Phase, type Task, type TaskType } from './api';
import { errMsg, useOl } from './ctx';
import { COLUMNS, boardColumns, phaseMark, typeCounts } from './model';
import { useTaskStatus } from './parts';
import { useWork } from './work';

export function Board() {
  const t = useT();
  const { o } = useOl();
  const [type, setType] = useState<TaskType | 'all'>('all');
  const [phase, setPhase] = useState<Phase | 'all'>('all');
  const n = typeCounts(o.tasks);
  const cols = boardColumns(o.tasks, type, phase);
  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="row wrap" style={{ gap: 10 }}>
        <Segmented<TaskType | 'all'> value={type} onChange={setType} ariaLabel={t('ol.board.type')}
          options={[{ value: 'all', label: t('ol.board.all', { n: n.all }) }, ...TASK_TYPES.map(k => ({ value: k, label: `${t(`ol.type.${k}`)} ${n[k]}` }))]} />
        <Segmented<Phase | 'all'> value={phase} onChange={setPhase} ariaLabel={t('ol.board.phase')}
          options={[{ value: 'all', label: t('ol.board.allPhases') }, { value: o.project_phase, label: t('ol.board.only', { mark: phaseMark(o.project_phase) }) }]} />
      </div>
      <span className="ol-hint">{t('ol.board.hint')}</span>
      <div className="ol-kgrid">
        {COLUMNS.map(c => (
          <section key={c} className={`ol-kcol ${c}`} aria-label={t(`ol.task.${c}`)}>
            <h2>{t(`ol.task.${c}`)} <span className="muted" style={{ fontWeight: 400 }}>{cols[c].length}</span></h2>
            <div className="ol-kstack">
              {cols[c].length ? cols[c].map(x => <TaskCard key={x.id} task={x} />) : <span className="ol-hint">{t('ol.board.empty')}</span>}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function TaskCard({ task }: { task: Task }) {
  const t = useT();
  const { navigate } = useApp();
  const { pid, items, openDialog, reload } = useOl();
  const { go } = useWork();
  const status = useTaskStatus();
  const [error, setError] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => { setError(null); try { await fn(); await reload(); } catch (e) { setError(errMsg(e)); } };
  const served = task.items.map(id => items.get(id)).filter((x): x is NonNullable<typeof x> => !!x);
  const who = task.assignee === 'me' ? t('ol.task.byMe') : task.assignee === 'agent' ? t('ol.task.byAgent') : '';
  const why = task.status === 'done' ? task.note : status(task);
  return (
    <div className={`ol-kc ${task.status}`}>
      <div className="row" style={{ gap: 6 }}>
        <span className={`ol-kc-type ${task.type}`}>{t(`ol.type.${task.type}`)}</span>
        {task.phase && <span className="ol-hint">{phaseMark(task.phase)}</span>}
        <span className="grow" />
        {who && <span className="ol-hint">{who}</span>}
      </div>
      <button type="button" className="ol-kc-title ol-link" style={{ color: 'var(--ink-strong)', textAlign: 'left', fontSize: 'var(--fs-md)' }}
        onClick={() => openDialog({ kind: 'task', task: task.id })}>{task.title}</button>
      {served.length > 0 && (
        <div className="row wrap" style={{ gap: 4 }}>
          <span className="ol-hint">{t('ol.task.serves')}</span>
          {served.map(it => <button key={it.id} type="button" className="chip mono" title={it.text} onClick={() => navigate('outline', `@item/${it.id}`)}>{it.num}</button>)}
        </div>
      )}
      {why && why !== t(`ol.task.${task.status}`) && <span className="ol-hint">{why}</span>}
      {error && <span className="ol-why">{error}</span>}
      {task.status === 'sugg' ? (
        <div className="row" style={{ justifyContent: 'flex-end', gap: 6 }}>
          <Button size="sm" onClick={() => act(() => outlineApi.deleteTask(pid, task.id))}>{t('ol.pend.drop')}</Button>
          <Button size="sm" variant="primary" onClick={() => act(() => outlineApi.updateTask(pid, task.id, { status: 'todo' }))}>{t('ol.pend.take')}</Button>
        </div>
      ) : (task.status === 'todo' || task.status === 'doing' || task.status === 'blocked') && (
        <div className="row" style={{ justifyContent: 'flex-end' }}><Button size="sm" onClick={() => go(task)}>{t(`ol.go.${task.type}`)}</Button></div>
      )}
    </div>
  );
}
