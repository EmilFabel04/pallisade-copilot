import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';

export async function GET(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const layer = searchParams.get('layer') || '';
  const graphDomain = searchParams.get('graphDomain') || '';

  const params = new URLSearchParams();
  if (layer) params.set('layer', layer);
  if (graphDomain) params.set('graph_domain', graphDomain);

  const qs = params.toString();
  const path = `/api/v1/drivers${qs ? `?${qs}` : ''}`;

  try {
    const resp = await scannerClient.fetch(session, path, { cache: 'no-store' });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch {
    return NextResponse.json(
      { error: 'Failed to fetch drivers from scanner' },
      { status: 502 },
    );
  }
}
