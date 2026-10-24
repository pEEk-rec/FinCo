import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';

import { api, ApiError, type ConsentView, type ImportResult } from '../api/client';
import { useConsents, useImports, keys, useInvalidateFinancials } from '../api/hooks';
import { Badge } from '../components/Badge';
import { BankLink } from '../components/BankLink';
import { Button } from '../components/Button';
import { Card, CardHeader } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { copy } from '../copy/en';
import { Constellation, type ClusterSpec, type ParticleSpec } from '../constellation/Constellation';
import { formatDay } from '../format/date';

const T = copy.connect;
const PARTICLE_CAP = 1500;
const REVIEW = '__review__';
const STATUS_TONE = {
  pending: 'attention',
  active: 'positive',
  expired: 'neutral',
  revoked: 'negative',
} as const;

/** Convert a real import result into constellation particles and clusters. */
function toConstellation(result: ImportResult, names: Map<string, string>) {
  const events = result.events.slice(0, PARTICLE_CAP);
  const clusterIds = [
    ...new Set(
      events.filter((e) => !e.needs_review && e.category_id).map((e) => e.category_id as string),
    ),
  ];
  const countBy = new Map<string, number>();
  for (const e of events) {
    const key = e.needs_review || !e.category_id ? REVIEW : e.category_id;
    countBy.set(key, (countBy.get(key) ?? 0) + 1);
  }
  const clusters: ClusterSpec[] = clusterIds.map((id, i) => ({
    id,
    label: names.get(id) ?? id,
    hue: i,
    countText: String(countBy.get(id) ?? 0),
  }));
  clusters.push({
    id: REVIEW,
    label: T.needsYou,
    hue: 0,
    isReview: true,
    countText: String(countBy.get(REVIEW) ?? 0),
  });
  const final: ParticleSpec[] = events.map((e) => ({
    id: e.transaction_id,
    state:
      e.needs_review || !e.category_id
        ? 'review'
        : e.source === 'llm' || e.source === 'cache'
          ? 'ai'
          : 'rule',
    clusterId: e.needs_review || !e.category_id ? REVIEW : e.category_id,
  }));
  return { clusters, final, capped: result.events.length > PARTICLE_CAP };
}

function ConsentCard({
  consent,
  onImport,
  busy,
}: {
  consent: ConsentView;
  onImport: () => void;
  busy: boolean;
}) {
  const queryClient = useQueryClient();
  const revoke = useMutation({
    mutationFn: () => api.revokeConsent(consent.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.consents }),
  });
  return (
    <Card labelledBy={`consent-${consent.id}`}>
      <CardHeader id={`consent-${consent.id}`} label={T.consentTitle}>
        <Badge tone={STATUS_TONE[consent.status]}>{T.status[consent.status]}</Badge>
      </CardHeader>
      <div className="flex flex-col gap-6 p-6">
        <p className="max-w-prose text-body text-ink-2">{T.consentBody}</p>
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <div>
            <dt className="label-mono text-ink-3">{T.accounts}</dt>
            <dd className="mt-1 text-[14px]">{consent.account_names.join(', ')}</dd>
          </div>
          <div>
            <dt className="label-mono text-ink-3">{T.range}</dt>
            <dd className="mt-1 text-[14px]">
              {formatDay(consent.range_from)} to {formatDay(consent.range_to)}
            </dd>
          </div>
          <div>
            <dt className="label-mono text-ink-3">{T.purpose}</dt>
            <dd className="mt-1 text-[14px]">{consent.purpose}</dd>
          </div>
          <div>
            <dt className="label-mono text-ink-3">{T.expires}</dt>
            <dd className="mt-1 text-[14px]">
              {consent.expires_at ? formatDay(consent.expires_at) : '–'}
            </dd>
          </div>
        </dl>
        <div className="flex flex-wrap items-center gap-3">
          {consent.status === 'pending' || consent.status === 'active' ? (
            <Button variant="primary" busy={busy} onClick={onImport}>
              {consent.status === 'pending' ? T.approve : T.importAgain}
            </Button>
          ) : null}
          {consent.status === 'pending' || consent.status === 'active' ? (
            <Button variant="danger" busy={revoke.isPending} onClick={() => revoke.mutate()}>
              {T.revoke}
            </Button>
          ) : null}
        </div>
        {revoke.error ? <p className="text-small text-negative">{revoke.error.message}</p> : null}
      </div>
    </Card>
  );
}

