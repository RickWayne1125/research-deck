// Custom React Flow nodes of the Research Map (docs/DAG.md §8 Encodings): shape = kind, fill/border = status,
// ring + badge = freshness, corner flags, the experiment cell mini-grid, the rev pill with a stacked-card shadow, and the
// last agent's robot avatar. Lane, rail and attempt-group nodes are backgrounds drawn behind the cards.
// Every state is shown through the shared tokens in dag/encoding.tsx; dimming and impact painting are classes the map
// puts on the React Flow wrapper, so these components re-render only when their node changes.
import { memo, type CSSProperties } from 'react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import { Icon } from '../../components/icons';
import { useT } from '../../i18n';
import { FRESH_STYLE, KIND_ICON, STATUS_STYLE, useDagLabels } from '../../dag/encoding';
import type { CellEval, DagNode, Freshness, GateStatus, NodeEval, StageKey } from '../../dag-types';
import { cellGrid } from './model';
import { GRID, shapeDetail, shapeOf, shapePath } from './shapes';

const P = 9;   // room around the body for the rings

export interface CardData extends Record<string, unknown> {
  node: DagNode;
  ev?: NodeEval;
  w: number; h: number;
  chip: boolean;                   // dead node collapsed to a chip
  cells: string[];
  runCount: number;
  stack: number;                   // older versions folded into this card by a supersede chain
  reason: string | null;           // status reason (refuted / abandoned)
  agent: 'claude' | 'codex' | null;
  thumb: string | null;            // drawn figure preview URL
  chosen: boolean;                 // the chosen sibling of an attempt group
  version: string | null;          // dataset version, shown on the cylinder
}
export type CardNode = Node<CardData, 'dgCard'>;

function Handles() {
  return (
    <>
      <Handle id="l" type="target" position={Position.Left} className="dg-handle" isConnectable={false} />
      <Handle id="t" type="target" position={Position.Top} className="dg-handle" isConnectable={false} />
      <Handle id="r" type="source" position={Position.Right} className="dg-handle" isConnectable={false} />
      <Handle id="b" type="source" position={Position.Bottom} className="dg-handle" isConnectable={false} />
    </>
  );
}

/** The SVG behind a card: stacked copies, the preview ring, the freshness ring, the body and its double line. */
function ShapeSvg({ data, level }: { data: CardData; level: Freshness | null }) {
  const { node, w, h, chip } = data;
  const shape = chip ? 'pill' : shapeOf(node);
  const st = STATUS_STYLE[node.status];
  const fr = level && level !== 'fresh' ? FRESH_STYLE[level] : null;
  // A supersede stack shows two cards behind; an edited node (rev > 1) shows one.
  const stacks = data.stack > 0 ? 2 : !chip && (node.head?.rev ?? 1) > 1 ? 1 : 0;
  const body = shapePath(shape, w, h, 0);
  const detail = chip ? null : shapeDetail(shape, w, h);
  const fill = st.fill === 'transparent' ? 'var(--surface)' : st.fill;
  return (
    <svg className="dg-shape" width={w + 2 * P} height={h + 2 * P} viewBox={`${-P} ${-P} ${w + 2 * P} ${h + 2 * P}`} aria-hidden="true">
      {Array.from({ length: stacks }, (_, i) => stacks - i).map(k => (
        <path key={k} d={body} transform={`translate(${3 * k},${3 * k})`} className="dg-stack" />
      ))}
      <path d={shapePath(shape, w, h, 6)} className="dg-pv" />
      {fr && <path d={shapePath(shape, w, h, 3)} className="dg-ring" style={{ stroke: fr.color, strokeDasharray: fr.dashed ? '4 3' : undefined }} />}
      <path d={body} className="dg-body" style={{ fill, stroke: st.line, strokeDasharray: st.dashed ? '4 3' : undefined, strokeWidth: data.chosen ? 2.4 : undefined }} />
      {st.double && <path d={shapePath(shape, w, h, -2.5)} className="dg-body2" style={{ stroke: st.line }} />}
      {detail && <path d={detail} className="dg-detail" style={{ stroke: st.line }} />}
    </svg>
  );
}

