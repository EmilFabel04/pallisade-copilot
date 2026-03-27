'use client';

import React from 'react';
import { X, Clock, Shield } from 'lucide-react';

const TIER_STYLES: Record<string, { color: string; bg: string }> = {
  T0: { color: 'text-red-400', bg: 'bg-red-500/15' },
  T1: { color: 'text-amber-400', bg: 'bg-amber-500/15' },
  T2: { color: 'text-blue-400', bg: 'bg-blue-500/15' },
  T3: { color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

const STATUS_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  active: { color: 'text-emerald-400', bg: 'bg-emerald-500/15', label: 'Active' },
  inactive: { color: 'text-zinc-400', bg: 'bg-zinc-500/15', label: 'Inactive' },
  archived: { color: 'text-amber-400', bg: 'bg-amber-500/15', label: 'Archived' },
};

interface SLAField {
  label: string;
  value: string | number | boolean | null | undefined;
}

interface SLAViewDrawerProps {
  title: string;
  subtitle?: string;
  slaTier?: string | null;
  status: string;
  fields: SLAField[];
  nodes?: string[];
  notes?: string | null;
  updatedAt?: string;
  onClose: () => void;
  onEdit?: () => void;
}

export function SLAViewDrawer({
  title,
  subtitle,
  slaTier,
  status,
  fields,
  nodes,
  notes,
  updatedAt,
  onClose,
  onEdit,
}: SLAViewDrawerProps) {
  const tierStyle = TIER_STYLES[(slaTier || '').toUpperCase()] || TIER_STYLES.T2;
  const statusStyle = STATUS_STYLES[status] || STATUS_STYLES.active;

  return (
    <div className="fixed inset-x-0 top-14 bottom-0 z-40 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative w-full max-w-lg bg-[var(--surface-sunken)] border-l border-[var(--subtle-border)] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="p-5 border-b border-[var(--subtle-border)] flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-[var(--accent)]/15 flex items-center justify-center">
                <Shield className="w-4.5 h-4.5 text-[var(--accent)]" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-[var(--foreground)]">{title}</h2>
                {subtitle && <p className="text-[11px] text-[var(--muted)] mt-0.5">{subtitle}</p>}
              </div>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-[var(--subtle-bg)] rounded transition-colors">
              <X className="w-4 h-4 text-[var(--muted)]" />
            </button>
          </div>
          <div className="flex gap-2 mt-3">
            {slaTier && (
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${tierStyle.color} ${tierStyle.bg}`}>
                {slaTier.toUpperCase()}
              </span>
            )}
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${statusStyle.color} ${statusStyle.bg}`}>
              {statusStyle.label}
            </span>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* SLA Expectations */}
          {fields.length > 0 && (
            <div>
              <h3 className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-3">Expectations</h3>
              <div className="space-y-2">
                {fields.map((f) => (
                  <div key={f.label} className="flex items-center justify-between py-2 px-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <span className="text-[12px] text-[var(--muted)]">{f.label}</span>
                    <span className="text-[12px] font-medium text-[var(--text)]">
                      {f.value != null ? String(f.value) : '\u2014'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Covered Nodes */}
          {nodes && nodes.length > 0 && (
            <div>
              <h3 className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-3">
                Covered Nodes ({nodes.length})
              </h3>
              <div className="space-y-1">
                {nodes.slice(0, 10).map((fqn) => (
                  <div key={fqn} className="text-[11px] text-[var(--text-tertiary)] font-mono truncate py-1 px-2 rounded bg-[var(--overlay-bg)]">
                    {fqn}
                  </div>
                ))}
                {nodes.length > 10 && (
                  <p className="text-[10px] text-[var(--muted)] pl-2">+{nodes.length - 10} more</p>
                )}
              </div>
            </div>
          )}

          {/* Notes */}
          {notes && (
            <div>
              <h3 className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-2">Notes</h3>
              <p className="text-[12px] text-[var(--text-tertiary)] whitespace-pre-wrap">{notes}</p>
            </div>
          )}

          {/* Updated timestamp */}
          {updatedAt && (
            <div className="flex items-center gap-1 text-[11px] text-[var(--muted)]">
              <Clock className="w-3 h-3" />
              Updated {new Date(updatedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            </div>
          )}
        </div>

        {/* Footer */}
        {onEdit && (
          <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0">
            <button
              onClick={onEdit}
              className="w-full px-4 py-2 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity"
            >
              Edit SLA
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
