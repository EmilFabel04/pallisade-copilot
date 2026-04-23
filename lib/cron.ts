/**
 * Compute the next run time from a cron expression.
 * Supports standard 5-field cron: minute hour day-of-month month day-of-week
 *
 * Returns a Date in UTC, or null if the expression is invalid.
 */
export function computeNextRun(cronExpr: string, tz: string = 'UTC'): Date | null {
  try {
    const parts = cronExpr.trim().split(/\s+/);
    if (parts.length < 5) return null;

    const [minSpec, hourSpec, domSpec, monSpec, dowSpec] = parts;

    // Get current time in the target timezone
    const now = new Date();
    const tzNow = new Date(now.toLocaleString('en-US', { timeZone: tz }));
    // Offset between local interpretation and UTC
    const tzOffsetMs = tzNow.getTime() - now.getTime();

    // Start searching from the next minute
    const candidate = new Date(tzNow);
    candidate.setSeconds(0, 0);
    candidate.setMinutes(candidate.getMinutes() + 1);

    // Search up to 366 days ahead
    const maxIterations = 366 * 24 * 60;

    for (let i = 0; i < maxIterations; i++) {
      if (
        matchField(monSpec, candidate.getMonth() + 1, 1, 12) &&
        matchField(domSpec, candidate.getDate(), 1, 31) &&
        matchField(dowSpec, candidate.getDay(), 0, 7) &&
        matchField(hourSpec, candidate.getHours(), 0, 23) &&
        matchField(minSpec, candidate.getMinutes(), 0, 59)
      ) {
        // Convert back from tz-local to UTC
        return new Date(candidate.getTime() - tzOffsetMs);
      }
      candidate.setMinutes(candidate.getMinutes() + 1);
    }

    return null;
  } catch {
    return null;
  }
}

function matchField(spec: string, value: number, min: number, max: number): boolean {
  if (spec === '*') return true;

  // Handle day-of-week 7 === 0 (Sunday)
  if (max === 7 && value === 0) value = 7;

  for (const part of spec.split(',')) {
    // Handle step: */n or range/n
    if (part.includes('/')) {
      const [rangeStr, stepStr] = part.split('/');
      const step = parseInt(stepStr, 10);
      if (isNaN(step) || step <= 0) continue;

      let rangeStart = min;
      let rangeEnd = max;
      if (rangeStr !== '*') {
        if (rangeStr.includes('-')) {
          const [s, e] = rangeStr.split('-').map(Number);
          rangeStart = s;
          rangeEnd = e;
        } else {
          rangeStart = parseInt(rangeStr, 10);
        }
      }
      if (value >= rangeStart && value <= rangeEnd && (value - rangeStart) % step === 0) return true;
      continue;
    }

    // Handle range: a-b
    if (part.includes('-')) {
      const [s, e] = part.split('-').map(Number);
      if (value >= s && value <= e) return true;
      continue;
    }

    // Handle single value
    if (parseInt(part, 10) === value) return true;
    // Sunday: both 0 and 7 match
    if (max === 7 && parseInt(part, 10) === 0 && value === 7) return true;
  }

  return false;
}
