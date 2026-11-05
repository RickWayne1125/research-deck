// Today: the project's home. It answers one question, "what do you need from me?": the stage the project is in and
// what stands before the next one, then the things that need a decision (agent proposals, drafted nodes to review,
// open decisions, nodes to revise, runs to start, failed runs), what is waiting for evidence, and the latest events.
// Every item can be settled in place or opens the place that settles it. J/K move between items, Y takes an item's
// first action, N its second. An engineering project gets EngineeringOverview (repositories, documents, runs, figures).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '../../api/client';
import { Button, Dialog, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { Markdown } from '../../components/Markdown';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useRelTime, useT } from '../../i18n';
import { useDagLabels } from '../../dag/encoding';
import { dagApi } from '../../dag/api';
import { ImpactView } from '../../dag/ImpactView';
import type { DagNode, Impact, Proposal } from '../../dag-types';
import { Activity } from './Activity';
import { StartCard } from './StartCard';
import { EngineeringOverview } from './EngineeringOverview';
import { ActorAvatar, errorMessage, usePlural, type NodeIndex } from './parts';
import { facetText } from './today';
import { Steps } from './NextStep';
import './overview.css';
import './i18n';

export default function OverviewPanel() {
  const { project } = useApp();
  if (!project) return null;
  return project.kind === 'engineering' ? <EngineeringOverview project={project} /> : <ResearchToday />;
}

/** An item's keyboard actions: Y runs the first, N the second. */
interface ItemKeys { yes?: () => void; no?: () => void }
type Register = (id: string, k: ItemKeys | null) => void;

