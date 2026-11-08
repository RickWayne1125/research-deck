// Settings › Docmost: this computer's Docmost site and sign-in (a window opens on the computer that runs Research Deck;
// the researcher signs in there as usual), and this project's bound page with each note's state. Notes go one way,
// notes → Docmost; a page edited in Docmost since the last push waits here for review (ConflictDialog).
import { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Dialog, ErrorNote, Spinner, useLoad } from '../components/ui';
import { Icon } from '../components/icons';
import { useRelTime, useT } from '../i18n';
import { useApp } from '../state/app';
import { docmostApi, type DocmostConflict, type DocmostNote, type DocmostStatus, type NoteState } from './api';
import './i18n';
import './integrations.css';

const msg = (e: unknown) => String((e as Error)?.message ?? e);
const TONE: Record<NoteState, 'ok' | 'warn' | 'accent' | 'stale' | undefined> = {
  synced: 'ok', pending: undefined, conflict: 'warn', missing: 'accent', removed: 'stale', error: 'accent',
};

export function DocmostSection() {
  const { projectId, onEvent } = useApp();
  const pid = projectId!;
  const t = useT();
  const rel = useRelTime();
  const [d, setD] = useState<DocmostStatus | null>(null);
  const [site, setSite] = useState('');
  const [link, setLink] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<string | null>(null);
  const proj = useLoad(() => docmostApi.project(pid), [pid]);

  const take = useCallback((s: DocmostStatus) => { setD(s); setSite(s.url ?? ''); }, []);
  const refresh = useCallback(() => docmostApi.status().then(take).catch(e => setError(msg(e))), [take]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {                       // a sign-in window is open, or the browser is downloading: look again
    if (d?.login.state !== 'waiting' && d?.install.state !== 'running') return;
    const id = window.setTimeout(() => { refresh(); if (d?.login.state === 'waiting') proj.reload(); }, 1500);
    return () => window.clearTimeout(id);
  }, [d, refresh, proj.reload]);
  useEffect(() => onEvent('docmost', () => { proj.reload(); refresh(); }), [onEvent, proj.reload, refresh]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try { await fn(); } catch (e) { setError(msg(e)); } finally { setBusy(null); }
  };

  if (!d) return error ? <ErrorNote error={error} /> : <div className="empty"><Spinner /></div>;
  const p = proj.data;
  const needsBrowser = d.helper === 'playwright' && (d.login.code === 5 || d.install.state === 'running');
  return (
    <dl className="kv st-kv ig">
      <dt>{t('ig.computer')}</dt>
      <dd className="col ig-col">
        <label className="col ig-field">
          <span className="faint">{t('ig.d.site')}</span>
          <input className="input mono" value={site} placeholder="https://docs.example.com" onChange={e => setSite(e.target.value)}
            onBlur={() => site.trim() !== (d.url ?? '') && act('site', async () => take(await docmostApi.setSite(site.trim() || null)))}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
        </label>
        <div className="row wrap ig-row">
          {d.signed_in ? (
            <>
              <span className="dot ok" />
              <span>{t('ig.d.signedIn', { who: d.user?.name || d.user?.email || '—' })}</span>
              {d.at && <span className="faint">{rel(d.at)}</span>}
              <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => act('out', async () => take(await docmostApi.logout()))}>{t('ig.d.signOut')}</Button>
            </>
          ) : (
            <>
              <span className="dot" />
              <span>{t('ig.d.signedOut')}</span>
              <Button size="sm" variant="primary" icon="user" disabled={!d.url || !!busy || d.login.state === 'waiting' || !d.helper}
                onClick={() => act('in', async () => take(await docmostApi.login()))}>{t('ig.d.signIn')}</Button>
            </>
          )}
        </div>
        {d.login.state === 'waiting' && (
          <div className="row ig-row ig-wait"><Spinner /><span>{d.login.phase === 'build' ? t('ig.d.building') : t('ig.d.window')}</span></div>
        )}
        {d.login.state === 'error' && <p className="ig-err">{d.login.message}</p>}
        {!d.helper && !d.signed_in && (
          <p className="ig-err">{t('ig.d.noHelper')} <code className="mono">xcode-select --install</code> · <code className="mono">pip install -e '.[docmost]'</code></p>
        )}
        {needsBrowser && (
          <div className="row wrap ig-row">
            <Button size="sm" icon="download" disabled={d.install.state === 'running'}
              onClick={() => act('browser', async () => take(await docmostApi.installBrowser()))}>{t('ig.d.install')}</Button>
            {d.install.state === 'running' && <><Spinner /><span className="faint">{d.install.message}</span></>}
            {d.install.state === 'error' && <span className="ig-err">{d.install.message}</span>}
          </div>
        )}
        <span className="st-hint st-flush">{d.helper === 'native' ? t('ig.d.signInHintNative') : t('ig.d.signInHint')}</span>
      </dd>

      <dt>{t('ig.project')}</dt>
      <dd className="col ig-col">
        {!p ? (proj.error ? <ErrorNote error={proj.error} onRetry={proj.reload} /> : <Spinner />) : p.binding ? (
          <>
            <div className="row wrap ig-row">
              <span className="faint">{t('ig.d.page')}</span>
              {p.binding.url
                ? <a href={p.binding.url} target="_blank" rel="noreferrer noopener" className="row ig-link">{p.binding.title || p.binding.slug_id}<Icon name="external" size={11} /></a>
                : <span>{p.binding.title}</span>}
              <Button size="sm" icon="refresh" disabled={!!busy || p.running || !d.signed_in}
                onClick={() => act('sync', async () => { await docmostApi.sync(pid); proj.reload(); })}>{t('ig.d.syncNow')}</Button>
              <Button size="sm" variant="ghost" icon="unlink" disabled={!!busy}
                onClick={() => act('unbind', async () => { await docmostApi.unbind(pid); proj.reload(); })}>{t('ig.d.unbind')}</Button>
              {(p.running || busy === 'sync') && <Spinner />}
            </div>
            {p.last && <span className="faint ig-last">{t('ig.d.last', { when: rel(p.last.at), pushed: p.last.pushed, conflicts: p.last.conflicts, errors: p.last.errors })}</span>}
            {p.notes.length === 0
              ? <span className="st-hint st-flush">{t('ig.d.noNotes')}</span>
              : <NotesTable notes={p.notes} busy={!!busy} onReview={setReview}
                  onAction={(path, action) => act(`${action}:${path}`, async () => { await docmostApi.resolve(pid, path, action); proj.reload(); })} />}
            <span className="st-hint st-flush">{t('ig.d.oneWay')}</span>
          </>
        ) : (
          <>
            <div className="row wrap ig-row ig-bind">
              <input className="input mono grow" value={link} placeholder={`${d.url ?? 'https://docs.example.com'}/s/…/p/…`}
                aria-label={t('ig.d.pageLink')} onChange={e => setLink(e.target.value)} />
              <Button size="sm" variant="primary" icon="link" disabled={!link.trim() || !d.signed_in || !!busy}
                onClick={() => act('bind', async () => { await docmostApi.bind(pid, link.trim()); setLink(''); proj.reload(); })}>{t('ig.d.bind')}</Button>
              {busy === 'bind' && <Spinner />}
            </div>
            <span className="st-hint st-flush">{d.signed_in ? t('ig.d.bindHint') : t('ig.d.signInFirst')}</span>
          </>
        )}
        {error && <ErrorNote error={error} />}
      </dd>
      {review && <ConflictDialog pid={pid} path={review} onClose={() => { setReview(null); proj.reload(); }} />}
    </dl>
  );
}

