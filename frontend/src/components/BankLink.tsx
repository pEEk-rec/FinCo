import { useState } from 'react';

import { ApiError, type BankLinkAction, type BankLinkFetch } from '../api/client';
import { useBankLink, useBankLinkWrites } from '../api/hooks';
import { Badge, type Tone } from './Badge';
import { Button } from './Button';
import { Card, CardHeader } from './Card';
import { EmptyState, ErrorState, SkeletonBlock } from './States';
import { copy } from '../copy/en';
import { formatDay } from '../format/date';

const T = copy.bankLink;

const TONE: Record<string, Tone> = {
  pending: 'attention',
  active: 'positive',
  paused: 'neutral',
  revoked: 'negative',
  expired: 'neutral',
};

const ACTION_LABEL: Record<BankLinkAction, string> = {
  approve: T.approve,
  pause: T.pause,
  resume: T.resume,
  revoke: T.revoke,
};

function Term({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="label-mono text-ink">{label}</dt>
      <dd className="mt-1 text-[14px] text-ink-2">{children}</dd>
    </div>
  );
}

/**
 * The consent artefact in plain words: what is read, why, how often, for how long, and how to take
 * it back. Every sentence comes from the API, which builds it from config.
 */
export function BankLink() {
  const link = useBankLink();
  const { create, act, fetchNow } = useBankLinkWrites();
  const [report, setReport] = useState<BankLinkFetch | null>(null);
  const consent = link.data?.consent ?? null;
  const failure = [create, act, fetchNow].find((m) => m.error)?.error;

  return (
    <Card labelledBy="bank-link-title">
      <CardHeader id="bank-link-title" label={T.title}>
        {consent ? (
          <Badge tone={TONE[consent.status] ?? 'neutral'}>{T.status[consent.status]}</Badge>
        ) : null}
      </CardHeader>
      <div className="flex flex-col gap-5 p-6">
        {link.isPending ? (
          <SkeletonBlock lines={4} />
        ) : link.error ? (
          <ErrorState
            code={link.error instanceof ApiError ? link.error.code : 'UNKNOWN'}
            message={link.error.message}
            onRetry={() => void link.refetch()}
          />
        ) : !consent ? (
          <>
            <EmptyState message={T.none} />
            <Button variant="primary" busy={create.isPending} onClick={() => create.mutate()}>
              {T.setUp}
            </Button>
          </>
        ) : (
          <>
            {consent.connector === 'mock' ? <Badge tone="agent">{T.practice}</Badge> : null}
            <dl className="grid gap-4">
              <Term label={T.what}>
                {consent.what.map((line) => (
                  <span key={line} className="block">
                    {line}
                  </span>
                ))}
              </Term>
              <Term label={T.why}>{consent.why}</Term>
              <Term label={T.often}>{consent.how_often}</Term>
              <Term label={T.long}>
                {consent.how_long}
                {consent.expires_at ? ` ${T.until(formatDay(consent.expires_at))}` : ''}
              </Term>
              <Term label={T.kept}>{consent.data_kept}</Term>
              <Term label={T.stop}>{consent.revoke}</Term>
            </dl>
            <div className="flex flex-wrap items-center gap-2">
              {consent.can.map((action) => (
                <Button
                  key={action}
                  variant={
                    action === 'approve' ? 'primary' : action === 'revoke' ? 'danger' : 'secondary'
                  }
                  size="sm"
                  busy={act.isPending}
                  onClick={() => act.mutate({ id: consent.id, action })}
                >
                  {ACTION_LABEL[action]}
                </Button>
              ))}
              {consent.status === 'active' ? (
                <Button
                  size="sm"
                  variant="secondary"
                  busy={fetchNow.isPending}
                  onClick={() => fetchNow.mutate(undefined, { onSuccess: setReport })}
                >
                  {T.fetchNow}
                </Button>
              ) : null}
            </div>
            {consent.last_fetch_at ? (
              <p className="text-small text-ink-2">
                {T.lastFetched(formatDay(consent.last_fetch_at))}
              </p>
            ) : null}
            {report ? (
              <p role="status" className="text-small text-ink">
                {T.report(report.inserted, report.matched)}
              </p>
            ) : null}
          </>
        )}
        {failure ? (
          <p role="alert" className="text-small text-negative">
            {failure.message}
          </p>
        ) : null}
      </div>
    </Card>
  );
}
