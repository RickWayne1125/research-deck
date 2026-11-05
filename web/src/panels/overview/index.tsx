// What waits for the researcher: the things that need a decision (agent proposals, drafted nodes to review, open
// decisions, nodes to revise, runs to start, failed runs, the finished early survey) and what is waiting for evidence.
// Every item can be settled in place or opens the place that settles it. J/K move between items, Y takes an item's
// first action, N its second. A research project shows the list at the top of its outline page (TodayList, with the
// outline's own items first); an engineering project's home is EngineeringOverview (repositories, documents, runs,
// figures).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
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
import { errText } from '../dag/preview';
import type { DagNode, Impact, Proposal } from '../../dag-types';
import { Activity } from './Activity';
import { EngineeringOverview } from './EngineeringOverview';
import { ActorAvatar, errorMessage, usePlural, type NodeIndex } from './parts';
import { facetText } from './today';
import { paperCounts } from '../../start/Survey';
import type { Survey } from '../../start/api';
import { stepOfStage, waitsForStep } from '../../state/stages';
import './overview.css';
import './i18n';

export default function OverviewPanel() {
  const { project, navigate } = useApp();
  const research = !!project && project.kind !== 'engineering';
  // A research project's Today is the top of its outline page.
  useEffect(() => { if (project && research) navigate('outline', null, project.id, { replace: true }); }, [project, research, navigate]);
  if (!project || research) return null;
  return <EngineeringOverview project={project} />;
}

/** An item's keyboard actions: Y runs the first, N the second. */
export interface ItemKeys { yes?: () => void; no?: () => void }
export type Register = (id: string, k: ItemKeys | null) => void;

/** J/K move the focus between the items under `root`; Y and N run the focused item's actions. */
export function useItemKeys(root: RefObject<HTMLElement | null>): Register {
  const keys = useRef(new Map<string, ItemKeys>());
  const register = useCallback<Register>((id, k) => { if (k) keys.current.set(id, k); else keys.current.delete(id); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector('.scrim')) return;
      const items = [...(root.current?.querySelectorAll<HTMLElement>('[data-item]') ?? [])];
      if (!items.length) return;
      const at = items.findIndex(x => x === document.activeElement || x.contains(document.activeElement));
      const k = e.key.toLowerCase();
      if ((k === 'j' || k === 'k') && (at >= 0 || !document.activeElement?.closest('[data-keys-own]'))) {
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
  }, [root]);
  return register;
}

/** How many cards TodayList shows that ask for a decision, and how many wait (the finished survey counts while the
 *  project is at the idea). */
export function useTodayCounts(): { decide: number; wait: number; surveyDone: boolean } {
  const { project } = useApp();
  const { needs, waiting, survey } = useToday();
  const surveyDone = !!survey && survey.status === 'done' && stepOfStage(project?.stage) === 'idea';
  const decide = needs.proposals.length + (needs.review.length ? 1 : 0) + needs.decisions.length + (needs.fix.length ? 1 : 0)
    + (needs.rerun.ids.length ? 1 : 0) + (needs.failed.length ? 1 : 0) + (surveyDone ? 1 : 0);
  const wait = (waiting.evidence.length ? 1 : 0) + (waiting.blocked.length ? 1 : 0);
  return { decide, wait, surveyDone };
}

/** The list of what waits for the researcher. `extra` renders more items first (the outline's own), counted in
 *  `extraCount`; `recent` adds the latest events below. */
