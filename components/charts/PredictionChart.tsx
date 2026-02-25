'use client';

import { useState, useEffect } from 'react';

interface DataPoint {
  timestamp: string;
  actual?: number;
  predicted?: number;
  lowerBound?: number;
  upperBound?: number;
  isAnomaly?: boolean;
}

interface PredictionChartProps {
  data: DataPoint[];
  title?: string;
  metric?: string;
  height?: number;
  showConfidenceBands?: boolean;
  animated?: boolean;
}

export function PredictionChart({
  data,
  title = 'Metric Trend',
  metric = 'Value',
  height = 200,
  showConfidenceBands = true,
  animated = true,
}: PredictionChartProps) {
  const [mounted, setMounted] = useState(false);
  const [hoveredPoint, setHoveredPoint] = useState<number | null>(null);

  useEffect(() => {
    if (animated) {
      const timer = setTimeout(() => setMounted(true), 100);
      return () => clearTimeout(timer);
    }
    setMounted(true);
  }, [animated]);

  if (!data || data.length === 0) {
    return (
      <div className="bg-[var(--overlay-faint)] border border-[var(--subtle-border)] rounded-xl p-4">
        <div className="text-xs text-[var(--muted)] mb-2">{title}</div>
        <div className="h-32 flex items-center justify-center text-[var(--text-faint)] text-sm">
          No data available
        </div>
      </div>
    );
  }

  // Calculate bounds
  const allValues = data.flatMap(d => [d.actual, d.predicted, d.upperBound, d.lowerBound].filter(v => v !== undefined) as number[]);
  const minVal = Math.min(...allValues) * 0.9;
  const maxVal = Math.max(...allValues) * 1.1;
  const range = maxVal - minVal || 1;

  const getY = (val: number) => height - ((val - minVal) / range) * height;
  const getX = (idx: number) => (idx / (data.length - 1)) * 100;

  // Build paths
  const actualPath = data
    .map((d, i) => d.actual !== undefined ? `${i === 0 || data[i-1]?.actual === undefined ? 'M' : 'L'} ${getX(i)} ${getY(d.actual)}` : '')
    .filter(Boolean)
    .join(' ');

  const predictedPath = data
    .map((d, i) => d.predicted !== undefined ? `${i === 0 || data[i-1]?.predicted === undefined ? 'M' : 'L'} ${getX(i)} ${getY(d.predicted)}` : '')
    .filter(Boolean)
    .join(' ');

  // Confidence band path
  const confidencePath = showConfidenceBands ? data.reduce((acc, d, i) => {
    if (d.upperBound !== undefined && d.lowerBound !== undefined) {
      acc.upper.push(`${acc.upper.length === 0 ? 'M' : 'L'} ${getX(i)} ${getY(d.upperBound)}`);
      acc.lower.unshift(`L ${getX(i)} ${getY(d.lowerBound)}`);
    }
    return acc;
  }, { upper: [] as string[], lower: [] as string[] }) : null;

  const bandPath = confidencePath ? `${confidencePath.upper.join(' ')} ${confidencePath.lower.join(' ')} Z` : '';

  // Find anomalies
  const anomalies = data.map((d, i) => d.isAnomaly ? i : -1).filter(i => i >= 0);

  // Last actual vs predicted comparison
  const lastActual = [...data].reverse().find(d => d.actual !== undefined);
  const lastPredicted = [...data].reverse().find(d => d.predicted !== undefined);
  const deviation = lastActual && lastPredicted && lastPredicted.predicted 
    ? ((lastActual.actual! - lastPredicted.predicted) / lastPredicted.predicted * 100) 
    : null;

  return (
    <div className="bg-[var(--overlay-faint)] border border-[var(--subtle-border)] rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs text-[var(--muted)]">{title}</div>
        <div className="flex items-center gap-4 text-[10px]">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-0.5 bg-emerald-400 rounded" />
            <span className="text-[var(--muted)]">Actual</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-0.5 bg-blue-400 rounded" style={{ strokeDasharray: '4 2' }} />
            <span className="text-[var(--muted)]">Predicted</span>
          </div>
          {anomalies.length > 0 && (
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 bg-red-400 rounded-full" />
              <span className="text-[var(--muted)]">Anomaly</span>
            </div>
          )}
        </div>
      </div>

      {/* Stats Row */}
      {deviation !== null && (
        <div className="flex items-center gap-4 mb-3 text-xs">
          <div>
            <span className="text-[var(--muted)]">Actual vs Predicted: </span>
            <span className={`font-mono ${Math.abs(deviation) > 10 ? 'text-red-400' : Math.abs(deviation) > 5 ? 'text-amber-400' : 'text-emerald-400'}`}>
              {deviation > 0 ? '+' : ''}{deviation.toFixed(1)}%
            </span>
          </div>
          {anomalies.length > 0 && (
            <div>
              <span className="text-[var(--muted)]">Anomalies: </span>
              <span className="text-red-400 font-mono">{anomalies.length}</span>
            </div>
          )}
        </div>
      )}

      {/* Chart */}
      <div className="relative" style={{ height }}>
        <svg 
          className="w-full h-full" 
          viewBox={`0 0 100 ${height}`} 
          preserveAspectRatio="none"
        >
          {/* Confidence band */}
          {bandPath && (
            <path
              d={bandPath}
              fill="rgba(59, 130, 246, 0.1)"
              className={`transition-opacity duration-1000 ${mounted ? 'opacity-100' : 'opacity-0'}`}
            />
          )}

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map(ratio => (
            <line
              key={ratio}
              x1="0"
              y1={height * ratio}
              x2="100"
              y2={height * ratio}
              stroke="var(--subtle-border)"
              strokeWidth="0.5"
            />
          ))}

          {/* Predicted line */}
          {predictedPath && (
            <path
              d={predictedPath}
              fill="none"
              stroke="#3b82f6"
              strokeWidth="1.5"
              strokeDasharray="4 2"
              strokeLinecap="round"
              className={`transition-all duration-1000 ${mounted ? 'opacity-100' : 'opacity-0'}`}
              style={{
                strokeDashoffset: mounted ? 0 : 1000,
                transition: 'stroke-dashoffset 2s ease-out, opacity 0.5s'
              }}
            />
          )}

          {/* Actual line */}
          {actualPath && (
            <path
              d={actualPath}
              fill="none"
              stroke="#10b981"
              strokeWidth="2"
              strokeLinecap="round"
              className={`transition-all duration-1000 ${mounted ? 'opacity-100' : 'opacity-0'}`}
            />
          )}

          {/* Anomaly points */}
          {anomalies.map(idx => {
            const d = data[idx];
            if (d.actual === undefined) return null;
            return (
              <g key={idx}>
                <circle
                  cx={getX(idx)}
                  cy={getY(d.actual)}
                  r="4"
                  fill="#ef4444"
                  className="animate-pulse"
                />
                <circle
                  cx={getX(idx)}
                  cy={getY(d.actual)}
                  r="8"
                  fill="none"
                  stroke="#ef4444"
                  strokeWidth="1"
                  opacity="0.3"
                  className="animate-ping"
                />
              </g>
            );
          })}

          {/* Hover points */}
          {data.map((d, i) => (
            <g key={i}>
              <rect
                x={getX(i) - 3}
                y={0}
                width={6}
                height={height}
                fill="transparent"
                onMouseEnter={() => setHoveredPoint(i)}
                onMouseLeave={() => setHoveredPoint(null)}
                style={{ cursor: 'crosshair' }}
              />
              {hoveredPoint === i && (
                <>
                  <line
                    x1={getX(i)}
                    y1={0}
                    x2={getX(i)}
                    y2={height}
                    stroke="var(--text-faint)"
                    strokeWidth="0.5"
                    strokeDasharray="2 2"
                  />
                  {d.actual !== undefined && (
                    <circle cx={getX(i)} cy={getY(d.actual)} r="3" fill="#10b981" />
                  )}
                  {d.predicted !== undefined && (
                    <circle cx={getX(i)} cy={getY(d.predicted)} r="3" fill="#3b82f6" />
                  )}
                </>
              )}
            </g>
          ))}
        </svg>

        {/* Tooltip */}
        {hoveredPoint !== null && data[hoveredPoint] && (
          <div 
            className="absolute bg-[var(--surface)] border border-[var(--border-medium)] rounded-lg px-3 py-2 text-xs pointer-events-none z-10"
            style={{
              left: `${getX(hoveredPoint)}%`,
              top: '50%',
              transform: 'translate(-50%, -50%)'
            }}
          >
            <div className="text-[var(--muted)] mb-1">
              {new Date(data[hoveredPoint].timestamp).toLocaleString()}
            </div>
            {data[hoveredPoint].actual !== undefined && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-[var(--text-tertiary)]">Actual:</span>
                <span className="font-mono text-[var(--text)]">{data[hoveredPoint].actual!.toLocaleString()}</span>
              </div>
            )}
            {data[hoveredPoint].predicted !== undefined && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-blue-400" />
                <span className="text-[var(--text-tertiary)]">Predicted:</span>
                <span className="font-mono text-[var(--text)]">{data[hoveredPoint].predicted!.toLocaleString()}</span>
              </div>
            )}
            {data[hoveredPoint].isAnomaly && (
              <div className="text-red-400 mt-1">⚠ Anomaly detected</div>
            )}
          </div>
        )}

        {/* Y-axis labels */}
        <div className="absolute left-0 top-0 bottom-0 w-12 flex flex-col justify-between text-[9px] text-[var(--text-faint)] font-mono -ml-14">
          <span>{maxVal.toFixed(0)}</span>
          <span>{((maxVal + minVal) / 2).toFixed(0)}</span>
          <span>{minVal.toFixed(0)}</span>
        </div>
      </div>

      {/* X-axis labels */}
      <div className="flex justify-between mt-2 text-[9px] text-[var(--text-faint)] font-mono">
        <span>{new Date(data[0].timestamp).toLocaleDateString()}</span>
        <span>{new Date(data[data.length - 1].timestamp).toLocaleDateString()}</span>
      </div>
    </div>
  );
}