function CellGrid({ cells, evals }: { cells: string[]; evals: Record<string, CellEval> }) {
  const L = useDagLabels();
  const grid = cellGrid(cells);
  const rows = grid.rows.slice(0, GRID.rowsMax);
  const hidden = grid.rows.slice(GRID.rowsMax).flat().filter(Boolean).length;
  return (
    <div className="dg-grid" role="img" aria-label={cells.map(c => `${c}: ${L.fresh(evals[c]?.level ?? 'unbuilt')}`).join('; ')}>
      {rows.map((row, i) => (
        <div key={i} className="dg-grid-row">
          {row.map((c, j) => {
            if (!c) return <span key={j} className="dg-cell is-empty" />;
            const ce = evals[c];
            const lvl = ce?.level ?? 'unbuilt';
            const s = FRESH_STYLE[lvl];
            const style: CSSProperties = lvl === 'fresh'
              ? { background: 'var(--data-line)', borderColor: 'var(--data-line)' }
              : { background: s.wash, borderColor: s.color, borderStyle: s.dashed ? 'dashed' : 'solid' };
            return (
              <span key={j} className={`dg-cell lvl-${lvl} ${ce?.impl_lag ? 'is-lag' : ''}`} style={style}
                title={`${c} · ${L.fresh(lvl)}${ce?.reused ? ' · reused' : ''}${ce?.cutoff ? ' · ≈' : ''}`}>
                {ce?.cutoff ? '≈' : ''}
              </span>
            );
          })}
        </div>
      ))}
      {hidden > 0 && <span className="dg-grid-more faint num">+{hidden}</span>}
    </div>
  );
}

function Flags({ ev, node }: { ev?: NodeEval; node: DagNode }) {
  const t = useT();
  const flags = new Set(ev?.flags ?? []);
  const out: { icon: string; cls: string; title: string }[] = [];
  if (flags.has('lock_alert')) out.push({ icon: 'lock', cls: 'is-accent', title: t('dag.flag.lock_alert') });
  if (flags.has('unsealed')) out.push({ icon: 'file', cls: '', title: t('dag.flag.unsealed') });
  if (flags.has('behind_head')) out.push({ icon: 'pin', cls: '', title: t('dag.flag.behind_head') });
  if (flags.has('conflict')) out.push({ icon: 'split', cls: 'is-accent', title: t('dag.flag.conflict') });
  if (flags.has('drift')) out.push({ icon: 'info', cls: 'is-small', title: t('dag.flag.drift') });
  if (flags.has('impl_lag') || Object.values(ev?.cells ?? {}).some(c => c.impl_lag)) out.push({ icon: 'coding', cls: 'is-warn', title: t('dag.flag.impl_lag') });
  const shaky = ev?.shaky ?? [];
  return (
    <span className="dg-flags">
      {out.map(f => <span key={f.icon} className={`dg-flag ${f.cls}`} title={f.title}><Icon name={f.icon} size={11} /></span>)}
      {shaky.length > 0 && <span className="dg-shaky" title={t('dag.flag.shaky', { via: shaky.slice(0, 3).join(', ') })} />}
      {node.status === 'locked' && !flags.has('lock_alert') && <span className="dg-flag" title={t('dagx.status.locked')}><Icon name="lock" size={11} /></span>}
    </span>
  );
}

function FreshMark({ level }: { level: Freshness | null }) {
  const L = useDagLabels();
  if (!level || level === 'fresh') return null;
  const s = FRESH_STYLE[level];
  return <span className="dg-fresh" style={{ color: s.color }}><Icon name={s.icon} size={11} />{L.fresh(level)}</span>;
}

