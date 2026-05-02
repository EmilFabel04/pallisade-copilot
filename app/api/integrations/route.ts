import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { encrypt, decrypt } from '@/lib/crypto';
import { resolveEffectiveSLA } from '@/lib/contracts/resolver';
import { PipelineSLAData, NodeSLAWithOverrides } from '@/components/contracts/types';
import { notifyEvents } from '@/lib/notifications';
import { validateVerifyToken, computeConfigHash } from '@/lib/server/verify-token';
import { scannerClient } from '@/lib/scanner-client';

// GET /api/integrations - List all integrations for the user's organization
// Now includes both legacy Integrations AND Pipeline nodes for compatibility
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ integrations: [], pipelineNodes: [] });
    }

    // Optional: filter by stackId if provided
    const stackId = request.nextUrl.searchParams.get('stackId');

    // Fetch integrations — when stackId is provided, only return integrations
    // that either: (a) are linked to a node in that stack, or
    // (b) have NO pipeline nodes at all (standalone OAuth like Slack, GitHub)
    const integrationWhere: any = { organizationId: user.organizationId };
    if (stackId) {
      integrationWhere.OR = [
        { pipelineNodes: { some: { stackId } } },
        { pipelineNodes: { none: {} } },
      ];
    }

    const legacyIntegrations = await prisma.integration.findMany({
      where: integrationWhere,
      select: {
        id: true,
        name: true,
        type: true,
        status: true,
        connectionInfo: true,
        lastSyncAt: true,
        lastTestAt: true,
        lastError: true,
        healthScore: true,
        scanCount: true,
        lastScanAt: true,
        config: true,
        tokenExpiry: true,
        lastExtractedAt: true,
        lastLineageExtractedAt: true,
        lastSchemaExtractedAt: true,
        lastLogsExtractedAt: true,
        createdAt: true,
        updatedAt: true,
        pipelineNodes: { select: { id: true } },
        sourceContract: true,
      },
      orderBy: { createdAt: 'desc' },
    });

    // Fetch Pipeline nodes (new approach)
    const pipelineNodes = await prisma.pipelineNode.findMany({
      where: {
        stack: { organizationId: user.organizationId },
        ...(stackId ? { stackId } : {}),
      },
      select: {
        id: true,
        name: true,
        layer: true,
        toolType: true,
        status: true,
        lastTestedAt: true,
        lastError: true,
        healthScore: true,
        lastScanAt: true,
        findingsCount: true,
        criticalCount: true,
        highCount: true,
        createdAt: true,
        updatedAt: true,
        stackId: true,
        config: true,
        integrationId: true,
        integration: {
          select: {
            tokenExpiry: true,
            config: true,
            lastExtractedAt: true,
            lastLineageExtractedAt: true,
            lastSchemaExtractedAt: true,
            lastLogsExtractedAt: true,
            sourceContract: {
              select: {
                slaTier: true,
                expectedFreshnessMinutes: true,
                expectedExtractionFrequencyMinutes: true,
                notes: true,
                inheritFromPipeline: true,
                pipelineStackId: true,
                overridesJson: true,
              },
            },
          },
        },
      },
      orderBy: { createdAt: 'desc' },
    });

    // ── Enrich with monitor health + scan extraction data ──

    // Batch-fetch monitor statuses for all linked integrations
    const allIntegrationIds = [
      ...pipelineNodes.map(n => n.integrationId).filter(Boolean) as string[],
      ...legacyIntegrations.map(i => i.id),
    ];

    const [monitors, latestScans] = await Promise.all([
      // Fetch enabled monitors for this org (not just those with integrationId)
      // so we can match by targetFqn pattern too. When a stackId is supplied,
      // scope to monitors that belong to that pipeline profile so the per-
      // integration count overlay reflects only the active profile (per
      // finding+monitor isolation spec). Integrations themselves stay
      // org-shared, but their count overlay is profile-scoped.
      prisma.monitor.findMany({
        where: {
          organizationId: user.organizationId,
          enabled: true,
          lastRunAt: { not: null },
          ...(stackId ? { pipelineStackId: stackId } : {}),
        },
        select: {
          integrationId: true,
          monitorType: true,
          targetFqn: true,
          lastRunAt: true,
          lastStatus: true,
        },
      }),
      // Latest completed scan per stack
      (() => {
        const stackIds = [...new Set(pipelineNodes.map(n => n.stackId))];
        return stackIds.length > 0
          ? prisma.pipelineScan.findMany({
              where: { stackId: { in: stackIds }, status: 'COMPLETED' },
              orderBy: { completedAt: 'desc' },
              distinct: ['stackId'],
              select: { stackId: true, completedAt: true, healthScore: true },
            })
          : Promise.resolve([]);
      })(),
    ]);

    // Build monitor health lookup: integrationId → { health, latestRunAt, counts }
    // Also build a secondary lookup by monitorType layer for monitors without integrationId
    type MonitorAgg = { health: number; latestRunAt: string; total: number; passing: number; failing: number; warning: number };
    const monitorMap = new Map<string, MonitorAgg>();

    // Group monitors by integrationId first
    const monitorGrouped = new Map<string, Array<{ lastStatus: string | null; lastRunAt: Date }>>();
    // Monitors without integrationId — group by monitorType for layer-based matching
    const MONITOR_TYPE_TO_LAYER: Record<string, string> = {
      SERVER_HEALTH: 'INFRASTRUCTURE', CERTIFICATE: 'INFRASTRUCTURE', LOG_ANALYSIS: 'INFRASTRUCTURE',
      FAILED_SYNCS: 'INGESTION', SYNC_LAG: 'INGESTION', CONNECTOR_SCHEMA_DRIFT: 'INGESTION',
      DAG_LAST_RUN: 'ORCHESTRATION', DAG_SCHEDULE_LAG: 'ORCHESTRATION', TASK_FAILURE_RATE: 'ORCHESTRATION',
      DBT_TEST_FAILURES: 'TRANSFORMATION', DBT_MODEL_FRESHNESS: 'TRANSFORMATION', DBT_SOURCE_FRESHNESS: 'TRANSFORMATION',
      FRESHNESS: 'WAREHOUSE', VOLUME: 'WAREHOUSE', SCHEMA_CHANGE: 'WAREHOUSE',
      NULL_CHECK: 'WAREHOUSE', REFERENTIAL: 'WAREHOUSE', CUSTOM_SQL: 'WAREHOUSE',
    };
    const monitorsByLayer = new Map<string, Array<{ lastStatus: string | null; lastRunAt: Date }>>();

    for (const m of monitors) {
      if (m.integrationId) {
        if (!monitorGrouped.has(m.integrationId)) monitorGrouped.set(m.integrationId, []);
        monitorGrouped.get(m.integrationId)!.push({ lastStatus: m.lastStatus, lastRunAt: m.lastRunAt! });
      } else if (m.monitorType) {
        // Match unlinked monitors to layers by monitorType
        const layer = MONITOR_TYPE_TO_LAYER[m.monitorType] || '';
        if (layer) {
          if (!monitorsByLayer.has(layer)) monitorsByLayer.set(layer, []);
          monitorsByLayer.get(layer)!.push({ lastStatus: m.lastStatus, lastRunAt: m.lastRunAt! });
        }
      }
    }

    function aggregateMonitors(mons: Array<{ lastStatus: string | null; lastRunAt: Date }>): MonitorAgg {
      let score = 0, latestRun = new Date(0);
      let passing = 0, failing = 0, warning = 0;
      for (const m of mons) {
        switch (m.lastStatus) {
          case 'PASS': score += 100; passing++; break;
          case 'WARN': score += 60; warning++; break;
          case 'FAIL': score += 20; failing++; break;
          case 'ERROR': score += 0; failing++; break;
          default: score += 50;
        }
        if (m.lastRunAt > latestRun) latestRun = m.lastRunAt;
      }
      return { health: Math.round(score / mons.length), latestRunAt: latestRun.toISOString(), total: mons.length, passing, failing, warning };
    }

    for (const [intId, mons] of monitorGrouped) {
      monitorMap.set(intId, aggregateMonitors(mons));
    }

    // Build layer-based monitor aggregation map
    const layerMonitorMap = new Map<string, MonitorAgg>();
    for (const [layer, mons] of monitorsByLayer) {
      layerMonitorMap.set(layer, aggregateMonitors(mons));
    }

    // Build scan lookup: stackId → { completedAt, healthScore }
    const scanMap = new Map<string, { completedAt: string; healthScore: number | null }>();
    for (const s of latestScans) {
      if (s.completedAt) {
        scanMap.set(s.stackId, {
          completedAt: s.completedAt.toISOString(),
          healthScore: s.healthScore,
        });
      }
    }

    // Include all pipeline nodes as sources
    const dataNodes = pipelineNodes;

    // Map pipeline nodes to integration-like format with enriched health/extraction
    const pipelineAsIntegrations = dataNodes.map(node => {
      const intId = node.integrationId;
      // Try integrationId-based monitors first, then fall back to layer-based
      const monitorData = (intId ? monitorMap.get(intId) : null) || layerMonitorMap.get(node.layer) || null;
      const scanData = scanMap.get(node.stackId);

      // Health fallback chain: node scan → monitors → stack scan → findings-derived
      const healthScore = node.healthScore
        ?? monitorData?.health
        ?? scanData?.healthScore
        ?? deriveFindingsHealth(node.findingsCount, node.criticalCount, node.highCount);

      // Extraction fallback: integration → node scan → stack scan
      const integ = (node as any).integration;
      const lastExtractedAt = integ?.lastExtractedAt
        ?? node.lastScanAt?.toISOString()
        ?? scanData?.completedAt
        ?? null;

      // Last tested fallback: node → monitor latest run
      const lastTestedAt = node.lastTestedAt
        ?? (monitorData ? new Date(monitorData.latestRunAt) : null);

      // Schema extraction fallback: integration → node scan
      const lastSchemaExtractedAt = integ?.lastSchemaExtractedAt
        ?? node.lastScanAt?.toISOString()
        ?? null;

      return {
        id: node.id,
        name: node.name,
        type: mapToolTypeToIntegrationType(node.toolType),
        status: mapPipelineStatus(node.status),
        connectionInfo: `Pipeline: ${node.layer.toLowerCase()}`,
        lastSyncAt: null,
        lastTestAt: lastTestedAt,
        lastError: node.lastError,
        healthScore,
        scanCount: null,
        lastScanAt: node.lastScanAt,
        config: integ?.config || (node as any).config || null,
        tokenExpiry: integ?.tokenExpiry || null,
        lastExtractedAt,
        lastLineageExtractedAt: integ?.lastLineageExtractedAt || null,
        lastSchemaExtractedAt,
        lastLogsExtractedAt: integ?.lastLogsExtractedAt || null,
        sourceContract: integ?.sourceContract || null,
        createdAt: node.createdAt,
        updatedAt: node.updatedAt,
        // Monitor aggregates
        monitorCount: monitorData?.total ?? 0,
        monitorPassing: monitorData?.passing ?? 0,
        monitorFailing: monitorData?.failing ?? 0,
        monitorWarning: monitorData?.warning ?? 0,
        // Extra fields to identify source
        source: 'pipeline' as const,
        layer: node.layer,
        stackId: node.stackId,
        findingsCount: node.findingsCount,
        criticalCount: node.criticalCount || 0,
        highCount: node.highCount || 0,
      };
    });

    // Combine both sources, with Pipeline nodes first.
    // Deduplicate: if a PipelineNode exists for a type, skip the legacy Integration
    // to prevent duplicate connector cards and duplicate auto-discovery records.
    const pipelineTypes = new Set(pipelineAsIntegrations.map(p => p.type));
    // Infer layer from legacy integration type for monitor matching
    const LEGACY_TYPE_TO_LAYER: Record<string, string> = {
      BIGQUERY: 'WAREHOUSE', SNOWFLAKE: 'WAREHOUSE', POSTGRES: 'WAREHOUSE', REDSHIFT: 'WAREHOUSE',
      DBT_CLOUD: 'TRANSFORMATION', DBT_CORE: 'TRANSFORMATION',
      FIVETRAN: 'INGESTION', AIRBYTE: 'INGESTION', STITCH: 'INGESTION',
      LOOKER: 'REPORTING', TABLEAU: 'REPORTING', POWERBI: 'REPORTING', METABASE: 'REPORTING',
      AIRFLOW: 'ORCHESTRATION', DAGSTER: 'ORCHESTRATION', PREFECT: 'ORCHESTRATION',
      GITHUB: 'VERSION_CONTROL', GITLAB: 'VERSION_CONTROL',
      LINUX_SERVER: 'INFRASTRUCTURE',
      SLACK: 'NOTIFICATIONS', PAGERDUTY: 'NOTIFICATIONS', JIRA: 'NOTIFICATIONS',
    };

    const dedupedLegacy = legacyIntegrations
      .filter(i => !pipelineTypes.has(i.type))
      .map(i => {
        // Enrich legacy integrations with monitor health
        const monitorData = monitorMap.get(i.id);
        const inferredLayer = LEGACY_TYPE_TO_LAYER[i.type] || 'WAREHOUSE';
        const layerMonitorData = !monitorData ? layerMonitorMap.get(inferredLayer) : null;
        const effectiveMonitorData = monitorData || layerMonitorData || null;
        const enrichedHealthScore = i.healthScore ?? effectiveMonitorData?.health ?? null;
        const enrichedLastTestAt = i.lastTestAt ?? (effectiveMonitorData ? new Date(effectiveMonitorData.latestRunAt) : null);
        return {
          ...i,
          healthScore: enrichedHealthScore,
          lastTestAt: enrichedLastTestAt,
          monitorCount: effectiveMonitorData?.total ?? 0,
          monitorPassing: effectiveMonitorData?.passing ?? 0,
          monitorFailing: effectiveMonitorData?.failing ?? 0,
          monitorWarning: effectiveMonitorData?.warning ?? 0,
          layer: inferredLayer,
          source: 'legacy' as const,
          managedByPipeline: (i.pipelineNodes?.length || 0) > 0,
        };
      });
    const allIntegrations = [...pipelineAsIntegrations, ...dedupedLegacy];

    // Fetch pipeline contract if stackId provided, for effective contract resolution
    let pipelineContractData: PipelineSLAData | null = null;
    if (stackId) {
      try {
        const pc = await prisma.pipelineContract.findUnique({
          where: { pipelineStackId: stackId },
        });
        if (pc) {
          pipelineContractData = {
            slaTier: pc.slaTier as any,
            expectedFreshnessMinutes: pc.expectedFreshnessMinutes,
            expectedExtractionFrequencyMinutes: pc.expectedExtractionFrequencyMinutes,
            alertPolicyJson: pc.alertPolicyJson as any,
            notes: pc.notes,
          };
        }
      } catch (err) {
        console.error('Error fetching pipeline contract:', err);
      }
    }

    // For data asset tools (WAREHOUSE, TRANSFORMATION), aggregate SLA from child
    // PolicyAssignment records instead of using the tool-level SourceContract.
    // This gives a representative SLA for the tool's data assets.
    const DATA_ASSET_LAYERS = new Set(['WAREHOUSE', 'TRANSFORMATION']);
    let childSLAMap = new Map<string, { slaTier: string; freshnessMinutes: number | null; extractionMinutes: number | null }>();

    if (stackId) {
      try {
        // Get all direct policy assignments for nodes in this stack
        const assignments = await prisma.policyAssignment.findMany({
          where: {
            assignmentType: 'direct',
            profile: { organizationId: user.organizationId },
          },
          select: {
            nodeFqn: true,
            profile: {
              select: {
                criticality: true,
                freshnessConfig: true,
                ingestionConfig: true,
              },
            },
          },
        });

        // Map FQN → SLA tier (from criticality)
        const tierOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
        const tierToLabel: Record<string, string> = { critical: 'T0', high: 'T1', medium: 'T2', low: 'T3' };

        // Group assignments by integration via PipelineNode linkage
        const fqnToAssignment = new Map(assignments.filter(a => a.nodeFqn).map(a => [a.nodeFqn!, a]));

        // Get pipeline nodes to map FQN → integrationId
        for (const node of dataNodes) {
          if (!DATA_ASSET_LAYERS.has(node.layer) || !node.integrationId) continue;

          // Check if any assignment matches this node's name pattern
          for (const [fqn, assignment] of fqnToAssignment) {
            const fqnParts = fqn.split('.');
            const nodeName = fqnParts[fqnParts.length - 1];
            if (nodeName !== node.name && !fqn.includes(node.name)) continue;

            const criticality = (assignment.profile.criticality || 'medium').toLowerCase();
            const tier = tierToLabel[criticality] || 'T2';
            const existing = childSLAMap.get(node.integrationId);

            // Keep the most critical tier (lowest T number)
            if (!existing || tierOrder[criticality] < tierOrder[existing.slaTier.toLowerCase().replace('t', '')] || 0) {
              const fc = assignment.profile.freshnessConfig as Record<string, unknown> | null;
              const ic = assignment.profile.ingestionConfig as Record<string, unknown> | null;
              childSLAMap.set(node.integrationId, {
                slaTier: tier,
                freshnessMinutes: fc?.maxHours != null ? Math.round(Number(fc.maxHours) * 60) : null,
                extractionMinutes: ic?.syncLagToleranceMinutes != null ? Number(ic.syncLagToleranceMinutes) : null,
              });
            }
          }
        }
      } catch (err) {
        console.error('Error aggregating child SLAs:', err);
      }
    }

    // Compute effective contract for each integration
    const integrationsWithEffective = allIntegrations.map(integration => {
      try {
        let sc = integration.sourceContract as NodeSLAWithOverrides | null;
        const intType = integration.type || '';

        // Discard stale SourceContracts that were created by old auto-sync
        // (inheritFromPipeline=true means it was blindly copied from pipeline,
        //  not derived from actual child asset SLA assignments)
        if (sc?.inheritFromPipeline) {
          sc = null;
        }

        // For data asset tools, use aggregated child SLA if available
        const layer = (integration as any).layer;
        if (DATA_ASSET_LAYERS.has(layer)) {
          const aggregated = childSLAMap.get(integration.id);
          if (aggregated) {
            sc = {
              notes: sc?.notes ?? null,
              slaTier: aggregated.slaTier,
              expectedFreshnessMinutes: aggregated.freshnessMinutes ?? null,
              expectedExtractionFrequencyMinutes: aggregated.extractionMinutes ?? null,
              inheritFromPipeline: false,
              pipelineStackId: null,
              overridesJson: null,
            } as NodeSLAWithOverrides;
          }
        }

        const effective = resolveEffectiveSLA(pipelineContractData, sc, intType);
        return {
          ...integration,
          sourceContract: sc,
          effectiveContract: effective,
          inheritanceState: effective.inheritanceState,
        };
      } catch (err) {
        console.error('Error resolving contract for integration:', integration.id, err);
        return {
          ...integration,
          effectiveContract: null,
          inheritanceState: null,
        };
      }
    });

    return NextResponse.json({
      integrations: integrationsWithEffective,
      pipelineContract: pipelineContractData,
      // Also provide separate access for modern consumers
      pipelineNodes,
      legacyIntegrations,
    });
  } catch (error) {
    console.error('Error fetching integrations:', error);
    return NextResponse.json({ error: 'Failed to fetch integrations' }, { status: 500 });
  }
}

