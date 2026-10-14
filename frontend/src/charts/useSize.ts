import { useEffect, useRef, useState } from 'react';

/** Track an element's content width (charts redraw on resize). */
export function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth || fallback);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [fallback]);
  return [ref, width] as const;
}

/** Charts draw in once per session per chart id, then morph in place. */
const drawn = new Set<string>();
export function firstDraw(chartId: string): boolean {
  if (drawn.has(chartId)) return false;
  drawn.add(chartId);
  return true;
}
