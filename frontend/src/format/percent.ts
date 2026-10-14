/**
 * Percent display. The UI never computes a percent: it only renders values the API returned.
 * Values outside the sanity cap (or null) render as a designed "not comparable" state.
 */

/** Anything above this is treated as not comparable (guards against "999%" style badges). */
export const PERCENT_SANITY_CAP = 500;

export type PercentView =
  { kind: 'value'; text: string; direction: 'up' | 'down' | 'flat' } | { kind: 'not_comparable' };

/** Render an API-provided percent (already rounded by the API) with an explicit sign. */
export function viewPercent(value: number | null | undefined, signed = false): PercentView {
  if (value === null || value === undefined || !Number.isFinite(value))
    return { kind: 'not_comparable' };
  if (Math.abs(value) > PERCENT_SANITY_CAP) return { kind: 'not_comparable' };
  const direction = value > 0 ? 'up' : value < 0 ? 'down' : 'flat';
  const magnitude = Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 1 });
  const sign = signed ? (value > 0 ? '+' : value < 0 ? '\u2212' : '') : value < 0 ? '\u2212' : '';
  return { kind: 'value', text: `${sign}${magnitude}%`, direction };
}

/** Confidence (0..1 from the API) as a whole percent label, e.g. "62%". */
export function formatConfidence(confidence: number): string {
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
    throw new RangeError(`confidence must be within 0..1, got ${confidence}`);
  }
  return `${Math.round(confidence * 100)}%`;
}
