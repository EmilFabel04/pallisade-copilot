'use client';

import React, { useState } from 'react';
import { Check, X, Pencil, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react';

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string; icon: string }> = {
  freshness: { label: 'Freshness', color: 'text-blue-400', bg: 'bg-blue-500/10', icon: 'clock' },
  volume: { label: 'Volume', color: 'text-purple-400', bg: 'bg-purple-500/10', icon: 'bar-chart' },
  quality: { label: 'Quality', color: 'text-amber-400', bg: 'bg-amber-500/10', icon: 'check-circle' },
  schema: { label: 'Schema', color: 'text-orange-400', bg: 'bg-orange-500/10', icon: 'columns' },
  anomaly: { label: 'Anomaly', color: 'text-red-400', bg: 'bg-red-500/10', icon: 'alert-triangle' },
  uniqueness: { label: 'Uniqueness', color: 'text-cyan-400', bg: 'bg-cyan-500/10', icon: 'fingerprint' },
};

const SEVERITY_CONFIG: Record<string, { label: string; color: string; border: string }> = {
  low: { label: 'Low', color: 'text-zinc-400', border: 'border-l-zinc-500/40' },
  medium: { label: 'Medium', color: 'text-amber-400', border: 'border-l-amber-500/60' },
  high: { label: 'High', color: 'text-red-400', border: 'border-l-red-500/60' },
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

  const cat = CATEGORY_CONFIG[rec.driftCategory] || CATEGORY_CONFIG.quality;
  const sev = SEVERITY_CONFIG[rec.severity] || SEVERITY_CONFIG.medium;
  const isActioned = rec.status !== 'pending';

  // Format field label: "freshness.maxHours" → "Max Hours"
  const fieldParts = rec.currentField.split('.');
  const rawFieldLabel = (fieldParts[1] || fieldParts[0])
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, s => s.toUpperCase())
    .trim();
  // Clarify volume labels — monitors use daily bucketing, not total count
  const fieldLabel = rec.driftCategory === 'volume' && rawFieldLabel === 'Min Rows'
    ? 'Min Daily Volume'
    : rec.driftCategory === 'volume' && rawFieldLabel === 'Max Rows'
    ? 'Max Daily Volume'
    : rawFieldLabel;

  const isTightening = !isNaN(Number(rec.currentValue)) && !isNaN(Number(rec.recommendedValue))
    && Number(rec.recommendedValue) < Number(rec.currentValue);

  return (
    <div className={`rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] border-l-[3px] ${sev.border} transition-all ${isActioned ? 'opacity-50' : 'hover:border-[var(--overlay-strong)]'}`}>
      {/* Header */}
      <div className="px-4 pt-3 pb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${cat.color} ${cat.bg}`}>
            {cat.label}
          </span>
          {isActioned && (
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
              rec.status === 'accepted' ? 'text-emerald-400 bg-emerald-500/10' : 'text-zinc-500 bg-zinc-500/10'
            }`}>
              {rec.status === 'accepted' ? 'Applied' : 'Dismissed'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-[var(--muted)]">
          <div className="w-1.5 h-1.5 rounded-full" style={{ background: `hsl(${Math.round(rec.confidence * 120)}, 70%, 50%)` }} />
          {Math.round(rec.confidence * 100)}%
        </div>
      </div>

      {/* Body */}
      <div className="px-4 pb-3">
        <p className="text-[13px] font-medium text-[var(--text)] truncate">{rec.monitorName}</p>
        <p className="text-[10px] text-[var(--text-faint)] font-mono truncate mt-0.5">{rec.targetFqn}</p>

        {/* Value change */}
        <div className="flex items-center gap-2 mt-3 px-3 py-2 rounded-md bg-[var(--overlay-bg)]">
          <span className="text-[11px] text-[var(--muted)] shrink-0">{fieldLabel}</span>
          <div className="flex items-center gap-1.5 ml-auto">
            <span className="text-[12px] text-[var(--text)] font-mono">{rec.currentValue}</span>
            <ArrowRight className="w-3 h-3 text-[var(--muted)]" />
            {editing ? (
              <input
                type="text"
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                className="w-16 px-1.5 py-0.5 text-[12px] font-mono rounded border border-[var(--accent)]/50 bg-[var(--surface)] text-[var(--accent)]"
                autoFocus
                onClick={e => e.stopPropagation()}
              />
            ) : (
              <span className="text-[12px] text-[var(--accent)] font-mono font-semibold">{rec.recommendedValue}</span>
            )}
            {isTightening
              ? <TrendingDown className="w-3 h-3 text-emerald-400" />
              : <TrendingUp className="w-3 h-3 text-amber-400" />
            }
          </div>
        </div>

        {/* Reasoning */}
        <p className="text-[11px] text-[var(--muted)] mt-2 leading-relaxed">
          {expanded ? rec.reasoning : rec.reasoning.slice(0, 100)}
          {rec.reasoning.length > 100 && !expanded && (
            <button onClick={(e) => { e.stopPropagation(); setExpanded(true); }} className="text-[var(--accent)] ml-1 hover:underline">
              more
            </button>
          )}
          {expanded && rec.reasoning.length > 100 && (
            <button onClick={(e) => { e.stopPropagation(); setExpanded(false); }} className="text-[var(--accent)] ml-1 hover:underline">
              less
            </button>
          )}
        </p>
      </div>

      {/* Actions */}
      {!isActioned && (
        <div className="flex items-center border-t border-[var(--subtle-border)] divide-x divide-[var(--subtle-border)]">
          {editing ? (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); onAccept(rec.id, editValue); setEditing(false); }}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium text-emerald-400 hover:bg-emerald-500/5 transition-colors"
              >
                <Check className="w-3 h-3" /> Apply
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setEditing(false); setEditValue(rec.recommendedValue); }}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium text-[var(--muted)] hover:bg-[var(--hover-bg)] transition-colors"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); onAccept(rec.id); }}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium text-emerald-400 hover:bg-emerald-500/5 transition-colors"
              >
                <Check className="w-3 h-3" /> Accept
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setEditing(true); }}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium text-[var(--muted)] hover:bg-[var(--hover-bg)] transition-colors"
              >
                <Pencil className="w-3 h-3" /> Edit
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDismiss(rec.id); }}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium text-[var(--muted)] hover:text-red-400 hover:bg-red-500/5 transition-colors"
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
