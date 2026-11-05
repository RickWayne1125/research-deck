// Settings → New projects: the default folder, git init, the survey's sources, size and PDF folder, and how the map
// grows step by step. Machine-wide (~/.research-deck/settings.json); every change is saved at once (text fields on
// Enter or when they lose focus).
import { useEffect, useState } from 'react';
import { Button, ErrorNote, Spinner } from '../components/ui';
import { useT } from '../i18n';
import { SOURCES, SOURCE_LABEL, startApi, type NewProjectSettings, type StageMode } from './api';
import './i18n';
import './start.css';

const COUNTS = [8, 15, 30];
const MODES: StageMode[] = ['strict', 'ahead', 'free'];

export function NewProjectSettingsSection() {
  const t = useT();
  const [s, setS] = useState<NewProjectSettings | null>(null);
  const [dir, setDir] = useState('');
  const [papers, setPapers] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const take = (v: NewProjectSettings) => { setS(v); setDir(v.dir); setPapers(v.survey.papers_dir); };
  useEffect(() => { startApi.settings().then(take).catch(e => setError(String((e as Error).message))); }, []);
  useEffect(() => {
    if (!saved) return;
    const id = window.setTimeout(() => setSaved(false), 1500);
    return () => window.clearTimeout(id);
  }, [saved]);

  const save = async (change: Parameters<typeof startApi.saveSettings>[0]) => {
    setError(null);
    try { take(await startApi.saveSettings(change)); setSaved(true); }
    catch (e) { setError(String((e as Error).message)); if (s) take(s); }
  };
  if (!s) return error ? <ErrorNote error={error} /> : <div className="empty"><Spinner /></div>;

  const counts = [...new Set([...COUNTS, s.survey.count])].sort((a, b) => a - b);
  const toggleSource = (src: (typeof SOURCES)[number], on: boolean) =>
    save({ survey: { sources: SOURCES.filter(x => (x === src ? on : s.survey.sources.includes(x))) } });
  return (
    <dl className="kv st-kv np-st">
      <dt>{t('np.st.dir')}</dt>
      <dd className="col np-st-col">
        <div className="row wrap np-st-dir" style={{ width: '100%' }}>
          <input className="input mono" value={dir} aria-label={t('np.st.dir')} onChange={e => setDir(e.target.value)}
            onBlur={() => dir.trim() !== s.dir && save({ dir: dir.trim() || null })}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
          <Button size="sm" disabled={s.dir === s.default_dir} onClick={() => save({ dir: null })}>{t('np.st.reset')}</Button>
        </div>
        <span className="st-hint st-flush">{t('np.st.dirHint')}</span>
        {s.dir_expanded !== s.dir && <span className="st-hint st-flush mono">{t('np.st.dirNow', { path: s.dir_expanded })}</span>}
      </dd>

      <dt>{t('np.st.onCreate')}</dt>
      <dd>
        <label className="row np-check"><input type="checkbox" checked={s.git_init} onChange={e => save({ git_init: e.target.checked })} /><span>{t('np.st.git')}</span></label>
      </dd>

      <dt>{t('np.st.survey')}</dt>
      <dd className="col np-st-col">
        <div className="row wrap" style={{ gap: '6px 16px' }}>
          {SOURCES.map(src => (
            <label key={src} className="row np-check">
              <input type="checkbox" checked={s.survey.sources.includes(src)} disabled={s.survey.sources.length === 1 && s.survey.sources.includes(src)}
                onChange={e => toggleSource(src, e.target.checked)} />
              <span>{SOURCE_LABEL[src]}</span>
            </label>
          ))}
        </div>
        <div className="row wrap" style={{ gap: 8 }}>
          <span>{t('np.st.keep')}</span>
          <select className="input np-count" value={s.survey.count} aria-label={t('np.survey.countLabel')} onChange={e => save({ survey: { count: Number(e.target.value) } })}>
            {counts.map(n => <option key={n} value={n}>{t('np.survey.count', { n })}</option>)}
          </select>
          <span>{t('np.st.keepTail')}</span>
        </div>
        <label className="row np-check" style={{ alignItems: 'center' }}>
          <input type="checkbox" checked={s.survey.download_pdfs} onChange={e => save({ survey: { download_pdfs: e.target.checked } })} />
          <span>{t('np.st.pdfs')}</span>
          <input className="input mono np-st-pdfdir" value={papers} aria-label={t('np.st.pdfDir')} onChange={e => setPapers(e.target.value)}
            onBlur={() => papers.trim() !== s.survey.papers_dir && save({ survey: { papers_dir: papers.trim() } })}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
        </label>
        <span className="st-hint st-flush">{t('np.st.paywall')}</span>
      </dd>

      <dt>{t('np.st.stages')}</dt>
      <dd className="col np-st-col">
        {MODES.map(m => (
          <label key={m} className="row np-check">
            <input type="radio" name="np-st-stage" checked={s.stage_mode === m} onChange={() => save({ stage_mode: m })} />
            <span>{t(`np.st.${m}`)}</span>
          </label>
        ))}
        <span className="st-hint st-flush">{t('np.st.stagesHint')}</span>
      </dd>

      {(error || saved) && (
        <>
          <dt />
          <dd>{error ? <ErrorNote error={error} /> : <span className="faint st-hint st-flush" role="status">{t('np.st.saved')}</span>}</dd>
        </>
      )}
    </dl>
  );
}
