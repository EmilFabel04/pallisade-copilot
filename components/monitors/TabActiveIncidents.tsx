'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { ActiveIncidents } from './ActiveIncidents';
import type { IncidentSummary } from '@/types/incident';

interface Props {
  stackId: string;
  monitorTypes: Set<string>;
  /** Optional label override; defaults to "Active incidents" via ActiveIncidents itself. */
  label?: string;
}

export function TabActiveIncidents({ stackId, monitorTypes }: Props) {
  const router = useRouter();
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);

  const fetchIncidents = useCallback(async () => {
    if (!stackId) return;
    try {
      const r = await cachedFetch(`/api/incidents?stackId=${stackId}&status=active`);
      if (r.ok) {
        const d = await r.json();
        setIncidents(d.incidents || []);
      }
    } catch {}
  }, [stackId]);

  useEffect(() => { fetchIncidents(); }, [fetchIncidents]);
  useEffect(() => {
    const t = setInterval(() => {
      invalidateCache('/api/incidents');
      fetchIncidents();
    }, 30000);
    return () => clearInterval(t);
  }, [fetchIncidents]);

  const filtered = incidents.filter((i) =>
    i.monitorType ? monitorTypes.has(String(i.monitorType).toUpperCase()) : false
  );

  const handleOpenInCopilot = useCallback((incident: IncidentSummary) => {
    // See DriftSummaryTab — same pattern as RunHistoryTable.navigateToScout:
    // sessionStorage + router.push('/dashboard/assistant') so the assistant's
    // deep-link effect opens a fresh chat and asks the LLM directly.
    const target = incident.targetFqn || 'unknown table';
    const type = incident.monitorType || 'monitor';
    const hypothesis = incident.llmHypothesis;
    const prompt = hypothesis
      ? `/debug Investigate the open incident on \`${target}\`. Initial hypothesis: ${hypothesis}. Identify the most likely root cause and recommend the next action.`
      : `/debug Investigate the open incident on \`${target}\`. Identify the most likely root cause and recommend the next action.`;
    const context = JSON.stringify({
      taskName: 'Incident',
      monitorType: type,
      targetFqn: target,
      status: incident.severity,
      message: hypothesis ?? undefined,
      details: {
        incidentId: incident.id,
        signature: incident.signature ?? undefined,
        consecutiveCount: incident.consecutiveCount,
        ownerSystem: incident.ownerSystem ?? undefined,
        ownerConfidence: incident.ownerConfidence ?? undefined,
        openedAt: incident.openedAt,
      },
    });
    const display = `Investigate the incident on ${target}`;
    if (typeof window !== 'undefined') {
      sessionStorage.setItem('askScoutDeepLink', JSON.stringify({ prompt, context, display }));
    }
    router.push('/dashboard/assistant');
  }, [router]);

  const onChanged = useCallback(() => {
    invalidateCache('/api/incidents');
    fetchIncidents();
  }, [fetchIncidents]);

  if (filtered.length === 0) return null;

  return (
    <ActiveIncidents
      incidents={filtered}
      onChanged={onChanged}
      onOpenInCopilot={handleOpenInCopilot}
    />
  );
}
