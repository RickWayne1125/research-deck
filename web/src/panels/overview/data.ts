// Quiet loaders for the engineering overview: each slice is optional, so a 404 or an error leaves `null`
// ("unavailable") instead of an error banner; slices reload on their topics.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useApp } from '../../state/app';

/** Call `fn` (debounced) whenever one of `topics` fires for the current project. */
export function useTopics(topics: string[], fn: () => void, delay = 350): void {
  const { onEvent } = useApp();
  const ref = useRef(fn);
  ref.current = fn;
  const key = topics.join(',');
  useEffect(() => {
    let timer = 0;
    const fire = () => { window.clearTimeout(timer); timer = window.setTimeout(() => ref.current(), delay); };
    const offs = key.split(',').filter(Boolean).map(topic => onEvent(topic, fire));
    return () => { offs.forEach(off => off()); window.clearTimeout(timer); };
  }, [key, delay, onEvent]);
}

/** undefined while loading, null when unavailable (404, error, unexpected shape), else the value. */
export function useQuiet<T>(fn: () => Promise<T>, deps: unknown[], topics: string[], valid?: (v: unknown) => boolean): T | null | undefined {
  const [value, setValue] = useState<T | null | undefined>(undefined);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const load = useCallback(() => {
    const mine = ++seq.current;
    fnRef.current().then(
      v => { if (mine === seq.current) setValue(valid && !valid(v) ? null : v); },
      () => { if (mine === seq.current) setValue(prev => (prev === undefined ? null : prev)); },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { setValue(undefined); load(); }, [load]);
  useTopics(topics, load, 600);
  return value;
}
