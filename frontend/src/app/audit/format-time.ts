// SQLite's CURRENT_TIMESTAMP is "YYYY-MM-DD HH:MM:SS" in UTC with no zone marker; without the "Z" the browser would read it as local time.
export function parseUtc(value: string): Date {
  return new Date(value.replace(' ', 'T') + 'Z');
}

const ABSOLUTE = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

/** "5 minutes ago" for the last day, otherwise "Nov 12, 2026, 9:37 AM" in the viewer's timezone. */
export function formatWhen(value: string, now: Date = new Date()): string {
  const date = parseUtc(value);
  if (isNaN(date.getTime())) return value;
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  if (seconds <= 0 && abs < 60) return 'just now';
  if (seconds <= 0 && abs < 3600) return RELATIVE.format(Math.round(seconds / 60), 'minute');
  if (seconds <= 0 && abs < 86400) return RELATIVE.format(Math.round(seconds / 3600), 'hour');
  return ABSOLUTE.format(date);
}

/** Full local date and time, used as the hover tooltip. */
export function formatFull(value: string): string {
  const date = parseUtc(value);
  return isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'full', timeStyle: 'long' }).format(date);
}
