// The outline page's dialogs: fork an item into directions, abandon a direction, remove an item, assign or edit a
// task, link a map node to an item, and leave the current phase (the gates and the outline's own check).
import { useMemo, useState } from 'react';
import { Button, Dialog, Segmented, Spinner } from '../../components/ui';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { STEPS, type StepId } from '../../state/stages';
import { useI18n, useT } from '../../i18n';
import { NextStepDialog } from '../overview/NextStep';
import '../overview/i18n';
import { TASK_TYPES, outlineApi, type Item, type Phase, type Task, type TaskStatus, type TaskType } from './api';
import { errMsg, useOl, type DialogSpec } from './ctx';
import { bi, outlineItemIds } from './model';
import { useTaskStatus } from './parts';
import { PHASE_EXPERIMENT, useWork } from './work';

const REASONS = ['infeasible', 'dominated', 'no_headroom', 'competitor_closed_gap', 'out_of_scope', 'cost', 'time', 'other'] as const;

export function OutlineDialogs() {
  const { dialog, openDialog } = useOl();
  if (!dialog) return null;
  const close = () => openDialog(null);
  switch (dialog.kind) {
    case 'fork': return <ForkDialog item={dialog.item} onClose={close} />;
    case 'abandon': return <AbandonDialog item={dialog.item} direction={dialog.direction} onClose={close} />;
    case 'remove': return <RemoveDialog item={dialog.item} onClose={close} />;
    case 'task': return <TaskDialog spec={dialog} onClose={close} />;
    case 'link': return <LinkDialog item={dialog.item} onClose={close} />;
    case 'leave': return <LeaveDialog phase={dialog.phase} onClose={close} />;
  }
}

function Err({ msg }: { msg: string | null }) {
  return msg ? <div className="notice accent" role="alert">{msg}</div> : null;
}

function useItem(id: string): Item | undefined {
  return useOl().items.get(id);
}

function ForkDialog({ item, onClose }: { item: string; onClose: () => void }) {
  const t = useT();
  const { run, error } = useOl();
  const it = useItem(item);
  const [question, setQuestion] = useState('');
  const [dirs, setDirs] = useState(() => (it ? `${it.text}\n` : ''));
  const [busy, setBusy] = useState(false);
  const lines = dirs.split('\n').map(x => x.trim()).filter(Boolean);
  const go = async () => {
    setBusy(true);
    const ok = await run([{ op: 'fork', item, ...(question.trim() ? { question: question.trim() } : {}), directions: lines }]);
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <Dialog title={t('ol.fork.dlgTitle', { num: it?.num ?? item })} onClose={onClose} width={560} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="primary" disabled={busy || lines.length < 2} onClick={go}>{busy && <Spinner />}{t('ol.fork.go')}</Button></>
    }>
      <div className="col" style={{ gap: 12 }}>
        <label className="field"><span className="label">{t('ol.fork.question')}</span>
          <input className="input" value={question} onChange={e => setQuestion(e.target.value)} placeholder={t('ol.fork.questionPh')} autoFocus />
        </label>
        <label className="field"><span className="label">{t('ol.fork.dirs')}</span>
          <textarea className="textarea" rows={5} value={dirs} onChange={e => setDirs(e.target.value)} />
        </label>
        <span className="ol-hint">{t('ol.fork.keep')}</span>
        <Err msg={error} />
      </div>
    </Dialog>
  );
}

function AbandonDialog({ item, direction, onClose }: { item: string; direction: string; onClose: () => void }) {
  const t = useT();
  const { run, error } = useOl();
  const d = useItem(direction);
  const [reason, setReason] = useState<(typeof REASONS)[number]>('dominated');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const ok = await run([{ op: 'abandon_direction', item, direction, reason, ...(note.trim() ? { note: note.trim() } : {}) }]);
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <Dialog title={t('ol.ab.title', { n: d?.direction ?? '?' })} onClose={onClose} width={520} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="danger" disabled={busy} onClick={go}>{busy && <Spinner />}{t('ol.ab.go')}</Button></>
    }>
      <div className="col" style={{ gap: 12 }}>
        {d && <p style={{ margin: 0 }}>{d.text}</p>}
        <label className="field"><span className="label">{t('ol.ab.reason')}</span>
          <select className="select" value={reason} onChange={e => setReason(e.target.value as (typeof REASONS)[number])}>
            {REASONS.map(r => <option key={r} value={r}>{t(`ol.reason.${r}`)}</option>)}
          </select>
        </label>
        <label className="field"><span className="label">{t('ol.ab.note')}</span>
          <textarea className="textarea" rows={3} value={note} onChange={e => setNote(e.target.value)} placeholder={t('ol.ab.notePh')} />
        </label>
        <Err msg={error} />
      </div>
    </Dialog>
  );
}

