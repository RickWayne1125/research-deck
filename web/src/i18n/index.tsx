// Chinese / English UI strings. Each panel registers its own strings from src/panels/<panel>/i18n.ts with
// registerStrings({ zh: {...}, en: {...} }); keys are namespaced by panel ("wr.check", "dag.impact.title").
// Missing keys fall back to English, then to the key itself, so a forgotten translation is visible, not blank.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { core } from './core';

export type Lang = 'zh' | 'en';
type Dict = Record<string, string>;

const dicts: Record<Lang, Dict> = { zh: {}, en: {} };

export function registerStrings(d: { zh: Dict; en: Dict }): void {
  Object.assign(dicts.zh, d.zh);
  Object.assign(dicts.en, d.en);
}
registerStrings(core);

export type TFunc = (key: string, vars?: Record<string, string | number>) => string;

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  let s = dicts[lang][key] ?? dicts.en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

const LANG_KEY = 'rd.lang';
function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === 'zh' || saved === 'en') return saved;
  } catch { /* storage unavailable */ }
  return navigator.language.toLowerCase().startsWith('en') ? 'en' : 'zh';
}

interface I18nValue { lang: Lang; setLang: (l: Lang) => void; t: TFunc }
const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(LANG_KEY, l); } catch { /* ignore */ }
  }, []);
  useEffect(() => { document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'; }, [lang]);
  const t = useCallback<TFunc>((key, vars) => translate(lang, key, vars), [lang]);
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const v = useContext(I18nContext);
  if (!v) throw new Error('useI18n outside I18nProvider');
  return v;
}
export const useT = (): TFunc => useI18n().t;

/** Format a timestamp relative to now in the current language ("3 分钟前" / "3 min ago"). */
export function useRelTime(): (iso: string | number | null | undefined) => string {
  const { lang } = useI18n();
  return useCallback((iso) => {
    if (iso == null || iso === '') return '—';
    const ts = typeof iso === 'number' ? (iso < 1e12 ? iso * 1000 : iso) : Date.parse(iso);
    if (!Number.isFinite(ts)) return String(iso);
    const s = Math.round((Date.now() - ts) / 1000);
    const rtf = new Intl.RelativeTimeFormat(lang === 'zh' ? 'zh-CN' : 'en', { numeric: 'auto' });
    const abs = Math.abs(s);
    if (abs < 60) return rtf.format(-s, 'second');
    if (abs < 3600) return rtf.format(-Math.round(s / 60), 'minute');
    if (abs < 86400) return rtf.format(-Math.round(s / 3600), 'hour');
    if (abs < 86400 * 30) return rtf.format(-Math.round(s / 86400), 'day');
    return new Date(ts).toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en');
  }, [lang]);
}
