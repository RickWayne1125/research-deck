// Text | Figures: the two halves of the paper view, as the first control of each half's header.
import { FIGURES, useApp } from '../../state/app';
import { Segmented } from '../../components/ui';
import { useT } from '../../i18n';

/** The document opened last in this project (WritingView stores it), so "Text" goes back to it. */
function lastDoc(pid: string): string | null {
  try { const v = localStorage.getItem(`rd.wr.doc.${pid}`); return v ? (JSON.parse(v) as string) : null; } catch { return null; }
}

export function PaperTabs() {
  const { projectId, sub, navigate } = useApp();
  const t = useT();
  const figures = !!sub && (sub === FIGURES || sub.startsWith(`${FIGURES}/`));
  return (
    <Segmented<'text' | 'figures'> ariaLabel={t('nav.writing')} value={figures ? 'figures' : 'text'}
      onChange={v => navigate('writing', v === 'figures' ? FIGURES : (projectId ? lastDoc(projectId) : null))}
      options={[{ value: 'text', label: t('wr.tab.text') }, { value: 'figures', label: t('wr.tab.figures') }]} />
  );
}
