'use client';

import { useState } from 'react';
import { IncidentCard } from './IncidentCard';
import type { IncidentSummary } from '@/types/incident';

interface Props {
  incidents: IncidentSummary[];
  onChanged: () => void;
  onOpenInCopilot: (i: IncidentSummary) => void;
}

export function ActiveIncidents({ incidents, onChanged, onOpenInCopilot }: Props) {
  const [showMuted, setShowMuted] = useState(false);

  const visible = incidents.filter((i) => !i.isMuted);
  const muted = incidents.filter((i) => i.isMuted);

  visible.sort((a, b) => {
    if (a.status !== b.status) return a.status === 'OPEN' ? -1 : 1;
    return new Date(a.openedAt).getTime() - new Date(b.openedAt).getTime();
  });

  if (incidents.length === 0) return null;

  return (
    <div className="mb-6">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Active incidents
      </div>
      {visible.map((i) => (
        <IncidentCard key={i.id} incident={i} onChanged={onChanged} onOpenInCopilot={onOpenInCopilot} />
      ))}
      {muted.length > 0 && (
        <div className="mt-2">
          <button onClick={() => setShowMuted((v) => !v)} className="text-[11px] text-[var(--muted)] hover:text-[var(--text)]">
            {showMuted ? '−' : '+'} {muted.length} muted incident{muted.length === 1 ? '' : 's'}
          </button>
          {showMuted && (
            <div className="mt-2">
              {muted.map((i) => (
                <IncidentCard key={i.id} incident={i} onChanged={onChanged} onOpenInCopilot={onOpenInCopilot} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
