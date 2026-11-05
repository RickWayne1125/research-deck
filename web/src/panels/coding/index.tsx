// The Code view: Changes (commits and diffs) | Review (agent findings).
// The panel owns what the tabs share: git status and log, the range shown in Changes, the running review, and the
// jump from a finding to its line. The tab is the route's sub-path (#/<project>/coding/<tab>).
import { useCallback, useEffect, useRef, useState } from 'react';
import { Badge, Empty, IconButton, PanelHead, useLoad } from '../../components/ui';
import { useApp } from '../../state/app';
import { useI18n, useT } from '../../i18n';
import type { CodeFinding } from '../../types';
import { commitRange, currentRepo, fetchLog, fetchRepos, fetchStatus, setCurrentRepo, WORKING, type Focus, type Range } from './api';
import { ChangesView } from './ChangesView';
import type { JumpTarget } from './DiffView';
import { ReviewView } from './ReviewView';
import { countLabel } from './parts';
import { useReview } from './reviewState';
import './coding.css';
import './i18n';

const TABS = ['changes', 'review'] as const;
type Tab = (typeof TABS)[number];
const isTab = (v: string | null | undefined): v is Tab => !!v && (TABS as readonly string[]).includes(v);
const STATUS_POLL_MS = 20_000;

/** Several repositories in one workspace: pick which one the panel shows (remounts the panel's content). */
function RepoPicker({ pid, onChange }: { pid: string; onChange: () => void }) {
  const t = useT();
  const repos = useLoad(() => fetchRepos(pid), [pid]);
  const list = repos.data ?? [];
  if (list.length < 2) return null;
  const value = currentRepo(pid) ?? list[0].repo ?? '';
  return (
    <label className="row" style={{ gap: 6 }} title={t('cd.repo.hint')}>
      <span className="label">{t('cd.repo')}</span>
      <select className="select" value={value} onChange={e => { setCurrentRepo(pid, e.target.value || null); onChange(); }}>
        {list.map(r => <option key={r.repo ?? ''} value={r.repo ?? ''}>{r.label}{r.branch ? ` · ${r.branch}` : ''}{r.dirty ? ` · ${r.dirty}±` : ''}</option>)}
      </select>
    </label>
  );
}

export default function CodingPanel() {
  const [repoVersion, setRepoVersion] = useState(0);
  const { projectId } = useApp();
  return <CodingPanelInner key={repoVersion} onRepoChange={() => setRepoVersion(v => v + 1)} pidHint={projectId ?? ''} />;
}

