// Settings › Zotero: how this computer reaches Zotero (the desktop app's local API, or zotero.org with a key kept in the
// Keychain), and where this project keeps its papers: files in the project, or a Zotero collection whose references.bib
// is exported into the project.
import { useCallback, useEffect, useState } from 'react';
import { Button, ErrorNote, Segmented, Spinner, useLoad } from '../components/ui';
import { useRelTime, useT } from '../i18n';
import { useApp } from '../state/app';
import { CopyButton } from '../agent/parts';
import { zoteroApi, type Collection, type ZoteroStatus } from './api';
import './i18n';
import './integrations.css';

const msg = (e: unknown) => String((e as Error)?.message ?? e);
const KEYCHAIN_CMD = 'security add-generic-password -s zotero-api-key -a "$USER" -w';

export function ZoteroSection() {
  const { projectId, onEvent } = useApp();
  const pid = projectId!;
  const t = useT();
  const rel = useRelTime();
  const [z, setZ] = useState<ZoteroStatus | null>(null);
  const [library, setLibrary] = useState('');
  const [credential, setCredential] = useState('');
  const [cols, setCols] = useState<Collection[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lit = useLoad(() => zoteroApi.literature(pid), [pid]);

  const take = useCallback((s: ZoteroStatus) => { setZ(s); setLibrary(s.library); setCredential(s.credential); }, []);
  useEffect(() => { zoteroApi.status().then(take).catch(e => setError(msg(e))); }, [take]);
  useEffect(() => {                       // the app's dialog is open: look again until it is answered
    if (z?.connect.state !== 'waiting') return;
    const id = window.setTimeout(() => zoteroApi.status().then(take).catch(() => {}), 1500);
    return () => window.clearTimeout(id);
  }, [z, take]);
  useEffect(() => onEvent('literature', () => lit.reload()), [onEvent, lit.reload]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try { await fn(); } catch (e) { setError(msg(e)); } finally { setBusy(null); }
  };
  const save = (change: Parameters<typeof zoteroApi.save>[0]) => act('save', async () => take(await zoteroApi.save(change)));
  const loadCols = () => act('cols', async () => setCols((await zoteroApi.collections()).collections));
  const setBackend = (body: Parameters<typeof zoteroApi.setLiterature>[1]) =>
    act('lit', async () => { await zoteroApi.setLiterature(pid, body); lit.reload(); });

  if (!z) return error ? <ErrorNote error={error} /> : <div className="empty"><Spinner /></div>;
  const l = lit.data;
  const check = z.check;
  return (
    <dl className="kv st-kv ig">
      <dt>{t('ig.computer')}</dt>
      <dd className="col ig-col">
        <Segmented ariaLabel={t('ig.z.mode')} value={z.mode} onChange={m => save({ mode: m })}
          options={[{ value: 'local', label: t('ig.z.local') }, { value: 'web', label: t('ig.z.web') }]} />
        {z.mode === 'local' ? (
          <>
            <div className="row wrap ig-row">
              <span className={`dot ${z.local_key ? 'ok' : ''}`} />
              <span>{z.local_key ? (z.local_remember === false ? t('ig.z.keyOnce') : t('ig.z.keyOk')) : t('ig.z.keyNone')}</span>
              <Button size="sm" variant={z.local_key ? undefined : 'primary'} icon="link" disabled={!!busy || z.connect.state === 'waiting'}
                onClick={() => act('connect', async () => take(await zoteroApi.connect()))}>{t('ig.z.connect')}</Button>
              {z.local_key && <Button size="sm" variant="ghost" icon="unlink" disabled={!!busy}
                onClick={() => act('forget', async () => take(await zoteroApi.forgetKey()))}>{t('ig.z.forget')}</Button>}
            </div>
            {z.connect.state === 'waiting' && <div className="row ig-row ig-wait"><Spinner /><span>{t('ig.z.dialog')}</span></div>}
            {z.connect.state === 'error' && <p className="ig-err">{z.connect.message}</p>}
            <span className="st-hint st-flush">{t('ig.z.localHint')}</span>
          </>
        ) : (
          <>
            <label className="col ig-field">
              <span className="faint">{t('ig.z.library')}</span>
              <input className="input mono" value={library} placeholder="users/123456" onChange={e => setLibrary(e.target.value)}
                onBlur={() => library.trim() !== z.library && save({ library: library.trim() || null })}
                onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
            </label>
            <label className="col ig-field">
              <span className="faint">{t('ig.z.credential')}</span>
              <input className="input mono" value={credential} placeholder="keychain:zotero-api-key" onChange={e => setCredential(e.target.value)}
                onBlur={() => credential.trim() !== z.credential && save({ credential: credential.trim() || null })}
                onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
            </label>
            <span className="st-hint st-flush">{t('ig.z.webHint')}</span>
            <span className="row ig-cmd"><code className="mono">{KEYCHAIN_CMD}</code><CopyButton text={KEYCHAIN_CMD} label={t('common.copy')} /></span>
          </>
        )}
        <div className="row wrap ig-row">
          <Button size="sm" icon="refresh" disabled={!!busy} onClick={() => act('check', async () => take(await zoteroApi.check()))}>{t('ig.z.check')}</Button>
          {busy === 'check' && <Spinner />}
          {check && (check.ok
            ? <span className="row ig-ok"><span className="dot ok" />{t('ig.z.answers', { library: z.library })}{check.user?.name ? ` · ${check.user.name}` : ''} · {rel(check.at)}</span>
            : <span className="ig-err">{check.message}</span>)}
        </div>
      </dd>

      <dt>{t('ig.project')}</dt>
      <dd className="col ig-col">
        {!l ? (lit.error ? <ErrorNote error={lit.error} onRetry={lit.reload} /> : <Spinner />) : (
          <>
            {(['files', 'zotero'] as const).map(b => (
              <label key={b} className="row np-check">
                <input type="radio" name="ig-lit" checked={l.backend === b} disabled={!!busy}
                  onChange={() => setBackend({ backend: b })} />
                <span>{t(`ig.z.backend.${b}`)}</span>
              </label>
            ))}
            {l.backend === 'zotero' && (
              <div className="col ig-sub">
                <div className="row wrap ig-row">
                  <span className="faint">{t('ig.z.collection')}</span>
                  <span>{l.collection_name ?? (l.collection ? l.collection : t('ig.z.collectionLater'))}</span>
                </div>
                <div className="row wrap ig-row">
                  {cols ? (
                    <select className="input" value={l.collection ?? ''} aria-label={t('ig.z.collection')} disabled={!!busy}
                      onChange={e => e.target.value && setBackend({ backend: 'zotero', collection: e.target.value })}>
                      <option value="">{t('ig.z.pick')}</option>
                      {cols.map(c => <option key={c.key} value={c.key}>{c.name}</option>)}
                    </select>
                  ) : <Button size="sm" disabled={!!busy} onClick={loadCols}>{t('ig.z.choose')}</Button>}
                  <Button size="sm" variant="ghost" icon="plus" disabled={!!busy}
                    onClick={() => setBackend({ backend: 'zotero', create: true })}>{t('ig.z.newCollection')}</Button>
                </div>
                <div className="row wrap ig-row">
                  <span className="mono">{l.bib}</span>
                  {l.exported && <span className="faint">{t('ig.z.exported', { n: l.exported.items, when: rel(l.exported.at) })}</span>}
                  <Button size="sm" icon="download" disabled={!!busy}
                    onClick={() => act('export', async () => { await zoteroApi.exportBib(pid); lit.reload(); })}>{t('ig.z.export')}</Button>
                  {busy === 'export' && <Spinner />}
                </div>
                <span className="st-hint st-flush">{t('ig.z.bibHint')}</span>
              </div>
            )}
          </>
        )}
        {error && <ErrorNote error={error} />}
      </dd>
    </dl>
  );
}
