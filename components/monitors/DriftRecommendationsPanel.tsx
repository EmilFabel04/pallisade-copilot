'use client';

import { useEffect, useState } from 'react';
import { X, Loader2, Inbox } from 'lucide-react';
import { toast } from 'sonner';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  recommendations: DriftRecommendation[];
  stackId: string;
  onClose: () => void;
  onChanged: () => void;
}

export function DriftRecommendationsPanel({ recommendations, stackId, onClose, onChanged }: Props) {
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const callAction = async (recId: string, action: string, value?: string) => {
    setBusyId(recId);
    try {
      const body: Record<string, any> = { stackId, action };
      if (value !== undefined) {
        body.value = value;
        body.action = 'accept_with_value';
      }
      const res = await fetch(`/api/drift/${recId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || 'Action failed');
      } else {
        onChanged();
      }
    } finally {
      setBusyId(null);
    }
  };

  const onAccept = (recId: string, value?: string) => {
    void callAction(recId, 'accept', value);
  };
  const onDismiss = (recId: string) => {
    void callAction(recId, 'dismiss');
  };

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        onTouchEnd={onClose}
        aria-hidden
      />
      <aside
        className="fixed right-0 top-0 bottom-0 w-[560px] max-w-[95vw] bg-[var(--bg)] border-l border-[var(--subtle-border)] z-50 flex flex-col"
        role="dialog"
        aria-label="SLA recommendations"
      >
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[var(--subtle-border)]">
          <div>
            <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Drift discovery</div>
            <div className="text-[14px] font-semibold">
              {recommendations.length} SLA recommendation{recommendations.length === 1 ? '' : 's'}
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--surface)]" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {recommendations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Inbox className="w-8 h-8 text-[var(--text-faint)] mb-3" />
              <p className="text-[12px] text-[var(--muted)]">No pending recommendations.</p>
            </div>
          ) : (
            recommendations.map((rec) => (
              <div key={rec.id} className={busyId === rec.id ? 'opacity-60 pointer-events-none' : ''}>
                <DriftRecommendationCard
                  rec={rec}
                  onAccept={onAccept}
                  onDismiss={onDismiss}
                />
              </div>
            ))
          )}
        </div>
        {busyId && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="bg-[var(--surface)]/90 rounded-md px-3 py-2 flex items-center gap-2 text-[12px]">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Updating…
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
