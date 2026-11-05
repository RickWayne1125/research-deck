// The bar above Experiments, Code and Paper while an outline task is being worked on: what the task is, the items it
// serves (back to the outline), and marking it in progress or done.
import { useState } from 'react';
import { Button, IconButton } from '../../components/ui';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useT } from '../../i18n';
import { outlineApi } from './api';
import { allItems } from './model';
import './outline.css';
import './i18n';

export default function TaskBar() {
  const t = useT();
  const { projectId, navigate } = useApp();
  const today = useToday();
  const [busy, setBusy] = useState(false);
  const task = today.outline?.tasks.find(x => x.id === today.activeTask);
  if (!task || !projectId) return null;
  const items = [...allItems(today.outline)].filter(i => task.items.includes(i.id));
  const derived = task.type === 'exp' && !!task.links?.node;        // its state follows the node's runs
  const set = async (status: 'doing' | 'done') => {
    setBusy(true);
    try { await outlineApi.updateTask(projectId, task.id, { status }); await today.reloadOutline(); } finally { setBusy(false); }
  };
  const status = task.status === 'locked' ? t('ol.task.locked', { mark: '' }) : t(`ol.task.${task.status}`);
  return (
    <div className="ol-bar" role="region" aria-label={t('ol.bar.label')}>
      <span className="ol-hint">{t('ol.bar.label')}</span>
      <span className={`ol-tk ${task.type} ${task.status}`} style={{ cursor: 'default' }}><b>{t(`ol.type.${task.type}`)}</b>{task.title}<i>· {status}</i></span>
      {items.length > 0 && <span className="ol-hint">{t('ol.task.serves')}</span>}
      {items.map(i => <button key={i.id} type="button" className="chip mono" title={i.text} onClick={() => navigate('outline', `@item/${i.id}`)}>{i.num}</button>)}
      <span className="grow" />
      {!derived && task.status === 'todo' && <Button size="sm" disabled={busy} onClick={() => set('doing')}>{t('ol.bar.doing')}</Button>}
      {!derived && (task.status === 'todo' || task.status === 'doing' || task.status === 'blocked') &&
        <Button size="sm" variant="primary" disabled={busy} onClick={() => set('done')}>{t('ol.bar.done')}</Button>}
      <Button size="sm" variant="ghost" onClick={() => navigate('outline', items[0] ? `@item/${items[0].id}` : null)}>{t('ol.bar.back')}</Button>
      <IconButton icon="close" label={t('ol.bar.close')} onClick={() => today.setActiveTask(null)} />
    </div>
  );
}
