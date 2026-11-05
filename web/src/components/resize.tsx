// Resizable panes. useResizableWidth keeps a pane's width (remembered per browser in localStorage) and ResizeHandle is
// the handle on the pane's inner edge: drag it, ←/→ change by 16 px (Shift: 64), Home/End go to the limits, a
// double-click restores the default. During a drag the width goes straight to the pane's CSS variable on `target`
// (no React render per pointer move) and is committed on release; text selection and iframes (the draw.io editor
// would swallow the mouse) are switched off meanwhile (html.rd-resizing in styles/base.css).
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from 'react';
import { useT } from '../i18n';

export const RESIZE_STEP = 16;

type Px = number | (() => number);
const px = (v: Px) => (typeof v === 'function' ? v() : v);

/** Clamp to [min, max]; when the two cross (a very narrow window), max wins so a pane never pushes the rest out. */
export function clampWidth(w: number, min: number, max: number): number {
  return Math.round(Math.min(max, Math.max(min, w)));
}

function readWidth(key: string | null): number | null {
  if (!key) return null;
  try {
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch { return null; }
}
function writeWidth(key: string | null, w: number | null): void {
  if (!key) return;
  try { if (w == null) localStorage.removeItem(key); else localStorage.setItem(key, String(Math.round(w))); } catch { /* storage unavailable */ }
}

/** What ResizeHandle drives: a width with its limits, a live preview, a commit and a reset. */
export interface Resizable {
  width: number; min: number; max: number;
  /** the width and limits right now, including a commit React has not rendered yet (fast key repeats) and a window
   *  resize that did not change the width (so no render) */
  read: () => number;
  limits: () => { min: number; max: number };
  /** the width the pane would take for a proposed one (clamped, snapped) */
  fit: (w: number, from: number, via: 'drag' | 'key') => number;
  /** during a drag: show this width without a React render */
  preview: (w: number) => void;
  /** set and remember a width */
  commit: (w: number) => void;
  /** back to the default */
  reset: () => void;
}

export interface ResizableWidth extends Resizable {
  defaultWidth: number;
  /** for the target element's style: { [cssVar]: "<width>px" } */
  style: CSSProperties;
}

export interface WidthOptions {
  /** the CSS custom property the pane reads its width from, set on `target` (the pane or an ancestor of it) */
  cssVar: string;
  target: RefObject<HTMLElement | null>;
  /** maps a proposed width to the one to use, e.g. a navigation dragged below a threshold snaps to its icon rail */
  snap?: (w: number, ctx: { from: number; via: 'drag' | 'key' }) => number;
}

interface Cfg { initial: Px; min: number; max: Px; opts: WidthOptions; stored: number | null }
function limitsOf(c: Cfg) {
  const hi = px(c.max);
  return { lo: Math.min(c.min, hi), hi, def: clampWidth(px(c.initial), c.min, hi) };
}
const widthOf = (c: Cfg) => { const { hi, def } = limitsOf(c); return clampWidth(c.stored ?? def, c.min, hi); };
const setVar = (c: Cfg, w: number) => c.opts.target.current?.style.setProperty(c.opts.cssVar, `${w}px`);

/** A pane width in px, remembered under storageKey (null: not remembered). `initial` and `max` may be functions, read
 *  on every render, after layout changes and on window resizes (a share of the window or of a container): a stored
 *  width wider than what fits now shows clamped, and the stored preference stays for when there is room again. */
export function useResizableWidth(storageKey: string | null, initial: Px, min: number, max: Px, opts: WidthOptions): ResizableWidth {
  const [stored, setStored] = useState<number | null>(() => readWidth(storageKey));
  const [, rerender] = useState(0);
  const cfg = useRef<Cfg>({ initial, min, max, opts, stored });
  cfg.current = { initial, min, max, opts, stored };
  const { lo, hi, def } = limitsOf(cfg.current);
  const width = clampWidth(stored ?? def, min, hi);
  const shown = useRef(width);
  shown.current = width;

  // A limit that depends on the layout (the window, a container another pane just resized) is read again after each
  // render and on window resizes; render again only when the width it gives has changed.
  useLayoutEffect(() => { if (widthOf(cfg.current) !== shown.current) rerender(n => n + 1); });
  const dynamic = typeof initial === 'function' || typeof max === 'function';
  useEffect(() => {
    if (!dynamic) return;
    let raf = 0;
    const onResize = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { if (widthOf(cfg.current) !== shown.current) rerender(n => n + 1); });
    };
    window.addEventListener('resize', onResize);
    return () => { window.removeEventListener('resize', onResize); cancelAnimationFrame(raf); };
  }, [dynamic]);

  const fit = useCallback((w: number, from: number, via: 'drag' | 'key') => {
    const c = cfg.current;
    const { lo, hi } = limitsOf(c);
    const v = clampWidth(w, lo, hi);
    return c.opts.snap ? clampWidth(c.opts.snap(v, { from, via }), lo, hi) : v;
  }, []);
  const read = useCallback(() => widthOf(cfg.current), []);
  const limits = useCallback(() => { const { lo, hi } = limitsOf(cfg.current); return { min: lo, max: hi }; }, []);
  const preview = useCallback((w: number) => setVar(cfg.current, w), []);
  const commit = useCallback((w: number) => {
    const c = cfg.current;
    const next = Math.round(w);
    setVar(c, clampWidth(next, c.min, limitsOf(c).hi));
    c.stored = next;
    setStored(next);
    writeWidth(storageKey, next);
  }, [storageKey]);
  const reset = useCallback(() => {
    const c = cfg.current;
    setVar(c, limitsOf(c).def);
    c.stored = null;
    setStored(null);
    writeWidth(storageKey, null);
  }, [storageKey]);

  return {
    width, min: lo, max: hi, defaultWidth: def, read, limits, fit, preview, commit, reset,
    style: { [opts.cssVar]: `${width}px` } as CSSProperties,
  };
}

