/**
 * Parse a date string, treating naive timestamps (no Z or +offset) as UTC.
 * Python's datetime.utcnow().isoformat() omits the Z suffix, which causes
 * browsers to interpret them as local time — this fixes that.
 */
function parseAsUTC(date: string | Date): Date {
  if (date instanceof Date) return date;
  // If the string has no timezone indicator, append Z to treat as UTC
  if (date && !date.endsWith('Z') && !date.includes('+') && !/\d{2}:\d{2}$/.test(date.slice(-6))) {
    return new Date(date + 'Z');
  }
  return new Date(date);
}

/**
 * Format a date/timestamp with the user's timezone.
 * All API responses return UTC; this converts for display.
 */
export function formatDate(
  date: string | Date | null | undefined,
  timezone: string | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  if (!date) return 'Unknown';

  const d = typeof date === 'string' ? parseAsUTC(date) : date;
  if (isNaN(d.getTime())) return 'Unknown';

  const tz = timezone || 'UTC';
  const defaultOptions: Intl.DateTimeFormatOptions = {
    timeZone: tz,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  };

  return d.toLocaleString([], { ...defaultOptions, ...options });
}

/**
 * Format a date as a relative time string (e.g., "2h ago", "3d ago").
 */
export function formatRelativeTime(
  date: string | Date | null | undefined,
  timezone: string | null | undefined
): string {
  if (!date) return 'Unknown';

  const d = typeof date === 'string' ? parseAsUTC(date) : date;
  if (isNaN(d.getTime())) return 'Unknown';

  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);

  if (diffHours < 0) return 'Just now';
  if (diffHours < 1) return 'Just now';
  if (diffHours < 24) return `${Math.round(diffHours)}h ago`;
  if (diffHours < 24 * 30) return `${Math.round(diffHours / 24)}d ago`;

  return formatDate(d, timezone, { hour: undefined, minute: undefined });
}

/**
 * Format a date for display in short form (date only, no time).
 */
export function formatDateShort(
  date: string | Date | null | undefined,
  timezone: string | null | undefined
): string {
  return formatDate(date, timezone, {
    hour: undefined,
    minute: undefined,
  });
}
