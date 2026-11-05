// Two panes split by a ratio of the container (remembered), stacked vertically when the container is narrow.
// The editor's width depends on the dock and the style panel, so a fixed pixel split would hide the preview.
// The divider is the shared ResizeHandle (components/resize.tsx), driven through a ratio ↔ px adapter.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ResizeHandle, type Resizable } from '../../components/resize';
import { useT } from '../../i18n';

const STACK_BELOW_PX = 760;
const LO = 0.2;
const HI = 0.8;
const clampRatio = (r: number) => Math.min(HI, Math.max(LO, r));

function readRatio(key: string, initial: number): number {
  try { const v = Number(localStorage.getItem(key)); return v >= LO && v <= HI ? v : initial; } catch { return initial; }
}
function writeRatio(key: string, r: number | null): void {
  try { if (r == null) localStorage.removeItem(key); else localStorage.setItem(key, String(r)); } catch { /* storage unavailable */ }
}

export function RatioSplit({ left, right, storageKey, initial = 0.5, label }: {
  left: ReactNode; right: ReactNode; storageKey: string; initial?: number; label?: string;
}) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  const a = useRef<HTMLDivElement>(null);
  const [ratio, setRatio] = useState(() => readRatio(storageKey, initial));
  const ratioRef = useRef(ratio);
  ratioRef.current = ratio;
  const [boxW, setBoxW] = useState(0);
  const stacked = boxW > 0 && boxW < STACK_BELOW_PX;

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setBoxW(Math.round(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // The handle works in px of the container; the split keeps the ratio.
  const room = () => box.current?.clientWidth || boxW || 1;
  const setRatioNow = (r: number | null) => {
    const next = r == null ? initial : clampRatio(r);
    ratioRef.current = next;
    if (a.current) a.current.style.flexBasis = `${next * 100}%`;
    setRatio(next);
    writeRatio(storageKey, r == null ? null : next);
  };
  const pane: Resizable = {
    width: Math.round(ratio * boxW), min: Math.round(LO * boxW), max: Math.round(HI * boxW),
    read: () => Math.round(ratioRef.current * room()),
    limits: () => ({ min: Math.round(LO * room()), max: Math.round(HI * room()) }),
    fit: (w) => Math.round(clampRatio(w / room()) * room()),
    preview: (w) => { if (a.current) a.current.style.flexBasis = `${(w / room()) * 100}%`; },
    commit: (w) => setRatioNow(w / room()),
    reset: () => setRatioNow(null),
  };

  return (
    <div ref={box} className={`vz-split ${stacked ? 'is-stacked' : ''}`}>
      <div ref={a} className="vz-split-a" style={stacked ? undefined : { flexBasis: `${ratio * 100}%` }}>
        <div className="vz-split-a-inner">{left}</div>
        {!stacked && boxW > 0 && <ResizeHandle pane={pane} edge="right" label={label ?? t('common.resize')} />}
      </div>
      <div className="vz-split-b">{right}</div>
    </div>
  );
}
