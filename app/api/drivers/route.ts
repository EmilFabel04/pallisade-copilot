import { NextResponse } from 'next/server';

const SCANNER_URL = process.env.SCANNER_URL || 'http://localhost:8000';

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const layer = searchParams.get('layer') || '';
  const graphDomain = searchParams.get('graphDomain') || '';

  const params = new URLSearchParams();
  if (layer) params.set('layer', layer);
  if (graphDomain) params.set('graph_domain', graphDomain);

  const qs = params.toString();
  const url = `${SCANNER_URL}/api/v1/drivers${qs ? `?${qs}` : ''}`;

  try {
    const resp = await fetch(url, { cache: 'no-store' });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch {
    return NextResponse.json(
      { error: 'Failed to fetch drivers from scanner' },
      { status: 502 },
    );
  }
}
