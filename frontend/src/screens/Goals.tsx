import { Plus, PencilSimple, Pause, Play, CheckCircle } from '@phosphor-icons/react';
import * as Dialog from '@radix-ui/react-dialog';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useState, type FormEvent } from 'react';

import { ApiError, type GoalIn, type GoalProgress } from '../api/client';
import { useGoals, useGoalWrites } from '../api/hooks';
import { Badge, type Tone } from '../components/Badge';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { formatDay } from '../format/date';
import { formatINR, parseRupeesToPaise } from '../format/money';
import { NumberTicker } from '../motion/NumberTicker';
import { motion as tokens } from '../tokens/tokens';

type Goal = NonNullable<ReturnType<typeof useGoals>['data']>['goals'][number];
type Kind = GoalIn['kind'];

const STATUS: Record<GoalProgress['status'], { label: string; tone: Tone; stroke: string }> = {
  on_track: { label: 'On track', tone: 'positive', stroke: 'stroke-positive' },
  at_risk: { label: 'Needs attention', tone: 'attention', stroke: 'stroke-attention' },
  off_track: { label: 'Behind', tone: 'negative', stroke: 'stroke-negative' },
  completed: { label: 'Reached', tone: 'positive', stroke: 'stroke-positive' },
  unknown: { label: 'In progress', tone: 'neutral', stroke: 'stroke-ink-2' },
};

const KINDS: { id: Kind; label: string }[] = [
  { id: 'savings', label: 'Savings' },
  { id: 'purchase', label: 'A purchase' },
  { id: 'emergency_fund', label: 'Emergency fund' },
  { id: 'other', label: 'Something else' },
];

const field =
  'h-10 w-full rounded-control border border-input-border bg-surface px-3 text-[14px] text-ink placeholder:text-ink-3';

/** The percentage the API computed (basis points), shown whole. */
const percentText = (bp: number): string => `${Math.floor(bp / 100)}%`;

function Ring({ progress, goalDone }: { progress: GoalProgress; goalDone: boolean }) {
  const reduce = useReducedMotion();
  const tone = STATUS[goalDone ? 'completed' : progress.status];
  return (
    <div className="relative h-24 w-24 shrink-0">
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden>
        <circle cx="50" cy="50" r="42" fill="none" strokeWidth="8" className="stroke-hairline" />
        <motion.circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          strokeWidth="8"
          strokeLinecap="round"
          className={tone.stroke}
          initial={reduce ? false : { pathLength: 0 }}
          animate={{ pathLength: Math.max(progress.percent_bp, 60) / 10000 }}
          transition={{ duration: tokens.slow / 1000, ease: tokens.easeArray }}
        />
      </svg>
      <span className="tabular absolute inset-0 flex items-center justify-center text-[18px]">
        <NumberTicker value={percentText(progress.percent_bp)} />
      </span>
    </div>
  );
}

