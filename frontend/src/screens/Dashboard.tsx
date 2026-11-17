import { CaretRight, CheckCircle } from '@phosphor-icons/react';
import { motion, useReducedMotion } from 'motion/react';
import { Link } from 'react-router';

import { ApiError, type Dashboard } from '../api/client';
import { useCaptureInbox, useDashboard } from '../api/hooks';
import { BarList, type BarRow } from '../charts/BarList';
import { PaceChart } from '../charts/PaceChart';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { Card, CardHeader } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, InsufficientDataState, SkeletonBlock } from '../components/States';
import { copy } from '../copy/en';
import { formatDayShort } from '../format/date';
import { formatINR } from '../format/money';
import { LiquidVessel } from '../motion/Liquid';
import { NumberTicker } from '../motion/NumberTicker';
import { useMonth } from '../state/month';
import { CheckinCard } from './ForYou';

const T = copy.dashboard;

function Headline({ data }: { data: Dashboard }) {
  const h = data.headline;
  if (!h) return <>{T.title}</>;
  return (
    <>
      {h.before}
      <em>{h.emphasis}</em>
      {h.after}
    </>
  );
}

function PaceCard({ data }: { data: Dashboard }) {
  const pace = data.budget_pace;
  if (!pace) {
    return (
      <Card className="lg:col-span-2">
        <CardHeader label={copy.dashboard.month} />
        <div className="p-6">
          <EmptyState message={T.noBudgets} />
        </div>
      </Card>
    );
  }
  const delta = formatINR(Math.abs(pace.pace_delta_paise), { paise: 'never' });
  const callout =
    pace.pace === 'on'
      ? { text: T.onPace, tone: 'neutral' as const }
      : pace.pace === 'under'
        ? { text: T.underPace(delta), tone: 'positive' as const }
        : { text: T.overPace(delta), tone: 'negative' as const };
  const forecast = pace.forecast;
  return (
    <Card className="lg:col-span-2" labelledBy="pace-title" tone="slab">
      <CardHeader
        id="pace-title"
        label={T.month}
        action={{ to: '/transactions', text: copy.nav.transactions }}
      />
      <div className="px-6 pt-8 pb-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <LiquidVessel
            // What is left of the budget, as liquid: it drains as the month is spent.
            fraction={
              pace.total_limit_paise > 0 && !pace.over_budget
                ? pace.left_to_spend_paise / pace.total_limit_paise
                : 0
            }
            tone={pace.over_budget ? 'negative' : pace.pace === 'over' ? 'attention' : 'brand'}
            size={120}
            shape="drop"
          />
          <div className="flex flex-col items-start gap-1">
            <span className="label-mono text-ink">{T.leftToSpend}</span>
            <NumberTicker
              value={formatINR(pace.left_to_spend_paise, { paise: 'never' })}
              className="tabular text-[44px] leading-none tracking-[-0.04em] sm:text-hero"
            />
            <span className="text-small font-medium text-ink">
              {pace.over_budget
                ? T.overBy(formatINR(Math.abs(pace.left_to_spend_paise), { paise: 'never' }))
                : T.ofBudget(formatINR(pace.total_limit_paise, { paise: 'never' }))}
              <span aria-hidden> · </span>
              {T.spentSoFar(formatINR(pace.spent_paise, { paise: 'never' }))}
            </span>
          </div>
        </div>
        <div className="mt-8">
          <PaceChart
            chartId="dashboard-pace"
            daysInMonth={data.period.days_in_month}
            limitPaise={pace.total_limit_paise}
            actual={pace.actual}
            ideal={pace.ideal}
            forecastLow={forecast.status === 'ok' ? forecast.low : null}
            forecastHigh={forecast.status === 'ok' ? forecast.high : null}
            labels={{ actual: T.actual, ideal: T.idealPace, limit: T.limit }}
            callout={callout}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-small text-ink">
          <span className="inline-flex items-center gap-2">
            <span aria-hidden className="h-0.5 w-5 bg-ink" />
            {T.actual}
          </span>
          <span className="inline-flex items-center gap-2">
            <span aria-hidden className="w-5 border-t border-dashed border-ink-3" />
            {T.idealPace}
          </span>
          {forecast.status === 'ok' ? (
            <span className="inline-flex items-center gap-2">
              <span aria-hidden className="h-2.5 w-5 bg-ink/10" />
              {T.forecastBand}
            </span>
          ) : null}
        </div>
        {forecast.status === 'insufficient_data' ? (
          <div className="mt-4">
            <InsufficientDataState
              message={T.forecastMissing(String(forecast.has_days), String(forecast.needs_days))}
            />
          </div>
        ) : null}
      </div>
    </Card>
  );
}

/**
 * The one call to action on Overview: everything waiting for you (statements and phone alerts)
 * counted once, opening the single Review queue.
 */
