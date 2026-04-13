'use client';

interface SparklineChartProps {
  values: (number | null)[];
  color: string;
  threshold?: number;
  width?: number;
  height?: number;
}

export function SparklineChart({
  values,
  color,
  threshold,
  width = 200,
  height = 40,
}: SparklineChartProps) {
  const points = values.map((v, i) => ({ x: i, value: v }));
  const validPoints = points.filter((p): p is { x: number; value: number } => p.value !== null);

  if (validPoints.length < 2) {
    return (
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height }}>
        <text x={width / 2} y={height / 2} textAnchor="middle" fill="var(--muted)" fontSize={10}>
          Not enough data
        </text>
      </svg>
    );
  }

  const minVal = Math.min(...validPoints.map((p) => p.value));
  const maxVal = Math.max(...validPoints.map((p) => p.value));
  const range = maxVal - minVal || 1;
  const padding = 4;
  const plotHeight = height - padding * 2;
  const plotWidth = width - padding * 2;

  const scaleX = (i: number) => padding + (i / (values.length - 1)) * plotWidth;
  const scaleY = (v: number) => padding + plotHeight - ((v - minVal) / range) * plotHeight;

  const polylinePoints = validPoints
    .map((p) => `${scaleX(p.x)},${scaleY(p.value)}`)
    .join(' ');

  const lastPoint = validPoints[validPoints.length - 1];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height }}>
      {threshold !== undefined && threshold >= minVal && threshold <= maxVal && (
        <line
          x1={padding}
          y1={scaleY(threshold)}
          x2={width - padding}
          y2={scaleY(threshold)}
          stroke={color}
          strokeOpacity={0.25}
          strokeWidth={1}
          strokeDasharray="4,3"
        />
      )}
      <polyline
        points={polylinePoints}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={scaleX(lastPoint.x)}
        cy={scaleY(lastPoint.value)}
        r={3}
        fill={color}
      />
    </svg>
  );
}
