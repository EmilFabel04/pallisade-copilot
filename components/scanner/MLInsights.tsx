'use client';

import React, { useState } from 'react';

interface Trend {
  direction: 'increasing' | 'decreasing' | 'stable';
  slopePerHour: number;
  confidence: number;
}

interface SeasonalPattern {
  type: 'hourly' | 'daily' | 'weekly';
  amplitude: number;
  pattern: Record<string, number>;
}

interface Baseline {
  mean: number;
  stdDev: number;
  bucketStats: Record<string, { mean: number; std: number }>;
}

interface MLInsightsProps {
  trend?: Trend;
  seasonality?: SeasonalPattern[];
  baseline?: Baseline;
  anomalyCount?: number;
  forecastAvailable?: boolean;
  className?: string;
}

export function MLInsights({
  trend,
  seasonality = [],
  baseline,
  anomalyCount = 0,
  forecastAvailable = false,
  className = '',
}: MLInsightsProps) {
  const [expanded, setExpanded] = useState(false);

  const trendIcon = {
    increasing: (
      <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
      </svg>
    ),
    decreasing: (
      <svg className="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
      </svg>
    ),
    stable: (
      <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14" />
      </svg>
    ),
  };

  const seasonalityIcons: Record<string, React.ReactNode> = {
    hourly: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    daily: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
      </svg>
    ),
    weekly: (
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    ),
  };

  return (
    <div className={`bg-[var(--card-bg)] rounded-lg border border-[var(--border-dim)] ${className}`}>
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-[var(--accent)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          <span className="text-sm font-medium text-white">ML Insights</span>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Quick stats */}
          {trend && (
            <div className="flex items-center gap-1 text-xs text-[var(--muted)]">
              {trendIcon[trend.direction]}
              <span className="capitalize">{trend.direction}</span>
            </div>
          )}
          {anomalyCount > 0 && (
            <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 text-xs rounded">
              {anomalyCount} anomalies
            </span>
          )}
          
          <svg 
            className={`w-4 h-4 text-[var(--muted)] transition-transform ${expanded ? 'rotate-180' : ''}`} 
            fill="none" 
            stroke="currentColor" 
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-4 pb-4 pt-2 border-t border-[var(--border-dim)] space-y-4">
          {/* Trend Analysis */}
          {trend && (
            <div>
              <h4 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider mb-2">Trend Analysis</h4>
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-black/20 rounded-lg p-3">
                  <div className="flex items-center gap-1.5 mb-1">
                    {trendIcon[trend.direction]}
                    <span className="text-xs text-[var(--muted)]">Direction</span>
                  </div>
                  <p className="text-sm font-medium text-white capitalize">{trend.direction}</p>
                </div>
                <div className="bg-black/20 rounded-lg p-3">
                  <p className="text-xs text-[var(--muted)] mb-1">Rate</p>
                  <p className="text-sm font-medium text-white">
                    {trend.slopePerHour > 0 ? '+' : ''}{trend.slopePerHour.toFixed(2)}/hr
                  </p>
                </div>
                <div className="bg-black/20 rounded-lg p-3">
                  <p className="text-xs text-[var(--muted)] mb-1">Confidence</p>
                  <p className="text-sm font-medium text-white">{(trend.confidence * 100).toFixed(0)}%</p>
                </div>
              </div>
            </div>
          )}

          {/* Seasonality */}
          {seasonality.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider mb-2">Seasonal Patterns</h4>
              <div className="space-y-2">
                {seasonality.map((pattern, i) => (
                  <div key={i} className="bg-black/20 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-1.5">
                        {seasonalityIcons[pattern.type]}
                        <span className="text-sm text-white capitalize">{pattern.type} Pattern</span>
                      </div>
                      <span className="text-xs text-[var(--muted)]">
                        {(pattern.amplitude * 100).toFixed(0)}% variation
                      </span>
                    </div>
                    {/* Mini pattern visualization */}
                    <div className="flex items-end gap-0.5 h-8">
                      {Object.entries(pattern.pattern).slice(0, 12).map(([key, value], j) => {
                        const maxVal = Math.max(...Object.values(pattern.pattern));
                        const minVal = Math.min(...Object.values(pattern.pattern));
                        const height = ((value - minVal) / (maxVal - minVal || 1)) * 100;
                        return (
                          <div
                            key={j}
                            className="flex-1 bg-[var(--accent)] rounded-t opacity-60"
                            style={{ height: `${Math.max(10, height)}%` }}
                            title={`${key}: ${value.toFixed(1)}`}
                          />
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Baseline Stats */}
          {baseline && (
            <div>
              <h4 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider mb-2">Learned Baseline</h4>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-black/20 rounded-lg p-3">
                  <p className="text-xs text-[var(--muted)] mb-1">Expected Value</p>
                  <p className="text-sm font-medium text-white">{baseline.mean.toFixed(1)} ± {baseline.stdDev.toFixed(1)}</p>
                </div>
                {baseline.bucketStats && Object.keys(baseline.bucketStats).length > 0 && (
                  <div className="bg-black/20 rounded-lg p-3">
                    <p className="text-xs text-[var(--muted)] mb-1">Time Buckets</p>
                    <div className="text-xs text-white space-y-0.5">
                      {Object.entries(baseline.bucketStats).slice(0, 3).map(([bucket, stats]) => (
                        <div key={bucket} className="flex justify-between">
                          <span className="text-[var(--muted)]">{bucket.replace('_', ' ')}:</span>
                          <span>{stats.mean.toFixed(0)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Capabilities indicator */}
          <div className="flex items-center gap-2 pt-2 border-t border-[var(--border-dim)]">
            <span className="text-xs text-[var(--muted)]">Capabilities:</span>
            <div className="flex gap-1.5">
              {trend && (
                <span className="px-1.5 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded">Trend</span>
              )}
              {seasonality.length > 0 && (
                <span className="px-1.5 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded">Seasonality</span>
              )}
              {baseline && (
                <span className="px-1.5 py-0.5 bg-green-500/20 text-green-400 text-xs rounded">Baseline</span>
              )}
              {forecastAvailable && (
                <span className="px-1.5 py-0.5 bg-amber-500/20 text-amber-400 text-xs rounded">Forecast</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