function CodingPanelInner({ onRepoChange, pidHint }: { onRepoChange: () => void; pidHint: string }) {
  const { projectId, sub, navigate, onEvent } = useApp();
  const pid = projectId!;
  const t = useT();
  const { lang } = useI18n();

  const [tab, setTabState] = useState<Tab>(() => {
    if (isTab(sub)) return sub;
    try { const v = localStorage.getItem('rd.cd.tab'); return isTab(v) ? v : 'changes'; } catch { return 'changes'; }
  });
  useEffect(() => { if (isTab(sub)) setTabState(sub); }, [sub]);
  const setTab = useCallback((next: Tab) => {
    setTabState(next);
    try { localStorage.setItem('rd.cd.tab', next); } catch { /* ignore */ }
    navigate('coding', next);
  }, [navigate]);

  const status = useLoad(() => fetchStatus(pid), [pid]);
  const log = useLoad(() => fetchLog(pid), [pid]);
  const reloaders = useRef({ status: status.reload, log: log.reload });
  reloaders.current = { status: status.reload, log: log.reload };
  const refresh = useCallback(() => { reloaders.current.status(); reloaders.current.log(); }, []);

  // File writes from the dashboard (and agents) change git status; debounce bursts. External edits are caught by polling.
  useEffect(() => {
    let timer = 0;
    const off = onEvent('file', () => { window.clearTimeout(timer); timer = window.setTimeout(() => reloaders.current.status(), 600); });
    return () => { off(); window.clearTimeout(timer); };
  }, [onEvent]);
  useEffect(() => {
    const id = window.setInterval(() => { if (document.visibilityState === 'visible') reloaders.current.status(); }, STATUS_POLL_MS);
    return () => window.clearInterval(id);
  }, [tab]);
  // A new HEAD (a commit made elsewhere) means a new log.
  const head = status.data?.head ?? null;
  const lastHead = useRef<string | null>(null);
  useEffect(() => {
    if (lastHead.current !== null && head !== lastHead.current) reloaders.current.log();
    lastHead.current = head;
  }, [head]);

  const review = useReview(pid, lang);

  // The range shown in Changes: uncommitted work when there is some, else the latest commit.
  const [range, setRange] = useState<Range | null>(null);
  useEffect(() => {
    if (range || !status.data || !log.data) return;
    setRange(status.data.dirty.length || !log.data.length ? WORKING : commitRange(log.data[0]));
  }, [range, status.data, log.data]);

  const [jump, setJump] = useState<JumpTarget | null>(null);
  const onJump = useCallback((f: CodeFinding, r: Range) => {
    setRange(r);
    setJump(j => ({ range: r, path: f.file, line: f.line, n: (j?.n ?? 0) + 1 }));
    setTab('changes');
  }, [setTab]);
  const onReviewRange = useCallback((r: Range) => { review.start(r); setTab('review'); }, [review, setTab]);
  const onReviewSelection = useCallback((r: Range, focus: Focus) => { review.start(r, focus); setTab('review'); }, [review, setTab]);

  const s = status.data;
  const notRepo = s ? !s.is_repo : false;
  const subtitle = !s ? (status.error ?? t('common.loading'))
    : !s.is_repo ? t('cd.notRepo')
      : [s.branch ?? t('cd.detached'), s.head?.slice(0, 7), s.dirty.length ? countLabel(t, 'cd.dirtyCount', s.dirty.length) : t('cd.clean')].filter(Boolean).join(' · ');

  return (
    <div className="panel cd-panel">
      <PanelHead title={t('nav.coding')} subtitle={subtitle}>
        <RepoPicker pid={pidHint} onChange={onRepoChange} />
        {s?.upstream && (s.ahead > 0 || s.behind > 0) && (
          <Badge title={t('cd.aheadBehind', { upstream: s.upstream })}>↑{s.ahead} ↓{s.behind}</Badge>
        )}
        <IconButton icon="refresh" label={t('common.refresh')} onClick={refresh} />
      </PanelHead>
      <div className="tabs" role="tablist" aria-label={t('nav.coding')}>
        {TABS.map(id => (
          <button key={id} type="button" role="tab" className="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {t(`cd.tab.${id}`)}
            {id === 'changes' && !!s?.dirty.length && <span className="badge cd-tab-badge">{s.dirty.length}</span>}
            {id === 'review' && review.openCount > 0 && (
              <span className={`badge cd-tab-badge ${review.openHigh ? 'accent' : ''}`} title={t('cd.review.openFindings', { n: review.openCount })}>{review.openCount}</span>
            )}
          </button>
        ))}
      </div>
      <div className="panel-body cd-body" role="tabpanel">
        {notRepo && (
          <Empty icon="branch" title={t('cd.notRepo')}>{t('cd.notRepoHint')}</Empty>
        )}
        {tab === 'changes' && !notRepo && (
          <ChangesView pid={pid} status={s} log={log.data} logError={log.data ? null : log.error} reloadLog={log.reload}
            range={range} setRange={setRange} target={jump} onReviewRange={onReviewRange} onReviewSelection={onReviewSelection} />
        )}
        {tab === 'review' && !notRepo && <ReviewView review={review} status={s} log={log.data} onJump={onJump} />}
      </div>
    </div>
  );
}
