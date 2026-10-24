import { Lightning } from '@phosphor-icons/react';
import { AnimatePresence } from 'motion/react';
import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router';

import { ApiError, type CaptureInbox, type CaptureSimulated } from '../api/client';
import { useBridgeHealth, useCaptureInbox, useCaptureWrites, usePushStatus } from '../api/hooks';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { PaymentPrompt, useTagPayment } from '../components/capture/PaymentPrompt';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { usePush } from '../push/usePush';
import { formatDay, formatTime } from '../format/date';
import { parseRupeesToPaise } from '../format/money';

const KIND_LABEL: Record<string, string> = {
  debit: 'Payment to someone',
  credit: 'Money received',
  card: 'Card payment',
  atm: 'Cash withdrawal',
  autopay: 'AutoPay',
  reversal: 'Reversal',
};

const field =
  'h-10 w-full rounded-control border border-input-border bg-surface px-3 text-[14px] text-ink placeholder:text-ink-3';

/** Keys 1, 2 and 3 pick the first payment's guesses, unless you are typing somewhere. */
function useGuessShortcuts(inbox: CaptureInbox | undefined) {
  const tag = useTagPayment();
  const first = inbox?.prompts[0];
  useEffect(() => {
    if (!first) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT'))
        return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const i = Number(e.key) - 1;
      const g = first.guesses[i];
      if (!Number.isInteger(i) || !g) return;
      e.preventDefault();
      void tag(first, {
        label: g.label,
        name: g.name,
        rank: i + 1,
        credit: first.event.direction === 'credit',
      });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [first, tag]);
}

function SimulatorPanel({ inbox }: { inbox: CaptureInbox }) {
  const writes = useCaptureWrites();
  const toast = useToast();
  const [bank, setBank] = useState(inbox.banks[0]?.code ?? 'hdfc');
  const [kind, setKind] = useState('debit');
  const [amount, setAmount] = useState('');
  const [who, setWho] = useState('');
  const [vpa, setVpa] = useState('');
  const [last, setLast] = useState<CaptureSimulated | null>(null);
  const paise = parseRupeesToPaise(amount);
  const needsName = kind !== 'atm' && kind !== 'reversal';
  const ready = paise !== null && (!needsName || who.trim() !== '' || vpa.trim() !== '');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ready || paise === null) return;
    writes.simulate.mutate(
      {
        bank: bank as 'hdfc',
        kind: kind as 'debit',
        amount_paise: paise,
        counterparty: who.trim(),
        ...(vpa.trim() ? { vpa: vpa.trim() } : {}),
      },
      {
        onSuccess: (out) => setLast(out),
        onError: (err) =>
          toast({
            message: err instanceof ApiError ? err.message : 'Could not simulate that.',
            tone: 'negative',
          }),
      },
    );
  };

  return (
    <Card className="p-5" labelledBy="sim-title">
      <div className="flex items-center justify-between gap-2">
        <h2 id="sim-title" className="serif-light text-[22px]">
          Try a payment
        </h2>
        <Badge tone="agent">Simulated</Badge>
      </div>
      <p className="mt-1 text-small text-ink-3">
        Sends a pretend bank alert through the same steps a real one takes. Nothing here is a real
        payment, and every one is marked as simulated.
      </p>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="label-mono text-ink-3">Bank</span>
            <select className={field} value={bank} onChange={(e) => setBank(e.target.value)}>
              {inbox.banks.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label-mono text-ink-3">What kind</span>
            <select className={field} value={kind} onChange={(e) => setKind(e.target.value)}>
              {inbox.kinds.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k] ?? k}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="label-mono text-ink-3">Amount (rupees)</span>
          <input
            className={field}
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        {needsName ? (
          <>
            <label className="flex flex-col gap-1.5">
              <span className="label-mono text-ink-3">{kind === 'credit' ? 'From' : 'To'}</span>
              <input
                className={field}
                value={who}
                placeholder="A name or a shop"
                onChange={(e) => setWho(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="label-mono text-ink-3">UPI handle (optional)</span>
              <input className={field} value={vpa} onChange={(e) => setVpa(e.target.value)} />
            </label>
          </>
        ) : null}
        <Button
          variant="primary"
          type="submit"
          icon={<Lightning size={14} />}
          busy={writes.simulate.isPending}
          disabled={!ready}
        >
          Send the alert
        </Button>
      </form>
      {last ? (
        <figure className="mt-4 rounded-control border border-hairline bg-surface-sunken/80 p-3">
          <figcaption className="label-mono text-ink-3">
            What the phone would have sent (made up)
          </figcaption>
          <blockquote className="mt-1.5 break-words font-mono text-[12px] leading-relaxed text-ink-2">
            {last.sample_text}
          </blockquote>
        </figure>
      ) : null}
    </Card>
  );
}

function BridgeCard() {
  const health = useBridgeHealth();
  if (!health.data) return null;
  const h = health.data;
  return (
    <Card className="p-5" labelledBy="bridge-title">
      <div className="flex items-center justify-between gap-2">
        <h2 id="bridge-title" className="serif-light text-[22px]">
          Phone bridge
        </h2>
        <Badge tone={h.any_enabled && h.secret_configured ? 'positive' : 'attention'}>
          {h.any_enabled && h.secret_configured ? 'Listening' : 'Not set up'}
        </Badge>
      </div>
      {!h.secret_configured || !h.any_enabled ? (
        <p className="mt-2 text-small text-ink-2">
          Real bank alerts are not coming in yet. In a terminal run{' '}
          <code className="rounded bg-surface-sunken px-1">copilot capture bridge-setup</code>; it
          prints the exact rule to create on your phone and the secret to use.
        </p>
      ) : null}
      <ul className="mt-3 flex flex-col gap-2">
        {h.banks.map((b) => (
          <li key={b.bank} className="flex flex-wrap items-center justify-between gap-2 text-small">
            <span className={b.enabled ? 'text-ink' : 'text-ink-3'}>{b.name}</span>
            <span className="flex items-center gap-2 text-ink-3">
              {b.enabled ? (
                b.last_received_at ? (
                  <>
                    Last alert {formatDay(b.last_received_at)}, {formatTime(b.last_received_at)}
                  </>
                ) : (
                  'No alerts yet'
                )
              ) : (
                'Switched off'
              )}
              {b.drifting ? <Badge tone="attention">Wording changed</Badge> : null}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function NotificationsCard() {
  const push = usePush();
  const status = usePushStatus();
  const devices = status.data?.devices ?? [];
  const note: Record<string, string> = {
    unsupported: 'This browser cannot show notifications.',
    insecure:
      'Notifications need a secure address. Open FinCo at localhost (on a phone over USB: adb reverse).',
    denied: 'Notifications are blocked for this site in your browser settings.',
  };
  return (
    <Card className="p-5" labelledBy="notify-title">
      <div className="flex items-center justify-between gap-2">
        <h2 id="notify-title" className="serif-light text-[22px]">
          Notifications
        </h2>
        <Badge tone={push.state === 'on' ? 'positive' : 'neutral'}>
          {push.state === 'on' ? 'On here' : 'Off here'}
        </Badge>
      </div>
      <p className="mt-2 text-small text-ink-2">
        A payment you need to tag can reach you on this device even when FinCo is closed.
        {status.data?.lock_screen_safe
          ? ' The notification says only that a payment needs tagging; the amount stays in the app.'
          : ''}
      </p>
      {note[push.state] ? (
        <p className="mt-2 text-small text-attention">{note[push.state]}</p>
      ) : null}
      {push.error ? <p className="mt-2 text-small text-negative">{push.error}</p> : null}
      {push.state === 'off' || push.state === 'on' ? (
        <div className="mt-3">
          {push.state === 'off' ? (
            <Button variant="primary" busy={push.busy} onClick={() => void push.enable()}>
              Notify me on this device
            </Button>
          ) : (
            <Button variant="text" busy={push.busy} onClick={() => void push.disable()}>
              Turn off on this device
            </Button>
          )}
        </div>
      ) : null}
      {devices.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-1 text-small text-ink-3">
          {devices.map((d) => (
            <li key={d.id}>{d.label}</li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

export function CaptureScreen() {
  const inbox = useCaptureInbox();
  const [params] = useSearchParams();
  const focusPrompt = params.get('prompt');
  useGuessShortcuts(inbox.data);

  return (
    <Page
      title={
        <>
          Tag payments <em>as they happen</em>
        </>
      }
      lead="When a payment is not obvious, you are asked once, while you still remember. One tap, and it is remembered where that makes sense."
    >
      {inbox.isPending ? (
        <Card className="p-6">
          <SkeletonBlock lines={4} />
        </Card>
      ) : inbox.error ? (
        <ErrorState
          code={inbox.error instanceof ApiError ? inbox.error.code : 'UNKNOWN'}
          message={inbox.error.message}
          onRetry={() => void inbox.refetch()}
        />
      ) : (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <section aria-labelledby="inbox-title">
            <div className="mb-4 flex items-baseline justify-between">
              <h2 id="inbox-title" className="serif-light text-[26px]">
                Waiting for you
              </h2>
              {inbox.data.pending_count > 0 ? (
                <span className="text-small text-ink-3">
                  Press{' '}
                  {inbox.data.prompts[0]?.guesses.map((g, n) => (
                    <kbd key={g.label} className="mr-1 rounded bg-surface-sunken px-1">
                      {n + 1}
                    </kbd>
                  ))}
                  to pick for the first one
                </span>
              ) : null}
            </div>
            {inbox.data.prompts.length === 0 ? (
              <Card className="p-8">
                <EmptyState message="All caught up. When a payment needs a word from you it will appear here and as a prompt wherever you are in the app." />
              </Card>
            ) : (
              <ul className="flex flex-col gap-4">
                <AnimatePresence initial={false}>
                  {inbox.data.prompts.map((p, i) => (
                    <PaymentPrompt
                      key={p.prompt_id}
                      prompt={p}
                      creditKinds={inbox.data.credit_kinds}
                      shortcuts={i === 0}
                      openSheet={p.prompt_id === focusPrompt}
                    />
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </section>
          <aside aria-label="Simulator" className="flex flex-col gap-5">
            <NotificationsCard />
            <BridgeCard />
            <SimulatorPanel inbox={inbox.data} />
          </aside>
        </div>
      )}
    </Page>
  );
}
