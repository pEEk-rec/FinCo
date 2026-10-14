import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { Link } from 'react-router';

import {
  api,
  ApiError,
  type LiveEvent,
  type LiveImport,
  type LivePaceRow,
  type LiveReceipt,
} from '../api/client';
import { useInvalidateFinancials } from '../api/hooks';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { Card, CardHeader } from '../components/Card';
import { Page } from '../components/Shell';
import { ErrorState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';

const field =
  'h-10 w-full rounded-control border border-input-border bg-surface px-3 text-[14px] text-ink placeholder:text-ink-3';
const area =
  'min-h-24 w-full rounded-control border border-input-border bg-surface p-3 font-mono text-[13px] text-ink placeholder:text-ink-3';

const PACE_TONE: Record<string, 'positive' | 'attention' | 'negative'> = {
  ok: 'positive',
  watch: 'attention',
  projected_over: 'negative',
  over: 'negative',
};

function useLiveRefresh() {
  const client = useQueryClient();
  const invalidate = useInvalidateFinancials();
  return () => {
    invalidate();
    void client.invalidateQueries({ queryKey: ['live'] });
  };
}

function ImportSummary({ result }: { result: LiveImport }) {
  return (
    <div className="mt-4 rounded-control bg-surface-sunken p-4 text-[14px]" role="status">
      <p>
        Read <span className="tabular">{result.read}</span> rows from your statement.{' '}
        <span className="tabular">{result.inserted}</span> new,{' '}
        <span className="tabular">{result.skipped_existing}</span> already there.
      </p>
      {result.ai_used && result.ai_applied > 0 ? (
        <p className="mt-1">
          The AI labelled <span className="tabular">{result.ai_applied}</span> rows that the rules
          did not know. Unsure ones are left for you.
        </p>
      ) : null}
      {result.ai_note ? <p className="mt-1 text-ink-2">{result.ai_note}</p> : null}
      {result.needs_review > 0 ? (
        <p className="mt-1">
          <span className="tabular">{result.needs_review}</span> need a category from you.{' '}
          <Link to="/review" className="text-agent underline">
            Open the review queue
          </Link>
        </p>
      ) : null}
      {result.verified_alerts > 0 ? (
        <p className="mt-1">
          <span className="tabular">{result.verified_alerts}</span> phone alerts were confirmed by
          this statement.
        </p>
      ) : null}
      {result.unreadable > 0 ? (
        <details className="mt-2 text-small text-ink-2">
          <summary className="cursor-pointer">
            <span className="tabular">{result.unreadable}</span> rows could not be read
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {result.unreadable_examples.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function PaceBar({ row }: { row: LivePaceRow }) {
  const settled = Math.min(100, row.percent_settled);
  const both = Math.min(100, row.percent_settled + row.percent_provisional);
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{row.category_name}</span>
        <span className="tabular text-[14px]">
          {row.total} of {row.limit}{' '}
          <Badge tone={PACE_TONE[row.status] ?? 'neutral'}>{row.status.replace('_', ' ')}</Badge>
        </span>
      </div>
      <div
        className="relative my-2 h-2.5 overflow-hidden rounded-full border border-hairline bg-surface-sunken"
        role="img"
        aria-label={`${row.category_name}: ${row.total} of ${row.limit}`}
      >
        <span
          className="absolute inset-y-0 left-0 bg-agent"
          style={{ width: `${settled}%` }}
          aria-hidden
        />
        <span
          className="absolute inset-y-0 bg-attention"
          style={{ left: `${settled}%`, width: `${both - settled}%` }}
          aria-hidden
        />
      </div>
      <p className="text-small text-ink-2">{row.message}</p>
    </li>
  );
}

export function LiveScreen() {
  const toast = useToast();
  const refresh = useLiveRefresh();
  const file = useRef<HTMLInputElement>(null);
  const status = useQuery({ queryKey: ['live', 'status'], queryFn: api.live.status });
  const pacing = useQuery({ queryKey: ['live', 'pacing'], queryFn: api.live.pacing });
  const events = useQuery({ queryKey: ['live', 'events'], queryFn: api.live.events });
  const [imported, setImported] = useState<LiveImport | null>(null);
  const [receiptText, setReceiptText] = useState('');
  const [receipt, setReceipt] = useState<LiveReceipt | null>(null);
  const [mobile, setMobile] = useState('');
  const [consent, setConsent] = useState<{ id: string; url: string } | null>(null);
  const [consentState, setConsentState] = useState('');

  const onError = (e: Error) => toast({ message: e.message, tone: 'negative' });
  const upload = useMutation({
    mutationFn: async (f: File) => api.live.importStatement(await f.text(), f.name),
    onSuccess: (r) => {
      setImported(r);
      refresh();
    },
    onError,
  });
  const readReceipt = useMutation({
    mutationFn: () => api.live.receipt(receiptText),
    onSuccess: setReceipt,
    onError,
  });
  const decide = useMutation({
    mutationFn: (v: { id: string; decision: 'approved' | 'rejected' }) =>
      api.live.decideSplit(v.id, v.decision),
    onSuccess: () => {
      setReceipt(null);
      refresh();
    },
    onError,
  });
  const reconcile = useMutation({
    mutationFn: api.live.reconcile,
    onSuccess: refresh,
    onError,
  });
  const startConsent = useMutation({
    mutationFn: () => api.live.aaConsent(mobile),
    onSuccess: (c) => {
      setConsent(c);
      setConsentState('PENDING');
      if (c.url) window.open(c.url, '_blank', 'noopener');
    },
    onError,
  });
  const checkConsent = useMutation({
    mutationFn: () => api.live.aaStatus(consent?.id ?? ''),
    onSuccess: (r) => setConsentState(r.status),
    onError,
  });
  const fetchAA = useMutation({
    mutationFn: () => api.live.aaFetch(consent?.id ?? ''),
    onSuccess: (r) => {
      setImported(r);
      refresh();
    },
    onError,
  });

  if (status.isPending)
    return (
      <Page title="Live data">
        <Card className="p-6">
          <SkeletonBlock lines={6} />
        </Card>
      </Page>
    );
  if (status.error)
    return (
      <Page title="Live data">
        <Card className="p-6">
          <ErrorState
            code={status.error instanceof ApiError ? status.error.code : 'NOT_LIVE'}
            message="This server is not running in live mode. Start it with npm run live."
            onRetry={() => void status.refetch()}
          />
        </Card>
      </Page>
    );
  const live = status.data;

  return (
    <Page
      title="Live data"
      lead="Your own bank data, read only. Import a statement, forward your bank alerts, and watch the budgets react."
    >
      <div className="flex flex-col gap-6">
        <Card labelledBy="live-import">
          <CardHeader id="live-import" label="Import your statement" />
          <div className="p-6">
            <p className="text-[14px] text-ink-2">
              Download the statement from your bank&apos;s net banking as CSV and choose it here. It
              is read on this computer and stored in the live database only. Importing the same
              period twice adds nothing.
            </p>
            <input
              ref={file}
              type="file"
              accept=".csv,.txt,.tsv,text/csv"
              className="sr-only"
              aria-label="Statement file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = '';
              }}
            />
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                busy={upload.isPending}
                onClick={() => file.current?.click()}
              >
                Choose statement file
              </Button>
              <span className="text-small text-ink-3">
                <span className="tabular">{live.counts.transactions}</span> payments held so far
              </span>
            </div>
            {imported ? <ImportSummary result={imported} /> : null}
          </div>
        </Card>

        <Card labelledBy="live-pace">
          <CardHeader id="live-pace" label="Budget pace this month" />
          <div className="p-6">
            {pacing.data ? (
              <>
                <p className="serif-light text-[22px]">{pacing.data.headline}</p>
                <ul className="mt-2 divide-y divide-hairline">
                  {pacing.data.rows.map((row) => (
                    <PaceBar key={row.category_id} row={row} />
                  ))}
                </ul>
                <p className="mt-2 text-small text-ink-3">
                  Dark: confirmed by the statement. Amber: alerts the statement has not confirmed
                  yet.
                </p>
              </>
            ) : (
              <SkeletonBlock lines={4} />
            )}
          </div>
        </Card>

        <Card labelledBy="live-alerts">
          <CardHeader id="live-alerts" label="Phone alerts" />
          <div className="flex flex-col gap-4 p-6">
            <p className="text-[14px] text-ink-2">
              Install an SMS forwarder app on your Android phone and point it at the address below.
              Each bank alert becomes a pending payment within seconds and is confirmed when the
              statement arrives. One-time passwords and failed payments are ignored.
            </p>
            <dl className="grid gap-2 text-small sm:grid-cols-[8rem_minmax(0,1fr)]">
              <dt className="text-ink-3">Address</dt>
              <dd className="break-all font-mono">
                POST http://&lt;this computer&gt;:&lt;live port&gt;{live.webhook.path}
              </dd>
              <dt className="text-ink-3">Header</dt>
              <dd className="break-all font-mono">X-Webhook-Secret: {live.webhook.secret}</dd>
              <dt className="text-ink-3">Body</dt>
              <dd className="font-mono">{'{ "text": "<the SMS>" }'}</dd>
            </dl>
            <div className="flex flex-wrap items-center gap-3">
              <Button busy={reconcile.isPending} onClick={() => reconcile.mutate()}>
                Match alerts to the statement
              </Button>
              <span className="text-small text-ink-3">
                <span className="tabular">{live.counts.alerts_waiting}</span> alerts waiting for the
                statement
              </span>
            </div>
            <EventTable events={events.data ?? []} />
          </div>
        </Card>

        <Card labelledBy="live-receipt">
          <CardHeader id="live-receipt" label="Receipts" />
          <div className="flex flex-col gap-3 p-6">
            <p className="text-[14px] text-ink-2">
              Paste the text of an order receipt. If it matches a payment, a split by category is
              drafted. Nothing changes until you approve it.
            </p>
            <textarea
              className={area}
              value={receiptText}
              onChange={(e) => setReceiptText(e.target.value)}
              aria-label="Receipt text"
              placeholder="Paste a receipt"
            />
            <div>
              <Button
                busy={readReceipt.isPending}
                onClick={() => receiptText.trim() && readReceipt.mutate()}
              >
                Read receipt
              </Button>
            </div>
            {receipt ? (
              receipt.outcome === 'suggested' && receipt.receipt_id ? (
                <div className="rounded-control bg-surface-sunken p-4" role="status">
                  <p className="text-[14px]">Drafted split. Approve it to move the amounts.</p>
                  <ul className="mt-2">
                    {receipt.parts.map((p) => (
                      <li key={p.id} className="flex justify-between py-1 text-[14px]">
                        <span>{p.category_name ?? p.category_id}</span>
                        <span className="tabular">{p.amount}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="primary"
                      onClick={() =>
                        decide.mutate({ id: receipt.receipt_id!, decision: 'approved' })
                      }
                    >
                      Approve split
                    </Button>
                    <Button
                      onClick={() =>
                        decide.mutate({ id: receipt.receipt_id!, decision: 'rejected' })
                      }
                    >
                      Reject
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="text-[14px] text-ink-2" role="status">
                  {receipt.reason ?? 'That receipt could not be used.'}
                </p>
              )
            ) : null}
          </div>
        </Card>

        <Card labelledBy="live-aa">
          <CardHeader id="live-aa" label="Account Aggregator" />
          <div className="flex flex-col gap-3 p-6">
            <p className="text-[14px] text-ink-2">
              The regulated, consent-based way to fetch statements. It needs gateway credentials
              from an Account Aggregator provider, and a sandbox gives test data only.
            </p>
            {!live.aa.configured ? (
              <p className="rounded-control bg-surface-sunken p-3 text-small text-ink-2">
                {live.aa.note}
              </p>
            ) : (
              <>
                <p className="text-small text-ink-3">Gateway: {live.aa.gateway}</p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    className={field}
                    value={mobile}
                    onChange={(e) => setMobile(e.target.value)}
                    inputMode="tel"
                    aria-label="Mobile number registered with your bank"
                    placeholder="Mobile number registered with your bank"
                  />
                  <Button
                    variant="primary"
                    busy={startConsent.isPending}
                    onClick={() => mobile.trim() && startConsent.mutate()}
                  >
                    Start consent
                  </Button>
                </div>
                {consent ? (
                  <div className="flex flex-wrap items-center gap-3 text-[14px]">
                    <span>
                      Consent: <Badge tone="attention">{consentState || 'PENDING'}</Badge>
                    </span>
                    <Button busy={checkConsent.isPending} onClick={() => checkConsent.mutate()}>
                      Check status
                    </Button>
                    <Button
                      variant="primary"
                      busy={fetchAA.isPending}
                      onClick={() => fetchAA.mutate()}
                    >
                      Fetch my data
                    </Button>
                  </div>
                ) : null}
              </>
            )}
          </div>
        </Card>
      </div>
    </Page>
  );
}

function EventTable({ events }: { events: LiveEvent[] }) {
  if (events.length === 0)
    return <p className="text-small text-ink-3">No alerts have arrived yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[14px]">
        <thead>
          <tr className="text-left text-small text-ink-3">
            <th className="py-1 pr-3 font-normal">Merchant</th>
            <th className="py-1 pr-3 font-normal">Category</th>
            <th className="py-1 pr-3 text-right font-normal">Amount</th>
            <th className="py-1 font-normal">Status</th>
          </tr>
        </thead>
        <tbody>
          {events.slice(0, 12).map((e) => (
            <tr key={e.id} className="border-t border-hairline">
              <td className="py-1.5 pr-3">{e.merchant}</td>
              <td className="py-1.5 pr-3 text-ink-2">
                {e.category_name ?? (e.needs_review ? 'Needs your category' : 'Unsorted')}
              </td>
              <td className="tabular py-1.5 pr-3 text-right">{e.amount}</td>
              <td className="py-1.5">
                <Badge tone={e.status === 'verified' ? 'positive' : 'attention'}>{e.status}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
