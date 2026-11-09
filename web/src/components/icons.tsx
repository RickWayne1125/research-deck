// A small stroke icon set (16×16, 1.5 px, currentColor), drawn to match the figures' thin-line style.
import type { SVGProps } from 'react';

const P: Record<string, string> = {
  overview: 'M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z',
  dag: 'M4 3.5a1.5 1.5 0 1 1 0 .01M12 3.5a1.5 1.5 0 1 1 0 .01M8 12.5a1.5 1.5 0 1 1 0 .01M4 5l3.3 6M12 5l-3.3 6',
  outline: 'M3 3.5h10M3 3.5v9M3 8h2.5M3 12.5h2.5M7.5 8h5.5M7.5 12.5h5.5',
  writing: 'M3 13l1-3.5L11 2.5l2.5 2.5-7 7L3 13zM9.5 4l2.5 2.5',
  coding: 'M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5M9 3l-2 10',
  experiments: 'M6 2.5h4M6.5 2.5v4L3 12.5a1 1 0 0 0 .9 1.5h8.2a1 1 0 0 0 .9-1.5L9.5 6.5v-4M4.6 10h6.8',
  visualization: 'M2.5 13.5h11M4 11V7M7 11V4M10 11V8M13 11V5.5',
  settings: 'M8 5.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4',
  plus: 'M8 3v10M3 8h10',
  minus: 'M3 8h10',
  close: 'M4 4l8 8M12 4l-8 8',
  check: 'M3 8.5l3 3 7-7',
  chevronDown: 'M4 6l4 4 4-4',
  chevronRight: 'M6 4l4 4-4 4',
  chevronLeft: 'M10 4L6 8l4 4',
  sparkle: 'M8 1.5l1.3 4.2L13.5 7l-4.2 1.3L8 12.5 6.7 8.3 2.5 7l4.2-1.3L8 1.5zM13 11.5l.5 1.5 1.5.5-1.5.5-.5 1.5-.5-1.5-1.5-.5 1.5-.5.5-1.5z',
  play: 'M5 3.5v9l7-4.5-7-4.5z',
  stop: 'M4.5 4.5h7v7h-7z',
  refresh: 'M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3',
  lock: 'M4.5 7.5h7v6h-7zM6 7.5V5.5a2 2 0 0 1 4 0v2',
  unlock: 'M4.5 7.5h7v6h-7zM6 7.5V5.5a2 2 0 0 1 3.9-.6',
  branch: 'M5 2.5v11M5 10.5c0-3 6-2 6-5.5M11 3.5a1.5 1.5 0 1 1 0 .01M5 13.5a1.5 1.5 0 1 1 0 .01',
  rollback: 'M3 6.5h7a3.5 3.5 0 0 1 0 7H6M5.5 4L3 6.5 5.5 9',
  external: 'M9 2.5h4.5V7M13.5 2.5L7.5 8.5M11.5 9.5v4h-9v-9h4',
  search: 'M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9zM10.3 10.3L13.5 13.5',
  sun: 'M8 5a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1',
  moon: 'M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z',
  globe: 'M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM1.5 8h13M8 1.5c-2 2-2.8 4-2.8 6.5S6 12.5 8 14.5M8 1.5c2 2 2.8 4 2.8 6.5S10 12.5 8 14.5',
  bolt: 'M9 1.5L3.5 9H8l-1 5.5L12.5 7H8l1-5.5z',
  link: 'M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 0 1 4.5 9l1-1',
  file: 'M4 1.5h5.5L12.5 4.5v10h-8.5zM9.5 1.5v3h3',
  folder: 'M1.5 4V13h13V5.5H7.5L6 4z',
  warn: 'M8 2l6.5 11.5h-13L8 2zM8 6.5v3.5M8 12v.01',
  info: 'M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM8 7v4.5M8 4.8v.01',
  dock: 'M2 3h12v10H2zM10 3v10',
  terminal: 'M2 3h12v10H2zM4.5 6.5L6.5 8l-2 1.5M8 10h3.5',
  diff: 'M5 2.5v6M2 5.5h6M8 12.5h6M11 9.5v0',
  layers: 'M8 2l6 3-6 3-6-3 6-3zM2 8l6 3 6-3M2 11l6 3 6-3',
  history: 'M2.5 8a5.5 5.5 0 1 0 1.6-3.9M2.5 2.5v2.5H5M8 5v3.2l2.2 1.3',
  pin: 'M6 2.5h4l-.5 4 2 2v1h-7v-1l2-2-.5-4zM8 9.5v4',
  eye: 'M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8zM8 6a2 2 0 1 1 0 4 2 2 0 0 1 0-4z',
  split: 'M2 3h12v10H2zM8 3v10',
  send: 'M2 8l12-5.5L10.5 14 8 9 2 8z',
  gpu: 'M2 4.5h12v7H2zM4.5 11.5v2M7 11.5v2M9.5 11.5v2M12 11.5v2M5 7h2.5v2H5zM9 7h2v2H9z',
  server: 'M2.5 2.5h11v4.5h-11zM2.5 9h11v4.5h-11zM5 4.8v.01M5 11.2v.01',
  user: 'M8 2a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM2.5 14c.8-2.6 3-4 5.5-4s4.7 1.4 5.5 4',
  robot: 'M3 5.5h10v7.5H3zM8 5.5V3M8 3a.8.8 0 1 1 0 .01M5.8 9v.01M10.2 9v.01M6 11.5h4',
  image: 'M2 3h12v10H2zM2 11l3.5-3.5 3 3 2-2L14 12M10.5 5.5a1 1 0 1 1 0 .01',
  download: 'M8 2v8.5M4.5 7.5L8 11l3.5-3.5M2.5 13.5h11',
  upload: 'M8 11V2.5M4.5 6L8 2.5 11.5 6M2.5 13.5h11',
  trash: 'M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v5M9.2 6.5v5',
  dots: 'M3.5 8v.01M8 8v.01M12.5 8v.01',
  copy: 'M5.5 5.5h8v8h-8zM10.5 5.5V2.5h-8v8h3',
  hourglass: 'M4 1.5h8M4 14.5h8M5 1.5c0 3.5 6 3.5 6 6.5s-6 3-6 6.5M11 1.5c0 3.5-6 3.5-6 6.5s6 3 6 6.5',
  unlink: 'M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 0 1 4.5 9l1-1M2 2l2 2M12 12l2 2',
};

export type IconName = keyof typeof P;

export function Icon({ name, size = 16, ...rest }: { name: IconName | string; size?: number } & SVGProps<SVGSVGElement>) {
  const d = P[name] ?? P.dots;
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden="true" fill="none" stroke="currentColor"
      strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      <path d={d} />
    </svg>
  );
}
