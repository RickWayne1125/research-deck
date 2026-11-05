// Small panel chrome: toasts (applied / sent to the Inbox as a proposal / queued) and the encoding legend.
import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { Icon } from '../../components/icons';
import { IconButton, Menu } from '../../components/ui';
import { useT } from '../../i18n';
import { FRESH_STYLE, STATUS_STYLE, useDagLabels } from '../../dag/encoding';
import type { Freshness, NodeStatus } from '../../dag-types';

export interface Toast { id: number; tone: 'ok' | 'info' | 'warn' | 'accent'; text: ReactNode; action?: { label: string; run: () => void } }

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const n = useRef(0);
  const dismiss = useCallback((id: number) => setToasts(ts => ts.filter(x => x.id !== id)), []);
  const push = useCallback((tst: Omit<Toast, 'id'>, ms = 6000) => {
    const id = ++n.current;
    setToasts(ts => [...ts.slice(-3), { ...tst, id }]);
    if (ms > 0) window.setTimeout(() => dismiss(id), ms);
  }, [dismiss]);
  return useMemo(() => ({ toasts, push, dismiss }), [toasts, push, dismiss]);
}

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  const t = useT();
  if (!toasts.length) return null;
  return (
    <div className="dg-toasts" role="status" aria-live="polite">
      {toasts.map(x => (
        <div key={x.id} className={`dg-toast tone-${x.tone}`}>
          <Icon name={x.tone === 'ok' ? 'check' : x.tone === 'info' ? 'info' : 'warn'} size={14} />
          <span className="grow">{x.text}</span>
          {x.action && <button type="button" className="dg-toast-act" onClick={() => { x.action!.run(); onDismiss(x.id); }}>{x.action.label}</button>}
          <IconButton icon="close" label={t('common.close')} onClick={() => onDismiss(x.id)} />
        </div>
      ))}
    </div>
  );
}

const STATUSES: NodeStatus[] = ['proposed', 'active', 'confirmed', 'locked', 'refuted', 'abandoned', 'superseded'];
const LEVELS: Freshness[] = ['review', 'orphaned', 'pending', 'stale', 'unbuilt', 'broken'];
const EDGES = ['input', 'evidence', 'basis', 'implements', 'describes', 'cites'] as const;

export function Legend() {
  const t = useT();
  const L = useDagLabels();
  return (
    <Menu button={(open, toggle) => <IconButton icon="info" label={t('dag.legend.title')} aria-expanded={open} onClick={toggle} />}>
      {() => (
        <div className="dg-legend">
          <div className="label">{t('dag.legend.status')}</div>
          <div className="dg-legend-grid">
            {STATUSES.map(s => {
              const st = STATUS_STYLE[s];
              return (
                <span key={s} className="dg-legend-item">
                  <span className="dg-legend-sw" style={{ background: st.fill === 'transparent' ? 'var(--surface)' : st.fill, borderColor: st.line, borderStyle: st.dashed ? 'dashed' : st.double ? 'double' : 'solid', borderWidth: st.double ? 3 : 1, opacity: st.faded ? 0.6 : 1 }} />
                  {L.status(s)}
                </span>
              );
            })}
          </div>
          <div className="label">{t('dag.legend.fresh')}</div>
          <div className="dg-legend-grid">
            {LEVELS.map(l => {
              const f = FRESH_STYLE[l];
              return (
                <span key={l} className="dg-legend-item">
                  <span className="dg-legend-ring" style={{ borderColor: f.color, borderStyle: f.dashed ? 'dashed' : 'solid' }}><Icon name={f.icon} size={10} style={{ color: f.color }} /></span>
                  {L.fresh(l)}
                </span>
              );
            })}
          </div>
          <div className="label">{t('dag.legend.edges')}</div>
          <div className="dg-legend-edges">
            {EDGES.map(e => (
              <span key={e} className="dg-legend-item">
                <svg width="34" height="10" aria-hidden="true"><line x1="1" y1="5" x2="33" y2="5" className={`dg-legend-line is-${e}`} /></svg>
                {t(`dag.edge.${e}`)}
              </span>
            ))}
            <span className="dg-legend-item"><svg width="34" height="10" aria-hidden="true"><line x1="1" y1="5" x2="33" y2="5" className="dg-legend-line is-moved" /></svg>{t('dag.legend.moved')}</span>
          </div>
          <div className="label">{t('dag.legend.shapes')}</div>
          <div className="faint dg-legend-note">{t('dag.legend.shapesBody')}</div>
        </div>
      )}
    </Menu>
  );
}
