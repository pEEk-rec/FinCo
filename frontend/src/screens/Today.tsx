import { ArrowDownLeft, ArrowUpRight, CaretLeft, CaretRight } from '@phosphor-icons/react';
import { AnimatePresence, motion } from 'motion/react';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import { ApiError, type PromptView, type TodayItem } from '../api/client';
import { useCaptureInbox, useToday } from '../api/hooks';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { PaymentPrompt, QuickSheet, useTagPayment } from '../components/capture/PaymentPrompt';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { formatDayHeader, formatTime } from '../format/date';
import { formatINR } from '../format/money';
import { LiquidVessel } from '../motion/Liquid';
import { NumberTicker } from '../motion/NumberTicker';

/** The prompt shape the shared components expect, rebuilt from a day's item. */
function asPrompt(item: TodayItem): PromptView | null {
  if (!item.event || !item.prompt_id) return null;
  return {
    prompt_id: item.prompt_id,
    event: item.event,
    decision: 'ask',
    reason: item.reason_code ?? '',
    guesses: item.guesses,
    status: (item.prompt_status ?? 'pending') as PromptView['status'],
    created_at: item.time,
    expires_at: null,
  };
}

function shiftDay(day: string, by: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + by);
  return d.toISOString().slice(0, 10);
}

function Row({ item, creditKinds }: { item: TodayItem; creditKinds: string[] }) {
  const credit = item.direction === 'credit';
  const prompt = asPrompt(item);
  const tag = useTagPayment();
  const [changing, setChanging] = useState(false);
  return (
    <li
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hairline py-3 last:border-b-0 ${item.reversed ? 'opacity-60' : ''}`}
    >
      <span
        aria-hidden
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${credit ? 'bg-positive-tint text-positive' : 'bg-surface-sunken text-ink-2'}`}
      >
        {credit ? <ArrowDownLeft size={18} /> : <ArrowUpRight size={18} />}
      </span>
      <div className="min-w-0 flex-1">
        <p className={`truncate text-[15px] ${item.reversed ? 'line-through' : ''}`}>{item.name}</p>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-small text-ink-3">
          <span>{formatTime(item.time)}</span>
          {item.category_name ? <Badge tone="neutral">{item.category_name}</Badge> : null}
          {item.reason ? <span>{item.reason}</span> : null}
          {item.reversed ? <Badge tone="attention">Reversed</Badge> : null}
          {item.simulated ? <Badge tone="agent">Simulated</Badge> : null}
          {!item.verified && !item.simulated ? <Badge>Not in your bank data yet</Badge> : null}
        </p>
      </div>
      <span className={`tabular text-[16px] ${credit ? 'text-positive' : ''}`}>
        {credit ? '+' : ''}
        {formatINR(item.amount_paise, { paise: 'auto' })}
      </span>
      {prompt && item.group !== 'needs_you' && !item.reversed ? (
        <Button size="sm" variant="text" onClick={() => setChanging(true)}>
          Change
        </Button>
      ) : null}
      {item.needs_review_link ? (
        <Link to="/review" className="text-small text-brand underline-offset-2 hover:underline">
          Choose a category
        </Link>
      ) : null}
      {changing && prompt ? (
        <QuickSheet
          prompt={prompt}
          creditKinds={creditKinds}
          onClose={() => setChanging(false)}
          onPick={async (label, name, note) => {
            const ok = await tag(prompt, { label, name, rank: 0, credit, note });
            if (ok) setChanging(false);
          }}
        />
      ) : null}
    </li>
  );
}

