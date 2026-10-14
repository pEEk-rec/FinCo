/**
 * The only money formatter in the app. Input is always integer paise from the API.
 *
 * - Indian digit grouping: last three digits, then pairs (1,23,45,678.90).
 * - Negative values use the true minus sign (U+2212): "−₹1,234.50".
 * - All arithmetic is BigInt: no floating point ever touches a money value.
 * - Rounding (when paise are hidden or in compact form) is half up, away from zero.
 * - Compact forms ("₹1.2L") are for chart axes only.
 */

export const RUPEE = '₹';
export const MINUS = '−';

export type PaiseDisplay = 'always' | 'auto' | 'never';
export type SignDisplay = 'negative' | 'always' | 'never';

export interface FormatINROptions {
  /** 'always' shows .00; 'auto' hides .00 only when exactly whole; 'never' rounds to rupees. */
  paise?: PaiseDisplay;
  /** 'negative' (default) marks negatives only; 'always' adds + to positives; 'never' drops it. */
  sign?: SignDisplay;
  /** Show the ₹ symbol (default true). */
  symbol?: boolean;
  /** Chart-axis form: K, L (lakh), Cr (crore) with one decimal. */
  compact?: boolean;
}

/** Group a non-negative integer string the Indian way: 1234567 -> 12,34,567. */
export function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  let rest = digits.slice(0, -3);
  const pairs: string[] = [];
  while (rest.length > 2) {
    pairs.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  pairs.unshift(rest);
  return `${pairs.join(',')},${last3}`;
}

/** Divide a non-negative BigInt, rounding half up. */
function divRoundHalfUp(value: bigint, divisor: bigint): bigint {
  return (value * 2n + divisor) / (divisor * 2n);
}

const COMPACT_STEPS: { min: bigint; unit: bigint; suffix: string }[] = [
  { min: 1_00_00_000n * 100n, unit: 1_00_00_000n * 100n, suffix: 'Cr' },
  { min: 1_00_000n * 100n, unit: 1_00_000n * 100n, suffix: 'L' },
  { min: 1_000n * 100n, unit: 1_000n * 100n, suffix: 'K' },
];

function formatCompact(absPaise: bigint): string {
  for (const step of COMPACT_STEPS) {
    if (absPaise >= step.min) {
      // One decimal place: round half up at tenths of the unit.
      const tenths = divRoundHalfUp(absPaise * 10n, step.unit);
      const whole = tenths / 10n;
      const frac = tenths % 10n;
      const number =
        frac === 0n ? groupIndian(whole.toString()) : `${groupIndian(whole.toString())}.${frac}`;
      return `${number}${step.suffix}`;
    }
  }
  return groupIndian(divRoundHalfUp(absPaise, 100n).toString());
}

function formatFull(absPaise: bigint, paise: PaiseDisplay): string {
  if (paise === 'never') return groupIndian(divRoundHalfUp(absPaise, 100n).toString());
  const rupees = absPaise / 100n;
  const rest = absPaise % 100n;
  if (paise === 'auto' && rest === 0n) return groupIndian(rupees.toString());
  return `${groupIndian(rupees.toString())}.${rest.toString().padStart(2, '0')}`;
}

/** Format integer paise as Indian rupees. Throws on non-integer or unsafe input. */
export function formatINR(paise: number, opts: FormatINROptions = {}): string {
  if (!Number.isSafeInteger(paise)) {
    throw new TypeError(`formatINR expects a safe integer number of paise, got ${String(paise)}`);
  }
  const { paise: paiseMode = 'always', sign = 'negative', symbol = true, compact = false } = opts;
  const value = BigInt(paise);
  const abs = value < 0n ? -value : value;
  const body = compact ? formatCompact(abs) : formatFull(abs, paiseMode);
  const isZero = /^[0.,]*$/.test(body.replace(/[KLCr]/g, ''));
  let prefix = '';
  if (sign !== 'never' && !isZero) {
    if (value < 0n) prefix = MINUS;
    else if (sign === 'always' && value > 0n) prefix = '+';
  }
  return `${prefix}${symbol ? RUPEE : ''}${body}`;
}

/** Short accessible text for screen readers, e.g. "minus 1,234 rupees 50 paise". */
export function spokenINR(paise: number): string {
  if (!Number.isSafeInteger(paise)) throw new TypeError('spokenINR expects integer paise');
  const value = BigInt(paise);
  const abs = value < 0n ? -value : value;
  const rupees = groupIndian((abs / 100n).toString());
  const rest = abs % 100n;
  const words = rest === 0n ? `${rupees} rupees` : `${rupees} rupees ${rest} paise`;
  return value < 0n ? `minus ${words}` : words;
}

/**
 * Parse what a user typed ("2,000", "2000.50", "₹2,000") into integer paise, or null when it
 * is not a valid positive amount with at most two decimals. Input parsing only: no arithmetic
 * on financial values happens in the UI.
 */
export function parseRupeesToPaise(text: string): number | null {
  const cleaned = text.replace(/[\s,\u20B9]/g, '');
  const match = /^(\d{1,12})(?:\.(\d{1,2}))?$/.exec(cleaned);
  if (!match) return null;
  const paise = BigInt(match[1] as string) * 100n + BigInt((match[2] ?? '').padEnd(2, '0') || '0');
  if (paise <= 0n || paise > BigInt(Number.MAX_SAFE_INTEGER)) return null;
  return Number(paise);
}
