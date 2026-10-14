import { formatINR } from '../format/money';
import { cx } from '../components/cx';

export interface CalendarDay {
  /** IST calendar date "YYYY-MM-DD" from the API. */
  date: string;
  spentPaise: number | null;
  /** API-provided intensity bucket 0..4 for shading (never computed in the UI). */
  level: number;
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const SHADE = [
  'bg-surface',
  'bg-surface-sunken',
  'bg-cat-12-bg',
  'bg-attention-tint',
  'bg-negative-tint',
];

/** Month grid of daily totals (weeks start Monday). */
export function CalendarGrid({ days, label }: { days: CalendarDay[]; label: string }) {
  if (days.length === 0) return null;
  const first = new Date(`${days[0]!.date}T12:00:00Z`);
  const offset = (first.getUTCDay() + 6) % 7;
  return (
    <div role="table" aria-label={label} className="grid grid-cols-7 gap-1">
      {WEEKDAYS.map((d) => (
        <span key={d} role="columnheader" className="label-mono pb-1 text-ink-3">
          {d}
        </span>
      ))}
      {Array.from({ length: offset }, (_, i) => (
        <span key={`pad-${i}`} aria-hidden />
      ))}
      {days.map((day) => (
        <div
          key={day.date}
          role="cell"
          className={cx(
            'flex min-h-14 flex-col justify-between rounded-[6px] border border-hairline p-1.5',
            SHADE[Math.max(0, Math.min(4, day.level))],
          )}
        >
          <span className="tabular text-[11px] text-ink-3">{Number(day.date.slice(8))}</span>
          <span className="tabular truncate text-[12px] text-ink">
            {day.spentPaise == null || day.spentPaise === 0
              ? '–'
              : formatINR(day.spentPaise, { paise: 'never' })}
          </span>
        </div>
      ))}
    </div>
  );
}
