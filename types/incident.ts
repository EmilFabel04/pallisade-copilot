export type IncidentStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';
export type IncidentSeverity = 'FAIL' | 'WARN';

export type IncidentResolutionType =
  | 'AUTO_RECOVERED'
  | 'FIXED'
  | 'EXPECTED'
  | 'FALSE_POSITIVE'
  | 'WONT_FIX';

export interface IncidentSummary {
  id: string;
  monitorId: string;
  monitorGroupId: string | null;
  monitorType: string | null;
  targetFqn: string;
  status: IncidentStatus;
  severity: IncidentSeverity;
  openedAt: string;
  signature: string | null;
  consecutiveCount: number;
  llmHypothesis: string | null;
  llmHypothesisAt: string | null;
  ownerSystem: string | null;
  ownerConfidence: number | null;
  acknowledgedAt: string | null;
  acknowledgedBy: string | null;
  resolvedAt: string | null;
  resolvedBy: string | null;
  resolutionType: IncidentResolutionType | null;
  resolutionNote: string | null;
  mutedUntil: string | null;
  isMuted: boolean;
  mutedReason: string | null;
}

export interface IncidentStats {
  windowDays: number;
  passRate:  { current: number | null; prior: number | null };
  mttrMs:    { current: number | null; prior: number | null };
  opened:    { current: number; prior: number; sparkline: number[] };
  recovered: { current: number; prior: number; ratio: number | null };
}
