// The art behind the dashboard (Settings → Appearance): radix-ui.com's background in a Radix theme's palette, or for a
// custom theme the ribbons, a gradient, a glow, a plain fill or the user's picture (blurred as chosen). It lies under
// the whole shell (fixed, behind everything, never takes clicks); the panels over it are glass (styles/shell.css).
import type { CSSProperties } from 'react';
import { MAX_BLUR_PX, useAppearance } from '../state/appearance';
import { RADIX_ART, RADIX_ART_VIEWBOX } from './radixArt';
import '../styles/backdrop.css';

export function Backdrop() {
  const { settings, resolved } = useAppearance();
  const bg = resolved.background;
  const blur = Math.round((settings.blur / 100) * MAX_BLUR_PX);
  return (
    <div className={`rd-backdrop rd-bg-${bg}`} aria-hidden="true" data-testid="backdrop">
      {bg === 'radix' && (
        <div className={`rd-art rd-pal-${resolved.palette ?? 'red'}`}>
          <svg viewBox={RADIX_ART_VIEWBOX} width="2560" height="1920" fill="none" dangerouslySetInnerHTML={{ __html: RADIX_ART }} />
        </div>
      )}
      {bg === 'ribbons' && <Ribbons />}
      {bg === 'image' && settings.image && (
        <div className="rd-photo" style={{ backgroundImage: `url("${settings.image}")`, '--rd-blur': `${blur}px` } as CSSProperties} />
      )}
    </div>
  );
}

// Ribbons: bands of thin strokes in the accent, each band fading across its width (the strokes' opacities) and along
// its length (the gradient), softened by a blur so no band has an edge.
const A = [
  ['M 120 -60 C 460 100 420 380 760 470 S 1260 500 1540 760', 0.06], ['M 98 -40 C 432 120 394 398 740 487 S 1248 518 1536 782', 0.16],
  ['M 76 -20 C 404 140 368 416 720 504 S 1236 536 1532 804', 0.22], ['M 54 0 C 376 160 342 434 700 521 S 1224 554 1528 826', 0.22],
  ['M 32 20 C 348 180 316 452 680 538 S 1212 572 1524 848', 0.19], ['M 10 40 C 320 200 290 470 660 555 S 1200 590 1520 870', 0.15],
  ['M -12 60 C 292 220 264 488 640 572 S 1188 608 1516 892', 0.11], ['M -34 80 C 264 240 238 506 620 589 S 1176 626 1512 914', 0.08],
  ['M -56 100 C 236 260 212 524 600 606 S 1164 644 1508 936', 0.05], ['M -78 120 C 208 280 186 542 580 623 S 1152 662 1504 958', 0.03],
  ['M -100 140 C 180 300 160 560 560 640 S 1140 680 1500 980', 0.015],
] as const;
const B = [
  ['M -80 760 C 260 620 520 820 860 700 S 1300 420 1540 380', 0.01], ['M -80 781 C 266 647 532 841 872 721 S 1303 447 1540 407', 0.03],
  ['M -80 802 C 272 674 544 862 884 742 S 1306 474 1540 434', 0.06], ['M -80 823 C 278 701 556 883 896 763 S 1309 501 1540 461', 0.1],
  ['M -80 844 C 284 728 568 904 908 784 S 1312 528 1540 488', 0.14], ['M -80 865 C 290 755 580 925 920 805 S 1315 555 1540 515', 0.18],
  ['M -80 886 C 296 782 592 946 932 826 S 1318 582 1540 542', 0.15], ['M -80 900 C 300 800 600 960 940 840 S 1320 600 1540 560', 0.05],
] as const;
const C = [
  ['M 640 -40 C 860 120 1080 10 1250 130 S 1440 300 1560 250', 0.16], ['M 652 -48 C 874 108 1092 2 1260 120 S 1446 288 1560 238', 0.13],
  ['M 664 -56 C 888 96 1104 -6 1270 110 S 1452 276 1560 226', 0.1], ['M 676 -64 C 902 84 1116 -14 1280 100 S 1458 264 1560 214', 0.07],
  ['M 688 -72 C 916 72 1128 -22 1290 90 S 1464 252 1560 202', 0.04], ['M 700 -80 C 930 60 1140 -30 1300 80 S 1470 240 1560 190', 0.02],
] as const;

/** The ribbons; `id` prefixes the gradients' ids so a swatch can draw them next to the backdrop. */
export function Ribbons({ id = 'rd-silk' }: { id?: string }) {
  return (
    <svg className="rd-ribbons" viewBox="0 0 1440 1000" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`${id}-a`} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="1440" y2="1000">
          <stop offset="0" style={{ stopColor: 'var(--accent-9)', stopOpacity: 1 }} />
          <stop offset="0.6" style={{ stopColor: 'var(--accent-9)', stopOpacity: 0.5 }} />
          <stop offset="1" style={{ stopColor: 'var(--accent-9)', stopOpacity: 0.08 }} />
        </linearGradient>
        <linearGradient id={`${id}-b`} gradientUnits="userSpaceOnUse" x1="0" y1="900" x2="1440" y2="400">
          <stop offset="0" style={{ stopColor: 'var(--accent-9)', stopOpacity: 0.9 }} />
          <stop offset="1" style={{ stopColor: 'var(--accent-9)', stopOpacity: 0.12 }} />
        </linearGradient>
        <filter id={`${id}-blur`} x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="14" /></filter>
      </defs>
      <g fill="none" filter={`url(#${id}-blur)`} stroke={`url(#${id}-a)`} strokeWidth="30">
        {A.map(([d, o]) => <path key={d} d={d} strokeOpacity={o} />)}
      </g>
      <g fill="none" filter={`url(#${id}-blur)`} stroke={`url(#${id}-b)`} strokeWidth="28">
        {B.map(([d, o]) => <path key={d} d={d} strokeOpacity={o} />)}
      </g>
      <g fill="none" filter={`url(#${id}-blur)`} stroke={`url(#${id}-a)`} strokeWidth="16">
        {C.map(([d, o]) => <path key={d} d={d} strokeOpacity={o} />)}
      </g>
    </svg>
  );
}
