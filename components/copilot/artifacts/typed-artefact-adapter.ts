import type { ArtefactRow, TypedArtefactEnvelope } from '@/types/artefact-row';

// The body components from `components/artefacts/bodies/` consume an
// `ArtefactRow`; the SSE envelope is narrower. Synthesize the missing
// fields with neutral defaults — the bodies only read `kind`, `payload`,
// `status`, `title`, and `summary`.
export function envelopeToRow(env: TypedArtefactEnvelope): ArtefactRow {
  const now = new Date().toISOString();
  return {
    id: env.artefactId,
    kind: env.kind,
    subtype: null,
    status: env.status,
    title: env.title,
    summary: env.summary,
    payload: env.payload,
    externalRef: env.externalRef,
    riskLevel: env.riskLevel,
    rollbackHint: null,
    tags: [],
    isPinned: env.isPinned,
    isSaved: env.isSaved,
    metadata: null,
    agentSessionId: env.agentSessionId,
    sourceSessionId: env.sourceSessionId,
    integrationId: null,
    agentRunId: null,
    toolCallId: null,
    createdAt: now,
    updatedAt: now,
    appliedAt: env.status === 'applied' ? now : null,
    sourceSession: null,
    agentSession: null,
    integration: null,
  };
}
