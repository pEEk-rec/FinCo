import { AnimatePresence, motion } from 'motion/react';
import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router';

import { openCaptureStream, type AutoTagged, type StreamEvent } from '../../api/captureStream';
import type { PromptView } from '../../api/client';
import { useCaptureInbox } from '../../api/hooks';
import { displayName } from '../../format/name';
import { formatINR } from '../../format/money';
import { PaymentPrompt, useTagPayment } from './PaymentPrompt';

const LATER_KEY = 'finco.capture.later';
const CHIP_MS = 7000;

function readLater(): Set<string> {
  try {
    return new Set(JSON.parse(window.sessionStorage.getItem(LATER_KEY) ?? '[]') as string[]);
  } catch {
    return new Set();
  }
}

function writeLater(ids: Set<string>): void {
  try {
    window.sessionStorage.setItem(LATER_KEY, JSON.stringify([...ids]));
  } catch {
    // session storage unavailable: "later" is simply forgotten on reload
  }
}

/**
 * The prompt that appears on any page when a payment needs a word from you.
 * It never blocks: "Later" (or Esc) sends it to the inbox and it does not come back as a prompt.
 * Several waiting payments collapse into a count. Hidden on the Tag payments page, which
 * already lists them.
 */
export function CaptureOverlay() {
  const location = useLocation();
  // the pages that already list what is waiting do not need a second copy floating over them
  const onInbox = location.pathname.startsWith('/review');
  const inbox = useCaptureInbox();
  const tag = useTagPayment();
  const [live, setLive] = useState<PromptView[]>([]);
  const [chips, setChips] = useState<AutoTagged[]>([]);
  const [laterIds, setLaterIds] = useState<Set<string>>(readLater);

  useEffect(() => {
    const handle = (e: StreamEvent) => {
      if (e.type === 'prompt') {
        setLive((cur) =>
          cur.some((p) => p.prompt_id === e.prompt.prompt_id) ? cur : [...cur, e.prompt],
        );
      } else if (e.type === 'resolved') {
        setLive((cur) => cur.filter((p) => p.prompt_id !== e.promptId));
      } else {
        setChips((cur) =>
          cur.some((c) => c.prompt_id === e.chip.prompt_id) ? cur : [...cur, e.chip],
        );
        window.setTimeout(
          () => setChips((cur) => cur.filter((c) => c.prompt_id !== e.chip.prompt_id)),
          CHIP_MS,
        );
      }
    };
    return openCaptureStream(handle, () => undefined);
  }, []);

  const visible = live.filter((p) => !laterIds.has(p.prompt_id));
  const current = visible[visible.length - 1];

  const dismiss = useCallback((p: PromptView) => {
    setLaterIds((cur) => {
      const next = new Set(cur).add(p.prompt_id);
      writeLater(next);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!current || onInbox) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) return;
      if (el?.closest('[role="dialog"]')) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'Escape') {
        dismiss(current);
        return;
      }
      const i = Number(e.key) - 1;
      const g = current.guesses[i];
      if (!Number.isInteger(i) || !g) return;
      e.preventDefault();
      void tag(current, {
        label: g.label,
        name: g.name,
        rank: i + 1,
        credit: current.event.direction === 'credit',
      });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [current, dismiss, onInbox, tag]);

  if (onInbox) return null;
  const waiting = inbox.data?.pending_count ?? 0;

  return (
    <div className="no-print pointer-events-none fixed inset-x-3 bottom-[calc(5.25rem+env(safe-area-inset-bottom))] z-50 flex max-h-[calc(100dvh-9rem)] flex-col-reverse items-stretch gap-3 overflow-y-auto lg:inset-x-auto lg:bottom-auto lg:right-4 lg:top-20 lg:w-[26rem] lg:flex-col lg:items-end">
      <div role="status" aria-live="polite" className="sr-only">
        {current
          ? `${current.event.direction === 'credit' ? 'Received' : 'Paid'} ${formatINR(current.event.amount_paise, { paise: 'auto' })} ${current.event.direction === 'credit' ? 'from' : 'to'} ${displayName(current.event.display_name)}. What was it?`
          : ''}
      </div>
      <AnimatePresence initial={false}>
        {current ? (
          <motion.div
            key={current.prompt_id}
            className="pointer-events-auto w-full"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12 }}
          >
            <ul className="m-0 p-0">
              <PaymentPrompt
                prompt={current}
                creditKinds={inbox.data?.credit_kinds ?? []}
                shortcuts
                onLater={() => dismiss(current)}
                onDone={() =>
                  setLive((cur) => cur.filter((p) => p.prompt_id !== current.prompt_id))
                }
              />
            </ul>
            {visible.length > 1 || waiting > 1 ? (
              <Link
                to="/review"
                className="mt-2 block text-right text-small text-brand underline-offset-2 hover:underline"
              >
                {Math.max(visible.length, waiting)} payments to tag
              </Link>
            ) : null}
          </motion.div>
        ) : null}
        {chips.map((c) => (
          <motion.div
            key={c.prompt_id}
            className="pointer-events-auto glass rounded-chip px-4 py-2 text-small"
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
          >
            Tagged {c.name} · {displayName(c.event.display_name)}{' '}
            <Link to="/review" className="text-brand underline-offset-2 hover:underline">
              Change
            </Link>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