// Derive health score from findings when no other health data is available
function deriveFindingsHealth(findings: number, critical: number, high: number): number | null {
  if (findings === 0 && critical === 0 && high === 0) return null;
  return Math.max(0, 100 - (critical * 20) - (high * 10));
}

// Map pipeline tool types to integration types
function mapToolTypeToIntegrationType(toolType: string): string {
  const map: Record<string, string> = {
    'snowflake': 'SNOWFLAKE',
    'bigquery': 'BIGQUERY',
    'redshift': 'REDSHIFT',
    'postgres': 'POSTGRES',
    'sqlserver': 'SQLSERVER',
    'azure_sql': 'AZURE_SQL',
    'fivetran': 'FIVETRAN',
    'airbyte': 'AIRBYTE',
    'stitch': 'STITCH',
    'dbt_cloud': 'DBT_CLOUD',
    'dbt_core': 'DBT_CORE',
    'airflow': 'AIRFLOW',
    'dagster': 'DAGSTER',
    'n8n': 'N8N',
    'looker': 'LOOKER',
    'tableau': 'TABLEAU',
    'powerbi': 'POWERBI',
    'metabase': 'METABASE',
    'databricks': 'DATABRICKS',
    'amazon_s3': 'AMAZON_S3',
    'gcs': 'GCS',
    'adls': 'ADLS',
  };
  return map[toolType] || toolType.toUpperCase();
}

