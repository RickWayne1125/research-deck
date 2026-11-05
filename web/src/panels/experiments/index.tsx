// The Experiments view: Runs (records, "does this need a rerun?", the log in a read-only terminal) | Resources. When the
// map says experiments need to run or rerun, a bar above the runs opens the run plan (#/<project>/experiments/plan).
// The route's sub-path is the tab, "plan", or an experiment id, which opens that run's drawer on the Runs tab:
// #/<project>/experiments/resources, #/<project>/experiments/e7-main.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, PanelHead, useLoad } from '../../components/ui';
import { useToday } from '../../state/today';
import { useT } from '../../i18n';
import { useApp, useLiveReload } from '../../state/app';
import { exApi } from './api';
import { NewExperimentDialog } from './NewExperimentDialog';
import { RerunPlanView } from './RerunPlanView';
import { ResourcesView } from './ResourcesView';
import { RunDrawer } from './RunDrawer';
import { RunsView } from './RunsView';
import './experiments.css';
import './i18n';

const TABS = ['runs', 'resources'] as const;
type Tab = (typeof TABS)[number];
const isTab = (v: string | null | undefined): v is Tab => !!v && (TABS as readonly string[]).includes(v);
const TAB_KEY = 'rd.ex.tab';

export default function ExperimentsPanel() {
  const { projectId, sub, navigate } = useApp();
  const pid = projectId!;
  const t = useT();

  // "plan" is the run plan; any other sub-path that is not a tab is an experiment id, shown on the Runs tab.
  const plan = sub === 'plan';
  const openId = sub && !isTab(sub) && !plan ? sub : null;
  const today = useToday();
  const toRun = today.needs.rerun.ids.length;
  const [tab, setTabState] = useState<Tab>(() => {
    if (isTab(sub)) return sub;
    if (openId) return 'runs';
    try { const v = localStorage.getItem(TAB_KEY); return isTab(v) ? v : 'runs'; } catch { return 'runs'; }
  });
  useEffect(() => { if (isTab(sub)) setTabState(sub); else if (sub && sub !== 'plan') setTabState('runs'); }, [sub]);
  const setTab = useCallback((next: Tab) => {
    setTabState(next);
    try { localStorage.setItem(TAB_KEY, next); } catch { /* storage unavailable */ }
    navigate('experiments', next);
  }, [navigate]);

  const list = useLoad(() => exApi.list(pid), [pid]);
  // Records and their freshness change on 'experiments' and 'dag' events; one reload per burst.
  const reloadRef = useRef(list.reload);
  reloadRef.current = list.reload;
  const timer = useRef(0);
  useLiveReload(['experiments', 'dag'], useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => reloadRef.current(), 300);
  }, []));
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // Running records also change without events (a log being written): poll gently while one is live.
  const anyLive = !!list.data?.some(r => r.status === 'running' || r.status === 'queued');
  useEffect(() => {
    if (!anyLive) return;
    const id = window.setInterval(() => { if (document.visibilityState === 'visible') reloadRef.current(); }, 20_000);
    return () => window.clearInterval(id);
  }, [anyLive]);

  const [creating, setCreating] = useState(false);
  const records = list.data;
  const stale = useMemo(() => (records ?? []).filter(r => r.freshness === 'stale').length, [records]);
  const summary = openId ? records?.find(r => r.id === openId) : undefined;
  const open = useCallback((id: string) => navigate('experiments', id), [navigate]);
  const close = useCallback(() => navigate('experiments', 'runs'), [navigate]);

  return (
    <div className="panel ex-panel">
      <PanelHead title={t('nav.experiments')} subtitle={records ? t('ex.subtitle', { n: records.length, stale }) : t('ex.subtitleNone')}>
        <Button icon="plus" variant="primary" onClick={() => setCreating(true)}>{t('ex.new')}</Button>
      </PanelHead>
      <div className="tabs" role="tablist">
        {TABS.map(k => (
          <button key={k} type="button" role="tab" className="tab" aria-selected={!plan && tab === k} onClick={() => setTab(k)}>
            {t(`ex.tab.${k}`)}
            {k === 'runs' && stale > 0 && <span className="ex-tab-badge"><Badge tone="stale">{stale}</Badge></span>}
          </button>
        ))}
      </div>
      <div className="panel-body ex-body">
        {plan && (
          <div className="ex-plan">
            <div className="ex-plan-head">
              <Button size="sm" icon="chevronLeft" onClick={() => setTab('runs')}>{t('ex.plan.back')}</Button>
            </div>
            <RerunPlanView pid={pid} records={records} />
          </div>
        )}
        {!plan && tab === 'runs' && toRun > 0 && (
          <div className="notice warn ex-torun" role="status">
            <span className="grow">{t('ex.plan.bar', { n: toRun })}</span>
            <Button size="sm" onClick={() => navigate('experiments', 'plan')}>{t('ex.plan.open')}</Button>
          </div>
        )}
        {!plan && tab === 'runs' && (
          <RunsView records={records} loading={list.loading} error={list.error} onRetry={list.reload}
            onOpen={open} onNew={() => setCreating(true)} selected={openId} />
        )}
        {!plan && tab === 'resources' && <ResourcesView />}
        {!plan && tab === 'runs' && openId && <RunDrawer key={openId} pid={pid} id={openId} summary={summary} onClose={close} />}
      </div>
      {creating && (
        <NewExperimentDialog pid={pid} onClose={() => setCreating(false)}
          onCreated={(rec) => { setCreating(false); list.reload(); navigate('experiments', rec.id); }} />
      )}
    </div>
  );
}
