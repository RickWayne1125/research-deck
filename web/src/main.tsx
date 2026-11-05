import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import 'katex/dist/katex.min.css';
import './styles/tokens.css';
import './styles/base.css';
import { I18nProvider } from './i18n';
import { AppProvider } from './state/app';
import { TodayProvider } from './state/today';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <AppProvider>
        <TodayProvider>
          <App />
        </TodayProvider>
      </AppProvider>
    </I18nProvider>
  </StrictMode>,
);
