// Shared building blocks. Panels compose these with the classes in styles/base.css instead of inventing their own.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Icon, type IconName } from './icons';
import { ResizeHandle, useResizableWidth } from './resize';
import { useT } from '../i18n';

/** A Radix Themes button (styles/base.css .btn): soft gray by default; primary and accent are solid in the accent,
 *  soft is the accent's soft variant, ghost has no fill, danger is soft red. sm is Radix size 1. */
export function Button({ icon, children, variant, size, active, ...rest }: {
  icon?: IconName | string; variant?: 'primary' | 'accent' | 'soft' | 'ghost' | 'danger'; size?: 'sm'; active?: boolean; children?: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = ['btn', variant, size, active ? 'active' : '', rest.className].filter(Boolean).join(' ');
  return <button type="button" {...rest} className={cls}>{icon && <Icon name={icon} />}{children}</button>;
}

export function IconButton({ icon, label, className, ...rest }: { icon: IconName | string; label: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" aria-label={label} title={label} {...rest} className={className ? `icon-btn ${className}` : 'icon-btn'}><Icon name={icon} /></button>;
}

/** A Radix segmented control (styles/base.css .seg); sm is Radix size 1. */
export function Segmented<T extends string>({ value, options, onChange, ariaLabel, size }: {
  value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; ariaLabel?: string; size?: 'sm';
}) {
  return (
    <div className={size ? `seg ${size}` : 'seg'} role="group" aria-label={ariaLabel}>
      {options.map(o => (
        <button key={o.value} type="button" aria-pressed={o.value === value} title={o.title} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export type BadgeTone = 'process' | 'data' | 'ok' | 'emphasis' | 'warn' | 'stale' | 'danger' | 'accent' | 'solid' | 't-lit' | 't-code' | 't-fig' | 't-exp';
/** A Radix Badge (styles/base.css .badge): soft by default, or the surface or outline variant; the tone picks the color. */
export function Badge({ tone, variant, children, title }: { tone?: BadgeTone; variant?: 'surface' | 'outline'; children: ReactNode; title?: string }) {
  return <span className={['badge', tone, variant].filter(Boolean).join(' ')} title={title}>{children}</span>;
}

/** The Radix spinner: eight leaves fading in turn (an empty .spinner elsewhere is a plain ring). */
export function Spinner({ size, label = 'loading' }: { size?: 'sm'; label?: string }) {
  return (
    <span className={size ? `spinner ${size}` : 'spinner'} role="status" aria-label={label}>
      <i /><i /><i /><i /><i /><i /><i /><i />
    </span>
  );
}

export function Empty({ icon = 'info', title, children, action }: { icon?: IconName | string; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} size={22} />
      <div className="h3">{title}</div>
      {children && <div className="muted" style={{ maxWidth: 420 }}>{children}</div>}
      {action}
    </div>
  );
}

/** A view's head: its title (Radix Heading 7; size "doc" is a document's or a figure's title, Heading 5), a badge
 *  beside the title, a line under it, and the view's controls on the right. */
export function PanelHead({ title, subtitle, badge, size, children }: {
  title: ReactNode; subtitle?: ReactNode; badge?: ReactNode; size?: 'doc'; children?: ReactNode;
}) {
  return (
    <div className={size ? `panel-head ${size}` : 'panel-head'}>
      <div className="col" style={{ gap: 2, minWidth: 0 }}>
        <div className="panel-head-title"><h1 className="h1 ellipsis">{title}</h1>{badge}</div>
        {subtitle && <div className="muted ellipsis" style={{ fontSize: 'var(--fs-sm)' }}>{subtitle}</div>}
      </div>
      <div className="grow" />
      <div className="row wrap panel-head-tools">{children}</div>
    </div>
  );
}

export function Dialog({ title, onClose, children, footer, width }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number }) {
  const t = useT();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" style={width ? { width: `min(${width}px, 100%)` } : undefined}>
        <div className="dialog-head"><h2 className="h2 grow">{title}</h2><IconButton icon="close" label={t('common.close')} onClick={onClose} /></div>
        <div className="dialog-body">{children}</div>
        {footer && <div className="dialog-foot">{footer}</div>}
      </div>
    </div>
  );
}

/** A button that opens a small menu below it. `portal`: the menu is drawn at the top of the page (fixed under the
 *  button), for a button inside a box that clips or covers it, such as the scrolling navigation. */
export function Menu({ button, children, align = 'right', portal = false }: {
  button: (open: boolean, toggle: () => void) => ReactNode; children: (close: () => void) => ReactNode; align?: 'left' | 'right'; portal?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<CSSProperties | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const at = e.target as Node;
      if (!ref.current?.contains(at) && !pop.current?.contains(at)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);
  // A portal menu follows its button while the window resizes or anything scrolls.
  useLayoutEffect(() => {
    if (!open || !portal) { setPlace(null); return; }
    const follow = () => {
      const r = ref.current?.getBoundingClientRect();
      if (!r) return;
      const top = r.bottom + 6;
      setPlace({ position: 'fixed', top, maxHeight: Math.max(160, window.innerHeight - top - 8), overflow: 'auto',
                 ...(align === 'left' ? { left: r.left, maxWidth: window.innerWidth - r.left - 8 }
                   : { right: Math.max(8, window.innerWidth - r.right), maxWidth: r.right - 8 }) });
    };
    follow();
    window.addEventListener('resize', follow);
    window.addEventListener('scroll', follow, true);
    return () => { window.removeEventListener('resize', follow); window.removeEventListener('scroll', follow, true); };
  }, [open, portal, align]);
  const close = () => setOpen(false);
  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-flex' }}>
      {button(open, () => setOpen(o => !o))}
      {open && !portal && <div ref={pop} className="popover" style={{ top: 'calc(100% + 6px)', [align]: 0 }}>{children(close)}</div>}
      {open && portal && place && createPortal(<div ref={pop} className="popover" style={place}>{children(close)}</div>, document.body)}
    </div>
  );
}

/** Two panes with a draggable divider (components/resize.tsx); the left width is remembered under storageKey. */
export function Split({ left, right, initial = 320, min = 200, max = 720, storageKey, label }: {
  left: ReactNode; right: ReactNode; initial?: number; min?: number; max?: number; storageKey?: string; label?: string;
}) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  // the right pane keeps at least 240 px of the container
  const fits = () => { const room = box.current?.clientWidth; return room ? Math.max(min, Math.min(max, room - 240)) : max; };
  const pane = useResizableWidth(storageKey ?? null, initial, min, fits, { cssVar: '--split-w', target: box });
  return (
    <div ref={box} className="split" style={pane.style}>
      <div className="split-a">
        <div className="split-scroll">{left}</div>
        <ResizeHandle pane={pane} edge="right" label={label ?? t('common.resize')} />
      </div>
      <div className="split-b">{right}</div>
    </div>
  );
}

/** Async loader with loading/error states: const { data, error, loading, reload } = useLoad(() => get(...), [deps]). */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean; reload: () => void; setData: (d: T | null) => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn().then(d => { if (alive) { setData(d); setError(null); } })
      .catch(e => { if (alive) setError(String(e?.message ?? e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN(x => x + 1), setData };
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  const t = useT();
  return <div className="notice accent" role="alert"><Icon name="warn" /> <span className="grow">{error}</span>{onRetry && <Button size="sm" onClick={onRetry}>{t('common.retry')}</Button>}</div>;
}

export function Kbd({ children }: { children: ReactNode }) { return <kbd>{children}</kbd>; }
