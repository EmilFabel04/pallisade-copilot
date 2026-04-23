/**
 * Credential resolution helpers.
 *
 * Single source of truth for resolving integration credentials.
 * Reads from the Integration table (preferred) with fallback to
 * legacy PipelineNode.config for backwards compatibility.
 */

import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ResolvedCredentials {
  credentials: Record<string, any>;
  toolType: string;
  integrationId: string | null;
  /** Where the credentials came from */
  source: 'integration' | 'legacy_node';
  /** Cached discovery data (tables, schemas) if present */
  cachedData?: Record<string, any> | null;
}

export interface ResolvedIntegration {
  id: string;
  name: string;
  type: string;
  layer: string;
  status: string;
  config: Record<string, any>;
  metadata: Record<string, any>;
}

// ---------------------------------------------------------------------------
// Field-name mapping (extracted from 3+ routes that duplicated this)
// ---------------------------------------------------------------------------

const INTEGRATION_LAYERS: Record<string, string> = {
  SNOWFLAKE: 'warehouse',
  BIGQUERY: 'warehouse',
  POSTGRES: 'warehouse',
  REDSHIFT: 'warehouse',
  SQLSERVER: 'warehouse',
  AZURE_SQL: 'warehouse',
  AZURE_SYNAPSE: 'warehouse',
  DATABRICKS: 'warehouse',
  FIVETRAN: 'ingestion',
  AIRBYTE: 'ingestion',
  STITCH: 'ingestion',
  DBT_CLOUD: 'transformation',
  DBT_CORE: 'transformation',
  AIRFLOW: 'orchestration',
  DAGSTER: 'orchestration',
  PREFECT: 'orchestration',
  N8N: 'orchestration',
  TABLEAU: 'reporting',
  LOOKER: 'reporting',
  POWERBI: 'reporting',
  METABASE: 'reporting',
  GITHUB: 'version_control',
  GITLAB: 'version_control',
  BITBUCKET: 'version_control',
  SLACK: 'alerts',
  PAGERDUTY: 'alerts',
  OPSGENIE: 'alerts',
  TEAMS: 'alerts',
  JIRA: 'alerts',
  LINUX_SERVER: 'infrastructure',
};

/**
 * Map frontend credential field names to what adapters/MCP servers expect.
 */
export function mapCredentialFields(
  toolType: string,
  credentials: Record<string, any>,
): Record<string, any> {
  const config = { ...credentials };
  const t = toolType.toUpperCase();

  // username -> user (Snowflake, Postgres, Redshift only — Airflow needs 'username' as-is)
  const usernameToUserTypes = ['SNOWFLAKE', 'POSTGRES', 'REDSHIFT'];
  if (usernameToUserTypes.includes(t) && config.username && !config.user) {
    config.user = config.username;
    delete config.username;
  }

  // server -> host (SQL Server variants)
  const serverToHostTypes = ['SQLSERVER', 'AZURE_SQL', 'AZURE_SYNAPSE'];
  if (serverToHostTypes.includes(t) && config.server && !config.host) {
    config.host = config.server;
    delete config.server;
  }

  // host -> base_url (Airflow, n8n)
  if ((t === 'AIRFLOW' || t === 'N8N') && config.host && !config.base_url) {
    config.base_url = config.host;
    delete config.host;
  }

  // base_url -> host (Looker — LookerClient expects 'host')
  if (t === 'LOOKER' && config.base_url && !config.host) {
    config.host = config.base_url;
    delete config.base_url;
  }

  return config;
}

// ---------------------------------------------------------------------------
// Decrypt helpers (same logic previously duplicated across routes)
// ---------------------------------------------------------------------------

interface RawConfig {
  encrypted?: string;
  _cached?: any;
  _autoDiscovered?: boolean;
  [key: string]: any;
}

/**
 * Decrypt a config blob (handles encrypted + legacy unencrypted formats).
 * Returns { credentials, cachedData }.
 */
function decryptConfig(
  config: any,
): { credentials: Record<string, any>; cachedData: Record<string, any> | null } {
  if (!config) return { credentials: {}, cachedData: null };

  try {
    const raw = config as RawConfig;
    const cachedData = raw._cached || null;

    if (raw.encrypted) {
      const decrypted = decrypt(raw.encrypted);
      return { credentials: JSON.parse(decrypted), cachedData };
    }

    // Legacy unencrypted — strip internal keys
    const { _cached, _autoDiscovered, ...creds } = raw;
    return { credentials: creds, cachedData };
  } catch (e) {
    console.error('[integration-credentials] Failed to decrypt config:', e);
    return { credentials: {}, cachedData: null };
  }
}

/**
 * Decrypt Integration.credentials field.
 */
function decryptIntegrationCredentials(
  credentials: any,
): Record<string, any> {
  if (!credentials) return {};

  try {
    const raw = credentials as RawConfig;

    if (raw.encrypted) {
      const decrypted = decrypt(raw.encrypted);
      return JSON.parse(decrypted);
    }

    // Legacy unencrypted
    return raw as Record<string, any>;
  } catch (e) {
    console.error('[integration-credentials] Failed to decrypt integration credentials:', e);
    return {};
  }
}

// ---------------------------------------------------------------------------
// resolveNodeCredentials
// ---------------------------------------------------------------------------

/**
 * Resolve credentials for a single pipeline node.
 *
 * Prefers Integration table (via integrationId FK). Falls back to
 * PipelineNode.config for legacy nodes that haven't been migrated.
 */