function Avatar({ agent }: { agent: 'claude' | 'codex' | null }) {
  const L = useDagLabels();
  if (!agent) return null;
  return <span className={`dg-avatar is-${agent}`} title={L.actor(`agent:${agent}`)}><Icon name="robot" size={12} /></span>;
}

export const CardNodeView = memo(function CardNodeView({ data }: NodeProps<CardNode>) {
  const t = useT();
  const L = useDagLabels();
  const { node, ev, w, h, chip } = data;
  const level = ev?.level ?? null;
  const st = STATUS_STYLE[node.status];
  const title = L.title(node);
  const shape = chip ? 'pill' : shapeOf(node);
  const cls = [
    'dg-node', `shape-${shape}`, `st-${node.status}`, level ? `lvl-${level}` : '', chip ? 'is-chip' : '',
    st.faded ? 'is-faded' : '', data.chosen ? 'is-chosen' : '',
  ].filter(Boolean).join(' ');
  const aria = `${L.kind(node.kind)} ${node.id}: ${title}. ${L.status(node.status)}${level ? `, ${L.fresh(level)}` : ''}`;

  if (chip) {
    return (
      <div className={cls} style={{ width: w, height: h }} aria-label={aria} title={data.reason ? `${title} — ${data.reason}` : title}>
        <ShapeSvg data={data} level={level} />
        <Handles />
        <div className="dg-chip-body">
          {st.icon && <Icon name={st.icon} size={11} />}
          <span className={`ellipsis ${st.strike ? 'is-strike' : ''}`}>{title}</span>
        </div>
      </div>
    );
  }

  if (node.kind === 'reference' || node.kind === 'dataset') {
    return (
      <div className={cls} style={{ width: w, height: h }} aria-label={aria}>
        <ShapeSvg data={data} level={level} />
        <Handles />
        <div className={`dg-rail-body ${node.kind === 'dataset' ? 'is-cyl' : ''}`}>
          <Icon name={KIND_ICON[node.kind]} size={12} />
          <span className={`ellipsis grow ${st.strike ? 'is-strike' : ''}`} title={`${node.id}: ${title}`}>{title}</span>
          {data.version && <span className="faint mono dg-dsver ellipsis" title={data.version}>{data.version}</span>}
          {level && level !== 'fresh' && <span className="dg-dot" style={{ background: FRESH_STYLE[level].color }} title={L.fresh(level)} />}
          <Avatar agent={data.agent} />
        </div>
      </div>
    );
  }

  const cells = data.cells;
  return (
    <div className={cls} style={{ width: w, height: h }} aria-label={aria}>
      <ShapeSvg data={data} level={level} />
      <Handles />
      <div className={`dg-card-body ${shape === 'lozenge' ? 'is-lozenge' : ''}`}>
        <div className="dg-n-top">
          <Icon name={node.kind === 'design' || node.kind === 'module' ? 'layers' : KIND_ICON[node.kind]} size={12} />
          <span className="dg-n-kind ellipsis">{L.kind(node.kind)}{node.purpose ? ` · ${node.purpose}` : ''}</span>
          <span className="grow" />
          <Flags ev={ev} node={node} />
          {(node.head?.rev ?? 0) > 0 && <span className="dg-rev mono" title={node.head.vid}>r{node.head.rev}</span>}
        </div>
        <div className={`dg-n-title ${st.strike ? 'is-strike' : ''}`} title={`${node.id}\n${title}`}>{title}</div>
        {data.thumb && <img className="dg-thumb" src={data.thumb} alt="" loading="lazy" />}
        {cells.length > 0 && <CellGrid cells={cells} evals={ev?.cells ?? {}} />}
        <div className="dg-n-foot">
          <FreshMark level={level} />
          {st.faded && <span className="dg-status-chip">{st.icon && <Icon name={st.icon} size={10} />}{L.status(node.status)}</span>}
          {data.reason && <span className="dg-reason ellipsis" title={data.reason}>{data.reason}</span>}
          {node.status === 'superseded' && node.superseded_by && <span className="dg-reason ellipsis mono">→ {node.superseded_by}</span>}
          {data.stack > 0 && <span className="dg-stack-n faint" title={t('dag.node.stackHint')}>{t('dag.node.stack', { n: data.stack })}</span>}
          <span className="grow" />
          {data.runCount > 0 && <span className="faint num dg-runs" title={t('dag.node.runsHint')}><Icon name="play" size={9} />{data.runCount}</span>}
          <Avatar agent={data.agent} />
        </div>
      </div>
    </div>
  );
});