function GoalCard({
  goal,
  progress,
  onEdit,
}: {
  goal: Goal;
  progress: GoalProgress;
  onEdit: () => void;
}) {
  const writes = useGoalWrites();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [amount, setAmount] = useState('');
  const done = goal.status === 'done';
  const paused = goal.status === 'paused';
  const badge = done
    ? { label: 'Finished', tone: 'positive' as Tone }
    : paused
      ? { label: 'Paused', tone: 'neutral' as Tone }
      : STATUS[progress.status];

  const fail = (e: unknown) =>
    toast({
      message: e instanceof ApiError ? e.message : 'That did not save. Try again.',
      tone: 'negative',
    });

  const add = (e: FormEvent) => {
    e.preventDefault();
    const paise = parseRupeesToPaise(amount);
    if (paise === null) return;
    writes.contribute.mutate(
      { id: goal.id, paise },
      {
        onSuccess: () => {
          setAmount('');
          setAdding(false);
        },
        onError: fail,
      },
    );
  };
  const setStatus = (status: 'active' | 'paused' | 'done') =>
    writes.update.mutate({ id: goal.id, body: { status } }, { onError: fail });

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ duration: tokens.base / 1000, ease: tokens.easeArray }}
      className={paused || done ? 'opacity-80' : undefined}
    >
      <Card className="p-6">
        <div className="flex gap-5">
          <Ring progress={progress} goalDone={done} />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[17px] font-medium">{goal.name}</h2>
              <Badge tone={badge.tone}>{badge.label}</Badge>
            </div>
            <p className="tabular text-body text-ink-2">
              <NumberTicker value={formatINR(progress.current_paise, { paise: 'never' })} /> of{' '}
              {formatINR(progress.target_paise, { paise: 'never' })}
              {goal.deadline ? ` by ${formatDay(`${goal.deadline}T06:30:00Z`)}` : ''}
            </p>
            {!done && !paused && progress.remaining_paise > 0 ? (
              <p className="text-small text-ink-3">
                {progress.required_monthly_paise > 0 && goal.deadline
                  ? `Setting aside ${formatINR(progress.required_monthly_paise, { paise: 'never' })} a month gets you there.`
                  : `${formatINR(progress.remaining_paise, { paise: 'never' })} to go.`}
                {progress.projected_completion_date
                  ? ` At your pace: ${formatDay(`${progress.projected_completion_date}T06:30:00Z`)}.`
                  : ''}
              </p>
            ) : null}
          </div>
        </div>

        <AnimatePresence initial={false}>
          {adding ? (
            <motion.form
              key="add"
              onSubmit={add}
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="mt-4 flex gap-2">
                <input
                  autoFocus
                  aria-label={`Amount to add to ${goal.name}`}
                  className={field}
                  inputMode="decimal"
                  placeholder="Amount in rupees"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
                <Button
                  variant="primary"
                  type="submit"
                  busy={writes.contribute.isPending}
                  disabled={parseRupeesToPaise(amount) === null}
                >
                  Add
                </Button>
                <Button variant="text" onClick={() => setAdding(false)}>
                  Cancel
                </Button>
              </div>
            </motion.form>
          ) : null}
        </AnimatePresence>

        <div className="mt-4 flex flex-wrap gap-2 border-t border-hairline pt-4">
          {!done && !paused && goal.progress_source === 'manual' ? (
            <Button size="sm" icon={<Plus size={14} />} onClick={() => setAdding((v) => !v)}>
              Add money
            </Button>
          ) : null}
          {!done ? (
            <Button size="sm" variant="text" icon={<PencilSimple size={14} />} onClick={onEdit}>
              Edit
            </Button>
          ) : null}
          {!done && !paused ? (
            <Button
              size="sm"
              variant="text"
              icon={<Pause size={14} />}
              onClick={() => setStatus('paused')}
            >
              Pause
            </Button>
          ) : null}
          {paused ? (
            <Button
              size="sm"
              variant="text"
              icon={<Play size={14} />}
              onClick={() => setStatus('active')}
            >
              Resume
            </Button>
          ) : null}
          {!done ? (
            <Button
              size="sm"
              variant="text"
              icon={<CheckCircle size={14} />}
              onClick={() => setStatus('done')}
            >
              Mark finished
            </Button>
          ) : (
            <Button size="sm" variant="text" onClick={() => setStatus('active')}>
              Reopen
            </Button>
          )}
        </div>
      </Card>
    </motion.li>
  );
}