export function TodayList({ extra, extraCount = 0, recent = false }: { extra?: (register: Register) => ReactNode; extraCount?: number; recent?: boolean }) {
  const { projectId } = useApp();
  const t = useT();
  const today = useToday();
  const pid = projectId!;
  const { needs, waiting, graph } = today;
  const index = useMemo<NodeIndex>(() => {
    const byId = new Map((graph?.nodes ?? []).map(n => [n.id, n]));
    return { node: id => byId.get(id), ev: id => graph?.eval[id] };
  }, [graph]);
  const listRef = useRef<HTMLDivElement>(null);
  const register = useItemKeys(listRef);
  const counts = useTodayCounts();
  const decide = counts.decide + extraCount;
  const survey = today.survey;
  return (
    <div ref={listRef} className="td-lists">
      <section className="td-sec" aria-labelledby="td-decide">
        <div className="td-sec-head">
          <h2 id="td-decide" className="td-h2">{t('td.decide')} <span className="muted td-count">{decide}</span></h2>
          {decide > 0 && <span className="faint td-keys">{t('td.keys')}</span>}
        </div>
        {decide === 0 ? <div className="card td-none muted">{t('td.nothing')}</div> : (
          <div className="card td-list">
            {extra?.(register)}
            {needs.proposals.map(x => <ProposalItem key={x.id} pid={pid} proposal={x} register={register} onChanged={() => { today.reload(); today.reloadOutline(); }} />)}
            {needs.review.length > 0 && <ReviewItem pid={pid} nodes={needs.review} register={register} onChanged={today.reload} />}
            {counts.surveyDone && survey && <SurveyItem survey={survey} register={register} />}
            {needs.decisions.map(d => <DecisionItem key={d.node.id} node={d.node} options={d.options} register={register} />)}
            {needs.fix.length > 0 && <FixItem ids={needs.fix} index={index} register={register} />}
            {needs.rerun.ids.length > 0 && <RerunItem ids={needs.rerun.ids} gpuH={needs.rerun.gpuH} index={index} register={register} />}
            {needs.failed.length > 0 && <FailedItem runs={needs.failed} register={register} />}
          </div>
        )}
      </section>
      {counts.wait > 0 && (
        <section className="td-sec" aria-labelledby="td-wait">
          <div className="td-sec-head"><h2 id="td-wait" className="td-h2">{t('td.waiting')} <span className="muted td-count">{counts.wait}</span></h2></div>
          <div className="card td-list">
            {waiting.evidence.length > 0 && <EvidenceItem nodes={waiting.evidence} register={register} />}
            {waiting.blocked.length > 0 && <BlockedItem ids={waiting.blocked} index={index} register={register} />}
          </div>
        </section>
      )}
      {recent && !!today.events?.length && (
        <section className="td-sec td-recent">
          <Activity events={today.events.slice(0, 8)} index={index} />
        </section>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ items

/** One row of a list: a small tag, the text, and the actions on the right. Focusable for J/K. */
export function Item({ id, tag, tone, title, children, actions, register, keys }: {
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

function AcceptAllDialog({ pid, nodes: all, onClose, onDone }: { pid: string; nodes: DagNode[]; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const L = useDagLabels();
  const { project } = useApp();
  const { graph } = useToday();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Drafts of a step the project has not reached wait for it (stage rules); accepting them would be refused.
  const step = stepOfStage(project?.stage);
  const nodes = all.filter(n => !waitsForStep(n, step, graph?.stage_mode));
  const waiting = all.length - nodes.length;
  const accept = async () => {
    setBusy(true); setError(null);
    try {
      await dagApi.ops(pid, nodes.map(n => ({ op: 'set_status', node: n.id, to: 'active' })), { rationale: t('td.review.rationale') });
      onDone();
    } catch (e) { setError(errText(e, t)); } finally { setBusy(false); }
  };
  return (
    <Dialog title={t('td.review.allTitle', { n: nodes.length })} onClose={onClose} width={560} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" onClick={accept} disabled={busy || nodes.length === 0}>{busy && <Spinner />}{t('td.review.allGo', { n: nodes.length })}</Button></>
    }>
      <div className="col" style={{ gap: 10 }}>
        <p style={{ margin: 0 }}>{t('td.review.allBody')}</p>
        {waiting > 0 && <p className="muted" style={{ margin: 0 }}>{t('td.review.waiting', { n: waiting })}</p>}
        <ul className="td-names">
          {nodes.map(n => <li key={n.id}><span className="faint td-kind">{L.kind(n.kind)}</span>{L.title(n)}</li>)}
        </ul>
        {error && <div className="notice accent" role="alert">{error}</div>}
      </div>
    </Dialog>
  );
}

/** The survey is written: open it, or ask the agent what it makes of it. */
function SurveyItem({ survey, register }: { survey: Survey; register: Register }) {
  const { navigate, askAgent } = useApp();
  const t = useT();
  const file = survey.files.survey ?? 'notes/survey.md';
  const open = () => navigate('writing', file);
  const ask = () => askAgent(t('sv.item.askPrompt', { file }), { file });
  const roles = (['competitor', 'baseline', 'related', 'background'] as const)
    .map(r => [r, survey.papers.filter(p => p.role === r).length] as const).filter(([, n]) => n > 0)
    .map(([r, n]) => `${n} ${t(`sv.role.${r}`)}`).join(t('td.sep'));
  const gaps = survey.papers.filter(p => p.closes_gap).length;
  return (
    <Item id="survey" tag={t('sv.item.tag')} register={register} keys={{ yes: open, no: ask }}
      title={<>{t('sv.item.title')}<span className="mono td-file">{file}</span></>}
      actions={<><Button size="sm" variant="primary" onClick={open}>{t('sv.item.open')}</Button><Button size="sm" icon="robot" onClick={ask}>{t('td.askAgent')}</Button></>}>
      <p className="td-p">{t('sv.item.body', { n: survey.papers.length, roles, pdfs: paperCounts(survey).done })}</p>
      {gaps > 0 && <p className="td-p td-warn-text">{t('sv.item.gap', { n: gaps })}</p>}
    </Item>
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
