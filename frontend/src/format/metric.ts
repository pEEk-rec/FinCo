import type { Unit } from '../api/client';
import { formatINR } from './money';

/** A challenge value with its unit: rupees, a count, days or a whole percentage. */
export function formatUnit(unit: Unit, value: number): string {
  switch (unit) {
    case 'money':
      return formatINR(value, { paise: 'never' });
    case 'percent_bp':
      return `${Math.floor(value / 100)}%`;
    case 'days':
      return value === 1 ? '1 day' : `${value} days`; // figures-ok: unit wording for an API value
    default:
      return String(value);
  }
}
