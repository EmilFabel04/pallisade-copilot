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
    const params = new URLSearchParams({
      contextType: 'incident',
      incidentId: incident.id,
      monitorId: incident.monitorId,
      targetFqn: incident.targetFqn,
    });
    router.push(`/dashboard/assistant?${params.toString()}`);
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
