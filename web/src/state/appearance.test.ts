// Appearance: what a theme choice draws (Radix attributes and the background), Radix's matching grays, what a custom
// change starts from, and how unknown values from the server or the cache are read.
import { describe, expect, it } from 'vitest';
import { ACCENTS, DEFAULTS, PRESETS, customChange, grayFor, normalize, resolve, type AppearanceSettings } from './appearance';

const custom = (c: Partial<AppearanceSettings['custom']>, rest: Partial<AppearanceSettings> = {}): AppearanceSettings =>
  ({ ...DEFAULTS, theme: 'custom', ...rest, custom: { ...DEFAULTS.custom, ...c } });

describe('appearance', () => {
  it('draws the Radix themes with their own accent, gray, radius and palette', () => {
    expect(resolve(DEFAULTS)).toEqual({ accent: 'red', gray: 'slate', radius: 'medium', background: 'radix', palette: 'red' });
    expect(resolve({ ...DEFAULTS, theme: 'radix-indigo' })).toMatchObject({ accent: 'indigo', palette: 'indigo' });
    expect(resolve({ ...DEFAULTS, theme: 'radix-teal' })).toMatchObject({ accent: 'teal', gray: 'gray', palette: 'teal' });
    // a preset ignores the custom choices kept for later
    expect(resolve({ ...DEFAULTS, custom: { accent: 'jade', radius: 'none', background: 'glow' } }).accent).toBe('red');
  });

  it('draws a custom theme with the gray Radix pairs with its accent', () => {
    expect(resolve(custom({ accent: 'indigo', radius: 'full', background: 'glow' })))
      .toEqual({ accent: 'indigo', gray: 'slate', radius: 'full', background: 'glow', palette: null });
    expect(resolve(custom({ accent: 'jade', background: 'radix' }))).toMatchObject({ gray: 'sage', background: 'radix', palette: 'accent' });
    expect(grayFor('crimson')).toBe('mauve');
    expect(grayFor('lime')).toBe('olive');
    expect(grayFor('amber')).toBe('sand');
    expect(grayFor('gray')).toBe('gray');
    for (const a of ACCENTS) expect(['gray', 'mauve', 'slate', 'sage', 'olive', 'sand']).toContain(grayFor(a));
  });

  it('falls back to the ribbons when the picture is gone', () => {
    expect(resolve(custom({ background: 'image' })).background).toBe('ribbons');
    expect(resolve(custom({ background: 'image' }, { image: '/api/settings/appearance/image?v=1' })).background).toBe('image');
  });

  it('starts a custom theme from the Radix theme on screen', () => {
    expect(customChange(DEFAULTS, { accent: 'blue' })).toEqual({ theme: 'custom', custom: { accent: 'blue', radius: 'medium', background: 'radix' } });
    expect(customChange({ ...DEFAULTS, theme: 'radix-teal' }, { background: 'glow' }))
      .toEqual({ theme: 'custom', custom: { accent: PRESETS['radix-teal'].accent, radius: 'medium', background: 'glow' } });
    expect(customChange(custom({}), { radius: 'small' })).toEqual({ theme: 'custom', custom: { radius: 'small' } });
  });

  it('reads anything unknown as the defaults', () => {
    expect(normalize(null)).toEqual(DEFAULTS);
    expect(normalize({ theme: 'neon', custom: { accent: 'chartreuse', radius: 'huge', background: 'video' }, blur: 400, image: 'javascript:alert(1)' }))
      .toEqual(DEFAULTS);
    expect(normalize({ theme: 'custom', custom: { accent: 'plum' }, blur: 12.4, image: '/api/settings/appearance/image?v=ab' }))
      .toEqual({ theme: 'custom', custom: { ...DEFAULTS.custom, accent: 'plum' }, blur: 12, image: '/api/settings/appearance/image?v=ab' });
  });
});