function Section({
  id,
  title,
  hint,
  children,
}: {
  id: string;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="rise">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 id={id} className="serif-light text-[24px]">
          {title}
        </h2>
        {hint ? <span className="text-small text-ink-3">{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function TodayScreen() {
  const [params, setParams] = useSearchParams();
  const day = params.get('day') ?? undefined;
  const today = useToday(day);
  const inbox = useCaptureInbox();
  const creditKinds = inbox.data?.credit_kinds ?? [];
  const view = today.data;
  const go = (to: string | undefined) => setParams(to ? { day: to } : {});

  return (
    <Page
      title={
        view?.is_today ? (
          <>
            Today, <em>what is left to tag</em>
          </>
        ) : (
          <>
            {view ? formatDayHeader(`${view.day}T06:30:00Z`) : 'A day'}, <em>looked back on</em>
          </>
        )
      }
      lead="Every payment in and out for the day, in time order. Tag what is left, or change anything that was tagged for you."
      actions={
        view ? (
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="secondary"
              aria-label="The day before"
              onClick={() => go(shiftDay(view.day, -1))}
            >
              <CaretLeft size={14} />
            </Button>
            {!view.is_today ? (
              <Button size="sm" variant="secondary" onClick={() => go(undefined)}>
                Today
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="secondary"
              aria-label="The day after"
              disabled={view.is_today}
              onClick={() => go(shiftDay(view.day, 1))}
            >
              <CaretRight size={14} />
            </Button>
          </div>
        ) : undefined
      }
    >
      {today.isPending ? (
        <Card className="p-6">
          <SkeletonBlock lines={5} />
        </Card>
      ) : today.error ? (
        <ErrorState
          code={today.error instanceof ApiError ? today.error.code : 'UNKNOWN'}
          message={today.error.message}
          onRetry={() => void today.refetch()}
        />
      ) : view ? (
        <div className="flex flex-col gap-10">
          <div className="grid gap-4 sm:grid-cols-2">
            <Card className="flex items-center gap-4 p-5">
              <LiquidVessel
                fraction={view.totals.in_paise > 0 ? 1 : 0}
                tone="positive"
                size={64}
                shape="drop"
              />
              <div>
                <p className="label-mono text-ink-3">Money in</p>
                <p className="tabular serif-light text-[30px] leading-none text-positive">
                  <NumberTicker value={formatINR(view.totals.in_paise, { paise: 'auto' })} />
                </p>
              </div>
            </Card>
            <Card className="flex items-center gap-4 p-5">
              <LiquidVessel
                fraction={view.totals.out_paise > 0 ? 1 : 0}
                tone="brand"
                size={64}
                shape="drop"
              />
              <div>
                <p className="label-mono text-ink-3">Money out</p>
                <p className="tabular serif-light text-[30px] leading-none">
                  <NumberTicker value={formatINR(view.totals.out_paise, { paise: 'auto' })} />
                </p>
              </div>
            </Card>
          </div>

          {view.items.length === 0 ? (
            <Card className="p-8">
              <EmptyState message="Nothing happened on this day. When payments arrive they will be listed here." />
            </Card>
          ) : null}

          {view.counts.needs_you > 0 ? (
            <Section id="needs-title" title="Needs you" hint="One tap each">
              <ul className="flex flex-col gap-4">
                <AnimatePresence initial={false}>
                  {view.items
                    .filter((i) => i.group === 'needs_you')
                    .map((i) => {
                      const prompt = asPrompt(i);
                      return prompt ? (
                        <PaymentPrompt key={i.id} prompt={prompt} creditKinds={creditKinds} />
                      ) : (
                        <motion.li key={i.id} layout className="list-none">
                          <Card className="p-0">
                            <ul className="px-5">
                              <Row item={i} creditKinds={creditKinds} />
                            </ul>
                          </Card>
                        </motion.li>
                      );
                    })}
                </AnimatePresence>
              </ul>
            </Section>
          ) : null}

          {view.counts.auto > 0 ? (
            <Section id="auto-title" title="Tagged for you" hint="Each one is a tap to change">
              <Card className="px-5">
                <ul>
                  {view.items
                    .filter((i) => i.group === 'auto')
                    .map((i) => (
                      <Row key={i.id} item={i} creditKinds={creditKinds} />
                    ))}
                </ul>
              </Card>
            </Section>
          ) : null}

          {view.counts.by_you > 0 ? (
            <Section id="you-title" title="Tagged by you">
              <Card className="px-5">
                <ul>
                  {view.items
                    .filter((i) => i.group === 'by_you')
                    .map((i) => (
                      <Row key={i.id} item={i} creditKinds={creditKinds} />
                    ))}
                </ul>
              </Card>
            </Section>
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
