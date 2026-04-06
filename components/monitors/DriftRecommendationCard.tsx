'use client';

import React, { useState } from 'react';
import { Check, X, Pencil } from 'lucide-react';

const CATEGORY_COLORS: Record<string, { color: string; bg: string }> = {
  freshness: { color: 'text-blue-400', bg: 'bg-blue-500/15' },
  volume: { color: 'text-purple-400', bg: 'bg-purple-500/15' },
  quality: { color: 'text-amber-400', bg: 'bg-amber-500/15' },
  schema: { color: 'text-orange-400', bg: 'bg-orange-500/15' },
  anomaly: { color: 'text-red-400', bg: 'bg-red-500/15' },
  uniqueness: { color: 'text-cyan-400', bg: 'bg-cyan-500/15' },
};

const SEVERITY_STYLES: Record<string, { color: string; bg: string }> = {
  low: { color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
  medium: { color: 'text-amber-400', bg: 'bg-amber-500/15' },
  high: { color: 'text-red-400', bg: 'bg-red-500/15' },
};

export interface DriftRecommendation {
  id: string;
  monitorName: string;
  monitorType: string;
  targetFqn: string;
  driftCategory: string;
  severity: string;
  currentField: string;
  currentValue: string;
  recommendedValue: string;
  reasoning: string;
  confidence: number;
  evidence: any;
  status: string;
  reviewedAt: string | null;
  createdAt: string;
}

interface Props {
  rec: DriftRecommendation;
  onAccept: (id: string, value?: string) => void;
  onDismiss: (id: string) => void;
}

export function DriftRecommendationCard({ rec, onAccept, onDismiss }: Props) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(rec.recommendedValue);
  const [expanded, setExpanded] = useState(false);

  const catStyle = CATEGORY_COLORS[rec.driftCategory] || CATEGORY_COLORS.quality;
  const sevStyle = SEVERITY_STYLES[rec.severity] || SEVERITY_STYLES.medium;
  const isActioned = rec.status !== 'pending';

  const fieldLabel = rec.currentField.replace('.', ': ').replace(/([A-Z])/g, ' $1').trim();

  return (
    <div className={`p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-raised)] transition-all ${isActioned ? 'opacity-60' : 'hover:border-[var(--accent)]/30'}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${catStyle.color} ${catStyle.bg}`}>
            {rec.driftCategory}
          </span>
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${sevStyle.color} ${sevStyle.bg}`}>
            {rec.severity}
          </span>
          {rec.status === 'accepted' && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded text-emerald-400 bg-emerald-500/15">Accepted</span>
          )}
          {rec.status === 'dismissed' && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded text-zinc-400 bg-zinc-500/15">Dismissed</span>
          )}
        </div>
        <span className="text-[10px] text-[var(--muted)]">{Math.round(rec.confidence * 100)}% confidence</span>
      </div>

      {/* Monitor info */}
      <p className="text-[13px] font-medium text-[var(--text)] truncate">{rec.monitorName}</p>
      <p className="text-[11px] text-[var(--muted)] font-mono truncate mt-0.5">{rec.targetFqn}</p>

      {/* Change row */}
      <div className="flex items-center gap-2 mt-3 p-2 rounded-lg bg-[var(--overlay-bg)]">
        <span className="text-[11px] text-[var(--muted)]">{fieldLabel}:</span>
        <span className="text-[12px] text-[var(--text)] font-medium">{rec.currentValue}</span>
        <span className="text-[11px] text-[var(--muted)]">&rarr;</span>
        {editing ? (
          <input
            type="text"
            value={editValue}
            onChange={e => setEditValue(e.target.value)}
            className="w-20 px-2 py-0.5 text-[12px] rounded border border-[var(--accent)]/50 bg-[var(--surface-raised)] text-[var(--text)]"
            autoFocus
          />
        ) : (
          <span className="text-[12px] text-[var(--accent)] font-semibold">{rec.recommendedValue}</span>
        )}
      </div>

      {/* Reasoning */}
      <p className="text-[11px] text-[var(--muted)] mt-2 leading-relaxed">
        {expanded ? rec.reasoning : rec.reasoning.slice(0, 120)}
        {rec.reasoning.length > 120 && (
          <button onClick={() => setExpanded(!expanded)} className="text-[var(--accent)] ml-1">
            {expanded ? 'less' : '...more'}
          </button>
        )}
      </p>

      {/* Actions */}
      {!isActioned && (
        <div className="flex items-center gap-2 mt-3">
          {editing ? (
            <>
              <button
                onClick={() => { onAccept(rec.id, editValue); setEditing(false); }}
                className="flex items-center gap-1 px-3 py-1.5 text-[11px] font-medium rounded-md bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors"
              >
                <Check className="w-3 h-3" /> Apply
              </button>
              <button
                onClick={() => { setEditing(false); setEditValue(rec.recommendedValue); }}
                className="px-3 py-1.5 text-[11px] font-medium rounded-md text-[var(--muted)] hover:bg-[var(--subtle-bg)] transition-colors"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => onAccept(rec.id)}
                className="flex items-center gap-1 px-3 py-1.5 text-[11px] font-medium rounded-md bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors"
              >
                <Check className="w-3 h-3" /> Accept
              </button>
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1 px-3 py-1.5 text-[11px] font-medium rounded-md bg-[var(--subtle-bg)] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
              >
                <Pencil className="w-3 h-3" /> Edit
              </button>
              <button
                onClick={() => onDismiss(rec.id)}
                className="flex items-center gap-1 px-3 py-1.5 text-[11px] font-medium rounded-md text-[var(--muted)] hover:text-red-400 transition-colors"
              >
                <X className="w-3 h-3" /> Dismiss
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
