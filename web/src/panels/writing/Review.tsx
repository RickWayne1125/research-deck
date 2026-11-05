// The proofreading controls in the header: "AI proofread" (the selection, or the whole document), then, once
// suggestions are in, how many are open, previous / next and "Accept all"; while a check runs, the pass in progress
// and Stop.
import { useT } from '../../i18n';
import { Button, IconButton, Spinner } from '../../components/ui';
import type { WrReview } from './api';
import { KEYS } from './text';

export function ReviewBar({ review, open, running, hasSelection, onCheck, onCancel, onAcceptAll, onStep }: {
  review: WrReview | null; open: number; running: boolean; hasSelection: boolean;
  onCheck: () => void; onCancel: () => void; onAcceptAll: () => void; onStep: (dir: 1 | -1) => void;
}) {
  const t = useT();
  if (running && review) {
    const now = review.passes.find(p => review.progress[p] === 'running') ?? review.passes.find(p => review.progress[p] !== 'done');
    return (
      <div className="wr-review" role="status" aria-live="polite">
        <span className="wr-review-state"><Spinner />{t('wr.review.running', { pass: now ? t(`wr.pass.${now}`) : '' })}</span>
        <Button size="sm" icon="stop" onClick={onCancel}>{t('wr.check.cancel')}</Button>
      </div>
    );
  }
  return (
    <div className="wr-review">
      {open > 0 && (
        <>
          <IconButton icon="chevronLeft" label={`${t('wr.review.prev')} (${KEYS.prev})`} onClick={() => onStep(-1)} />
          <span className="wr-review-count num">{t('wr.review.open', { n: open })}</span>
          <IconButton icon="chevronRight" label={`${t('wr.review.next')} (${KEYS.next})`} onClick={() => onStep(1)} />
          <Button size="sm" onClick={onAcceptAll} title={t('wr.all.hint')}>{t('wr.all')}</Button>
        </>
      )}
      <Button variant="accent" icon="sparkle" onClick={onCheck} title={t('wr.check.hint', { key: KEYS.check })}>
        {hasSelection ? t('wr.proofreadSel') : t('wr.proofread')}
      </Button>
    </div>
  );
}