export async function resolveNodeCredentials(
  nodeId: string,
  stackId: string,
  organizationId: string,
): Promise<ResolvedCredentials | null> {
  const node = await prisma.pipelineNode.findFirst({
    where: {
      id: nodeId,
      stackId,
      stack: { organizationId },
    },
    include: {
      integration: true,
      stack: true,
    },
  });

  if (!node) return null;

  // Prefer Integration table
  if (node.integrationId && node.integration) {
    const credentials = decryptIntegrationCredentials(node.integration.credentials);
    return {
      credentials: mapCredentialFields(node.toolType, credentials),
      toolType: node.toolType,
      integrationId: node.integrationId,
      source: 'integration',
      cachedData: (node.config as any)?._cached || null,
    };
  }

  // Legacy fallback: read from PipelineNode.config
  const { credentials, cachedData } = decryptConfig(node.config);
  return {
    credentials: mapCredentialFields(node.toolType, credentials),
    toolType: node.toolType,
    integrationId: null,
    source: 'legacy_node',
    cachedData,
  };
}

// ---------------------------------------------------------------------------
// resolveStackIntegrations
// ---------------------------------------------------------------------------

/**
 * Resolve all integrations for a pipeline stack.
 *
 * Used by the copilot chat route to build the integrations array
 * that gets sent to the scanner/FastAPI backend.
 *
 * Deduplicates by type (first wins), merges OAuth tokens from
 * the Integration table, and applies field-name mappings.
 */
export async function resolveStackIntegrations(
  pipelineStackId: string | null,
  organizationId: string,
): Promise<ResolvedIntegration[]> {
  const integrations: ResolvedIntegration[] = [];
  const seenTypes = new Set<string>();

  // 1. Fetch pipeline nodes
  if (pipelineStackId) {
    const pipelineStack = await prisma.pipelineStack.findFirst({
      where: {
        organizationId,
        ...(pipelineStackId ? { id: pipelineStackId } : {}),
      },
      include: {
        nodes: {
          where: { status: { notIn: ['ERROR', 'TESTING'] } },
          include: { integration: true },
        },
      },
    });

    const validActiveStatuses = ['CONNECTED', 'HEALTHY', 'WARNING'];

    for (const node of pipelineStack?.nodes ?? []) {
      const toolType = node.toolType.toUpperCase();

      // Deduplicate by type (first wins)
      if (seenTypes.has(toolType)) {
        console.warn(
          `[integration-credentials] Duplicate ${toolType} node "${node.name}" — skipping (using first). Remove duplicates in Pipeline settings.`,
        );
        continue;
      }

      // Resolve credentials
      let config: Record<string, any>;
      if (node.integrationId && node.integration) {
        config = mapCredentialFields(
          toolType,
          decryptIntegrationCredentials(node.integration.credentials),
        );
        console.log(
          `[integration-credentials] Resolved ${node.name} (${toolType}) from Integration table, keys: ${Object.keys(config).join(', ')}`,
        );
      } else {
        // Legacy fallback
        const { credentials } = decryptConfig(node.config);
        config = mapCredentialFields(toolType, credentials);
        console.log(
          `[integration-credentials] Resolved ${node.name} (${toolType}) from legacy PipelineNode.config, keys: ${Object.keys(config).join(', ')}`,
        );
      }

      if (Object.keys(config).length === 0) continue;

      seenTypes.add(toolType);
      integrations.push({
        id: node.id,
        name: node.name,
        type: toolType,
        layer: node.layer.toLowerCase(),
        status: validActiveStatuses.includes(node.status) ? 'ACTIVE' : node.status,
        config,
        metadata: {},
      });
    }
  }

  // 2. Fetch OAuth / standalone integrations from Integration table
  const oauthIntegrations = await prisma.integration.findMany({
    where: { organizationId, status: 'ACTIVE' },
    select: {
      id: true,
      name: true,
      type: true,
      status: true,
      accessToken: true,
      metadata: true,
    },
  });

  for (const oauth of oauthIntegrations) {
    let accessToken = '';
    if (oauth.accessToken) {
      try {
        accessToken = decrypt(oauth.accessToken);
      } catch (e) {
        console.error(
          `[integration-credentials] Failed to decrypt token for ${oauth.name}:`,
          e,
        );
      }
    }

    const oauthType = oauth.type.toUpperCase();

    // If this type already exists (from pipeline nodes), merge the OAuth token
    const existing = integrations.find((i) => i.type === oauthType);
    if (existing) {
      console.log(
        `[integration-credentials] Merging OAuth token for ${oauthType} into existing pipeline node`,
      );
      existing.config = {
        ...existing.config,
        access_token: accessToken,
        token: accessToken,
      };
      existing.metadata = {
        ...existing.metadata,
        ...((oauth.metadata as Record<string, any>) || {}),
      };
      continue;
    }

    // Standalone OAuth integration (no matching pipeline node)
    if (!accessToken) continue;

    seenTypes.add(oauthType);
    integrations.push({
      id: oauth.id,
      name: oauth.name,
      type: oauthType,
      layer: INTEGRATION_LAYERS[oauthType] || 'version_control',
      status: 'ACTIVE',
      config: {
        access_token: accessToken,
        token: accessToken,
      },
      metadata: (oauth.metadata as Record<string, any>) || {},
    });
  }

  console.log(
    '[integration-credentials] Resolved integrations:',
    integrations.map((i) => ({
      name: i.name,
      type: i.type,
      status: i.status,
      configKeys: Object.keys(i.config),
    })),
  );

  return integrations;
}
