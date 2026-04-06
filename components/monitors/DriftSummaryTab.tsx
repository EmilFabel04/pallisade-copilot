'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Play, BarChart3 } from 'lucide-react';
import { toast } from 'sonner';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';

const CATEGORIES = ['freshness', 'volume', 'quality', 'schema', 'anomaly', 'uniqueness'];
const SEVERITIES = ['low', 'medium', 'high'];

export function DriftSummaryTab() {
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});

  const [categoryFilter, setCategoryFilter] = useState<Set<string>>(new Set());
  const [severityFilter, setSeverityFilter] = useState<Set<string>>(new Set());
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
        toast.success(`Analysis complete — ${data.recommendationCount} recommendations`);
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
      toast.success('Recommendation accepted');
      fetchRecommendations();
    } else {
      toast.error('Failed to accept');
    }
  };

  const handleDismiss = async (id: string) => {
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'dismiss' }),
    });
    if (res.ok) {
      toast.success('Recommendation dismissed');
      fetchRecommendations();
    } else {
      toast.error('Failed to dismiss');
    }
  };

  const toggleFilter = (set: Set<string>, setter: (s: Set<string>) => void, value: string) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setter(next);
  };

  const filtered = useMemo(() => {
    let result = recommendations;
    if (categoryFilter.size > 0) {
      result = result.filter(r => categoryFilter.has(r.driftCategory));
    }
    if (severityFilter.size > 0) {
      result = result.filter(r => severityFilter.has(r.severity));
    }
    return result;
  }, [recommendations, categoryFilter, severityFilter]);

  return (
    <div className="space-y-5">
      {/* Stats Banner */}
      <div className="flex items-center justify-between p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-[var(--accent)]" />
            <span className="text-[13px] font-medium text-[var(--text)]">Drift Analysis</span>
          </div>
          {lastAnalyzedAt && (
            <span className="text-[11px] text-[var(--muted)]">
              Last analyzed: {new Date(lastAnalyzedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            </span>
          )}
          <div className="flex items-center gap-3 text-[11px]">
            <span className="text-amber-400">{counts.pending || 0} pending</span>
            <span className="text-emerald-400">{counts.accepted || 0} accepted</span>
            <span className="text-zinc-400">{counts.dismissed || 0} dismissed</span>
          </div>
        </div>
        <button
          onClick={handleRunAnalysis}
          disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          {running ? 'Analyzing...' : 'Run Analysis'}
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1">
          {CATEGORIES.map(cat => (
            <button
              key={cat}
              onClick={() => toggleFilter(categoryFilter, setCategoryFilter, cat)}
              className={`px-2 py-1 text-[11px] rounded-md font-medium transition-colors ${
                categoryFilter.has(cat) ? 'bg-[var(--accent)]/15 text-[var(--accent)]' : 'text-[var(--muted)] hover:text-[var(--text)]'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
        <div className="w-px h-4 bg-[var(--subtle-border)]" />
        <div className="flex items-center gap-1">
          {SEVERITIES.map(sev => (
            <button
              key={sev}
              onClick={() => toggleFilter(severityFilter, setSeverityFilter, sev)}
              className={`px-2 py-1 text-[11px] rounded-md font-medium transition-colors ${
                severityFilter.has(sev) ? 'bg-[var(--accent)]/15 text-[var(--accent)]' : 'text-[var(--muted)] hover:text-[var(--text)]'
              }`}
            >
              {sev}
            </button>
          ))}
        </div>
        <div className="w-px h-4 bg-[var(--subtle-border)]" />
        <div className="flex items-center gap-1">
          {['pending', 'accepted', 'dismissed'].map(s => (
            <button
              key={s}
              onClick={() => setStatusFilter(statusFilter === s ? '' : s)}
              className={`px-2 py-1 text-[11px] rounded-md font-medium transition-colors ${
                statusFilter === s ? 'bg-[var(--accent)]/15 text-[var(--accent)]' : 'text-[var(--muted)] hover:text-[var(--text)]'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Recommendations */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-[var(--muted)] text-[13px]">
            {recommendations.length === 0
              ? 'No drift analysis results yet. Click "Run Analysis" to get started.'
              : 'No recommendations match your filters.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(rec => (
            <DriftRecommendationCard
              key={rec.id}
              rec={rec}
              onAccept={handleAccept}
              onDismiss={handleDismiss}
            />
          ))}
        </div>
      )}
    </div>
  );
}
