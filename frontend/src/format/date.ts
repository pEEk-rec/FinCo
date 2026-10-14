/** Dates are rendered in IST, Indian style ("14 Oct 2026"), never US order. */

const TZ = 'Asia/Kolkata';

const dayFormat = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: TZ,
});
const dayShort = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', timeZone: TZ });
const weekdayLong = new Intl.DateTimeFormat('en-IN', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  timeZone: TZ,
});
const monthLong = new Intl.DateTimeFormat('en-IN', {
  month: 'long',
  year: 'numeric',
  timeZone: TZ,
});
const monthOnly = new Intl.DateTimeFormat('en-IN', { month: 'long', timeZone: TZ });
const timeFormat = new Intl.DateTimeFormat('en-IN', {
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
  timeZone: TZ,
});
const isoDay = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: TZ,
});

function parse(utcIso: string): Date {
  const date = new Date(utcIso);
  if (Number.isNaN(date.getTime())) throw new TypeError(`Invalid timestamp: ${utcIso}`);
  return date;
}

/** "14 Oct 2026" */
export const formatDay = (utcIso: string): string => dayFormat.format(parse(utcIso));
/** "14 Oct" */
export const formatDayShort = (utcIso: string): string => dayShort.format(parse(utcIso));
/** "Tuesday, 14 October" (list group headers) */
export const formatDayHeader = (utcIso: string): string => weekdayLong.format(parse(utcIso));
/** "3:05 pm" */
export const formatTime = (utcIso: string): string => timeFormat.format(parse(utcIso));
/** IST calendar day key "2026-10-14", used to group rows by day. */
export const istDayKey = (utcIso: string): string => isoDay.format(parse(utcIso));

/** "October 2026" for a "YYYY-MM" period. */
export function formatPeriod(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) throw new TypeError(`Invalid period: ${period}`);
  // Noon UTC on the 15th is the same calendar month in every timezone.
  return monthLong.format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 15, 12)));
}

/** "October" for a "YYYY-MM" period. */
export function formatPeriodMonth(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) throw new TypeError(`Invalid period: ${period}`);
  return monthOnly.format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 15, 12)));
}
