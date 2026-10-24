import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { cx } from './cx';

/** A flat white card with a crisp edge. `tone` makes it the screen's one loud slab. */
export function Card({
  children,
  className,
  as: Tag = 'section',
  labelledBy,
  tone = 'plain',
}: {
  children: ReactNode;
  className?: string;
  as?: 'section' | 'div' | 'article' | 'aside';
  labelledBy?: string;
  tone?: 'plain' | 'slab' | 'sun';
}) {
  return (
    <Tag
      aria-labelledby={labelledBy}
      className={cx(
        tone === 'slab' ? 'slab' : tone === 'sun' ? 'slab-sun' : 'glass',
        'rounded-card',
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/** Card header: mono uppercase label on the left, an optional quiet link on the right. */
export function CardHeader({
  id,
  label,
  action,
  children,
}: {
  id?: string;
  label: string;
  action?: { to: string; text: string };
  children?: ReactNode;
}) {
  return (
    <header className="flex min-h-12 items-center justify-between gap-4 border-b-[1.5px] border-ink/10 px-6 py-3">
      <h2 id={id} className="label-mono text-ink">
        {label}
      </h2>
      <div className="flex items-center gap-2">
        {children}
        {action ? (
          <Link
            to={action.to}
            className="text-small font-semibold text-ink underline-offset-4 transition-colors duration-fast hover:underline"
          >
            {action.text}
            <span aria-hidden> →</span>
          </Link>
        ) : null}
      </div>
    </header>
  );
}

/** A labelled figure. `value` is already formatted by the caller from an API field. */
export function Stat({
  label,
  value,
  hint,
  size = 'md',
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  size?: 'md' | 'hero';
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="label-mono text-ink-3">{label}</span>
      <span
        className={cx(
          'tabular text-ink',
          size === 'hero' ? 'text-hero tracking-[-0.04em]' : 'text-h2',
        )}
      >
        {value}
      </span>
      {hint ? <span className="text-small text-ink-2">{hint}</span> : null}
    </div>
  );
}
