import { NextRequest } from 'next/server';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';

export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return new Response('Unauthorized', { status: 401 });
  }

  const body = await req.text();

  // scannerClient.fetch returns the raw fetch Response without consuming the body,
  // so the ReadableStream flows through unmolested — perfect for SSE pass-through.
  const upstream = await scannerClient.fetch(
    session,
    '/api/v1/integrations/source/verify',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    },
  );

  if (!upstream.ok && upstream.status !== 200) {
    // Non-streaming error from the upstream (e.g. 422 validation error).
    return new Response(await upstream.text(), { status: upstream.status });
  }

  // Pass the SSE stream body straight through to the browser.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  });
}
