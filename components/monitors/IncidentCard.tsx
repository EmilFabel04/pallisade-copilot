'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import type { IncidentSummary } from '@/types/incident';

interface Props {
  incident: IncidentSummary;
  onChanged: () => void;        // parent refetches after action
  onOpenInCopilot: (incident: IncidentSummary) => void;
}

const MUTE_PRESETS: Array<{ label: string; ms: number }> = [
  { label: '1h', ms: 60 * 60 * 1000 },
  { label: '4h', ms: 4 * 60 * 60 * 1000 },
  { label: '1d', ms: 24 * 60 * 60 * 1000 },
  { label: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
];

export function IncidentCard({ incident, onChanged, onOpenInCopilot }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showMuteMenu, setShowMuteMenu] = useState(false);

  const tone = incident.status === 'ACKNOWLEDGED'
    ? 'border-zinc-600/40 bg-zinc-500/[0.03] opacity-75'
    : incident.isMuted
      ? 'border-purple-500/30 bg-purple-500/[0.03] opacity-75'
      : 'border-red-400/40 bg-red-400/[0.04]';

  const dot = incident.status === 'ACKNOWLEDGED'
    ? 'bg-zinc-400'
    : incident.isMuted
      ? 'bg-purple-400'
      : 'bg-red-500';

  const since = (() => {
    const ms = Date.now() - new Date(incident.openedAt).getTime();
    const m = Math.floor(ms / 60000);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h`;
    return `${Math.floor(h / 24)}d`;
  })();

  async function callAction(path: string, body?: any) {
    setBusy(true);
    try {
      const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || 'Action failed');
      } else {
        onChanged();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn('rounded-xl border px-4 py-3 mb-2', tone)}>
      <div className="flex items-center gap-2.5">
        <span className={cn('w-2 h-2 rounded-full flex-shrink-0', dot)} />
        <span className="font-semibold text-[13px] text-[var(--text)]">{incident.targetFqn}</span>
        <span className="text-[11px] text-[var(--muted)]">{(incident.monitorType ?? 'unknown').toLowerCase()} · {since}</span>
        {incident.isMuted && incident.mutedUntil && (
          <span className="text-[10px] text-purple-300 ml-1">muted until {new Date(incident.mutedUntil).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        )}
      </div>

      <div className="mt-2 text-[12px] leading-snug">
        <div className="text-[9px] uppercase tracking-wider text-[var(--muted)]">Likely cause</div>
        {incident.llmHypothesis ? (
          <div className="text-[var(--text)]/90 mt-0.5">{incident.llmHypothesis}</div>
        ) : (
          <div className="text-[var(--muted)] mt-0.5 flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 animate-spin" /> Analyzing…
          </div>
        )}
      </div>

      <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
        <button
          disabled={busy}
          onClick={() => onOpenInCopilot(incident)}
          className="px-2.5 py-1 text-[11px] font-medium rounded bg-[var(--accent)] text-white hover:opacity-90"
        >
          Open in Co-pilot →
        </button>
        {incident.status === 'OPEN' && (
          <button disabled={busy} onClick={() => callAction(`/api/incidents/${incident.id}/acknowledge`)} className="px-2.5 py-1 text-[11px] rounded border border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]">
            Acknowledge
          </button>
        )}
        {(incident.status === 'OPEN' || incident.status === 'ACKNOWLEDGED') && (
          <ResolveMenu disabled={busy} onPick={(reason) => callAction(`/api/incidents/${incident.id}/resolve`, { reason })} />
        )}
        {incident.isMuted ? (
          <button disabled={busy} onClick={() => callAction(`/api/incidents/${incident.id}/unmute`)} className="px-2.5 py-1 text-[11px] rounded border border-purple-500/40 text-purple-300">
            Unmute
          </button>
        ) : (
          <div className="relative">
            <button disabled={busy} onClick={() => setShowMuteMenu((v) => !v)} className="px-2.5 py-1 text-[11px] rounded border border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]">
              Mute ▾
            </button>
            {showMuteMenu && (
              <div className="absolute z-10 mt-1 bg-[var(--surface)] border border-[var(--subtle-border)] rounded shadow-md p-1 min-w-[100px]">
                {MUTE_PRESETS.map((p) => (
                  <button key={p.label} className="block w-full text-left px-2 py-1 text-[11px] hover:bg-[var(--hover-bg)]"
                    onClick={() => { setShowMuteMenu(false); callAction(`/api/incidents/${incident.id}/mute`, { until: new Date(Date.now() + p.ms).toISOString() }); }}>
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <button onClick={() => setExpanded((v) => !v)} className="ml-auto text-[10px] text-[var(--muted)] flex items-center gap-1">
          {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          {expanded ? 'Hide' : 'Show'} evidence
        </button>
      </div>

      {expanded && (
        <div className="mt-2 pt-2 border-t border-[var(--subtle-border)] text-[11px] text-[var(--muted)] space-y-1.5">
          <div>Signature: <code>{incident.signature ?? '—'}</code> · count: {incident.consecutiveCount}</div>
          <div>Owner system: {incident.ownerSystem ?? '—'} ({incident.ownerConfidence != null ? `${Math.round(incident.ownerConfidence * 100)}% confidence` : 'n/a'})</div>
          <div>Opened {new Date(incident.openedAt).toLocaleString()}</div>
          <button
            disabled={busy}
            onClick={() => callAction(`/api/incidents/${incident.id}/reanalyze`)}
            className="text-[var(--accent)] hover:underline disabled:opacity-50"
          >
            {busy ? 'Re-analyzing…' : 'Re-analyze'}
          </button>
        </div>
      )}
    </div>
  );
}

function ResolveMenu({ disabled, onPick }: { disabled: boolean; onPick: (reason: string) => void }) {
  const [open, setOpen] = useState(false);
  const reasons = [
    { value: 'FIXED', label: 'Fixed' },
    { value: 'EXPECTED', label: 'Expected' },
    { value: 'FALSE_POSITIVE', label: 'False positive' },
    { value: 'WONT_FIX', label: "Won't fix" },
  ];
  return (
    <div className="relative">
      <button disabled={disabled} onClick={() => setOpen((v) => !v)} className="px-2.5 py-1 text-[11px] rounded border border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]">
        Resolve ▾
      </button>
      {open && (
        <div className="absolute z-10 mt-1 bg-[var(--surface)] border border-[var(--subtle-border)] rounded shadow-md p-1 min-w-[140px]">
          {reasons.map((r) => (
            <button key={r.value} className="block w-full text-left px-2 py-1 text-[11px] hover:bg-[var(--hover-bg)]"
              onClick={() => { setOpen(false); onPick(r.value); }}>
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
