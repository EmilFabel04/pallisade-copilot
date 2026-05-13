import type { ArtifactKind, ArtifactRisk, ArtifactStatus } from '@prisma/client';
import type { ArtifactPayload } from './artifact';

export interface ArtefactRow {
  id: string;
  kind: ArtifactKind;
  subtype: string | null;
  status: ArtifactStatus;
  title: string;
  summary: string | null;
  payload: ArtifactPayload;
  externalRef: Record<string, unknown> | null;
  riskLevel: ArtifactRisk | null;
  rollbackHint: string | null;
  tags: string[];
  isPinned: boolean;
  isSaved: boolean;
  metadata: Record<string, unknown> | null;
  agentSessionId: string | null;
  sourceSessionId: string | null;
  integrationId: string | null;
  agentRunId: string | null;
  toolCallId: string | null;
  createdAt: string;
  updatedAt: string;
  appliedAt: string | null;

  sourceSession: { id: string; title: string | null } | null;
  agentSession: { id: string; title: string | null } | null;
  integration: { id: string; type: string } | null;
}

export interface ArtefactListResponse {
  artifacts: ArtefactRow[];
  pagination: { total: number; limit: number; offset: number; hasMore: boolean };
}
