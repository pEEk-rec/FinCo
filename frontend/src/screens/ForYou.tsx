import { useState, type FormEvent } from 'react';

import { ApiError, type ForYouCheckin, type ProfileData, type ReplanOption } from '../api/client';
import {
  useBudgetProposal,
  useCategories,
  useCheckins,
  useForYouWrites,
  useProfile,
  useReplan,
  useSubscriptions,
} from '../api/hooks';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { Card, CardHeader } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { formatINR, parseRupeesToPaise } from '../format/money';

const DAY_MIN = 1;
const DAY_MAX = 28;
const STYLES = [
  { id: 'gentle', label: 'Gently' },
  { id: 'direct', label: 'Directly' },
  { id: 'numbers', label: 'Just the numbers' },
] as const;

const field =
  'h-10 w-full rounded-control border border-input-border bg-surface px-3 text-[14px] text-ink placeholder:text-ink-3';
const label = 'label-mono text-ink';

function useNames(): (id: string) => string {
  const cats = useCategories();
  const names = new Map((cats.data ?? []).map((c) => [c.id, c.name]));
  return (id) => names.get(id) ?? id;
}

function fail(error: unknown): string {
  return error instanceof ApiError ? error.message : 'That did not work. Please try again.';
}

// ---- the check-in ----------------------------------------------------------------------------
export function CheckinCard() {
  const q = useCheckins();
  const w = useForYouWrites();
  const toast = useToast();
  const latest: ForYouCheckin | undefined = q.data?.data.checkins.find((c) => c.status === 'sent');
  const v = q.data?.data.verification;
  const answer = (c: ForYouCheckin, response: 'acted' | 'dismissed' | 'not_useful') =>
    w.respond.mutate(
      { id: c.id, response },
      {
        onError: (e) => toast({ message: fail(e) }),
        onSuccess: () => toast({ message: 'Thanks, noted.' }),
      },
    );
  return (
    <Card labelledBy="checkin-title">
      <CardHeader id="checkin-title" label="This week" />
      <div className="flex flex-col gap-4 p-6">
        {q.isPending ? (
          <SkeletonBlock lines={3} />
        ) : q.error ? (
          <ErrorState
            code={q.error instanceof ApiError ? q.error.code : 'UNKNOWN'}
            message={q.error.message}
            onRetry={() => void q.refetch()}
          />
        ) : latest ? (
          <>
            <h2 className="serif-light text-[24px]">{latest.headline}</h2>
            <p className="text-[15px] text-ink-2">{latest.body}</p>
            {latest.options.length ? (
              <ul className="flex list-disc flex-col gap-1 pl-5 text-[14px] text-ink-2">
                {latest.options.map((o) => (
                  <li key={o}>{o}</li>
                ))}
              </ul>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" size="sm" onClick={() => answer(latest, 'acted')}>
                I will act on it
              </Button>
              <Button size="sm" onClick={() => answer(latest, 'dismissed')}>
                Not now
              </Button>
              <Button size="sm" variant="text" onClick={() => answer(latest, 'not_useful')}>
                Not useful
              </Button>
            </div>
          </>
        ) : (
          <>
            <EmptyState message="Nothing needs your attention right now. When something does, it appears here, after it has been checked." />
            <div>
              <Button
                busy={w.runCheckin.isPending}
                onClick={() =>
                  w.runCheckin.mutate(undefined, {
                    onSuccess: (r) =>
                      toast({
                        message: r.sent
                          ? 'There is something for you.'
                          : 'Nothing worth saying right now.',
                      }),
                    onError: (e) => toast({ message: fail(e) }),
                  })
                }
              >
                Check now
              </Button>
            </div>
          </>
        )}
        {v && v.sent + v.dropped > 0 ? (
          <p className="text-small text-ink-2">
            {v.sent} said, {v.dropped} held back because they did not survive their own check.
          </p>
        ) : null}
      </div>
    </Card>
  );
}

// ---- what matters to you ------------------------------------------------------------------------
/** Plain names for the profile's fields. */
const FIELD_LABEL: Record<string, string> = {
  income: 'Money in',
  savings_intent_paise: 'Set aside each month',
  priorities: 'Matters most',
  nudge_style: 'How to talk to you',
  fixed_commitments: 'Fixed payments',
  checkin_weekday: 'Check-in day',
  language: 'Language',
};
const fieldLabel = (k: string): string => FIELD_LABEL[k] ?? k.replace(/_/g, ' ');

function describe(field: string, value: unknown, name: (id: string) => string): string {
  const v = value as Record<string, unknown>;
  if (field === 'income')
    return v.kind === 'monthly'
      ? `${formatINR(v.expected_paise as number, { paise: 'never' })} a month`
      : String(v.kind);
  if (field === 'savings_intent_paise')
    return `${formatINR(value as number, { paise: 'never' })} a month`;
  if (field === 'priorities') return (value as string[]).map(name).join(', ');
  return String(value);
}

export function AboutYouCard() {
  const q = useProfile();
  const w = useForYouWrites();
  const name = useNames();
  const cats = useCategories();
  const toast = useToast();
  const [income, setIncome] = useState('');
  const [day, setDay] = useState(String(DAY_MIN));
  const [savings, setSavings] = useState('');
  const [first, setFirst] = useState('');
  const [style, setStyle] = useState<string>('');
  const p: ProfileData | undefined = q.data?.data;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const calls: (() => Promise<unknown>)[] = [];
    const incomePaise = parseRupeesToPaise(income);
    if (income && incomePaise === null)
      return toast({ message: 'Enter income as a number, like 40000.' });
    if (incomePaise !== null)
      calls.push(() =>
        w.setProfile.mutateAsync({
          field: 'income',
          value: { kind: 'monthly', expected_paise: incomePaise, day_of_month: Number(day) },
        }),
      );
    const savePaise = parseRupeesToPaise(savings);
    if (savings && savePaise === null)
      return toast({ message: 'Enter savings as a number, like 5000.' });
    if (savePaise !== null)
      calls.push(() =>
        w.setProfile.mutateAsync({ field: 'savings_intent_paise', value: savePaise }),
      );
    if (first) calls.push(() => w.setProfile.mutateAsync({ field: 'priorities', value: [first] }));
    if (style) calls.push(() => w.setProfile.mutateAsync({ field: 'nudge_style', value: style }));
    try {
      for (const call of calls) await call(); // one at a time: each is a write
      toast({ message: 'Saved.' });
    } catch (err) {
      toast({ message: fail(err) });
    }
  };

  return (
    <Card labelledBy="about-title">
      <CardHeader id="about-title" label="About you" />
      <div className="flex flex-col gap-5 p-6">
        {q.isPending ? (
          <SkeletonBlock lines={4} />
        ) : q.error ? (
          <ErrorState
            code={q.error instanceof ApiError ? q.error.code : 'UNKNOWN'}
            message={q.error.message}
            onRetry={() => void q.refetch()}
          />
        ) : (
          <>
            <dl className="grid gap-2 text-[14px]">
              {Object.entries(p?.values ?? {}).map(([k, v]) => (
                <div key={k} className="flex flex-wrap items-baseline gap-x-3">
                  <dt className={label}>{fieldLabel(k)}</dt>
                  <dd className="text-ink-2">{describe(k, v, name)}</dd>
                </div>
              ))}
              {Object.keys(p?.values ?? {}).length === 0 ? (
                <p className="text-ink-2">Nothing yet. Tell me a little, and plans get better.</p>
              ) : null}
            </dl>
            {Object.entries(p?.suggestions ?? {}).map(([k, v]) => (
              <div
                key={k}
                className="flex flex-wrap items-center gap-3 rounded-control bg-brand-tint p-3 text-[14px]"
              >
                <Badge tone="agent">Suggested</Badge>
                <span className="text-ink">
                  {fieldLabel(k)}: {describe(k, v, name)}
                </span>
                <Button size="sm" onClick={() => w.confirmProfile.mutate(k)}>
                  That is right
                </Button>
              </div>
            ))}
            <div>
              <Button
                size="sm"
                variant="secondary"
                busy={w.suggestProfile.isPending}
                onClick={() => w.suggestProfile.mutate()}
              >
                Suggest from my money
              </Button>
            </div>
            <form onSubmit={(e) => void save(e)} className="grid gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className={label}>Money in each month</span>
                <input
                  className={field}
                  inputMode="decimal"
                  value={income}
                  onChange={(e) => setIncome(e.target.value)}
                  placeholder="for example 40000"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>It usually arrives on day</span>
                <input
                  className={field}
                  type="number"
                  min={DAY_MIN}
                  max={DAY_MAX}
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Set aside each month</span>
                <input
                  className={field}
                  inputMode="decimal"
                  value={savings}
                  onChange={(e) => setSavings(e.target.value)}
                  placeholder="for example 5000"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className={label}>Matters most</span>
                <select className={field} value={first} onChange={(e) => setFirst(e.target.value)}>
                  <option value="">Choose a category</option>
                  {(cats.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset className="flex flex-col gap-1 sm:col-span-2">
                <legend className={label}>Talk to me</legend>
                <div className="flex flex-wrap gap-2">
                  {STYLES.map((s) => (
                    <label
                      key={s.id}
                      className={`cursor-pointer rounded-chip border-2 px-4 py-1.5 text-[14px] font-semibold ${style === s.id ? 'border-ink bg-ink text-ink-inverse' : 'border-ink/20 text-ink'}`}
                    >
                      <input
                        type="radio"
                        name="style"
                        className="sr-only"
                        checked={style === s.id}
                        onChange={() => setStyle(s.id)}
                      />
                      {s.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="sm:col-span-2">
                <Button type="submit" variant="primary" busy={w.setProfile.isPending}>
                  Save
                </Button>
              </div>
            </form>
          </>
        )}
      </div>
    </Card>
  );
}

// ---- a month's plan -----------------------------------------------------------------------------------
export function BudgetCard() {
  const q = useBudgetProposal();
  const replan = useReplan();
  const w = useForYouWrites();
  const name = useNames();
  const toast = useToast();
  const plan = q.data?.data;
  const move = (o: ReplanOption) =>
    o.from_category
      ? w.moveBudget.mutate(
          {
            from_category: o.from_category,
            to_category: o.category_id,
            amount_paise: o.amount_paise,
          },
          {
            onSuccess: () => toast({ message: 'Moved.' }),
            onError: (e) => toast({ message: fail(e) }),
          },
        )
      : undefined;
  return (
    <Card labelledBy="plan-title" tone="slab">
      <CardHeader id="plan-title" label="A plan for this month" />
      <div className="flex flex-col gap-4 p-6">
        {q.isPending ? (
          <SkeletonBlock lines={4} />
        ) : q.error ? (
          <ErrorState
            code={q.error instanceof ApiError ? q.error.code : 'UNKNOWN'}
            message={q.error.message}
            onRetry={() => void q.refetch()}
          />
        ) : plan ? (
          <>
            <p className="text-[15px] font-medium text-ink">{plan.note}</p>
            {plan.lines.length ? (
              <table className="w-full text-left text-[14px] text-ink">
                <thead>
                  <tr className="label-mono">
                    <th className="py-1 pr-3">Category</th>
                    <th className="py-1 pr-3 text-right">Limit</th>
                    <th className="py-1 text-right">Usually</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.lines.map((l) => (
                    <tr key={l.category_id} className="border-t border-ink/15">
                      <td className="py-1.5 pr-3">{name(l.category_id)}</td>
                      <td className="tabular py-1.5 pr-3 text-right">
                        {formatINR(l.limit_paise, { paise: 'never' })}
                      </td>
                      <td className="tabular py-1.5 text-right">
                        {formatINR(l.usual_paise, { paise: 'never' })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {plan.status === 'ok' ? (
              <div>
                <Button
                  variant="primary"
                  busy={w.applyBudget.isPending}
                  onClick={() =>
                    w.applyBudget.mutate(undefined, {
                      onSuccess: () => toast({ message: 'These are now your budgets.' }),
                      onError: (e) => toast({ message: fail(e) }),
                    })
                  }
                >
                  Use this plan
                </Button>
              </div>
            ) : null}
          </>
        ) : null}
        {(replan.data?.data ?? []).map((r) => (
          <div key={r.category_id} className="rounded-control border-2 border-ink bg-surface p-4">
            <p className="text-[14px] font-semibold text-ink">
              {name(r.category_id)} is heading over its limit.
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {r.options.map((o) => (
                <li key={o.id} className="flex flex-wrap items-center gap-3 text-[14px] text-ink-2">
                  <span className="flex-1">{o.text}</span>
                  {o.kind === 'move' ? (
                    <Button size="sm" onClick={() => move(o)}>
                      Do this
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ---- subscriptions -------------------------------------------------------------------------------------
export function SubscriptionsCard() {
  const q = useSubscriptions();
  const w = useForYouWrites();
  const rows = q.data?.data ?? [];
  return (
    <Card labelledBy="subs-title">
      <CardHeader id="subs-title" label="Subscriptions" />
      <div className="p-6">
        {q.isPending ? (
          <SkeletonBlock lines={3} />
        ) : rows.length === 0 ? (
          <EmptyState message="No regular subscriptions found yet." />
        ) : (
          <ul className="flex flex-col divide-y divide-hairline">
            {rows.map((s) => (
              <li key={s.series_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[15px] font-semibold">{s.name}</p>
                  <p className="text-small text-ink-2">
                    {formatINR(s.monthly_paise, { paise: 'never' })} a month, renews in{' '}
                    {s.days_until_renewal} days
                    {s.price_change_bp > 0 ? ', and the last charge was higher' : ''}
                  </p>
                </div>
                {s.note ? <Badge>{s.note === 'unused' ? 'Not using' : 'Keeping'}</Badge> : null}
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => w.markSubscription.mutate({ id: s.series_id, note: 'unused' })}
                >
                  I do not use this
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

export function ForYouScreen() {
  return (
    <Page
      title={
        <>
          Made <em>for you</em>
        </>
      }
      lead="What matters to you, a plan that follows it, and a weekly word only when there is something worth saying."
    >
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-6">
          <CheckinCard />
          <AboutYouCard />
        </div>
        <div className="flex flex-col gap-6">
          <BudgetCard />
          <SubscriptionsCard />
        </div>
      </div>
    </Page>
  );
}