function RemoveDialog({ item, onClose }: { item: string; onClose: () => void }) {
  const t = useT();
  const { run, error, select } = useOl();
  const it = useItem(item);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const ok = await run([{ op: 'remove_item', item }]);
    setBusy(false);
    if (ok) { select(null); onClose(); }
  };
  return (
    <Dialog title={t('ol.rm.title', { num: it?.num ?? item })} onClose={onClose} width={500} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="danger" disabled={busy} onClick={go}>{busy && <Spinner />}{t('ol.rm.go')}</Button></>
    }>
      <div className="col" style={{ gap: 10 }}>
        {it && <p style={{ margin: 0 }}>{it.text}</p>}
        <p className="muted" style={{ margin: 0 }}>{t('ol.rm.body')}</p>
        <Err msg={error} />
      </div>
    </Dialog>
  );
}

/** Nodes of the map that can back an item: everything but the outline's own sections and items. */
function useMapNodes(): { id: string; label: string; kind: string }[] {
  const { graph } = useToday();
  const { o, lang } = useOl();
  return useMemo(() => {
    const own = outlineItemIds(o);
    return (graph?.nodes ?? []).filter(n => !own.has(n.id) && n.status !== 'abandoned')
      .map(n => ({ id: n.id, kind: n.kind, label: bi(n.title, lang) || n.id }));
  }, [graph, o, lang]);
}

