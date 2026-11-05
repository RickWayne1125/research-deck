// The empty state of a project without a DAG: write the problem, which becomes prob.<slug> (status active, S0), the
// root of the pipeline. A human may create active nodes directly (docs/DAG.md §2.4); agents would only propose.
import { useState } from 'react';
import { Button } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useApp } from '../../state/app';
import { useI18n } from '../../i18n';
import { dagApi } from '../../dag/api';
import { errorMessage } from './parts';

/** ASCII slug for a node id; Chinese titles have none, so the caller falls back to the project id. */
export function slugify(s: string): string {
  return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9.]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').replace(/-{2,}/g, '-').slice(0, 40).replace(/[-.]+$/, '');
}
const SLUG_RE = /^[a-z0-9][a-z0-9.-]*$/;

export function StartCard({ pid, onCreated }: { pid: string; onCreated: () => void }) {
  const { project, askAgent } = useApp();
  const { t, lang } = useI18n();
  const [title, setTitle] = useState('');
  const [statement, setStatement] = useState('');
  const [slug, setSlug] = useState<string | null>(null);   // null: derived from the title
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const auto = slugify(title) || slugify(project?.id ?? '') || 'main';
  const effective = slug ?? auto;
  const slugOk = SLUG_RE.test(effective);
  const ready = title.trim() && statement.trim() && slugOk && !busy;

  const create = async () => {
    if (!ready) return;
    setBusy(true); setError(null); setNote(null);
    const node = {
      id: `prob.${effective}`, kind: 'problem', stage: 'S0', status: 'active',
      title: { [lang]: title.trim() },
      facets: { statement: { type: 'prose', value: statement.trim() } },
      edges: [],
    };
    try {
      const res = await dagApi.ops(pid, [{ op: 'create', node }]);
      if (!res.applied && res.proposal) setNote(t('ov.start.proposed'));
      onCreated();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };

  return (
    <section className="card ov-start" aria-labelledby="ov-start-title">
      <div className="ov-start-intro">
        <span className="label">S0 · {t('dagx.stage.S0')}</span>
        <h2 id="ov-start-title" className="h2">{t('ov.start.title')}</h2>
        <p className="muted">{t('ov.start.body')}</p>
      </div>
      <div className="ov-start-form">
        <label className="field">
          <span className="label">{t('ov.start.titleField')}</span>
          <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder={t('ov.start.titlePh')} />
        </label>
        <label className="field">
          <span className="label">{t('ov.start.statement')}</span>
          <textarea className="textarea" rows={3} value={statement} onChange={e => setStatement(e.target.value)} placeholder={t('ov.start.statementPh')}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) create(); }} />
        </label>
        <label className="field">
          <span className="label">{t('ov.start.id')}</span>
          <span className="ov-start-id">
            <span className="mono faint">prob.</span>
            <input className="input mono" value={effective} onChange={e => setSlug(e.target.value.toLowerCase())} aria-invalid={!slugOk} spellCheck={false} />
          </span>
          {!slugOk && <span className="ov-xs" style={{ color: 'var(--accent)' }}>{t('ov.start.idInvalid')}</span>}
        </label>
        {error && <div className="notice accent ov-small" role="alert">{t('ov.start.failed', { msg: error })}</div>}
        {note && <div className="notice ov-small">{note}</div>}
        <div className="row wrap">
          <Button variant="accent" icon="plus" disabled={!ready} onClick={create}>{t('ov.start.create')}</Button>
          <Button variant="ghost" icon="sparkle" onClick={() => askAgent(t('ov.start.askPrompt'), {})}>{t('ov.start.ask')}</Button>
          <span className="grow" />
          <span className="faint ov-xs row" style={{ gap: 4 }}><Icon name="info" size={12} />S0 → S1 → … → S6 · W</span>
        </div>
      </div>
    </section>
  );
}