// Map pipeline node status to integration status
function mapPipelineStatus(status: string): string {
  const map: Record<string, string> = {
    'CONNECTED': 'ACTIVE',
    'HEALTHY': 'ACTIVE',
    'WARNING': 'ACTIVE',
    'ERROR': 'ERROR',
    'FAILED': 'ERROR',
    'PENDING': 'INACTIVE',
    'TESTING': 'TESTING',
  };
  return map[status] || 'INACTIVE';
}

// POST /api/integrations - Create a new integration
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      include: { organization: true },
    });

    if (!user) {
      return NextResponse.json({ error: 'User not found' }, { status: 404 });
    }

    // Create organization if user doesn't have one
    let organizationId = user.organizationId;
    if (!organizationId) {
      const org = await prisma.organization.create({
        data: {
          name: `${user.name || user.email}'s Organization`,
          users: { connect: { id: user.id } },
        },
      });
      organizationId = org.id;
    }

    const body = await request.json();
    const { type, name, credentials, config, probeSchedule, activate } = body;

    if (!type || !name) {
      return NextResponse.json({ error: 'Type and name are required' }, { status: 400 });
    }

    if (type === 'CUSTOM_SOURCE' &&
        process.env.NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY !== 'true') {
      return NextResponse.json({ error: 'CUSTOM_SOURCE not enabled' }, { status: 404 });
    }

    // ── CUSTOM_SOURCE server-side verify gate ────────────────────────────────
    // An integration row that exists in the DB is, by construction, working.
    // For CUSTOM_SOURCE, this invariant is enforced here: we require a valid
    // verify_token issued by FastAPI after a successful all-pass probe run.
    if (type === 'CUSTOM_SOURCE') {
      const verifyToken: string | undefined = body.verify_token;
      if (!verifyToken) {
        return NextResponse.json(
          { error: 'verify_token required for CUSTOM_SOURCE' },
          { status: 400 },
        );
      }

      // The config hash must be computed over the same config that was verified.
      // We hash body.config (the same shape the wizard sends to /verify as the
      // body minus non-config keys like name, schedule, stack_id).
      // Note: config_hash is compared against what FastAPI hashed from the full
      // VerifyRequest body, so we hash body.config here using the same canonical
      // algorithm that verify_token.py uses on the Python side.
      const configHashInput = body.config ?? {};
      const expectedConfigHash = computeConfigHash(configHashInput);

      if (!organizationId) {
        return NextResponse.json({ error: 'Organization not found' }, { status: 400 });
      }

      const { valid, reason } = validateVerifyToken(verifyToken, organizationId, expectedConfigHash);
      if (!valid) {
        return NextResponse.json(
          { error: `verify_token validation failed: ${reason}` },
          { status: 400 },
        );
      }

      // Resolve the stash ref to the durable secret value.
      // The wizard stores the raw secret transiently in the stash; we resolve it
      // here so the persisted Integration config carries the real credential.
      const secretRef: string | undefined = body.config?.auth?.secret_ref;
      if (secretRef) {
        try {
          const resolveResp = await scannerClient.fetch(
            session,
            '/api/v1/integrations/source/resolve-secret',
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ secret_ref: secretRef }),
            },
          );
          if (!resolveResp.ok) {
            const errBody = await resolveResp.json().catch(() => ({}));
            return NextResponse.json(
              {
                error:
                  (errBody as any).detail ||
                  (errBody as any).error ||
                  'Failed to resolve credentials — they may have expired. Re-run the wizard.',
              },
              { status: 400 },
            );
          }
          const { secret } = await resolveResp.json();
          // Strip both the stash ref and any raw secret from the persisted config
          // so that Integration.config never contains plaintext credentials.
          // The raw secret goes ONLY into the encrypted credentials column below.
          const { secret_ref: _ref, secret: _existingSecret, ...nonSecretAuth } = body.config?.auth ?? {};
          body.config = {
            ...body.config,
            auth: nonSecretAuth,  // auth shape minus all credential fields
          };
          // Store the durable secret in the encrypted credentials column only.
          // probe_runner.py:_resolve_secret sources it from here, NOT config.auth.
          body.credentials = { secret };
        } catch {
          return NextResponse.json(
            { error: 'Failed to reach scanner to resolve credentials — try again' },
            { status: 502 },
          );
        }
      }
    }

    // Use body.credentials and body.config directly so CUSTOM_SOURCE can mutate them
    // above (resolve-secret path) and have those changes picked up here.
    const effectiveCredentials = body.credentials ?? null;
    const effectiveConfig = body.config ?? null;

    // Encrypt credentials before storing
    const encryptedCredentials = effectiveCredentials ? encrypt(JSON.stringify(effectiveCredentials)) : null;

    // Generate connection info for display
    const connectionInfo = generateConnectionInfo(type, effectiveCredentials, effectiveConfig);

    // For CUSTOM_SOURCE, populate probe scheduling so the runner picks it up.
    // The wizard sends `probeSchedule` (one of "hourly" | "every_6h" | "daily" |
    // "weekly") and `activate=true`. Without nextProbeAt + ACTIVE status, the
    // probe runner's WHERE clause filters the row out forever.
    const isCustomSource = type === 'CUSTOM_SOURCE';
    const integration = await prisma.integration.create({
      data: {
        type,
        name,
        credentials: encryptedCredentials ? { encrypted: encryptedCredentials } : undefined,
        config: effectiveConfig,
        connectionInfo,
        status: isCustomSource && activate ? 'ACTIVE' : 'INACTIVE',
        organizationId,
        ...(isCustomSource && probeSchedule
          ? {
              probeSchedule,
              // Run the first probe on the next scheduler tick (now).
              nextProbeAt: new Date(),
            }
          : {}),
      },
    });

    // Fire-and-forget notification
    notifyEvents.integrationCreated(
      organizationId!, undefined, user.id, name, type, integration.id,
    );

    return NextResponse.json({
      integration: {
        id: integration.id,
        name: integration.name,
        type: integration.type,
        status: integration.status,
        connectionInfo: integration.connectionInfo,
        createdAt: integration.createdAt,
      },
    });
  } catch (error: any) {
    console.error('Error creating integration:', error);
    if (error.code === 'P2002') {
      return NextResponse.json({ error: 'An integration with this name already exists' }, { status: 409 });
    }
    return NextResponse.json({ error: 'Failed to create integration' }, { status: 500 });
  }
}