function TaskDialog({ spec, onClose }: { spec: Extract<DialogSpec, { kind: 'task' }>; onClose: () => void }) {
  const t = useT();
  const { pid, tasks, items, reload } = useOl();
  const nodes = useMapNodes();
  const { go, makeExperiment, startSurvey } = useWork();
  const statusText = useTaskStatus();
  const task = spec.task ? tasks.get(spec.task) : undefined;
  const it = spec.item ? items.get(spec.item) : undefined;
  const [type, setType] = useState<TaskType>(task?.type ?? 'exp');
  const [title, setTitle] = useState(task?.title ?? '');
  const [who, setWho] = useState<Task['assignee']>(task?.assignee ?? '');
  const [node, setNode] = useState(task?.links?.node ?? '');
  const [status, setStatus] = useState<TaskStatus>(task?.set_status ?? 'todo');
  const [note, setNote] = useState(task?.note ?? '');
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); await reload(); onClose(); } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  };
  const others = it ? [...tasks.values()].filter(x => !x.items.includes(it.id) && !x.abandoned) : [];
  const links = { ...(task?.links ?? {}), node: node.trim() || undefined };

  if (task) {
    const served = task.items.map(id => items.get(id)).filter((x): x is Item => !!x);
    return (
      <Dialog title={task.title} onClose={onClose} width={580} footer={
        <>
          <Button variant="danger" disabled={busy} onClick={() => act(() => outlineApi.deleteTask(pid, task.id))}>{t('ol.task.delete')}</Button>
          <span className="grow" />
          {task.status === 'sugg' ? (
            <Button variant="primary" disabled={busy} onClick={() => act(() => outlineApi.updateTask(pid, task.id, { status: 'todo' }))}>{t('ol.pend.take')}</Button>
          ) : (
            <>
              {task.status !== 'locked' && <Button onClick={() => { onClose(); go(task); }}>{t(`ol.go.${task.type}`)}</Button>}
              <Button variant="primary" disabled={busy || !title.trim()} onClick={() => act(() => outlineApi.updateTask(pid, task.id, { type, title: title.trim(), assignee: who, status, note, links }))}>
                {busy && <Spinner />}{t('common.save')}
              </Button>
            </>
          )}
        </>
      }>
        <div className="col" style={{ gap: 12 }}>
          <div className="row wrap" style={{ gap: 6 }}>
            <span className={`ol-tk ${task.type} ${task.status}`}><b>{t(`ol.type.${task.type}`)}</b><i>{statusText(task)}</i></span>
            <span className="ol-hint">{t('ol.task.serves')}</span>
            {served.map(x => (
              <span key={x.id} className="chip">{x.num}
                <button type="button" className="ol-link" title={t('ol.tf.unassign')} aria-label={t('ol.tf.unassign')}
                  onClick={() => act(() => outlineApi.updateTask(pid, task.id, { items: task.items.filter(i => i !== x.id) }))}>×</button>
              </span>
            ))}
          </div>
          <TaskFields {...{ type, setType, title, setTitle, who, setWho, node, setNode, nodes }} />
          {task.status !== 'sugg' && task.status !== 'locked' && task.type === 'exp' && !task.links?.node && (
            <div className="row wrap" style={{ gap: 8 }}>
              <Button size="sm" icon="plus" disabled={busy} onClick={() => act(() => makeExperiment(task))}>
                {t('ol.work.makeExp', { stage: PHASE_EXPERIMENT[task.phase ?? 'evaluation'].stage })}
              </Button>
            </div>
          )}
          {task.status !== 'sugg' && task.status !== 'locked' && task.type === 'lit' && !task.links?.survey && (
            <div className="row wrap" style={{ gap: 8 }}>
              <Button size="sm" icon="search" disabled={busy} onClick={() => act(() => startSurvey(task))}>{t('ol.work.survey')}</Button>
              <span className="ol-hint grow">{t('ol.work.surveyHint')}</span>
            </div>
          )}
          {task.status !== 'sugg' && (
            <div className="row wrap" style={{ gap: 12 }}>
              <label className="field"><span className="label">{t('ol.task.set')}</span>
                <select className="select" value={status} onChange={e => setStatus(e.target.value as TaskStatus)}>
                  {(['todo', 'doing', 'blocked', 'done'] as const).map(s => <option key={s} value={s}>{t(`ol.task.${s}`)}</option>)}
                </select>
              </label>
              <label className="field grow"><span className="label">{t('ol.task.note')}</span>
                <input className="input" value={note} onChange={e => setNote(e.target.value)} />
              </label>
            </div>
          )}
          <Err msg={error} />
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog title={t('ol.tf.title', { num: it?.num ?? '' })} onClose={onClose} width={580} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="primary" disabled={busy || !title.trim() || !it} onClick={() => act(() => outlineApi.createTask(pid, { type, title: title.trim(), items: [it!.id], assignee: who, links }))}>
          {busy && <Spinner />}{t('ol.tf.create')}
        </Button></>
    }>
      <div className="col" style={{ gap: 12 }}>
        {it && <p style={{ margin: 0 }} className="muted">{it.num} · {it.text}</p>}
        <TaskFields {...{ type, setType, title, setTitle, who, setWho, node, setNode, nodes }} />
        {others.length > 0 && (
          <div className="field">
            <span className="label">{t('ol.tf.existing')}</span>
            <div className="row" style={{ gap: 8 }}>
              <select className="select grow" value={pick} onChange={e => setPick(e.target.value)}>
                <option value="">{t('ol.tf.pick')}</option>
                {others.map(x => <option key={x.id} value={x.id}>{t(`ol.type.${x.type}`)} · {x.title}{x.nums.length ? ` (${x.nums.join(', ')})` : ''}</option>)}
              </select>
              <Button disabled={!pick || busy} onClick={() => { const x = tasks.get(pick)!; act(() => outlineApi.updateTask(pid, x.id, { items: [...x.items, it!.id] })); }}>{t('ol.tf.attach')}</Button>
            </div>
          </div>
        )}
        <Err msg={error} />
      </div>
    </Dialog>
  );
}

function TaskFields({ type, setType, title, setTitle, who, setWho, node, setNode, nodes }: {
  type: TaskType; setType: (v: TaskType) => void; title: string; setTitle: (v: string) => void;
  who: Task['assignee']; setWho: (v: Task['assignee']) => void; node: string; setNode: (v: string) => void;
  nodes: { id: string; label: string; kind: string }[];
}) {
  const t = useT();
  return (
    <>
      <div className="row wrap" style={{ gap: 12 }}>
        <div className="field"><span className="label">{t('ol.tf.type')}</span>
          <Segmented<TaskType> value={type} onChange={setType} options={TASK_TYPES.map(k => ({ value: k, label: t(`ol.type.${k}`) }))} ariaLabel={t('ol.tf.type')} />
        </div>
        <div className="field"><span className="label">{t('ol.tf.who')}</span>
          <Segmented<Task['assignee']> value={who} onChange={setWho} options={(['', 'me', 'agent'] as const).map(k => ({ value: k, label: t(`ol.who.${k}`) }))} ariaLabel={t('ol.tf.who')} />
        </div>
      </div>
      <label className="field"><span className="label">{t('ol.tf.name')}</span>
        <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder={t('ol.tf.namePh')} autoFocus />
      </label>
      <label className="field"><span className="label">{t('ol.tf.link')}</span>
        <input className="input mono" list="ol-map-nodes" value={node} onChange={e => setNode(e.target.value)} placeholder={t('ol.tf.linkPh')} spellCheck={false} />
        <datalist id="ol-map-nodes">{nodes.map(n => <option key={n.id} value={n.id}>{n.label}</option>)}</datalist>
      </label>
    </>
  );
}

