import { motion, useReducedMotion } from 'motion/react';

import { CategoryPill } from '../components/Badge';
import { formatINR } from '../format/money';
import { motion as tokens } from '../tokens/tokens';

export type BudgetStatus = 'ok' | 'warning' | 'exceeded' | 'none';

export interface BarRow {
  key: string;
  categoryId: string | null;
  name: string | null;
  spentPaise: number;
  limitPaise: number | null;
  /** From the API; the bar width is this value scaled to pixels, capped at the track. */
  pctUsed: number | null;
  status: BudgetStatus;
}

const FILL: Record<BudgetStatus, string> = {
  ok: 'bg-positive',
  warning: 'bg-attention',
  exceeded: 'bg-negative',
  none: 'bg-ink-3',
};

/** Category rows with spend, limit and a thin progress bar coloured by the API status. */
export function BarList({ rows, ofLabel }: { rows: BarRow[]; ofLabel: (limit: string) => string }) {
  const reduce = useReducedMotion();
  return (
    <ul className="flex flex-col">
      {rows.map((row) => {
        const width = row.pctUsed == null ? 0 : Math.max(0, Math.min(100, row.pctUsed));
        return (
          <li
            key={row.key}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 border-b border-hairline px-6 py-3 last:border-b-0"
          >
            <CategoryPill categoryId={row.categoryId} name={row.name} />
            <span className="tabular text-right text-cell text-ink">
              {formatINR(row.spentPaise, { paise: 'never' })}
              {row.limitPaise != null ? (
                <span className="text-ink-3">
                  {' '}
                  {ofLabel(formatINR(row.limitPaise, { paise: 'never' }))}
                </span>
              ) : null}
            </span>
            {row.limitPaise != null ? (
              <div className="col-span-2 h-1 overflow-hidden rounded-full bg-surface-sunken">
                <motion.div
                  className={`h-full rounded-full ${FILL[row.status]}`}
                  initial={false}
                  animate={{ width: `${width}%` }}
                  transition={
                    reduce
                      ? { duration: 0 }
                      : { duration: tokens.slow / 1000, ease: tokens.easeArray }
                  }
                />
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