function NotesTable({ notes, busy, onReview, onAction }: {
  notes: DocmostNote[]; busy: boolean; onReview: (path: string) => void;
  onAction: (path: string, action: 'recreate' | 'forget') => void;
}) {
  const t = useT();
  const rel = useRelTime();
  return (
    <table className="table ig-notes">
      <thead><tr><th>{t('ig.d.note')}</th><th>{t('ig.d.state')}</th><th /></tr></thead>
      <tbody>
        {notes.map(n => (
          <tr key={n.path}>
            <td>
              <div className="ig-note-title">{n.url
                ? <a href={n.url} target="_blank" rel="noreferrer noopener" className="row ig-link">{n.title}<Icon name="external" size={11} /></a>
                : n.title}</div>
              <div className="mono faint ig-note-path">{n.path}</div>
            </td>
            <td>
              <Badge tone={TONE[n.state]} title={n.error ?? undefined}>{t(`ig.d.st.${n.state}`)}</Badge>
              {n.at && n.state === 'synced' && <span className="faint ig-when">{rel(n.at)}</span>}
              {n.error && <div className="ig-err ig-note-err">{n.error}</div>}
            </td>
            <td className="ig-actions">
              {n.state === 'conflict' && <Button size="sm" variant="primary" icon="diff" disabled={busy} onClick={() => onReview(n.path)}>{t('ig.d.review')}</Button>}
              {n.state === 'missing' && <Button size="sm" disabled={busy} onClick={() => onAction(n.path, 'recreate')}>{t('ig.d.recreate')}</Button>}
              {(n.state === 'missing' || n.state === 'removed') && <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAction(n.path, 'forget')}>{t('ig.d.forget')}</Button>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConflictDialog({ pid, path, onClose }: { pid: string; path: string; onClose: () => void }) {
  const t = useT();
  const { navigate } = useApp();
  const c = useLoad<DocmostConflict>(() => docmostApi.conflict(pid, path), [pid, path]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resolve = async (action: 'push' | 'take') => {
    setBusy(true);
    setError(null);
    try { await docmostApi.resolve(pid, path, action); onClose(); } catch (e) { setError(msg(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog width={760} onClose={onClose} title={t('ig.d.conflictTitle', { title: c.data?.title ?? path })}
      footer={<>
        <Button variant="ghost" onClick={() => { onClose(); navigate('writing', path); }}>{t('ig.d.openNote')}</Button>
        <span className="grow" />
        <Button disabled={busy || !c.data} onClick={() => resolve('take')}>{t('ig.d.take')}</Button>
        <Button variant="primary" disabled={busy || !c.data} onClick={() => resolve('push')}>{t('ig.d.push')}</Button>
      </>}>
      {!c.data ? (c.error ? <ErrorNote error={c.error} onRetry={c.reload} /> : <Spinner />) : (
        <div className="col ig-conflict">
          <p className="ig-p">{t('ig.d.conflictBody')}</p>
          <div className="row ig-row">
            <span className="h3">{t('ig.d.theirChanges')}</span>
            {c.data.url && <a href={c.data.url} target="_blank" rel="noreferrer noopener" className="row ig-link">{t('ig.d.openPage')}<Icon name="external" size={11} /></a>}
          </div>
          <pre className="ig-diff mono">{c.data.diff.length === 0 ? t('ig.d.noDiff') : c.data.diff.map((l, i) => (
            <div key={i} className={`ig-dl ig-dl-${l.kind === '+' ? 'add' : l.kind === '-' ? 'del' : l.kind === '@' ? 'hunk' : 'ctx'}`}>
              {l.kind === '@' ? l.text : `${l.kind === ' ' ? ' ' : l.kind} ${l.text}`}
            </div>
          ))}</pre>
          <p className="faint ig-p">{t('ig.d.mergeHint')}</p>
          {error && <ErrorNote error={error} />}
        </div>
      )}
    </Dialog>
  );
}
