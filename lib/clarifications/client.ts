/**
 * Typed fetch helpers for the clarification UI.
 *
 * All read/write paths for ContextRequest rows go through the Next.js proxy
 * routes (FastAPI has no DB client). These wrappers exist so the React code
 * doesn't sprinkle URL literals everywhere and so error handling stays
 * uniform across the popup, the bell, and the SLA editor tag.
 */

import type { ContextRequest } from './types';

export async function listContextRequests(pipelineId: string): Promise<ContextRequest[]> {
  const res = await fetch(
    `/api/context-requests?pipeline_stack_id=${encodeURIComponent(pipelineId)}`,
    { cache: 'no-store' },
  );
  if (!res.ok) throw new Error(`list failed: ${res.status}`);
  const json = await res.json();
  return Array.isArray(json?.items) ? (json.items as ContextRequest[]) : [];
}

export async function dismissContextRequest(id: string): Promise<void> {
  const res = await fetch(`/api/context-requests/${id}/dismiss`, { method: 'POST' });
  if (!res.ok) throw new Error(`dismiss failed: ${res.status}`);
}
