// Smaller pieces of the writing panel: the documents drawer, the preview, the claim card of the claims gutter.
import { memo, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useT, useRelTime } from '../../i18n';
import { Empty, IconButton, Spinner } from '../../components/ui';
import { ResizeHandle, type Resizable } from '../../components/resize';
import { Icon } from '../../components/icons';
import { Markdown } from '../../components/Markdown';
import { FreshBadge, useDagLabels } from '../../dag/encoding';
import type { WritingDoc } from '../../types';
import type { DocClaim } from './api';
import { renderTex } from './texPreview';

export function DocsDrawer({ docs, loading, current, onOpen, onRefresh, floating, width }: {
  docs: WritingDoc[] | null; loading: boolean; current: string | null; onOpen: (path: string) => void; onRefresh: () => void; floating?: boolean;
  width?: Resizable;
}) {
  const t = useT();
  const rel = useRelTime();
  const [q, setQ] = useState('');
  const shown = (docs ?? []).filter(d => !q || `${d.title} ${d.path}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <nav id="wr-docs" className={`wr-docs${floating ? ' floating' : ''}`} aria-label={t('wr.docs')}>
      {width && <ResizeHandle pane={width} edge="right" label={t('wr.docs.resize')} controls="wr-docs" />}
      <div className="wr-docs-head">
        <span className="label grow">{t('wr.docs')}</span>
        <IconButton icon="refresh" label={t('wr.docs.refresh')} onClick={onRefresh} />
      </div>
      {(docs?.length ?? 0) > 8 && (
        <div className="wr-docs-filter"><input className="input" value={q} onChange={e => setQ(e.target.value)} placeholder={t('wr.docs.filter')} aria-label={t('wr.docs.filter')} /></div>
      )}
      <div className="wr-docs-list">
        {loading && !docs ? <div className="empty"><Spinner /></div>
          : !docs?.length ? <p className="wr-empty">{t('wr.docs.empty')}</p>
            : shown.map(d => (
              <button key={d.path} type="button" className={`wr-doc${d.path === current ? ' active' : ''}`} onClick={() => onOpen(d.path)} title={d.path}>
                <span className="wr-doc-title ellipsis">{d.title}</span>
                <span className="wr-doc-path mono ellipsis">{d.path}</span>
                <span className="wr-doc-meta">
                  <span className="badge">{d.kind.toUpperCase()}</span>
                  <span className="num">{t('wr.docs.words', { n: d.words.toLocaleString() })}</span>
                  <span className="faint">{rel(d.updated_at)}</span>
                  {d.stale_claims > 0
                    ? <span className="badge warn" title={t('wr.docs.stale', { n: d.stale_claims })}><Icon name="warn" size={11} />{d.stale_claims}</span>
                    : d.claims > 0 ? <span className="badge ok" title={t('wr.docs.claims', { n: d.claims })}><Icon name="check" size={11} />{d.claims}</span> : null}
                </span>
              </button>
            ))}
      </div>
    </nav>
  );
}

export const Preview = memo(function Preview({ text, kind }: { text: string; kind: 'tex' | 'md' }) {
  const t = useT();
  const html = useMemo(() => kind === 'tex' ? renderTex(text, {
    abstract: t('wr.pv.abstract'), figure: t('wr.pv.figure'), table: t('wr.pv.table'), algorithm: t('wr.pv.algorithm'),
    input: t('wr.pv.input'), references: t('wr.pv.references'), code: t('wr.pv.code'),
  }) : '', [text, kind, t]);
  if (kind === 'md') return <div className="wr-preview"><Markdown text={text} /></div>;
  return (
    <div className="wr-preview">
      <p className="wr-preview-note faint">{t('wr.preview.note')}</p>
      <div className="wr-pv md" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
});

export function ClaimCard({ claims, rect, onOpen, onEnter, onLeave }: {
  claims: DocClaim[]; rect: DOMRect; onOpen: (id: string) => void; onEnter: () => void; onLeave: () => void;
}) {
  const t = useT();
  const L = useDagLabels();
  const ref = useRef<HTMLDivElement>(null);
  // Below the marked line (above it near the bottom of the window), so the claim's own text stays readable.
  const [pos, setPos] = useState({ top: rect.bottom + 8, left: rect.left });
  useLayoutEffect(() => {
    const h = ref.current?.offsetHeight ?? 120;
    const below = rect.bottom + 8;
    const top = below + h > window.innerHeight - 8 && rect.top - h - 8 > 8 ? rect.top - h - 8 : below;
    setPos({ top: Math.max(8, top), left: Math.max(8, Math.min(rect.left - 4, window.innerWidth - 348)) });
  }, [rect, claims]);
  return (
    <div ref={ref} className="wr-card wr-claim-card" role="dialog" style={{ top: pos.top, left: pos.left }} onMouseEnter={onEnter} onMouseLeave={onLeave}>
      {claims.map(c => {
        const values = Object.entries(c.values ?? {});
        const section = c.kind === 'section' || c.id.startsWith('sec.');
        return (
          <div key={c.id} className="wr-claim">
            <div className="row">
              <span className="badge">{section ? t('wr.claims.section') : L.kind('claim')}</span>
              <FreshBadge level={c.freshness} />
              <span className="grow" />
              <button type="button" className="wr-link mono" onClick={() => onOpen(c.id)}>{c.id}</button>
            </div>
            <div className="wr-claim-label">{c.label}</div>
            {c.text && c.text !== c.label && <p className="wr-claim-text">{c.text}</p>}
            {values.length > 0 && (
              <dl className="kv wr-small">
                <dt>{t('wr.claims.values')}</dt>
                <dd className="mono">{values.map(([k, v]) => `${k} = ${typeof v === 'number' ? v : JSON.stringify(v)}`).join(' · ')}</dd>
              </dl>
            )}
            {c.evidence.length > 0 && (
              <div className="row wrap wr-small">
                <span className="faint">{t('wr.claims.evidence')}</span>
                {c.evidence.map(e => <button key={e} type="button" className="wr-link mono" onClick={() => onOpen(e)}>{e}</button>)}
              </div>
            )}
            <button type="button" className="wr-link" onClick={() => onOpen(c.id)}><Icon name="dag" size={12} /> {t('wr.claims.open')}</button>
          </div>
        );
      })}
    </div>
  );
}

export function NoDoc() {
  const t = useT();
  return <Empty icon="writing" title={t('wr.noDoc.title')}>{t('wr.noDoc.body')}</Empty>;
}
