// The paper view: the text (WritingView: documents, editor, AI proofreading) and the figures (the visualization
// gallery and editors), switched by the Text | Figures control in each header. Route: #/<project>/writing[/<doc path>]
// for the text, #/<project>/writing/@figures[/<figure id>] for the figures.
import { lazy, Suspense } from 'react';
import { FIGURES, useApp } from '../../state/app';
import { Spinner } from '../../components/ui';
import { WritingView } from './WritingView';
import './i18n';

const FiguresView = lazy(() => import('../visualization').then(m => ({ default: m.FiguresView })));

export default function PaperPanel() {
  const { sub } = useApp();
  if (sub === FIGURES || sub?.startsWith(`${FIGURES}/`)) {
    return <Suspense fallback={<div className="empty"><Spinner /></div>}><FiguresView /></Suspense>;
  }
  return <WritingView />;
}
