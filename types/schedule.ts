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
  monitorGroupId?: string;
  monitorGroupName?: string;
  createdAt: string;
  updatedAt: string;
}

export interface MonitorGroupSummary {
  id: string;
  name: string;
  description?: string;
  groupType: string;
  anchorFqn?: string;
  anchorNodeId?: string;
  monitorCount: number;
  passCount: number;
  failCount: number;
  warnCount: number;
  lastStatus?: string;
  lastRunAt?: string;
  schedule?: string;
  timezone?: string;
  enabled: boolean;
  // Group Monitor fields (present when watchType is set)
  watchType?: string;
  anchorNodeType?: string;
  anchorPlatform?: string;
  healthScore?: number;
  healthDetails?: Record<string, any>;
  coveragePct?: number;
  lastHealthAt?: string;
  monitors: Array<{
    id: string;
    name: string;
    monitorType?: string;
    targetFqn?: string;
    enabled: boolean;
    lastStatus?: string;
    lastRunAt?: string;
    schedule?: string;
  }>;
  createdAt: string;
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

// Re-exported from the monitor catalog for backward compatibility.
// New code should use MONITOR_CATALOG from './monitor-catalog' directly.
import { MONITOR_CATALOG } from './monitor-catalog';

export const MONITOR_TYPES = MONITOR_CATALOG.map((m) => ({
  value: m.key as string,
  label: m.label,
  description: m.description,
}));

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
