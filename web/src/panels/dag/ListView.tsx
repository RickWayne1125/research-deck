// The map as a list (the default view): nodes grouped by the four steps, one row each with only the exceptions shown
// (to review, to rerun, broken …). A row opens in place: what it says, what it rests on, what depends on it, the
// options of a decision (choosing one previews its impact first) and the actions. Review mode is the keyboard:
// J/K move, Y accepts a draft, N rejects it, Enter opens the details, Esc closes.
import { useEffect, useMemo, useRef } from 'react';
import { Icon } from '../../components/icons';
import { Button } from '../../components/ui';
import { useT } from '../../i18n';
import { FreshBadge, STATUS_STYLE, useDagLabels } from '../../dag/encoding';
import type { DagNode, GraphResponse, NodeEval, Op } from '../../dag-types';
import { STEPS, STEP_DAG, stepOfDag, waitsForStep, type StepId } from '../../state/stages';
import { decisionOptions, facetText, isOpenDecision } from '../overview/today';
import { isDead } from './model';

/** The facet each kind is written around (shown when a row opens). */
const MAIN_FACET: Partial<Record<DagNode['kind'], string>> = {
  problem: 'statement', finding: 'statement', gap: 'statement', solution: 'mechanism', decision: 'question',
  reference: 'takeaway', claim: 'text', design: 'overview',
};
const KIND_ORDER: DagNode['kind'][] = ['problem', 'reference', 'dataset', 'finding', 'gap', 'solution', 'decision', 'design', 'module', 'experiment', 'figure', 'claim', 'section'];
const nodeOf = (addr: string) => addr.match(/^node:([^#[]+)/)?.[1] ?? null;

export function mainText(n: DagNode): string | null {
  const main = MAIN_FACET[n.kind];
  if (main) { const v = facetText(n, main); if (v) return v; }
  for (const f of Object.values(n.facets ?? {})) if ((f.type === 'prose' || f.type === 'text') && typeof f.value === 'string' && f.value.trim()) return f.value.trim();
  return n.purpose ?? n.notes ?? null;
}

export interface ListViewProps {
  graph: GraphResponse;
  members: Set<string>;               // the nodes the filter shows
  runNode: Map<string, string>;
  selected: string | null;
  currentStep: StepId;
  missing: number;                    // checks that stand before the next step
  missingLabels?: string[];           // … and what they check
  stageMode?: 'strict' | 'ahead' | 'free';
  readOnly: boolean;
  onSelect: (id: string | null) => void;
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  onDetails: (id: string) => void;
  onAsk: (id: string) => void;
  onChoose: (decision: DagNode, option: DagNode) => void;
  onNextStep: () => void;
  onPreviewOps?: (ops: Op[], title: string, node: string) => void;
}

export function ListView(p: ListViewProps) {
  const t = useT();
  const L = useDagLabels();
  const byId = useMemo(() => new Map(p.graph.nodes.map(n => [n.id, n])), [p.graph]);

  // Who rests on whom: upstream edges from the node, dependents from everybody else's edges.
  const dependents = useMemo(() => {
    const m = new Map<string, { id: string; edge: string }[]>();
    for (const n of p.graph.nodes) for (const e of n.edges ?? []) {
      const up = nodeOf(e.to) ?? (e.to.startsWith('run:') ? p.runNode.get(e.to.slice(4).split('#')[0]) ?? null : null);
      if (!up || up === n.id) continue;
      const list = m.get(up) ?? [];
      if (!list.some(x => x.id === n.id)) list.push({ id: n.id, edge: e.type });
      m.set(up, list);
    }
    return m;
  }, [p.graph, p.runNode]);

  const groups = useMemo(() => {
    const order = (n: DagNode) => (STEP_DAG[stepOfDag(n.stage)].indexOf(n.stage) * 100) + KIND_ORDER.indexOf(n.kind);
    return STEPS.map(step => ({
      step,
      nodes: p.graph.nodes.filter(n => p.members.has(n.id) && stepOfDag(n.stage) === step)
        .sort((a, b) => order(a) - order(b) || L.title(a).localeCompare(L.title(b))),
    }));
  }, [p.graph, p.members, L]);
  const flat = useMemo(() => groups.flatMap(g => g.nodes.map(n => n.id)), [groups]);

  // Review mode: J/K move (and open) rows, Y/N accept or reject a draft, Enter the details, Esc closes the row.
  const keys = useRef(p);
  keys.current = p;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector('.scrim')) return;
      const k = keys.current;
      const at = k.selected ? flat.indexOf(k.selected) : -1;
      const key = e.key.toLowerCase();
      if (key === 'j' || key === 'k') {
        e.preventDefault();
        const next = flat[at < 0 ? 0 : Math.max(0, Math.min(flat.length - 1, at + (key === 'j' ? 1 : -1)))];
        if (next) k.onSelect(next);
      } else if (at >= 0 && !k.readOnly) {
        const node = byId.get(flat[at]);
        if (!node) return;
        if (key === 'y' && node.status === 'proposed' && !waitsForStep(node, k.currentStep, k.stageMode)) { e.preventDefault(); k.onAccept(node.id); k.onSelect(flat[at + 1] ?? flat[at - 1] ?? null); }
        else if (key === 'n' && node.status === 'proposed') { e.preventDefault(); k.onReject(node.id); }
        else if (e.key === 'Enter') { e.preventDefault(); k.onDetails(node.id); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [flat, byId]);
  useEffect(() => {
    if (p.selected) document.getElementById(`dl-row-${p.selected}`)?.scrollIntoView({ block: 'nearest' });
  }, [p.selected]);

  if (!flat.length) return <div className="dl-list-empty muted">{t('dag.list.empty')}</div>;
  const at = STEPS.indexOf(p.currentStep);
  const staged = (p.stageMode ?? 'free') !== 'free';
  return (
    <div className="dl-list">
      {groups.map((g, i) => (
        <section key={g.step} className={`dl-group${staged && i > at ? ' later' : ''}`} aria-label={t(`step.${g.step}`)}>
          <div className="dl-group-head">
            <h2 className="dl-group-title">{t(`step.${g.step}`)} {g.nodes.length > 0 && <span className="faint num">{g.nodes.length}</span>}</h2>
            {g.step === p.currentStep && (
              <button type="button" className="dl-group-gate" onClick={p.onNextStep}>
                {p.missing ? t('td.next.missing', { n: p.missing }) : t('td.next.ready')}
              </button>
            )}
            {staged && i < at && <span className="chip dl-stage-chip is-passed">{t('dag.stage.passed')}</span>}
            {staged && i > at && <span className="chip dl-stage-chip">{t('dag.stage.notStarted')}</span>}
          </div>
          {staged && i > at && (g.nodes.length === 0 || i === at + 1) && (
            <div className="dl-locked">
              <Icon name="lock" size={14} />
              <div className="col" style={{ gap: 2 }}>
                <span>{t('dag.stage.startsAfter', { step: t(`step.${STEPS[i - 1]}`) })}</span>
                {i === at + 1 && (
                  <span className="faint dl-locked-hint">
                    {p.missingLabels?.length ? t('dag.stage.missing', { items: [...new Set(p.missingLabels)].join(t('td.sep')) }) : ''}{t('dag.stage.then')}
                  </span>
                )}
              </div>
            </div>
          )}
          {g.nodes.length === 0 ? (!(staged && i > at) && <div className="dl-group-none faint">{t('dag.list.none')}</div>) : (
            <ul className="dl-rows">
              {g.nodes.map(n => (
                <Row key={n.id} node={n} ev={p.graph.eval[n.id]} open={p.selected === n.id} byId={byId} p={p}
                  dependents={dependents.get(n.id) ?? []} />
              ))}
            </ul>
          )}
        </section>
      ))}
      {!p.readOnly && <div className="dl-list-keys faint">{t('dag.list.keys')}</div>}
    </div>
  );
}

function StatusMark({ node }: { node: DagNode }) {
  const L = useDagLabels();
  const s = STATUS_STYLE[node.status];
  return (
    <span className={`dl-mark is-${node.status}`} title={L.status(node.status)} aria-label={L.status(node.status)}
      style={{ background: s.fill === 'transparent' ? 'transparent' : s.fill, borderColor: s.line, borderStyle: s.dashed ? 'dashed' : 'solid' }}>
      {s.icon && node.status !== 'proposed' && <Icon name={s.icon} size={9} />}
    </span>
  );
}

function Row({ node, ev, open, byId, dependents, p }: {
  node: DagNode; ev: NodeEval | undefined; open: boolean; byId: Map<string, DagNode>; dependents: { id: string; edge: string }[]; p: ListViewProps;
}) {
  const t = useT();
  const L = useDagLabels();
  const level = ev?.level && ev.level !== 'fresh' && !isDead(node.status) ? ev.level : null;
  const decision = node.kind === 'decision' && isOpenDecision(node, byId);
  const options = node.kind === 'decision' ? decisionOptions(node, byId) : [];
  const chosen = facetText(node, 'choice');
  const upstream = (node.edges ?? []).map(e => ({ id: nodeOf(e.to) ?? e.to, edge: e.type, polarity: e.polarity }))
    .filter((x, i, all) => all.findIndex(y => y.id === x.id) === i);
  const name = (id: string) => { const n = byId.get(id); return n ? L.title(n) : id; };
  const dead = isDead(node.status);
  const waits = !dead && waitsForStep(node, p.currentStep, p.stageMode);
  // What the node rests on (its parents on the map), shown under the title when staged. Like the server's rule, only
  // parents of an earlier step must be confirmed; parents in the same step need not be.
  const parents = upstream.map(u => byId.get(u.id)).filter((n): n is DagNode => !!n && n.id !== node.id);
  const held = (n: DagNode) => n.status === 'confirmed' || n.status === 'locked';
  const mine = STEPS.indexOf(stepOfDag(node.stage));
  const open_ = parents.filter(n => STEPS.indexOf(stepOfDag(n.stage)) < mine && !held(n)).length;
  const staged = (p.stageMode ?? 'free') !== 'free';
  return (
    <li id={`dl-row-${node.id}`} className={`dl-row${open ? ' open' : ''}${dead ? ' dead' : ''}`}>
      <button type="button" className="dl-row-head" aria-expanded={open} onClick={() => p.onSelect(open ? null : node.id)}>
        <StatusMark node={node} />
        <span className="dl-row-title ellipsis">{L.title(node)}</span>
        <span className="dl-row-kind faint">{L.kind(node.kind)}</span>
        {waits && <span className="chip dl-row-chip is-waits" title={t('dag.stage.waitsHint')}>{t('dag.stage.waits')}</span>}
        {decision && <span className="chip dl-row-chip">{t('dag.list.undecided')}</span>}
        {level && <FreshBadge level={level} />}
      </button>
      {staged && (dead || parents.length > 0) && (
        <div className="dl-row-from faint">
          {dead ? t('dag.stage.branchEnds')
            : t('dag.stage.basis', { names: parents.slice(0, 3).map(n => L.title(n)).join(t('td.sep')) + (parents.length > 3 ? t('td.andMore', { n: parents.length - 3 }) : '') })
              + (open_ ? t('dag.stage.someOpen', { n: open_ }) : parents.every(held) ? t('dag.stage.allConfirmed') : '')}
        </div>
      )}
      {open && (
        <div className="dl-row-body">
          <div className="row wrap dl-row-meta faint">
            <span className="mono">{node.id}</span>
            <span>· {L.status(node.status)}</span>
            {level && ev?.reasons?.[0] && <span>· {ev.reasons[0].note ?? ev.reasons[0].edge ?? ''}</span>}
          </div>
          {mainText(node) && <p className="dl-row-text">{mainText(node)}</p>}

          {options.length > 0 && (
            <div className="dl-options">
              <div className="label">{t('dag.list.options')}</div>
              {options.map(o => (
                <div key={o.id} className={`dl-option${chosen === o.id ? ' chosen' : ''}`}>
                  <span className="grow dl-option-main">
                    <button type="button" className="dl-link" onClick={() => p.onSelect(o.id)}>{L.title(o)}</button>
                    {mainText(o) && <span className="faint dl-option-text" title={mainText(o) ?? ''}>{mainText(o)}</span>}
                  </span>
                  {chosen === o.id ? <span className="chip">{t('dag.list.chosen')}</span>
                    : !p.readOnly && <Button size="sm" onClick={() => p.onChoose(node, o)}>{t('dag.list.choose')}</Button>}
                </div>
              ))}
              <div className="faint dl-hint">{t('dag.list.chooseHint')}</div>
            </div>
          )}

          <div className="dl-deps">
            <div className="dl-deps-col">
              <div className="label">{t('dag.list.upstream')}</div>
              {upstream.length === 0 ? <div className="faint">{t('common.none')}</div> : upstream.map(u => (
                <div key={u.id} className="dl-dep">
                  <span className="faint dl-dep-edge">{t(`dag.edge.${u.edge}`)}</span>
                  {byId.has(u.id) ? <button type="button" className="dl-link ellipsis" onClick={() => p.onSelect(u.id)}>{name(u.id)}</button> : <span className="mono ellipsis">{u.id}</span>}
                </div>
              ))}
            </div>
            <div className="dl-deps-col">
              <div className="label">{t('dag.list.downstream')}</div>
              {dependents.length === 0 ? <div className="faint">{t('common.none')}</div> : dependents.map(d => (
                <div key={d.id} className="dl-dep">
                  <span className="faint dl-dep-edge">{t(`dag.edge.${d.edge}`)}</span>
                  <button type="button" className="dl-link ellipsis" onClick={() => p.onSelect(d.id)}>{name(d.id)}</button>
                </div>
              ))}
            </div>
          </div>

          <div className="row wrap dl-row-actions">
            {node.status === 'proposed' && !p.readOnly && (
              <>
                {!waits && <Button size="sm" variant="primary" icon="check" onClick={() => p.onAccept(node.id)}>{t('dag.list.accept')}</Button>}
                <Button size="sm" onClick={() => p.onReject(node.id)}>{t('dag.list.reject')}…</Button>
              </>
            )}
            <Button size="sm" onClick={() => p.onDetails(node.id)}>{t('dag.list.details')}</Button>
            <Button size="sm" icon="robot" onClick={() => p.onAsk(node.id)}>{t('td.askAgent')}</Button>
          </div>
        </div>
      )}
    </li>
  );
}
