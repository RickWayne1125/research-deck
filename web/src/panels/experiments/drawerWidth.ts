// Width of the run drawer (RunDrawer.tsx), dragged by its left edge or set from the keyboard; remembered in this
// browser, kept within the panel.
export const DRAWER_KEY = 'rd.ex.drawerWidth';
export const DRAWER_DEFAULT = 560;
export const DRAWER_MIN = 380;
const KEEP_VISIBLE = 48;       // of the runs table, left of the drawer
const STEP = 24;
const BIG_STEP = 96;

export const drawerMax = (container: number): number => Math.max(DRAWER_MIN, Math.floor(container - KEEP_VISIBLE));

export const clampDrawerWidth = (w: number, container: number): number =>
  Math.round(Math.min(drawerMax(container), Math.max(DRAWER_MIN, w)));

/** The width a key on the resize handle asks for, or null for other keys. The handle is the drawer's left edge, so
 *  ← widens and → narrows; Shift takes bigger steps; Home / End go to the narrowest / widest; Enter resets. */
export function keyDrawerWidth(key: string, shift: boolean, w: number, container: number): number | null {
  const step = shift ? BIG_STEP : STEP;
  switch (key) {
    case 'ArrowLeft': return clampDrawerWidth(w + step, container);
    case 'ArrowRight': return clampDrawerWidth(w - step, container);
    case 'Home': return DRAWER_MIN;
    case 'End': return drawerMax(container);
    case 'Enter': return clampDrawerWidth(DRAWER_DEFAULT, container);
    default: return null;
  }
}

export function loadDrawerWidth(): number {
  try {
    const v = Number(localStorage.getItem(DRAWER_KEY));
    return Number.isFinite(v) && v >= DRAWER_MIN ? v : DRAWER_DEFAULT;
  } catch { return DRAWER_DEFAULT; }
}

/** null forgets the width (back to the default). */
export function saveDrawerWidth(w: number | null): void {
  try {
    if (w == null) localStorage.removeItem(DRAWER_KEY);
    else localStorage.setItem(DRAWER_KEY, String(Math.round(w)));
  } catch { /* storage unavailable */ }
}
