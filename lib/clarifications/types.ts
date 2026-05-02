/**
 * Shared types for the clarification UI surface.
 *
 * Mirrors the response shape from `GET /api/context-requests` (see
 * `app/api/context-requests/route.ts`). The API normalises Prisma columns to
 * snake_case so the same payload can be consumed by both Next.js and the
 * FastAPI scanner without re-mapping field names. Keep this file in sync if
 * either side changes.
 */

export type ContextRequestStatus =
  | 'open'
  | 'answered'
  | 'dismissed'
  | 'superseded'
  | 'expired';

export type ContextRequestPriority = 'critical' | 'high' | 'normal' | 'low';

export interface ContextRequest {
  id: string;
  kind: string;
  scope_type: 'node' | 'dataset' | 'integration' | 'pipeline';
  scope_ref: string;
  payload: Record<string, unknown>;
  status: ContextRequestStatus;
  priority: ContextRequestPriority;
  created_at: string;
  dismissed_until: string | null;
}
