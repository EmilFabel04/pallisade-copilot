import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import type { PresetDefinition, PresetKey } from '@/types/health-watch';

/**
 * Static preset definitions returned directly without hitting FastAPI.
 * The FastAPI endpoint is used for preview/apply which need the lineage graph.
 */
const PRESETS: PresetDefinition[] = [
  {
    key: 'pipeline_health',
    label: 'Pipeline Health',
    description: 'Protect a warehouse table and its upstream pipeline with freshness, volume, and schema checks.',
    eligible: true,
    eligibleDomains: ['warehouse'],
    estimatedWatches: '1',
    estimatedMonitors: '8-12',
  },
  {
    key: 'data_drift',
    label: 'Data Drift',
    description: 'Detect schema changes, volume anomalies, and quality drift across pipeline assets.',
    eligible: true,
    eligibleDomains: ['warehouse', 'transform'],
    estimatedWatches: '1',
    estimatedMonitors: '6-10',
  },
  {
    key: 'ingestion_watch',
    label: 'Ingestion Watch',
    description: 'Protect all ingestion connectors feeding a warehouse table with sync lag, failure, and schema drift checks.',
    eligible: true,
    eligibleDomains: ['warehouse'],
    estimatedWatches: '1-3',
    estimatedMonitors: '6-18',
  },
  {
    key: 'bi_reliability',
    label: 'BI Reliability',
    description: 'End-to-end protection for a BI asset and its upstream data path.',
    eligible: true,
    eligibleDomains: ['bi'],
    estimatedWatches: '2',
    estimatedMonitors: '15-23',
  },
  {
    key: 'full_coverage',
    label: 'Full Coverage',
    description: 'Maximum monitoring coverage across your entire pipeline — data, orchestration, and BI layers.',
    eligible: true,
    eligibleDomains: ['warehouse', 'transform', 'bi', 'ingestion', 'orchestration'],
    estimatedWatches: '1',
    estimatedMonitors: '15-40',
  },
];

// GET /api/schedule/presets - List all presets
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    // Optionally filter eligibility by node domain
    const { searchParams } = new URL(request.url);
    const nodeDomain = searchParams.get('nodeDomain');

    const presets = PRESETS.map((p) => ({
      ...p,
      eligible: nodeDomain
        ? p.eligibleDomains.includes(nodeDomain) || p.eligibleDomains.length === 0
        : true,
    }));

    return NextResponse.json({ presets });
  } catch (error: any) {
    console.error('[Presets] List error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
