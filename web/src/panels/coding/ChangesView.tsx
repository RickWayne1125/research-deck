// Changes tab: the commit list on the left (uncommitted work first when there is any), the selected diff on the right.
import { useState } from 'react';
import { Badge, ErrorNote, Spinner, Split } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useApp } from '../../state/app';
import { useRelTime, useT } from '../../i18n';
import type { GitCommit } from '../../types';
import { commitRange, rangeKey, WORKING, type CdStatus, type Focus, type Range } from './api';
import { DiffView, type JumpTarget } from './DiffView';
import { countLabel } from './parts';

export function ChangesView({ pid, status, log, logError, reloadLog, range, setRange, target, onReviewRange, onReviewSelection }: {
  pid: string; status: CdStatus | null; log: GitCommit[] | null; logError: string | null; reloadLog: () => void;
  range: Range | null; setRange: (r: Range) => void; target: JumpTarget | null;
  onReviewRange: (r: Range) => void; onReviewSelection: (r: Range, focus: Focus) => void;
}) {
  const t = useT();
  const rel = useRelTime();
  const { navigate } = useApp();
  const [filter, setFilter] = useState('');
  const dirty = status?.dirty ?? [];
  const q = filter.trim().toLowerCase();
  const commits = (log ?? []).filter(c => !q || `${c.subject} ${c.sha} ${c.author} ${(c.node_ids ?? []).join(' ')}`.toLowerCase().includes(q));
  const activeKey = range ? rangeKey(range) : null;
  // The working-tree diff reloads when the set of dirty files changes (status is polled by the panel).
  const refreshKey = dirty.map(d => `${d.status}${d.path}`).join('|');

  const left = (
    <div className="cd-commits">
      <div className="cd-commits-head">
        <div className="cd-search">
          <Icon name="search" size={14} />
          <input className="input" value={filter} onChange={e => setFilter(e.target.value)} placeholder={t('cd.changes.filter')} aria-label={t('cd.changes.filter')} />
        </div>
      </div>
      <div className="list" role="listbox" aria-label={t('cd.changes.history')}>
        {dirty.length > 0 ? (
          <div role="option" tabIndex={0} aria-selected={activeKey === 'working'} className={`list-item cd-commit ${activeKey === 'working' ? 'active' : ''}`}
            onClick={() => setRange(WORKING)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setRange(WORKING); } }}>
            <div className="col grow" style={{ gap: 3, minWidth: 0 }}>
              <span className="cd-commit-subject">{t('cd.changes.workingTree')}</span>
              <span className="cd-commit-meta">{countLabel(t, 'cd.dirtyCount', dirty.length)}</span>
            </div>
            <Badge tone="warn">{dirty.length}</Badge>
          </div>
        ) : status && <div className="cd-clean faint"><Icon name="check" size={13} /> {t('cd.changes.treeClean')}</div>}
        {logError && <div className="cd-pad"><ErrorNote error={logError} onRetry={reloadLog} /></div>}
        {!log && !logError && <div className="empty"><Spinner /></div>}
        {log && !log.length && <div className="cd-pad faint">{t('cd.changes.noCommits')}</div>}
        {commits.map(c => {
          const active = activeKey === c.sha;
          const refs = c.refs.filter(r => r !== 'HEAD');
          const pick = () => setRange(commitRange(c));
          return (
            <div key={c.sha} role="option" tabIndex={0} aria-selected={active} className={`list-item cd-commit ${active ? 'active' : ''}`}
              onClick={pick} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } }}>
              <div className="col grow" style={{ gap: 3, minWidth: 0 }}>
                <span className="cd-commit-subject ellipsis" title={c.subject}>{c.subject}</span>
                <span className="cd-commit-meta ellipsis">
                  <span className="mono">{c.short}</span> · {c.author} · <span title={c.date}>{rel(c.date)}</span>
                </span>
                {(refs.length > 0 || (c.node_ids?.length ?? 0) > 0) && (
                  <span className="row wrap cd-commit-tags">
                    {refs.map(r => <span key={r} className="chip">{r}</span>)}
                    {c.node_ids?.map(n => (
                      <button key={n} type="button" className="badge process cd-node" title={t('cd.changes.openNode', { id: n })}
                        onClick={e => { e.stopPropagation(); navigate('dag', n); }}>{n}</button>
                    ))}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <Split storageKey="rd.cd.commitsWidth" initial={300} min={220} max={520} label={t('cd.commits.resize')} left={left}
      right={range ? (
        <DiffView pid={pid} range={range} refreshKey={refreshKey} target={target} onReviewRange={onReviewRange} onReviewSelection={onReviewSelection} />
      ) : <div className="empty"><Spinner /></div>} />
  );
}
