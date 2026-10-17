import { Sparkle } from '@phosphor-icons/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useLocation } from 'react-router';

import { api, ApiError, type AskOut, type CompareOut, type InvestigationOut } from '../api/client';
import { useAlerts, useCategories, useGoals, useSession, useTimeline } from '../api/hooks';
import { Badge, Chip } from '../components/Badge';
import { Button } from '../components/Button';
import { Card, CardHeader } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, InsufficientDataState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { copy } from '../copy/en';
import { formatDay, formatPeriod, formatTime } from '../format/date';
import { formatINR, parseRupeesToPaise } from '../format/money';
import { Constellation } from '../constellation/Constellation';
import { AgentProcess } from './AgentProcess';

const T = copy.agent;
type Tab = 'ask' | 'investigate' | 'whatif' | 'goals' | 'activity';
const TABS: { id: Tab; label: string }[] = [
  { id: 'ask', label: T.ask },
  { id: 'investigate', label: 'Investigate' },
  { id: 'whatif', label: T.whatIf },
  { id: 'goals', label: `${T.goals} and alerts` },
  { id: 'activity', label: T.timeline },
];

const field =
  'h-10 w-full rounded-control border border-input-border bg-surface px-3 text-[14px] text-ink placeholder:text-ink-3';

function previousPeriod(period: string): string {
  const [y, m] = period.split('-').map(Number) as [number, number];
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`;
}

/** Agent surfaces are where violet lives. */
function AgentMark({ working = false }: { working?: boolean }) {
  return working ? (
    <div className="w-[120px]">
      <Constellation
        particles={[]}
        clusters={[]}
        height={48}
        mode="ambient"
        ariaLabel={T.working}
      />
    </div>
  ) : (
    <Sparkle size={16} weight="fill" aria-hidden className="text-agent" />
  );
}

// ------------------------------------------------------------------------------------------
// Ask
// ------------------------------------------------------------------------------------------

function ObservationData({
  name,
  data,
  names,
}: {
  name: string;
  data: Record<string, unknown> | null;
  names: Map<string, string>;
}) {
  if (!data) return null;
  if (name === 'aggregate_spend_by_category' && Array.isArray(data.totals)) {
    return (
      <ul className="mt-2 flex flex-col gap-1">
        {(data.totals as { category_id: string | null; total_spend_paise: number }[]).map((t) => (
          <li key={String(t.category_id)} className="flex justify-between text-small">
            <span className="text-ink-2">
              {(t.category_id && names.get(t.category_id)) ?? copy.common.uncategorised}
            </span>
            <span className="tabular">{formatINR(t.total_spend_paise, { paise: 'never' })}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (name === 'check_budgets' && Array.isArray(data.statuses)) {
    return (
      <ul className="mt-2 flex flex-col gap-1">
        {(
          data.statuses as {
            category_id: string;
            spent_paise: number;
            limit_paise: number;
            status: string;
          }[]
        ).map((s) => (
          <li key={s.category_id} className="flex justify-between gap-3 text-small">
            <span className="text-ink-2">{names.get(s.category_id) ?? s.category_id}</span>
            <span className="tabular">
              {formatINR(s.spent_paise, { paise: 'never' })} /{' '}
              {formatINR(s.limit_paise, { paise: 'never' })}{' '}
              <Badge
                tone={
                  s.status === 'exceeded'
                    ? 'negative'
                    : s.status === 'ok'
                      ? 'positive'
                      : 'attention'
                }
              >
                {s.status.replace('_', ' ')}
              </Badge>
            </span>
          </li>
        ))}
      </ul>
    );
  }
  if (name === 'explain_change' && data.investigation) {
    return (
      <div className="mt-3">
        <InvestigationView out={data as unknown as InvestigationOut} />
      </div>
    );
  }
  if (name === 'run_whatif' && data.projection) {
    const projection = data.projection as {
      monthly_surplus_paise: Record<string, number>;
      goal_impacts: Record<string, string>;
    };
    const goalStates = Object.values(projection.goal_impacts);
    return (
      <div className="mt-3 flex flex-col gap-2">
        <ul className="flex flex-col gap-1">
          {Object.entries(projection.monthly_surplus_paise).map(([month, surplus]) => (
            <li key={month} className="flex justify-between text-small">
              <span className="text-ink-2">{formatPeriod(month)}</span>
              <span className="tabular">{formatINR(surplus, { paise: 'never' })}</span>
            </li>
          ))}
        </ul>
        {goalStates.length ? (
          <p className="text-small text-ink-2">
            {T.goals}: {(goalStates[goalStates.length - 1] ?? '').replace(/_/g, ' ')}
          </p>
        ) : null}
      </div>
    );
  }
  if (name === 'detect_anomalies' && Array.isArray(data.anomalies)) {
    return (
      <p className="tabular mt-2 text-small text-ink-2">
        {data.anomalies.length} unusual transaction(s) found. Use the Investigate tab to test why.
      </p>
    );
  }
  if (name === 'forecast_month' && typeof data.projected_total === 'number') {
    return (
      <p className="tabular mt-2 text-small">
        Projected month-end spend {formatINR(data.projected_total, { paise: 'never' })}
      </p>
    );
  }
  return null;
}

function AskPanel() {
  const toast = useToast();
  const [text, setText] = useState('');
  const [asked, setAsked] = useState('');
  const [answer, setAnswer] = useState('');
  const session = useSession();
  const [useLlm, setUseLlm] = useState(true);
  const ask = useMutation({
    mutationFn: (v: { text: string; clarification?: string; useLlm?: boolean }) =>
      api.ask(v.text, v.clarification, v.useLlm ?? useLlm),
    onError: (e) => toast({ message: e.message, tone: 'negative' }),
  });
  const result: AskOut | undefined = ask.data;
  const categories = useCategories();
  const names = new Map((categories.data ?? []).map((c) => [c.id, c.name]));

  return (
    <div className="flex flex-col gap-5">
      <form
        className="flex flex-col gap-3 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          setAsked(text.trim());
          setAnswer('');
          ask.mutate({ text: text.trim() });
        }}
      >
        <label className="flex-1">
          <span className="sr-only">{T.ask}</span>
          <input
            className={field}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={T.askPlaceholder}
            maxLength={500}
          />
        </label>
        <Button variant="primary" busy={ask.isPending} type="submit">
          {T.ask}
        </Button>
      </form>
      {session.data?.llm_available ? (
        <label className="flex items-center gap-2 text-small text-ink-2">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          Use AI to plan and word the answer (numbers always come from your data)
        </label>
      ) : null}

      <div className="flex flex-col gap-3">
        <p className="label-mono text-ink-3">Try asking</p>
        <ul className="flex flex-wrap gap-2">
          {T.examples.map((example) => (
            <li key={example}>
              <button
                type="button"
                onClick={() => {
                  setText(example);
                  setAsked(example);
                  setAnswer('');
                  ask.mutate({ text: example });
                }}
                className="rounded-control border border-hairline-strong bg-surface px-3 py-2 text-left text-[14px] text-ink-2 transition-colors duration-fast hover:border-agent hover:text-agent"
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {ask.isPending ? (
        <Card className="flex items-center gap-4 p-6">
          <AgentMark working />
          <span className="text-body text-ink-2">{T.working}</span>
        </Card>
      ) : result ? (
        <Card className="border-agent/30" labelledBy="ask-result">
          <div className="flex items-center gap-2 border-b border-hairline px-6 py-3">
            <AgentMark />
            <h2 id="ask-result" className="label-mono text-agent">
              {T.ask}
            </h2>
            {result.intent && (result.intent as { type?: string }).type !== 'unknown' ? (
              <Badge tone="agent">
                {String((result.intent as { type?: string }).type ?? '').replace(/_/g, ' ')}
              </Badge>
            ) : null}
          </div>
          <div className="flex flex-col gap-4 p-6">
            <p className="serif-light text-[22px] leading-snug">{asked}</p>
            {result.refusal_reason ? (
              <>
                <div className="rounded-control bg-negative-tint p-4">
                  <p className="font-medium text-negative">{T.refused}</p>
                  <p className="mt-1 text-[14px] text-ink">{result.refusal_reason}</p>
                  <p className="label-mono mt-3 text-ink-3">{T.canInstead}</p>
                  <p className="mt-1 text-small text-ink-2">
                    Explain a change, check budgets, forecast the month, or run a what-if.
                  </p>
                </div>
                <div className="mt-5">
                  <AgentProcess result={result} />
                </div>
              </>
            ) : result.question ? (
              <form
                className="flex flex-col gap-3 rounded-control bg-agent-tint p-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (answer.trim()) ask.mutate({ text: asked, clarification: answer.trim() });
                }}
              >
                <p className="label-mono text-agent">{T.clarify}</p>
                <p className="text-[14px] text-ink">{result.question}</p>
                <div className="flex gap-2">
                  <input
                    className={field}
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    aria-label={T.clarify}
                  />
                  <Button type="submit" variant="primary">
                    {copy.common.confirm}
                  </Button>
                </div>
              </form>
            ) : (
              <>
                {result.answer ? (
                  <div className="flex flex-col gap-3" data-testid="ask-answer">
                    <p className="serif-light text-[24px] leading-snug">{result.answer.headline}</p>
                    {result.answer.points.length > 0 ? (
                      <ul className="flex list-disc flex-col gap-1.5 pl-5 text-[15px] text-ink-2">
                        {result.answer.points.map((point) => (
                          <li key={point}>{point}</li>
                        ))}
                      </ul>
                    ) : null}
                    <p className="flex flex-wrap items-center gap-2 text-small text-ink-3">
                      <Badge tone={result.answer.written_by === 'ai' ? 'agent' : 'neutral'}>
                        {result.answer.written_by === 'ai'
                          ? 'Written by AI from your data'
                          : 'Written from your data by rules'}
                      </Badge>
                      {result.answer.confidence ? (
                        <span>
                          {T.confidence}: {result.answer.confidence}
                        </span>
                      ) : null}
                    </p>
                    {result.answer.followups.length > 0 ? (
                      <ul className="flex flex-wrap gap-2">
                        {result.answer.followups.map((q) => (
                          <li key={q}>
                            <button
                              type="button"
                              onClick={() => {
                                setText(q);
                                setAsked(q);
                                setAnswer('');
                                ask.mutate({ text: q, useLlm });
                              }}
                              className="rounded-control border border-hairline-strong bg-surface px-3 py-1.5 text-left text-small text-ink-2 hover:border-agent hover:text-agent"
                            >
                              {q}
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
                <details
                  className="group rounded-control border border-hairline"
                  data-testid="ask-process"
                >
                  <summary className="cursor-pointer select-none px-4 py-3 text-[14px] text-ink-2 hover:text-agent">
                    Show how the agent worked
                  </summary>
                  <div className="flex flex-col gap-4 border-t border-hairline p-4">
                    <AgentProcess result={result} />
                    <h3 className="label-mono text-ink-2">What it found</h3>
                    {result.observations.length === 0 ? (
                      <InsufficientDataState message="The agent did not need to look at any data for this." />
                    ) : (
                      <ul className="flex flex-col divide-y divide-hairline">
                        {result.observations.map((o) => (
                          <li key={`${o.step_seq}-${String(o.tool_name)}`} className="py-3">
                            <p className="flex items-center gap-2 text-[14px]">
                              <Badge tone={o.ok ? 'positive' : 'negative'}>
                                {o.ok ? 'ok' : 'failed'}
                              </Badge>
                              <span>{String(o.tool_name).replace(/_/g, ' ')}</span>
                            </p>
                            <ObservationData
                              names={names}
                              name={String(o.tool_name)}
                              data={(o.data_summary as Record<string, unknown> | null) ?? null}
                            />
                          </li>
                        ))}
                      </ul>
                    )}
                    {result.recommendations.length > 0 ? (
                      <p className="text-small text-ink-3">
                        {T.confidence}: {String(result.recommendations[0]?.confidence_label ?? '–')}{' '}
                        · Tools:{' '}
                        {(result.recommendations[0]?.tools_used as { tool: string }[] | undefined)
                          ?.map((t) => t.tool.replace(/_/g, ' '))
                          .join(', ')}
                      </p>
                    ) : null}
                  </div>
                </details>
              </>
            )}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------------------------------
// Investigate
// ------------------------------------------------------------------------------------------

const KIND_LABEL: Record<string, string> = {
  duplicate_charge: 'Possible duplicate',
  new_merchant: 'New merchant',
  large_transaction: 'Large payment',
};

function InvestigationView({ out }: { out: InvestigationOut }) {
  const inv = out.investigation;
  const tested = inv.hypotheses.filter(
    (h) => h.status === 'supported' || h.status === 'contradicted',
  );
  const ruledOut = inv.hypotheses.filter((h) => h.status === 'neutral');
  const inconclusive = inv.outcome === 'inconclusive';
  return (
    <Card className="border-agent/30" labelledBy="inv-title">
      <div className="flex flex-wrap items-center gap-2 border-b border-hairline px-6 py-3">
        <AgentMark />
        <h3 id="inv-title" className="label-mono text-agent">
          Investigation
        </h3>
        <Badge tone="agent">{inv.outcome.replace(/_/g, ' ')}</Badge>
        <Badge>{`${inv.confidence_label} confidence`}</Badge>
      </div>
      <div className="flex flex-col gap-5 p-6">
        {inconclusive ? (
          <p className="serif-light text-[24px] leading-snug">
            {T.inconclusive(formatINR(Math.abs(inv.unexplained_paise), { paise: 'never' }))}
          </p>
        ) : (
          <p className="serif-light text-[24px] leading-snug">
            {formatINR(Math.abs(inv.unexplained_paise), { paise: 'never' })} remains unexplained
            after testing the hypotheses below.
          </p>
        )}
        <div>
          <h4 className="label-mono mb-2 text-ink-2">{T.hypotheses}</h4>
          <ul className="flex flex-col divide-y divide-hairline">
            {tested.map((h) => (
              <li key={h.id} className="flex items-center justify-between gap-4 py-2.5">
                <span className="text-[14px] capitalize">{h.code.replace(/_/g, ' ')}</span>
                <span className="flex items-center gap-3">
                  {h.contribution_paise !== 0 ? (
                    <span className="tabular text-small">
                      {formatINR(h.contribution_paise, { paise: 'never' })}
                    </span>
                  ) : null}
                  <Badge
                    tone={
                      h.status === 'supported'
                        ? 'positive'
                        : h.status === 'contradicted'
                          ? 'negative'
                          : 'neutral'
                    }
                  >
                    {h.status === 'supported'
                      ? T.supported
                      : h.status === 'contradicted'
                        ? T.contradicted
                        : 'Not supported'}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
          {ruledOut.length > 0 ? (
            <details className="mt-3 text-small text-ink-2">
              <summary className="cursor-pointer text-ink-2 hover:text-ink">
                {tested.length === 0
                  ? `All ${ruledOut.length} explanations were tested; none had enough evidence`
                  : `${ruledOut.length} other explanations had no supporting evidence`}
              </summary>
              <ul className="mt-2 flex flex-wrap gap-2">
                {ruledOut.map((h) => (
                  <li key={h.id}>
                    <Badge>{h.code.replace(/_/g, ' ')}</Badge>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
        {inv.evidence.some((e) => e.result !== 'neutral') ? (
          <div>
            <h4 className="label-mono mb-2 text-ink-2">{T.evidence}</h4>
            <ul className="flex flex-col gap-2">
              {inv.evidence
                .filter((e) => e.result !== 'neutral')
                .map((e) => (
                  <li key={e.id} className="rounded-control bg-agent-tint px-4 py-3 text-small">
                    <p className="font-medium capitalize text-ink">
                      {e.test_code.replace(/_/g, ' ')}
                    </p>
                    <p className="tabular mt-1 text-ink-2">
                      {Object.entries(e.numbers)
                        .map(([k, v]) =>
                          typeof v === 'number' && k.endsWith('paise')
                            ? `${k.replace(/_paise$/, '').replace(/_/g, ' ')}: ${formatINR(v, { paise: 'never' })}`
                            : `${k.replace(/_/g, ' ')}: ${String(v)}`,
                        )
                        .join(' · ')}
                    </p>
                    {e.txn_ids.length ? (
                      <p className="mt-1 text-ink-3">{e.txn_ids.length} transaction(s) cited</p>
                    ) : null}
                  </li>
                ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function useInvestigation() {
  return useMutation({
    mutationFn: (
      v:
        | { kind: 'anomaly'; id: string }
        | { kind: 'change'; period: string; category: string | null },
    ) =>
      v.kind === 'anomaly'
        ? api.investigateAnomaly(v.id)
        : api.investigateChange(v.period, v.category),
  });
}

function InvestigatePanel() {
  const session = useSession();
  const categories = useCategories();
  const anomalies = useQuery({ queryKey: ['anomalies'], queryFn: api.anomalies });
  const run = useInvestigation();
  const [category, setCategory] = useState('');
  const period = session.data ? previousPeriod(session.data.period) : '';

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
      <div className="flex flex-col gap-5">
        <Card labelledBy="anom-title">
          <CardHeader id="anom-title" label="Unusual payments" />
          {anomalies.isPending ? (
            <div className="p-6">
              <SkeletonBlock lines={4} />
            </div>
          ) : anomalies.data && anomalies.data.length > 0 ? (
            <ul>
              {anomalies.data.map((a) => (
                <li
                  key={a.id}
                  className="flex items-center justify-between gap-3 border-b border-hairline px-6 py-3 last:border-b-0"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] capitalize">{a.merchant}</span>
                    <span className="text-small text-ink-3">
                      {KIND_LABEL[a.kind] ?? a.kind} · {formatDay(a.occurred_at)}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="tabular text-cell">
                      {formatINR(a.amount_paise, { paise: 'never' })}
                    </span>
                    <Button size="sm" onClick={() => run.mutate({ kind: 'anomaly', id: a.id })}>
                      Investigate
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="p-6">
              <EmptyState message="No unusual payments found." />
            </div>
          )}
        </Card>
        <Card labelledBy="chg-title">
          <CardHeader id="chg-title" label="Why did a category change?" />
          <form
            className="flex flex-col gap-3 p-6"
            onSubmit={(e) => {
              e.preventDefault();
              run.mutate({ kind: 'change', period, category: category || null });
            }}
          >
            <label className="flex flex-col gap-1.5">
              <span className="label-mono text-ink-3">{copy.transactions.category}</span>
              <select
                className={field}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">All categories</option>
                {(categories.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-small text-ink-3">{period ? formatPeriod(period) : ''}</p>
            <Button variant="primary" type="submit" busy={run.isPending}>
              Investigate
            </Button>
          </form>
        </Card>
      </div>
      <div>
        {run.isPending ? (
          <Card className="flex items-center gap-4 p-6">
            <AgentMark working />
            <span className="text-body text-ink-2">{T.working}</span>
          </Card>
        ) : run.error ? (
          <Card className="p-6">
            <ErrorState
              code={run.error instanceof ApiError ? run.error.code : 'UNKNOWN'}
              message={run.error.message}
            />
          </Card>
        ) : run.data ? (
          <InvestigationView out={run.data} />
        ) : (
          <EmptyState message="Pick a payment or a category to see which explanations hold up, with the evidence behind each." />
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------
// What if
// ------------------------------------------------------------------------------------------

function WhatIfPanel() {
  const categories = useCategories();
  const toast = useToast();
  const [kind, setKind] = useState<'add_spend' | 'reduce_spend'>('add_spend');
  const [category, setCategory] = useState('food');
  const [amount, setAmount] = useState('2000');
  const [months, setMonths] = useState('6');
  const compare = useMutation({
    mutationFn: (): Promise<CompareOut> => {
      const paise = parseRupeesToPaise(amount);
      if (paise === null) throw new Error('Enter an amount in rupees, for example 2000.');
      return api.compare([
        {
          kind,
          category_id: category,
          amount_paise: paise,
          recurring: true,
          months: Number(months),
        },
      ]);
    },
    onError: (e) => toast({ message: e.message, tone: 'negative' }),
  });
  const cmp = compare.data?.comparison;
  const goalStatus = (projection: NonNullable<typeof cmp>['baseline']) => {
    const values = Object.values(projection.goal_impacts);
    return values[values.length - 1] ?? null;
  };

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <Card labelledBy="wi-title">
        <CardHeader id="wi-title" label={T.whatIf} />
        <form
          className="flex flex-col gap-4 p-6"
          onSubmit={(e) => {
            e.preventDefault();
            compare.mutate();
          }}
        >
          <div className="flex gap-1.5" role="group" aria-label="Change">
            <Chip selected={kind === 'add_spend'} onClick={() => setKind('add_spend')}>
              Spend more
            </Chip>
            <Chip selected={kind === 'reduce_spend'} onClick={() => setKind('reduce_spend')}>
              Spend less
            </Chip>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="label-mono text-ink-3">{copy.transactions.category}</span>
            <select
              className={field}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {(categories.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label-mono text-ink-3">Each month, in rupees</span>
            <input
              className={field}
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label-mono text-ink-3">For how many months</span>
            <select className={field} value={months} onChange={(e) => setMonths(e.target.value)}>
              {['3', '6', '12'].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <Button variant="primary" type="submit" busy={compare.isPending}>
            Compare with now
          </Button>
        </form>
      </Card>

      <div>
        {compare.isPending ? (
          <Card className="p-6">
            <SkeletonBlock lines={6} />
          </Card>
        ) : cmp ? (
          <Card className="border-agent/30" labelledBy="cmp-title">
            <div className="flex items-center gap-2 border-b border-hairline px-6 py-3">
              <AgentMark />
              <h3 id="cmp-title" className="label-mono text-agent">
                Monthly surplus: now and with this change
              </h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-hairline text-small text-ink-3">
                    <th className="px-6 py-2 font-normal">Month</th>
                    <th className="px-4 py-2 text-right font-normal">Now</th>
                    <th className="px-6 py-2 text-right font-normal">With change</th>
                  </tr>
                </thead>
                <tbody>
                  {cmp.side_by_side.map((row) => (
                    <tr
                      key={String(row.month)}
                      className="border-b border-hairline last:border-b-0"
                    >
                      <td className="px-6 py-2.5 text-[14px]">{formatPeriod(String(row.month))}</td>
                      <td className="tabular px-4 py-2.5 text-right text-cell">
                        {formatINR(Number(row.baseline_surplus_paise), { paise: 'never' })}
                      </td>
                      <td className="tabular px-6 py-2.5 text-right text-cell font-medium">
                        {formatINR(Number(row.scenario_1_surplus_paise), { paise: 'never' })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-3 border-t border-hairline p-6">
              <p className="text-[14px]">
                {T.goals}:{' '}
                <Badge tone="neutral">
                  {(goalStatus(cmp.baseline) ?? 'no goal').replace(/_/g, ' ')}
                </Badge>{' '}
                now,{' '}
                <Badge tone="agent">
                  {(goalStatus(cmp.scenarios[0]!) ?? 'no goal').replace(/_/g, ' ')}
                </Badge>{' '}
                with this change
              </p>
              <ul className="list-disc pl-5 text-small text-ink-3">
                {cmp.scenarios[0]?.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          </Card>
        ) : (
          <EmptyState message="Describe a change to your spending to see its effect on each month's surplus and on your goals." />
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------
// Goals, alerts, activity
// ------------------------------------------------------------------------------------------

function GoalsAlertsPanel() {
  const goals = useGoals();
  const alerts = useAlerts();
  const queryClient = useQueryClient();
  const toast = useToast();
  const decide = useMutation({
    mutationFn: (v: { id: string; action: 'acknowledge' | 'dismiss' | 'snooze' }) =>
      api.decideAlert(v.id, {
        action: v.action,
        snooze_days: v.action === 'snooze' ? 3 : null,
        reason: null,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
    onError: (e) => toast({ message: e.message, tone: 'negative' }),
  });
  return (
    <div id="alerts" className="grid items-start gap-5 lg:grid-cols-2">
      <Card labelledBy="goals-title">
        <CardHeader id="goals-title" label={T.goals} />
        {goals.isPending ? (
          <div className="p-6">
            <SkeletonBlock lines={3} />
          </div>
        ) : goals.data && goals.data.goals.length > 0 ? (
          <ul>
            {goals.data.goals.map((g) => (
              <li
                key={g.id}
                className="flex flex-col gap-2 border-b border-hairline px-6 py-4 last:border-b-0"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[15px] font-medium">{g.name}</span>
                  <Badge>{g.status}</Badge>
                </div>
                <p className="tabular text-small text-ink-2">
                  {formatINR(
                    goals.data.progress.find((p) => p.goal_id === g.id)?.current_paise ??
                      g.current_paise,
                    { paise: 'never' },
                  )}{' '}
                  of {formatINR(g.target_paise, { paise: 'never' })}
                  {g.deadline ? ` by ${formatDay(`${g.deadline}T06:30:00Z`)}` : ''}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <div className="p-6">
            <EmptyState message="No goals yet." />
          </div>
        )}
      </Card>
      <Card labelledBy="alerts2-title">
        <CardHeader id="alerts2-title" label={T.alerts} />
        {alerts.isPending ? (
          <div className="p-6">
            <SkeletonBlock lines={3} />
          </div>
        ) : alerts.data && alerts.data.alerts.length > 0 ? (
          <ul>
            {alerts.data.alerts.map((raw) => {
              const a = raw as { id: string; severity: string; why_text: string; status: string };
              return (
                <li
                  key={a.id}
                  className="flex flex-col gap-2 border-b border-hairline px-6 py-4 last:border-b-0"
                >
                  <div className="flex items-center gap-2">
                    <Badge
                      tone={
                        a.severity === 'critical'
                          ? 'negative'
                          : a.severity === 'info'
                            ? 'neutral'
                            : 'attention'
                      }
                    >
                      {a.severity}
                    </Badge>
                    <Badge>{a.status}</Badge>
                  </div>
                  <p className="text-[14px]">{a.why_text}</p>
                  {a.status === 'open' ? (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => decide.mutate({ id: a.id, action: 'acknowledge' })}
                      >
                        Acknowledge
                      </Button>
                      <Button
                        size="sm"
                        variant="text"
                        onClick={() => decide.mutate({ id: a.id, action: 'snooze' })}
                      >
                        Snooze
                      </Button>
                      <Button
                        size="sm"
                        variant="text"
                        onClick={() => decide.mutate({ id: a.id, action: 'dismiss' })}
                      >
                        Dismiss
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="p-6">
            <EmptyState message={copy.dashboard.alertsEmpty} />
          </div>
        )}
      </Card>
    </div>
  );
}

type RouterKey = {
  id: string;
  state: string;
  calls: number;
  rate_limited: number;
  load_pct: number;
};

function RouterCard() {
  const status = useQuery({ queryKey: ['llm-status'], queryFn: api.llmStatus, retry: false });
  const providers = (status.data?.router?.providers ?? {}) as Record<string, { keys: RouterKey[] }>;
  if (!status.data) return null;
  return (
    <Card labelledBy="router-title">
      <CardHeader id="router-title" label="Model router" />
      <div className="flex flex-col gap-2 p-6 text-small text-ink-2" data-testid="router-card">
        {!status.data.available ? (
          <p>No model is configured, so every answer is written from your data by rules.</p>
        ) : (
          Object.entries(providers).map(([name, p]) => (
            <p key={name}>
              <span className="font-medium text-ink">{name}</span>:{' '}
              {p.keys.filter((k) => k.state === 'ready').length} of {p.keys.length} keys ready,{' '}
              {p.keys.reduce((n, k) => n + k.calls, 0)} calls,{' '}
              {p.keys.reduce((n, k) => n + k.rate_limited, 0)} rate limits absorbed
            </p>
          ))
        )}
      </div>
    </Card>
  );
}

function ActivityPanel() {
  const timeline = useTimeline();
  if (timeline.isPending)
    return (
      <Card className="p-6">
        <SkeletonBlock lines={6} />
      </Card>
    );
  if (timeline.error)
    return (
      <Card className="p-6">
        <ErrorState
          code={timeline.error instanceof ApiError ? timeline.error.code : 'UNKNOWN'}
          message={timeline.error.message}
          onRetry={() => void timeline.refetch()}
        />
      </Card>
    );
  const { entries, pending_approvals: pending } = timeline.data;
  return (
    <div className="flex flex-col gap-5">
      <RouterCard />
      {pending.length > 0 ? (
        <Card labelledBy="pend-title" className="border-agent/30">
          <CardHeader id="pend-title" label={T.pendingApprovals} />
          <ul>
            {pending.map((p, i) => (
              <li
                key={`${p.ts}-${p.title}-${i}`}
                className="border-b border-hairline px-6 py-3 last:border-b-0"
              >
                <p className="text-[14px]">{p.title}</p>
                <p className="text-small text-ink-3">{p.detail}</p>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <Card labelledBy="act-title">
        <CardHeader id="act-title" label={T.timeline} />
        {entries.length === 0 ? (
          <div className="p-6">
            <EmptyState message="No agent activity yet." />
          </div>
        ) : (
          <ol>
            {entries.slice(0, 60).map((e, i) => (
              <li
                key={`${e.ts}-${e.kind}-${e.title}-${i}`}
                className="grid grid-cols-[6rem_10rem_minmax(0,1fr)] gap-3 border-b border-hairline px-6 py-3 last:border-b-0"
              >
                <span className="text-small text-ink-3">
                  {formatDay(e.ts)}
                  <br />
                  {formatTime(e.ts)}
                </span>
                <span>
                  <Badge
                    tone={
                      e.kind === 'refusal' || e.kind === 'error'
                        ? 'negative'
                        : e.kind === 'investigation' || e.kind === 'simulation'
                          ? 'agent'
                          : 'neutral'
                    }
                  >
                    {e.kind.replace(/_/g, ' ')}
                  </Badge>
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[14px]">{e.title}</span>
                  <span className="block truncate text-small text-ink-3">{e.detail}</span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

export function AgentScreen() {
  const location = useLocation();
  const fromHash: Tab =
    location.hash === '#activity' ? 'activity' : location.hash === '#alerts' ? 'goals' : 'ask';
  const [tab, setTab] = useState<Tab>(fromHash);
  const [seenHash, setSeenHash] = useState(location.hash);
  if (seenHash !== location.hash) {
    // Following the sidebar's Activity link while already here switches the tab.
    setSeenHash(location.hash);
    setTab(fromHash);
  }
  return (
    <Page
      title={T.title}
      lead="Ask, investigate, test a change, and see exactly what the agent did."
    >
      <div role="tablist" aria-label={T.title} className="mb-6 flex flex-wrap gap-1.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`inline-flex h-8 items-center rounded-chip px-4 text-small transition-colors duration-fast ${tab === t.id ? 'bg-agent text-ink-inverse' : 'text-ink-2 hover:bg-surface-sunken'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'ask' ? <AskPanel /> : null}
        {tab === 'investigate' ? <InvestigatePanel /> : null}
        {tab === 'whatif' ? <WhatIfPanel /> : null}
        {tab === 'goals' ? <GoalsAlertsPanel /> : null}
        {tab === 'activity' ? <ActivityPanel /> : null}
      </div>
    </Page>
  );
}
