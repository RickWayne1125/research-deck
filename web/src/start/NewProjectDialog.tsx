// New project from an idea (project menu → New from an idea…): the idea as text and/or a file, a name taken from it,
// where the folder goes (the default folder from Settings → New projects, or a folder of one's choice) and whether
// the early survey runs right after. POST /api/projects/new does the rest (start/create.py).
import { useEffect, useRef, useState, type DragEvent } from 'react';
import { Button, Dialog, Spinner } from '../components/ui';
import { Icon } from '../components/icons';
import { useApp } from '../state/app';
import { useT } from '../i18n';
import { SOURCE_LABEL, fileBase64, folderName, nameFromIdea, startApi, type NewProjectSettings } from './api';
import './i18n';
import './start.css';

const MAX_UPLOAD = 20 * 1024 * 1024;
const TYPES = ['.md', '.txt', '.pdf'];
const COUNTS = [8, 15, 30];

export function NewProjectDialog({ onClose }: { onClose: () => void }) {
  const { reloadProjects, navigate } = useApp();
  const t = useT();
  const [cfg, setCfg] = useState<NewProjectSettings | null>(null);
  const [idea, setIdea] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [nameEdited, setNameEdited] = useState(false);
  const [where, setWhere] = useState<'default' | 'custom'>('default');
  const [folder, setFolder] = useState('');
  const [survey, setSurvey] = useState(true);
  const [count, setCount] = useState(15);
  const [pdfs, setPdfs] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    startApi.settings().then(s => { setCfg(s); setCount(s.survey.count); setPdfs(s.survey.download_pdfs); })
      .catch(e => setError(String((e as Error).message)));
  }, []);
  // The name follows the idea (or the file's name) until it is edited.
  useEffect(() => {
    if (nameEdited) return;
    setName(nameFromIdea(idea) || (file ? file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ') : ''));
  }, [idea, file, nameEdited]);

  const pick = (f: File | null | undefined) => {
    setFileError(null);
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
    if (!TYPES.includes(ext)) { setFileError(t('np.fileType')); return; }
    if (f.size > MAX_UPLOAD) { setFileError(t('np.fileTooBig')); return; }
    setFile(f);
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); };

  const base = cfg ? cfg.dir.replace(/[\\/]+$/, '') : '';
  const sep = cfg && /^%|^[A-Za-z]:\\/.test(cfg.dir) ? '\\' : '/';
  const target = `${base}${sep}${folderName(name)}`;
  const ready = !!name.trim() && (!!idea.trim() || !!file) && (where === 'default' || !!folder.trim()) && !busy && !!cfg;
  const papers = cfg?.survey.papers_dir ?? 'papers';
  const sources = (cfg?.survey.sources ?? []).map(s => SOURCE_LABEL[s]).join(' · ');
  const counts = [...new Set([...COUNTS, cfg?.survey.count ?? 15])].sort((a, b) => a - b);

  const create = async () => {
    if (!ready) return;
    setBusy(true); setError(null);
    try {
      const res = await startApi.create({
        name: name.trim(), idea,
        file: file ? { name: file.name, content_base64: await fileBase64(file) } : null,
        folder: where === 'custom' ? folder.trim() : null,
        survey: { enabled: survey, count, download_pdfs: pdfs },
      });
      await reloadProjects();
      navigate('overview', null, res.project.id);
      onClose();
    } catch (e) { setError(String((e as Error).message)); setBusy(false); }
  };

  return (
    <Dialog title={t('np.title')} onClose={onClose} width={680} footer={
      <>
        <span className="faint np-writes">{t('np.writes')} <span className="mono">notes/idea.md{survey ? ` · ${papers}/` : ''} · .research/</span></span>
        <span className="grow" />
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="primary" onClick={create} disabled={!ready}>{busy && <Spinner />}{t(survey ? 'np.create' : 'np.createOnly')}</Button>
      </>
    }>
      <div className="col np-body">
        <div className={`field np-idea${dragging ? ' dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)} onDrop={onDrop}>
          <label className="label" htmlFor="np-idea">{t('np.idea')}</label>
          <textarea id="np-idea" className="textarea" rows={6} value={idea} autoFocus placeholder={t('np.ideaPh')}
            onChange={e => setIdea(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) create(); }} />
          <div className="np-drop">
            <Icon name="file" />
            {file ? (
              <span className="grow row" style={{ gap: 6, minWidth: 0 }}>
                <span className="mono ellipsis">{file.name}</span>
                <span className="faint num">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                <button type="button" className="np-link" onClick={() => { setFile(null); if (input.current) input.current.value = ''; }}>{t('np.removeFile')}</button>
              </span>
            ) : <span className="grow muted">{dragging ? t('np.dropHere') : t('np.drop')}</span>}
            <input ref={input} type="file" accept={TYPES.join(',')} hidden onChange={e => pick(e.target.files?.[0])} />
            <Button size="sm" onClick={() => input.current?.click()}>{t('np.chooseFile')}</Button>
          </div>
          {fileError && <span className="np-error">{fileError}</span>}
          {file && idea.trim() && <span className="faint np-small">{t('np.fileNote')}</span>}
        </div>

        <div className="row wrap np-row">
          <label className="field grow" style={{ minWidth: 240 }}>
            <span className="label">{t('np.name')}</span>
            <input className="input" value={name} onChange={e => { setName(e.target.value); setNameEdited(true); }} maxLength={120} />
            <span className="faint np-small">{t('np.nameHint')}</span>
          </label>
          <div className="field">
            <span className="label">{t('np.kind')}</span>
            <span className="row np-kind"><span className="chip">{t('nav.kind.research')}</span></span>
          </div>
        </div>

        <fieldset className="np-where">
          <legend className="label">{t('np.where')}</legend>
          <label className={`np-opt${where === 'default' ? ' on' : ''}`}>
            <input type="radio" name="np-where" checked={where === 'default'} onChange={() => setWhere('default')} />
            <span className="col" style={{ gap: 2, minWidth: 0 }}>
              <span>{t('np.where.default')} <span className="mono np-path">{cfg ? target : '…'}</span></span>
              <span className="faint np-small">{t('np.where.defaultHint', { git: cfg?.git_init ? t('np.where.git') : '' })}</span>
            </span>
          </label>
          <label className={`np-opt${where === 'custom' ? ' on' : ''}`}>
            <input type="radio" name="np-where" checked={where === 'custom'} onChange={() => setWhere('custom')} />
            <span className="col grow" style={{ gap: 6, minWidth: 0 }}>
              <span>{t('np.where.custom')}</span>
              <input className="input mono" value={folder} placeholder="~/path/to/folder" aria-label={t('np.where.custom')}
                onFocus={() => setWhere('custom')} onChange={e => setFolder(e.target.value)} />
              <span className="faint np-small">{t('np.where.customHint')}</span>
            </span>
          </label>
        </fieldset>

        <div className="np-survey">
          <label className="row np-check"><input type="checkbox" checked={survey} onChange={e => setSurvey(e.target.checked)} /><b>{t('np.survey.on')}</b></label>
          {survey && (
            <div className="col np-survey-body">
              <div className="row wrap" style={{ gap: '6px 10px' }}>
                <span>{t('np.survey.search', { sources })}</span>
                <select className="input np-count" aria-label={t('np.survey.countLabel')} value={count} onChange={e => setCount(Number(e.target.value))}>
                  {counts.map(n => <option key={n} value={n}>{t('np.survey.count', { n })}</option>)}
                </select>
              </div>
              <label className="row np-check"><input type="checkbox" checked={pdfs} onChange={e => setPdfs(e.target.checked)} /><span>{t('np.survey.pdfs', { dir: papers })}</span></label>
              <span>{t('np.survey.drafts')}</span>
              <span className="faint np-small">{t('np.survey.noRun')}</span>
            </div>
          )}
        </div>
        {error && <div className="notice accent" role="alert"><Icon name="warn" /><span>{error}</span></div>}
      </div>
    </Dialog>
  );
}
