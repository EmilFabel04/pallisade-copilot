'use client';

import { useMemo } from 'react';

interface DataPoint {
  date: string;
  value: number;
  label?: string;
}

interface TrendChartProps {
  data: DataPoint[];
  title?: string;
  height?: number;
  color?: string;
  showArea?: boolean;
  valueFormatter?: (value: number) => string;
}

export function TrendChart({
  data,
  title,
  height = 80,
  color = '#10b981',
  showArea = true,
  valueFormatter = (v) => v.toString(),
}: TrendChartProps) {
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return null;
    
    const values = data.map(d => d.value);
    const min = Math.min(...values) * 0.9;
    const max = Math.max(...values) * 1.1;
    const range = max - min || 1;
    
    const points = data.map((d, i) => ({
      x: (i / Math.max(data.length - 1, 1)) * 100,
      y: height - ((d.value - min) / range) * height,
      ...d,
    }));
    
    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
    const areaPath = `${linePath} L ${points[points.length - 1].x} ${height} L 0 ${height} Z`;
    
    return { points, linePath, areaPath, min, max };
  }, [data, height]);

  if (!chartData || data.length === 0) {
    return (
      <div className="flex items-center justify-center text-[var(--text-faint)] text-xs" style={{ height }}>
        No historical data
      </div>
    );
  }

  const latest = data[data.length - 1];
  const previous = data.length > 1 ? data[data.length - 2] : null;
  const change = previous ? ((latest.value - previous.value) / previous.value) * 100 : null;

  return (
    <div>
      {title && (
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-[var(--muted)]">{title}</span>
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono font-medium">{valueFormatter(latest.value)}</span>
            {change !== null && (
              <span className={`text-xs ${change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {change >= 0 ? '↑' : '↓'} {Math.abs(change).toFixed(1)}%
              </span>
            )}
          </div>
        </div>
      )}
      <svg viewBox={`0 0 100 ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
        {showArea && (
          <path d={chartData.areaPath} fill={`${color}15`} />
        )}
        <path d={chartData.linePath} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        {chartData.points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="3" fill={color} className="opacity-0 hover:opacity-100 transition-opacity" />
        ))}
      </svg>
      <div className="flex justify-between mt-1 text-[10px] text-[var(--text-faint)] font-mono">
        <span>{data[0]?.label || new Date(data[0]?.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
        <span>{latest?.label || new Date(latest?.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
      </div>
    </div>
  );
}

// Mini sparkline version
export function Sparkline({ data, color = '#10b981', height = 24 }: { data: number[]; color?: string; height?: number }) {
  if (!data || data.length < 2) return null;
  
  const min = Math.min(...data) * 0.9;
  const max = Math.max(...data) * 1.1;
  const range = max - min || 1;
  
  const points = data.map((v, i) => ({
    x: (i / (data.length - 1)) * 100,
    y: height - ((v - min) / range) * height,
  }));
  
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  
  return (
    <svg viewBox={`0 0 100 ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
