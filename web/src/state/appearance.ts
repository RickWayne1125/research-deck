// Appearance: the Radix Themes theme (accent, gray, radius) and the background art, from Settings → Appearance.
// The choice lives on the server (~/.research-deck/settings.json, server/research_deck/appearance.py) so every browser
// shows the same; light or dark stays per browser (state/app.tsx). The last choice is cached in localStorage and
// index.html applies it before the first paint, so a reload never flashes another theme.
import { useEffect, useSyncExternalStore } from 'react';
import { del, get, patch, put } from '../api/client';

export const ACCENTS = ['gray', 'gold', 'bronze', 'brown', 'yellow', 'amber', 'orange', 'tomato', 'red', 'ruby', 'crimson',
  'pink', 'plum', 'purple', 'violet', 'iris', 'indigo', 'blue', 'cyan', 'teal', 'jade', 'green', 'grass', 'lime', 'mint', 'sky'] as const;
export type Accent = (typeof ACCENTS)[number];
export type Gray = 'gray' | 'mauve' | 'slate' | 'sage' | 'olive' | 'sand';
export const RADII = ['none', 'small', 'medium', 'large', 'full'] as const;
export type Radius = (typeof RADII)[number];
export const THEMES = ['radix-red', 'radix-indigo', 'radix-teal', 'custom'] as const;
export type ThemeId = (typeof THEMES)[number];
export const BACKGROUNDS = ['radix', 'ribbons', 'gradient', 'glow', 'plain', 'image'] as const;
export type CustomBackground = (typeof BACKGROUNDS)[number];
/** The Radix art's palette: one of the site's three, or built from a custom theme's accent. */
export type Palette = 'red' | 'indigo' | 'teal' | 'accent';
export type Mode = 'light' | 'dark';

export interface AppearanceSettings {
  theme: ThemeId;
  custom: { accent: Accent; radius: Radius; background: CustomBackground };
  /** the picture's blur, 0–100 (% of 40 px) */
  blur: number;
  /** the uploaded picture's URL, or null */
  image: string | null;
}

/** What the page draws: Radix attributes for <html> and the background layer. */
export interface Resolved { accent: Accent; gray: Gray; radius: Radius; background: CustomBackground; palette: Palette | null }

/** radix-ui.com's three looks: the accent, gray and radius of its examples, and its background art in their palette. */
export const PRESETS: Record<Exclude<ThemeId, 'custom'>, { accent: Accent; gray: Gray; radius: Radius; palette: Palette }> = {
  'radix-red': { accent: 'red', gray: 'slate', radius: 'medium', palette: 'red' },
  'radix-indigo': { accent: 'indigo', gray: 'slate', radius: 'medium', palette: 'indigo' },
  'radix-teal': { accent: 'teal', gray: 'gray', radius: 'medium', palette: 'teal' },
};

export const DEFAULTS: AppearanceSettings = {
  theme: 'radix-red', custom: { accent: 'red', radius: 'large', background: 'ribbons' }, blur: 40, image: null,
};
export const MAX_BLUR_PX = 40;

/** Radix Themes' "auto" gray: the neutral scale that is tinted like the accent. */
export function grayFor(accent: Accent): Gray {
  switch (accent) {
    case 'tomato': case 'red': case 'ruby': case 'crimson': case 'pink': case 'plum': case 'purple': case 'violet': return 'mauve';
    case 'iris': case 'indigo': case 'blue': case 'sky': case 'cyan': return 'slate';
    case 'teal': case 'jade': case 'mint': case 'green': return 'sage';
    case 'grass': case 'lime': return 'olive';
    case 'yellow': case 'amber': case 'orange': case 'brown': case 'gold': case 'bronze': return 'sand';
    default: return 'gray';
  }
}

export function resolve(s: AppearanceSettings): Resolved {
  if (s.theme !== 'custom') {
    const p = PRESETS[s.theme] ?? PRESETS['radix-red'];
    return { accent: p.accent, gray: p.gray, radius: p.radius, background: 'radix', palette: p.palette };
  }
  const background = s.custom.background === 'image' && !s.image ? 'ribbons' : s.custom.background;
  return { accent: s.custom.accent, gray: grayFor(s.custom.accent), radius: s.custom.radius, background, palette: background === 'radix' ? 'accent' : null };
}

const listeners = new Set<() => void>();

/** The interface size (Radix's scaling): per browser, like light or dark; 100 % is Radix's own size. */
export const SCALINGS = ['90%', '95%', '100%', '105%', '110%'] as const;
export type Scaling = (typeof SCALINGS)[number];
const SCALING_KEY = 'rd.scaling';

export function readScaling(): Scaling {
  try {
    const v = localStorage.getItem(SCALING_KEY);
    if ((SCALINGS as readonly string[]).includes(v ?? '')) return v as Scaling;
  } catch { /* storage unavailable */ }
  return '100%';
}

export function setScaling(v: Scaling, el: HTMLElement = document.documentElement) {
  try { localStorage.setItem(SCALING_KEY, v); } catch { /* storage unavailable */ }
  el.dataset.scaling = v;
  listeners.forEach(fn => fn());
}

/** Put the theme on <html> (the Radix theme root). index.html does the same from the cache before React starts. */
export function applyTheme(r: Resolved, el: HTMLElement = document.documentElement) {
  el.classList.add('radix-themes');
  el.dataset.accentColor = r.accent;
  el.dataset.grayColor = r.gray;
  el.dataset.radius = r.radius;
  el.dataset.scaling = readScaling();
  el.dataset.panelBackground = 'translucent';
  el.dataset.hasBackground = 'false';
  el.dataset.background = r.background;
}

