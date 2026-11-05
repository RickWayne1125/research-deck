// "Describe the change" box for draw.io and matplotlib figures. POST ai-edit starts a run on the visualization panel's
// session; the stream is followed like useAgentRun; the fenced block of the answer is diffed against the source the
// request was made from. Accept hands the proposal to the editor; Reject drops it. Nothing is written before Accept.
import { useCallback, useEffect, useRef, useState } from 'react';
import { post, streamRun } from '../../api/client';
import { extractFence } from '../../agent/useAgentRun';
import { Markdown } from '../../components/Markdown';
import { Icon } from '../../components/icons';
import { Button, Dialog, IconButton, Spinner } from '../../components/ui';
import { useT } from '../../i18n';
import type { AgentEvent, FigureKind } from '../../types';
import { DiffView, diffRows } from './DiffView';
import { errMessage, vz } from './api';

interface Answerer { provider: string; model: string; effort: string; fast: boolean }
interface EditState {
  status: 'idle' | 'running' | 'done' | 'error' | 'cancelled';
  runId: string | null; text: string; error: string | null; who: Answerer | null; activity: string | null;
}
const IDLE: EditState = { status: 'idle', runId: null, text: '', error: null, who: null, activity: null };

function useFigureEdit(projectId: string, figureId: string) {
  const [state, setState] = useState<EditState>(IDLE);
  const off = useRef<(() => void) | null>(null);
  useEffect(() => () => off.current?.(), []);

  const start = useCallback(async (instruction: string, source: string) => {
    off.current?.();
    setState({ ...IDLE, status: 'running' });
    try {
      const meta = await vz.aiEdit(projectId, figureId, instruction, source);
      setState(s => ({ ...s, runId: meta.run_id, who: { provider: meta.provider, model: meta.model, effort: meta.effort, fast: meta.fast } }));
      off.current = streamRun(meta.run_id, (e: AgentEvent) => setState(s => {
        switch (e.type) {
          case 'start': return { ...s, who: { provider: e.provider, model: e.model, effort: e.effort, fast: e.fast } };
          case 'text': return { ...s, text: s.text + e.delta };
          case 'thinking': return { ...s, activity: e.text ?? null };
          case 'tool': return { ...s, activity: `${e.name} ${e.detail ?? ''}`.trim() };
          case 'error': return { ...s, error: e.message };
          case 'done': return { ...s, text: e.text || s.text, status: e.cancelled ? 'cancelled' : e.ok ? 'done' : 'error' };
          default: return s;
        }
      }));
    } catch (e) {
      setState(s => ({ ...s, status: 'error', error: errMessage(e) }));
    }
  }, [projectId, figureId]);

  const cancel = useCallback(() => {
    if (state.runId) post(`/api/agent/runs/${state.runId}/cancel`).catch(() => {});
  }, [state.runId]);
  const reset = useCallback(() => { off.current?.(); setState(IDLE); }, []);
  return { ...state, start, cancel, reset };
}

export function answererLabel(who: Answerer | null, t: (k: string) => string): string {
  if (!who) return '';
  const name = who.provider === 'claude' ? 'Claude' : who.provider === 'codex' ? 'Codex' : t('vz.ai.fake');
  return [name, who.model, who.effort, who.fast ? 'fast' : ''].filter(Boolean).join(' · ');
}

/** The answer's text after the fenced block: the agent's change note. */
function changeNote(text: string): string {
  const end = text.lastIndexOf('```');
  return (end >= 0 ? text.slice(end + 3) : '').trim();
}

