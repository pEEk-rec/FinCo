import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';

import { ApiError, type ReviewItem } from '../api/client';
import { useCategories, useRecategorize, useReviewQueue, useUndo } from '../api/hooks';
import { Badge, CategoryPill } from '../components/Badge';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { cx } from '../components/cx';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { Toggle } from '../components/Toggle';
import { copy } from '../copy/en';
import { formatDay } from '../format/date';
import { formatINR } from '../format/money';

const T = copy.review;

export function ReviewScreen() {
  const queue = useReviewQueue();
  const categories = useCategories();
  const recategorize = useRecategorize();
  const undo = useUndo();
  const toast = useToast();

  const [skipped, setSkipped] = useState<string[]>([]);
  const [done, setDone] = useState<{ id: string; event: string }[]>([]);
  const [remember, setRemember] = useState(true);
  const [cursor, setCursor] = useState(0);
  const [initialTotal, setInitialTotal] = useState<number | null>(null);

  const items: ReviewItem[] = useMemo(() => {
    const all = queue.data?.items ?? [];
    const open = all.filter((i) => !skipped.includes(i.transaction.id));
    return [...open, ...all.filter((i) => skipped.includes(i.transaction.id))];
  }, [queue.data, skipped]);

  // Remember how long the queue was when the screen opened (adjusting state during render).
  if (queue.data && initialTotal === null) setInitialTotal(queue.data.total);
  const current = items[Math.min(cursor, Math.max(items.length - 1, 0))];
  const names = useMemo(
    () => new Map((categories.data ?? []).map((c) => [c.id, c.name])),
    [categories.data],
  );

  const confirm = async (categoryId: string) => {
    if (!current) return;
    const id = current.transaction.id;
    try {
      const out = await recategorize.mutateAsync({ id, categoryId, remember });
      setDone((d) => [...d, { id, event: out.audit_event_id }]);
      setCursor(0);
      toast({
        message: copy.transactions.corrected(names.get(categoryId) ?? categoryId),
        onUndo: async () => {
          await undo.mutateAsync(out.audit_event_id);
          setDone((d) => d.filter((x) => x.id !== id));
        },
      });
    } catch (error) {
      toast({ message: (error as Error).message, tone: 'negative' });
    }
  };

  const undoLast = async () => {
    const last = done[done.length - 1];
    if (!last) return;
    try {
      await undo.mutateAsync(last.event);
      setDone((d) => d.slice(0, -1));
      toast({ message: copy.transactions.undone });
    } catch (error) {
      toast({ message: (error as Error).message, tone: 'negative' });
    }
  };

  // Keyboard flow: 1-5 pick, Enter confirms the highlighted pick, S skips, U undoes, J/K move.
  const [pick, setPick] = useState<{ id: string | undefined; index: number }>({
    id: undefined,
    index: 0,
  });
  const picked = pick.id === current?.transaction.id ? pick.index : 0;
  const setPicked = (index: number) => setPick({ id: current?.transaction.id, index });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        target.closest('input, textarea, select, [role="dialog"]') ||
        event.metaKey ||
        event.ctrlKey
      )
        return;
      const key = event.key.toLowerCase();
      const suggestions = current?.suggestions ?? [];
      if (/^[1-5]$/.test(key) && suggestions[Number(key) - 1]) {
        event.preventDefault();
        setPicked(Number(key) - 1);
      } else if (key === 'enter' && suggestions[picked] && !target.closest('button')) {
        event.preventDefault();
        void confirm(suggestions[picked]!.category_id);
      } else if (key === 's' && current) {
        setSkipped((s) => [...s, current.transaction.id]);
        setCursor(0);
      } else if (key === 'u') {
        void undoLast();
      } else if (key === 'j') {
        setCursor((c) => Math.min(c + 1, items.length - 1));
      } else if (key === 'k') {
        setCursor((c) => Math.max(c - 1, 0));
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const total = initialTotal ?? 0;
  const doneCount = Math.max(0, total - (queue.data?.total ?? 0));

  return (
    <Page title={T.title} lead={T.subtitle}>
      {queue.isPending ? (
        <Card className="p-6">
          <SkeletonBlock lines={6} />
        </Card>
      ) : queue.error ? (
        <Card className="p-6">
          <ErrorState
            code={queue.error instanceof ApiError ? queue.error.code : 'UNKNOWN'}
            message={queue.error.message}
            onRetry={() => void queue.refetch()}
          />
        </Card>
      ) : !current ? (
        <Card className="p-8">
          <EmptyState
            message={done.length ? `${T.done} ${T.doneSummary(String(done.length))}` : T.done}
            action={
              <Link to="/">
                <Button>{copy.nav.dashboard}</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <Card as="article" labelledBy="rv-merchant" className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-hairline px-6 py-3">
              <span className="label-mono text-ink-2">
                {T.progress(String(doneCount + 1), String(Math.max(total, doneCount + 1)))}
              </span>
              <div className="h-1 w-40 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                <div
                  className="h-full bg-ink transition-[width] duration-slow ease-out-soft"
                  style={{ width: `${total ? (doneCount / total) * 100 : 0}%` }}
                />
              </div>
            </div>
            <div className="px-6 pt-7 pb-6">
              <p className="text-small text-ink-3">{formatDay(current.transaction.occurred_at)}</p>
              <h2
                id="rv-merchant"
                className="serif-light mt-1 text-[34px] leading-tight capitalize"
              >
                {current.transaction.merchant}
              </h2>
              <p className="tabular mt-2 text-[28px] font-light">
                {formatINR(Math.abs(current.transaction.amount_paise))}
              </p>
              <p className="mt-1 break-words text-small text-ink-3">
                {current.transaction.merchant_raw}
              </p>
              <p className="mt-5 text-small text-ink-2">
                <span className="label-mono mr-2 text-ink-3">{T.why}</span>
                {current.why}
              </p>
            </div>

            <div className="border-t border-hairline px-6 py-5">
              <h3 className="label-mono mb-3 text-ink-2">{T.suggestions}</h3>
              <ul className="flex flex-wrap gap-2">
                {current.suggestions.map((s, index) => (
                  <li key={s.category_id}>
                    <button
                      type="button"
                      onClick={() => setPicked(index)}
                      onDoubleClick={() => void confirm(s.category_id)}
                      aria-pressed={picked === index}
                      className={cx(
                        'flex h-10 items-center gap-2.5 rounded-control border px-3 text-[14px] transition-colors duration-fast',
                        picked === index
                          ? 'border-ink bg-surface-selected'
                          : 'border-hairline-strong bg-surface hover:bg-surface-hover',
                      )}
                    >
                      <kbd className="tabular flex size-5 items-center justify-center rounded-[4px] bg-surface-sunken font-mono text-[11px] text-ink-2">
                        {index + 1}
                      </kbd>
                      {s.name}
                      {s.reason === 'ai_suggestion' ? <Badge tone="agent">AI</Badge> : null}
                    </button>
                  </li>
                ))}
              </ul>
              {current.suggestions.length === 0 ? (
                <p className="text-small text-ink-3">{T.noSuggestions}</p>
              ) : null}
              <div className="mt-6 max-w-sm">
                <Toggle
                  checked={remember}
                  onCheckedChange={setRemember}
                  label={T.remember}
                  hint={copy.transactions.rememberHint}
                />
              </div>
              <div className="mt-6 flex items-center gap-3">
                <Button
                  variant="primary"
                  disabled={!current.suggestions[picked]}
                  busy={recategorize.isPending}
                  onClick={() =>
                    current.suggestions[picked] &&
                    void confirm(current.suggestions[picked].category_id)
                  }
                >
                  {T.confirm}
                </Button>
                <Button
                  variant="text"
                  onClick={() => {
                    setSkipped((s) => [...s, current.transaction.id]);
                    setCursor(0);
                  }}
                >
                  {T.skip}
                </Button>
              </div>
              <p className="mt-5 text-small text-ink-3">{T.keys}</p>
            </div>
          </Card>

          <Card as="aside" labelledBy="rv-similar">
            <div className="border-b border-hairline px-5 py-3">
              <h3 id="rv-similar" className="label-mono text-ink-2">
                {T.similar}
              </h3>
            </div>
            {current.similar.length === 0 ? (
              <p className="p-5 text-small text-ink-3">{T.noSimilar}</p>
            ) : (
              <ul>
                {current.similar.map((s) => (
                  <li
                    key={s.id}
                    className="flex flex-col gap-1.5 border-b border-hairline px-5 py-3 last:border-b-0"
                  >
                    <span className="flex justify-between text-small text-ink-3">
                      {formatDay(s.occurred_at)}
                      <span className="tabular text-ink">
                        {formatINR(s.amount_paise, { paise: 'never' })}
                      </span>
                    </span>
                    <CategoryPill categoryId={s.category_id} name={s.category_name} />
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
