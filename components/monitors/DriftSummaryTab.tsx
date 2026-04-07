'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Play, Activity, AlertTriangle, CheckCircle, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';

const CATEGORIES = [
  { key: 'freshness', label: 'Freshness', color: 'text-blue-400' },
  { key: 'volume', label: 'Volume', color: 'text-purple-400' },
  { key: 'quality', label: 'Quality', color: 'text-amber-400' },
  { key: 'schema', label: 'Schema', color: 'text-orange-400' },
  { key: 'anomaly', label: 'Anomaly', color: 'text-red-400' },
  { key: 'uniqueness', label: 'Uniqueness', color: 'text-cyan-400' },
];

export function DriftSummaryTab() {
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});

  const [categoryFilter, setCategoryFilter] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<string>('pending');

  const fetchRecommendations = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      const res = await fetch(`/api/drift?${params}`);
      if (res.ok) {
        const data = await res.json();
        setRecommendations(data.recommendations || []);
        setLastAnalyzedAt(data.lastAnalyzedAt);
        setCounts(data.counts || {});
      }
    } catch (err) {
      console.error('[DriftSummary] Fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { fetchRecommendations(); }, [fetchRecommendations]);

  const handleRunAnalysis = async () => {
    setRunning(true);
    try {
      const res = await fetch('/api/drift/run', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        toast.success(`Analysis complete — ${data.recommendationCount} recommendation${data.recommendationCount !== 1 ? 's' : ''}`);
        fetchRecommendations();
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || 'Analysis failed');
      }
    } catch {
      toast.error('Failed to run analysis');
    } finally {
      setRunning(false);
    }
  };

  const handleAccept = async (id: string, value?: string) => {
    const action = value ? 'accept_with_value' : 'accept';
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, value }),
    });
    if (res.ok) {
      toast.success('Recommendation applied');
      fetchRecommendations();
    } else {
      toast.error('Failed to apply');
    }
  };

  const handleDismiss = async (id: string) => {
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'dismiss' }),
    });
    if (res.ok) {
      fetchRecommendations();
    } else {
      toast.error('Failed to dismiss');
    }
  };

  const toggleCategory = (key: string) => {
    setCategoryFilter(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const filtered = useMemo(() => {
    let result = recommendations;
    if (categoryFilter.size > 0) {
      result = result.filter(r => categoryFilter.has(r.driftCategory));
    }
    return result;
  }, [recommendations, categoryFilter]);

  // Group by severity for display
  const highCount = filtered.filter(r => r.severity === 'high').length;
  const mediumCount = filtered.filter(r => r.severity === 'medium').length;
  const lowCount = filtered.filter(r => r.severity === 'low').length;

  const pending = counts.pending || 0;
  const accepted = counts.accepted || 0;
  const dismissed = counts.dismissed || 0;

  return (
    <div className="space-y-5">
      {/* Overview cards */}
      <div className="grid grid-cols-4 gap-3">
        <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)]">
          <div className="flex items-center gap-2 mb-1">
            <Activity className="w-3.5 h-3.5 text-[var(--accent)]" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Last Analysis</span>
          </div>
          <p className="text-[13px] font-medium text-[var(--text)]">
            {lastAnalyzedAt
              ? new Date(lastAnalyzedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
              : 'Never'}
          </p>
        </div>
        <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)]">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Pending</span>
          </div>
          <p className="text-[13px] font-medium text-[var(--text)]">{pending}</p>
        </div>
        <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)]">
          <div className="flex items-center gap-2 mb-1">
            <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Applied</span>
          </div>
          <p className="text-[13px] font-medium text-[var(--text)]">{accepted}</p>
        </div>
        <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)]">
          <div className="flex items-center gap-2 mb-1">
            <XCircle className="w-3.5 h-3.5 text-zinc-400" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Dismissed</span>
          </div>
          <p className="text-[13px] font-medium text-[var(--text)]">{dismissed}</p>
        </div>
      </div>

      {/* Toolbar: filters + run button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {/* Status tabs */}
          <div className="flex items-center bg-[var(--overlay-bg)] rounded-lg p-0.5">
            {[
              { key: 'pending', label: 'Pending' },
              { key: 'accepted', label: 'Applied' },
              { key: 'dismissed', label: 'Dismissed' },
              { key: '', label: 'All' },
            ].map(s => (
              <button
                key={s.key}
                onClick={() => setStatusFilter(s.key)}
                className={cn(
                  'px-3 py-1 text-[11px] font-medium rounded-md transition-colors',
                  statusFilter === s.key
                    ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm'
                    : 'text-[var(--muted)] hover:text-[var(--text)]'
                )}
              >
                {s.label}
              </button>
            ))}
          </div>

          {/* Category filters */}
          <div className="w-px h-5 bg-[var(--subtle-border)] mx-1" />
          <div className="flex items-center gap-0.5">
            {CATEGORIES.map(cat => (
              <button
                key={cat.key}
                onClick={() => toggleCategory(cat.key)}
                className={cn(
                  'px-2 py-1 text-[10px] font-medium rounded-md transition-colors',
                  categoryFilter.has(cat.key)
                    ? `${cat.color} bg-[var(--surface)] shadow-sm`
                    : 'text-[var(--muted)] hover:text-[var(--text)]'
                )}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={handleRunAnalysis}
          disabled={running}
          className="flex items-center gap-1.5 px-4 py-1.5 text-[11px] font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          {running ? 'Analyzing...' : 'Run Analysis'}
        </button>
      </div>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Activity className="w-10 h-10 text-[var(--text-faint)] mb-3" />
          <p className="text-[13px] text-[var(--muted)]">
            {recommendations.length === 0
              ? 'No drift analysis results yet. Run an analysis to detect SLA drift.'
              : 'No recommendations match your filters.'}
          </p>
          {recommendations.length === 0 && (
            <button
              onClick={handleRunAnalysis}
              disabled={running}
              className="mt-3 px-4 py-1.5 text-[11px] font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {running ? 'Analyzing...' : 'Run First Analysis'}
            </button>
          )}
        </div>
      ) : (
        <div>
          {/* Severity summary */}
          {(highCount > 0 || mediumCount > 0) && (
            <div className="flex items-center gap-3 mb-4 text-[11px]">
              {highCount > 0 && <span className="text-red-400 font-medium">{highCount} high severity</span>}
              {mediumCount > 0 && <span className="text-amber-400 font-medium">{mediumCount} medium</span>}
              {lowCount > 0 && <span className="text-zinc-400">{lowCount} low</span>}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {filtered.map(rec => (
              <DriftRecommendationCard
                key={rec.id}
                rec={rec}
                onAccept={handleAccept}
                onDismiss={handleDismiss}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
