import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

/**
 * Resolve warehouse credentials from the Integration table.
 * Finds the PipelineNode for the given stack + platform (e.g. "bigquery"),
 * then decrypts credentials from its linked Integration.
 */
export async function resolveWarehouseCredentials(
  userEmail: string,
  stackId: string,
  platform: string
): Promise<Record<string, any> | null> {
  const user = await prisma.user.findUnique({
    where: { email: userEmail },
    select: { organizationId: true },
  });
  if (!user?.organizationId) return null;

  // Find the warehouse PipelineNode matching this platform
  const pipelineNode = await prisma.pipelineNode.findFirst({
    where: {
      stackId,
      toolType: platform.toLowerCase(),
      stack: { organizationId: user.organizationId },
    },
    include: { integration: true },
  });

  if (!pipelineNode) return null;

  // Resolve credentials — prefer Integration, fall back to PipelineNode.config
  if ((pipelineNode as any).integrationId && (pipelineNode as any).integration?.credentials) {
    try {
      const intCreds = (pipelineNode as any).integration.credentials as any;
      if (intCreds.encrypted) {
        return JSON.parse(decrypt(intCreds.encrypted));
      }
      return intCreds;
    } catch (e) {
      console.error('[Discovery] Integration credentials parsing failed:', e);
    }
  }

  if (pipelineNode.config) {
    try {
      const configJson = pipelineNode.config as { encrypted?: string; _cached?: any; [key: string]: any };
      if (configJson.encrypted) {
        return JSON.parse(decrypt(configJson.encrypted));
      }
      const { _cached, ...creds } = configJson;
      return creds;
    } catch (e) {
      console.error('[Discovery] Config credentials parsing failed:', e);
    }
  }

  return null;
}

export async function resolveOrganizationId(userEmail: string): Promise<string | undefined> {
  const userRow = await prisma.user.findUnique({
    where: { email: userEmail },
    select: { organizationId: true },
  });
  return userRow?.organizationId ?? undefined;
}

/**
 * Look up prior clarification answers for the given (stack, table) pair so a
 * second discovery run doesn't re-ask the same questions. Returns a flat dict
 * keyed by clarification kind — e.g. {timestamp_choice: {column: "loaded_at"}}.
 *
 * Currently scoped to `timestamp_choice` because that's the only kind discovery
 * emits today. Add other kinds here when they're introduced.
 */
export async function findPriorAnswers(
  stackId: string,
  tableFqn: string,
): Promise<Record<string, Record<string, unknown>>> {
  const answered = await prisma.contextRequest.findMany({
    where: {
      pipelineStackId: stackId,
      scopeRef: tableFqn,
      status: 'answered',
      kind: { in: ['timestamp_choice'] },
    },
    orderBy: { resolvedAt: 'desc' },
    select: {
      kind: true,
      resolution: { select: { answer: true } },
    },
  });

  const byKind: Record<string, Record<string, unknown>> = {};
  for (const row of answered) {
    if (byKind[row.kind]) continue; // first (most recent) wins
    const ans = row.resolution?.answer as Record<string, unknown> | null | undefined;
    if (ans) byKind[row.kind] = ans;
  }
  return byKind;
}
