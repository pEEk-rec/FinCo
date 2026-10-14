import { MagnifyingGlass } from '@phosphor-icons/react';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';

import { ApiError, type HistoryEntry, type TransactionRow } from '../api/client';
import {
  useCategories,
  useRecategorize,
  useTransaction,
  useTransactions,
  useUndo,
} from '../api/hooks';
import { Badge, CategoryPill, Chip, SourceBadge } from '../components/Badge';
import { Button } from '../components/Button';
import { CategoryMenu } from '../components/CategoryMenu';
import { cx } from '../components/cx';
import { DetailPanel } from '../components/DetailPanel';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { useToast } from '../components/Toast';
import { Toggle } from '../components/Toggle';
import { copy } from '../copy/en';
import { formatDay, formatDayHeader, formatTime, istDayKey } from '../format/date';
import { formatINR } from '../format/money';
import { NumberTicker } from '../motion/NumberTicker';

const T = copy.transactions;
const PAGE = 60;
const PERIODS = ['2024-03', '2024-02', '2024-01'];

function periodLabel(period: string): string {
  const names = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return `${names[Number(period.slice(5)) - 1]} ${period.slice(0, 4)}`;
}

function Row({
  tx,
  selected,
  onSelect,
}: {
  tx: TransactionRow;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        data-testid="tx-row"
        onClick={onSelect}
        aria-current={selected}
        className={cx(
          'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 border-l-2 px-5 py-2.5 text-left transition-colors duration-fast sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]',
          selected ? 'border-ink bg-surface-selected' : 'border-transparent hover:bg-surface-hover',
        )}
      >
        <span className="min-w-0">
          <span className="block truncate text-[14px] capitalize">{tx.merchant}</span>
          <span className="block truncate text-small text-ink-3">
            {tx.account_name} · {formatTime(tx.occurred_at)}
          </span>
        </span>
        <span className="hidden sm:block">
          <CategoryPill categoryId={tx.category_id} name={tx.category_name} />
        </span>
        <span className="hidden sm:block">
          {tx.needs_review ? (
            <Badge tone="attention">{T.needsReview}</Badge>
          ) : (
            <SourceBadge source={tx.category_source} confidence={tx.category_confidence} />
          )}
        </span>
        <span
          className={cx(
            'tabular text-right text-cell',
            tx.direction === 'credit' ? 'font-medium text-positive' : 'text-ink',
          )}
        >
          {formatINR(Math.abs(tx.amount_paise), { sign: 'never' })}
          {tx.direction === 'credit' ? <span className="sr-only"> credit</span> : null}
        </span>
      </button>
    </li>
  );
}

function HistoryItem({
  entry,
  names,
  onUndo,
  busy,
}: {
  entry: HistoryEntry;
  names: Map<string, string>;
  onUndo: (id: string) => void;
  busy: boolean;
}) {
  const from = entry.before_category_id
    ? (names.get(entry.before_category_id) ?? entry.before_category_id)
    : copy.common.uncategorised;
  const to = entry.after_category_id
    ? (names.get(entry.after_category_id) ?? entry.after_category_id)
    : copy.common.uncategorised;
  return (
    <li className="flex items-start justify-between gap-3 border-b border-hairline py-3 last:border-b-0">
      <div className="min-w-0">
        <p className="text-[14px]">
          {entry.event_type === 'undo' ? T.undone : T.changedCategory(from, to)}
        </p>
        <p className="text-small text-ink-3">
          {formatDay(entry.occurred_at)}, {formatTime(entry.occurred_at)} · {entry.actor}
        </p>
      </div>
      {entry.undoable ? (
        <Button
          size="sm"
          variant="text"
          disabled={busy}
          onClick={() => onUndo(entry.audit_event_id)}
        >
          {copy.common.undo}
        </Button>
      ) : null}
    </li>
  );
}

