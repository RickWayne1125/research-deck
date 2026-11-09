// Settings → Appearance: the interface language, the Radix theme (radix-ui.com's red, indigo and teal, or a custom one:
// accent, radius and background), light or dark, and a picture of one's own as the background, blurred to taste.
// The theme lives on the server (state/appearance.ts); light or dark and the language stay with this browser.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useApp, type Theme } from '../../state/app';
import { useI18n, useT } from '../../i18n';
import { Button, ErrorNote, Segmented } from '../../components/ui';
import { Icon } from '../../components/icons';
import { Ribbons } from '../../components/Backdrop';
import { fileBase64 } from '../../start/api';
import {
  ACCENTS, BACKGROUNDS, PRESETS, RADII, SCALINGS, THEMES, appearanceApi, customChange, setScaling, useAppearance, useScaling,
  type Accent, type CustomBackground, type Radius, type Scaling, type ThemeId,
} from '../../state/appearance';
import '../../styles/backdrop.css';

const PICTURES = 'image/png,image/jpeg,image/webp,image/gif,image/avif';

export function AppearanceSection() {
  const t = useT();
  const { lang, setLang } = useI18n();
  const { theme: mode, setTheme: setMode } = useApp();
  const { settings, resolved } = useAppearance();
  const scaling = useScaling();
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const run = (p: Promise<unknown>) => { setError(null); p.catch(e => setError(String((e as Error)?.message ?? e))); };

  const pickTheme = (id: ThemeId) => run(appearanceApi.update({ theme: id }));
  const pickCustom = (change: { accent?: Accent; radius?: Radius; background?: CustomBackground }) => run(appearanceApi.update(customChange(settings, change)));
  const pickBackground = (b: CustomBackground) => {
    if (b === 'image' && !settings.image) { file.current?.click(); return; }
    pickCustom({ background: b });
  };
  const upload = async (f: File | undefined) => {
    if (!f) return;
    setUploading(true); setError(null);
    try {
      if (settings.theme !== 'custom') await appearanceApi.update(customChange(settings, {}));
      await appearanceApi.uploadImage(f.name, await fileBase64(f));
    } catch (e) { setError(String((e as Error)?.message ?? e)); } finally { setUploading(false); if (file.current) file.current.value = ''; }
  };

  // the blur shows while the slider moves and is saved once it rests
  const [blur, setBlur] = useState(settings.blur);
  useEffect(() => { setBlur(settings.blur); }, [settings.blur]);
  const saveBlur = useRef(0);
  const moveBlur = (v: number) => {
    setBlur(v);
    appearanceApi.preview({ blur: v });
    window.clearTimeout(saveBlur.current);
    saveBlur.current = window.setTimeout(() => run(appearanceApi.update({ blur: v })), 400);
  };
  useEffect(() => () => window.clearTimeout(saveBlur.current), []);

  return (
    <div className="col st-look">
      <Row label={t('st.app.lang')} hint={t('st.app.langHint')}>
        <Segmented ariaLabel={t('st.app.lang')} value={lang} onChange={setLang}
          options={[{ value: 'zh', label: t('lang.zh') }, { value: 'en', label: t('lang.en') }]} />
      </Row>

      <div className="st-look-block">
        <div className="st-look-head"><span className="st-look-label">{t('st.app.themes')}</span><span className="st-hint st-flush">{t('st.app.themesHint')}</span></div>
        <div className="st-look-themes" role="radiogroup" aria-label={t('st.app.themes')}>
          {THEMES.map(id => (
            <button key={id} type="button" role="radio" aria-checked={settings.theme === id} className="st-look-pick" onClick={() => pickTheme(id)}>
              <span className={`st-look-swatch rd-chip-${id === 'custom' ? 'custom' : PRESETS[id].palette}`}
                data-accent-color={id === 'custom' ? undefined : PRESETS[id].accent} />
              <span>{t(`st.app.theme.${id}`)}</span>
            </button>
          ))}
        </div>
      </div>

      <Row label={t('st.app.mode')} hint={t('st.app.modeHint')}>
        <Segmented<Theme> ariaLabel={t('st.app.mode')} value={mode} onChange={setMode}
          options={[{ value: 'light', label: t('theme.light') }, { value: 'dark', label: t('theme.dark') }, { value: 'auto', label: t('theme.auto') }]} />
      </Row>

      <Row label={t('st.app.size')} hint={t('st.app.sizeHint')}>
        <Segmented<Scaling> ariaLabel={t('st.app.size')} value={scaling} onChange={setScaling}
          options={SCALINGS.map(v => ({ value: v, label: v }))} />
      </Row>

      <div className="st-look-block">
        <div className="st-look-head"><span className="st-look-label">{t('st.app.accent')}</span><span className="st-hint st-flush">{resolved.accent}</span></div>
        <div className="st-look-accents" role="radiogroup" aria-label={t('st.app.accent')}>
          {ACCENTS.map(a => (
            <button key={a} type="button" role="radio" aria-checked={resolved.accent === a} aria-label={a} title={a}
              data-accent-color={a} className="st-look-accent" onClick={() => pickCustom({ accent: a })} />
          ))}
        </div>
      </div>

      <Row label={t('st.app.radius')}>
        <Segmented<Radius> ariaLabel={t('st.app.radius')} value={resolved.radius} onChange={r => pickCustom({ radius: r })}
          options={RADII.map(r => ({ value: r, label: t(`st.app.radius.${r}`) }))} />
      </Row>

      <hr className="st-look-rule" />

      <div className="st-look-block">
        <div className="st-look-head"><span className="st-look-label">{t('st.app.bg')}</span><span className="st-hint st-flush">{t('st.app.bgHint')}</span></div>
        <div className="st-look-bgs" role="radiogroup" aria-label={t('st.app.bg')}>
          {BACKGROUNDS.map(b => (
            <button key={b} type="button" role="radio" aria-checked={resolved.background === b} className="st-look-pick" onClick={() => pickBackground(b)}>
              <BackgroundSwatch kind={b} image={settings.image} palette={resolved.palette} />
              <span>{t(`st.app.bg.${b}`)}</span>
            </button>
          ))}
        </div>
        <div className="row wrap">
          <Button variant="soft" icon="upload" disabled={uploading} onClick={() => file.current?.click()}>
            {uploading ? t('st.app.uploading') : settings.image ? t('st.app.replace') : t('st.app.upload')}
          </Button>
          {settings.image && <Button variant="ghost" icon="trash" onClick={() => run(appearanceApi.removeImage())}>{t('st.app.removeImage')}</Button>}
          <Button variant="ghost" onClick={() => run(appearanceApi.reset())}>{t('st.app.reset')}</Button>
          <input ref={file} type="file" accept={PICTURES} hidden onChange={e => upload(e.target.files?.[0])} />
        </div>
        {settings.image && (
          <label className="st-look-slider">
            <span className="row"><span className="grow">{t('st.app.blur')}</span><span className="num muted">{blur}%</span></span>
            <input type="range" min={0} max={100} step={5} value={blur} aria-label={t('st.app.blur')}
              style={{ '--value': `${blur}%` } as React.CSSProperties} onChange={e => moveBlur(Number(e.target.value))} />
          </label>
        )}
        <p className="st-hint st-flush">{t('st.app.imageNote')}</p>
        {error && <ErrorNote error={error} />}
      </div>
    </div>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="st-look-row">
      <span className="col" style={{ gap: 2, minWidth: 0 }}>
        <span className="st-look-label">{label}</span>
        {hint && <span className="st-hint st-flush">{hint}</span>}
      </span>
      {children}
    </div>
  );
}

function BackgroundSwatch({ kind, image, palette }: { kind: CustomBackground; image: string | null; palette: string | null }) {
  if (kind === 'radix') return <span className={`st-look-swatch rd-chip-${palette && palette !== 'accent' ? palette : 'accent'}`} />;
  if (kind === 'ribbons') return <span className="st-look-swatch rd-bg-ribbons"><Ribbons id="rd-swatch-silk" /></span>;
  if (kind === 'image') {
    return image
      ? <span className="st-look-swatch st-look-photo" style={{ backgroundImage: `url("${image}")` }} />
      : <span className="st-look-swatch st-look-empty"><Icon name="upload" /></span>;
  }
  return <span className={`st-look-swatch rd-bg-${kind}`} />;
}
