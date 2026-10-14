import { WarningCircle } from '@phosphor-icons/react';
import type { ReactNode } from 'react';

import { copy } from '../copy/en';
import { Button } from './Button';
import { cx } from './cx';

/** Loading placeholder shaped like the content it replaces. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cx('animate-pulse rounded-[6px] bg-surface-sunken', className)} />
  );
}

/** Several skeleton lines with a polite loading announcement. */
export function SkeletonBlock({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div
      role="status"
      aria-label={copy.common.loading}
      className={cx('flex flex-col gap-3', className)}
    >
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cx('h-4', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}

/** Calm empty state: a sentence and at most one action. No illustrations. */
export function EmptyState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 py-2">
      <p className="max-w-prose text-body text-ink-2">{message}</p>
      {action}
    </div>
  );
}

/** Failed request: a readable message, the error code and a retry. Never stale values. */
export function ErrorState({
  code,
  message,
  onRetry,
}: {
  code: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 py-2">
      <div className="flex items-center gap-2 text-negative">
        <WarningCircle size={18} aria-hidden />
        <span className="font-medium">{copy.common.errorTitle}</span>
      </div>
      {message ? <p className="max-w-prose text-small text-ink-2">{message}</p> : null}
      <span className="label-mono text-ink-3">{copy.common.errorCode(code)}</span>
      {onRetry ? (
        <Button size="sm" onClick={onRetry}>
          {copy.common.retry}
        </Button>
      ) : null}
    </div>
  );
}

/** Not enough data is a designed state, not an error: it says what is missing. */
export function InsufficientDataState({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-3 rounded-control border border-dashed border-hairline-strong bg-canvas px-4 py-3">
      <span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-ink-3" />
      <p className="text-small text-ink-2">{message}</p>
    </div>
  );
}
