// Dialogs of the map: status verdicts with reasons (§2.4), the live gate checklist (§1), and creating a node (and the
// "Create the problem node" starter).
import { useEffect, useMemo, useState } from 'react';
import { Icon } from '../../components/icons';
import { Button, Dialog, Spinner } from '../../components/ui';
import { useI18n, useRelTime, useT } from '../../i18n';
import { ImpactView } from '../../dag/ImpactView';
import { dagApi } from '../../dag/api';
import { StatusBadge, useDagLabels } from '../../dag/encoding';
import { DAG_STAGES, type DagNode, type GateStatus, type GraphResponse, type Impact, type NodeKind, type Op, type OpsResult, type StageKey } from '../../dag-types';
import type { StatusAction } from './Inspector';
import { DEFAULT_STAGE, ID_PREFIX, isLive, slug } from './model';
import { errText } from './preview';

// ------------------------------------------------------------------ status verdicts

export const ABANDON_REASONS = ['infeasible', 'dominated', 'no_headroom', 'competitor_closed_gap', 'out_of_scope', 'cost', 'time', 'other'] as const;

const TARGET: Record<StatusAction, string> = {
  activate: 'active', confirm: 'confirmed', reopen: 'active', lock: 'locked', unlock: 'confirmed',
  refute: 'refuted', abandon: 'abandoned', supersede: 'superseded', revive: 'active',
};

