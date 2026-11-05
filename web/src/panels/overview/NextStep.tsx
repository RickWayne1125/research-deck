// The dialog that moves the project on to the next step (Idea → Motivation & insight → System design → Evaluation): it
// lists the open checks (the outline's, then the gates'), passes the gates on the way (each pass saves a snapshot) and
// sets the project's stage; the outline page opens it from the current phase. Binding checks (project.yaml
// gates.blocking) must hold first. Then the conversation opens with a request to draft the new step from the confirmed
// nodes (not sent: the researcher edits and sends it).
import { useState, type ReactNode } from 'react';
import { p, patch } from '../../api/client';
import { Button, Dialog, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { STEPS, leaving, nextStage, type StepId } from '../../state/stages';
import { useI18n } from '../../i18n';
import { dagApi } from '../../dag/api';
import { errorMessage } from './parts';
import './i18n';

/** `extra` shows more checks above the gates (the outline's: every item of the phase holds) and `extraMissing` counts
 *  the ones of them that fail; `passNote` is what the gate passes record. */
export function NextStepDialog({ pid, step, onClose, extra, extraMissing = 0, passNote }: {
  pid: string; step: StepId; onClose: () => void; extra?: ReactNode; extraMissing?: number; passNote?: string;
}) {
  const { project, reloadProject, navigate, askAgent } = useApp();
  const { t, lang } = useI18n();
  const today = useToday();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { gates, missing: gateMissing } = leaving(step, today.gates);
  const missing = { length: gateMissing.length + extraMissing };
  const next = nextStage(step);
  const blocking = !!(project?.config?.gates as { blocking?: boolean } | undefined)?.blocking;
  const nextStep = STEPS[STEPS.indexOf(step) + 1] as StepId | undefined;
  const go = async () => {
    setBusy(true); setError(null);
    try {
      for (const g of gates) await dagApi.passGate(pid, g.gate, passNote ?? t('td.next.note'));
      if (next) await patch(p(pid, '/config'), { stage: next });
      await reloadProject();
      today.reload();
      onClose();
      if (nextStep) askAgent(t('td.next.draftPrompt', { step: t(`step.${nextStep}`), prev: t(`step.${step}`) }), {});
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  const label = nextStep ? t('td.next.go', { step: t(`step.${nextStep}`) }) : t('td.next.goLast');
  return (
    <Dialog title={nextStep ? t('td.next.title', { step: t(`step.${nextStep}`) }) : t('td.next.titleLast')} onClose={onClose} width={600} footer={
      <>
        <Button onClick={onClose}>{t('common.close')}</Button>
        {(gates.length > 0 || next) && (
          <Button variant="primary" onClick={go} disabled={busy || (blocking && missing.length > 0)}>
            {busy && <Spinner />}{missing.length && !blocking ? t('td.next.anyway') : label}
          </Button>
        )}
      </>
    }>
      <div className="col" style={{ gap: 12 }}>
        {extra}
        {missing.length === 0
          ? <p style={{ margin: 0 }}>{t('td.next.allOk')}</p>
          : <p style={{ margin: 0 }}>{t(blocking ? 'td.next.blocking' : 'td.next.advisory', { n: missing.length })}</p>}
        {gates.map(g => {
          const failing = g.checks.filter(c => !c.ok);
          return (
            <div key={g.gate} className="td-gate">
              <div className="row" style={{ gap: 8 }}>
                <b>{(lang === 'zh' ? g.title.zh : g.title.en) || g.title.en}</b>
                <span className="faint num">{t('td.next.checks', { ok: g.checks.length - failing.length, n: g.checks.length })}</span>
              </div>
              <ul className="td-checks">
                {g.checks.map((c, i) => (
                  <li key={i} className={c.ok ? 'ok' : 'no'}>
                    <Icon name={c.ok ? 'check' : 'close'} size={12} />
                    <span className="grow">{(lang === 'zh' && c.zh) || c.label}
                      {!c.ok && !!c.items?.length && (
                        <span className="td-check-items">
                          {c.items.slice(0, 6).map(id => <button key={id} type="button" className="chip mono" onClick={() => { onClose(); navigate('dag', id); }}>{id}</button>)}
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {error && <div className="notice accent" role="alert"><Icon name="warn" /><span>{error}</span></div>}
      </div>
    </Dialog>
  );
}

