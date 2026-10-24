import { ArrowDownLeft, ArrowUpRight, MagnifyingGlass } from '@phosphor-icons/react';
import * as Dialog from '@radix-ui/react-dialog';
import { motion } from 'motion/react';
import { useMemo, useState } from 'react';

import { ApiError, type PromptView } from '../../api/client';
import { useCaptureWrites, useCategories, useUndo } from '../../api/hooks';
import { formatDay, formatTime } from '../../format/date';
import { formatINR } from '../../format/money';
import { motion as tokens } from '../../tokens/tokens';
import { Badge } from '../Badge';
import { Button } from '../Button';
import { useToast } from '../Toast';

/** Plain words for why a payment is being asked about, or held back. */
const WHY: Record<string, string> = {
  unknown_merchant: 'A payee I have not seen before',
  person_unclear: 'A person, so it could be anything',
  cash_purpose: 'Cash, so I cannot tell what it was for',
  credit_needs_you: 'Money came in and I am not sure what from',
  quiet_hours: 'Held back during your quiet hours',
  daily_budget: 'Held back so you are not interrupted too much today',
  counterparty_cooldown: 'Asked about this payee a little while ago',
};

export const why = (reason: string): string => WHY[reason] ?? 'I could not tell what this was';

const humanise = (code: string): string =>
  code.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

/** Tag a payment, then offer to take it back. Shared by the inbox, the overlay and Today. */
export function useTagPayment() {
  const writes = useCaptureWrites();
  const undo = useUndo();
  const toast = useToast();
  return async (
    prompt: Pick<PromptView, 'event'>,
    choice: { label: string; name: string; rank: number; credit?: boolean; note?: string },
  ): Promise<boolean> => {
    try {
      const out = await writes.label.mutateAsync({
        event_id: prompt.event.id,
        ...(choice.credit ? { credit_kind: choice.label } : { category_id: choice.label }),
        rank_picked: choice.rank,
        ...(choice.note ? { note: choice.note } : {}),
      });
      toast({
        message: `Tagged ${choice.name}`,
        onUndo: out.audit_event_id
          ? async () => {
              await undo.mutateAsync(out.audit_event_id as string);
              await writes.label.reset();
            }
          : undefined,
      });
      return true;
    } catch (error) {
      toast({
        message: error instanceof ApiError ? error.message : 'That did not save. Try again.',
        tone: 'negative',
      });
      return false;
    }
  };
}

