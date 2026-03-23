import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';

const SCANNER_URL = process.env.SCANNER_URL || 'http://localhost:8000';

// POST /api/schedule/presets/preview - Preview preset watch generation
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { presetKey, anchorNodeId, stackId, existingFqns, mode } = body;

    if (!presetKey && mode !== 'smart_build') {
      return NextResponse.json({ error: 'presetKey is required' }, { status: 400 });
    }
    if (!anchorNodeId) {
      return NextResponse.json({ error: 'anchorNodeId is required' }, { status: 400 });
    }

    const endpoint = mode === 'smart_build'
      ? '/api/v1/monitors/presets/smart-build'
      : '/api/v1/monitors/presets/preview';

    const qs = stackId ? `?stack_id=${encodeURIComponent(stackId)}` : '';

    const res = await fetch(`${SCANNER_URL}${endpoint}${qs}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        preset_key: presetKey,
        anchor_node_id: anchorNodeId,
        existing_fqns: existingFqns || [],
      }),
    });

    if (!res.ok) {
      const err = await res.text();
      console.error('[Presets] Preview error from FastAPI:', err);
      return NextResponse.json(
        { error: `Preview failed: ${res.status}` },
        { status: res.status },
      );
    }

    const raw = await res.json();

    // Transform snake_case response to camelCase for frontend types
    const data = {
      presetKey: raw.preset_key,
      watches: (raw.watches || []).map((w: any) => ({
        watchType: w.watch_type,
        anchorNodeId: w.anchor_node_id,
        anchorName: w.anchor_name,
        anchorFqn: w.anchor_fqn,
        anchorNodeType: w.anchor_node_type,
        anchorPlatform: w.anchor_platform,
        scopeResult: w.scope_result,  // inner fields stay snake_case (frontend reads them as-is)
        monitorCount: w.monitor_count,
        coveragePct: w.coverage_pct,
      })),
      totalMonitors: raw.total_monitors,
      totalNodes: raw.total_nodes,
      deduplicatedCount: raw.deduplicated_count,
      warnings: raw.warnings || [],
    };

    return NextResponse.json(data);
  } catch (error: any) {
    console.error('[Presets] Preview error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