function GoalDialog({
  goal,
  open,
  onClose,
}: {
  goal: Goal | null;
  open: boolean;
  onClose: () => void;
}) {
  const writes = useGoalWrites();
  const toast = useToast();
  const editing = goal !== null;
  const [name, setName] = useState(goal?.name ?? '');
  const [kind, setKind] = useState<Kind>((goal?.kind as Kind | undefined) ?? 'savings');
  const [target, setTarget] = useState(goal ? String(goal.target_paise / 100) : '');
  const [saved, setSaved] = useState('');
  const [deadline, setDeadline] = useState(goal?.deadline ?? '');
  const targetPaise = parseRupeesToPaise(target);
  const savedPaise = saved.trim() === '' ? 0 : parseRupeesToPaise(saved);
  const valid = name.trim().length > 0 && targetPaise !== null && savedPaise !== null;
  const busy = writes.create.isPending || writes.update.isPending;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || targetPaise === null || savedPaise === null) return;
    const done = {
      onSuccess: onClose,
      onError: (err: unknown) =>
        toast({
          message: err instanceof ApiError ? err.message : 'That did not save. Try again.',
          tone: 'negative',
        }),
    };
    if (editing && goal) {
      writes.update.mutate(
        {
          id: goal.id,
          body: { name: name.trim(), target_paise: targetPaise, ...(deadline ? { deadline } : {}) },
        },
        done,
      );
    } else {
      writes.create.mutate(
        {
          name: name.trim(),
          kind,
          priority: 2,
          target_paise: targetPaise,
          current_paise: savedPaise,
          ...(deadline ? { deadline } : {}),
        },
        done,
      );
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => (!o ? onClose() : undefined)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-card border border-hairline bg-surface p-6 shadow-lg">
          <Dialog.Title className="serif-light text-[24px]">
            {editing ? 'Edit goal' : 'New goal'}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-small text-ink-3">
            {editing
              ? 'Change the name, the amount or the date.'
              : 'Pick something to save towards. You can change it any time.'}
          </Dialog.Description>
          <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="label-mono text-ink-3">What are you saving for</span>
              <input
                autoFocus
                className={field}
                value={name}
                maxLength={80}
                placeholder="A trip, a laptop, a safety net"
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            {!editing ? (
              <label className="flex flex-col gap-1.5">
                <span className="label-mono text-ink-3">Kind</span>
                <select
                  className={field}
                  value={kind}
                  onChange={(e) => setKind(e.target.value as Kind)}
                >
                  {KINDS.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1.5">
                <span className="label-mono text-ink-3">Target (rupees)</span>
                <input
                  className={field}
                  inputMode="decimal"
                  value={target}
                  aria-invalid={target !== '' && targetPaise === null}
                  onChange={(e) => setTarget(e.target.value)}
                />
              </label>
              {!editing ? (
                <label className="flex flex-col gap-1.5">
                  <span className="label-mono text-ink-3">Saved so far</span>
                  <input
                    className={field}
                    inputMode="decimal"
                    value={saved}
                    placeholder="Optional"
                    aria-invalid={savedPaise === null}
                    onChange={(e) => setSaved(e.target.value)}
                  />
                </label>
              ) : null}
            </div>
            <label className="flex flex-col gap-1.5">
              <span className="label-mono text-ink-3">By when (optional)</span>
              <input
                className={field}
                type="date"
                value={deadline}
                onChange={(e) => setDeadline(e.target.value)}
              />
            </label>
            <div className="mt-1 flex justify-end gap-2">
              <Button variant="text" onClick={onClose}>
                Cancel
              </Button>
              <Button variant="primary" type="submit" busy={busy} disabled={!valid}>
                {editing ? 'Save changes' : 'Create goal'}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function GoalsScreen() {
  const goals = useGoals();
  const [dialog, setDialog] = useState<{ goal: Goal | null } | null>(null);

  const rows =
    goals.data?.goals.map((g) => ({
      goal: g,
      progress: goals.data.progress.find((p) => p.goal_id === g.id),
    })) ?? [];
  const open = rows.filter((r) => r.goal.status !== 'done');
  const finished = rows.filter((r) => r.goal.status === 'done');

  return (
    <Page
      title={
        <>
          What you are <em>saving for</em>
        </>
      }
      lead="Set a goal, add money as you go, and see whether you are on track."
      actions={
        <Button
          variant="primary"
          icon={<Plus size={16} />}
          onClick={() => setDialog({ goal: null })}
        >
          New goal
        </Button>
      }
    >
      {goals.isPending ? (
        <Card className="p-6">
          <SkeletonBlock lines={4} />
        </Card>
      ) : goals.error ? (
        <ErrorState
          code={goals.error instanceof ApiError ? goals.error.code : 'UNKNOWN'}
          message={goals.error.message}
          onRetry={() => void goals.refetch()}
        />
      ) : rows.length === 0 ? (
        <Card className="p-8">
          <EmptyState message="No goals yet. Start with something you would like to have by a certain date." />
          <div className="mt-4">
            <Button variant="primary" onClick={() => setDialog({ goal: null })}>
              Create your first goal
            </Button>
          </div>
        </Card>
      ) : (
        <div className="flex flex-col gap-8">
          <ul className="grid gap-5 lg:grid-cols-2">
            <AnimatePresence initial={false}>
              {open.map(({ goal, progress }) =>
                progress ? (
                  <GoalCard
                    key={goal.id}
                    goal={goal}
                    progress={progress}
                    onEdit={() => setDialog({ goal })}
                  />
                ) : null,
              )}
            </AnimatePresence>
          </ul>
          {finished.length > 0 ? (
            <section aria-labelledby="done-goals">
              <h2 id="done-goals" className="label-mono mb-3 text-ink-3">
                Finished
              </h2>
              <ul className="grid gap-5 lg:grid-cols-2">
                {finished.map(({ goal, progress }) =>
                  progress ? (
                    <GoalCard
                      key={goal.id}
                      goal={goal}
                      progress={progress}
                      onEdit={() => setDialog({ goal })}
                    />
                  ) : null,
                )}
              </ul>
            </section>
          ) : null}
        </div>
      )}
      {dialog ? (
        <GoalDialog
          key={dialog.goal?.id ?? 'new'}
          goal={dialog.goal}
          open
          onClose={() => setDialog(null)}
        />
      ) : null}
    </Page>
  );
}