// ------------------------------------------------------------------ backgrounds

export interface LaneData extends Record<string, unknown> {
  stage: StageKey; count: number; gates: GateStatus[]; alt: boolean;
  onGate: (gate: string) => void;
}
export type LaneNode = Node<LaneData, 'dgLane'>;

export function GateChip({ gate, onClick }: { gate: GateStatus; onClick: () => void }) {
  const t = useT();
  return (
    <button type="button" className={`dg-gate is-${gate.state}`} onClick={onClick} title={t('dag.gate.open', { gate: gate.gate })}>
      <span className="dg-gate-dot" aria-hidden="true" />
      <b className="mono">{gate.gate}</b>
      <span>{t(`dag.gate.state.${gate.state}`)}</span>
    </button>
  );
}

export const LaneNodeView = memo(function LaneNodeView({ data }: NodeProps<LaneNode>) {
  const L = useDagLabels();
  return (
    <div className={`dg-lane ${data.alt ? 'is-alt' : ''} ${data.stage === 'W' ? 'is-w' : ''}`}>
      <div className="dg-lane-head">
        <span className="label">{data.stage}</span>
        <span className="h3 ellipsis">{L.stage(data.stage)}</span>
        <span className="faint num">{data.count}</span>
        <span className="grow" />
        <span className="dg-hit row" style={{ gap: 4 }}>
          {data.gates.map(g => <GateChip key={g.gate} gate={g} onClick={() => data.onGate(g.gate)} />)}
        </span>
      </div>
    </div>
  );
});

export interface RailData extends Record<string, unknown> {
  collapsed: boolean; refs: number; datasets: number; onToggle: () => void;
}
export type RailNode = Node<RailData, 'dgRail'>;

export const RailNodeView = memo(function RailNodeView({ data }: NodeProps<RailNode>) {
  const t = useT();
  return (
    <div className={`dg-rail ${data.collapsed ? 'is-collapsed' : ''}`}>
      <button type="button" className="dg-rail-head dg-hit" onClick={data.onToggle} aria-expanded={!data.collapsed}>
        <Icon name={data.collapsed ? 'chevronRight' : 'chevronDown'} size={12} />
        <span className="label">{t('dag.rail.title')}</span>
        <span className="faint">{t('dag.rail.counts', { refs: data.refs, data: data.datasets })}</span>
      </button>
    </div>
  );
});

export interface GroupData extends Record<string, unknown> {
  id: string; label: string; tried: number; chosen: number; onOpen: (id: string) => void;
}
export type GroupNode = Node<GroupData, 'dgGroup'>;

export const GroupNodeView = memo(function GroupNodeView({ data }: NodeProps<GroupNode>) {
  const t = useT();
  return (
    <div className="dg-group">
      <span className="dg-bracket" aria-hidden="true" />
      <button type="button" className="dg-group-head dg-hit" onClick={() => data.onOpen(data.id)} title={t('dag.group.openHint')}>
        <span className="mono ellipsis">{data.label}</span>
        <span className="dg-group-n">{t('dag.group.count', { tried: data.tried, chosen: data.chosen })}</span>
      </button>
    </div>
  );
});

export const NODE_TYPES = { dgCard: CardNodeView, dgLane: LaneNodeView, dgRail: RailNodeView, dgGroup: GroupNodeView };