export function AiAssist({ projectId, figureId, kind, getSource, onAccept }: {
  projectId: string; figureId: string; kind: FigureKind;
  getSource: () => string;
  /** Apply the accepted proposal; resolves with a short confirmation to show. */
  onAccept: (proposal: string) => Promise<string> | string;
}) {
  const t = useT();
  const run = useFigureEdit(projectId, figureId);
  const [instruction, setInstruction] = useState('');
  const [base, setBase] = useState('');
  const [big, setBig] = useState(false);
  const [notice, setNotice] = useState<{ tone: '' | 'accent'; text: string } | null>(null);
  const lang = kind === 'drawio' ? 'xml' : 'python';

  const fenced = run.status === 'done' ? extractFence(run.text, lang) ?? extractFence(run.text) : null;
  // A fence drops the file's final newline; keep the source's own ending so the diff shows only real changes.
  const proposal = fenced === null ? null : base.endsWith('\n') && !fenced.endsWith('\n') ? `${fenced}\n` : fenced;
  const stats = proposal !== null ? diffRows(base, proposal) : null;

  const submit = () => {
    if (!instruction.trim() || run.status === 'running') return;
    const src = getSource();
    setBase(src);
    setNotice(null);
    run.start(instruction.trim(), src);
  };

  const accept = async () => {
    if (proposal === null) return;
    try {
      const msg = await onAccept(proposal);
      setNotice({ tone: '', text: msg });
      setInstruction('');
      run.reset();
      setBig(false);
    } catch (e) {
      setNotice({ tone: 'accent', text: t('vz.ai.failed', { msg: errMessage(e) }) });
    }
  };
  const reject = () => { run.reset(); setBig(false); };
  const drift = proposal !== null && getSource() !== base;

  return (
    <section className="vz-ai" aria-label={t('vz.ai.title')}>
      <div className="row">
        <Icon name="sparkle" />
        <span className="h3 grow">{t('vz.ai.title')}</span>
      </div>
      {run.who && (
        <div className="vz-ai-who" title={t('vz.ai.answeredBy', { agent: answererLabel(run.who, t) })}>
          <Icon name="robot" size={12} /><span className="ellipsis">{t('vz.ai.answeredBy', { agent: answererLabel(run.who, t) })}</span>
        </div>
      )}
      <textarea className="textarea" rows={3} value={instruction} onChange={e => setInstruction(e.target.value)}
        placeholder={kind === 'drawio' ? t('vz.ai.placeholderDio') : t('vz.ai.placeholder')}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } }}
        disabled={run.status === 'running'} />
      <div className="row">
        <span className="faint grow" style={{ fontSize: 'var(--fs-xs)' }}>{t('vz.ai.runHint')}</span>
        {run.status === 'running'
          ? <Button size="sm" icon="stop" onClick={run.cancel}>{t('common.stop')}</Button>
          : <Button size="sm" variant="primary" icon="sparkle" onClick={submit} disabled={!instruction.trim()}>{t('vz.ai.run')}</Button>}
      </div>

      {run.status === 'running' && (
        <div className="vz-ai-status">
          <Spinner />
          <span className="grow ellipsis">{t('vz.ai.running', { agent: answererLabel(run.who, t) || 'Agent' })}</span>
          <span className="faint mono num">{run.text.length ? t('vz.ai.chars', { n: run.text.length }) : run.activity ? '…' : ''}</span>
        </div>
      )}
      {(run.status === 'error' || run.status === 'cancelled') && (
        <div className="notice accent"><Icon name="warn" /><span className="grow">{run.status === 'cancelled' ? t('vz.ai.cancelled') : run.error ?? t('agent.error')}</span>
          <IconButton icon="close" label={t('common.close')} onClick={run.reset} /></div>
      )}
      {run.status === 'done' && proposal === null && (
        <div className="notice warn"><Icon name="warn" /><span className="grow">{t('vz.ai.noFence')}</span>
          <IconButton icon="close" label={t('common.close')} onClick={run.reset} /></div>
      )}
      {run.status === 'done' && proposal !== null && stats && (
        <div className="vz-ai-result">
          <div className="row">
            <span className="label grow">{t('vz.ai.diffTitle')}</span>
            <span className="mono num faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('vz.ai.stats', { add: stats.add, del: stats.del })}</span>
            <IconButton icon="split" label={t('vz.ai.expand')} onClick={() => setBig(true)} />
          </div>
          {stats.add + stats.del === 0 ? <div className="notice">{t('vz.ai.same')}</div> : <DiffView before={base} after={proposal} maxHeight={260} />}
          {changeNote(run.text) && <div className="vz-ai-note"><div className="label">{t('vz.ai.note')}</div><Markdown text={changeNote(run.text)} /></div>}
          {drift && <div className="notice warn"><Icon name="warn" /><span>{t('vz.ai.drift')}</span></div>}
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <Button size="sm" onClick={reject}>{t('vz.ai.reject')}</Button>
            <Button size="sm" variant="primary" icon="check" onClick={accept} disabled={stats.add + stats.del === 0}>{t('vz.ai.accept')}</Button>
          </div>
        </div>
      )}
      {notice && <div className={`notice ${notice.tone}`}><Icon name={notice.tone ? 'warn' : 'check'} /><span className="grow">{notice.text}</span>
        <IconButton icon="close" label={t('common.close')} onClick={() => setNotice(null)} /></div>}
      {run.status === 'idle' && !notice && <p className="vz-hint">{t('vz.ai.hint')}</p>}

      {big && proposal !== null && (
        <Dialog title={t('vz.ai.diffTitle')} onClose={() => setBig(false)} width={980}
          footer={<><Button onClick={reject}>{t('vz.ai.reject')}</Button><Button variant="primary" icon="check" onClick={accept}>{t('vz.ai.accept')}</Button></>}>
          <DiffView before={base} after={proposal} maxHeight="65vh" />
        </Dialog>
      )}
    </section>
  );
}