function Detail({ id }: { id: string }) {
  const detail = useTransaction(id);
  const categories = useCategories();
  const recategorize = useRecategorize();
  const undo = useUndo();
  const toast = useToast();
  const [remember, setRemember] = useState(false);
  const names = useMemo(
    () => new Map((categories.data ?? []).map((c) => [c.id, c.name])),
    [categories.data],
  );

  if (detail.isPending) return <SkeletonBlock className="p-6" lines={6} />;
  if (detail.error)
    return (
      <div className="p-6">
        <ErrorState
          code={detail.error instanceof ApiError ? detail.error.code : 'UNKNOWN'}
          message={detail.error.message}
          onRetry={() => void detail.refetch()}
        />
      </div>
    );

  const tx = detail.data.transaction;

  const runUndo = async (auditEventId: string) => {
    try {
      await undo.mutateAsync(auditEventId);
      toast({ message: T.undone });
    } catch (error) {
      // A refused undo is a normal outcome: say why, plainly.
      toast({
        message:
          error instanceof ApiError && error.code === 'STALE_DATA'
            ? T.undoBlocked
            : (error as Error).message,
        tone: 'negative',
      });
    }
  };

  const change = async (categoryId: string) => {
    if (categoryId === tx.category_id) return;
    try {
      const out = await recategorize.mutateAsync({ id: tx.id, categoryId, remember });
      toast({
        message: T.corrected(names.get(categoryId) ?? categoryId),
        onUndo: () => runUndo(out.audit_event_id),
      });
    } catch (error) {
      toast({ message: (error as Error).message, tone: 'negative' });
    }
  };

  return (
    <div className="flex flex-col">
      <div className="border-b border-hairline px-6 py-5">
        <p className="text-small text-ink-3">{formatDay(tx.occurred_at)}</p>
        <h2 className="serif-light mt-1 text-[26px] leading-tight capitalize">{tx.merchant}</h2>
        <NumberTicker
          value={formatINR(Math.abs(tx.amount_paise), { sign: 'never' })}
          className={cx(
            'tabular mt-2 text-[28px] font-light',
            tx.direction === 'credit' && 'text-positive',
          )}
        />
        <p className="mt-1 text-small text-ink-3">{tx.account_name}</p>
      </div>

      <div className="flex flex-col gap-5 px-6 py-5">
        <div className="flex items-center justify-between gap-4">
          <span className="text-small text-ink-3">{T.category}</span>
          <div className="flex items-center gap-2">
            <CategoryMenu
              categories={categories.data ?? []}
              value={tx.category_id ?? null}
              valueName={tx.category_name ?? null}
              onChange={(id) => void change(id)}
              disabled={recategorize.isPending}
              searchLabel={T.search}
            />
          </div>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-small text-ink-3">{T.source}</span>
          <div>
            <SourceBadge source={tx.category_source} confidence={tx.category_confidence} />
          </div>
        </div>
        <Toggle
          checked={remember}
          onCheckedChange={setRemember}
          label={T.remember}
          hint={T.rememberHint}
        />
        <div className="flex flex-col gap-2">
          {tx.is_duplicate ? <Badge tone="attention">{T.duplicate}</Badge> : null}
          {tx.is_transfer ? <Badge>{T.transfer}</Badge> : null}
          {detail.data.recurring ? <Badge>{T.recurring}</Badge> : null}
        </div>
        <div>
          <span className="text-small text-ink-3">{T.description}</span>
          <div className="mt-1 break-words text-[14px] text-ink-2">{tx.merchant_raw}</div>
        </div>
      </div>

      <section aria-labelledby="hist" className="border-t border-hairline px-6 py-5">
        <h3 id="hist" className="label-mono mb-2 text-ink-2">
          {T.history}
        </h3>
        {detail.data.history.length === 0 ? (
          <p className="text-small text-ink-3">{T.noHistory}</p>
        ) : (
          <ul>
            {detail.data.history.map((entry) => (
              <HistoryItem
                key={entry.audit_event_id}
                entry={entry}
                names={names}
                busy={undo.isPending}
                onUndo={(eventId) => void runUndo(eventId)}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export function TransactionsScreen() {
  const [params, setParams] = useSearchParams();
  const period = params.get('period') ?? '';
  const category = params.get('category') ?? '';
  const reviewOnly = params.get('review') === '1';
  const selected = params.get('tx');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(PAGE);
  const categories = useCategories();

  const filters = {
    period: period || undefined,
    category_id: category && category !== 'none' ? category : undefined,
    uncategorised: category === 'none' || undefined,
    needs_review: reviewOnly || undefined,
    q: query.trim() || undefined,
    offset: 0,
    limit,
  };
  const list = useTransactions(filters);

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setLimit(PAGE);
  };

  const groups = useMemo(() => {
    const byDay = new Map<string, TransactionRow[]>();
    for (const tx of list.data?.items ?? []) {
      const key = istDayKey(tx.occurred_at);
      byDay.set(key, [...(byDay.get(key) ?? []), tx]);
    }
    return [...byDay.entries()];
  }, [list.data]);

  return (
    <div className="grid h-[calc(100vh-3.5rem)] min-h-[32rem] grid-cols-1 lg:h-screen lg:grid-cols-[minmax(0,1fr)_26rem]">
      <section aria-labelledby="tx-title" className="flex min-h-0 min-w-0 flex-col">
        <div className="border-b border-hairline px-5 py-4 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 id="tx-title" className="serif-light text-[28px] leading-none">
              {T.title}
            </h1>
            <label className="flex h-9 w-full max-w-xs items-center gap-2 rounded-control border border-input-border bg-surface px-3 sm:w-64">
              <MagnifyingGlass size={15} aria-hidden className="text-ink-3" />
              <input
                aria-label={T.search}
                placeholder={T.search}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full bg-transparent text-small outline-none placeholder:text-ink-3"
              />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Chip selected={period === ''} onClick={() => set('period', null)}>
              {T.allTime}
            </Chip>
            {PERIODS.map((p) => (
              <Chip key={p} selected={period === p} onClick={() => set('period', p)}>
                {periodLabel(p)}
              </Chip>
            ))}
            <span aria-hidden className="mx-1 h-4 w-px bg-hairline" />
            <Chip selected={reviewOnly} onClick={() => set('review', reviewOnly ? null : '1')}>
              {T.needsReview}
            </Chip>
            <label className="ml-1">
              <span className="sr-only">{T.category}</span>
              <select
                value={category}
                onChange={(e) => set('category', e.target.value || null)}
                className="h-7 rounded-chip border border-hairline-strong bg-surface px-3 text-small text-ink-2"
              >
                <option value="">{T.allCategories}</option>
                <option value="none">{copy.common.uncategorised}</option>
                {(categories.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {list.isPending ? (
            <SkeletonBlock className="p-6" lines={8} />
          ) : list.error ? (
            <div className="p-6">
              <ErrorState
                code={list.error instanceof ApiError ? list.error.code : 'UNKNOWN'}
                message={list.error.message}
                onRetry={() => void list.refetch()}
              />
            </div>
          ) : groups.length === 0 ? (
            <div className="p-6">
              <EmptyState
                message={period || category || reviewOnly || query ? T.empty : T.emptyAll}
              />
            </div>
          ) : (
            <>
              {groups.map(([day, rows]) => (
                <div key={day}>
                  <h2 className="sticky top-0 z-10 border-b border-hairline bg-canvas px-5 py-2 text-small font-medium text-ink-2 sm:px-6">
                    {formatDayHeader(rows[0]!.occurred_at)}
                  </h2>
                  <ul className="bg-surface">
                    {rows.map((tx) => (
                      <Row
                        key={tx.id}
                        tx={tx}
                        selected={tx.id === selected}
                        onSelect={() => set('tx', tx.id)}
                      />
                    ))}
                  </ul>
                </div>
              ))}
              {list.data && list.data.items.length < list.data.total ? (
                <div className="p-5">
                  <Button onClick={() => setLimit((n) => n + PAGE)}>{T.loadMore}</Button>
                </div>
              ) : null}
            </>
          )}
        </div>
      </section>

      <div className="hidden min-h-0 lg:block">
        <DetailPanel
          openKey={selected}
          title={T.title}
          onClose={() => set('tx', null)}
          empty={<p className="max-w-[16rem] text-small text-ink-3">{T.detailEmpty}</p>}
        >
          {selected ? <Detail id={selected} /> : null}
        </DetailPanel>
      </div>

      {selected ? (
        <div className="fixed inset-0 z-40 overflow-y-auto bg-surface lg:hidden">
          <div className="flex h-12 items-center border-b border-hairline px-4">
            <Button variant="text" size="sm" onClick={() => set('tx', null)}>
              {copy.common.close}
            </Button>
          </div>
          <Detail id={selected} />
        </div>
      ) : null}
    </div>
  );
}
