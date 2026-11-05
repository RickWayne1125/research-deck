// The last events of the DAG log (GET /dag/timeline), colored by actor: you, Claude, Codex or the system.
import { useApp } from '../../state/app';
import { useRelTime, useT } from '../../i18n';
import { actorKind, useDagLabels } from '../../dag/encoding';
import type { DagEvent } from '../../dag-types';
import { tOr, type NodeIndex } from './parts';

export function Activity({ events, index }: { events: DagEvent[]; index: NodeIndex }) {
  const t = useT();
  return (
    <section className="card ov-activity" aria-label={t('ov.act.title')}>
      <div className="card-head"><h2 className="h3 grow">{t('ov.act.title')}</h2></div>
      {events.length === 0 ? <div className="card-body muted ov-small">{t('ov.act.empty')}</div> : (
        <ol className="ov-act-list">{events.map((e, i) => <Row key={e.e ?? i} e={e} index={index} />)}</ol>
      )}
    </section>
  );
}

function Row({ e, index }: { e: DagEvent; index: NodeIndex }) {
  const { navigate } = useApp();
  const t = useT();
  const L = useDagLabels();
  const rel = useRelTime();
  const kind = actorKind(e.by);
  const verb = e.op === 'decision' && e.kind
    ? tOr(t, `ov.decision.${e.kind}`, tOr(t, 'ov.op.decision', e.op))
    : tOr(t, `ov.op.${e.op}`, String(e.op ?? '').replace(/_/g, ' '));
  const node = e.node ? index.node(e.node) : undefined;
  const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
  const target = node ? L.title(node) : e.node ?? str(e.gate) ?? str(e.name) ?? str(e.proposal) ?? str(e.via) ?? str(e.file) ?? '';
  const to = typeof e.to === 'string' && ['proposed', 'active', 'confirmed', 'locked', 'refuted', 'abandoned', 'superseded'].includes(e.to)
    ? L.status(e.to as Parameters<typeof L.status>[0]) : null;
  const detail = [e.cell, to ? `→ ${to}` : null, e.summary ?? e.reason].filter(Boolean).join(' · ');
  const body = (
    <>
      <span className={`ov-act-dot ov-actor-${kind}`} aria-hidden="true" />
      <span className="ov-act-text">
        <span className={`ov-act-who ov-actor-${kind}`}>{L.actor(e.by)}</span>{' '}
        <span className="muted">{verb}</span>{' '}
        {target && <span className="ov-act-target">{target}</span>}
        {detail && <span className="ov-act-detail faint">{detail}</span>}
      </span>
      <time className="faint num ov-xs ov-nowrap" dateTime={e.at} title={e.at}>{rel(e.at)}</time>
    </>
  );
  return (
    <li>
      {e.node
        ? <button type="button" className="ov-act-row" title={`${e.node}${e.by ? ` · ${e.by}` : ''}`} onClick={() => navigate('dag', e.node!)}>{body}</button>
        : <div className="ov-act-row" title={e.by}>{body}</div>}
    </li>
  );
}
