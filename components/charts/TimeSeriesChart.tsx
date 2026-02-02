'use client';

import { useMemo } from 'react';

interface DataPoint {
  timestamp: string;
  value: number;
  predicted?: number;
  lowerBound?: number;
  upperBound?: number;
  isAnomaly?: boolean;
}

interface TimeSeriesChartProps {
  data: DataPoint[];
  title?: string;
  yAxisLabel?: string;
  showForecast?: boolean;
  height?: number;
}

export function TimeSeriesChart({ 
  data, 
  title,
  yAxisLabel = 'Value',
  showForecast = true,
  height = 200 
}: TimeSeriesChartProps) {
  const { minValue, maxValue, points, width } = useMemo(() => {
    if (!data || data.length === 0) {
      return { minValue: 0, maxValue: 100, points: [], width: 100 };
    }

    const allValues = data.flatMap(d => [
      d.value,
      d.predicted,
      d.lowerBound,
      d.upperBound
    ].filter(v => v !== undefined)) as number[];

    const min = Math.min(...allValues);
    const max = Math.max(...allValues);
    const padding = (max - min) * 0.1 || 10;

    return {
      minValue: min - padding,
      maxValue: max + padding,
      points: data,
      width: Math.max(data.length * 4, 100)
    };
  }, [data]);

  const getY = (value: number) => {
    const range = maxValue - minValue;
    return height - ((value - minValue) / range) * (height - 40) - 20;
  };

  const getX = (index: number) => {
    return (index / (points.length - 1)) * (width - 60) + 40;
  };

  // Build path for actual values
  const actualPath = points
    .filter(p => p.value !== undefined)
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(points.indexOf(p))} ${getY(p.value)}`)
    .join(' ');

  // Build path for predicted values
  const predictedPath = showForecast 
    ? points
        .filter(p => p.predicted !== undefined)
        .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(points.indexOf(p))} ${getY(p.predicted!)}`)
        .join(' ')
    : '';

  // Build confidence interval area
  const confidenceArea = showForecast && points.some(p => p.lowerBound !== undefined)
    ? (() => {
        const forecastPoints = points.filter(p => p.lowerBound !== undefined && p.upperBound !== undefined);
        if (forecastPoints.length === 0) return '';
        
        const upperPath = forecastPoints
          .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(points.indexOf(p))} ${getY(p.upperBound!)}`)
          .join(' ');
        
        const lowerPath = [...forecastPoints]
          .reverse()
          .map((p) => `L ${getX(points.indexOf(p))} ${getY(p.lowerBound!)}`)
          .join(' ');
        
        return `${upperPath} ${lowerPath} Z`;
      })()
    : '';

  // Find anomalies
  const anomalies = points.filter(p => p.isAnomaly);

  if (!data || data.length === 0) {
    return (
      <div className="bg-[var(--card-bg)] rounded-lg border border-[var(--border-dim)] p-4">
        <p className="text-[var(--muted)] text-sm text-center">No data available</p>
      </div>
    );
  }

  return (
    <div className="bg-[var(--card-bg)] rounded-lg border border-[var(--border-dim)] p-4">
      {title && (
        <h3 className="text-sm font-medium text-white mb-3">{title}</h3>
      )}
      
      <div className="overflow-x-auto">
        <svg 
          width={width} 
          height={height} 
          className="min-w-full"
          viewBox={`0 0 ${width} ${height}`}
        >
          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const y = 20 + ratio * (height - 40);
            const value = maxValue - ratio * (maxValue - minValue);
            return (
              <g key={ratio}>
                <line
                  x1={40}
                  y1={y}
                  x2={width - 20}
                  y2={y}
                  stroke="var(--border-dim)"
                  strokeDasharray="4 4"
                  strokeWidth={0.5}
                />
                <text
                  x={35}
                  y={y + 4}
                  textAnchor="end"
                  fill="var(--muted)"
                  fontSize={10}
                >
                  {value.toFixed(0)}
                </text>
              </g>
            );
          })}

          {/* Confidence interval area */}
          {confidenceArea && (
            <path
              d={confidenceArea}
              fill="var(--accent)"
              fillOpacity={0.1}
            />
          )}

          {/* Actual values line */}
          <path
            d={actualPath}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={2}
          />

          {/* Predicted values line */}
          {predictedPath && (
            <path
              d={predictedPath}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2}
              strokeDasharray="6 4"
              opacity={0.7}
            />
          )}

          {/* Data points */}
          {points.map((point, i) => (
            <circle
              key={i}
              cx={getX(i)}
              cy={getY(point.value)}
              r={point.isAnomaly ? 5 : 3}
              fill={point.isAnomaly ? '#ef4444' : 'var(--accent)'}
              stroke={point.isAnomaly ? '#ef4444' : 'var(--card-bg)'}
              strokeWidth={point.isAnomaly ? 2 : 1}
            />
          ))}

          {/* Anomaly markers */}
          {anomalies.map((point, i) => {
            const idx = points.indexOf(point);
            return (
              <g key={`anomaly-${i}`}>
                <text
                  x={getX(idx)}
                  y={getY(point.value) - 12}
                  textAnchor="middle"
                  fill="#ef4444"
                  fontSize={10}
                  fontWeight="bold"
                >
                  !
                </text>
              </g>
            );
          })}

          {/* Y-axis label */}
          <text
            x={15}
            y={height / 2}
            textAnchor="middle"
            fill="var(--muted)"
            fontSize={10}
            transform={`rotate(-90, 15, ${height / 2})`}
          >
            {yAxisLabel}
          </text>
        </svg>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 text-xs text-[var(--muted)]">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-0.5 bg-[var(--accent)]" />
          <span>Actual</span>
        </div>
        {showForecast && predictedPath && (
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-0.5 bg-[var(--accent)] opacity-70" style={{ borderStyle: 'dashed' }} />
            <span>Forecast</span>
          </div>
        )}
        {anomalies.length > 0 && (
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-red-500" />
            <span>Anomaly ({anomalies.length})</span>
          </div>
        )}
      </div>
    </div>
  );
}