function ResearchToday() {
  const { project, projectId } = useApp();
  const t = useT();
  const today = useToday();
  const pid = projectId!;
  const { needs, waiting } = today;
  const graph = today.graph;

  const index = useMemo<NodeIndex>(() => {
    const byId = new Map((graph?.nodes ?? []).map(n => [n.id, n]));
    return { node: id => byId.get(id), ev: id => graph?.eval[id] };
  }, [graph]);

  // J/K move the focus between items; Y and N run the focused item's actions.
  const keys = useRef(new Map<string, ItemKeys>());
  const listRef = useRef<HTMLDivElement>(null);
  const register = useCallback<Register>((id, k) => { if (k) keys.current.set(id, k); else keys.current.delete(id); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector('.scrim')) return;
      const items = [...(listRef.current?.querySelectorAll<HTMLElement>('[data-item]') ?? [])];
      if (!items.length) return;
      const at = items.findIndex(x => x === document.activeElement || x.contains(document.activeElement));
      const k = e.key.toLowerCase();
      if (k === 'j' || k === 'k') {
        e.preventDefault();
        const next = at < 0 ? 0 : Math.max(0, Math.min(items.length - 1, at + (k === 'j' ? 1 : -1)));
        items[next].focus();
        items[next].scrollIntoView({ block: 'nearest' });
      } else if ((k === 'y' || k === 'n') && at >= 0) {
        const fn = keys.current.get(items[at].dataset.item ?? '')?.[k === 'y' ? 'yes' : 'no'];
        if (fn) { e.preventDefault(); fn(); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  if (!project) return null;
  const empty = today.loaded && !!graph && graph.nodes.length === 0 && !needs.proposals.length;
  const decide = needs.proposals.length + (needs.review.length ? 1 : 0) + needs.decisions.length + (needs.fix.length ? 1 : 0)
    + (needs.rerun.ids.length ? 1 : 0) + (needs.failed.length ? 1 : 0);
  const wait = (waiting.evidence.length ? 1 : 0) + (waiting.blocked.length ? 1 : 0);

  return (
    <div className="panel td">
      <div className="panel-body td-body" ref={listRef}>
        <div className="td-page">
          <header className="td-head">
            <div className="td-title">
              <div className="row" style={{ gap: 10 }}>
                <h1 className="td-h1">{project.name}</h1>
                {project.demo && <span className="chip">{t('nav.demo')}</span>}
              </div>
              {project.summary && <p className="muted td-summary">{project.summary}</p>}
            </div>
            <Steps pid={pid} />
          </header>

          {today.error && (
            <div className="notice warn" role="status">
              <Icon name="warn" />
              <span className="grow"><b>{t('ov.dag.unavailable')}</b> · {t('ov.dag.unavailableBody', { msg: today.error })}</span>
              <button type="button" className="btn sm" onClick={today.reload}>{t('common.retry')}</button>
            </div>
          )}

          {!today.loaded ? <div className="td-loading"><Spinner /></div> : empty ? <StartCard pid={pid} onCreated={today.reload} /> : (
            <>
              <section className="td-sec" aria-labelledby="td-decide">
                <div className="td-sec-head">
                  <h2 id="td-decide" className="td-h2">{t('td.decide')} <span className="muted td-count">{decide}</span></h2>
                  {decide > 0 && <span className="faint td-keys">{t('td.keys')}</span>}
                </div>
                {decide === 0 ? <div className="card td-none muted">{t('td.nothing')}</div> : (
                  <div className="card td-list">
                    {needs.proposals.map(x => <ProposalItem key={x.id} pid={pid} proposal={x} register={register} onChanged={today.reload} />)}
                    {needs.review.length > 0 && <ReviewItem pid={pid} nodes={needs.review} register={register} onChanged={today.reload} />}
                    {needs.decisions.map(d => <DecisionItem key={d.node.id} node={d.node} options={d.options} register={register} />)}
                    {needs.fix.length > 0 && <FixItem ids={needs.fix} index={index} register={register} />}
                    {needs.rerun.ids.length > 0 && <RerunItem ids={needs.rerun.ids} gpuH={needs.rerun.gpuH} index={index} register={register} />}
                    {needs.failed.length > 0 && <FailedItem runs={needs.failed} register={register} />}
                  </div>
                )}
              </section>

              {wait > 0 && (
                <section className="td-sec" aria-labelledby="td-wait">
                  <div className="td-sec-head"><h2 id="td-wait" className="td-h2">{t('td.waiting')} <span className="muted td-count">{wait}</span></h2></div>
                  <div className="card td-list">
                    {waiting.evidence.length > 0 && <EvidenceItem nodes={waiting.evidence} register={register} />}
                    {waiting.blocked.length > 0 && <BlockedItem ids={waiting.blocked} index={index} register={register} />}
                  </div>
                </section>
              )}

              {!!today.events?.length && (
                <section className="td-sec td-recent">
                  <Activity events={today.events.slice(0, 8)} index={index} />
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ items

/** One row of a list: a small tag, the text, and the actions on the right. Focusable for J/K. */
function Item({ id, tag, tone, title, children, actions, register, keys }: {
  id: string; tag: string; tone?: 'prop' | 'warn' | 'accent'; title: ReactNode; children?: ReactNode; actions?: ReactNode;
  register: Register; keys?: ItemKeys;
}) {
  const ref = useRef(keys);
  ref.current = keys;
  useEffect(() => {
    register(id, { yes: () => ref.current?.yes?.(), no: () => ref.current?.no?.() });
    return () => register(id, null);
  }, [id, register]);
  return (
    <div className="td-item" tabIndex={0} data-item={id}>
      <span className={`chip td-tag${tone ? ` is-${tone}` : ''}`}>{tag}</span>
      <div className="td-text">
        <h3 className="td-h3">{title}</h3>
        {children}
      </div>
      {actions && <div className="td-actions">{actions}</div>}
    </div>
  );
}

function ProposalItem({ pid, proposal, register, onChanged }: { pid: string; proposal: Proposal; register: Register; onChanged: () => void }) {
  const { navigate } = useApp();
  const t = useT();
  const L = useDagLabels();
  const rel = useRelTime();
  const plural = usePlural();
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [rebased, setRebased] = useState<Impact | null>(null);
  const unlocks = (proposal.requires ?? []).filter(r => r.startsWith('unlock:')).map(r => r.slice('unlock:'.length));
  const [unlockOk, setUnlockOk] = useState(false);
  const impact = rebased ?? proposal.impact;
  const firstNode = proposal.ops.map(o => (typeof o.node === 'string' ? o.node : null)).find(Boolean) ?? null;

  const approve = async () => {
    if (busy || (unlocks.length && !unlockOk)) return;
    setBusy(true); setError(null);
    try { await dagApi.approve(pid, proposal.id); onChanged(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const d = e.detail as { impact?: Impact; proposal?: Proposal } | null;
        const next = d?.impact ?? d?.proposal?.impact ?? null;
        if (next) setRebased(next); else setError(errorMessage(e));
        onChanged();
      } else setError(errorMessage(e));
    } finally { setBusy(false); }
  };
  const reject = async () => {
    if (!reason.trim()) return;
    setBusy(true); setError(null);
    try { await dagApi.reject(pid, proposal.id, reason.trim()); onChanged(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <Item id={`p:${proposal.id}`} tag={t('td.tag.proposal')} tone="prop" register={register} keys={{ yes: approve, no: () => setRejecting(true) }}
      title={proposal.title}
      actions={rejecting ? (
        <>
          <Button size="sm" variant="ghost" onClick={() => { setRejecting(false); setReason(''); }}>{t('common.cancel')}</Button>
          <Button size="sm" variant="danger" disabled={!reason.trim() || busy} onClick={reject}>{t('td.reject')}</Button>
        </>
      ) : (
        <>
          <Button size="sm" variant="primary" icon="check" disabled={busy || (unlocks.length > 0 && !unlockOk)} onClick={approve}>{t('td.approve')}</Button>
          <Button size="sm" onClick={() => setRejecting(true)} disabled={busy}>{t('td.reject')}</Button>
        </>
      )}>
      <p className="td-p td-meta">
        <ActorAvatar by={proposal.by} size={16} /> {L.actor(proposal.by)} · {rel(proposal.at)} · {plural('ov.inbox.ops', proposal.ops.length)}
        {firstNode && <> · <button type="button" className="td-link mono" onClick={() => navigate('dag', firstNode)}>{firstNode}</button></>}
      </p>
      {proposal.rationale && <Markdown text={proposal.rationale} className="td-rationale" />}
      {(proposal.state === 'needs_rebase' || rebased) && <div className="notice warn td-small"><Icon name="refresh" /> <span>{t('ov.inbox.rebase')}</span></div>}
      {impact && (
        <details className="td-more">
          <summary>{t('td.impact')}</summary>
          <ImpactView impact={impact} compact />
        </details>
      )}
      {unlocks.length > 0 && (
        <label className="td-confirm td-small">
          <input type="checkbox" checked={unlockOk} onChange={e => setUnlockOk(e.target.checked)} />
          <span>{t('ov.inbox.confirmUnlock', { ids: unlocks.join(', ') })}</span>
        </label>
      )}
      {rejecting && (
        <textarea className="textarea td-reason" rows={2} value={reason} autoFocus placeholder={t('ov.inbox.rejectPh')}
          onChange={e => setReason(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) reject(); if (e.key === 'Escape') setRejecting(false); }} />
      )}
      {error && <div className="notice accent td-small" role="alert">{error}</div>}
    </Item>
  );
}

function ReviewItem({ pid, nodes, register, onChanged }: { pid: string; nodes: DagNode[]; register: Register; onChanged: () => void }) {
  const { navigate } = useApp();
  const t = useT();
  const L = useDagLabels();
  const [confirming, setConfirming] = useState(false);
  const kinds = useMemo(() => {
    const m = new Map<DagNode['kind'], number>();
    nodes.forEach(n => m.set(n.kind, (m.get(n.kind) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [nodes]);
  const review = () => navigate('dag', 'filter:proposed');
  return (
    <>
      <Item id="review" tag={t('td.tag.drafted')} tone="prop" register={register} keys={{ yes: review, no: () => setConfirming(true) }}
        title={t('td.review.title', { n: nodes.length })}
        actions={<><Button size="sm" variant="primary" onClick={review}>{t('td.review.one')}</Button><Button size="sm" onClick={() => setConfirming(true)}>{t('td.review.all')}…</Button></>}>
        <p className="td-p">{t('td.review.body', { kinds: kinds.map(([k, n]) => `${n} ${L.kind(k)}`).join(t('td.sep')) })}</p>
      </Item>
      {confirming && <AcceptAllDialog pid={pid} nodes={nodes} onClose={() => setConfirming(false)} onDone={() => { setConfirming(false); onChanged(); }} />}
    </>
  );
}

function AcceptAllDialog({ pid, nodes, onClose, onDone }: { pid: string; nodes: DagNode[]; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const L = useDagLabels();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accept = async () => {
    setBusy(true); setError(null);
    try {
      await dagApi.ops(pid, nodes.map(n => ({ op: 'set_status', node: n.id, to: 'active' })), { rationale: t('td.review.rationale') });
      onDone();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog title={t('td.review.allTitle', { n: nodes.length })} onClose={onClose} width={560} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" onClick={accept} disabled={busy}>{busy && <Spinner />}{t('td.review.allGo', { n: nodes.length })}</Button></>
    }>
      <div className="col" style={{ gap: 10 }}>
        <p style={{ margin: 0 }}>{t('td.review.allBody')}</p>
        <ul className="td-names">
          {nodes.map(n => <li key={n.id}><span className="faint td-kind">{L.kind(n.kind)}</span>{L.title(n)}</li>)}
        </ul>
        {error && <div className="notice accent" role="alert">{error}</div>}
      </div>
    </Dialog>
  );
}

function DecisionItem({ node, options, register }: { node: DagNode; options: DagNode[]; register: Register }) {
  const { navigate, askAgent } = useApp();
  const t = useT();
  const L = useDagLabels();
  const go = () => navigate('dag', node.id);
  const ask = () => askAgent(t('td.decision.ask', { title: L.title(node) }), { node_id: node.id });
  const question = facetText(node, 'question') ?? facetText(node, 'choice');
  return (
    <Item id={`d:${node.id}`} tag={t('dagx.kind.decision')} register={register} keys={{ yes: go, no: ask }} title={L.title(node)}
      actions={<><Button size="sm" variant="primary" onClick={go}>{t('td.decision.go')}</Button><Button size="sm" icon="robot" onClick={ask}>{t('td.askAgent')}</Button></>}>
      {question && <p className="td-p td-clamp">{question}</p>}
      {options.length > 0 && (
        <div className="td-chips">{options.map(o => <button key={o.id} type="button" className="chip" onClick={() => navigate('dag', o.id)} title={o.id}>{L.title(o)}</button>)}</div>
      )}
    </Item>
  );
}

function NameList({ ids, index, max = 3 }: { ids: string[]; index: NodeIndex; max?: number }) {
  const L = useDagLabels();
  const t = useT();
  const shown = ids.slice(0, max).map(id => { const n = index.node(id); return n ? L.title(n) : id; });
  return <p className="td-p td-clamp">{shown.join(t('td.sep'))}{ids.length > max ? t('td.andMore', { n: ids.length - max }) : ''}</p>;
}

function FixItem({ ids, index, register }: { ids: string[]; index: NodeIndex; register: Register }) {
  const { navigate } = useApp();
  const t = useT();
  const go = () => navigate('dag', 'filter:attention');
  return (
    <Item id="fix" tag={t('td.tag.fix')} tone="warn" register={register} keys={{ yes: go }} title={t('td.fix.title', { n: ids.length })}
      actions={<Button size="sm" variant="primary" onClick={go}>{t('td.fix.go')}</Button>}>
      <NameList ids={ids} index={index} />
    </Item>
  );
}

function RerunItem({ ids, gpuH, index, register }: { ids: string[]; gpuH: number; index: NodeIndex; register: Register }) {
  const { navigate } = useApp();
  const t = useT();
  const go = () => navigate('experiments', 'plan');
  return (
    <Item id="rerun" tag={t('td.tag.run')} tone="warn" register={register} keys={{ yes: go }}
      title={gpuH > 0 ? t('td.rerun.titleH', { n: ids.length, h: gpuH < 10 ? gpuH.toFixed(1) : Math.round(gpuH) }) : t('td.rerun.title', { n: ids.length })}
      actions={<Button size="sm" variant="primary" onClick={go}>{t('td.rerun.go')}</Button>}>
      <NameList ids={ids} index={index} />
    </Item>
  );
}

function FailedItem({ runs, register }: { runs: { id: string; title: string }[]; register: Register }) {
  const { navigate } = useApp();
  const t = useT();
  const go = () => navigate('experiments', runs[0].id);
  return (
    <Item id="failed" tag={t('td.tag.failed')} tone="accent" register={register} keys={{ yes: go }} title={t('td.failed.title', { n: runs.length })}
      actions={<Button size="sm" variant="primary" onClick={go}>{t('td.failed.go')}</Button>}>
      <p className="td-p td-clamp">{runs.slice(0, 3).map(r => r.title || r.id).join(t('td.sep'))}{runs.length > 3 ? t('td.andMore', { n: runs.length - 3 }) : ''}</p>
    </Item>
  );
}

function EvidenceItem({ nodes, register }: { nodes: DagNode[]; register: Register }) {
  const { navigate, askAgent } = useApp();
  const t = useT();
  const L = useDagLabels();
  const go = () => navigate('dag', nodes[0].id);
  const ask = () => askAgent(t('td.evidence.ask', { ids: nodes.slice(0, 6).map(n => n.id).join(', ') }), { node_id: nodes[0].id });
  return (
    <Item id="evidence" tag={t('td.tag.noEvidence')} tone="warn" register={register} keys={{ yes: go, no: ask }}
      title={nodes.length === 1 ? L.title(nodes[0]) : t('td.evidence.title', { n: nodes.length })}
      actions={<><Button size="sm" onClick={go}>{t('td.open')}</Button><Button size="sm" icon="robot" onClick={ask}>{t('td.askAgent')}</Button></>}>
      <p className="td-p td-clamp">{nodes.length === 1 ? t('td.evidence.one', { kind: L.kind(nodes[0].kind) }) : nodes.slice(0, 3).map(n => L.title(n)).join(t('td.sep'))}</p>
    </Item>
  );
}

function BlockedItem({ ids, index, register }: { ids: string[]; index: NodeIndex; register: Register }) {
  const { navigate } = useApp();
  const t = useT();
  const go = () => navigate('dag', 'filter:attention');
  return (
    <Item id="blocked" tag={t('td.tag.blocked')} register={register} keys={{ yes: go }} title={t('td.blocked.title', { n: ids.length })}
      actions={<Button size="sm" onClick={go}>{t('td.open')}</Button>}>
      <NameList ids={ids} index={index} />
    </Item>
  );
}