export function StatusDialog({ pid, node, action, graph, onClose, onDone }: {
  pid: string; node: DagNode; action: StatusAction; graph: GraphResponse;
  onClose: () => void; onDone: (r: OpsResult | null, action: StatusAction) => void;
}) {
  const t = useT();
  const L = useDagLabels();
  const evidenceEdges = (node.edges ?? []).filter(e => e.type === 'evidence').map(e => e.to);
  const [reason, setReason] = useState('');
  const [enumReason, setEnumReason] = useState<(typeof ABANDON_REASONS)[number]>('infeasible');
  const [evidence, setEvidence] = useState<Set<string>>(new Set(evidenceEdges.filter((_, i) => i === 0)));
  const [extraEvidence, setExtraEvidence] = useState('');
  const [successor, setSuccessor] = useState('');
  const [impact, setImpact] = useState<Impact | null>(null);
  const [impactErr, setImpactErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const candidates = useMemo(() => graph.nodes.filter(n => n.id !== node.id && isLive(n.status))
    .sort((a, b) => Number(b.kind === node.kind) - Number(a.kind === node.kind) || a.id.localeCompare(b.id)), [graph, node]);

  const evidenceList = [...evidence, ...extraEvidence.split(/[\s,]+/).filter(Boolean)];
  const op = (): Op => {
    const base: Op = { op: 'set_status', node: node.id, to: TARGET[action] };
    if (action === 'abandon') return { ...base, reason: enumReason, note: reason.trim() };
    if (action === 'refute') return { ...base, reason: reason.trim(), evidence: evidenceList };
    if (action === 'supersede') return { ...base, reason: reason.trim(), superseded_by: successor };
    return { ...base, reason: reason.trim() };
  };

  // What the verdict does downstream (refuting or abandoning orphans dependents); lock/unlock change no fingerprint.
  useEffect(() => {
    if (action === 'lock' || action === 'unlock') return;
    let alive = true;
    dagApi.impact(pid, { ops: [{ ...op(), reason: action === 'abandon' ? enumReason : 'preview' }] })
      .then(i => { if (alive) setImpact(i); }).catch(e => { if (alive) setImpactErr(errText(e)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid, node.id, action, successor]);

  const valid = (action === 'abandon' ? true : reason.trim().length > 0)
    && (action !== 'refute' || evidenceList.length > 0)
    && (action !== 'supersede' || !!successor);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      if (action === 'lock') { await dagApi.lock(pid, node.id, reason.trim()); onDone(null, action); }
      else if (action === 'unlock') { await dagApi.unlock(pid, node.id, reason.trim()); onDone(null, action); }
      else onDone(await dagApi.ops(pid, [op()], { base_digest: graph.digest, rationale: reason.trim() || enumReason }), action);
    } catch (e) { setError(errText(e, t)); } finally { setBusy(false); }
  };

  return (
    <Dialog title={t('dag.status.dialogTitle', { action: t(`dag.status.${action}`), id: node.id })} onClose={onClose} width={620} footer={
      <>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant={action === 'refute' || action === 'abandon' ? 'danger' : 'primary'} onClick={submit} disabled={!valid || busy}>
          {busy && <Spinner />}{t(`dag.status.${action}`)}
        </Button>
      </>
    }>
      <div className="col" style={{ gap: 12 }}>
        <div className="row wrap" style={{ gap: 6 }}>
          <StatusBadge status={node.status} /><Icon name="chevronRight" size={12} /><StatusBadge status={TARGET[action] as DagNode['status']} />
          <span className="muted ellipsis">{L.title(node)}</span>
        </div>
        <p className="muted" style={{ margin: 0 }}>{t(`dag.status.${action}Hint`)}</p>

        {action === 'abandon' && (
          <label className="field"><span className="label">{t('dag.status.abandonReason')}</span>
            <select className="select" value={enumReason} onChange={e => setEnumReason(e.target.value as typeof enumReason)}>
              {ABANDON_REASONS.map(r => <option key={r} value={r}>{t(`dag.abandon.${r}`)}</option>)}
            </select>
          </label>
        )}
        {action === 'supersede' && (
          <label className="field"><span className="label">{t('dag.status.successor')}</span>
            <select className="select" value={successor} onChange={e => setSuccessor(e.target.value)}>
              <option value="">{t('dag.status.pickSuccessor')}</option>
              {candidates.map(n => <option key={n.id} value={n.id}>{n.id} — {L.title(n)}</option>)}
            </select>
          </label>
        )}
        {action === 'refute' && (
          <fieldset className="dg-fieldset">
            <legend className="label">{t('dag.status.evidence')}</legend>
            {evidenceEdges.map(a => (
              <label key={a} className="dg-check mono"><input type="checkbox" checked={evidence.has(a)}
                onChange={() => setEvidence(prev => { const n = new Set(prev); if (n.has(a)) n.delete(a); else n.add(a); return n; })} /> {a}</label>
            ))}
            <input className="input mono" value={extraEvidence} onChange={e => setExtraEvidence(e.target.value)} placeholder={t('dag.status.evidencePh')} />
            <span className="faint dg-hint">{t('dag.status.freezeHint')}</span>
          </fieldset>
        )}
        <label className="field">
          <span className="label">{action === 'abandon' ? t('dag.status.note') : t('dag.status.reason')}</span>
          <textarea className="textarea" rows={3} value={reason} onChange={e => setReason(e.target.value)} placeholder={t(`dag.status.reasonPh.${action}`)} autoFocus />
        </label>
        {impact && <ImpactView impact={impact} compact />}
        {impactErr && <div className="faint">{impactErr}</div>}
        {error && <div className="notice accent" role="alert"><Icon name="warn" /><span>{error}</span></div>}
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ gate checklist

export function GateDialog({ gate, readOnly, onClose, onPass, onSelect }: {
  gate: GateStatus; readOnly: boolean; onClose: () => void; onPass: (note: string) => Promise<void>; onSelect: (id: string) => void;
}) {
  const t = useT();
  const { lang } = useI18n();
  const L = useDagLabels();
  const rel = useRelTime();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ok = gate.checks.filter(c => c.ok).length;
  const pass = async () => {
    setBusy(true); setError(null);
    try { await onPass(note.trim()); } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog title={`${gate.gate} · ${(lang === 'zh' ? gate.title.zh : gate.title.en) || gate.title.en}`} onClose={onClose} width={600} footer={
      <>
        <Button onClick={onClose}>{t('common.close')}</Button>
        {!readOnly && gate.state !== 'passed' && (
          <Button variant="primary" icon="check" onClick={pass} disabled={busy}>{busy && <Spinner />}{t('dag.gate.pass')}</Button>
        )}
      </>
    }>
      <div className="col" style={{ gap: 12 }}>
        <div className="row wrap" style={{ gap: 8 }}>
          <span className={`dg-gate is-${gate.state}`}><span className="dg-gate-dot" /><b className="mono">{gate.gate}</b><span>{t(`dag.gate.state.${gate.state}`)}</span></span>
          <span className="muted">{t('dag.gate.after', { stage: L.stage(gate.after) })}</span>
          <span className="faint num">{t('dag.gate.checks', { ok, n: gate.checks.length })}</span>
        </div>
        {gate.passed && <div className="faint">{t('dag.gate.passedBy', { who: L.actor(gate.passed.by), at: rel(gate.passed.at), snap: gate.passed.snapshot })}</div>}
        <ul className="dg-checks">
          {gate.checks.map((c, i) => (
            <li key={i} className={`dg-check-row ${c.ok ? 'is-ok' : 'is-no'}`}>
              <Icon name={c.ok ? 'check' : 'close'} size={13} />
              <div className="col grow" style={{ gap: 2, minWidth: 0 }}>
                <span>{c.label}</span>
                {(c.value != null || c.target != null) && <span className="faint num">{t('dag.gate.value', { v: String(c.value ?? '—'), target: String(c.target ?? '—') })}</span>}
                {c.items && c.items.length > 0 && (
                  <span className="row wrap" style={{ gap: 4 }}>
                    {c.items.map(id => <button key={id} type="button" className="chip mono" onClick={() => { onSelect(id); onClose(); }}>{id}</button>)}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
        {!readOnly && gate.state !== 'passed' && (
          <>
            <p className="faint" style={{ margin: 0 }}>{t('dag.gate.passHint', { gate: gate.gate })}</p>
            <label className="field"><span className="label">{t('dag.gate.note')}</span>
              <input className="input" value={note} onChange={e => setNote(e.target.value)} placeholder={t('dag.gate.notePh')} /></label>
          </>
        )}
        {error && <div className="notice accent"><Icon name="warn" /><span>{error}</span></div>}
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ new node / problem starter

const KINDS: NodeKind[] = ['problem', 'reference', 'dataset', 'finding', 'gap', 'solution', 'decision', 'design', 'module', 'experiment', 'figure', 'claim', 'section'];
/** The first prose facet each kind is written around. */
const MAIN_FACET: Partial<Record<NodeKind, string>> = {
  problem: 'statement', finding: 'statement', gap: 'statement', solution: 'mechanism', decision: 'question',
  reference: 'takeaway', claim: 'text', design: 'overview',
};

export function NewNodeDialog({ pid, graph, starter, onClose, onCreated }: {
  pid: string; graph: GraphResponse | null; starter?: boolean; onClose: () => void; onCreated: (id: string, r: OpsResult) => void;
}) {
  const t = useT();
  const { lang } = useI18n();
  const L = useDagLabels();
  const [kind, setKind] = useState<NodeKind>('problem');
  const [stage, setStage] = useState<StageKey>('S0');
  const [titleZh, setTitleZh] = useState('');
  const [titleEn, setTitleEn] = useState('');
  const [idSlug, setIdSlug] = useState('');
  const [text, setText] = useState('');
  const [metric, setMetric] = useState('');
  const [threshold, setThreshold] = useState('');
  const [direction, setDirection] = useState<'lower' | 'higher'>('lower');
  const [kill, setKill] = useState('');
  const [status, setStatus] = useState<'active' | 'proposed'>('active');
  const [altGroup, setAltGroup] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setStage(DEFAULT_STAGE[kind]); }, [kind]);
  const autoSlug = slug(titleEn || idSlug || '') || slug(titleZh ? 'node' : '');
  const id = `${ID_PREFIX[kind]}.${slug(idSlug) || autoSlug || 'new'}`;
  const taken = new Set(graph?.nodes.map(n => n.id) ?? []);
  const clash = taken.has(id);
  const groupsHere = useMemo(() => (graph?.nodes ?? []).filter(n => n.kind === 'gap' || n.kind === 'problem' || n.kind === 'decision' || !!graph?.nodes.some(m => m.alt_group === n.id)), [graph]);

  const submit = async () => {
    setBusy(true); setError(null);
    const facets: Record<string, { type: string; value: unknown }> = {};
    const main = MAIN_FACET[kind];
    if (main && text.trim()) facets[main] = { type: 'prose', value: text.trim() };
    if (kind === 'problem') {
      if (metric.trim()) facets.success = { type: 'json', value: { metric: metric.trim(), threshold: Number(threshold) || threshold, direction } };
      if (kill.trim()) facets.kill_criteria = { type: 'prose', value: kill.trim() };
      facets.scope = facets.scope ?? { type: 'json', value: {} };
    }
    if (kind === 'reference') facets.role = { type: 'json', value: 'related' };
    if (kind === 'claim') facets.role = { type: 'json', value: 'contribution' };
    const node: Record<string, unknown> = {
      id, kind, stage, status, title: { zh: titleZh.trim() || undefined, en: titleEn.trim() || undefined }, facets, edges: [],
    };
    if (altGroup && (kind === 'solution' || kind === 'design')) node.alt_group = altGroup;
    try {
      const r = await dagApi.ops(pid, [{ op: 'create', node }]);
      onCreated(id, r);
    } catch (e) { setError(errText(e, t)); } finally { setBusy(false); }
  };

  const valid = (titleZh.trim() || titleEn.trim()) && !clash && (!starter || text.trim());
  return (
    <Dialog title={starter ? t('dag.new.starterTitle') : t('dag.new.title')} onClose={onClose} width={620} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" onClick={submit} disabled={!valid || busy}>{busy && <Spinner />}{t('dag.new.create')}</Button></>
    }>
      <div className="col" style={{ gap: 12 }}>
        {starter && <p className="muted" style={{ margin: 0 }}>{t('dag.new.starterBody')}</p>}
        {!starter && (
          <div className="row" style={{ gap: 8 }}>
            <label className="field grow"><span className="label">{t('dag.new.kind')}</span>
              <select className="select" value={kind} onChange={e => setKind(e.target.value as NodeKind)}>
                {KINDS.map(k => <option key={k} value={k}>{L.kind(k)}</option>)}
              </select></label>
            <label className="field"><span className="label">{t('dag.new.stage')}</span>
              <select className="select" value={stage} onChange={e => setStage(e.target.value as StageKey)}>
                {DAG_STAGES.map(s => <option key={s} value={s}>{s} · {L.stage(s)}</option>)}
              </select></label>
            <label className="field"><span className="label">{t('dag.new.status')}</span>
              <select className="select" value={status} onChange={e => setStatus(e.target.value as 'active' | 'proposed')}>
                <option value="active">{L.status('active')}</option><option value="proposed">{L.status('proposed')}</option>
              </select></label>
          </div>
        )}
        <div className="row" style={{ gap: 8 }}>
          <label className="field grow"><span className="label">{t('dag.new.titleZh')}</span>
            <input className="input" value={titleZh} onChange={e => setTitleZh(e.target.value)} autoFocus={lang === 'zh'} placeholder={starter ? t('dag.new.problemPhZh') : ''} /></label>
          <label className="field grow"><span className="label">{t('dag.new.titleEn')}</span>
            <input className="input" value={titleEn} onChange={e => setTitleEn(e.target.value)} autoFocus={lang === 'en'} placeholder={starter ? t('dag.new.problemPhEn') : ''} /></label>
        </div>
        <label className="field"><span className="label">{t('dag.new.id')}</span>
          <div className="row" style={{ gap: 6 }}>
            <span className="mono faint">{ID_PREFIX[kind]}.</span>
            <input className="input mono grow" value={idSlug} onChange={e => setIdSlug(e.target.value)} placeholder={autoSlug || 'tail-latency'} />
          </div>
          <span className={`mono dg-hint ${clash ? '' : 'faint'}`} style={clash ? { color: 'var(--accent-text)' } : undefined}>{clash ? t('dag.new.idTaken', { id }) : id}</span>
        </label>
        {MAIN_FACET[kind] && (
          <label className="field"><span className="label">{t(`dag.new.facet.${MAIN_FACET[kind]}`)}</span>
            <textarea className="textarea" rows={3} value={text} onChange={e => setText(e.target.value)} placeholder={starter ? t('dag.new.statementPh') : ''} /></label>
        )}
        {kind === 'problem' && (
          <>
            <div className="row" style={{ gap: 8 }}>
              <label className="field grow"><span className="label">{t('dag.new.metric')}</span>
                <input className="input mono" value={metric} onChange={e => setMetric(e.target.value)} placeholder="ttft_p99" /></label>
              <label className="field"><span className="label">{t('dag.new.threshold')}</span>
                <input className="input mono" value={threshold} onChange={e => setThreshold(e.target.value)} placeholder="2.0" style={{ width: 90 }} /></label>
              <label className="field"><span className="label">{t('dag.new.direction')}</span>
                <select className="select" value={direction} onChange={e => setDirection(e.target.value as 'lower' | 'higher')}>
                  <option value="lower">{t('dag.new.lower')}</option><option value="higher">{t('dag.new.higher')}</option>
                </select></label>
            </div>
            <label className="field"><span className="label">{t('dag.new.kill')}</span>
              <textarea className="textarea" rows={2} value={kill} onChange={e => setKill(e.target.value)} placeholder={t('dag.new.killPh')} />
              <span className="faint dg-hint">{t('dag.new.killHint')}</span></label>
          </>
        )}
        {(kind === 'solution' || kind === 'design') && groupsHere.length > 0 && (
          <label className="field"><span className="label">{t('dag.new.altGroup')}</span>
            <select className="select" value={altGroup} onChange={e => setAltGroup(e.target.value)}>
              <option value="">{t('common.none')}</option>
              {groupsHere.map(n => <option key={n.id} value={n.id}>{n.id} — {L.title(n)}</option>)}
            </select></label>
        )}
        {error && <div className="notice accent"><Icon name="warn" /><span>{error}</span></div>}
      </div>
    </Dialog>
  );
}