export function ConnectScreen() {
  const consents = useConsents();
  const imports = useImports();
  const invalidate = useInvalidateFinancials();
  const queryClient = useQueryClient();
  const names = useMemo(() => new Map<string, string>(), []);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [settled, setSettled] = useState(false);

  const run = useMutation({
    mutationFn: async (consent: ConsentView) => {
      if (consent.status === 'pending') await api.approveConsent(consent.id);
      return api.runImport(consent.id);
    },
    onSuccess: async (data) => {
      setSettled(false);
      setResult(data);
      await invalidate();
      await queryClient.invalidateQueries({ queryKey: keys.consents });
      await queryClient.invalidateQueries({ queryKey: keys.imports });
    },
  });

  useEffect(() => {
    api
      .categories()
      .then((cats) => cats.forEach((c) => names.set(c.id, c.name)))
      .catch(() => undefined);
  }, [names]);

  useEffect(() => {
    if (!result) return;
    const timer = window.setTimeout(() => setSettled(true), 900);
    return () => window.clearTimeout(timer);
  }, [result]);

  const viz = useMemo(() => (result ? toConstellation(result, names) : null), [result, names]);
  const particles: ParticleSpec[] = useMemo(
    () =>
      viz
        ? viz.final.map((p) =>
            settled ? p : { ...p, clusterId: null, state: 'unassigned' as const },
          )
        : [],
    [viz, settled],
  );

  const top =
    consents.data?.find((c) => c.status === 'pending' || c.status === 'active') ??
    consents.data?.[0];

  return (
    <Page title={T.title} lead={copy.connect.consentBody}>
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <div className="flex flex-col gap-5">
          {consents.isPending ? (
            <Card className="p-6">
              <SkeletonBlock lines={5} />
            </Card>
          ) : consents.error ? (
            <Card className="p-6">
              <ErrorState
                code={consents.error instanceof ApiError ? consents.error.code : 'UNKNOWN'}
                message={consents.error.message}
                onRetry={() => void consents.refetch()}
              />
            </Card>
          ) : top ? (
            <ConsentCard consent={top} busy={run.isPending} onImport={() => run.mutate(top)} />
          ) : (
            <Card className="p-6">
              <EmptyState message={copy.dashboard.noData} />
            </Card>
          )}
          <BankLink />
          {imports.data && imports.data.length > 0 ? (
            <Card labelledBy="imports-title">
              <CardHeader id="imports-title" label="Imports" />
              <ul>
                {imports.data.map((b) => (
                  <li
                    key={b.id}
                    className="flex items-center justify-between gap-3 border-b border-hairline px-6 py-3 last:border-b-0"
                  >
                    <span className="text-small text-ink-2">
                      {b.started_at ? formatDay(b.started_at) : '–'}
                    </span>
                    <span className="tabular text-small">{T.fetched(String(b.fetched))}</span>
                    <Badge
                      tone={b.status === 'ok' || b.status === 'completed' ? 'positive' : 'neutral'}
                    >
                      {b.status}
                    </Badge>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>

        <Card labelledBy="constellation-title" className="overflow-hidden">
          <CardHeader id="constellation-title" label={T.importing} />
          <div className="p-4">
            {run.isPending ? (
              <div
                role="status"
                className="flex h-[360px] items-center justify-center text-body text-ink-2"
              >
                {T.importing}
              </div>
            ) : run.error ? (
              <div className="p-4">
                <ErrorState
                  code={run.error instanceof ApiError ? run.error.code : 'UNKNOWN'}
                  message={run.error.message}
                  onRetry={top ? () => run.mutate(top) : undefined}
                />
              </div>
            ) : result && result.inserted === 0 ? (
              <div className="flex h-[360px] items-center justify-center px-8 text-center text-body text-ink-2">
                {T.nothingNew(String(result.skipped_existing))}
              </div>
            ) : viz && result ? (
              <>
                <Constellation
                  particles={particles}
                  clusters={viz.clusters}
                  height={360}
                  ariaLabel={T.summary(
                    String(result.by_rule),
                    String(result.by_ai),
                    String(result.needs_review),
                  )}
                />
                <div className="flex flex-col gap-1 px-2 pt-3">
                  <p className="text-[14px] text-ink">
                    {T.fetched(String(result.fetched))}.{' '}
                    {T.summary(
                      String(result.by_rule),
                      String(result.by_ai),
                      String(result.needs_review),
                    )}
                  </p>
                  {viz.capped ? (
                    <p className="text-small text-ink-3">
                      {T.capped(String(PARTICLE_CAP), String(result.events.length))}
                    </p>
                  ) : null}
                  {result.needs_review > 0 ? (
                    <Link to="/review" className="mt-2 w-fit">
                      <Button variant="primary">{copy.dashboard.reviewCta}</Button>
                    </Link>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="flex h-[360px] items-center justify-center px-8 text-center text-body text-ink-3">
                {T.idle}
              </div>
            )}
          </div>
        </Card>
      </div>
    </Page>
  );
}
