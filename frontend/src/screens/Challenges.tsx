import { ArrowRight, Pause, Play, Sparkle, Stop } from '@phosphor-icons/react';
import { AnimatePresence, motion } from 'motion/react';
import { useState } from 'react';

import {
  ApiError,
  type CheckinResponse,
  type ExperimentView,
  type OfferView,
  type ReviewView,
} from '../api/client';
import { useCoach, useCoachWrites } from '../api/hooks';
import { Badge, type Tone } from '../components/Badge';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { formatDayShort } from '../format/date';
import { formatINR } from '../format/money';
import { formatUnit } from '../format/metric';
import { LiquidBand, LiquidVessel, type LiquidTone } from '../motion/Liquid';
import { motion as tokens } from '../tokens/tokens';

type Coach = NonNullable<ReturnType<typeof useCoach>['data']>;
type Adjustment = Coach['adjustments'][number];

const DAY = (iso: string) => formatDayShort(`${iso}T06:30:00Z`);

const DIFFICULTY: Record<
  OfferView['difficulty'],
  { label: string; fill: number; tone: LiquidTone }
> = {
  easy: { label: 'Gentle', fill: 0.34, tone: 'positive' },
  medium: { label: 'Steady', fill: 0.67, tone: 'brand' },
  hard: { label: 'Stretch', fill: 1, tone: 'gold' },
};

const PACE: Record<string, { label: string; tone: Tone }> = {
  ahead: { label: 'Ahead of pace', tone: 'positive' },
  on_pace: { label: 'On pace', tone: 'neutral' },
  behind: { label: 'A little behind', tone: 'attention' },
};

const OUTCOME: Record<string, { label: string; tone: Tone }> = {
  beyond_usual_range: { label: 'Beyond your usual range', tone: 'positive' },
  within_usual_range: { label: 'Within your usual range', tone: 'neutral' },
  above_usual_range: { label: 'Above your usual range', tone: 'attention' },
  no_baseline: { label: 'Not enough history to compare', tone: 'neutral' },
};

const CHECKINS: { id: CheckinResponse; label: string }[] = [
  { id: 'going_well', label: 'Going well' },
  { id: 'hard', label: 'It is hard' },
  { id: 'want_to_pause', label: 'I want a pause' },
  { id: 'skip', label: 'Skip this one' },
];

function useFail() {
  const toast = useToast();
  return (e: unknown) =>
    toast({
      message: e instanceof ApiError ? e.message : 'That did not go through. Try again.',
      tone: 'negative',
    });
}

function SectionTitle({ id, children, hint }: { id: string; children: string; hint?: string }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-3">
      <h2 id={id} className="serif-light text-[26px]">
        {children}
      </h2>
      {hint ? <span className="text-small text-ink-3">{hint}</span> : null}
    </div>
  );
}

