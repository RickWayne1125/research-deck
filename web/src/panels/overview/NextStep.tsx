// The four steps (Idea → Motivation & insight → System design → Evaluation) with what stands before the next one, and
// the dialog that lists the open checks and moves the project on: it passes the gates on the way (each pass saves a
// snapshot) and sets the project's stage. Binding checks (project.yaml gates.blocking) must hold first.
import { useState } from 'react';
import { p, patch } from '../../api/client';
import { Button, Dialog, Spinner } from '../../components/ui';
import { Icon } from '../../components/icons';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { STEPS, leaving, nextStage, stepOfStage, type StepId } from '../../state/stages';
import { useI18n, useT } from '../../i18n';
import { dagApi } from '../../dag/api';
import { errorMessage } from './parts';
import './i18n';

// ------------------------------------------------------------------ the four steps and what the next one needs

export function Steps({ pid }: { pid: string }) {
  const { project } = useApp();
  const t = useT();
  const today = useToday();
  const [open, setOpen] = useState(false);
  if (!project) return null;
  const step = stepOfStage(project.stage);
  const at = STEPS.indexOf(step);
  const { missing } = leaving(step, today.gates);
  const last = at === STEPS.length - 1;
  return (
    <div className="td-steps">
      <ol className="td-stepper" aria-label={t('td.steps')}>
        {STEPS.map((s, i) => (
          <li key={s} className={i < at ? 'done' : i === at ? 'current' : ''} aria-current={i === at ? 'step' : undefined}>
            <span className="td-step-dot" aria-hidden="true">{i < at && <Icon name="check" size={10} />}</span>
            <span>{t(`step.${s}`)}</span>
          </li>
        ))}
      </ol>
      {today.gates && (
        <button type="button" className="td-next" onClick={() => setOpen(true)}>
          {missing.length ? t(last ? 'td.next.missingLast' : 'td.next.missing', { n: missing.length }) : t(last ? 'td.next.readyLast' : 'td.next.ready')}
        </button>
      )}
      {open && <NextStepDialog pid={pid} step={step} onClose={() => setOpen(false)} />}
    </div>
  );
}

export function NextStepDialog({ pid, step, onClose }: { pid: string; step: StepId; onClose: () => void }) {
  const { project, reloadProject, navigate } = useApp();
  const { t, lang } = useI18n();
  const today = useToday();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { gates, missing } = leaving(step, today.gates);
  const next = nextStage(step);
  const blocking = !!(project?.config?.gates as { blocking?: boolean } | undefined)?.blocking;
  const nextStep = STEPS[STEPS.indexOf(step) + 1] as StepId | undefined;
  const go = async () => {
    setBusy(true); setError(null);
    try {
      for (const g of gates) await dagApi.passGate(pid, g.gate, t('td.next.note'));
      if (next) await patch(p(pid, '/config'), { stage: next });
      await reloadProject();
      today.reload();
      onClose();
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
                    <span className="grow">{c.label}
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

