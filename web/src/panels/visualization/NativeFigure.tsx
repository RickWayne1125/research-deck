// OmniGraffle / DataGraph figures: the document stays native. Preview (when exported), open in the app, export PDF,
// and a clear state when the app is not installed on this Mac.
import { useState } from 'react';
import { ApiError } from '../../api/client';
import { Icon } from '../../components/icons';
import { Button, Spinner } from '../../components/ui';
import { useT } from '../../i18n';
import { errMessage, KIND_LABEL, vz, type FigureView } from './api';

export function NativeFigure({ projectId, figure, onChanged }: { projectId: string; figure: FigureView; onChanged: () => void }) {
  const t = useT();
  const app = KIND_LABEL[figure.kind];
  const installed = !!figure.native?.installed;
  const [busy, setBusy] = useState<'open' | 'export' | null>(null);
  const [note, setNote] = useState<{ tone: '' | 'accent'; text: string; log?: string } | null>(null);

  const act = async (what: 'open' | 'export') => {
    setBusy(what);
    setNote(null);
    try {
      if (what === 'open') {
        await vz.openNative(projectId, figure.id);
        setNote({ tone: '', text: t('vz.nat.opened', { app }) });
      } else {
        const r = await vz.exportNative(projectId, figure.id);
        setNote({ tone: '', text: t('vz.nat.exported', { files: r.outputs.join(', ') }) });
        onChanged();
      }
    } catch (e) {
      const log = e instanceof ApiError ? (e.detail as { log?: string })?.log : undefined;
      setNote({ tone: 'accent', text: errMessage(e), log });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="vz-native">
      <div className="vz-native-preview vz-thumb">
        {figure.preview ? <img src={figure.preview} alt={figure.title} />
          : <div className="col" style={{ alignItems: 'center', gap: 6 }}><Icon name="image" size={22} /><span className="faint">{t('vz.nat.noPreview', { app })}</span></div>}
      </div>
      <aside className="vz-native-side">
        <dl className="kv">
          <dt>{t('vz.nat.file')}</dt><dd className="mono">{figure.source}</dd>
          {!figure.exists && <><dt /><dd><span className="badge accent">{t('vz.missingFile')}</span></dd></>}
        </dl>
        {!installed && (
          <div className="notice warn">
            <Icon name="warn" />
            <div className="col" style={{ gap: 2 }}>
              <b>{t('vz.nat.notInstalled', { app })}</b>
              <span>{t('vz.nat.notInstalledBody', { app })}</span>
            </div>
          </div>
        )}
        <div className="row wrap">
          <Button variant="primary" icon="external" disabled={!installed || !figure.exists || busy !== null} onClick={() => act('open')}>
            {busy === 'open' ? <Spinner /> : null}{t('vz.nat.open', { app })}
          </Button>
          <Button icon="download" disabled={!installed || !figure.exists || busy !== null} onClick={() => act('export')}>
            {busy === 'export' ? t('vz.nat.exporting') : t('vz.nat.export')}
          </Button>
        </div>
        {note && (
          <div className={`notice ${note.tone}`} role={note.tone ? 'alert' : undefined}>
            <Icon name={note.tone ? 'warn' : 'check'} />
            <div className="col grow" style={{ gap: 4 }}>
              <span>{note.text}</span>
              {note.log && <pre className="code vz-log-inline">{note.log}</pre>}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
