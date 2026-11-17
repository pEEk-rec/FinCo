import { motion, useReducedMotion } from 'motion/react';
import { useSearchParams } from 'react-router';

import { cx } from './cx';

export interface TabDef<T extends string> {
  id: T;
  label: string;
}

const spring = { type: 'spring', stiffness: 420, damping: 34 } as const;

/** A tab's state lives in the URL (`?tab=`), so back, reload and links all land on the right tab. */
export function useTabParam<T extends string>(
  tabs: readonly TabDef<T>[],
  fallback: T,
  name = 'tab',
): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const value = (tabs.find((t) => t.id === raw)?.id ?? fallback) as T;
  const set = (next: T) => {
    const p = new URLSearchParams(params);
    p.set(name, next);
    setParams(p, { replace: true });
  };
  return [value, set];
}

/** Underlined tabs whose indicator slides to the chosen one. */
export function Tabs<T extends string>({
  id,
  tabs,
  value,
  onChange,
  label,
}: {
  id: string;
  tabs: readonly TabDef<T>[];
  value: T;
  onChange: (next: T) => void;
  label: string;
}) {
  const reduce = useReducedMotion();
  return (
    <div
      role="tablist"
      aria-label={label}
      className="no-print -mx-1 flex gap-1 overflow-x-auto border-b border-hairline px-1"
    >
      {tabs.map((t) => {
        const on = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.id)}
            className={cx(
              'relative h-11 shrink-0 px-3.5 text-[14px] font-semibold transition-colors duration-fast',
              on ? 'text-ink' : 'text-ink-3 hover:text-ink-2',
            )}
          >
            {t.label}
            {on ? (
              <motion.span
                layoutId={`${id}-tab`}
                aria-hidden
                className="absolute inset-x-2 -bottom-px h-[2.5px] rounded-full bg-brand"
                transition={reduce ? { duration: 0 } : spring}
              />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** Two to four options in a pill, with a thumb that glides between them. */
export function Segmented<T extends string>({
  id,
  options,
  value,
  onChange,
  label,
}: {
  id: string;
  options: readonly TabDef<T>[];
  value: T;
  onChange: (next: T) => void;
  label: string;
}) {
  const reduce = useReducedMotion();
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex rounded-[14px] bg-surface-sunken p-1"
    >
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.id)}
            className={cx(
              'relative h-8 rounded-[10px] px-4 text-[13.5px] font-semibold transition-colors duration-fast',
              on ? 'text-ink' : 'text-ink-3 hover:text-ink-2',
            )}
          >
            {on ? (
              <motion.span
                layoutId={`${id}-thumb`}
                aria-hidden
                className="absolute inset-0 rounded-[10px] bg-surface shadow-[0_1px_3px_rgba(31,26,23,0.12)]"
                transition={reduce ? { duration: 0 } : spring}
              />
            ) : null}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}
