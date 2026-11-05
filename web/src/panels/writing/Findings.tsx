// A suggestion over a marked passage: what changes, why, accept / reject, and "why?" after a rejection.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { diffWordsWithSpace } from 'diff';
import { useT } from '../../i18n';
import { Button, IconButton, Kbd } from '../../components/ui';
import { ResizeHandle, type Resizable } from '../../components/resize';
import { Icon } from '../../components/icons';
import { REVIEW_PASSES, type ReviewPass } from '../../types';
import type { WrFinding, WrReview } from './api';
import { AUTO_FIX, KEYS, LESS_CERTAIN, PASS_TINT } from './text';

export const WHY_KEYS = ['wr.why.1', 'wr.why.2', 'wr.why.3', 'wr.why.4'];

const tintStyle = (pass: ReviewPass): CSSProperties => ({
  ['--look' as string]: PASS_TINT[pass].line, ['--look-wash' as string]: PASS_TINT[pass].wash, ['--look-ink' as string]: PASS_TINT[pass].ink,
});

/** quote → replacement as an inline word diff, or a split before/after for long rewrites. */
function Change({ quote, replacement }: { quote: string; replacement: string | null }) {
  const t = useT();
  if (replacement === null) return <p className="wr-diff wr-diff-context">{quote}</p>;
  if (replacement === '') return <p className="wr-diff"><del>{quote}</del> <span className="faint">· {t('wr.finding.delete')}</span></p>;
  if (quote.length > 90 || replacement.length > 90) {
    return <div className="wr-diff wr-diff-split"><del>{quote}</del><ins>{replacement}</ins></div>;
  }
  const parts = diffWordsWithSpace(quote, replacement);
  const changed = parts.filter(p => p.added || p.removed).length;
  const kept = parts.some(p => !p.added && !p.removed && p.value.trim());
  // Nothing in common (one word for another) or too many pieces: before → after reads better than an interleaved diff.
  if (!kept || changed > 6) return <p className="wr-diff"><del>{quote}</del><span className="wr-arrow">→</span><ins>{replacement}</ins></p>;
  return (
    <p className="wr-diff">
      {parts.map((p, i) => p.added ? <ins key={i}>{p.value}</ins> : p.removed ? <del key={i}>{p.value}</del> : <span key={i}>{p.value}</span>)}
    </p>
  );
}

export interface FindingActions {
  accept: (f: WrFinding) => void;
  reject: (f: WrFinding) => void;                       // opens the "why?" step
  why: (f: WrFinding, reason: string | null) => void;   // null: reject without a reason
  cancelWhy: () => void;
  reopen: (f: WrFinding) => void;
  jumpLine: (line: number) => void;
  openNode: (id: string) => void;
}

