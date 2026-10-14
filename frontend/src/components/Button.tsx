import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cx } from './cx';

export type ButtonVariant = 'primary' | 'secondary' | 'text' | 'danger';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
  icon?: ReactNode;
  busy?: boolean;
}

const VARIANTS: Record<ButtonVariant, string> = {
  // The only filled button in the system: ink, one per view.
  primary: 'bg-ink text-ink-inverse hover:bg-ink-2 disabled:bg-ink-3',
  secondary:
    'bg-surface text-ink border border-hairline-strong hover:bg-surface-hover hover:border-input-border',
  text: 'bg-transparent text-ink-2 hover:text-ink hover:bg-surface-sunken',
  danger: 'bg-surface text-negative border border-hairline-strong hover:bg-negative-tint',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    icon,
    busy = false,
    className,
    children,
    disabled,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-control font-medium whitespace-nowrap',
        'transition-colors duration-fast ease-out-soft disabled:cursor-not-allowed disabled:opacity-60',
        size === 'sm' ? 'h-8 px-3 text-small' : 'h-10 px-4 text-[14px]',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {icon ? (
        <span aria-hidden className="-ml-0.5 flex">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  );
});
