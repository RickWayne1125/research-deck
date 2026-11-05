// How DAG states look everywhere (docs/DAG.md §8 Encodings): each state has a color token, an icon and a word,
// so meaning survives grayscale. Panels show freshness/status only through these helpers.
import { registerStrings, useI18n } from '../i18n';
import { Icon } from '../components/icons';
import type { DagNode, Freshness, NodeKind, NodeStatus, StageKey } from '../dag-types';
import type { StageId } from '../types';

/** The project's coarse stage (project.yaml `stage`, the top-bar strip) → the DAG stages it covers (docs/DAG.md §1). */
export const STAGE_GROUPS: Record<StageId, StageKey[]> = {
  idea: ['S0', 'S1'], motivation: ['S2', 'S3'], insight: ['S4'], design: ['S5'], evaluation: ['S6'], writing: ['W'],
};

registerStrings({
  zh: {
    'dagx.status.proposed': '提议', 'dagx.status.active': '进行中', 'dagx.status.confirmed': '已确认', 'dagx.status.locked': '已锁定',
    'dagx.status.refuted': '已证伪', 'dagx.status.abandoned': '已放弃', 'dagx.status.superseded': '已取代',
    'dagx.fresh.fresh': '最新', 'dagx.fresh.review': '需复核', 'dagx.fresh.orphaned': '上游失效', 'dagx.fresh.pending': '等待上游',
    'dagx.fresh.unbuilt': '未运行', 'dagx.fresh.stale': '需重跑', 'dagx.fresh.broken': '不成立',
    'dagx.fresh.reusable': '可复用', 'dagx.fresh.unknown': '未知',
    'dagx.kind.problem': '问题', 'dagx.kind.reference': '文献', 'dagx.kind.dataset': '数据集', 'dagx.kind.experiment': '实验',
    'dagx.kind.finding': '发现', 'dagx.kind.gap': '机会/差距', 'dagx.kind.solution': '方案', 'dagx.kind.decision': '决策',
    'dagx.kind.design': '设计', 'dagx.kind.module': '模块', 'dagx.kind.figure': '图', 'dagx.kind.claim': '论点', 'dagx.kind.section': '章节',
    'dagx.stage.S0': '问题定义', 'dagx.stage.S1': '相关工作与基线', 'dagx.stage.S2': '现象刻画', 'dagx.stage.S3': '机会与差距',
    'dagx.stage.S4': '方案探索', 'dagx.stage.S5': '设计与实现', 'dagx.stage.S6': '评估', 'dagx.stage.W': '写作',
    'dagx.lens.tried': '尝试过什么', 'dagx.lens.confirmed': '已确定', 'dagx.lens.revise': '需回滚或修改', 'dagx.lens.rerun': '需重跑',
    'dagx.actor.human': '你', 'dagx.actor.claude': 'Claude', 'dagx.actor.codex': 'Codex', 'dagx.actor.system': '系统',
  },
  en: {
    'dagx.status.proposed': 'Proposed', 'dagx.status.active': 'Active', 'dagx.status.confirmed': 'Confirmed', 'dagx.status.locked': 'Locked',
    'dagx.status.refuted': 'Refuted', 'dagx.status.abandoned': 'Abandoned', 'dagx.status.superseded': 'Superseded',
    'dagx.fresh.fresh': 'Fresh', 'dagx.fresh.review': 'Review', 'dagx.fresh.orphaned': 'Orphaned', 'dagx.fresh.pending': 'Pending',
    'dagx.fresh.unbuilt': 'Not run', 'dagx.fresh.stale': 'Rerun', 'dagx.fresh.broken': 'Broken',
    'dagx.fresh.reusable': 'Reusable', 'dagx.fresh.unknown': 'Unknown',
    'dagx.kind.problem': 'Problem', 'dagx.kind.reference': 'Reference', 'dagx.kind.dataset': 'Dataset', 'dagx.kind.experiment': 'Experiment',
    'dagx.kind.finding': 'Finding', 'dagx.kind.gap': 'Gap', 'dagx.kind.solution': 'Solution', 'dagx.kind.decision': 'Decision',
    'dagx.kind.design': 'Design', 'dagx.kind.module': 'Module', 'dagx.kind.figure': 'Figure', 'dagx.kind.claim': 'Claim', 'dagx.kind.section': 'Section',
    'dagx.stage.S0': 'Frame', 'dagx.stage.S1': 'Landscape & baselines', 'dagx.stage.S2': 'Characterize', 'dagx.stage.S3': 'Opportunity',
    'dagx.stage.S4': 'Solutions', 'dagx.stage.S5': 'Design & implementation', 'dagx.stage.S6': 'Evaluation', 'dagx.stage.W': 'Writing',
    'dagx.lens.tried': 'Tried', 'dagx.lens.confirmed': 'Confirmed', 'dagx.lens.revise': 'Revise / roll back', 'dagx.lens.rerun': 'Rerun',
    'dagx.actor.human': 'You', 'dagx.actor.claude': 'Claude', 'dagx.actor.codex': 'Codex', 'dagx.actor.system': 'System',
  },
});

