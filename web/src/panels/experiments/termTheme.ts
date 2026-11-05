// Colors of the log terminal (LogTerminal.tsx), derived from the design tokens in styles/tokens.css — no color is
// written here. The terminal is dark in both UI themes: in the dark theme the tokens already suit a dark ground; in
// the light theme the ground is the ink, and each semantic color is lifted toward the surface until it reads on it.
import type { ITheme } from '@xterm/xterm';

export type Rgb = [number, number, number];

export function parseColor(value: string): Rgb | null {
  const v = value.trim().toLowerCase();
  const short = /^#([0-9a-f]{3})$/.exec(v);
  if (short) return [...short[1]].map(c => parseInt(c + c, 16)) as Rgb;
  const long = /^#([0-9a-f]{6})(?:[0-9a-f]{2})?$/.exec(v);
  if (long) return [0, 2, 4].map(i => parseInt(long[1].slice(i, i + 2), 16)) as Rgb;
  const fn = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(v);
  if (fn) return [fn[1], fn[2], fn[3]].map(x => Math.min(255, Math.round(Number(x)))) as Rgb;
  return null;
}

/** `a` moved toward `b` by `t` (0 … 1). */
export const mix = (a: Rgb, b: Rgb, t: number): Rgb => a.map((x, i) => Math.round(x + (b[i] - x) * t)) as Rgb;

export const hex = (c: Rgb): string => `#${c.map(x => Math.max(0, Math.min(255, x)).toString(16).padStart(2, '0')).join('')}`;

/** WCAG relative luminance. */
export function luminance(c: Rgb): number {
  const [r, g, b] = c.map(x => { const s = x / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `c`, moved toward `toward` in small steps until its contrast with `ground` reaches `min`. */
export function readable(c: Rgb, ground: Rgb, toward: Rgb, min: number): Rgb {
  for (let k = 0; k < 1; k += 0.05) {
    const m = mix(c, toward, k);
    if (contrast(m, ground) >= min) return m;
  }
  return toward;
}

export const TERM_TOKENS = ['--paper', '--surface', '--ink', '--ink-strong', '--slate', '--rule-strong',
  '--accent', '--ok', '--warn', '--info'] as const;
type Token = (typeof TERM_TOKENS)[number];

export interface TermColors {
  theme: ITheme;
  /** Search highlights (the search addon wants #RRGGBB). */
  match: string;
  activeMatch: string;
  /** Whether the UI itself is in its dark theme. */
  darkUi: boolean;
}

/** The terminal's colors from the current token values (`read('--ok')` → "#2f7d5b"); null if a token is missing. */
export function terminalColors(read: (token: string) => string): TermColors | null {
  const tok = {} as Record<Token, Rgb>;
  for (const name of TERM_TOKENS) {
    const c = parseColor(read(name));
    if (!c) return null;
    tok[name] = c;
  }
  const darkUi = luminance(tok['--paper']) < luminance(tok['--ink']);
  const ground = darkUi ? tok['--paper'] : tok['--ink-strong'];
  const top = darkUi ? tok['--ink-strong'] : tok['--surface'];       // the lightest token: colors lift toward it
  const fg = darkUi ? tok['--ink'] : mix(top, ground, 0.1);
  const tone = (c: Rgb) => readable(c, ground, top, 4.5);
  const bright = (c: Rgb) => mix(tone(c), top, 0.3);
  const red = tok['--accent'], green = tok['--ok'], yellow = tok['--warn'], blue = tok['--info'];
  const ansi: Record<'red' | 'green' | 'yellow' | 'blue' | 'magenta' | 'cyan', Rgb> = {
    red, green, yellow, blue, magenta: mix(red, blue, 0.5), cyan: mix(blue, green, 0.5),
  };
  const theme: ITheme = {
    background: hex(ground), foreground: hex(fg),
    cursor: hex(ground), cursorAccent: hex(ground),                   // read-only: no cursor to see
    selectionBackground: `${hex(tone(blue))}59`, selectionInactiveBackground: `${hex(tone(blue))}40`,
    scrollbarSliderBackground: `${hex(fg)}33`, scrollbarSliderHoverBackground: `${hex(fg)}55`,
    scrollbarSliderActiveBackground: `${hex(fg)}77`, overviewRulerBorder: hex(ground),
    black: hex(darkUi ? tok['--rule-strong'] : tok['--ink']), brightBlack: hex(readable(tok['--slate'], ground, top, 3.5)),
    white: hex(mix(fg, ground, 0.12)), brightWhite: hex(top),
  };
  for (const [name, c] of Object.entries(ansi)) {
    const key = name as keyof typeof ansi;
    theme[key] = hex(tone(c));
    theme[`bright${key[0].toUpperCase()}${key.slice(1)}` as 'brightRed'] = hex(bright(c));
  }
  return { theme, match: hex(mix(ground, tone(yellow), 0.35)), activeMatch: hex(mix(ground, tone(yellow), 0.7)), darkUi };
}
