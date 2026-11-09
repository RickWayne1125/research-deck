// The agent at work, floating over the view while the conversation is folded: who is answering, how many tools it has
// called and the last one, a button that opens the conversation and one that stops the answer (styles/shell.css).
import { useEffect, useState } from 'react';
import { streamRun } from '../api/client';
import { Button, IconButton, Spinner } from '../components/ui';
import { useT } from '../i18n';
import { agentApi, type RunSummary } from './api';
import { ProviderMark, providerLabel } from './parts';

export function AgentPill({ pid, onOpen }: { pid: string; onOpen: () => void }) {
  const t = useT();
  const [run, setRun] = useState<RunSummary | null>(null);
  const [tools, setTools] = useState<{ n: number; last: string | null }>({ n: 0, last: null });

  // the project conversation's answer in progress, the one the dock shows (other runs, such as a figure or a check,
  // show where they were started); polled while the page is visible, quicker while one runs
  useEffect(() => {
    let alive = true, timer = 0;
    const tick = async () => {
      let next: RunSummary | null = null;
      if (document.visibilityState === 'visible') {
        try { next = (await agentApi.runs(pid)).find(r => r.status === 'running' && r.panel === 'project') ?? null; } catch { /* offline */ }
        if (alive) setRun(prev => (prev?.run_id === next?.run_id ? prev : next));
      }
      if (alive) timer = window.setTimeout(tick, next ? 2500 : 5000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [pid]);

  // its tool calls (the stream replays the run from the start)
  const runId = run?.run_id ?? null;
  useEffect(() => {
    setTools({ n: 0, last: null });
    if (!runId) return;
    return streamRun(runId, e => {
      if (e.type === 'reset') setTools({ n: 0, last: null });
      else if (e.type === 'tool') setTools(s => ({ n: s.n + 1, last: e.name }));
      else if (e.type === 'done') setRun(null);
    }, { onGone: () => setRun(null) });
  }, [runId]);

  if (!run) return null;
  const who = providerLabel(run.provider, t);
  const sub = tools.n ? t('agent.pill.tools', { n: tools.n }) + (tools.last ? ` · ${tools.last}` : '') : t('agent.pill.starting');
  return (
    <div className="agent-pill" role="status" aria-label={t('agent.pill.working', { agent: who })}>
      <span className="agent-pill-mark"><ProviderMark provider={run.provider} size={16} /></span>
      <span className="agent-pill-text">
        <span className="agent-pill-title">{t('agent.pill.working', { agent: who })}</span>
        <span className="agent-pill-sub">{sub}</span>
      </span>
      <Spinner label={t('agent.pill.working', { agent: who })} />
      <Button variant="soft" onClick={onOpen}>{t('agent.pill.open')}</Button>
      <IconButton icon="stop" label={t('common.stop')} onClick={() => { agentApi.cancel(run.run_id).catch(() => {}); setRun(null); }} />
    </div>
  );
}
