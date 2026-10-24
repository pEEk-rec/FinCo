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
  // The only filled button in the system: liquid aqua, one per view.
  primary: 'pop bg-brand text-brand-ink [--edge:var(--color-brand-edge)] disabled:bg-ink-3',
  secondary: 'pop bg-surface text-ink border-2 border-ink [--edge:var(--color-ink)]',
  text: 'bg-transparent text-ink-2 hover:text-ink hover:bg-surface-sunken',
  danger: 'pop bg-surface text-negative border-2 border-negative [--edge:var(--color-negative)]',
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
        'inline-flex items-center justify-center gap-2 rounded-control font-bold whitespace-nowrap',
        'transition-[color,background-color,box-shadow,transform] duration-fast ease-out-soft disabled:cursor-not-allowed disabled:opacity-60',
        size === 'sm' ? 'h-9 px-3.5 text-small' : 'h-12 px-6 text-[15px]',
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
