import { CaretDown, Printer } from '@phosphor-icons/react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useSearchParams } from 'react-router';

import { api, ApiError, type AdviceExplanation } from '../api/client';
import { useMonthlyReview, useSession } from '../api/hooks';
import { Badge, Chip } from '../components/Badge';
import { Button } from '../components/Button';
import { Card, CardHeader, Stat } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, InsufficientDataState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { copy } from '../copy/en';
import { formatDay, formatPeriod } from '../format/date';
import { formatINR } from '../format/money';
import { viewPercent } from '../format/percent';

const T = copy.monthly;

function previousPeriod(period: string): string {
  const [y, m] = period.split('-').map(Number) as [number, number];
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`;
}

function Change({ pct }: { pct: number | null | undefined }) {
  const view = viewPercent(pct, true);
  if (view.kind === 'not_comparable')
    return <span className="text-small text-ink-3">{copy.common.notComparable}</span>;
  return (
    <span
      className={`tabular text-small ${view.direction === 'up' ? 'text-attention' : view.direction === 'down' ? 'text-positive' : 'text-ink-3'}`}
    >
      {view.text}
    </span>
  );
}

function Explain({ adviceId }: { adviceId: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<AdviceExplanation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = async () => {
    setOpen((o) => !o);
    if (!data && !error) {
      try {
        setData(await api.advice(adviceId));
      } catch (e) {
        setError((e as Error).message);
      }
    }
  };
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => void toggle()}
        className="inline-flex items-center gap-1.5 rounded-[6px] text-small text-agent hover:underline"
      >
        <CaretDown size={12} aria-hidden className={open ? 'rotate-180' : ''} />
        {T.explain}
      </button>
      {open ? (
        <div className="mt-3 flex flex-col gap-3 rounded-control bg-agent-tint p-4 text-small">
          {error ? <p className="text-negative">{error}</p> : null}
          {!data && !error ? <SkeletonBlock lines={2} /> : null}
          {data ? (
            <>
              {data.evidence.map((e, i) => {
                const f = e as {
                  description?: string;
                  subject?: string;
                  numbers?: { label: string; value: number; unit: string }[];
                };
                return (
                  <div key={i}>
                    <p className="label-mono text-agent">{copy.agent.evidence}</p>
                    <p className="mt-1 text-ink">{f.description}</p>
                    <ul className="mt-1 text-ink-2">
                      {(f.numbers ?? []).map((n) => (
                        <li key={n.label} className="tabular">
                          {n.label.replace(/_/g, ' ')}:{' '}
                          {n.unit === 'paise'
                            ? formatINR(n.value, { paise: 'never' })
                            : `${n.value}${n.unit === 'percent' ? '%' : ''}`}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
              {data.assumptions.length ? (
                <div>
                  <p className="label-mono text-agent">Assumptions</p>
                  <ul className="mt-1 list-disc pl-4 text-ink-2">
                    {data.assumptions.map((a, i) => (
                      <li key={i}>{String(a)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function MonthlyScreen() {
  const session = useSession();
  const [params, setParams] = useSearchParams();
  const period = params.get('period') ?? (session.data ? previousPeriod(session.data.period) : '');
  const version = params.get('v') ? Number(params.get('v')) : undefined;
  const query = useMonthlyReview(period || '2000-01', version);
  const queryClient = useQueryClient();
  const toast = useToast();

  const generate = useMutation({
    mutationFn: () => api.generateReview(period),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monthly'] }),
    onError: (e) => toast({ message: e.message, tone: 'negative' }),
  });
  const decide = useMutation({
    mutationFn: (v: { id: string; decision: 'approved' | 'rejected' }) =>
      api.decideAdvice(v.id, v.decision),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monthly'] }),
    onError: (e) => toast({ message: e.message, tone: 'negative' }),
  });

  const setPeriod = (p: string) => setParams({ period: p }, { replace: true });
  const review = query.data?.review ?? null;
  const months = session.data
    ? [
        session.data.period,
        previousPeriod(session.data.period),
        previousPeriod(previousPeriod(session.data.period)),
      ]
    : [];

  return (
    <Page
      title={period ? formatPeriod(period) : T.title}
      lead={T.title}
      actions={
        <div className="no-print flex items-center gap-2">
          {review ? (
            <Button icon={<Printer size={16} />} onClick={() => window.print()}>
              {T.print}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="no-print mb-6 flex flex-wrap items-center gap-1.5">
        {months.map((m) => (
          <Chip key={m} selected={m === period} onClick={() => setPeriod(m)}>
            {formatPeriod(m)}
          </Chip>
        ))}
        {query.data && query.data.versions.length > 1 ? (
          <span className="ml-3 flex items-center gap-1.5">
            {query.data.versions.map((v) => (
              <Chip
                key={v.version}
                selected={(version ?? query.data!.versions[0]!.version) === v.version}
                onClick={() => setParams({ period, v: String(v.version) }, { replace: true })}
              >
                {T.version(String(v.version))}
              </Chip>
            ))}
          </span>
        ) : null}
      </div>

      {query.isPending || !period ? (
        <Card className="p-6">
          <SkeletonBlock lines={8} />
        </Card>
      ) : query.error ? (
        <Card className="p-6">
          <ErrorState
            code={query.error instanceof ApiError ? query.error.code : 'UNKNOWN'}
            message={query.error.message}
            onRetry={() => void query.refetch()}
          />
        </Card>
      ) : !review ? (
        <Card className="p-8">
          <EmptyState
            message={T.empty}
            action={
              <Button variant="primary" busy={generate.isPending} onClick={() => generate.mutate()}>
                Generate review
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-5">
          {review.data_quality.is_partial_month ? (
            <InsufficientDataState message={T.partial} />
          ) : null}

          <Card labelledBy="find-title">
            <CardHeader id="find-title" label={T.findings}>
              <Badge>{T.version(String(review.version))}</Badge>
            </CardHeader>
            <div className="grid gap-8 p-6 sm:grid-cols-3">
              <Stat
                size="hero"
                label="Spent"
                value={formatINR(review.spend_paise, { paise: 'never' })}
                hint={
                  review.previous_spend_paise != null
                    ? `Last month ${formatINR(review.previous_spend_paise, { paise: 'never' })}`
                    : copy.common.notComparable
                }
              />
              <Stat label="Income" value={formatINR(review.income_paise, { paise: 'never' })} />
              <Stat
                label="Net"
                value={formatINR(review.net_paise, { paise: 'never', sign: 'always' })}
              />
            </div>
          </Card>

          <div className="grid items-start gap-5 lg:grid-cols-2">
            <Card labelledBy="cat-title">
              <CardHeader id="cat-title" label={`${T.categories} · ${T.vsPrevious}`} />
              <ul>
                {review.category_totals.map((c) => (
                  <li
                    key={c.category_id}
                    className="grid grid-cols-[minmax(0,1fr)_auto_7rem] items-center gap-4 border-b border-hairline px-6 py-3 last:border-b-0"
                  >
                    <span className="truncate text-[14px]">{c.category_name}</span>
                    <span className="tabular text-cell">
                      {formatINR(c.current_spend_paise, { paise: 'never' })}
                    </span>
                    <span className="text-right">
                      <Change pct={c.change_pct} />
                    </span>
                  </li>
                ))}
              </ul>
            </Card>

            <div className="flex flex-col gap-5">
              <Card labelledBy="bud-title">
                <CardHeader id="bud-title" label={T.budgets} />
                <ul>
                  {review.budget_statuses.map((b) => (
                    <li
                      key={b.category_id}
                      className="flex items-center justify-between gap-3 border-b border-hairline px-6 py-3 last:border-b-0"
                    >
                      <span className="text-[14px]">{b.category_name}</span>
                      <span className="flex items-center gap-3">
                        <span className="tabular text-small text-ink-2">
                          {formatINR(b.spent_paise, { paise: 'never' })} /{' '}
                          {formatINR(b.limit_paise, { paise: 'never' })}
                        </span>
                        <Badge
                          tone={
                            b.status === 'exceeded'
                              ? 'negative'
                              : b.status === 'ok'
                                ? 'positive'
                                : 'attention'
                          }
                        >
                          {b.status.replace('_', ' ')}
                        </Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
              <Card labelledBy="fc-title">
                <CardHeader id="fc-title" label={T.forecast} />
                <div className="p-6">
                  {review.forecast && !review.forecast.insufficient_data ? (
                    <Stat
                      label="Projected month-end spend"
                      value={formatINR(review.forecast.projected_total_paise, { paise: 'never' })}
                      hint={`${formatINR(review.forecast.projected_range_paise[0], { paise: 'never' })} to ${formatINR(review.forecast.projected_range_paise[1], { paise: 'never' })}`}
                    />
                  ) : (
                    <InsufficientDataState message={copy.dashboard.forecastMissing('–', '–')} />
                  )}
                </div>
              </Card>
            </div>
          </div>

          <div className="grid items-start gap-5 lg:grid-cols-2">
            <Card labelledBy="rec-title">
              <CardHeader id="rec-title" label={T.recurring} />
              {review.recurring_payments.length === 0 ? (
                <div className="p-6">
                  <EmptyState message={copy.dashboard.upcomingEmpty} />
                </div>
              ) : (
                <ul>
                  {review.recurring_payments.map((r) => (
                    <li
                      key={r.merchant}
                      className="flex justify-between gap-3 border-b border-hairline px-6 py-3 last:border-b-0"
                    >
                      <span className="text-[14px] capitalize">{r.merchant}</span>
                      <span className="tabular text-cell">
                        {formatINR(r.typical_amount_paise, { paise: 'never' })}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card labelledBy="dq-title">
              <CardHeader id="dq-title" label={`${T.anomalies} · ${T.dataQuality}`} />
              <ul>
                {review.anomalies.map((a) => (
                  <li key={a.transaction_id} className="border-b border-hairline px-6 py-3">
                    <p className="flex justify-between gap-3 text-[14px]">
                      <span className="capitalize">{a.merchant}</span>
                      <span className="tabular">
                        {formatINR(a.amount_paise, { paise: 'never' })}
                      </span>
                    </p>
                    <p className="text-small text-ink-3">
                      {formatDay(a.occurred_at)} · {a.reason}
                    </p>
                  </li>
                ))}
                <li className="flex flex-wrap gap-x-6 gap-y-1 px-6 py-3 text-small text-ink-2">
                  <span className="tabular">
                    Needs review: {review.data_quality.review_queue_size}
                  </span>
                  <span className="tabular">
                    Duplicates flagged: {review.data_quality.duplicates_flagged}
                  </span>
                  <span className="tabular">
                    Days without data: {review.data_quality.missing_days}
                  </span>
                </li>
              </ul>
            </Card>
          </div>

          <Card labelledBy="adv-title">
            <CardHeader id="adv-title" label={T.advice} />
            {review.advice.length === 0 ? (
              <div className="p-6">
                <EmptyState message={T.empty} />
              </div>
            ) : (
              <ul>
                {review.advice.map((a) => (
                  <li
                    key={a.id}
                    className="flex flex-col gap-3 border-b border-hairline px-6 py-5 last:border-b-0"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <p className="max-w-2xl text-body">{a.text}</p>
                      {a.status === 'draft' ? (
                        <span className="no-print flex gap-2">
                          <Button
                            size="sm"
                            variant="primary"
                            busy={decide.isPending}
                            onClick={() => decide.mutate({ id: a.id, decision: 'approved' })}
                          >
                            {T.approve}
                          </Button>
                          <Button
                            size="sm"
                            busy={decide.isPending}
                            onClick={() => decide.mutate({ id: a.id, decision: 'rejected' })}
                          >
                            {T.reject}
                          </Button>
                        </span>
                      ) : (
                        <Badge tone={a.status === 'approved' ? 'positive' : 'neutral'}>
                          {a.status === 'approved' ? T.approved : T.rejected}
                        </Badge>
                      )}
                    </div>
                    <Explain adviceId={a.id} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </Page>
  );
}
