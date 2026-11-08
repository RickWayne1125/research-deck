// Signing the Coder CLI in from the page, when ssh to a Coder workspace failed because the CLI is signed out
// (pools/coder.py). The researcher opens the deployment's /cli-auth page (on any device), copies the session token it
// shows and pastes it here; the server hands it to the CLI's own prompt, and the CLI keeps it where ssh reads it.
import { useEffect, useState } from 'react';
import { useT } from '../i18n';
import { Button, Dialog, Spinner } from '../components/ui';
import { poolApi, type CoderStatus } from './api';

const errText = (e: unknown) => String((e as Error)?.message ?? e);

/** The sign-in, inline (the wizard's test result) or in a dialog (CoderSignInDialog). `onDone` once it is signed in. */
export function CoderSignIn({ host, onDone }: { host: string | null; onDone: (s: CoderStatus) => void }) {
  const t = useT();
  const [status, setStatus] = useState<CoderStatus | null>(null);
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    poolApi.coderStatus(host).then(s => {
      if (!alive) return;
      setStatus(s);
      setUrl(u => u || s.url || '');
    }).catch(e => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [host]);

  const base = url.trim().replace(/\/+$/, '');
  const authUrl = /^https?:\/\/[^\s/]+/.test(base) ? `${base}/cli-auth` : null;
  const submit = async () => {
    if (!authUrl || !token.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const s = await poolApi.coderLogin(base, token.trim(), host);
      setStatus(s);
      setToken('');
      if (s.signed_in) onDone(s); else setError(t('pl.coder.notYet'));
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };

  if (!status) return error ? <div className="notice accent">{error}</div> : <div className="row pl-coder-wait"><Spinner /></div>;
  if (!status.installed) return <div className="notice warn">{t('pl.coder.missing')}</div>;
  if (status.managed === 'vscode') return <div className="notice warn">{t('pl.coder.vscode')}</div>;
  if (status.signed_in) {
    return (
      <div className="col pl-coder">
        <span className="pl-good">{t('pl.coder.signedIn', { user: status.user ?? '?' })}</span>
        <div><Button size="sm" icon="play" onClick={() => onDone(status)}>{t('pl.coder.retest')}</Button></div>
      </div>
    );
  }
  return (
    <form className="col pl-coder" onSubmit={e => { e.preventDefault(); submit(); }}>
      <span>{host ? t('pl.coder.needed', { host }) : t('pl.coder.neededNoHost')}</span>
      {status.error && <span className="pl-err mono">{t('pl.coder.error', { error: status.error })}</span>}
      <label className="field"><span className="label">{t('pl.coder.url')}</span>
        <input className="input mono" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://coder.example.com" spellCheck={false} />
      </label>
      <div className="col pl-coder-step">
        <span>① {t('pl.coder.step1')}</span>
        {authUrl
          ? <a className="btn sm pl-coder-open" href={authUrl} target="_blank" rel="noopener noreferrer">{t('pl.coder.open')} ↗</a>
          : <span className="faint pl-small">{t('pl.coder.urlFirst')}</span>}
      </div>
      <label className="field"><span className="label">② {t('pl.coder.step2')}</span>
        <input className="input mono" type="password" value={token} onChange={e => setToken(e.target.value)}
          autoComplete="off" spellCheck={false} aria-label={t('pl.coder.token')} placeholder={t('pl.coder.token')} />
      </label>
      {error && <div className="notice accent">{error}</div>}
      <div className="row pl-coder-foot">
        <Button type="submit" variant="accent" disabled={!authUrl || !token.trim() || busy}>{busy ? t('pl.coder.busy') : t('pl.coder.submit')}</Button>
      </div>
      <span className="faint pl-small">{t('pl.coder.where', { folder: status.folder })}</span>
    </form>
  );
}

export function CoderSignInDialog({ host, onClose, onDone }: { host: string | null; onClose: () => void; onDone: () => void }) {
  const t = useT();
  return (
    <Dialog title={t('pl.coder.title')} onClose={onClose} width={520}>
      <CoderSignIn host={host} onDone={() => { onDone(); onClose(); }} />
    </Dialog>
  );
}
