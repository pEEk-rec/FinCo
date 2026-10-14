import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { cx } from './cx';

/** Flat surface with a hairline border. Cards never carry shadows. */
export function Card({
  children,
  className,
  as: Tag = 'section',
  labelledBy,
}: {
  children: ReactNode;
  className?: string;
  as?: 'section' | 'div' | 'article' | 'aside';
  labelledBy?: string;
}) {
  return (
    <Tag
      aria-labelledby={labelledBy}
      className={cx('rounded-card border border-hairline bg-surface', className)}
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
    <header className="flex min-h-12 items-center justify-between gap-4 border-b border-hairline px-6 py-3">
      <h2 id={id} className="label-mono text-ink-2">
        {label}
      </h2>
      <div className="flex items-center gap-2">
        {children}
        {action ? (
          <Link
            to={action.to}
            className="text-small text-ink-3 transition-colors duration-fast hover:text-ink"
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
          size === 'hero' ? 'text-hero font-light tracking-[-0.02em]' : 'text-h2',
        )}
      >
        {value}
      </span>
      {hint ? <span className="text-small text-ink-2">{hint}</span> : null}
    </div>
  );
}
