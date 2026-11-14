// Layout by size. The window: a phone (styles/responsive.css uses the same width) gets the app bar and the tab bar
// instead of the navigation. The main column: its width as a class of layout for the views' CSS (html[data-main]),
// so the views lay out by the room they have, whatever takes the rest of the window (the navigation, the conversation).
import { useEffect, useState } from 'react';

/** A phone-sized window (keep in step with the @media rules in styles/responsive.css). */
export const PHONE_QUERY = '(max-width: 640px)';

/** Whether the window matches `query`, following it as the window changes. */
export function useMedia(query: string): boolean {
  const [on, setOn] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const update = () => setOn(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, [query]);
  return on;
}

export type MainClass = 'phone' | 'narrow' | 'medium' | 'wide';

/** phone under 560 px, narrow under 900, medium under 1200, else wide */
export function mainClass(width: number): MainClass {
  return width < 560 ? 'phone' : width < 900 ? 'narrow' : width < 1200 ? 'medium' : 'wide';
}
