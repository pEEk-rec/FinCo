import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../api/client';
import { keys, useInvalidateFinancials } from '../api/hooks';
import { formatINR } from '../format/money';
import { Badge } from './Badge';
import { Button } from './Button';
import { Card, CardHeader } from './Card';

const AUTO_MS = 9000;

/**
 * The step after connecting: new payments now arrive as they happen. Each one is played through
 * the very path a real bank alert takes, so a card pops up (or a quiet "Tagged" chip) exactly as
 * it would for a real payment. Marked simulated, always.
 */
export function LiveDemoFeed() {
  const invalidate = useInvalidateFinancials();
  const client = useQueryClient();
  const [auto, setAuto] = useState(false);
  const [sent, setSent] = useState<Awaited<ReturnType<typeof api.demoLivePayment>>[]>([]);

  const play = useMutation({
    mutationFn: api.demoLivePayment,
    onSuccess: async (out) => {
      setSent((all) => [out, ...all].slice(0, 5));
      await Promise.all([invalidate(), client.invalidateQueries({ queryKey: keys.capture })]);
    },
  });

  const playRef = useRef(play.mutate);
  useEffect(() => {
    playRef.current = play.mutate;
  });
  useEffect(() => {
    if (!auto) return;
    const timer = window.setInterval(() => playRef.current(), AUTO_MS);
    return () => window.clearInterval(timer);
  }, [auto]);

  return (
    <Card labelledBy="live-feed-title">
      <CardHeader id="live-feed-title" label="Live payments">
        <Badge tone="agent">Simulated</Badge>
      </CardHeader>
      <div className="flex flex-col gap-4 p-6">
        <p className="text-[14px] text-ink-2">
          Your bank is connected and its history is in. Now watch what happens when you pay: each
          button press plays one new payment through the same steps a real bank alert takes. A card
          asks you what it was, or, for a shop FinCo already knows, tags it quietly.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" busy={play.isPending} onClick={() => play.mutate()}>
            Send next live payment
          </Button>
          <label className="flex items-center gap-2 text-small text-ink-2">
            <input
              type="checkbox"
              checked={auto}
              onChange={(e) => setAuto(e.target.checked)}
              className="size-4 accent-[var(--color-brand)]"
            />
            Play one every {AUTO_MS / 1000} seconds
          </label>
        </div>
        {play.error ? (
          <p role="alert" className="text-small text-negative">
            {play.error instanceof ApiError ? play.error.message : 'Could not send that.'}
          </p>
        ) : null}
        {sent.length > 0 ? (
          <ul aria-label="Payments played" className="flex flex-col divide-y divide-hairline">
            {sent.map((s, i) => (
              <li key={`${s.position}-${i}`} className="flex flex-col gap-0.5 py-2.5">
                <p className="flex items-baseline justify-between gap-3 text-[14px]">
                  <span className="font-semibold text-ink">{s.counterparty}</span>
                  <span className="tabular text-ink">
                    {formatINR(s.amount_paise, { paise: 'auto' })}
                  </span>
                </p>
                <p className="text-small text-ink-3">{s.note}</p>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  );
}