function NeedsYouBanner({
  count,
  preview,
}: {
  count: number;
  preview: Dashboard['review_preview'];
}) {
  const reduce = useReducedMotion();
  if (count === 0) {
    return (
      <div className="flex items-center gap-3 rounded-card bg-positive-tint px-5 py-4 text-[15px] font-semibold text-positive">
        <CheckCircle size={22} weight="fill" aria-hidden />
        {T.reviewZero}
      </div>
    );
  }
  const names = preview
    .slice(0, 3)
    .map((p) => p.merchant)
    .join(', ');
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 28 }}
    >
      <Link
        to="/review"
        aria-label={`${T.review}: ${T.needsYou(String(count))}`}
        className="group flex items-center gap-4 rounded-card border border-brand/20 bg-brand-tint px-5 py-4 transition-[transform,box-shadow] duration-fast hover:-translate-y-0.5 hover:shadow-[0_14px_34px_-18px_rgba(186,58,37,0.45)]"
      >
        <span className="tabular flex size-11 shrink-0 items-center justify-center rounded-[14px] bg-brand text-[18px] font-bold text-brand-ink">
          {count}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[16px] font-semibold text-ink">{T.review}</span>
          <span className="block truncate text-small text-ink-2">
            {T.needsYou(String(count))}
            {names ? <span className="capitalize">{` · ${names}`}</span> : null}
          </span>
        </span>
        <span className="hidden items-center gap-1 text-[14px] font-semibold text-brand sm:flex">
          {T.reviewCta}
          <CaretRight
            size={16}
            weight="bold"
            aria-hidden
            className="transition-transform duration-fast group-hover:translate-x-0.5"
          />
        </span>
      </Link>
    </motion.div>
  );
}

export function UpcomingCard({ data }: { data: Dashboard }) {
  return (
    <Card labelledBy="upcoming-title">
      <CardHeader id="upcoming-title" label={T.upcoming} />
      {data.upcoming.length === 0 ? (
        <div className="p-6">
          <EmptyState message={T.upcomingEmpty} />
        </div>
      ) : (
        <ul>
          {data.upcoming.map((u) => (
            <li
              key={`${u.merchant}-${u.expected_on}`}
              className="flex items-center justify-between gap-4 border-b border-hairline px-6 py-3 last:border-b-0"
            >
              <span className="min-w-0">
                <span className="block truncate text-[14px] capitalize">{u.merchant}</span>
                <span className="text-small text-ink-3">
                  {formatDayShort(`${u.expected_on}T06:30:00Z`)}
                </span>
              </span>
              <span className="tabular text-cell">
                {formatINR(u.amount_paise, { paise: 'never' })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function CategoriesCard({ data }: { data: Dashboard }) {
  const rows: BarRow[] = data.top_categories.map((c) => ({
    key: c.category_id ?? 'none',
    categoryId: c.category_id,
    name: c.name,
    spentPaise: c.spent_paise,
    limitPaise: c.limit_paise,
    overPaise: c.over_paise,
    pctUsed: c.pct_used,
    status: c.status === 'projected_exceed' ? 'warning' : c.status,
  }));
  return (
    <Card labelledBy="cats-title">
      <CardHeader
        id="cats-title"
        label={T.topCategories}
        action={{ to: '/transactions?view=category', text: copy.common.viewAll }}
      />
      {rows.length === 0 ? (
        <div className="p-6">
          <EmptyState message={T.topEmpty} />
        </div>
      ) : (
        <BarList
          rows={rows}
          ofLabel={T.budgetOf}
          overLabel={T.budgetOver}
          hrefFor={(row) =>
            `/transactions?view=category&category=${encodeURIComponent(row.categoryId ?? 'none')}`
          }
        />
      )}
    </Card>
  );
}

const SEVERITY_TONE = {
  info: 'neutral',
  notice: 'attention',
  warning: 'attention',
  critical: 'negative',
} as const;

function AlertsCard({ data }: { data: Dashboard }) {
  return (
    <Card labelledBy="alerts-title">
      <CardHeader id="alerts-title" label={T.alerts} />
      {data.alerts.length === 0 ? (
        <div className="p-6">
          <EmptyState message={T.alertsEmpty} />
        </div>
      ) : (
        <ul>
          {data.alerts.map((a) => (
            <li
              key={a.id}
              className="flex flex-col gap-1.5 border-b border-hairline px-6 py-4 last:border-b-0"
            >
              <Badge tone={SEVERITY_TONE[a.severity]}>{T.severity[a.severity]}</Badge>
              <p className="text-[14px] text-ink">{a.why_text}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Loading() {
  return (
    <div className="grid gap-5 lg:grid-cols-3" aria-busy="true">
      <Card className="p-6 lg:col-span-2">
        <SkeletonBlock lines={6} />
      </Card>
      <Card className="p-6">
        <SkeletonBlock lines={4} />
      </Card>
      <Card className="p-6">
        <SkeletonBlock lines={4} />
      </Card>
      <Card className="p-6 lg:col-span-2">
        <SkeletonBlock lines={4} />
      </Card>
    </div>
  );
}

export function DashboardScreen() {
  const { month } = useMonth();
  const query = useDashboard(month);
  const inbox = useCaptureInbox();
  const data = query.data;
  const waiting = (data?.review_count ?? 0) + (inbox.data?.pending_count ?? 0);
  return (
    <Page title={data ? <Headline data={data} /> : T.title} wide>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <Card className="p-6">
          <ErrorState
            code={query.error instanceof ApiError ? query.error.code : 'UNKNOWN'}
            message={query.error.message}
            onRetry={() => void query.refetch()}
          />
        </Card>
      ) : !data?.has_transactions ? (
        <Card className="p-8">
          <EmptyState
            message={T.noData}
            action={
              <Link to="/settings?tab=connections">
                <Button variant="primary">{T.connectCta}</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-5">
          <NeedsYouBanner count={waiting} preview={data.review_preview} />
          <div className="grid items-start gap-5 lg:grid-cols-3">
            <PaceCard data={data} />
            <div className="flex flex-col gap-5">
              <CheckinCard />
              <AlertsCard data={data} />
            </div>
            <CategoriesCard data={data} />
            <UpcomingCard data={data} />
          </div>
        </div>
      )}
    </Page>
  );
}
