'use client';

import { useState, useEffect } from 'react';
import { MLInsights } from '@/components/scanner';

interface MLInsightsData {
  trend?: {
    direction: 'increasing' | 'decreasing' | 'stable';
    slopePerHour: number;
    confidence: number;
  };
  seasonality?: Array<{
    type: 'hourly' | 'daily' | 'weekly';
    amplitude: number;
    pattern: Record<string, number>;
  }>;
  baseline?: {
    mean: number;
    stdDev: number;
    bucketStats: Record<string, { mean: number; std: number }>;
  };
  anomalyCount?: number;
}

interface Props {
  metricKey?: string;
  reportId?: string;
}

export function MLInsightsClient({ metricKey, reportId }: Props) {
  const [data, setData] = useState<MLInsightsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchInsights() {
      try {
        // Try to fetch from baselines API
        if (metricKey) {
          const response = await fetch(`/api/baselines?metricKey=${metricKey}`);
          if (response.ok) {
            const result = await response.json();
            if (result && result.length > 0) {
              const baseline = result[0];
              setData({
                trend: {
                  direction: baseline.trendDirection || 'stable',
                  slopePerHour: baseline.trendSlope || 0,
                  confidence: Math.min(1, (baseline.sampleCount || 0) / 100),
                },
                baseline: {
                  mean: baseline.mean || 0,
                  stdDev: baseline.stdDev || 0,
                  bucketStats: {},
                },
                anomalyCount: 0,
              });
            }
          }
        }
      } catch (error) {
        console.error('Failed to fetch ML insights:', error);
      } finally {
        setLoading(false);
      }
    }

    fetchInsights();
  }, [metricKey, reportId]);

  if (loading || !data) {
    return null;
  }

  return (
    <MLInsights
      trend={data.trend}
      seasonality={data.seasonality}
      baseline={data.baseline}
      anomalyCount={data.anomalyCount}
      forecastAvailable={!!data.trend}
    />
  );
}

