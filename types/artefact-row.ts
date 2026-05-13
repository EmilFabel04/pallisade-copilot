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

// SSE envelope yielded by the scanner (`typed_artefact` event) when a
// write tool's auto-emit persists an artefact row. The chat hook collects
// these into StreamingMessage.typedArtefacts and the assistant page renders
// each one as a TypedArtefactCard inline with the assistant reply.
export interface TypedArtefactEnvelope {
  artefactId: string;
  kind: ArtefactRow['kind'];
  status: ArtefactRow['status'];
  title: string;
  summary: string | null;
  payload: ArtifactPayload;
  externalRef: Record<string, unknown> | null;
  riskLevel: ArtefactRow['riskLevel'];
  agentSessionId: string | null;
  sourceSessionId: string | null;
  isPinned: boolean;
  isSaved: boolean;
  // Source tool name (e.g. "create_monitor") so approve/reject can route
  // back to the right tool via the __action:confirm protocol.
  toolName: string;
}
