import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';

const SCANNER_URL = process.env.SCANNER_URL || 'http://localhost:8000';

// POST /api/schedule/plans/preview - Preview a monitoring plan
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const {
      scopeType,
      scopeConfig,
      mode,
      families,
      manualSelections,
      existingFqns,
      stackId,
    } = body;

    if (!scopeType) {
      return NextResponse.json({ error: 'scopeType is required' }, { status: 400 });
    }
    if (!mode) {
      return NextResponse.json({ error: 'mode is required' }, { status: 400 });
    }

    const qs = stackId ? `?stack_id=${encodeURIComponent(stackId)}` : '';

    const res = await fetch(
      `${SCANNER_URL}/api/v1/monitors/plans/preview${qs}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope_type: scopeType,
          scope_config: scopeConfig || {},
          mode,
          families: families || [],
          manual_selections: manualSelections || {},
          existing_fqns: existingFqns || [],
        }),
      },
    );

    if (!res.ok) {
      const err = await res.text();
      console.error('[Plans] Preview error from FastAPI:', err);
      return NextResponse.json(
        { error: `Preview failed: ${res.status}` },
        { status: res.status },
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error('[Plans] Preview error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