export function FindingBody({ f, keys, why, stale, actions }: { f: WrFinding; keys?: boolean; why?: boolean; stale?: boolean; actions: FindingActions }) {
  const t = useT();
  const [other, setOther] = useState('');
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (why) { setOther(''); if (!keys) input.current?.focus(); } }, [why, keys]);
  const advisory = f.replacement === null;
  return (
    <div className="wr-fbody" style={tintStyle(f.pass)}>
      <div className="wr-fhead">
        <span className="wr-chip">{t(`wr.pass.${f.pass}`)}</span>
        <span className="wr-kind">{t(`wr.kind.${f.kind}`)}</span>
        {f.confidence < LESS_CERTAIN && <span className="wr-kind faint">{t('wr.finding.lessCertain')}</span>}
        <span className="grow" />
        {f.line != null && <button type="button" className="wr-where" onClick={() => actions.jumpLine(f.line!)}>{t('wr.finding.line', { n: f.line })}</button>}
      </div>
      <Change quote={f.quote} replacement={f.replacement} />
      {f.reason && <p className="wr-why-text">{f.reason}</p>}
      {advisory && <p className="wr-advisory">{t('wr.finding.advisory')}</p>}
      {(f.related?.length || f.evidence_node) ? (
        <p className="wr-related">
          {f.related?.map((r, i) => (
            <button key={i} type="button" className="wr-link" onClick={() => r.line && actions.jumpLine(r.line)}>
              {t('wr.finding.related')} {r.line ? t('wr.finding.line', { n: r.line }) : ''} “{r.quote.length > 40 ? r.quote.slice(0, 39) + '…' : r.quote}”
            </button>
          ))}
          {f.evidence_node && (
            <button type="button" className="wr-link mono" onClick={() => actions.openNode(f.evidence_node!)}>
              <Icon name="dag" size={12} /> {f.evidence_node}
            </button>
          )}
        </p>
      ) : null}
      {stale ? <p className="wr-advisory">{t('wr.finding.stale')}</p>
        : f.status !== 'open' ? (
          <div className="wr-acts">
            <span className={`badge ${f.status === 'accepted' ? 'ok' : ''}`}>{t(f.status === 'accepted' ? 'wr.finding.accepted' : 'wr.finding.rejected')}</span>
            {f.reject_reason && <span className="faint wr-small">“{f.reject_reason}”</span>}
            <span className="grow" />
            <button type="button" className="wr-link" onClick={() => actions.reopen(f)}>{t('wr.finding.reopen')}</button>
          </div>
        ) : why ? (
          <div className="wr-whys">
            <p className="wr-ask">{t('wr.why.ask')}{keys && <> <Kbd>↵</Kbd> {t('wr.why.skip')}</>}</p>
            <div className="wr-why-opts">
              {WHY_KEYS.map((k, i) => (
                <button key={k} type="button" onClick={() => actions.why(f, t(k))}>{keys && <Kbd>{i + 1}</Kbd>} {t(k)}</button>
              ))}
            </div>
            <input ref={input} className="input" value={other} placeholder={t('wr.why.other')} aria-label={t('wr.why.other')}
              onChange={e => setOther(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); actions.why(f, other.trim() || null); }
                if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); actions.cancelWhy(); }
              }} />
            <div className="wr-acts">
              <span className="grow" />
              <Button size="sm" variant="ghost" onClick={() => actions.why(f, other.trim() || null)}>{t('wr.why.skip')}</Button>
            </div>
          </div>
        ) : (
          <div className="wr-acts">
            <Button size="sm" variant="primary" onClick={() => actions.accept(f)}>
              {t(advisory ? 'wr.finding.ack' : 'wr.finding.accept')}{keys && <Kbd>↵</Kbd>}
            </Button>
            <Button size="sm" onClick={() => actions.reject(f)}>
              {t(advisory ? 'wr.finding.notIssue' : 'wr.finding.reject')}{keys && <Kbd>⌫</Kbd>}
            </Button>
          </div>
        )}
    </div>
  );
}

/** The card over the text: below the marked words (above them near the bottom of the window). */
export function FindingCard({ f, rect, keys, why, actions, onEnter, onLeave, onClose }: {
  f: WrFinding; rect: DOMRect; keys: boolean; why: boolean; actions: FindingActions;
  onEnter: () => void; onLeave: () => void; onClose: () => void;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: rect.bottom + 6, left: rect.left });
  useLayoutEffect(() => {
    const h = ref.current?.offsetHeight ?? 160;
    const w = ref.current?.offsetWidth ?? 340;
    const below = rect.bottom + 6;
    const top = below + h > window.innerHeight - 8 && rect.top - h - 6 > 8 ? rect.top - h - 6 : below;
    setPos({ top: Math.max(8, top), left: Math.min(Math.max(8, rect.left - 12), window.innerWidth - w - 8) });
  }, [rect, f.id, why]);
  return (
    <div ref={ref} className="wr-card" role="dialog" aria-label={t(`wr.pass.${f.pass}`)} style={{ ...tintStyle(f.pass), top: pos.top, left: pos.left }}
      onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <div className="wr-card-close"><IconButton icon="close" label={t('wr.card.close')} onClick={onClose} /></div>
      <FindingBody f={f} keys={keys} why={why} actions={actions} />
    </div>
  );
}