/** Status → fill/border tokens and icon (§8: fill and border = status). */
export const STATUS_STYLE: Record<NodeStatus, { fill: string; line: string; dashed?: boolean; double?: boolean; faded?: boolean; strike?: boolean; icon?: string }> = {
  proposed: { fill: 'transparent', line: 'var(--rule-strong)', dashed: true },
  active: { fill: 'var(--process)', line: 'var(--process-line)' },
  confirmed: { fill: 'var(--data)', line: 'var(--data-line)', icon: 'check' },
  locked: { fill: 'var(--data)', line: 'var(--data-line)', double: true, icon: 'lock' },
  refuted: { fill: 'var(--neutral)', line: 'var(--neutral-line)', faded: true, strike: true, icon: 'close' },
  abandoned: { fill: 'var(--neutral)', line: 'var(--neutral-line)', faded: true, dashed: true, icon: 'minus' },
  superseded: { fill: 'var(--neutral)', line: 'var(--neutral-line)', faded: true, icon: 'chevronRight' },
};

/** Freshness → ring color, icon and dashing (§8: ring and badge = freshness). fresh has no ring. */
export const FRESH_STYLE: Record<Freshness | 'reusable' | 'unknown', { color: string; wash: string; icon: string; dashed?: boolean }> = {
  fresh: { color: 'var(--ok)', wash: 'var(--ok-wash)', icon: 'check' },
  review: { color: 'var(--warn)', wash: 'var(--warn-wash)', icon: 'warn' },
  orphaned: { color: 'var(--emphasis-line)', wash: 'var(--emphasis)', icon: 'unlink' },
  pending: { color: 'var(--stale)', wash: 'var(--stale-wash)', icon: 'hourglass', dashed: true },
  unbuilt: { color: 'var(--faint)', wash: 'var(--plate)', icon: 'play', dashed: true },
  stale: { color: 'var(--stale)', wash: 'var(--stale-wash)', icon: 'refresh' },
  broken: { color: 'var(--accent)', wash: 'var(--accent-wash)', icon: 'close' },
  reusable: { color: 'var(--info)', wash: 'var(--info-wash)', icon: 'history' },
  unknown: { color: 'var(--faint)', wash: 'var(--plate)', icon: 'info', dashed: true },
};

export const KIND_ICON: Record<NodeKind, string> = {
  problem: 'info', reference: 'file', dataset: 'layers', experiment: 'experiments', finding: 'search', gap: 'diff',
  solution: 'sparkle', decision: 'branch', design: 'layers', module: 'coding', figure: 'image', claim: 'writing', section: 'file',
};

/** "agent:claude:46e445" → 'claude'; "human:alice" → 'human'. */
export function actorKind(by: string | undefined | null): 'human' | 'claude' | 'codex' | 'system' {
  if (!by) return 'system';
  if (by.startsWith('agent:claude')) return 'claude';
  if (by.startsWith('agent:codex')) return 'codex';
  if (by.startsWith('human')) return 'human';
  return 'system';
}

export function useDagLabels() {
  const { t, lang } = useI18n();
  return {
    status: (s: NodeStatus) => t(`dagx.status.${s}`),
    fresh: (f: Freshness | 'reusable' | 'unknown') => t(`dagx.fresh.${f}`),
    kind: (k: NodeKind) => t(`dagx.kind.${k}`),
    stage: (s: StageKey) => t(`dagx.stage.${s}`),
    lens: (l: 'tried' | 'confirmed' | 'revise' | 'rerun') => t(`dagx.lens.${l}`),
    actor: (by: string | undefined | null) => t(`dagx.actor.${actorKind(by)}`),
    /** The node's title in the UI language, falling back to the other language, then the id. */
    title: (n: Pick<DagNode, 'title' | 'id'>) => (lang === 'zh' ? n.title.zh || n.title.en : n.title.en || n.title.zh) || n.id,
  };
}

export function StatusBadge({ status }: { status: NodeStatus }) {
  const L = useDagLabels();
  const s = STATUS_STYLE[status];
  return (
    <span className="badge" style={{ background: s.fill === 'transparent' ? 'var(--surface)' : s.fill, color: 'var(--ink)', border: `1px ${s.dashed ? 'dashed' : 'solid'} ${s.line}`, opacity: s.faded ? 0.75 : 1 }}>
      {s.icon && <Icon name={s.icon} size={11} />}{L.status(status)}
    </span>
  );
}

export function FreshBadge({ level, title }: { level: Freshness | 'reusable' | 'unknown' | null | undefined; title?: string }) {
  const L = useDagLabels();
  if (!level) return null;
  const s = FRESH_STYLE[level];
  return (
    <span className="badge" title={title} style={{ background: s.wash, color: s.color, border: `1px ${s.dashed ? 'dashed' : 'solid'} color-mix(in srgb, ${s.color} 45%, transparent)` }}>
      <Icon name={s.icon} size={11} />{L.fresh(level)}
    </span>
  );
}
