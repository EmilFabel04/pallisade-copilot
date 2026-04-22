import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ type: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { type } = await params;
  try {
    const resp = await scannerClient.fetch(session, `/api/v1/drivers/${type}`, { cache: 'no-store' });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch {
    return NextResponse.json(
      { error: `Failed to fetch driver ${type}` },
      { status: 502 },
    );
  }
}