/** The drag handle on a pane's inner edge (role="separator"). `edge` is the pane edge it sits on: "right" for a pane
 *  left of the content it gives way to (dragging right widens it), "left" for a pane on the right. The handle is
 *  absolutely positioned over that edge, so its parent must be positioned and must not scroll. */
export function ResizeHandle({ pane, edge, label, controls, onToggle, className }: {
  pane: Resizable; edge: 'left' | 'right'; label: string;
  /** id of the pane, for aria-controls */
  controls?: string;
  /** Enter collapses or expands the pane (the window-splitter pattern), for a pane that has a collapsed state */
  onToggle?: () => void;
  className?: string;
}) {
  const t = useT();
  const el = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; x: number; from: number; last: number; onKey: (e: KeyboardEvent) => void } | null>(null);
  const paneRef = useRef(pane);
  paneRef.current = pane;
  const dir = edge === 'right' ? 1 : -1;

  const finish = useCallback((keep: boolean) => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    window.removeEventListener('keydown', d.onKey, true);
    document.documentElement.classList.remove('rd-resizing');
    el.current?.classList.remove('is-dragging');
    if (keep && d.last !== d.from) paneRef.current.commit(d.last);
    else if (!keep) { paneRef.current.preview(d.from); el.current?.setAttribute('aria-valuenow', String(d.from)); }
  }, []);
  useEffect(() => () => finish(false), [finish]);

  // aria-value* as of now (a window resize that keeps the width does not render)
  const syncAria = () => {
    const { min, max } = pane.limits();
    el.current?.setAttribute('aria-valuemin', String(min));
    el.current?.setAttribute('aria-valuemax', String(max));
    el.current?.setAttribute('aria-valuenow', String(pane.read()));
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || drag.current) return;
    syncAria();
    e.preventDefault();
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* capture is a nicety; the iframe guard does the rest */ }
    // Escape during a drag puts the pane back where it was.
    const onKey = (k: KeyboardEvent) => { if (k.key === 'Escape') { k.preventDefault(); k.stopPropagation(); finish(false); } };
    window.addEventListener('keydown', onKey, true);
    const from = pane.read();
    drag.current = { id: e.pointerId, x: e.clientX, from, last: from, onKey };
    document.documentElement.classList.add('rd-resizing');
    el.current?.classList.add('is-dragging');
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.id) return;
    const next = pane.fit(d.from + dir * (e.clientX - d.x), d.last, 'drag');
    if (next === d.last) return;
    d.last = next;
    pane.preview(next);
    el.current?.setAttribute('aria-valuenow', String(next));
  };
  const onPointerEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    if (drag.current && e.pointerId === drag.current.id) finish(true);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (drag.current) return;
    const now = pane.read();
    let next: number | null = null;
    const step = RESIZE_STEP * (e.shiftKey ? 4 : 1);
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') next = now + (e.key === 'ArrowRight' ? 1 : -1) * dir * step;
    else if (e.key === 'Home') next = pane.limits().min;
    else if (e.key === 'End') next = pane.limits().max;
    else if (e.key === 'Enter' && onToggle) { e.preventDefault(); onToggle(); return; }
    if (next == null) return;
    e.preventDefault();
    const fitted = pane.fit(next, now, 'key');
    if (fitted !== now) pane.commit(fitted);
  };

  return (
    <div ref={el} role="separator" aria-orientation="vertical" aria-label={label} aria-controls={controls}
      aria-valuenow={pane.width} aria-valuemin={pane.min} aria-valuemax={pane.max} tabIndex={0}
      className={`rs-handle${className ? ` ${className}` : ''}`} data-edge={edge} title={`${label} · ${t('common.resizeHint')}`}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerEnd} onPointerCancel={onPointerEnd}
      onLostPointerCapture={onPointerEnd} onDoubleClick={() => pane.reset()} onKeyDown={onKeyDown} onFocus={syncAria} />
  );
}
