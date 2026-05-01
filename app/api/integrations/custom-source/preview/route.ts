import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';

/**
 * POST /api/integrations/custom-source/preview
 *
 * Probe-and-report proxy used by the Custom Source wizard's "Test fetch"
 * button. Forwards the candidate config to the FastAPI driver
 * test-connection endpoint and returns the result as-is.
 *
 * Body shape: { config: { base_url, auth, datasets } }
 *
 * Nothing is persisted here — the actual save happens after the wizard's
 * review step (Task 23).
 */
export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { ok: false, message: 'Invalid JSON body' },
      { status: 400 },
    );
  }

  try {
    const resp = await scannerClient.fetch(
      session,
      '/api/v1/drivers/CUSTOM_SOURCE/test-connection',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    );
    const data = await resp.json().catch(() => ({}));
    // Pass through the FastAPI status so the UI can surface non-2xx errors.
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        message:
          err instanceof Error ? err.message : 'Failed to reach scanner',
      },
      { status: 502 },
    );
  }
}