export function PaymentPrompt({
  prompt,
  creditKinds,
  shortcuts = false,
  onDone,
  onLater,
  openSheet = false,
}: {
  prompt: PromptView;
  creditKinds: string[];
  /** Show 1, 2, 3 on the guess buttons (the page listens for those keys). */
  shortcuts?: boolean;
  onDone?: () => void;
  /** Show a Later button (the overlay's way of sending this to the inbox). */
  onLater?: () => void;
  /** Open the Other sheet straight away (a tapped notification lands here). */
  openSheet?: boolean;
}) {
  const { event } = prompt;
  const credit = event.direction === 'credit';
  const tag = useTagPayment();
  const [busy, setBusy] = useState<string | null>(null);
  const [sheet, setSheet] = useState(openSheet);

  const choose = async (label: string, name: string, rank: number) => {
    setBusy(label);
    const ok = await tag(prompt, { label, name, rank, credit });
    setBusy(null);
    if (ok) onDone?.();
  };

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: tokens.base / 1000, ease: tokens.easeArray }}
      className="list-none"
    >
      <article
        aria-label={`${credit ? 'Received' : 'Paid'} ${formatINR(event.amount_paise, { paise: 'auto' })} ${credit ? 'from' : 'to'} ${event.display_name}`}
        className="rounded-card border-2 border-ink bg-surface p-5 shadow-[5px_5px_0_var(--color-ink)]"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span
              aria-hidden
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${credit ? 'bg-positive-tint text-positive' : 'bg-brand-tint text-brand'}`}
            >
              {credit ? <ArrowDownLeft size={20} /> : <ArrowUpRight size={20} />}
            </span>
            <div className="min-w-0">
              <p className="truncate text-[17px] font-bold">{event.display_name}</p>
              <p className="text-small text-ink-3">
                {[
                  event.bank ? event.bank.toUpperCase() : null,
                  formatDay(event.occurred_at),
                  formatTime(event.occurred_at),
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            </div>
          </div>
          <div className="text-right">
            <p
              className={`tabular serif-light text-[36px] leading-none ${credit ? 'text-positive' : ''}`}
            >
              {credit ? '+' : ''}
              {formatINR(event.amount_paise, { paise: 'auto' })}
            </p>
            <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
              {event.simulated ? <Badge tone="agent">Simulated payment</Badge> : null}
              {prompt.decision === 'inbox' ? <Badge>Waiting for you</Badge> : null}
            </div>
          </div>
        </div>

        <p className="mt-3 text-small text-ink-3">{why(prompt.reason)}</p>

        <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="What was it?">
          {prompt.guesses.map((g, i) => (
            <Button
              key={g.label}
              variant={i === 0 ? 'primary' : 'secondary'}
              busy={busy === g.label}
              disabled={busy !== null && busy !== g.label}
              title={g.reasons.length ? g.reasons.join(', ') : undefined}
              onClick={() => void choose(g.label, g.name, i + 1)}
            >
              {shortcuts ? (
                <kbd aria-hidden className="mr-1 rounded bg-black/10 px-1 text-[11px]">
                  {i + 1}
                </kbd>
              ) : null}
              {g.name}
            </Button>
          ))}
          <Button variant="text" onClick={() => setSheet(true)}>
            Other…
          </Button>
          {onLater ? (
            <Button variant="text" onClick={onLater}>
              Later
            </Button>
          ) : null}
        </div>
      </article>
      {sheet ? (
        <QuickSheet
          prompt={prompt}
          creditKinds={creditKinds}
          onClose={() => setSheet(false)}
          onPick={async (label, name, note) => {
            const ok = await tag(prompt, { label, name, rank: 0, credit, note });
            if (ok) {
              setSheet(false);
              onDone?.();
            }
          }}
        />
      ) : null}
    </motion.li>
  );
}

/** Every category, searchable, with a note and what to do about this payee in future. */
export function QuickSheet({
  prompt,
  creditKinds,
  onClose,
  onPick,
}: {
  prompt: PromptView;
  creditKinds: string[];
  onClose: () => void;
  onPick: (label: string, name: string, note?: string) => Promise<void>;
}) {
  const { event } = prompt;
  const credit = event.direction === 'credit';
  const categories = useCategories();
  const writes = useCaptureWrites();
  const toast = useToast();
  const [q, setQ] = useState('');
  const [note, setNote] = useState('');
  const options = useMemo(() => {
    const all = credit
      ? creditKinds.map((k) => ({ id: k, name: humanise(k) }))
      : (categories.data ?? []).map((c) => ({ id: c.id, name: c.name }));
    const needle = q.trim().toLowerCase();
    return needle ? all.filter((o) => o.name.toLowerCase().includes(needle)) : all;
  }, [credit, creditKinds, categories.data, q]);

  const setPolicy = (policy: 'always_ask' | 'always_category', categoryId?: string) =>
    writes.policy.mutate(
      {
        counterparty_key: event.counterparty_key,
        policy,
        ...(categoryId ? { category_id: categoryId } : {}),
      },
      {
        onSuccess: () =>
          toast({
            message:
              policy === 'always_ask'
                ? `I will always ask about ${event.display_name}`
                : `${event.display_name} will always be tagged the same`,
          }),
        onError: (e) => toast({ message: (e as Error).message, tone: 'negative' }),
      },
    );

  return (
    <Dialog.Root open onOpenChange={(o) => (!o ? onClose() : undefined)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-card border border-hairline bg-surface p-6 shadow-popover">
          <Dialog.Title className="serif-light text-[24px]">What was this?</Dialog.Title>
          <Dialog.Description className="text-small text-ink-3">
            {formatINR(event.amount_paise, { paise: 'auto' })} {credit ? 'from' : 'to'}{' '}
            {event.display_name}
          </Dialog.Description>
          <label className="mt-4 flex h-10 items-center gap-2 rounded-control border border-input-border bg-surface px-3">
            <MagnifyingGlass size={16} aria-hidden className="text-ink-3" />
            <input
              autoFocus
              aria-label="Search categories"
              className="w-full bg-transparent text-[14px] outline-none placeholder:text-ink-3"
              placeholder="Search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          <ul
            className="mt-3 grid max-h-52 grid-cols-2 gap-1.5 overflow-y-auto"
            aria-label="Categories"
          >
            {options.map((o) => (
              <li key={o.id}>
                <button
                  type="button"
                  onClick={() => void onPick(o.id, o.name, note.trim() || undefined)}
                  className="w-full rounded-control border border-hairline px-3 py-2 text-left text-[14px] transition-colors hover:border-brand hover:bg-brand-tint"
                >
                  {o.name}
                </button>
              </li>
            ))}
            {options.length === 0 ? (
              <li className="col-span-2 text-small text-ink-3">Nothing matches.</li>
            ) : null}
          </ul>
          <label className="mt-4 flex flex-col gap-1.5">
            <span className="label-mono text-ink-3">A note (optional)</span>
            <input
              className="h-10 rounded-control border border-input-border bg-surface px-3 text-[14px]"
              maxLength={200}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          {event.counterparty_kind === 'person' ? (
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-hairline pt-4">
              <span className="text-small text-ink-3">For {event.display_name}:</span>
              <Button size="sm" variant="text" onClick={() => setPolicy('always_ask')}>
                Always ask me
              </Button>
              {prompt.guesses[0] && !credit ? (
                <Button
                  size="sm"
                  variant="text"
                  onClick={() => setPolicy('always_category', prompt.guesses[0]?.label)}
                >
                  Always {prompt.guesses[0].name}
                </Button>
              ) : null}
            </div>
          ) : null}
          <div className="mt-4 flex justify-end">
            <Button variant="text" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