function LinkDialog({ item, onClose }: { item: string; onClose: () => void }) {
  const t = useT();
  const { run, error } = useOl();
  const it = useItem(item);
  const nodes = useMapNodes();
  const [kind, setKind] = useState<'basis' | 'evidence' | 'cites'>('basis');
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const have = new Set((it?.evidence ?? []).map(e => e.id));
  const hits = nodes.filter(n => !have.has(n.id) && (!q.trim() || `${n.id} ${n.label}`.toLowerCase().includes(q.trim().toLowerCase()))).slice(0, 12);
  const link = async (id: string) => {
    setBusy(true);
    const ok = await run([{ op: 'link', item, to: id, type: kind }]);
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <Dialog title={t('ol.link.title', { num: it?.num ?? item })} onClose={onClose} width={560}>
      <div className="col" style={{ gap: 10 }}>
        <div className="row wrap" style={{ gap: 10 }}>
          <span className="label">{t('ol.link.kind')}</span>
          <Segmented<'basis' | 'evidence' | 'cites'> value={kind} onChange={setKind} ariaLabel={t('ol.link.kind')}
            options={(['basis', 'evidence', 'cites'] as const).map(k => ({ value: k, label: t(`ol.link.${k}`) }))} />
        </div>
        <input className="input" value={q} onChange={e => setQ(e.target.value)} placeholder={t('ol.link.nodePh')} autoFocus />
        <div className="list card">
          {hits.map(n => (
            <button key={n.id} type="button" className="list-item" disabled={busy} onClick={() => link(n.id)} style={{ border: 0, background: 'none', textAlign: 'left', width: '100%' }}>
              <span className="mono ol-faint" style={{ fontSize: 'var(--fs-xs)' }}>{n.id}</span>
              <span className="grow ellipsis">{n.label}</span>
            </button>
          ))}
        </div>
        <Err msg={error} />
      </div>
    </Dialog>
  );
}

/** Leaving the current phase: the outline's check (every item of its sections holds) above the gates. */
function LeaveDialog({ phase, onClose }: { phase: string; onClose: () => void }) {
  const t = useT();
  const { lang } = useI18n();
  const { projectId } = useApp();
  const { o, select } = useOl();
  const g = o.groups.find(x => x.phase === phase);
  const step = (STEPS.includes(phase as StepId) ? phase : 'idea') as StepId;
  const secs = (g?.sections ?? []).map(id => o.sections.find(s => s.id === id)).filter(Boolean).map(s => `§${s!.num} ${bi(s!.title, lang)}`).join(t('ol.secSep'));
  const tops = topItems(o);
  const extra = g && (
    <div className="td-gate">
      <div className="row" style={{ gap: 8 }}>
        <b>{bi(o.phases[phase as Phase], lang)} · {secs}</b>
        <span className="faint num">{t('td.next.checks', { ok: g.holds, n: g.items })}</span>
      </div>
      {g.missing.length > 0 && (
        <div className="td-check-items" style={{ marginTop: 6 }}>
          {g.missing.map(num => {
            const it = tops.find(x => x.num === num);
            return <button key={num} type="button" className="chip mono" onClick={() => { onClose(); if (it) select(it.id, { reveal: true }); }}>{num}</button>;
          })}
        </div>
      )}
    </div>
  );
  return <NextStepDialog pid={projectId!} step={step} onClose={onClose} extra={extra} extraMissing={g?.missing.length ?? 0} passNote={t('ol.leave.note')} />;
}

function topItems(o: ReturnType<typeof useOl>['o']): Item[] {
  const out: Item[] = [];
  for (const s of o.sections) for (const st of s.items) for (const it of st.items) out.push(it);
  return out;
}
