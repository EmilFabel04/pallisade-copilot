import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import {
  MONITOR_CATALOG,
  getAvailableMonitors,
  groupMonitorsByCategory,
} from '@/types/monitor-catalog';

// Tool types that have a source_mode concept (live API vs static files)
const TOOLS_WITH_SOURCE_MODES: Record<string, { liveMode: string; label: string }> = {
  airflow: { liveMode: 'api', label: 'Airflow API' },
  dbt_core: { liveMode: 'api', label: 'dbt Cloud API' }, // dbt_core only has upload/project/github — none are live
};

function decryptConfig(config: any): Record<string, any> | null {
  if (!config) return null;
  try {
    if (config.encrypted) return JSON.parse(decrypt(config.encrypted));
    return config as Record<string, any>;
  } catch { return null; }
}

/**
 * Determine if a pipeline node has a live API connection (vs static files).
 * Returns { sourceMode, hasLiveConnection }.
 */
function getConnectionMode(toolType: string, config: any): { sourceMode: string | null; hasLiveConnection: boolean } {
  const spec = TOOLS_WITH_SOURCE_MODES[toolType.toLowerCase()];
  if (!spec) {
    // Tools without source_mode (fivetran, dbt_cloud, bigquery, etc.) are always "live"
    return { sourceMode: null, hasLiveConnection: true };
  }

  const decrypted = decryptConfig(config);
  if (!decrypted) return { sourceMode: null, hasLiveConnection: false };

  const sourceMode = decrypted.source_mode || null;

  // Airflow: live if source_mode=api or has a host/base_url
  if (toolType.toLowerCase() === 'airflow') {
    const hasHost = !!(decrypted.host || decrypted.base_url);
    const isLive = sourceMode === 'api' || (hasHost && sourceMode !== 'github');
    return { sourceMode, hasLiveConnection: isLive };
  }

  // dbt_core: none of the source modes (upload/project/github) are live API
  if (toolType.toLowerCase() === 'dbt_core') {
    return { sourceMode, hasLiveConnection: false };
  }

  return { sourceMode, hasLiveConnection: spec.liveMode === sourceMode };
}

// GET /api/schedule/monitor-catalog?stackId=...
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const stackId = searchParams.get('stackId');

    if (!stackId) {
      return NextResponse.json({
        catalog: MONITOR_CATALOG,
        available: [],
        grouped: [],
        connectedToolTypes: [],
        integrationNodes: [],
      });
    }

    // Fetch connected pipeline nodes for this stack
    // Include integration credentials (not PipelineNode.config) for source_mode detection,
    // because the real config is stored in the Integration table after save.
    const nodes = await prisma.pipelineNode.findMany({
      where: {
        stackId,
        status: { in: ['CONNECTED', 'HEALTHY', 'WARNING'] },
      },
      select: {
        id: true,
        name: true,
        toolType: true,
        layer: true,
        integrationId: true,
        config: true,
        integration: {
          select: { credentials: true },
        },
      },
    });

    const connectedToolTypes = [...new Set(nodes.map((n) => n.toolType))];
    const available = getAvailableMonitors(connectedToolTypes);
    const grouped = groupMonitorsByCategory(available);

    return NextResponse.json({
      catalog: MONITOR_CATALOG,
      available,
      grouped,
      connectedToolTypes,
      integrationNodes: nodes.map((n) => {
        // Prefer Integration credentials (where the real config lives after save),
        // fall back to PipelineNode.config for legacy/unsaved nodes
        const configSource = n.integration?.credentials || n.config;
        const { sourceMode, hasLiveConnection } = getConnectionMode(n.toolType, configSource);
        return {
          id: n.id,
          name: n.name,
          toolType: n.toolType,
          layer: n.layer,
          integrationId: n.integrationId,
          sourceMode,
          hasLiveConnection,
        };
      }),
    });
  } catch (error: any) {
    console.error('[MonitorCatalog] Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
