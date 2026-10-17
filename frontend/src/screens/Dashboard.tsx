import { Link } from 'react-router';

import { ApiError, type Dashboard } from '../api/client';
import { useDashboard } from '../api/hooks';
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
    <Card className="lg:col-span-2" labelledBy="pace-title">
      <CardHeader
        id="pace-title"
        label={T.month}
        action={{ to: '/transactions', text: copy.nav.transactions }}
      />
      <div className="px-6 pt-8 pb-6">
        <div className="flex items-center gap-6">
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
            <span className="label-mono text-ink-3">{T.leftToSpend}</span>
            <NumberTicker
              value={formatINR(pace.left_to_spend_paise, { paise: 'never' })}
              className="tabular text-hero font-light tracking-[-0.02em]"
            />
            <span className="text-small text-ink-2">
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
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-small text-ink-2">
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

function ReviewCard({ data }: { data: Dashboard }) {
  return (
    <Card labelledBy="review-title">
      <CardHeader
        id="review-title"
        label={T.review}
        action={{ to: '/review', text: copy.common.viewAll }}
      />
      <div className="p-6">
        {data.review_count === 0 ? (
          <EmptyState message={T.reviewZero} />
        ) : (
          <div className="flex flex-col gap-4">
            <p className="serif-light text-[28px] leading-none tabular">{data.review_count}</p>
            <ul className="flex flex-col divide-y divide-hairline">
              {data.review_preview.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-3 py-2.5">
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] capitalize">{item.merchant}</span>
                    <span className="text-small text-ink-3">
                      {formatDayShort(item.occurred_at)}
                    </span>
                  </span>
                  <span className="tabular text-cell">
                    {formatINR(item.amount_paise, { paise: 'never' })}
                  </span>
                </li>
              ))}
            </ul>
            <Link to="/review">
              <Button variant="primary">{T.reviewCta}</Button>
            </Link>
          </div>
        )}
      </div>
    </Card>
  );
}

function UpcomingCard({ data }: { data: Dashboard }) {
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
    pctUsed: c.pct_used,
    status: c.status === 'projected_exceed' ? 'warning' : c.status,
  }));
  return (
    <Card labelledBy="cats-title">
      <CardHeader
        id="cats-title"
        label={T.topCategories}
        action={{ to: '/transactions', text: copy.common.viewAll }}
      />
      {rows.length === 0 ? (
        <div className="p-6">
          <EmptyState message={T.topEmpty} />
        </div>
      ) : (
        <BarList rows={rows} ofLabel={(limit) => `/ ${limit}`} />
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
      <CardHeader
        id="alerts-title"
        label={T.alerts}
        action={{ to: '/agent#alerts', text: copy.common.viewAll }}
      />
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
              <Badge tone={SEVERITY_TONE[a.severity]}>{a.severity}</Badge>
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
  const query = useDashboard();
  const data = query.data;
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
              <Link to="/connect">
                <Button variant="primary">{T.connectCta}</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-3">
          <PaceCard data={data} />
          <div className="flex flex-col gap-5">
            <ReviewCard data={data} />
            <AlertsCard data={data} />
          </div>
          <CategoriesCard data={data} />
          <UpcomingCard data={data} />
        </div>
      )}
    </Page>
  );
}
