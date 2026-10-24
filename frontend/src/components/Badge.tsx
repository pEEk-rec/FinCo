import type { ReactNode } from 'react';

import { copy } from '../copy/en';
import { categoryColors } from '../format/category';
import { formatConfidence } from '../format/percent';
import { cx } from './cx';

export type Tone = 'neutral' | 'positive' | 'attention' | 'negative' | 'agent';

const TONES: Record<Tone, string> = {
  neutral: 'bg-surface-sunken text-ink-2',
  positive: 'bg-positive-tint text-positive',
  attention: 'bg-attention-tint text-attention',
  negative: 'bg-negative-tint text-negative',
  agent: 'bg-agent-tint text-agent',
};

/** Small uppercase mono tag for status and data labels. */
export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        'label-mono inline-flex h-6 shrink-0 items-center rounded-chip px-2.5 whitespace-nowrap',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Selectable chip (time ranges, filters). Radius 999 is reserved for chips. */
export function Chip({
  selected = false,
  onClick,
  children,
}: {
  selected?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cx(
        'inline-flex h-7 items-center rounded-chip px-3 text-small transition-colors duration-fast',
        selected
          ? 'bg-ink text-ink-inverse'
          : 'bg-transparent text-ink-2 ring-1 ring-ink/15 ring-inset hover:bg-surface-sunken hover:text-ink',
      )}
    >
      {children}
    </button>
  );
}

/** Category identity pill: tinted background, dark text of the same hue, always labelled. */
export function CategoryPill({
  categoryId,
  name,
}: {
  categoryId: string | null;
  name: string | null;
}) {
  const { index } = categoryColors(categoryId);
  return (
    <span
      className="inline-flex h-6 max-w-[11rem] items-center gap-1.5 rounded-chip px-2.5 text-small"
      style={{
        backgroundColor: `var(--color-cat-${index}-bg)`,
        color: `var(--color-cat-${index}-fg)`,
      }}
    >
      <span
        aria-hidden
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: `var(--color-cat-${index}-mark)` }}
      />
      <span className="truncate">{name ?? copy.common.uncategorised}</span>
    </span>
  );
}

/**
 * Where a category came from. AI-derived labels belong to the agent (violet); confidence is
 * shown for AI rows only, exactly as the API reported it.
 */
export function SourceBadge({
  source,
  confidence,
}: {
  source: string;
  confidence?: number | null;
}) {
  const label = copy.common.source[source] ?? source;
  const isAi = source === 'llm';
  return (
    <span className="inline-flex items-center gap-1.5">
      <Badge tone={isAi ? 'agent' : 'neutral'}>{label}</Badge>
      {isAi && confidence != null ? (
        <span
          className="tabular text-small text-ink-3"
          title={copy.common.confidence(formatConfidence(confidence))}
        >
          {formatConfidence(confidence)}
        </span>
      ) : null}
    </span>
  );
}