// Helper to generate human-readable connection info
function generateConnectionInfo(type: string, credentials: any, config: any): string {
  if (!credentials && !config) return '';

  switch (type) {
    case 'SNOWFLAKE':
      return `${credentials?.account || 'account'}.snowflakecomputing.com / ${credentials?.database || 'database'}`;
    case 'BIGQUERY':
      return `Project: ${credentials?.project_id || config?.project_id || 'unknown'}`;
    case 'REDSHIFT':
      return `${credentials?.host || 'cluster'} / ${credentials?.database || 'database'}`;
    case 'DATABRICKS':
      return `${credentials?.host || 'workspace'} / ${credentials?.catalog || 'hive_metastore'}`;
    case 'AMAZON_S3':
      return `S3: ${credentials?.bucket || 'all buckets'} (${credentials?.region || 'us-east-1'})`;
    case 'GCS':
      return `GCS: ${credentials?.project_id || 'project'} / ${credentials?.bucket || 'all buckets'}`;
    case 'ADLS':
      return `ADLS: ${credentials?.account_name || 'account'} / ${credentials?.container || 'all containers'}`;
    case 'POSTGRES':
    case 'MYSQL':
      return `${credentials?.host || 'localhost'}:${credentials?.port || '5432'} / ${credentials?.database || 'database'}`;
    case 'GITHUB':
      return config?.repos ? `${config.repos.length} repositories` : 'All accessible repos';
    case 'GITLAB':
      return config?.groups ? `${config.groups.length} groups` : 'All accessible projects';
    case 'DBT_CLOUD':
      return `Account: ${credentials?.account_id || config?.account_id || 'unknown'}`;
    case 'AIRFLOW':
      return credentials?.base_url || config?.base_url || 'Airflow instance';
    case 'PREFECT':
      return `Workspace: ${config?.workspace || 'default'}`;
    case 'SLACK':
      return config?.channel ? `#${config.channel}` : 'Slack workspace';
    case 'PAGERDUTY':
      return config?.service ? `Service: ${config.service}` : 'PagerDuty service';
    case 'JIRA':
      return `${credentials?.domain || config?.domain || 'atlassian'}.atlassian.net`;
    case 'LINEAR':
      return config?.team ? `Team: ${config.team}` : 'Linear workspace';
    default:
      return '';
  }
}

