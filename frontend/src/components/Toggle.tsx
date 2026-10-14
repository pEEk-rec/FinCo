import * as Switch from '@radix-ui/react-switch';
import { useId } from 'react';

/** Explicit on/off with a visible label and optional hint (Radix Switch, fully restyled). */
export function Toggle({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <label htmlFor={id} className="flex flex-col gap-0.5">
        <span className="text-[14px] text-ink">{label}</span>
        {hint ? <span className="text-small text-ink-3">{hint}</span> : null}
      </label>
      <Switch.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className="relative mt-0.5 h-5 w-9 shrink-0 rounded-chip border border-input-border bg-surface-sunken transition-colors duration-fast data-[state=checked]:border-ink data-[state=checked]:bg-ink disabled:opacity-50"
      >
        <Switch.Thumb className="block size-3.5 translate-x-0.5 rounded-full bg-ink-3 transition-transform duration-fast ease-out-soft data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-surface" />
      </Switch.Root>
    </div>
  );
}
