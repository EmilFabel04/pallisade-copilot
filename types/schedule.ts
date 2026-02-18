export interface ScheduledTask {
  id: string;
  name: string;
  taskMode: 'prompt' | 'structured';
  prompt?: string;
  description?: string;
  monitorType?: string;
  targetFqn?: string;
  config?: Record<string, any>;
  schedule: string;
  timezone: string;
  enabled: boolean;
  alertChannels: string[];
  alertConfig?: Record<string, any>;
  alertOnStatus: string[];
  lastRunAt?: string;
  lastStatus?: string;
  nextRunAt?: string;
  integrationId?: string;
  integrationName?: string;
  createdAt: string;
  updatedAt: string;
}

export interface TaskRun {
  id: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'ERROR' | 'SKIPPED' | 'RUNNING';
  value?: number;
  threshold?: number;
  message?: string;
  details?: Record<string, any>;
  sqlExecuted?: string;
  startedAt: string;
  completedAt?: string;
  durationMs?: number;
}

export const MONITOR_TYPES = [
  { value: 'FRESHNESS', label: 'Freshness', description: 'Auto-detects timestamp column & alert threshold' },
  { value: 'VOLUME', label: 'Volume', description: 'Auto-computes expected row count range from history' },
  { value: 'SCHEMA_CHANGE', label: 'Schema Change', description: 'Detect column additions/removals' },
  { value: 'NULL_RATE', label: 'Null Rate', description: 'Scans all columns for unexpected null spikes' },
  { value: 'UNIQUENESS', label: 'Uniqueness', description: 'Detects drops in column uniqueness' },
  { value: 'DISTRIBUTION', label: 'Distribution', description: 'Detects shifts in numeric column averages' },
  { value: 'CUSTOM_SQL', label: 'Custom SQL', description: 'Run a custom SQL check' },
  { value: 'ANOMALY', label: 'Anomaly', description: 'Z-score detection on row count or all columns' },
  // Infrastructure monitors (require Linux Server integration)
  { value: 'CERTIFICATE', label: 'Certificate', description: 'Detects expiring or missing TLS/SSL certificates' },
  { value: 'SERVER_HEALTH', label: 'Server Health', description: 'Monitors CPU, memory, disk usage' },
  { value: 'LOG_ANALYSIS', label: 'Log Analysis', description: 'Scans server logs for error patterns' },
] as const;

export const SCHEDULE_PRESETS = [
  { value: '0 * * * *', label: 'Every hour' },
  { value: '0 */6 * * *', label: 'Every 6 hours' },
  { value: '0 8 * * *', label: 'Daily at 8am' },
  { value: '0 8 * * 1-5', label: 'Weekdays at 8am' },
  { value: '0 8 * * 1', label: 'Weekly (Monday 8am)' },
] as const;

export const RUN_STATUS_COLORS: Record<string, string> = {
  PASS: 'bg-emerald-500/20 text-emerald-400',
  WARN: 'bg-amber-500/20 text-amber-400',
  FAIL: 'bg-red-500/20 text-red-400',
  ERROR: 'bg-red-500/20 text-red-300',
  SKIPPED: 'bg-white/10 text-white/40',
  RUNNING: 'bg-blue-500/20 text-blue-400',
};