function AdjustmentStrip({ items }: { items: Adjustment[] }) {
  const writes = useCoachWrites();
  const fail = useFail();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="adj-title" className="rise">
      <SectionTitle id="adj-title" hint="Only you can accept these">
        A suggestion
      </SectionTitle>
      <ul className="flex flex-col gap-3">
        {items.map((a) => (
          <li key={a.id}>
            <Card className="flex flex-wrap items-center justify-between gap-4 border-agent/40 p-5">
              <div className="flex min-w-0 items-start gap-3">
                <Sparkle
                  size={18}
                  weight="fill"
                  className="mt-0.5 shrink-0 text-agent"
                  aria-hidden
                />
                <div>
                  <p className="text-[15px]">{a.message}</p>
                  <p className="text-small text-ink-3">{a.experiment_title}</p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  busy={writes.acceptAdjustment.isPending}
                  onClick={() => writes.acceptAdjustment.mutate(a.id, { onError: fail })}
                >
                  Yes, do that
                </Button>
                <Button
                  size="sm"
                  variant="text"
                  onClick={() => writes.rejectAdjustment.mutate(a.id, { onError: fail })}
                >
                  Keep it as is
                </Button>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

function OfferCard({ offer }: { offer: OfferView }) {
  const writes = useCoachWrites();
  const fail = useFail();
  const d = DIFFICULTY[offer.difficulty];
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: tokens.base / 1000, ease: tokens.easeArray }}
    >
      <Card className="flex h-full flex-col gap-5 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <Badge tone="agent">{d.label}</Badge>
            <h3 className="mt-3 serif-light text-[24px] leading-tight">{offer.title}</h3>
          </div>
          <LiquidVessel fraction={d.fill} tone={d.tone} size={64} shape="drop" />
        </div>
        <p className="text-[15px] text-ink-2">{offer.reason}</p>
        {offer.usual > 0 || offer.target > 0 ? (
          <dl className="grid grid-cols-2 gap-4 border-t border-hairline pt-4">
            <div>
              <dt className="label-mono text-ink-3">Your usual</dt>
              <dd className="tabular text-[22px]">{formatUnit(offer.unit, offer.usual)}</dd>
            </div>
            <div>
              <dt className="label-mono text-gold">The aim</dt>
              <dd className="tabular text-[22px] text-gold">
                {formatUnit(offer.unit, offer.target)}
              </dd>
            </div>
          </dl>
        ) : null}
        <p className="text-small text-ink-3">
          For {offer.duration_days} days
          {offer.expected_saving_paise > 0
            ? `, could keep about ${formatINR(offer.expected_saving_paise, { paise: 'never' })} with you`
            : ''}
          . Optional, and you can stop any time.
        </p>
        <div className="mt-auto flex gap-2">
          <Button
            variant="primary"
            icon={<ArrowRight size={14} />}
            busy={writes.accept.isPending}
            onClick={() => writes.accept.mutate(offer.id, { onError: fail })}
          >
            Start this challenge
          </Button>
          <Button variant="text" onClick={() => writes.dismiss.mutate(offer.id, { onError: fail })}>
            Not now
          </Button>
        </div>
      </Card>
    </motion.li>
  );
}

function ActiveCard({ exp }: { exp: ExperimentView }) {
  const writes = useCoachWrites();
  const fail = useFail();
  const pace = PACE[exp.pace] ?? { label: exp.pace, tone: 'neutral' as Tone };
  const paused = exp.status === 'paused';
  const dayFraction = exp.total_days > 0 ? exp.elapsed_days / exp.total_days : 0;
  const bandTone: LiquidTone =
    exp.pace === 'behind' ? 'attention' : exp.pace === 'ahead' ? 'positive' : 'brand';
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: tokens.base / 1000, ease: tokens.easeArray }}
    >
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={paused ? 'neutral' : pace.tone}>{paused ? 'Paused' : pace.label}</Badge>
              <span className="text-small text-ink-3">
                {DAY(exp.window_start)} to {DAY(exp.window_end)}
              </span>
            </div>
            <h3 className="mt-3 serif-light text-[28px] leading-tight">{exp.title}</h3>
            <p className="mt-1 max-w-xl text-small text-ink-3">{exp.hypothesis}</p>
          </div>
          <LiquidVessel fraction={dayFraction} tone={bandTone} size={96}>
            <span className="flex flex-col leading-tight">
              <span className="text-[22px]">{exp.elapsed_days}</span>
              <span className="label-mono text-ink-3">of {exp.total_days} days</span>
            </span>
          </LiquidVessel>
        </div>

        <div className="mt-6">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="label-mono text-ink-3">So far</span>
            <span className="tabular text-[26px]">{formatUnit(exp.unit, exp.observed)}</span>
          </div>
          <LiquidBand
            value={exp.observed}
            target={exp.target}
            usual={exp.usual}
            low={exp.low}
            high={exp.high}
            direction={exp.direction}
            tone={bandTone}
            label={`So far ${formatUnit(exp.unit, exp.observed)}, aim ${formatUnit(exp.unit, exp.target)}`}
          />
          <p className="mt-1 text-small text-ink-3">
            Aim {formatUnit(exp.unit, exp.target)}
            {exp.usual !== null && exp.low !== null && exp.high !== null && exp.high > 0
              ? `. Your usual is ${formatUnit(exp.unit, exp.usual)}, and it has ranged from ${formatUnit(exp.unit, exp.low)} to ${formatUnit(exp.unit, exp.high)}.`
              : '.'}
          </p>
          {exp.paused_days.length > 0 ? (
            <p className="mt-2 text-small text-agent">
              {exp.paused_days.length === 1 ? 'One day' : 'Some days'} did not count because of an
              exception you set
              {exp.extended_by_days > 0 ? `, so the window grew by ${exp.extended_by_days}` : ''}.
            </p>
          ) : null}
        </div>

        {exp.checkin_id && !paused ? (
          <div className="mt-6 rounded-control border border-hairline bg-surface-sunken/70 p-4">
            <p className="text-[15px]">How is it going?</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {CHECKINS.map((c) => (
                <Button
                  key={c.id}
                  size="sm"
                  onClick={() =>
                    writes.checkin.mutate(
                      { id: exp.checkin_id as string, response: c.id },
                      { onError: fail },
                    )
                  }
                >
                  {c.label}
                </Button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2 border-t border-hairline pt-4">
          {paused ? (
            <Button
              size="sm"
              icon={<Play size={14} />}
              onClick={() => writes.resume.mutate(exp.id, { onError: fail })}
            >
              Resume
            </Button>
          ) : (
            <Button
              size="sm"
              variant="text"
              icon={<Pause size={14} />}
              onClick={() => writes.pause.mutate(exp.id, { onError: fail })}
            >
              Pause
            </Button>
          )}
          <Button
            size="sm"
            variant="text"
            icon={<Stop size={14} />}
            onClick={() => writes.abandon.mutate(exp.id, { onError: fail })}
          >
            Stop without penalty
          </Button>
        </div>
      </Card>
    </motion.li>
  );
}

function Rating({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: number | boolean | undefined;
  onChange: (v: never) => void;
  options: { id: number | boolean; text: string }[];
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="label-mono text-ink-3">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <button
            key={String(o.id)}
            type="button"
            aria-pressed={value === o.id}
            onClick={() => onChange(o.id as never)}
            className={
              value === o.id
                ? 'h-8 min-w-8 rounded-chip bg-brand px-3 text-small font-medium text-brand-ink'
                : 'h-8 min-w-8 rounded-chip border border-hairline-strong px-3 text-small text-ink-2 hover:bg-surface-hover'
            }
          >
            {o.text}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function ReviewCard({ review }: { review: ReviewView }) {
  const writes = useCoachWrites();
  const fail = useFail();
  const outcome = OUTCOME[review.outcome] ?? { label: review.outcome, tone: 'neutral' as Tone };
  const [difficulty, setDifficulty] = useState<number | undefined>();
  const [helpful, setHelpful] = useState<boolean | undefined>();
  const [repeat, setRepeat] = useState<boolean | undefined>();
  const ready = difficulty !== undefined || helpful !== undefined || repeat !== undefined;
  return (
    <li>
      <Card className="p-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={outcome.tone}>{outcome.label}</Badge>
          {review.target_met === true ? <Badge tone="positive">Aim reached</Badge> : null}
          {review.target_met === false ? <Badge tone="neutral">Aim not reached</Badge> : null}
          <span className="text-small text-ink-3">{review.title}</span>
        </div>
        <p className="serif-light mt-4 text-[26px] leading-snug">{review.headline}</p>
        <ul className="mt-3 flex flex-col gap-1 text-small text-ink-3">
          {review.details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>

        {review.needs_confirmation ? (
          <div className="mt-5 rounded-control border border-attention/40 bg-attention-tint/60 p-4">
            <p className="text-[15px]">{review.confirmation_prompt}</p>
            <Button
              className="mt-3"
              size="sm"
              busy={writes.confirm.isPending}
              onClick={() => writes.confirm.mutate(review.experiment_id, { onError: fail })}
            >
              Yes, those were genuine
            </Button>
          </div>
        ) : null}

        <AnimatePresence initial={false}>
          {!review.feedback_given ? (
            <motion.div
              exit={{ opacity: 0, height: 0 }}
              className="mt-5 flex flex-col gap-4 border-t border-hairline pt-5"
            >
              <p className="text-[15px]">Did this help? It teaches the app what to offer next.</p>
              <div className="grid gap-4 sm:grid-cols-3">
                <Rating
                  label="How hard was it"
                  value={difficulty}
                  onChange={setDifficulty as (v: never) => void}
                  options={[1, 2, 3, 4, 5].map((n) => ({ id: n, text: String(n) }))}
                />
                <Rating
                  label="Was it useful"
                  value={helpful}
                  onChange={setHelpful as (v: never) => void}
                  options={[
                    { id: true, text: 'Yes' },
                    { id: false, text: 'Not really' },
                  ]}
                />
                <Rating
                  label="Try it again"
                  value={repeat}
                  onChange={setRepeat as (v: never) => void}
                  options={[
                    { id: true, text: 'Yes' },
                    { id: false, text: 'No' },
                  ]}
                />
              </div>
              <div>
                <Button
                  variant="primary"
                  disabled={!ready}
                  busy={writes.feedback.isPending}
                  onClick={() =>
                    writes.feedback.mutate(
                      {
                        id: review.experiment_id,
                        body: {
                          ...(difficulty !== undefined ? { difficulty_rating: difficulty } : {}),
                          ...(helpful !== undefined ? { user_helpful: helpful } : {}),
                          ...(repeat !== undefined ? { would_repeat: repeat } : {}),
                        },
                      },
                      { onError: fail },
                    )
                  }
                >
                  Send feedback
                </Button>
              </div>
            </motion.div>
          ) : (
            <p className="mt-4 text-small text-positive">
              Thanks. Your feedback shapes what comes next.
            </p>
          )}
        </AnimatePresence>
      </Card>
    </li>
  );
}

export function ChallengesScreen() {
  const coach = useCoach();
  const writes = useCoachWrites();
  const fail = useFail();

  return (
    <Page
      title={
        <>
          Small experiments, <em>honestly measured</em>
        </>
      }
      lead="Optional challenges built from your own spending. Each result is compared with your own earlier weeks, never with anyone else."
    >
      {coach.isPending ? (
        <Card className="p-6">
          <SkeletonBlock lines={5} />
        </Card>
      ) : coach.error ? (
        <ErrorState
          code={coach.error instanceof ApiError ? coach.error.code : 'UNKNOWN'}
          message={coach.error.message}
          onRetry={() => void coach.refetch()}
        />
      ) : (
        <div className="flex flex-col gap-12">
          <AdjustmentStrip items={coach.data.adjustments} />

          {coach.data.active.length > 0 ? (
            <section aria-labelledby="active-title" className="rise">
              <SectionTitle id="active-title">In progress</SectionTitle>
              <ul className="grid gap-5">
                {coach.data.active.map((e) => (
                  <ActiveCard key={e.id} exp={e} />
                ))}
              </ul>
            </section>
          ) : null}

          <section aria-labelledby="offers-title" className="rise">
            <SectionTitle id="offers-title" hint="Chosen from your spending, never forced">
              This week
            </SectionTitle>
            {coach.data.offers.length > 0 ? (
              <ul className="grid gap-5 lg:grid-cols-2">
                <AnimatePresence initial={false}>
                  {coach.data.offers.map((o) => (
                    <OfferCard key={o.id} offer={o} />
                  ))}
                </AnimatePresence>
              </ul>
            ) : (
              <Card className="p-8">
                <EmptyState
                  message={
                    coach.data.offers_note ??
                    'Nothing is on offer yet. Ask for suggestions and the app will look for something that fits your spending.'
                  }
                />
                {!coach.data.offers_note ? (
                  <div className="mt-4">
                    <Button
                      variant="primary"
                      icon={<Sparkle size={14} weight="fill" />}
                      busy={writes.suggest.isPending}
                      onClick={() => writes.suggest.mutate(undefined, { onError: fail })}
                    >
                      Look for a challenge
                    </Button>
                  </div>
                ) : null}
              </Card>
            )}
          </section>

          {coach.data.reviews.length > 0 ? (
            <section aria-labelledby="reviews-title" className="rise">
              <SectionTitle id="reviews-title" hint="Compared only with your own history">
                How it went
              </SectionTitle>
              <ul className="grid gap-5">
                {coach.data.reviews.map((r) => (
                  <ReviewCard key={r.experiment_id} review={r} />
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      )}
    </Page>
  );
}
