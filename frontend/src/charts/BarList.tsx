import { motion, useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';

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
  /** From the API: how far spend is past the limit (0 when within it). */
  overPaise?: number | null;
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
export function BarList({
  rows,
  ofLabel,
  overLabel,
  hrefFor,
}: {
  rows: BarRow[];
  /** "of ₹2,000 budget": what the spend is measured against. */
  ofLabel: (limit: string) => string;
  /** "₹2,213 over budget": shown instead when the spend has passed the limit. */
  overLabel: (over: string) => string;
  /** When given, each row opens this link (for example the category's payments). */
  hrefFor?: (row: BarRow) => string;
}) {
  const reduce = useReducedMotion();
  return (
    <ul className="flex flex-col">
      {rows.map((row) => {
        const width = row.pctUsed == null ? 0 : Math.max(0, Math.min(100, row.pctUsed));
        return (
          <li key={row.key} className="border-b border-hairline last:border-b-0">
            <RowFrame href={hrefFor?.(row)}>
              <CategoryPill categoryId={row.categoryId} name={row.name} />
              <span className="tabular text-right text-cell text-ink">
                {formatINR(row.spentPaise, { paise: 'never' })}
                {row.limitPaise != null ? (
                  <span className="text-ink-3">
                    {' '}
                    {row.overPaise
                      ? overLabel(formatINR(row.overPaise, { paise: 'never' }))
                      : ofLabel(formatINR(row.limitPaise, { paise: 'never' }))}
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
            </RowFrame>
          </li>
        );
      })}
    </ul>
  );
}

function RowFrame({ href, children }: { href: string | undefined; children: ReactNode }) {
  const grid = 'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-6 py-3';
  return href ? (
    <Link
      to={href}
      className={`${grid} transition-colors duration-fast hover:bg-surface-hover focus-visible:bg-surface-hover`}
    >
      {children}
    </Link>
  ) : (
    <div className={grid}>{children}</div>
  );
}
