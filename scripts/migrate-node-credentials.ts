/**
 * One-time migration: Move credentials from PipelineNode.config to Integration table.
 *
 * For each PipelineNode that has credentials in config but no integrationId,
 * creates an Integration record and links it.
 *
 * Run: npx tsx scripts/migrate-node-credentials.ts
 *
 * Safe to run multiple times — skips nodes that already have an integrationId.
 */

import { PrismaClient } from '@prisma/client';
import crypto from 'crypto';

const prisma = new PrismaClient();

// --- Crypto helpers (mirror lib/crypto.ts) ---
const ALGORITHM = 'aes-256-gcm';
const IV_LENGTH = 16;
const AUTH_TAG_LENGTH = 16;

function getEncryptionKey(): Buffer {
  const key = process.env.ENCRYPTION_KEY;
  if (key) return Buffer.from(key, 'hex');
  console.warn('⚠️  Using development encryption key');
  return crypto.scryptSync('pallisade-dev-key', 'salt', 32);
}

function decrypt(encryptedData: string): string {
  const key = getEncryptionKey();
  const iv = Buffer.from(encryptedData.slice(0, IV_LENGTH * 2), 'hex');
  const authTag = Buffer.from(
    encryptedData.slice(IV_LENGTH * 2, IV_LENGTH * 2 + AUTH_TAG_LENGTH * 2),
    'hex',
  );
  const encrypted = encryptedData.slice(IV_LENGTH * 2 + AUTH_TAG_LENGTH * 2);
  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
  decipher.setAuthTag(authTag);
  let decrypted = decipher.update(encrypted, 'hex', 'utf8');
  decrypted += decipher.final('utf8');
  return decrypted;
}

function encrypt(text: string): string {
  const key = getEncryptionKey();
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);
  let encrypted = cipher.update(text, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  const authTag = cipher.getAuthTag();
  return iv.toString('hex') + authTag.toString('hex') + encrypted;
}

// --- Main migration ---

const NON_CREDENTIAL_KEYS = new Set(['_cached', '_autoDiscovered']);

async function main() {
  console.log('=== Migrate PipelineNode credentials to Integration table ===\n');

  // Find all nodes with config but no integrationId
  const nodes = await prisma.pipelineNode.findMany({
    where: {
      config: { not: null as any },
      integrationId: null,
    },
    include: {
      stack: { select: { organizationId: true } },
    },
  });

  console.log(`Found ${nodes.length} nodes to check.\n`);

  let migrated = 0;
  let skipped = 0;

  for (const node of nodes) {
    const orgId = node.stack?.organizationId;
    if (!orgId) {
      console.log(`  SKIP ${node.name} (${node.toolType}): no organizationId`);
      skipped++;
      continue;
    }

    // Decrypt config
    let credentials: Record<string, any> = {};
    let cachedData: any = null;
    try {
      const raw = node.config as any;
      cachedData = raw?._cached || null;

      if (raw?.encrypted) {
        credentials = JSON.parse(decrypt(raw.encrypted));
      } else if (raw) {
        const { _cached, _autoDiscovered, ...creds } = raw;
        credentials = creds;
      }
    } catch (e) {
      console.log(`  SKIP ${node.name} (${node.toolType}): decrypt failed — ${e}`);
      skipped++;
      continue;
    }

    // Skip if no real credentials
    const realKeys = Object.keys(credentials).filter((k) => !NON_CREDENTIAL_KEYS.has(k));
    if (realKeys.length === 0) {
      console.log(`  SKIP ${node.name} (${node.toolType}): no real credentials`);
      skipped++;
      continue;
    }

    // Create Integration record
    const integrationType = node.toolType.toUpperCase();
    const isActive = ['CONNECTED', 'HEALTHY', 'WARNING'].includes(node.status);

    try {
      const encryptedCreds = { encrypted: encrypt(JSON.stringify(credentials)) };
      const integration = await prisma.integration.upsert({
        where: {
          organizationId_type_name: {
            organizationId: orgId,
            type: integrationType as any,
            name: node.name,
          },
        },
        update: {
          credentials: encryptedCreds,
          status: isActive ? 'ACTIVE' : 'INACTIVE',
        },
        create: {
          name: node.name,
          type: integrationType as any,
          status: isActive ? 'ACTIVE' : 'INACTIVE',
          credentials: encryptedCreds,
          organizationId: orgId,
        },
      });

      // Link node to Integration and clear credentials from config
      await prisma.pipelineNode.update({
        where: { id: node.id },
        data: {
          integrationId: integration.id,
          config: cachedData ? { _cached: cachedData } : undefined,
        },
      });

      console.log(
        `  OK   ${node.name} (${integrationType}) → Integration ${integration.id} [${realKeys.join(', ')}]`,
      );
      migrated++;
    } catch (e) {
      console.error(`  FAIL ${node.name} (${integrationType}): ${e}`);
      skipped++;
    }
  }

  console.log(`\n=== Done: ${migrated} migrated, ${skipped} skipped ===`);
}

main()
  .catch((e) => {
    console.error('Migration failed:', e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
