import type { PrismaClient } from '@prisma/client';
import { fallbackSignature } from './signature';

const SCANNER_URL = process.env.SCANNER_URL ?? 'http://localhost:8000';
const DEFAULT_CONCURRENCY = Number(process.env.INCIDENT_DIAGNOSE_CONCURRENCY ?? 3);

const semaphores = new Map<string, { count: number; queue: Array<() => void> }>();

function acquire(stackId: string): Promise<() => void> {
  let s = semaphores.get(stackId);
  if (!s) {
    s = { count: 0, queue: [] };
    semaphores.set(stackId, s);
  }
  return new Promise((resolve) => {
    const tryAcquire = () => {
      if (s!.count < DEFAULT_CONCURRENCY) {
        s!.count += 1;
        resolve(() => release(stackId));
      } else {
        s!.queue.push(tryAcquire);
      }
    };
    tryAcquire();
  });
}

function release(stackId: string) {
  const s = semaphores.get(stackId);
  if (!s) return;
  s.count -= 1;
  const next = s.queue.shift();
  if (next) next();
}

/** For tests only — reset semaphore state between cases. */
export function __resetSemaphoresForTest() {
  semaphores.clear();
}

export async function diagnoseIncident(incidentId: string, prisma: PrismaClient): Promise<void> {
  const incident = await prisma.incident.findUnique({
    where: { id: incidentId },
    include: { monitor: { select: { monitorType: true } } },
  } as any) as any;
  if (!incident) return;

  const release = await acquire(incident.pipelineStackId);
  try {
    let hypothesis: string;
    let signature: string;
    let ownerSystem = 'unknown';
    let ownerConfidence = 0;

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const secret = process.env.SCANNER_SHARED_SECRET;
      if (secret) headers['X-Internal-Auth'] = secret;

      const res = await fetch(`${SCANNER_URL}/api/v1/copilot/incident-diagnose`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          stackId: incident.pipelineStackId,
          monitorRunId: incident.openingRunId,
          targetFqn: incident.targetFqn,
          monitorType: incident.monitor?.monitorType ?? 'UNKNOWN',
          runDetails: {},
        }),
      });
      if (!res.ok) throw new Error(`scanner returned ${res.status}`);
      const body = await res.json();
      hypothesis = body.hypothesis;
      signature = body.signature;
      ownerSystem = body.ownerSystem;
      ownerConfidence = body.ownerConfidence;
    } catch {
      // Deterministic fallback
      signature = fallbackSignature({
        monitorType: incident.monitor?.monitorType ?? 'UNKNOWN',
        breachClass: 'unknown',
      });
      hypothesis = 'Unable to generate hypothesis — analysis is offline. Click "Open in Co-pilot" to investigate manually.';
    }

    const signatureChanged = incident.signature !== null && incident.signature !== signature;
    const newCount = signatureChanged ? 1 : (incident.consecutiveCount ?? 0) + 1;

    await prisma.incident.update({
      where: { id: incidentId },
      data: {
        signature,
        llmHypothesis: hypothesis,
        llmHypothesisAt: new Date(),
        ownerSystem,
        ownerConfidence,
        consecutiveCount: newCount,
      },
    });
  } finally {
    release();
  }
}