export function applyMode(mode: Mode, el: HTMLElement = document.documentElement) {
  el.classList.toggle('dark', mode === 'dark');
  el.classList.toggle('light', mode === 'light');
  el.style.colorScheme = mode;
}

// ------------------------------------------------------------------ the store

const CACHE = 'rd.appearance';

function readCache(): AppearanceSettings {
  try {
    const raw = JSON.parse(localStorage.getItem(CACHE) || 'null');
    if (raw && typeof raw === 'object' && raw.settings) return normalize(raw.settings);
  } catch { /* storage unavailable or garbage */ }
  return DEFAULTS;
}

/** Anything the server or the cache sends, as settings the page can draw (unknown values give the defaults). */
export function normalize(v: unknown): AppearanceSettings {
  const o = (v && typeof v === 'object' ? v : {}) as Partial<Omit<AppearanceSettings, 'custom'>> & { custom?: Partial<AppearanceSettings['custom']> };
  const c: Partial<AppearanceSettings['custom']> = o.custom ?? {};
  return {
    theme: (THEMES as readonly string[]).includes(o.theme as string) ? o.theme as ThemeId : DEFAULTS.theme,
    custom: {
      accent: (ACCENTS as readonly string[]).includes(c.accent as string) ? c.accent as Accent : DEFAULTS.custom.accent,
      radius: (RADII as readonly string[]).includes(c.radius as string) ? c.radius as Radius : DEFAULTS.custom.radius,
      background: (BACKGROUNDS as readonly string[]).includes(c.background as string) ? c.background as CustomBackground : DEFAULTS.custom.background,
    },
    blur: typeof o.blur === 'number' && o.blur >= 0 && o.blur <= 100 ? Math.round(o.blur) : DEFAULTS.blur,
    image: typeof o.image === 'string' && o.image.startsWith('/api/') ? o.image : null,
  };
}

let state: AppearanceSettings = typeof window === 'undefined' ? DEFAULTS : readCache();

function set(next: AppearanceSettings) {
  state = next;
  const r = resolve(next);
  if (typeof document !== 'undefined') applyTheme(r);
  // the cache keeps what index.html needs (the attributes) next to the settings themselves
  try { localStorage.setItem(CACHE, JSON.stringify({ settings: next, resolved: r })); } catch { /* storage unavailable */ }
  listeners.forEach(fn => fn());
}

const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

/** The interface size, following setScaling. */
export function useScaling(): Scaling {
  return useSyncExternalStore(subscribe, readScaling, () => '100%');
}
const snapshot = () => state;

let loaded: Promise<void> | null = null;
/** Fetch the settings once per page (later calls share the request). */
export function loadAppearance(force = false): Promise<void> {
  if (!loaded || force) {
    loaded = get<AppearanceSettings>('/api/settings/appearance').then(s => set(normalize(s))).catch(() => { loaded = null; });
  }
  return loaded;
}

export const appearanceApi = {
  update: async (change: { theme?: ThemeId | null; custom?: Partial<AppearanceSettings['custom']> | null; blur?: number | null }) => {
    // shown at once; the server's answer (or the settings before, when it refuses) follows
    const before = state;
    set(normalize({ ...state, ...change, custom: change.custom === null ? DEFAULTS.custom : { ...state.custom, ...(change.custom ?? {}) },
      theme: change.theme === null ? DEFAULTS.theme : change.theme ?? state.theme, blur: change.blur === null ? DEFAULTS.blur : change.blur ?? state.blur }));
    try { set(normalize(await patch<AppearanceSettings>('/api/settings/appearance', change))); } catch (e) { set(before); throw e; }
  },
  uploadImage: async (name: string, contentBase64: string) => {
    set(normalize(await put<AppearanceSettings>('/api/settings/appearance/image', { name, content_base64: contentBase64 })));
  },
  removeImage: async () => { set(normalize(await del<AppearanceSettings>('/api/settings/appearance/image'))); },
  reset: async () => appearanceApi.update({ theme: null, custom: null, blur: null }),
  /** Show a value at once without saving it (the blur slider while it moves; update() saves it). */
  preview: (change: { blur?: number }) => set(normalize({ ...state, ...change })),
};

/** A change to a custom theme's accent, radius or background. From one of the Radix themes it starts from that
 *  theme (its accent, radius and the Radix art), so only the one thing changes on screen. */
export function customChange(s: AppearanceSettings, change: Partial<AppearanceSettings['custom']>): { theme: 'custom'; custom: Partial<AppearanceSettings['custom']> } {
  if (s.theme === 'custom') return { theme: 'custom', custom: change };
  const p = PRESETS[s.theme];
  return { theme: 'custom', custom: { accent: p.accent, radius: p.radius, background: 'radix', ...change } };
}

/** The current settings and what they resolve to; loads them from the server on first use. */
export function useAppearance(): { settings: AppearanceSettings; resolved: Resolved } {
  const settings = useSyncExternalStore(subscribe, snapshot, snapshot);
  useEffect(() => { loadAppearance(); }, []);
  return { settings, resolved: resolve(settings) };
}

// apply the cached theme as soon as this module loads (index.html normally did already)
if (typeof document !== 'undefined') applyTheme(resolve(state));
