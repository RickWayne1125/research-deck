// The outline page, a research project's home. The outline is the paper's logic: each section a chain of numbered
// items, the phases are groups of sections, and the work (literature, code, figures, experiments) is tasks hung on
// items. Views: the outline (by phase or in paper order, with the inspector), the tasks by state, the research tree of
// every fork; any item can be opened as the root (focus). Above them: the tasks by state and what waits for the
// researcher (Today's list, with the outline's own items first). A project without an outline writes one here.
// Routes: #/<p>/outline[/@tasks | /@tree | /@focus/<item> | /@item/<item> (select it)].
import { useEffect, useState } from 'react';
import { Button, Segmented, Spinner } from '../../components/ui';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useT } from '../../i18n';
import { TodayList } from '../overview';
import '../overview/i18n';
import { FolderCard, SurveyCard, dismiss, isDismissed } from '../../start/Survey';
import { OutlineProvider, useOl } from './ctx';
import { allItems, outlinePending, outlineText } from './model';
import { Story } from './Story';
import { Inspector } from './Inspector';
import { PhasesCard, TasksCard } from './Side';
import { Board } from './Board';
import { Tree } from './Tree';
import { Focus } from './Focus';
import { Compose } from './Compose';
import { OutlineDialogs } from './Dialogs';
import { OwnPending, StatusStrip } from './Pending';
import '../overview/overview.css';
import './outline.css';
import './i18n';

type View = 'story' | 'tasks' | 'tree' | 'focus';

function useLocal<T extends string>(key: string, fallback: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => { try { return (localStorage.getItem(key) as T) || fallback; } catch { return fallback; } });
  return [v, (x: T) => { setV(x); try { localStorage.setItem(key, x); } catch { /* storage unavailable */ } }];
}

export default function OutlinePanel() {
  const t = useT();
  const { project } = useApp();
  const today = useToday();
  if (!project) return null;
  if (!today.outline) return <div className="panel"><div className="empty"><Spinner /><span>{t('ol.loading')}</span></div></div>;
  return <OutlineProvider o={today.outline}><OutlinePage /></OutlineProvider>;
}

function OutlinePage() {
  const t = useT();
  const { sub, navigate, askAgent, projectId } = useApp();
  const today = useToday();
  const { o, lang, sel, select, showAbandoned, setShowAbandoned, error, setError, note } = useOl();
  const view: View = sub === '@tasks' ? 'tasks' : sub === '@tree' ? 'tree' : sub?.startsWith('@focus/') ? 'focus' : 'story';
  const focusId = view === 'focus' ? sub!.slice('@focus/'.length) : null;
  const [order, setOrder] = useLocal<'phase' | 'paper'>('rd.outline.order', 'phase');
  const [pend, setPend] = useLocal<'open' | 'closed'>('rd.outline.pending', 'closed');
  const [, setDismissed] = useState(0);

  // #/<p>/outline/@item/<id>: select the item and show it, then drop the sub-route.
  useEffect(() => {
    if (!sub?.startsWith('@item/')) return;
    const id = sub.slice('@item/'.length);
    navigate('outline', null, undefined, { replace: true });
    select(id, { reveal: true });
  }, [sub, navigate, select]);

  const abandoned = [...allItems(o)].filter(i => i.state === 'abandoned').length;
  const survey = today.survey;
  const surveyCard = !!survey && (survey.status === 'running' || (survey.status !== 'done' && !isDismissed(projectId!, survey.id)));
  const evaluate = () => askAgent(t('ol.eval.prompt', { outline: outlineText(o, lang) }), {});

  return (
    <div className="panel">
      <div className="panel-body">
        <div className="ol-body">
          <div className="ol-head">
            <div className="row" style={{ gap: 12 }}>
              <h1>{t('nav.outline')}</h1>
              {o.has_outline
                ? <Segmented<Exclude<View, 'focus'>> value={view === 'focus' ? 'story' : view} ariaLabel={t('ol.views')}
                    onChange={v => navigate('outline', v === 'story' ? null : `@${v}`)}
                    options={[{ value: 'story', label: t('ol.view.story') }, { value: 'tasks', label: t('ol.view.tasks') }, { value: 'tree', label: t('ol.view.tree') }]} />
                : <span className="chip ol-chip off">{t('ol.c.none')}</span>}
            </div>
            {o.has_outline ? (
              <div className="ol-tools">
                {(view === 'story' || view === 'focus') && <>
                  <label className="ol-check"><input type="checkbox" checked={showAbandoned} onChange={e => setShowAbandoned(e.target.checked)} />{t('ol.showAbandoned', { n: abandoned })}</label>
                  {view === 'story' && <Segmented<'phase' | 'paper'> value={order} onChange={setOrder} ariaLabel={t('ol.order')}
                    options={[{ value: 'phase', label: t('ol.order.phase') }, { value: 'paper', label: t('ol.order.paper') }]} />}
                </>}
                <Button variant="soft" icon="robot" onClick={evaluate}>{t('ol.evaluate')}</Button>
                {o.file?.path && <button type="button" className="ol-link" title={t('ol.fileTitle', { path: o.file.path })}
                  onClick={() => navigate('writing', o.file!.path)}>{t('ol.file')}</button>}
                <button type="button" className="ol-link" title={t('ol.mapTitle')} onClick={() => navigate('dag')}>{t('ol.map')}</button>
              </div>
            ) : <span className="ol-hint" style={{ maxWidth: 640 }}>{t('ol.c.lead')}</span>}
          </div>

          <StatusStrip open={pend === 'open'} onToggle={() => setPend(pend === 'open' ? 'closed' : 'open')} />
          {pend === 'open' && (
            <div className="ol-pend">
              <TodayList extra={reg => <OwnPending register={reg} />} extraCount={outlinePending(o).length} recent />
            </div>
          )}
          {surveyCard && survey && <SurveyCard pid={projectId!} survey={survey} onDismiss={() => { dismiss(projectId!, survey.id); setDismissed(n => n + 1); }} />}
          {error && (
            <div className="notice accent" role="alert">
              <span className="grow">{t('ol.err', { msg: error })}</span>
              <button type="button" className="ol-link" onClick={() => setError(null)}>{t('common.close')}</button>
            </div>
          )}
          {note === 'proposed' && <div className="notice" role="status">{t('ol.proposed')}</div>}

          {!o.has_outline ? (
            <>
              <Compose template={o.template} />
              {survey?.status === 'done' && <FolderCard survey={survey} />}
            </>
          ) : view === 'tasks' ? <Board /> : view === 'tree' ? <Tree /> : (
            <div className="ol-main">
              {view === 'focus' && focusId ? <Focus id={focusId} /> : <Story order={order} />}
              {/* the right column: the inspector on top while something is selected, the phases and the tasks, and
                  (nothing selected) the outliner's keys */}
              <div className="ol-side">
                {sel && <Inspector />}
                <PhasesCard />
                <TasksCard />
                {!sel && <Inspector />}
              </div>
            </div>
          )}
          <OutlineDialogs />
        </div>
      </div>
    </div>
  );
}
