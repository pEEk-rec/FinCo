import { CaretLeft, CaretRight } from '@phosphor-icons/react';
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';

import { useSession } from '../api/hooks';
import { cx } from '../components/cx';
import { formatPeriod } from '../format/date';

/**
 * One month for the whole app. Overview, Transactions and Plan all read it, so changing the month
 * once changes every screen. It survives a reload (session storage), and a link can set it with
 * `?period=YYYY-MM`.
 */

const KEY = 'finco.month';
const HOW_MANY = 3; // the current month and the two before it

export function shiftPeriod(period: string, by: number): string {
  const [y, m] = period.split('-').map(Number) as [number, number];
  const index = y * 12 + (m - 1) + by;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}`;
}

interface MonthState {
  /** The chosen month, `YYYY-MM`; undefined until the session has loaded. */
  month: string | undefined;
  /** The months you can move between, oldest first. */
  months: string[];
  /** The month that is still running (the session's current month). */
  current: string | undefined;
  setMonth: (period: string) => void;
}

const MonthContext = createContext<MonthState | null>(null);

function readStored(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function MonthProvider({ children }: { children: ReactNode }) {
  const current = useSession().data?.period;
  const [params] = useSearchParams();
  const linked = params.get('period');
  const [chosen, setChosen] = useState<string | null>(readStored);

  const months = useMemo(
    () =>
      current
        ? Array.from({ length: HOW_MANY }, (_, i) => shiftPeriod(current, i - HOW_MANY + 1))
        : [],
    [current],
  );

  // A link that names a month (?period=2024-02) moves the whole app to it, once per new link
  // (adjusting state during render, so there is no extra render pass).
  const [followed, setFollowed] = useState<string | null>(null);
  if (linked && linked !== followed && months.includes(linked)) {
    setFollowed(linked);
    setChosen(linked);
  }

  const month = chosen && months.includes(chosen) ? chosen : current;
  const value = useMemo<MonthState>(
    () => ({
      month,
      months,
      current,
      setMonth: (period) => {
        setChosen(period);
        try {
          sessionStorage.setItem(KEY, period);
        } catch {
          /* private mode: the month just is not remembered */
        }
      },
    }),
    [month, months, current],
  );
  return <MonthContext.Provider value={value}>{children}</MonthContext.Provider>;
}

export function useMonth(): MonthState {
  const value = useContext(MonthContext);
  if (!value) throw new Error('useMonth needs a MonthProvider');
  return value;
}

/** ‹ March 2024 › — the one month control, in the top bar. */
export function MonthSwitcher({ compact = false }: { compact?: boolean }) {
  const { month, months, current, setMonth } = useMonth();
  if (!month) return <span className="h-10 w-48" aria-hidden />;
  const at = months.indexOf(month);
  // `month` is always one of `months`, so a missing neighbour means the end of the range.
  const prev = months[at - 1];
  const next = months[at + 1];
  const arrow =
    'flex size-8 items-center justify-center rounded-full text-ink transition-colors duration-fast hover:bg-surface-sunken disabled:text-ink-3/50 disabled:hover:bg-transparent';
  return (
    <div
      role="group"
      aria-label="Month"
      className="flex items-center gap-1 rounded-full border border-hairline bg-surface p-1 shadow-[0_1px_2px_rgba(31,26,23,0.04)]"
    >
      <button
        type="button"
        className={arrow}
        disabled={!prev}
        onClick={() => prev && setMonth(prev)}
        aria-label="Previous month"
      >
        <CaretLeft size={15} weight="bold" aria-hidden />
      </button>
      <span
        aria-live="polite"
        className={cx(
          'tabular text-center text-[14px] font-semibold text-ink',
          compact ? 'min-w-[7.5rem]' : 'min-w-[9.5rem]',
        )}
      >
        {formatPeriod(month)}
        {!compact && month !== current ? (
          <span className="ml-1.5 text-[12px] font-medium text-ink-3">closed</span>
        ) : null}
      </span>
      <button
        type="button"
        className={arrow}
        disabled={!next}
        onClick={() => next && setMonth(next)}
        aria-label="Next month"
      >
        <CaretRight size={15} weight="bold" aria-hidden />
      </button>
    </div>
  );
}
